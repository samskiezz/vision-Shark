from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from typing import Any, Iterable


@dataclass(frozen=True)
class CameraFrameRef:
    camera_id: str
    timestamp_s: float
    uri: str
    sha256: str | None = None
    width: int | None = None
    height: int | None = None

    def validate(self) -> None:
        if not self.camera_id.strip():
            raise ValueError("camera_id is required")
        if not math.isfinite(float(self.timestamp_s)) or self.timestamp_s < 0:
            raise ValueError("camera timestamp must be finite and non-negative")
        if not self.uri.strip():
            raise ValueError("camera frame uri is required")
        if self.sha256 is not None:
            value = self.sha256.lower()
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise ValueError("camera frame sha256 must be 64 lowercase hex characters")
        if self.width is not None and self.width <= 0:
            raise ValueError("camera frame width must be positive")
        if self.height is not None and self.height <= 0:
            raise ValueError("camera frame height must be positive")


@dataclass(frozen=True)
class TrainingSample:
    sample_id: str
    recording_id: str
    timestamp_s: float
    cameras: tuple[CameraFrameRef, ...]
    ego_state: dict[str, Any]
    labels: dict[str, Any]
    calibration_id: str | None = None
    scenario_tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self, *, required_cameras: Iterable[str] = ()) -> None:
        if not self.sample_id.strip():
            raise ValueError("sample_id is required")
        if not self.recording_id.strip():
            raise ValueError("recording_id is required")
        if not math.isfinite(float(self.timestamp_s)) or self.timestamp_s < 0:
            raise ValueError("sample timestamp must be finite and non-negative")
        if not self.cameras:
            raise ValueError("at least one camera frame is required")
        seen: set[str] = set()
        for camera in self.cameras:
            camera.validate()
            if camera.camera_id in seen:
                raise ValueError(f"duplicate camera_id in sample: {camera.camera_id}")
            seen.add(camera.camera_id)
        missing = sorted(set(required_cameras) - seen)
        if missing:
            raise ValueError("missing required cameras: " + ",".join(missing))
        if not isinstance(self.ego_state, dict):
            raise ValueError("ego_state must be a mapping")
        if not isinstance(self.labels, dict):
            raise ValueError("labels must be a mapping")
        if not self.labels:
            raise ValueError("training sample requires at least one label product")

    def canonical_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["cameras"] = sorted(payload["cameras"], key=lambda item: item["camera_id"])
        payload["scenario_tags"] = sorted(set(payload["scenario_tags"]))
        return payload

    def sha256(self) -> str:
        payload = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class DatasetManifest:
    dataset_id: str
    version: str
    samples: tuple[TrainingSample, ...]
    required_cameras: tuple[str, ...] = ()
    label_schema_version: str = "planning-world-v2"
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.dataset_id.strip():
            raise ValueError("dataset_id is required")
        if not self.version.strip():
            raise ValueError("dataset version is required")
        if not self.samples:
            raise ValueError("dataset manifest requires samples")
        seen: set[str] = set()
        for sample in self.samples:
            sample.validate(required_cameras=self.required_cameras)
            if sample.sample_id in seen:
                raise ValueError(f"duplicate sample_id: {sample.sample_id}")
            seen.add(sample.sample_id)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "version": self.version,
            "required_cameras": sorted(set(self.required_cameras)),
            "label_schema_version": self.label_schema_version,
            "metadata": self.metadata,
            "samples": [sample.canonical_dict() for sample in sorted(self.samples, key=lambda item: item.sample_id)],
        }

    def sha256(self) -> str:
        payload = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(payload).hexdigest()

    def split(self, *, train: float = 0.8, validation: float = 0.1, test: float = 0.1, salt: str = "vision-shark") -> dict[str, list[str]]:
        fractions = (float(train), float(validation), float(test))
        if any(value < 0 or not math.isfinite(value) for value in fractions):
            raise ValueError("split fractions must be finite and non-negative")
        total = sum(fractions)
        if abs(total - 1.0) > 1e-9:
            raise ValueError("split fractions must sum to 1.0")
        boundaries = (fractions[0], fractions[0] + fractions[1])
        result = {"train": [], "validation": [], "test": []}
        for sample in sorted(self.samples, key=lambda item: item.sample_id):
            digest = hashlib.sha256(f"{salt}:{sample.sample_id}".encode()).digest()
            value = int.from_bytes(digest[:8], "big") / float(2**64)
            if value < boundaries[0]:
                result["train"].append(sample.sample_id)
            elif value < boundaries[1]:
                result["validation"].append(sample.sample_id)
            else:
                result["test"].append(sample.sample_id)
        return result


def camera_frame_from_dict(raw: dict[str, Any]) -> CameraFrameRef:
    return CameraFrameRef(
        camera_id=str(raw.get("camera_id", "")),
        timestamp_s=float(raw.get("timestamp_s", 0.0)),
        uri=str(raw.get("uri", "")),
        sha256=None if raw.get("sha256") is None else str(raw.get("sha256")),
        width=None if raw.get("width") is None else int(raw.get("width")),
        height=None if raw.get("height") is None else int(raw.get("height")),
    )


def training_sample_from_dict(raw: dict[str, Any]) -> TrainingSample:
    return TrainingSample(
        sample_id=str(raw.get("sample_id", "")),
        recording_id=str(raw.get("recording_id", "")),
        timestamp_s=float(raw.get("timestamp_s", 0.0)),
        cameras=tuple(camera_frame_from_dict(item) for item in raw.get("cameras", []) or []),
        ego_state=dict(raw.get("ego_state") or {}),
        labels=dict(raw.get("labels") or {}),
        calibration_id=None if raw.get("calibration_id") is None else str(raw.get("calibration_id")),
        scenario_tags=tuple(str(item) for item in raw.get("scenario_tags", []) or []),
        metadata=dict(raw.get("metadata") or {}),
    )


def dataset_manifest_from_dict(raw: dict[str, Any]) -> DatasetManifest:
    manifest = DatasetManifest(
        dataset_id=str(raw.get("dataset_id", "")),
        version=str(raw.get("version", "")),
        samples=tuple(training_sample_from_dict(item) for item in raw.get("samples", []) or []),
        required_cameras=tuple(str(item) for item in raw.get("required_cameras", []) or []),
        label_schema_version=str(raw.get("label_schema_version", "planning-world-v2")),
        metadata=dict(raw.get("metadata") or {}),
    )
    manifest.validate()
    return manifest


def training_contract_profile() -> dict[str, Any]:
    return {
        "contract": "vision-shark-autonomy-training-v1",
        "sample_products": [
            "multi_camera_frames",
            "ego_state",
            "camera_calibration_reference",
            "occupancy",
            "occupancy_flow",
            "agent_forecasts",
            "lane_topology",
            "ego_trajectory",
        ],
        "deterministic_manifest_hash": True,
        "deterministic_split": True,
        "raw_vehicle_tx": False,
        "live_actuation": False,
    }
