from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from statistics import fmean
from typing import Any, Iterable

from .hybrid import HybridShadowPlanner
from .temporal_world import TemporalWorldModel


_EPS = 1e-9


@dataclass(frozen=True)
class CameraCalibration:
    camera_id: str
    fx: float
    fy: float
    cx: float
    cy: float
    camera_to_ego: tuple[tuple[float, float, float, float], ...]
    width: int | None = None
    height: int | None = None

    def __post_init__(self) -> None:
        if not self.camera_id:
            raise ValueError("camera_id is required")
        if self.fx <= 0 or self.fy <= 0:
            raise ValueError("camera focal lengths must be positive")
        if len(self.camera_to_ego) != 4 or any(len(row) != 4 for row in self.camera_to_ego):
            raise ValueError("camera_to_ego must be a 4x4 homogeneous transform")
        values = [self.fx, self.fy, self.cx, self.cy, *[v for row in self.camera_to_ego for v in row]]
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("camera calibration must contain only finite values")
        bottom = self.camera_to_ego[3]
        if any(abs(a - b) > 1e-6 for a, b in zip(bottom, (0.0, 0.0, 0.0, 1.0), strict=True)):
            raise ValueError("camera_to_ego must have homogeneous bottom row [0,0,0,1]")


@dataclass(frozen=True)
class CameraFrame:
    camera_id: str
    timestamp_s: float
    frame_id: str | None = None
    exposure_ms: float | None = None
    latency_ms: float | None = None


@dataclass(frozen=True)
class FusedDetection:
    track_hint: str
    cls: str
    x: float
    y: float
    z: float
    confidence: float
    source_cameras: tuple[str, ...]
    source_count: int


@dataclass(frozen=True)
class MotionHypothesis:
    hypothesis_id: str
    probability: float
    points: tuple[tuple[float, float, float], ...]
    kind: str


@dataclass
class LaneRecord:
    lane_id: str
    centerline: list[tuple[float, float]]
    left_neighbor: str | None = None
    right_neighbor: str | None = None
    predecessors: list[str] = field(default_factory=list)
    successors: list[str] = field(default_factory=list)
    speed_limit_ms: float | None = None
    route_relevance: float = 0.0
    confidence: float = 1.0


@dataclass(frozen=True)
class CandidatePoint:
    t: float
    x: float
    y: float
    speed: float
    accel: float = 0.0


@dataclass
class PolicyCandidate:
    candidate_id: str
    source: str
    probability: float
    points: list[CandidatePoint]
    metadata: dict[str, Any] = field(default_factory=dict)


class MultiCameraSynchronizer:
    """Evaluate temporal alignment of camera observations.

    The runtime accepts already captured camera frames/features and calibration
    metadata. It does not acquire cameras itself. Synchronization quality is
    exposed as evidence so downstream planners can degrade gracefully.
    """

    def __init__(self, expected_cameras: Iterable[str] = (), tolerance_ms: float = 35.0):
        self.expected_cameras = tuple(dict.fromkeys(str(item) for item in expected_cameras if str(item)))
        self.tolerance_ms = float(tolerance_ms)
        if self.tolerance_ms <= 0:
            raise ValueError("tolerance_ms must be positive")

    def evaluate(self, frames: Iterable[dict[str, Any] | CameraFrame]) -> dict[str, Any]:
        clean: list[CameraFrame] = []
        for raw in frames:
            frame = raw if isinstance(raw, CameraFrame) else CameraFrame(
                camera_id=str(raw.get("camera_id", "")),
                timestamp_s=float(raw.get("timestamp_s", 0.0)),
                frame_id=None if raw.get("frame_id") is None else str(raw.get("frame_id")),
                exposure_ms=None if raw.get("exposure_ms") is None else float(raw.get("exposure_ms")),
                latency_ms=None if raw.get("latency_ms") is None else float(raw.get("latency_ms")),
            )
            if not frame.camera_id or not math.isfinite(frame.timestamp_s):
                continue
            clean.append(frame)
        if not clean:
            return {
                "synchronized": False,
                "camera_count": 0,
                "span_ms": None,
                "missing": list(self.expected_cameras),
                "duplicate_cameras": [],
                "reason": "no_camera_frames",
            }
        by_camera: dict[str, list[CameraFrame]] = {}
        for frame in clean:
            by_camera.setdefault(frame.camera_id, []).append(frame)
        duplicate = sorted(camera for camera, items in by_camera.items() if len(items) > 1)
        selected = [max(items, key=lambda item: item.timestamp_s) for items in by_camera.values()]
        stamps = [item.timestamp_s for item in selected]
        span_ms = (max(stamps) - min(stamps)) * 1000.0
        expected = set(self.expected_cameras)
        observed = set(by_camera)
        missing = sorted(expected - observed)
        synchronized = span_ms <= self.tolerance_ms and not missing
        latency = [item.latency_ms for item in selected if item.latency_ms is not None and math.isfinite(item.latency_ms)]
        return {
            "synchronized": synchronized,
            "camera_count": len(selected),
            "span_ms": span_ms,
            "tolerance_ms": self.tolerance_ms,
            "missing": missing,
            "duplicate_cameras": duplicate,
            "mean_latency_ms": None if not latency else fmean(latency),
            "max_latency_ms": None if not latency else max(latency),
            "reason": "ok" if synchronized else ("missing_camera" if missing else "camera_desync"),
        }


def calibration_from_dict(raw: dict[str, Any]) -> CameraCalibration:
    transform = raw.get("camera_to_ego")
    if not isinstance(transform, list) or len(transform) != 4:
        raise ValueError("camera_to_ego must be a 4x4 list")
    matrix = tuple(tuple(float(value) for value in row) for row in transform)
    return CameraCalibration(
        camera_id=str(raw.get("camera_id", "")),
        fx=float(raw.get("fx", 0.0)),
        fy=float(raw.get("fy", 0.0)),
        cx=float(raw.get("cx", 0.0)),
        cy=float(raw.get("cy", 0.0)),
        camera_to_ego=matrix,
        width=None if raw.get("width") is None else int(raw.get("width")),
        height=None if raw.get("height") is None else int(raw.get("height")),
    )


def _transform_point(matrix: tuple[tuple[float, float, float, float], ...], xyz: tuple[float, float, float]) -> tuple[float, float, float]:
    vector = (xyz[0], xyz[1], xyz[2], 1.0)
    out = [sum(matrix[row][column] * vector[column] for column in range(4)) for row in range(4)]
    if abs(out[3]) < _EPS:
        raise ValueError("camera transform produced invalid homogeneous coordinate")
    return out[0] / out[3], out[1] / out[3], out[2] / out[3]


def project_pixel_depth_to_ego(calibration: CameraCalibration, u: float, v: float, depth_m: float) -> tuple[float, float, float]:
    """Project a depth-associated pixel into the ego coordinate frame.

    Camera convention is x-right, y-down, z-forward. The supplied 4x4
    camera_to_ego transform defines the vehicle-frame convention explicitly.
    """
    u = float(u)
    v = float(v)
    depth_m = float(depth_m)
    if depth_m <= 0 or not all(math.isfinite(value) for value in (u, v, depth_m)):
        raise ValueError("pixel coordinates and positive depth must be finite")
    if calibration.width is not None and not 0 <= u < calibration.width:
        raise ValueError("pixel u is outside calibrated image width")
    if calibration.height is not None and not 0 <= v < calibration.height:
        raise ValueError("pixel v is outside calibrated image height")
    camera_x = (u - calibration.cx) * depth_m / calibration.fx
    camera_y = (v - calibration.cy) * depth_m / calibration.fy
    camera_z = depth_m
    return _transform_point(calibration.camera_to_ego, (camera_x, camera_y, camera_z))


def normalize_camera_detections(
    detections: Iterable[dict[str, Any]],
    calibrations: dict[str, CameraCalibration],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, raw in enumerate(detections or []):
        confidence = float(raw.get("confidence", 0.5) or 0.0)
        if confidence < 0.05 or not math.isfinite(confidence):
            continue
        camera_id = str(raw.get("camera_id", ""))
        cls = str(raw.get("class", raw.get("cls", "unknown")))
        if all(key in raw for key in ("x", "y")):
            x = float(raw.get("x", 0.0))
            y = float(raw.get("y", 0.0))
            z = float(raw.get("z", 0.0) or 0.0)
        elif all(key in raw for key in ("u", "v", "depth_m")):
            calibration = calibrations.get(camera_id)
            if calibration is None:
                continue
            try:
                x, y, z = project_pixel_depth_to_ego(
                    calibration,
                    float(raw["u"]),
                    float(raw["v"]),
                    float(raw["depth_m"]),
                )
            except (TypeError, ValueError):
                continue
        else:
            continue
        if not all(math.isfinite(value) for value in (x, y, z)):
            continue
        output.append(
            {
                "source_track_id": str(raw.get("track_id", raw.get("source_track_id", index))),
                "camera_id": camera_id,
                "class": cls,
                "x": x,
                "y": y,
                "z": z,
                "confidence": max(0.0, min(1.0, confidence)),
            }
        )
    return output


def fuse_multicamera_detections(detections: Iterable[dict[str, Any]], gate_m: float = 2.5) -> list[FusedDetection]:
    """Geometry-aware late fusion baseline for already localized detections.

    It intentionally avoids claiming learned feature-level fusion. Detections are
    clustered by class and ego-frame distance, then confidence-weighted.
    """
    gate_m = float(gate_m)
    if gate_m <= 0:
        raise ValueError("gate_m must be positive")
    items = list(detections)
    clusters: list[list[dict[str, Any]]] = []
    for item in sorted(items, key=lambda value: float(value.get("confidence", 0.0)), reverse=True):
        best_index: int | None = None
        best_distance = float("inf")
        cls = str(item.get("class", "unknown"))
        for index, cluster in enumerate(clusters):
            if str(cluster[0].get("class", "unknown")) != cls:
                continue
            center_x = fmean(float(member["x"]) for member in cluster)
            center_y = fmean(float(member["y"]) for member in cluster)
            distance = math.hypot(float(item["x"]) - center_x, float(item["y"]) - center_y)
            if distance < best_distance and distance <= gate_m:
                best_index = index
                best_distance = distance
        if best_index is None:
            clusters.append([item])
        else:
            clusters[best_index].append(item)

    fused: list[FusedDetection] = []
    for index, cluster in enumerate(clusters):
        weights = [max(0.01, float(item.get("confidence", 0.0))) for item in cluster]
        total = sum(weights)
        x = sum(float(item["x"]) * weight for item, weight in zip(cluster, weights, strict=True)) / total
        y = sum(float(item["y"]) * weight for item, weight in zip(cluster, weights, strict=True)) / total
        z = sum(float(item.get("z", 0.0)) * weight for item, weight in zip(cluster, weights, strict=True)) / total
        independent_cameras = sorted({str(item.get("camera_id", "")) for item in cluster if item.get("camera_id")})
        confidence = 1.0
        for item in cluster:
            confidence *= 1.0 - max(0.0, min(0.999, float(item.get("confidence", 0.0))))
        confidence = 1.0 - confidence
        track_hint = next((str(item.get("source_track_id")) for item in cluster if item.get("source_track_id")), f"fusion-{index}")
        fused.append(
            FusedDetection(
                track_hint=track_hint,
                cls=str(cluster[0].get("class", "unknown")),
                x=x,
                y=y,
                z=z,
                confidence=max(0.0, min(1.0, confidence)),
                source_cameras=tuple(independent_cameras),
                source_count=len(cluster),
            )
        )
    return fused


class LaneTopologyGraph:
    def __init__(self, lanes: Iterable[dict[str, Any]] = ()):
        self.lanes: dict[str, LaneRecord] = {}
        for index, raw in enumerate(lanes or []):
            lane_id = str(raw.get("lane_id", index))
            points: list[tuple[float, float]] = []
            for point in raw.get("centerline", raw.get("points", [])) or []:
                x = float(point.get("x", 0.0))
                y = float(point.get("y", 0.0))
                if math.isfinite(x) and math.isfinite(y):
                    points.append((x, y))
            if len(points) < 2:
                continue
            self.lanes[lane_id] = LaneRecord(
                lane_id=lane_id,
                centerline=points,
                left_neighbor=None if raw.get("left_neighbor") is None else str(raw.get("left_neighbor")),
                right_neighbor=None if raw.get("right_neighbor") is None else str(raw.get("right_neighbor")),
                predecessors=[str(item) for item in raw.get("predecessors", [])],
                successors=[str(item) for item in raw.get("successors", [])],
                speed_limit_ms=None if raw.get("speed_limit_ms") is None else float(raw.get("speed_limit_ms")),
                route_relevance=max(0.0, min(1.0, float(raw.get("route_relevance", 0.0) or 0.0))),
                confidence=max(0.0, min(1.0, float(raw.get("confidence", 1.0) or 0.0))),
            )

    @staticmethod
    def _point_segment_distance(px: float, py: float, a: tuple[float, float], b: tuple[float, float]) -> float:
        vx, vy = b[0] - a[0], b[1] - a[1]
        wx, wy = px - a[0], py - a[1]
        denom = vx * vx + vy * vy
        if denom < _EPS:
            return math.hypot(px - a[0], py - a[1])
        t = max(0.0, min(1.0, (wx * vx + wy * vy) / denom))
        return math.hypot(px - (a[0] + t * vx), py - (a[1] + t * vy))

    def nearest_lane(self, x: float = 0.0, y: float = 0.0) -> dict[str, Any] | None:
        best: tuple[float, LaneRecord] | None = None
        for lane in self.lanes.values():
            distance = min(
                self._point_segment_distance(x, y, a, b)
                for a, b in zip(lane.centerline, lane.centerline[1:], strict=False)
            )
            if best is None or distance < best[0]:
                best = (distance, lane)
        if best is None:
            return None
        distance, lane = best
        return {"lane_id": lane.lane_id, "distance_m": distance, "confidence": lane.confidence, "route_relevance": lane.route_relevance}

    def route_candidates(self, current_lane_id: str | None = None) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for lane in self.lanes.values():
            topology_bonus = 0.0
            if current_lane_id and lane.lane_id == current_lane_id:
                topology_bonus = 0.15
            elif current_lane_id and current_lane_id in lane.predecessors:
                topology_bonus = 0.10
            score = min(1.0, lane.route_relevance * 0.7 + lane.confidence * 0.3 + topology_bonus)
            output.append(
                {
                    "lane_id": lane.lane_id,
                    "score": score,
                    "left_neighbor": lane.left_neighbor,
                    "right_neighbor": lane.right_neighbor,
                    "successors": lane.successors,
                    "speed_limit_ms": lane.speed_limit_ms,
                    "points": [{"x": x, "y": y} for x, y in lane.centerline],
                }
            )
        return sorted(output, key=lambda item: item["score"], reverse=True)

    def snapshot(self) -> dict[str, Any]:
        nearest = self.nearest_lane()
        return {
            "lane_count": len(self.lanes),
            "nearest_lane": nearest,
            "route_candidates": self.route_candidates(None if nearest is None else nearest["lane_id"]),
        }


class MultimodalAgentForecaster:
    """Deterministic multi-hypothesis forecasting baseline.

    The interface mirrors modern planning-oriented stacks: each tracked agent
    exposes multiple weighted futures instead of a single extrapolation.
    """

    def __init__(self, horizons_s: tuple[float, ...] = (0.5, 1.0, 2.0, 3.0, 4.0)):
        self.horizons_s = tuple(float(value) for value in horizons_s)

    def _points(self, x: float, y: float, vx: float, vy: float, *, ax: float = 0.0, ay: float = 0.0, yaw_rate: float = 0.0) -> tuple[tuple[float, float, float], ...]:
        output: list[tuple[float, float, float]] = []
        speed = math.hypot(vx, vy)
        heading = math.atan2(vy, vx) if speed > 0.1 else 0.0
        for dt in self.horizons_s:
            if abs(yaw_rate) > 1e-4 and speed > 0.1:
                theta = heading + yaw_rate * dt
                radius = speed / yaw_rate
                px = x + radius * (math.sin(theta) - math.sin(heading))
                py = y - radius * (math.cos(theta) - math.cos(heading))
            else:
                px = x + vx * dt + 0.5 * ax * dt * dt
                py = y + vy * dt + 0.5 * ay * dt * dt
            output.append((dt, px, py))
        return tuple(output)

    def forecast(self, track: dict[str, Any]) -> list[MotionHypothesis]:
        x = float(track.get("x", 0.0))
        y = float(track.get("y", 0.0))
        vx = float(track.get("vx", 0.0))
        vy = float(track.get("vy", 0.0))
        cls = str(track.get("cls", track.get("class", "unknown"))).lower()
        base_confidence = max(0.0, min(1.0, float(track.get("confidence", 0.5) or 0.0)))
        moving = math.hypot(vx, vy) > 0.5
        hypotheses: list[MotionHypothesis] = [
            MotionHypothesis("constant_velocity", 0.55 if moving else 0.70, self._points(x, y, vx, vy), "kinematic")
        ]
        if moving:
            speed = math.hypot(vx, vy)
            brake_accel = -min(3.0, speed / max(self.horizons_s[-1], 0.5))
            heading = math.atan2(vy, vx)
            hypotheses.append(
                MotionHypothesis(
                    "decelerate",
                    0.20,
                    self._points(x, y, vx, vy, ax=brake_accel * math.cos(heading), ay=brake_accel * math.sin(heading)),
                    "kinematic",
                )
            )
            turn_prob = 0.125
            hypotheses.append(MotionHypothesis("turn_left", turn_prob, self._points(x, y, vx, vy, yaw_rate=0.12), "kinematic"))
            hypotheses.append(MotionHypothesis("turn_right", turn_prob, self._points(x, y, vx, vy, yaw_rate=-0.12), "kinematic"))
        elif cls in {"pedestrian", "cyclist", "bicycle"}:
            hypotheses.append(MotionHypothesis("cross_left", 0.15, self._points(x, y, vx, -1.0), "crossing"))
            hypotheses.append(MotionHypothesis("cross_right", 0.15, self._points(x, y, vx, 1.0), "crossing"))
        total = sum(item.probability for item in hypotheses)
        if total <= 0:
            total = 1.0
        normalized: list[MotionHypothesis] = []
        for item in hypotheses:
            probability = (item.probability / total) * (0.5 + 0.5 * base_confidence)
            normalized.append(MotionHypothesis(item.hypothesis_id, probability, item.points, item.kind))
        return normalized


class OccupancyFlowBuilder:
    def __init__(self, x_min: float = -15.0, x_max: float = 100.0, y_min: float = -30.0, y_max: float = 30.0, resolution_m: float = 1.0):
        if resolution_m <= 0:
            raise ValueError("resolution_m must be positive")
        self.x_min = float(x_min)
        self.x_max = float(x_max)
        self.y_min = float(y_min)
        self.y_max = float(y_max)
        self.resolution_m = float(resolution_m)

    def _cell(self, x: float, y: float) -> tuple[int, int] | None:
        if not self.x_min <= x <= self.x_max or not self.y_min <= y <= self.y_max:
            return None
        return (
            int(math.floor((x - self.x_min) / self.resolution_m)),
            int(math.floor((y - self.y_min) / self.resolution_m)),
        )

    def build(self, forecasts: dict[str, list[MotionHypothesis]]) -> dict[str, Any]:
        horizons: dict[float, dict[tuple[int, int], dict[str, float]]] = {}
        for track_id, hypotheses in forecasts.items():
            del track_id
            for hypothesis in hypotheses:
                for dt, x, y in hypothesis.points:
                    cell = self._cell(x, y)
                    if cell is None:
                        continue
                    layer = horizons.setdefault(dt, {})
                    entry = layer.setdefault(cell, {"probability": 0.0, "flow_x": 0.0, "flow_y": 0.0, "weight": 0.0})
                    p = max(0.0, min(1.0, hypothesis.probability))
                    entry["probability"] = 1.0 - (1.0 - entry["probability"]) * (1.0 - p)
                    entry["weight"] += p
        layers = []
        for dt, cells in sorted(horizons.items()):
            layers.append(
                {
                    "dt": dt,
                    "occupied": [
                        {"gx": gx, "gy": gy, "probability": values["probability"]}
                        for (gx, gy), values in sorted(cells.items())
                    ],
                }
            )
        return {
            "bounds_m": {"x_min": self.x_min, "x_max": self.x_max, "y_min": self.y_min, "y_max": self.y_max},
            "resolution_m": self.resolution_m,
            "layers": layers,
        }


class CounterfactualTrajectoryEvaluator:
    """Score policy trajectories against weighted future-agent hypotheses.

    This is a transparent kinematic rollout evaluator, not a learned world model.
    It provides the same action-conditioned evaluation seam that can later be
    backed by a learned simulator without changing the API.
    """

    def __init__(self, collision_radius_m: float = 2.2):
        self.collision_radius_m = float(collision_radius_m)

    @staticmethod
    def _sample_prediction(hypothesis: MotionHypothesis, t: float) -> tuple[float, float]:
        points = hypothesis.points
        if not points:
            return 0.0, 0.0
        if t <= points[0][0]:
            return points[0][1], points[0][2]
        if t >= points[-1][0]:
            return points[-1][1], points[-1][2]
        for left, right in zip(points, points[1:], strict=False):
            if left[0] <= t <= right[0]:
                ratio = (t - left[0]) / max(_EPS, right[0] - left[0])
                return left[1] + ratio * (right[1] - left[1]), left[2] + ratio * (right[2] - left[2])
        return points[-1][1], points[-1][2]

    def evaluate(
        self,
        candidate: PolicyCandidate,
        forecasts: dict[str, list[MotionHypothesis]],
        lane_graph: LaneTopologyGraph,
    ) -> dict[str, Any]:
        if not candidate.points:
            return {"candidate_id": candidate.candidate_id, "valid": False, "score": float("inf"), "reasons": ["empty_trajectory"]}
        expected_collision_risk = 0.0
        min_clearance = float("inf")
        collision_modes: list[dict[str, Any]] = []
        for point in candidate.points:
            for track_id, hypotheses in forecasts.items():
                for hypothesis in hypotheses:
                    ox, oy = self._sample_prediction(hypothesis, point.t)
                    clearance = math.hypot(point.x - ox, point.y - oy)
                    min_clearance = min(min_clearance, clearance)
                    if clearance < self.collision_radius_m:
                        expected_collision_risk += hypothesis.probability
                        collision_modes.append(
                            {
                                "track_id": track_id,
                                "hypothesis": hypothesis.hypothesis_id,
                                "t": point.t,
                                "clearance_m": clearance,
                                "probability": hypothesis.probability,
                            }
                        )
        jerk: list[float] = []
        for left, right in zip(candidate.points, candidate.points[1:], strict=False):
            dt = max(_EPS, right.t - left.t)
            jerk.append(abs((right.accel - left.accel) / dt))
        nearest_lane = lane_graph.nearest_lane() if lane_graph.lanes else None
        route_penalty = 0.0
        if lane_graph.lanes:
            for point in candidate.points:
                nearest = lane_graph.nearest_lane(point.x, point.y)
                if nearest is not None:
                    route_penalty += min(5.0, nearest["distance_m"]) * 0.05
            route_penalty /= max(1, len(candidate.points))
        comfort_penalty = fmean(jerk) * 0.15 if jerk else 0.0
        clearance_penalty = 0.0 if math.isinf(min_clearance) else 1.0 / max(0.25, min_clearance)
        probability_penalty = 1.0 - max(0.0, min(1.0, candidate.probability))
        score = expected_collision_risk * 100.0 + clearance_penalty * 5.0 + route_penalty + comfort_penalty + probability_penalty
        return {
            "candidate_id": candidate.candidate_id,
            "source": candidate.source,
            "valid": True,
            "score": score,
            "expected_collision_risk": expected_collision_risk,
            "min_clearance_m": None if math.isinf(min_clearance) else min_clearance,
            "collision_modes": collision_modes[:64],
            "mean_abs_jerk": 0.0 if not jerk else fmean(jerk),
            "route_penalty": route_penalty,
            "nearest_ego_lane": nearest_lane,
            "probability": candidate.probability,
        }


def _candidate_from_dict(raw: dict[str, Any], index: int) -> PolicyCandidate | None:
    points: list[CandidatePoint] = []
    for point in raw.get("points", []) or []:
        try:
            item = CandidatePoint(
                t=float(point.get("t", 0.0)),
                x=float(point.get("x", 0.0)),
                y=float(point.get("y", 0.0)),
                speed=float(point.get("speed", 0.0)),
                accel=float(point.get("accel", 0.0) or 0.0),
            )
        except (TypeError, ValueError):
            continue
        if item.t >= 0 and all(math.isfinite(value) for value in (item.t, item.x, item.y, item.speed, item.accel)):
            points.append(item)
    points.sort(key=lambda item: item.t)
    if len(points) < 2:
        return None
    return PolicyCandidate(
        candidate_id=str(raw.get("candidate_id", f"model-{index}")),
        source=str(raw.get("source", "model_policy")),
        probability=max(0.0, min(1.0, float(raw.get("probability", raw.get("confidence", 0.5)) or 0.0))),
        points=points,
        metadata=dict(raw.get("metadata") or {}),
    )


def _candidate_from_hybrid(result: dict[str, Any]) -> PolicyCandidate | None:
    selected = result.get("selected") or {}
    points: list[CandidatePoint] = []
    for raw in selected.get("points", []) or []:
        points.append(
            CandidatePoint(
                t=float(raw.get("t", 0.0)),
                x=float(raw.get("x", 0.0)),
                y=float(raw.get("y", 0.0)),
                speed=float(raw.get("speed", 0.0)),
                accel=float(raw.get("accel", 0.0)),
            )
        )
    if len(points) < 2:
        return None
    return PolicyCandidate(
        candidate_id=f"fallback-{selected.get('generator', 'hybrid')}",
        source="deterministic_hybrid_fallback",
        probability=max(0.0, min(1.0, float(selected.get("confidence", 0.5) or 0.0))),
        points=points,
        metadata={"hybrid_score": selected.get("score")},
    )


class ScenarioMiner:
    def tags(
        self,
        *,
        sync: dict[str, Any],
        tracks: list[dict[str, Any]],
        evaluations: list[dict[str, Any]],
        lane_graph: LaneTopologyGraph,
        model_latency_ms: float,
    ) -> list[str]:
        tags: set[str] = set()
        if not sync.get("synchronized", False):
            tags.add(str(sync.get("reason", "camera_sync_issue")))
        if model_latency_ms > 200.0:
            tags.add("high_model_latency")
        if not lane_graph.lanes:
            tags.add("lane_topology_missing")
        if any(float(track.get("confidence", 0.0)) < 0.35 for track in tracks):
            tags.add("low_track_confidence")
        if any(int(track.get("misses", 0)) > 0 for track in tracks):
            tags.add("occlusion_or_track_gap")
        if evaluations:
            best = min(evaluations, key=lambda item: float(item.get("score", float("inf"))))
            if float(best.get("expected_collision_risk", 0.0)) > 0.0:
                tags.add("predicted_collision_risk")
            if best.get("min_clearance_m") is not None and float(best["min_clearance_m"]) < 4.0:
                tags.add("low_clearance")
            scores = sorted(float(item.get("score", 0.0)) for item in evaluations if math.isfinite(float(item.get("score", 0.0))))
            if len(scores) >= 2 and abs(scores[1] - scores[0]) < 0.5:
                tags.add("policy_ambiguity")
        return sorted(tags)


class PlanningWorldRuntime:
    """Planning-oriented world representation and shadow policy evaluator.

    Design influences are public/open research concepts from Tesla's published
    Autonomy/AI presentations, BEVFormer, UniAD, VAD, AutoE2E, openpilot world
    models and NVIDIA Alpamayo. No proprietary Tesla FSD source is included.

    This runtime is observation/replay/shadow only and deliberately exposes no
    steering, braking, propulsion, CAN transmit, flashing or security bypass.
    """

    def __init__(self):
        self.world = TemporalWorldModel(association_gate_m=3.5, stale_after_s=1.25)
        self.forecaster = MultimodalAgentForecaster()
        self.occupancy = OccupancyFlowBuilder()
        self.evaluator = CounterfactualTrajectoryEvaluator()
        self.hybrid = HybridShadowPlanner()
        self.miner = ScenarioMiner()
        self._last_timestamp: float | None = None
        self._steps = 0

    def reset(self) -> dict[str, Any]:
        self.world.reset()
        self._last_timestamp = None
        self._steps = 0
        return {
            "reset": True,
            "architecture": "planning_world_v2",
            "shadow_only": True,
            "live_actuation": False,
            "raw_vehicle_tx": False,
        }

    @staticmethod
    def architecture_profile() -> dict[str, Any]:
        return {
            "name": "Vision Planning World v2",
            "principles": [
                "synchronized multi-camera evidence",
                "explicit camera geometry baseline",
                "persistent temporal tracks",
                "vector lane topology",
                "multimodal agent futures",
                "time-indexed occupancy",
                "multimodal ego policy candidates",
                "counterfactual candidate evaluation",
                "hard-case mining",
                "deterministic safety fallback",
            ],
            "research_influences": {
                "Tesla Autonomy/AI": "fleet learning, temporal vector-space representation, occupancy/flow, end-to-end policy scaling",
                "BEVFormer": "spatiotemporal BEV memory and calibrated multi-camera fusion",
                "UniAD": "planning-oriented unified task interfaces",
                "VAD": "vectorized agents and map constraints",
                "AutoE2E": "multi-camera temporal policy and pluggable fusion",
                "openpilot 0.11": "policy training/evaluation through an action-conditioned learned world model",
                "Alpamayo": "reasoning/action prediction research interface for long-tail scenarios",
            },
            "implemented_now": [
                "camera synchronization quality",
                "camera calibration validation",
                "pixel+depth to ego projection",
                "late multi-camera geometric object fusion",
                "temporal object tracking",
                "lane topology graph",
                "multimodal kinematic agent forecasting",
                "time-indexed occupancy grid",
                "multimodal policy candidate adapter",
                "counterfactual kinematic rollout evaluation",
                "scenario tags",
            ],
            "not_claimed": [
                "Tesla proprietary FSD source or weights",
                "learned feature-level BEV fusion",
                "learned occupancy network",
                "learned world-model video synthesis",
                "automotive-grade autonomous driving validation",
            ],
            "shadow_only": True,
            "live_actuation": False,
            "raw_vehicle_tx": False,
        }

    def step(self, frame: dict[str, Any]) -> dict[str, Any]:
        timestamp = float(frame.get("timestamp_s", 0.0))
        if not math.isfinite(timestamp):
            raise ValueError("timestamp_s must be finite")
        if self._last_timestamp is not None and timestamp < self._last_timestamp:
            raise ValueError("planning world timestamps must be monotonic")
        self._last_timestamp = timestamp
        self._steps += 1

        calibration_list = frame.get("calibrations") or []
        calibrations: dict[str, CameraCalibration] = {}
        calibration_errors: list[str] = []
        for raw in calibration_list:
            try:
                calibration = calibration_from_dict(raw)
                calibrations[calibration.camera_id] = calibration
            except (TypeError, ValueError) as exc:
                calibration_errors.append(str(exc))

        expected_cameras = frame.get("expected_cameras") or list(calibrations)
        synchronizer = MultiCameraSynchronizer(
            expected_cameras=expected_cameras,
            tolerance_ms=float(frame.get("sync_tolerance_ms", 35.0)),
        )
        sync = synchronizer.evaluate(frame.get("camera_frames") or [])

        localized = normalize_camera_detections(frame.get("camera_detections") or frame.get("detections") or [], calibrations)
        fused = fuse_multicamera_detections(localized, gate_m=float(frame.get("fusion_gate_m", 2.5)))
        temporal_input = [
            {
                "track_id": detection.track_hint,
                "class": detection.cls,
                "x": detection.x,
                "y": detection.y,
                "confidence": detection.confidence,
            }
            for detection in fused
        ]
        tracks = self.world.update(timestamp, temporal_input)
        track_rows = [asdict(track) | {"age_s": track.age_s} for track in tracks]

        forecasts: dict[str, list[MotionHypothesis]] = {
            track.track_id: self.forecaster.forecast(asdict(track)) for track in tracks
        }
        occupancy = self.occupancy.build(forecasts)
        lane_graph = LaneTopologyGraph(frame.get("lanes") or [])

        policy_candidates: list[PolicyCandidate] = []
        for index, raw in enumerate(frame.get("policy_candidates") or []):
            candidate = _candidate_from_dict(raw, index)
            if candidate is not None:
                policy_candidates.append(candidate)

        lane_path = frame.get("lane_path") or []
        model_path = frame.get("model_path") or []
        if not lane_path and lane_graph.lanes:
            route = lane_graph.route_candidates()
            if route:
                lane_path = [{"x": item["x"], "y": item["y"], "confidence": route[0]["score"]} for item in route[0]["points"]]
        hybrid = self.hybrid.run(
            ego_speed_ms=float(frame.get("ego_speed_ms", 0.0)),
            detections=[
                {
                    "track_id": track.track_id,
                    "class": track.cls,
                    "x": track.x,
                    "y": track.y,
                    "vx": track.vx,
                    "vy": track.vy,
                    "confidence": track.confidence,
                    "age_s": max(0.0, timestamp - track.last_ts),
                }
                for track in tracks
            ],
            lane_path=lane_path,
            model_path=model_path,
            cruise_target_ms=frame.get("cruise_target_ms"),
            model_longitudinal=frame.get("model_longitudinal"),
            world_age_s=float(frame.get("world_age_s", 0.0)),
            model_age_s=float(frame.get("model_age_s", 0.0)),
            calibration_valid=bool(frame.get("calibration_valid", not calibration_errors)),
            model_latency_ms=float(frame.get("model_latency_ms", 0.0)),
        )
        fallback = _candidate_from_hybrid(hybrid)
        if fallback is not None:
            policy_candidates.append(fallback)

        evaluations = [self.evaluator.evaluate(candidate, forecasts, lane_graph) for candidate in policy_candidates]
        valid = [item for item in evaluations if item.get("valid") and math.isfinite(float(item.get("score", float("inf"))))]
        selected_eval = min(valid, key=lambda item: float(item["score"])) if valid else None
        selected_candidate = None
        if selected_eval is not None:
            selected_candidate = next(
                (candidate for candidate in policy_candidates if candidate.candidate_id == selected_eval["candidate_id"]),
                None,
            )

        model_latency_ms = float(frame.get("model_latency_ms", 0.0))
        scenario_tags = self.miner.tags(
            sync=sync,
            tracks=track_rows,
            evaluations=evaluations,
            lane_graph=lane_graph,
            model_latency_ms=model_latency_ms,
        )
        if calibration_errors:
            scenario_tags = sorted(set(scenario_tags) | {"calibration_invalid"})

        return {
            "architecture": "planning_world_v2",
            "step": self._steps,
            "timestamp_s": timestamp,
            "camera_sync": sync,
            "calibration": {
                "loaded": sorted(calibrations),
                "errors": calibration_errors,
                "valid": not calibration_errors,
            },
            "multicamera_fusion": {
                "input_detections": len(list(frame.get("camera_detections") or frame.get("detections") or [])),
                "localized_detections": len(localized),
                "fused_detections": [asdict(item) for item in fused],
                "method": "geometry_aware_late_fusion",
                "learned_feature_fusion": False,
            },
            "temporal_world": self.world.snapshot(),
            "lane_topology": lane_graph.snapshot(),
            "agent_forecasts": {
                track_id: [asdict(item) for item in hypotheses] for track_id, hypotheses in forecasts.items()
            },
            "occupancy_flow": occupancy,
            "policy": {
                "candidate_count": len(policy_candidates),
                "evaluations": evaluations,
                "selected": None if selected_candidate is None else {
                    "candidate_id": selected_candidate.candidate_id,
                    "source": selected_candidate.source,
                    "probability": selected_candidate.probability,
                    "points": [asdict(point) for point in selected_candidate.points],
                    "evaluation": selected_eval,
                },
                "fallback_hybrid": hybrid,
            },
            "scenario_mining": {"tags": scenario_tags, "hard_case": bool(scenario_tags)},
            "architecture_profile": self.architecture_profile(),
            "shadow_only": True,
            "live_actuation": False,
            "raw_vehicle_tx": False,
        }
