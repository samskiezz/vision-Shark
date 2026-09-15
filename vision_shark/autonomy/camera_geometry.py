from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Any, Iterable, Mapping


GEOMETRY_VECTOR_DIM = 18


@dataclass(frozen=True)
class CameraGeometry:
    camera_id: str
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    camera_to_ego: tuple[tuple[float, float, float, float], ...]

    def validate(self) -> None:
        if not self.camera_id.strip():
            raise ValueError("camera_id is required")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("camera image dimensions must be positive")
        if self.fx <= 0 or self.fy <= 0:
            raise ValueError("camera focal lengths must be positive")
        if not all(math.isfinite(value) for value in (self.fx, self.fy, self.cx, self.cy)):
            raise ValueError("camera intrinsics must be finite")
        if len(self.camera_to_ego) != 4 or any(len(row) != 4 for row in self.camera_to_ego):
            raise ValueError("camera_to_ego must be a 4x4 transform")
        values = [float(value) for row in self.camera_to_ego for value in row]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("camera_to_ego must contain finite values")
        bottom = self.camera_to_ego[3]
        if any(abs(float(left) - right) > 1e-6 for left, right in zip(bottom, (0.0, 0.0, 0.0, 1.0), strict=True)):
            raise ValueError("camera_to_ego bottom row must be [0,0,0,1]")
        rotation = [self.camera_to_ego[row][:3] for row in range(3)]
        for row in rotation:
            norm = math.sqrt(sum(float(value) ** 2 for value in row))
            if abs(norm - 1.0) > 0.05:
                raise ValueError("camera_to_ego rotation rows must be approximately unit length")
        for left_index in range(3):
            for right_index in range(left_index + 1, 3):
                dot = sum(float(rotation[left_index][index]) * float(rotation[right_index][index]) for index in range(3))
                if abs(dot) > 0.05:
                    raise ValueError("camera_to_ego rotation rows must be approximately orthogonal")

    def vector(self) -> tuple[float, ...]:
        """Return a scale-normalized 18D intrinsic/extrinsic feature vector."""
        self.validate()
        intrinsic = (
            self.fx / self.width,
            self.fy / self.height,
            self.cx / self.width,
            self.cy / self.height,
            self.width / self.height,
            self.height / self.width,
        )
        extrinsic = tuple(float(self.camera_to_ego[row][column]) for row in range(3) for column in range(4))
        vector = intrinsic + extrinsic
        if len(vector) != GEOMETRY_VECTOR_DIM:
            raise AssertionError("camera geometry vector contract changed unexpectedly")
        return vector

    def canonical_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)


@dataclass(frozen=True)
class CalibrationRig:
    calibration_id: str
    cameras: tuple[CameraGeometry, ...]
    vehicle_variant: str | None = None
    firmware: str | None = None
    source: str | None = None

    def validate(self) -> None:
        if not self.calibration_id.strip():
            raise ValueError("calibration_id is required")
        if not self.cameras:
            raise ValueError("calibration rig requires cameras")
        seen: set[str] = set()
        for camera in self.cameras:
            camera.validate()
            if camera.camera_id in seen:
                raise ValueError(f"duplicate camera geometry: {camera.camera_id}")
            seen.add(camera.camera_id)

    def camera_map(self) -> dict[str, CameraGeometry]:
        self.validate()
        return {camera.camera_id: camera for camera in self.cameras}

    def ordered_vectors(self, camera_ids: Iterable[str]) -> tuple[tuple[float, ...], ...]:
        by_id = self.camera_map()
        missing = [camera_id for camera_id in camera_ids if camera_id not in by_id]
        if missing:
            raise ValueError("calibration rig missing cameras: " + ",".join(missing))
        return tuple(by_id[camera_id].vector() for camera_id in camera_ids)

    def canonical_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "calibration_id": self.calibration_id,
            "vehicle_variant": self.vehicle_variant,
            "firmware": self.firmware,
            "source": self.source,
            "cameras": [camera.canonical_dict() for camera in sorted(self.cameras, key=lambda item: item.camera_id)],
        }

    def sha256(self) -> str:
        encoded = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(encoded).hexdigest()


def camera_geometry_from_dict(raw: dict[str, Any]) -> CameraGeometry:
    matrix = raw.get("camera_to_ego")
    if not isinstance(matrix, (list, tuple)):
        raise ValueError("camera_to_ego is required")
    camera = CameraGeometry(
        camera_id=str(raw.get("camera_id", "")),
        width=int(raw.get("width", 0)),
        height=int(raw.get("height", 0)),
        fx=float(raw.get("fx", 0.0)),
        fy=float(raw.get("fy", 0.0)),
        cx=float(raw.get("cx", 0.0)),
        cy=float(raw.get("cy", 0.0)),
        camera_to_ego=tuple(tuple(float(value) for value in row) for row in matrix),
    )
    camera.validate()
    return camera


def calibration_rig_from_dict(raw: dict[str, Any]) -> CalibrationRig:
    rig = CalibrationRig(
        calibration_id=str(raw.get("calibration_id", "")),
        cameras=tuple(camera_geometry_from_dict(item) for item in raw.get("cameras", []) or []),
        vehicle_variant=None if raw.get("vehicle_variant") is None else str(raw.get("vehicle_variant")),
        firmware=None if raw.get("firmware") is None else str(raw.get("firmware")),
        source=None if raw.get("source") is None else str(raw.get("source")),
    )
    rig.validate()
    return rig


def calibration_registry_from_dict(raw: dict[str, Any]) -> dict[str, CalibrationRig]:
    values = raw.get("calibrations", raw.get("rigs", raw))
    rigs: list[CalibrationRig] = []
    if isinstance(values, dict):
        for calibration_id, item in values.items():
            if not isinstance(item, dict):
                raise ValueError("calibration registry entries must be objects")
            enriched = dict(item)
            enriched.setdefault("calibration_id", calibration_id)
            rigs.append(calibration_rig_from_dict(enriched))
    elif isinstance(values, list):
        rigs = [calibration_rig_from_dict(item) for item in values]
    else:
        raise ValueError("calibration registry must contain an object or list")
    registry: dict[str, CalibrationRig] = {}
    for rig in rigs:
        if rig.calibration_id in registry:
            raise ValueError(f"duplicate calibration_id: {rig.calibration_id}")
        registry[rig.calibration_id] = rig
    if not registry:
        raise ValueError("calibration registry is empty")
    return registry


def calibration_registry_sha256(registry: Mapping[str, CalibrationRig]) -> str:
    if not registry:
        raise ValueError("calibration registry is empty")
    canonical: dict[str, Any] = {}
    for calibration_id, rig in sorted(registry.items()):
        rig.validate()
        if calibration_id != rig.calibration_id:
            raise ValueError("calibration registry key must match rig calibration_id")
        canonical[calibration_id] = rig.canonical_dict()
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def calibration_registry_summary(registry: Mapping[str, CalibrationRig]) -> dict[str, Any]:
    digest = calibration_registry_sha256(registry)
    return {
        "calibration_count": len(registry),
        "calibration_registry_sha256": digest,
        "calibrations": [
            {
                "calibration_id": calibration_id,
                "sha256": rig.sha256(),
                "camera_ids": sorted(rig.camera_map()),
                "vehicle_variant": rig.vehicle_variant,
                "firmware": rig.firmware,
                "source": rig.source,
            }
            for calibration_id, rig in sorted(registry.items())
        ],
        "geometry_vector_dim": GEOMETRY_VECTOR_DIM,
        "valid": True,
    }


def calibration_profile() -> dict[str, Any]:
    return {
        "geometry_vector_dim": GEOMETRY_VECTOR_DIM,
        "intrinsic_features": ["fx/width", "fy/height", "cx/width", "cy/height", "width/height", "height/width"],
        "extrinsic_features": "camera_to_ego first 3x4 rows",
        "transform_validation": ["finite", "homogeneous_bottom_row", "rotation_row_norm", "rotation_orthogonality"],
        "immutable_rig_sha256": True,
        "immutable_registry_sha256": True,
        "live_actuation": False,
        "raw_vehicle_tx": False,
    }
