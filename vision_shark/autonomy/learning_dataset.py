from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import unquote, urlparse

from .camera_geometry import CalibrationRig, GEOMETRY_VECTOR_DIM
from .training_contracts import DatasetManifest, TrainingSample


DEFAULT_EGO_FIELDS = (
    "speed_ms",
    "accel_ms2",
    "yaw_rate_rads",
    "steering_angle_rad",
    "x_m",
    "y_m",
    "heading_rad",
    "route_progress_m",
)


@dataclass(frozen=True)
class SequenceWindow:
    sample_ids: tuple[str, ...]
    recording_id: str
    timestamps_s: tuple[float, ...]


@dataclass(frozen=True)
class DatasetLoaderConfig:
    history_steps: int = 4
    stride: int = 1
    image_height: int = 128
    image_width: int = 256
    max_gap_s: float = 0.5
    future_steps: int = 10
    max_agents: int = 32
    ego_fields: tuple[str, ...] = DEFAULT_EGO_FIELDS
    verify_frame_hashes: bool = True
    require_calibration: bool = False

    def validate(self) -> None:
        if self.history_steps <= 0:
            raise ValueError("history_steps must be positive")
        if self.stride <= 0:
            raise ValueError("stride must be positive")
        if self.image_height <= 0 or self.image_width <= 0:
            raise ValueError("image dimensions must be positive")
        if not math.isfinite(self.max_gap_s) or self.max_gap_s <= 0:
            raise ValueError("max_gap_s must be finite and positive")
        if self.future_steps <= 0 or self.max_agents <= 0:
            raise ValueError("future_steps and max_agents must be positive")
        if not self.ego_fields or any(not str(item).strip() for item in self.ego_fields):
            raise ValueError("ego_fields must be non-empty strings")


def _require_learning_dependencies():
    try:
        import torch
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("PyTorch and Pillow are required for dataset materialization; install vision-shark-app[learning]") from exc
    return torch, Image


def _resolve_local_frame(uri: str, roots: Sequence[Path]) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme not in {"", "file"}:
        raise ValueError(f"only local frame URIs are supported for training: {parsed.scheme}")
    raw_path = unquote(parsed.path if parsed.scheme == "file" else uri)
    candidate = Path(raw_path)
    resolved_roots = [Path(root).expanduser().resolve() for root in roots]
    candidates = [candidate] if candidate.is_absolute() else [root / candidate for root in resolved_roots]
    for item in candidates:
        resolved = item.expanduser().resolve()
        if not any(resolved == root or root in resolved.parents for root in resolved_roots):
            continue
        if resolved.is_file():
            return resolved
    raise ValueError(f"frame path is missing or outside allowed roots: {uri}")


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_sequence_windows(
    manifest: DatasetManifest,
    *,
    history_steps: int = 4,
    stride: int = 1,
    max_gap_s: float = 0.5,
    sample_ids: Iterable[str] | None = None,
) -> list[SequenceWindow]:
    """Build history windows, using sample_ids as target IDs rather than context IDs."""
    if history_steps <= 0 or stride <= 0:
        raise ValueError("history_steps and stride must be positive")
    if not math.isfinite(max_gap_s) or max_gap_s <= 0:
        raise ValueError("max_gap_s must be finite and positive")
    allowed_targets = None if sample_ids is None else set(sample_ids)
    groups: dict[str, list[TrainingSample]] = {}
    for sample in manifest.samples:
        groups.setdefault(sample.recording_id, []).append(sample)
    windows: list[SequenceWindow] = []
    for recording_id, samples in sorted(groups.items()):
        ordered = sorted(samples, key=lambda item: (item.timestamp_s, item.sample_id))
        for start in range(0, max(0, len(ordered) - history_steps + 1), stride):
            chunk = ordered[start : start + history_steps]
            if len(chunk) != history_steps:
                continue
            if allowed_targets is not None and chunk[-1].sample_id not in allowed_targets:
                continue
            gaps = [right.timestamp_s - left.timestamp_s for left, right in zip(chunk, chunk[1:], strict=False)]
            if any(gap < 0 or gap > max_gap_s for gap in gaps):
                continue
            camera_sets = [{camera.camera_id for camera in sample.cameras} for sample in chunk]
            if any(camera_set != camera_sets[0] for camera_set in camera_sets[1:]):
                continue
            windows.append(
                SequenceWindow(
                    sample_ids=tuple(sample.sample_id for sample in chunk),
                    recording_id=recording_id,
                    timestamps_s=tuple(sample.timestamp_s for sample in chunk),
                )
            )
    return windows


def _points_tensor(value: Any, torch, *, future_steps: int):
    rows = []
    for point in value or []:
        if isinstance(point, dict):
            rows.append([
                float(point.get("x", 0.0) or 0.0),
                float(point.get("y", 0.0) or 0.0),
                float(point.get("speed", point.get("speed_ms", 0.0)) or 0.0),
                float(point.get("accel", point.get("acceleration", 0.0)) or 0.0),
            ])
        else:
            row = list(point)
            rows.append([float(row[index]) if index < len(row) else 0.0 for index in range(4)])
    if len(rows) != future_steps:
        raise ValueError(f"ego_trajectory requires exactly {future_steps} future points")
    return torch.tensor(rows, dtype=torch.float32)


def _agents_tensor(value: Any, torch, *, future_steps: int, max_agents: int):
    if not value:
        raise ValueError("agent_forecasts label cannot be empty")
    if len(value) > max_agents:
        raise ValueError(f"agent_forecasts exceeds max_agents={max_agents}")
    agents = []
    mask = []
    for item in value:
        points = item.get("points", []) if isinstance(item, dict) else item
        if len(points) > future_steps:
            raise ValueError(f"agent forecast exceeds future_steps={future_steps}")
        rows = []
        active = []
        for point in points:
            if isinstance(point, dict):
                rows.append([
                    float(point.get("x", 0.0) or 0.0),
                    float(point.get("y", 0.0) or 0.0),
                    float(point.get("vx", 0.0) or 0.0),
                    float(point.get("vy", 0.0) or 0.0),
                ])
            else:
                row = list(point)
                rows.append([float(row[index]) if index < len(row) else 0.0 for index in range(4)])
            active.append(1.0)
        while len(rows) < future_steps:
            rows.append([0.0, 0.0, 0.0, 0.0])
            active.append(0.0)
        agents.append(rows)
        mask.append(active)
    while len(agents) < max_agents:
        agents.append([[0.0, 0.0, 0.0, 0.0] for _ in range(future_steps)])
        mask.append([0.0 for _ in range(future_steps)])
    return torch.tensor(agents, dtype=torch.float32), torch.tensor(mask, dtype=torch.float32)


def _pack_targets(labels: dict[str, Any], torch, *, future_steps: int, max_agents: int) -> dict[str, Any]:
    targets: dict[str, Any] = {}
    for key, value in labels.items():
        if value is None:
            continue
        if key == "ego_trajectory":
            targets[key] = _points_tensor(value, torch, future_steps=future_steps)
        elif key == "agent_forecasts":
            agents, mask = _agents_tensor(value, torch, future_steps=future_steps, max_agents=max_agents)
            targets[key] = agents
            targets["agent_mask"] = mask
        elif key in {"occupancy", "occupancy_flow", "risk"}:
            tensor = torch.as_tensor(value, dtype=torch.float32)
            if tensor.shape[0] != future_steps:
                raise ValueError(f"{key} first dimension must equal future_steps={future_steps}")
            targets[key] = tensor
        elif key == "agent_mask" and "agent_mask" not in targets:
            targets[key] = torch.as_tensor(value, dtype=torch.float32)
    if not targets:
        raise ValueError("sample labels contain no supported trainable target products")
    return targets


class SequenceWindowDataset:
    """Load deterministic multi-camera history windows from a DatasetManifest.

    Frame references are local-only. When calibration rigs are supplied, every
    history frame also emits an ordered camera-geometry tensor using normalized
    intrinsics and the camera-to-ego extrinsic transform.
    """

    def __init__(
        self,
        manifest: DatasetManifest,
        *,
        frame_roots: Sequence[str | Path],
        sample_ids: Iterable[str] | None = None,
        config: DatasetLoaderConfig | None = None,
        calibration_rigs: Mapping[str, CalibrationRig] | None = None,
    ) -> None:
        self.manifest = manifest
        self.config = config or DatasetLoaderConfig()
        self.config.validate()
        self.frame_roots = tuple(Path(root).expanduser().resolve() for root in frame_roots)
        if not self.frame_roots:
            raise ValueError("at least one frame root is required")
        self.calibration_rigs = dict(calibration_rigs or {})
        for calibration_id, rig in self.calibration_rigs.items():
            rig.validate()
            if calibration_id != rig.calibration_id:
                raise ValueError("calibration registry key must match rig calibration_id")
        self.samples = {sample.sample_id: sample for sample in manifest.samples}
        self.camera_ids = tuple(sorted(set(manifest.required_cameras) or {camera.camera_id for sample in manifest.samples for camera in sample.cameras}))
        if not self.camera_ids:
            raise ValueError("dataset has no cameras")
        if self.config.require_calibration and not self.calibration_rigs:
            raise ValueError("require_calibration is enabled but no calibration rigs were supplied")
        self.windows = build_sequence_windows(
            manifest,
            history_steps=self.config.history_steps,
            stride=self.config.stride,
            max_gap_s=self.config.max_gap_s,
            sample_ids=sample_ids,
        )
        if not self.windows:
            raise ValueError("dataset has no valid history windows")

    def __len__(self) -> int:
        return len(self.windows)

    def _load_frame(self, frame) -> Any:
        torch, Image = _require_learning_dependencies()
        path = _resolve_local_frame(frame.uri, self.frame_roots)
        if self.config.verify_frame_hashes and frame.sha256 is not None:
            actual = _sha256_file(path)
            if actual != frame.sha256.lower():
                raise ValueError(f"frame hash mismatch for {frame.camera_id}: {path}")
        with Image.open(path) as image:
            image = image.convert("RGB")
            image = image.resize((self.config.image_width, self.config.image_height), resample=Image.Resampling.BILINEAR)
            raw = torch.frombuffer(bytearray(image.tobytes()), dtype=torch.uint8)
            tensor = raw.reshape(self.config.image_height, self.config.image_width, 3).permute(2, 0, 1).to(torch.float32) / 255.0
        return tensor

    def _geometry_for_sample(self, sample: TrainingSample, torch):
        if sample.calibration_id is None:
            if self.config.require_calibration:
                raise ValueError(f"sample {sample.sample_id} has no calibration_id")
            return torch.zeros((len(self.camera_ids), GEOMETRY_VECTOR_DIM), dtype=torch.float32)
        rig = self.calibration_rigs.get(sample.calibration_id)
        if rig is None:
            if self.config.require_calibration:
                raise ValueError(f"unknown calibration_id for sample {sample.sample_id}: {sample.calibration_id}")
            return torch.zeros((len(self.camera_ids), GEOMETRY_VECTOR_DIM), dtype=torch.float32)
        return torch.tensor(rig.ordered_vectors(self.camera_ids), dtype=torch.float32)

    def __getitem__(self, index: int) -> dict[str, Any]:
        torch, _ = _require_learning_dependencies()
        window = self.windows[index]
        history = [self.samples[sample_id] for sample_id in window.sample_ids]
        camera_history = []
        geometry_history = []
        ego_history = []
        for sample in history:
            by_camera = {frame.camera_id: frame for frame in sample.cameras}
            missing = [camera_id for camera_id in self.camera_ids if camera_id not in by_camera]
            if missing:
                raise ValueError("history window missing cameras: " + ",".join(missing))
            camera_history.append(torch.stack([self._load_frame(by_camera[camera_id]) for camera_id in self.camera_ids], dim=0))
            geometry_history.append(self._geometry_for_sample(sample, torch))
            ego_history.append([float(sample.ego_state.get(field, 0.0) or 0.0) for field in self.config.ego_fields])
        cameras = torch.stack(camera_history, dim=0)
        camera_geometry = torch.stack(geometry_history, dim=0)
        ego = torch.tensor(ego_history, dtype=torch.float32)
        targets = _pack_targets(
            history[-1].labels,
            torch,
            future_steps=self.config.future_steps,
            max_agents=self.config.max_agents,
        )
        return {
            "cameras": cameras,
            "camera_geometry": camera_geometry,
            "ego_history": ego,
            "targets": targets,
            "sample_id": history[-1].sample_id,
            "history_sample_ids": list(window.sample_ids),
            "recording_id": window.recording_id,
            "camera_ids": list(self.camera_ids),
            "timestamps_s": list(window.timestamps_s),
            "calibration_ids": [sample.calibration_id for sample in history],
        }

    def profile(self) -> dict[str, Any]:
        return {
            "samples": len(self.manifest.samples),
            "windows": len(self.windows),
            "history_steps": self.config.history_steps,
            "future_steps": self.config.future_steps,
            "max_agents": self.config.max_agents,
            "camera_ids": list(self.camera_ids),
            "image_shape": [3, self.config.image_height, self.config.image_width],
            "camera_geometry_shape": [len(self.camera_ids), GEOMETRY_VECTOR_DIM],
            "calibration_rigs": len(self.calibration_rigs),
            "require_calibration": self.config.require_calibration,
            "ego_fields": list(self.config.ego_fields),
            "frame_roots": [str(root) for root in self.frame_roots],
            "verify_frame_hashes": self.config.verify_frame_hashes,
            "remote_fetch": False,
            "raw_vehicle_tx": False,
            "live_actuation": False,
        }


def split_hashes(splits: dict[str, list[str]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, sample_ids in sorted(splits.items()):
        payload = json.dumps(sorted(sample_ids), separators=(",", ":")).encode()
        result[name] = hashlib.sha256(payload).hexdigest()
    return result
