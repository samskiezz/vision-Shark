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
    use_spatial_bev: bool = False
    spatial_token_height: int = 4
    spatial_token_width: int = 8
    attention_heads: int = 4

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
            "spatial_token_height": self.spatial_token_height,
            "spatial_token_width": self.spatial_token_width,
            "attention_heads": self.attention_heads,
        }
        if any(value <= 0 for value in integer_fields.values()):
            raise ValueError("world-model dimensions must be positive")
        if self.hidden_dim < 16:
            raise ValueError("hidden_dim must be at least 16")
        if not math.isfinite(self.future_dt_s) or not (0.01 <= self.future_dt_s <= 1.0):
            raise ValueError("future_dt_s must be in [0.01, 1.0]")
        if self.use_camera_geometry and self.camera_geometry_dim != GEOMETRY_VECTOR_DIM:
            raise ValueError(f"camera_geometry_dim must equal the calibration contract width {GEOMETRY_VECTOR_DIM}")
        if self.use_spatial_bev:
            if not self.use_camera_geometry:
                raise ValueError("use_spatial_bev requires use_camera_geometry")
            if self.hidden_dim % self.attention_heads != 0:
                raise ValueError("hidden_dim must be divisible by attention_heads for spatial BEV attention")

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

    The compatibility path retains the original globally pooled camera encoder.
    Geometry-aware models can additionally use a spatial BEV path that preserves
    image tokens, derives per-token rays from measured intrinsics/extrinsics and
    cross-attends learned BEV cells into the multi-camera token set before
    temporal fusion and multi-task decoding.
    """
    cfg = config or WorldModelConfig()
    cfg.validate()
    torch, nn, _ = _require_torch()

    class VisionWorldModel(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            channels = max(32, cfg.hidden_dim // 2)
            pool_shape = (
                (cfg.spatial_token_height, cfg.spatial_token_width)
                if cfg.use_spatial_bev
                else (1, 1)
            )
            self.image_encoder = nn.Sequential(
                nn.Conv2d(cfg.image_channels, 32, kernel_size=5, stride=2, padding=2),
                nn.SiLU(),
                nn.Conv2d(32, channels, kernel_size=3, stride=2, padding=1),
                nn.SiLU(),
                nn.Conv2d(channels, cfg.hidden_dim, kernel_size=3, stride=2, padding=1),
                nn.SiLU(),
                nn.AdaptiveAvgPool2d(pool_shape),
            )
            self.camera_embedding = nn.Embedding(cfg.camera_count, cfg.hidden_dim)
            self.geometry_encoder = None
            if cfg.use_camera_geometry:
                self.geometry_encoder = nn.Sequential(
                    nn.Linear(cfg.camera_geometry_dim, cfg.hidden_dim),
                    nn.SiLU(),
                    nn.Linear(cfg.hidden_dim, cfg.hidden_dim),
                )
            self.camera_attention = None
            self.ray_encoder = None
            self.bev_queries = None
            self.bev_attention = None
            self.bev_norm = None
            self.bev_ffn = None
            self.bev_ffn_norm = None
            self.spatial_fusion = None
            if cfg.use_spatial_bev:
                self.ray_encoder = nn.Sequential(
                    nn.Linear(8, cfg.hidden_dim),
                    nn.SiLU(),
                    nn.Linear(cfg.hidden_dim, cfg.hidden_dim),
                )
                bev_cells = cfg.bev_height * cfg.bev_width
                self.bev_queries = nn.Parameter(torch.empty(bev_cells, cfg.hidden_dim))
                nn.init.normal_(self.bev_queries, mean=0.0, std=0.02)
                self.bev_attention = nn.MultiheadAttention(
                    embed_dim=cfg.hidden_dim,
                    num_heads=cfg.attention_heads,
                    batch_first=True,
                )
                self.bev_norm = nn.LayerNorm(cfg.hidden_dim)
                self.bev_ffn = nn.Sequential(
                    nn.Linear(cfg.hidden_dim, cfg.hidden_dim * 2),
                    nn.SiLU(),
                    nn.Linear(cfg.hidden_dim * 2, cfg.hidden_dim),
                )
                self.bev_ffn_norm = nn.LayerNorm(cfg.hidden_dim)
                self.spatial_fusion = nn.Sequential(
                    nn.Linear(cfg.hidden_dim * 2, cfg.hidden_dim),
                    nn.SiLU(),
                    nn.Linear(cfg.hidden_dim, cfg.hidden_dim),
                )
                v = (torch.arange(cfg.spatial_token_height, dtype=torch.float32) + 0.5) / cfg.spatial_token_height
                u = (torch.arange(cfg.spatial_token_width, dtype=torch.float32) + 0.5) / cfg.spatial_token_width
                grid_v, grid_u = torch.meshgrid(v, u, indexing="ij")
                self.register_buffer(
                    "pixel_uv",
                    torch.stack([grid_u.reshape(-1), grid_v.reshape(-1)], dim=-1),
                    persistent=False,
                )
            else:
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
            if cfg.use_spatial_bev:
                self.occupancy_head = nn.Linear(cfg.hidden_dim, cfg.future_steps)
                self.flow_head = nn.Linear(cfg.hidden_dim, cfg.future_steps * 2)
                self.risk_head = nn.Linear(cfg.hidden_dim, cfg.future_steps)
            else:
                self.occupancy_head = nn.Linear(cfg.hidden_dim, cfg.future_steps * bev_cells)
                self.flow_head = nn.Linear(cfg.hidden_dim, cfg.future_steps * 2 * bev_cells)
                self.risk_head = nn.Linear(cfg.hidden_dim, cfg.future_steps * bev_cells)
            self.agent_head = nn.Linear(
                cfg.hidden_dim,
                cfg.max_agents * cfg.future_steps * cfg.agent_state_dim,
            )
            self.trajectory_head = nn.Linear(
                cfg.hidden_dim,
                cfg.trajectory_modes * cfg.future_steps * 4,
            )
            self.trajectory_logits = nn.Linear(cfg.hidden_dim, cfg.trajectory_modes)

        @property
        def config(self) -> WorldModelConfig:
            return cfg

        def _validate_camera_inputs(self, cameras, camera_geometry=None):
            if cameras.ndim != 6:
                raise ValueError("cameras must have shape [B,T,C,Channels,H,W]")
            batch, time_steps, camera_count, channels, height, width = cameras.shape
            if camera_count != cfg.camera_count:
                raise ValueError(f"expected {cfg.camera_count} cameras, received {camera_count}")
            if channels != cfg.image_channels:
                raise ValueError(f"expected {cfg.image_channels} image channels, received {channels}")
            geometry = None
            if cfg.use_camera_geometry:
                if camera_geometry is None:
                    raise ValueError("camera_geometry is required when use_camera_geometry is enabled")
                expected_shape = (batch, time_steps, camera_count, cfg.camera_geometry_dim)
                if tuple(camera_geometry.shape) != expected_shape:
                    raise ValueError(
                        "camera_geometry must have shape "
                        f"[B,T,C,{cfg.camera_geometry_dim}], received {tuple(camera_geometry.shape)}"
                    )
                geometry = camera_geometry.to(device=cameras.device, dtype=cameras.dtype)
            return batch, time_steps, camera_count, channels, height, width, geometry

        def _ray_features(self, geometry):
            batch, time_steps, camera_count, _ = geometry.shape
            point_count = cfg.spatial_token_height * cfg.spatial_token_width
            uv = self.pixel_uv.to(device=geometry.device, dtype=geometry.dtype)
            u = uv[:, 0].view(1, 1, 1, point_count)
            v = uv[:, 1].view(1, 1, 1, point_count)
            fx = geometry[..., 0].unsqueeze(-1).clamp_min(1e-6)
            fy = geometry[..., 1].unsqueeze(-1).clamp_min(1e-6)
            cx = geometry[..., 2].unsqueeze(-1)
            cy = geometry[..., 3].unsqueeze(-1)
            ray_camera = torch.stack(
                [
                    (u - cx) / fx,
                    (v - cy) / fy,
                    torch.ones((batch, time_steps, camera_count, point_count), device=geometry.device, dtype=geometry.dtype),
                ],
                dim=-1,
            )
            ray_camera = ray_camera / torch.linalg.vector_norm(ray_camera, dim=-1, keepdim=True).clamp_min(1e-6)
            rotation = torch.stack(
                [
                    geometry[..., 6:9],
                    geometry[..., 10:13],
                    geometry[..., 14:17],
                ],
                dim=-2,
            )
            translation = torch.stack(
                [geometry[..., 9], geometry[..., 13], geometry[..., 17]],
                dim=-1,
            )
            ray_ego = torch.matmul(rotation.unsqueeze(3), ray_camera.unsqueeze(-1)).squeeze(-1)
            ray_ego = ray_ego / torch.linalg.vector_norm(ray_ego, dim=-1, keepdim=True).clamp_min(1e-6)
            origin = translation.unsqueeze(3).expand(-1, -1, -1, point_count, -1)
            uv_features = uv.view(1, 1, 1, point_count, 2).expand(batch, time_steps, camera_count, -1, -1)
            return torch.cat([origin, ray_ego, uv_features], dim=-1)

        def _encode_spatial_cameras(self, cameras, geometry):
            batch, time_steps, camera_count, channels, height, width = cameras.shape
            point_count = cfg.spatial_token_height * cfg.spatial_token_width
            flat = cameras.reshape(batch * time_steps * camera_count, channels, height, width)
            encoded = self.image_encoder(flat)
            encoded = encoded.flatten(2).transpose(1, 2)
            encoded = encoded.reshape(batch, time_steps, camera_count, point_count, cfg.hidden_dim)
            camera_ids = torch.arange(camera_count, device=cameras.device)
            camera_tokens = self.camera_embedding(camera_ids).view(1, 1, camera_count, 1, cfg.hidden_dim)
            geometry_tokens = self.geometry_encoder(geometry).unsqueeze(3)
            ray_tokens = self.ray_encoder(self._ray_features(geometry))
            source = encoded + camera_tokens + geometry_tokens + ray_tokens
            source = source.reshape(batch * time_steps, camera_count * point_count, cfg.hidden_dim)
            queries = self.bev_queries.unsqueeze(0).expand(batch * time_steps, -1, -1)
            attended, attention = self.bev_attention(
                queries,
                source,
                source,
                need_weights=True,
                average_attn_weights=True,
            )
            bev = self.bev_norm(queries + attended)
            bev = self.bev_ffn_norm(bev + self.bev_ffn(bev))
            bev_cells = cfg.bev_height * cfg.bev_width
            attention = attention.reshape(
                batch,
                time_steps,
                bev_cells,
                camera_count,
                point_count,
            )
            camera_weights = attention.mean(dim=(2, 4))
            camera_weights = camera_weights / camera_weights.sum(dim=2, keepdim=True).clamp_min(1e-6)
            return bev.reshape(batch, time_steps, bev_cells, cfg.hidden_dim), camera_weights

        def encode_cameras(self, cameras, camera_geometry=None):
            batch, time_steps, camera_count, channels, height, width, geometry = self._validate_camera_inputs(
                cameras,
                camera_geometry,
            )
            if cfg.use_spatial_bev:
                return self._encode_spatial_cameras(cameras, geometry)
            flat = cameras.reshape(batch * time_steps * camera_count, channels, height, width)
            encoded = self.image_encoder(flat).flatten(1)
            encoded = encoded.reshape(batch, time_steps, camera_count, cfg.hidden_dim)
            camera_ids = torch.arange(camera_count, device=cameras.device)
            encoded = encoded + self.camera_embedding(camera_ids).view(1, 1, camera_count, cfg.hidden_dim)
            if cfg.use_camera_geometry:
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
            if cfg.use_spatial_bev:
                visual_history = camera_features.mean(dim=2)
            else:
                visual_history = camera_features
            ego_features = self.ego_encoder(ego_history)
            temporal_input = torch.cat([visual_history, ego_features], dim=-1)
            temporal_output, hidden = self.temporal(temporal_input)
            latent = temporal_output[:, -1]
            batch = latent.shape[0]
            if cfg.use_spatial_bev:
                spatial = camera_features[:, -1]
                temporal_context = latent.unsqueeze(1).expand(-1, spatial.shape[1], -1)
                spatial = self.spatial_fusion(torch.cat([spatial, temporal_context], dim=-1))
                occupancy_logits = self.occupancy_head(spatial).permute(0, 2, 1).reshape(
                    batch,
                    cfg.future_steps,
                    cfg.bev_height,
                    cfg.bev_width,
                )
                flow = self.flow_head(spatial).reshape(
                    batch,
                    cfg.bev_height * cfg.bev_width,
                    cfg.future_steps,
                    2,
                ).permute(0, 2, 3, 1).reshape(
                    batch,
                    cfg.future_steps,
                    2,
                    cfg.bev_height,
                    cfg.bev_width,
                )
                risk_logits = self.risk_head(spatial).permute(0, 2, 1).reshape(
                    batch,
                    cfg.future_steps,
                    cfg.bev_height,
                    cfg.bev_width,
                )
            else:
                occupancy_logits = self.occupancy_head(latent).reshape(
                    batch, cfg.future_steps, cfg.bev_height, cfg.bev_width
                )
                flow = self.flow_head(latent).reshape(
                    batch, cfg.future_steps, 2, cfg.bev_height, cfg.bev_width
                )
                risk_logits = self.risk_head(latent).reshape(
                    batch, cfg.future_steps, cfg.bev_height, cfg.bev_width
                )
            agents = self.agent_head(latent).reshape(
                batch, cfg.max_agents, cfg.future_steps, cfg.agent_state_dim
            )
            trajectories = self.trajectory_head(latent).reshape(
                batch, cfg.trajectory_modes, cfg.future_steps, 4
            )
            trajectory_logits = self.trajectory_logits(latent)
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
    if cfg.use_spatial_bev:
        architecture = (
            "shared multi-camera spatial CNN + calibrated camera-ray tokens + learned BEV cross-attention + "
            "temporal GRU + spatial occupancy/flow/risk decoders + agent/trajectory heads"
        )
    elif cfg.use_camera_geometry:
        architecture = "shared multi-camera CNN + calibrated geometry embeddings + learned camera attention + temporal GRU + multi-task heads"
    else:
        architecture = "shared multi-camera CNN + learned camera attention + temporal GRU + multi-task heads"
    return {
        "model_family": "vision_world_model",
        "architecture": architecture,
        "config": cfg.as_dict(),
        "input_contract": inputs,
        "geometry_aware": bool(cfg.use_camera_geometry),
        "spatial_bev": bool(cfg.use_spatial_bev),
        "spatial_camera_tokens_per_camera": cfg.spatial_token_height * cfg.spatial_token_width if cfg.use_spatial_bev else 1,
        "bev_tokens": cfg.bev_height * cfg.bev_width if cfg.use_spatial_bev else 0,
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
