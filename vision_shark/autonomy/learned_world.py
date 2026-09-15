from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

from .camera_geometry import GEOMETRY_VECTOR_DIM


@dataclass(frozen=True)
class WorldModelConfig:
    camera_count: int = 6
    image_channels: int = 3
    ego_state_dim: int = 8
    hidden_dim: int = 128
    temporal_layers: int = 1
    bev_height: int = 32
    bev_width: int = 32
    future_steps: int = 10
    future_dt_s: float = 0.2
    trajectory_modes: int = 6
    max_agents: int = 32
    agent_state_dim: int = 4
    camera_geometry_dim: int = GEOMETRY_VECTOR_DIM
    use_camera_geometry: bool = False

    def validate(self) -> None:
        integer_fields = {
            "camera_count": self.camera_count,
            "image_channels": self.image_channels,
            "ego_state_dim": self.ego_state_dim,
            "hidden_dim": self.hidden_dim,
            "temporal_layers": self.temporal_layers,
            "bev_height": self.bev_height,
            "bev_width": self.bev_width,
            "future_steps": self.future_steps,
            "trajectory_modes": self.trajectory_modes,
            "max_agents": self.max_agents,
            "agent_state_dim": self.agent_state_dim,
            "camera_geometry_dim": self.camera_geometry_dim,
        }
        if any(value <= 0 for value in integer_fields.values()):
            raise ValueError("world-model dimensions must be positive")
        if self.hidden_dim < 16:
            raise ValueError("hidden_dim must be at least 16")
        if not math.isfinite(self.future_dt_s) or not (0.01 <= self.future_dt_s <= 1.0):
            raise ValueError("future_dt_s must be in [0.01, 1.0]")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)


def _require_torch():
    try:
        import torch
        import torch.nn as nn
        import torch.nn.functional as functional
    except ImportError as exc:
        raise RuntimeError("PyTorch is required for the trainable world-model backend; install vision-shark-app[learning]") from exc
    return torch, nn, functional


def build_torch_world_model(config: WorldModelConfig | None = None):
    """Build a trainable multi-camera temporal world model.

    Camera images are encoded by a shared CNN. When `use_camera_geometry` is
    enabled, validated normalized intrinsics and camera-to-ego extrinsics are
    embedded and fused into each camera token before cross-camera attention.
    Ego history and fused visual history then pass through a temporal GRU and
    multi-task world/policy heads for offline or shadow evaluation.
    """
    cfg = config or WorldModelConfig()
    cfg.validate()
    torch, nn, _ = _require_torch()

    class VisionWorldModel(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            channels = max(32, cfg.hidden_dim // 2)
            self.image_encoder = nn.Sequential(
                nn.Conv2d(cfg.image_channels, 32, kernel_size=5, stride=2, padding=2),
                nn.SiLU(),
                nn.Conv2d(32, channels, kernel_size=3, stride=2, padding=1),
                nn.SiLU(),
                nn.Conv2d(channels, cfg.hidden_dim, kernel_size=3, stride=2, padding=1),
                nn.SiLU(),
                nn.AdaptiveAvgPool2d((1, 1)),
            )
            self.camera_embedding = nn.Embedding(cfg.camera_count, cfg.hidden_dim)
            self.geometry_encoder = None
            if cfg.use_camera_geometry:
                self.geometry_encoder = nn.Sequential(
                    nn.Linear(cfg.camera_geometry_dim, cfg.hidden_dim),
                    nn.SiLU(),
                    nn.Linear(cfg.hidden_dim, cfg.hidden_dim),
                )
            self.camera_attention = nn.Sequential(
                nn.Linear(cfg.hidden_dim, cfg.hidden_dim),
                nn.SiLU(),
                nn.Linear(cfg.hidden_dim, 1),
            )
            self.ego_encoder = nn.Sequential(
                nn.Linear(cfg.ego_state_dim, cfg.hidden_dim),
                nn.SiLU(),
                nn.Linear(cfg.hidden_dim, cfg.hidden_dim),
            )
            self.temporal = nn.GRU(
                input_size=cfg.hidden_dim * 2,
                hidden_size=cfg.hidden_dim,
                num_layers=cfg.temporal_layers,
                batch_first=True,
            )
            bev_cells = cfg.bev_height * cfg.bev_width
            self.occupancy_head = nn.Linear(cfg.hidden_dim, cfg.future_steps * bev_cells)
            self.flow_head = nn.Linear(cfg.hidden_dim, cfg.future_steps * 2 * bev_cells)
            self.agent_head = nn.Linear(
                cfg.hidden_dim,
                cfg.max_agents * cfg.future_steps * cfg.agent_state_dim,
            )
            self.trajectory_head = nn.Linear(
                cfg.hidden_dim,
                cfg.trajectory_modes * cfg.future_steps * 4,
            )
            self.trajectory_logits = nn.Linear(cfg.hidden_dim, cfg.trajectory_modes)
            self.risk_head = nn.Linear(cfg.hidden_dim, cfg.future_steps * bev_cells)

        @property
        def config(self) -> WorldModelConfig:
            return cfg

        def encode_cameras(self, cameras, camera_geometry=None):
            if cameras.ndim != 6:
                raise ValueError("cameras must have shape [B,T,C,Channels,H,W]")
            batch, time_steps, camera_count, channels, height, width = cameras.shape
            if camera_count != cfg.camera_count:
                raise ValueError(f"expected {cfg.camera_count} cameras, received {camera_count}")
            if channels != cfg.image_channels:
                raise ValueError(f"expected {cfg.image_channels} image channels, received {channels}")
            flat = cameras.reshape(batch * time_steps * camera_count, channels, height, width)
            encoded = self.image_encoder(flat).flatten(1)
            encoded = encoded.reshape(batch, time_steps, camera_count, cfg.hidden_dim)
            camera_ids = torch.arange(camera_count, device=cameras.device)
            encoded = encoded + self.camera_embedding(camera_ids).view(1, 1, camera_count, cfg.hidden_dim)
            if cfg.use_camera_geometry:
                if camera_geometry is None:
                    raise ValueError("camera_geometry is required when use_camera_geometry is enabled")
                expected_shape = (batch, time_steps, camera_count, cfg.camera_geometry_dim)
                if tuple(camera_geometry.shape) != expected_shape:
                    raise ValueError(
                        "camera_geometry must have shape "
                        f"[B,T,C,{cfg.camera_geometry_dim}], received {tuple(camera_geometry.shape)}"
                    )
                geometry = camera_geometry.to(device=cameras.device, dtype=encoded.dtype)
                encoded = encoded + self.geometry_encoder(geometry)
            weights = torch.softmax(self.camera_attention(encoded).squeeze(-1), dim=2)
            fused = (encoded * weights.unsqueeze(-1)).sum(dim=2)
            return fused, weights

        def forward(self, cameras, ego_history, camera_geometry=None):
            if ego_history.ndim != 3:
                raise ValueError("ego_history must have shape [B,T,E]")
            camera_features, camera_weights = self.encode_cameras(cameras, camera_geometry)
            if ego_history.shape[:2] != camera_features.shape[:2]:
                raise ValueError("camera and ego history batch/time dimensions must match")
            if ego_history.shape[-1] != cfg.ego_state_dim:
                raise ValueError(f"expected ego_state_dim={cfg.ego_state_dim}")
            ego_features = self.ego_encoder(ego_history)
            temporal_input = torch.cat([camera_features, ego_features], dim=-1)
            temporal_output, hidden = self.temporal(temporal_input)
            latent = temporal_output[:, -1]
            batch = latent.shape[0]
            occupancy_logits = self.occupancy_head(latent).reshape(
                batch, cfg.future_steps, cfg.bev_height, cfg.bev_width
            )
            flow = self.flow_head(latent).reshape(
                batch, cfg.future_steps, 2, cfg.bev_height, cfg.bev_width
            )
            agents = self.agent_head(latent).reshape(
                batch, cfg.max_agents, cfg.future_steps, cfg.agent_state_dim
            )
            trajectories = self.trajectory_head(latent).reshape(
                batch, cfg.trajectory_modes, cfg.future_steps, 4
            )
            trajectory_logits = self.trajectory_logits(latent)
            risk_logits = self.risk_head(latent).reshape(
                batch, cfg.future_steps, cfg.bev_height, cfg.bev_width
            )
            return {
                "occupancy_logits": occupancy_logits,
                "occupancy_flow": flow,
                "agent_forecasts": agents,
                "ego_trajectories": trajectories,
                "trajectory_logits": trajectory_logits,
                "risk_logits": risk_logits,
                "camera_attention": camera_weights,
                "temporal_hidden": hidden[-1],
            }

    return VisionWorldModel()


def world_model_loss(outputs: dict[str, Any], targets: dict[str, Any], *, weights: dict[str, float] | None = None):
    torch, _, functional = _require_torch()
    loss_weights = {
        "occupancy": 1.0,
        "flow": 0.25,
        "agents": 0.5,
        "trajectory": 2.0,
        "risk": 0.5,
        **(weights or {}),
    }
    losses: dict[str, Any] = {}

    if targets.get("occupancy") is not None:
        target = targets["occupancy"].to(outputs["occupancy_logits"].dtype)
        losses["occupancy"] = functional.binary_cross_entropy_with_logits(outputs["occupancy_logits"], target)
    if targets.get("occupancy_flow") is not None:
        losses["flow"] = functional.smooth_l1_loss(outputs["occupancy_flow"], targets["occupancy_flow"])
    if targets.get("agent_forecasts") is not None:
        prediction = outputs["agent_forecasts"]
        target = targets["agent_forecasts"]
        mask = targets.get("agent_mask")
        if mask is None:
            losses["agents"] = functional.smooth_l1_loss(prediction, target)
        else:
            expanded = mask.to(prediction.dtype)
            while expanded.ndim < prediction.ndim:
                expanded = expanded.unsqueeze(-1)
            coordinate_count = prediction.shape[-1]
            denom = (expanded.sum() * coordinate_count).clamp_min(1.0)
            losses["agents"] = (functional.smooth_l1_loss(prediction, target, reduction="none") * expanded).sum() / denom
    if targets.get("ego_trajectory") is not None:
        target = targets["ego_trajectory"]
        prediction = outputs["ego_trajectories"]
        position_error = torch.linalg.vector_norm(prediction[..., :2] - target[:, None, :, :2], dim=-1).mean(dim=-1)
        best_mode = position_error.argmin(dim=1)
        batch_ids = torch.arange(prediction.shape[0], device=prediction.device)
        best_prediction = prediction[batch_ids, best_mode]
        regression = functional.smooth_l1_loss(best_prediction, target)
        classification = functional.cross_entropy(outputs["trajectory_logits"], best_mode)
        losses["trajectory"] = regression + 0.25 * classification
    if targets.get("risk") is not None:
        risk_target = targets["risk"].to(outputs["risk_logits"].dtype)
        losses["risk"] = functional.binary_cross_entropy_with_logits(outputs["risk_logits"], risk_target)

    if not losses:
        raise ValueError("at least one supported target product is required")
    total = sum(loss_weights[name] * value for name, value in losses.items())
    return total, losses


def world_model_profile(config: WorldModelConfig | None = None) -> dict[str, Any]:
    cfg = config or WorldModelConfig()
    cfg.validate()
    inputs = {
        "cameras": "[batch,time,cameras,channels,height,width]",
        "ego_history": "[batch,time,ego_state_dim]",
    }
    if cfg.use_camera_geometry:
        inputs["camera_geometry"] = f"[batch,time,cameras,{cfg.camera_geometry_dim}]"
    return {
        "model_family": "vision_world_model",
        "architecture": (
            "shared multi-camera CNN + calibrated geometry embeddings + learned camera attention + temporal GRU + multi-task heads"
            if cfg.use_camera_geometry
            else "shared multi-camera CNN + learned camera attention + temporal GRU + multi-task heads"
        ),
        "config": cfg.as_dict(),
        "input_contract": inputs,
        "geometry_aware": bool(cfg.use_camera_geometry),
        "output_products": [
            "occupancy_logits",
            "occupancy_flow",
            "agent_forecasts",
            "ego_trajectories",
            "trajectory_logits",
            "risk_logits",
            "camera_attention",
        ],
        "trainable": True,
        "weights_included": False,
        "offline_or_shadow_only": True,
        "live_actuation": False,
        "raw_vehicle_tx": False,
    }
