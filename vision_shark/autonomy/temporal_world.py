from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

from .hybrid import HybridShadowPlanner


@dataclass
class TemporalTrack:
    track_id: str
    cls: str
    x: float
    y: float
    vx: float
    vy: float
    confidence: float
    first_ts: float
    last_ts: float
    hits: int = 1
    misses: int = 0

    @property
    def age_s(self) -> float:
        return max(0.0, self.last_ts - self.first_ts)


class TemporalWorldModel:
    """Small deterministic temporal tracker and BEV occupancy model.

    This is an independent Vision implementation. It is not Tesla FSD code.
    It exists to add the temporal state that a single-frame planner cannot
    provide: persistent tracks, measured motion, future occupancy and a local
    free-space view for shadow/replay evaluation.
    """

    def __init__(self, *, association_gate_m: float = 4.0, stale_after_s: float = 1.0):
        self.association_gate_m = float(association_gate_m)
        self.stale_after_s = float(stale_after_s)
        self._tracks: dict[str, TemporalTrack] = {}
        self._next_id = 1
        self._last_ts: float | None = None

    def reset(self) -> None:
        self._tracks.clear()
        self._next_id = 1
        self._last_ts = None

    @staticmethod
    def _valid_detection(raw: dict[str, Any]) -> dict[str, Any] | None:
        confidence = float(raw.get("confidence", 0.5) or 0.0)
        x = float(raw.get("x", 0.0) or 0.0)
        y = float(raw.get("y", 0.0) or 0.0)
        if confidence < 0.10 or not all(math.isfinite(v) for v in (confidence, x, y)):
            return None
        return {
            "source_track_id": str(raw.get("track_id", "")),
            "cls": str(raw.get("class", raw.get("cls", "unknown"))),
            "x": x,
            "y": y,
            "confidence": confidence,
        }

    def _associate(self, detection: dict[str, Any], used: set[str], ts: float) -> str | None:
        explicit = detection["source_track_id"]
        if explicit and explicit in self._tracks and explicit not in used:
            return explicit
        best_id: str | None = None
        best_distance = float("inf")
        for track_id, track in self._tracks.items():
            if track_id in used:
                continue
            dt = max(0.0, ts - track.last_ts)
            predicted_x = track.x + track.vx * dt
            predicted_y = track.y + track.vy * dt
            distance = math.hypot(detection["x"] - predicted_x, detection["y"] - predicted_y)
            class_penalty = 0.0 if detection["cls"] == track.cls else 1.5
            score = distance + class_penalty
            if score < best_distance and distance <= self.association_gate_m:
                best_id = track_id
                best_distance = score
        return best_id

    def update(self, ts: float, detections: list[dict[str, Any]]) -> list[TemporalTrack]:
        ts = float(ts)
        if not math.isfinite(ts):
            raise ValueError("timestamp must be finite")
        if self._last_ts is not None and ts < self._last_ts:
            raise ValueError("temporal world timestamps must be monotonic")
        self._last_ts = ts

        clean = [item for raw in detections if (item := self._valid_detection(raw)) is not None]
        used: set[str] = set()
        touched: set[str] = set()

        for detection in clean:
            track_id = self._associate(detection, used, ts)
            if track_id is None:
                requested = detection["source_track_id"]
                track_id = requested if requested and requested not in self._tracks else f"t{self._next_id}"
                while track_id in self._tracks:
                    self._next_id += 1
                    track_id = f"t{self._next_id}"
                self._next_id += 1
                self._tracks[track_id] = TemporalTrack(
                    track_id=track_id,
                    cls=detection["cls"],
                    x=detection["x"],
                    y=detection["y"],
                    vx=0.0,
                    vy=0.0,
                    confidence=detection["confidence"],
                    first_ts=ts,
                    last_ts=ts,
                )
            else:
                track = self._tracks[track_id]
                dt = max(1e-3, ts - track.last_ts)
                measured_vx = (detection["x"] - track.x) / dt
                measured_vy = (detection["y"] - track.y) / dt
                alpha = 0.70
                beta = 0.45
                track.x = alpha * detection["x"] + (1.0 - alpha) * (track.x + track.vx * dt)
                track.y = alpha * detection["y"] + (1.0 - alpha) * (track.y + track.vy * dt)
                track.vx = beta * measured_vx + (1.0 - beta) * track.vx
                track.vy = beta * measured_vy + (1.0 - beta) * track.vy
                track.confidence = min(1.0, 0.65 * track.confidence + 0.35 * detection["confidence"] + 0.05)
                track.cls = detection["cls"] if detection["confidence"] >= track.confidence * 0.6 else track.cls
                track.last_ts = ts
                track.hits += 1
                track.misses = 0
            used.add(track_id)
            touched.add(track_id)

        for track_id, track in list(self._tracks.items()):
            if track_id not in touched:
                track.misses += 1
                dt = max(0.0, ts - track.last_ts)
                if dt > self.stale_after_s:
                    del self._tracks[track_id]
                else:
                    track.confidence *= 0.85

        return list(self._tracks.values())

    def predictions(self, horizons_s: tuple[float, ...] = (0.5, 1.0, 1.5, 2.0, 3.0)) -> dict[str, list[dict[str, float]]]:
        result: dict[str, list[dict[str, float]]] = {}
        for track_id, track in self._tracks.items():
            result[track_id] = [
                {
                    "dt": dt,
                    "x": track.x + track.vx * dt,
                    "y": track.y + track.vy * dt,
                    "confidence": max(0.0, min(1.0, track.confidence * math.exp(-0.18 * dt))),
                }
                for dt in horizons_s
            ]
        return result

    def occupancy_grid(
        self,
        *,
        x_min: float = -10.0,
        x_max: float = 80.0,
        y_min: float = -20.0,
        y_max: float = 20.0,
        resolution_m: float = 1.0,
        prediction_s: float = 1.0,
    ) -> dict[str, Any]:
        if resolution_m <= 0:
            raise ValueError("resolution_m must be positive")
        occupied: dict[tuple[int, int], float] = {}
        for track in self._tracks.values():
            samples = max(1, int(round(prediction_s / 0.25)))
            for index in range(samples + 1):
                dt = prediction_s * index / samples
                x = track.x + track.vx * dt
                y = track.y + track.vy * dt
                if not (x_min <= x <= x_max and y_min <= y <= y_max):
                    continue
                gx = int(math.floor((x - x_min) / resolution_m))
                gy = int(math.floor((y - y_min) / resolution_m))
                probability = max(0.05, min(1.0, track.confidence * math.exp(-0.15 * dt)))
                radius = 1 if track.cls.lower() in {"pedestrian", "cyclist", "bicycle", "motorcycle"} else 2
                for dx in range(-radius, radius + 1):
                    for dy in range(-radius, radius + 1):
                        key = (gx + dx, gy + dy)
                        if key[0] < 0 or key[1] < 0:
                            continue
                        occupied[key] = max(occupied.get(key, 0.0), probability)
        return {
            "bounds_m": {"x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max},
            "resolution_m": resolution_m,
            "prediction_s": prediction_s,
            "occupied": [
                {"gx": gx, "gy": gy, "probability": probability}
                for (gx, gy), probability in sorted(occupied.items())
            ],
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "track_count": len(self._tracks),
            "tracks": [asdict(track) | {"age_s": track.age_s} for track in self._tracks.values()],
            "predictions": self.predictions(),
            "occupancy": self.occupancy_grid(),
        }


class TemporalShadowRuntime:
    """Stateful temporal world + HybridShadowPlanner composition.

    Inputs are observations only. Outputs remain shadow trajectories with no
    actuator transport, no CAN transmit primitive and no live-control authority.
    """

    def __init__(self):
        self.world = TemporalWorldModel()
        self.planner = HybridShadowPlanner()

    def reset(self) -> dict[str, Any]:
        self.world.reset()
        return {"reset": True, "shadow_only": True, "live_actuation": False, "raw_vehicle_tx": False}

    def step(self, frame: dict[str, Any]) -> dict[str, Any]:
        ts = float(frame.get("timestamp_s", 0.0))
        detections = list(frame.get("detections") or [])
        tracks = self.world.update(ts, detections)
        fused_detections = [
            {
                "track_id": track.track_id,
                "class": track.cls,
                "x": track.x,
                "y": track.y,
                "vx": track.vx,
                "vy": track.vy,
                "confidence": track.confidence,
                "age_s": max(0.0, ts - track.last_ts),
            }
            for track in tracks
        ]
        planner_result = self.planner.run(
            ego_speed_ms=float(frame.get("ego_speed_ms", 0.0)),
            detections=fused_detections,
            lane_path=list(frame.get("lane_path") or []),
            model_path=list(frame.get("model_path") or []),
            cruise_target_ms=frame.get("cruise_target_ms"),
            model_longitudinal=frame.get("model_longitudinal"),
            world_age_s=float(frame.get("world_age_s", 0.0)),
            model_age_s=float(frame.get("model_age_s", 0.0)),
            calibration_valid=bool(frame.get("calibration_valid", True)),
            model_latency_ms=float(frame.get("model_latency_ms", 0.0)),
        )
        return {
            "architecture": "temporal_vision_shadow_v1",
            "timestamp_s": ts,
            "temporal_world": self.world.snapshot(),
            "planner": planner_result,
            "shadow_only": True,
            "live_actuation": False,
            "raw_vehicle_tx": False,
        }
