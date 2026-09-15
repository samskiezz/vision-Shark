from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from statistics import fmean
from typing import Any, Iterable


_EPS = 1e-6


@dataclass(frozen=True)
class PathPoint:
    x: float
    y: float
    confidence: float = 1.0


@dataclass(frozen=True)
class TrackedObject:
    track_id: str
    cls: str
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    confidence: float = 0.5
    age_s: float = 0.0


@dataclass(frozen=True)
class LeadEstimate:
    present: bool
    track_id: str | None = None
    distance_m: float | None = None
    relative_speed_ms: float | None = None
    time_headway_s: float | None = None
    ttc_s: float | None = None
    confidence: float = 0.0
    source: str = "none"


@dataclass
class ShadowTrajectoryPoint:
    t: float
    x: float
    y: float
    heading: float
    speed: float
    accel: float
    jerk: float
    curvature: float


@dataclass
class ShadowTrajectory:
    generator: str
    points: list[ShadowTrajectoryPoint]
    confidence: float
    source_confidence: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float | None = None
    guardian: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlannerConfig:
    horizon_s: float = 5.0
    dt_s: float = 0.2
    lane_half_width_m: float = 1.9
    object_half_width_m: float = 1.0
    collision_radius_m: float = 2.2
    hard_ttc_s: float = 1.5
    caution_ttc_s: float = 4.0
    minimum_time_gap_s: float = 1.8
    standstill_gap_m: float = 4.0
    max_accel_ms2: float = 2.0
    comfortable_decel_ms2: float = 2.5
    emergency_shadow_decel_ms2: float = 4.5
    max_jerk_ms3: float = 2.5
    max_curvature_inv_m: float = 0.22
    max_speed_ms: float = 55.0
    stale_world_s: float = 0.5
    stale_model_s: float = 0.5
    min_model_confidence: float = 0.35
    min_lane_confidence: float = 0.25


class HybridShadowPlanner:
    """Hybrid open-loop planner for replay/shadow evaluation only.

    The planner intentionally has no CAN, DoIP, J2534 or actuator transport.
    It produces candidate trajectories, deterministic safety evidence and an
    abstract shadow target. Its output must never be interpreted as a command.
    """

    def __init__(self, config: PlannerConfig | None = None):
        self.config = config or PlannerConfig()

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    @staticmethod
    def _polyline(points: Iterable[dict[str, Any] | PathPoint]) -> list[PathPoint]:
        output: list[PathPoint] = []
        for raw in points:
            if isinstance(raw, PathPoint):
                point = raw
            else:
                point = PathPoint(
                    x=float(raw.get("x", 0.0)),
                    y=float(raw.get("y", 0.0)),
                    confidence=float(raw.get("confidence", raw.get("probability", 1.0)) or 0.0),
                )
            if math.isfinite(point.x) and math.isfinite(point.y) and point.x >= 0.0:
                output.append(point)
        output.sort(key=lambda p: p.x)
        return output

    @staticmethod
    def _sample_path(path: list[PathPoint], x: float) -> tuple[float, float]:
        """Return interpolated lateral y and local heading for forward distance x."""
        if not path:
            return 0.0, 0.0
        if len(path) == 1:
            return path[0].y, 0.0
        if x <= path[0].x:
            a, b = path[0], path[1]
        elif x >= path[-1].x:
            a, b = path[-2], path[-1]
        else:
            a, b = path[0], path[1]
            for left, right in zip(path, path[1:], strict=False):
                if left.x <= x <= right.x:
                    a, b = left, right
                    break
        dx = max(_EPS, b.x - a.x)
        ratio = self_or_zero((x - a.x) / dx)
        ratio = max(0.0, min(1.0, ratio))
        y = a.y + ratio * (b.y - a.y)
        heading = math.atan2(b.y - a.y, dx)
        return y, heading

    @staticmethod
    def _path_confidence(path: list[PathPoint]) -> float:
        if not path:
            return 0.0
        return HybridShadowPlanner._clamp(fmean(p.confidence for p in path), 0.0, 1.0)

    def normalize_objects(self, detections: Iterable[dict[str, Any]]) -> list[TrackedObject]:
        output: list[TrackedObject] = []
        for index, raw in enumerate(detections or []):
            confidence = float(raw.get("confidence", 0.5) or 0.0)
            age_s = max(0.0, float(raw.get("age_s", 0.0) or 0.0))
            if confidence < 0.15 or age_s > 2.0:
                continue
            values = {
                "track_id": str(raw.get("track_id", index)),
                "cls": str(raw.get("class", raw.get("cls", "unknown"))),
                "x": float(raw.get("x", 0.0) or 0.0),
                "y": float(raw.get("y", 0.0) or 0.0),
                "vx": float(raw.get("vx", 0.0) or 0.0),
                "vy": float(raw.get("vy", 0.0) or 0.0),
                "confidence": confidence,
                "age_s": age_s,
            }
            if all(math.isfinite(values[key]) for key in ("x", "y", "vx", "vy", "confidence", "age_s")):
                output.append(TrackedObject(**values))
        return output

    def closest_in_path_object(
        self,
        ego_speed_ms: float,
        objects: list[TrackedObject],
        path: list[PathPoint],
    ) -> LeadEstimate:
        best: tuple[float, TrackedObject, float] | None = None
        for obj in objects:
            if obj.x <= 0.0:
                continue
            path_y, _ = self._sample_path(path, obj.x)
            lateral_error = abs(obj.y - path_y)
            gate = self.config.lane_half_width_m + self.config.object_half_width_m
            if lateral_error > gate:
                continue
            distance = max(0.0, math.hypot(obj.x, obj.y - path_y))
            quality = obj.confidence * max(0.0, 1.0 - obj.age_s / 2.0)
            candidate = (distance, obj, quality)
            if best is None or candidate[0] < best[0]:
                best = candidate
        if best is None:
            return LeadEstimate(False)
        distance, obj, quality = best
        relative_speed = obj.vx - ego_speed_ms
        headway = distance / max(ego_speed_ms, 0.1)
        closing_speed = max(0.0, -relative_speed)
        ttc = distance / closing_speed if closing_speed > 0.05 else None
        return LeadEstimate(
            present=True,
            track_id=obj.track_id,
            distance_m=distance,
            relative_speed_ms=relative_speed,
            time_headway_s=headway,
            ttc_s=ttc,
            confidence=self._clamp(quality, 0.0, 1.0),
            source="object_path_association",
        )

    def risk_metrics(self, ego_speed_ms: float, lead: LeadEstimate) -> dict[str, Any]:
        if not lead.present:
            return {
                "lead_present": False,
                "risk": "clear",
                "ttc_s": None,
                "time_headway_s": None,
                "required_gap_m": self.config.standstill_gap_m + ego_speed_ms * self.config.minimum_time_gap_s,
            }
        ttc = lead.ttc_s
        headway = lead.time_headway_s
        if ttc is not None and ttc <= self.config.hard_ttc_s:
            risk = "critical"
        elif (ttc is not None and ttc <= self.config.caution_ttc_s) or (
            headway is not None and headway < self.config.minimum_time_gap_s
        ):
            risk = "caution"
        else:
            risk = "nominal"
        return {
            "lead_present": True,
            "risk": risk,
            "distance_m": lead.distance_m,
            "relative_speed_ms": lead.relative_speed_ms,
            "ttc_s": ttc,
            "time_headway_s": headway,
            "required_gap_m": self.config.standstill_gap_m + ego_speed_ms * self.config.minimum_time_gap_s,
            "lead_confidence": lead.confidence,
        }

    def longitudinal_candidates(
        self,
        ego_speed_ms: float,
        cruise_target_ms: float,
        lead: LeadEstimate,
        model: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        c = self.config
        cruise_target_ms = self._clamp(float(cruise_target_ms), 0.0, c.max_speed_ms)
        candidates: list[dict[str, Any]] = [
            {
                "source": "cruise",
                "target_speed_ms": cruise_target_ms,
                "target_accel_ms2": self._clamp((cruise_target_ms - ego_speed_ms) * 0.6, -c.comfortable_decel_ms2, c.max_accel_ms2),
                "confidence": 1.0,
            }
        ]

        if lead.present and lead.distance_m is not None:
            required_gap = c.standstill_gap_m + max(0.0, ego_speed_ms) * c.minimum_time_gap_s
            gap_error = lead.distance_m - required_gap
            relative_speed = lead.relative_speed_ms or 0.0
            lead_speed = max(0.0, ego_speed_ms + relative_speed)
            follow_target = max(0.0, min(cruise_target_ms, lead_speed + 0.35 * gap_error))
            decel = self._clamp((follow_target - ego_speed_ms) * 0.9, -c.emergency_shadow_decel_ms2, c.max_accel_ms2)
            if lead.ttc_s is not None and lead.ttc_s <= c.hard_ttc_s:
                decel = min(decel, -c.emergency_shadow_decel_ms2)
                follow_target = min(follow_target, max(0.0, ego_speed_ms + decel * 1.0))
            candidates.append(
                {
                    "source": "lead_gap",
                    "target_speed_ms": follow_target,
                    "target_accel_ms2": decel,
                    "confidence": lead.confidence,
                    "distance_m": lead.distance_m,
                    "ttc_s": lead.ttc_s,
                }
            )

        if model:
            confidence = self._clamp(float(model.get("confidence", 0.0) or 0.0), 0.0, 1.0)
            if confidence >= c.min_model_confidence:
                speed = model.get("target_speed_ms")
                accel = model.get("target_accel_ms2")
                if speed is not None or accel is not None:
                    target_speed = cruise_target_ms if speed is None else self._clamp(float(speed), 0.0, c.max_speed_ms)
                    target_accel = (
                        self._clamp((target_speed - ego_speed_ms) * 0.6, -c.emergency_shadow_decel_ms2, c.max_accel_ms2)
                        if accel is None
                        else self._clamp(float(accel), -c.emergency_shadow_decel_ms2, c.max_accel_ms2)
                    )
                    candidates.append(
                        {
                            "source": "model",
                            "target_speed_ms": target_speed,
                            "target_accel_ms2": target_accel,
                            "confidence": confidence,
                        }
                    )

        # Conservative arbitration: never choose a faster longitudinal candidate than another
        # valid candidate when the purpose is safety-oriented shadow planning.
        chosen = min(candidates, key=lambda item: (item["target_speed_ms"], item["target_accel_ms2"]))
        for item in candidates:
            item["selected"] = item is chosen
        return candidates

    def _blend_paths(self, lane: list[PathPoint], model: list[PathPoint]) -> list[PathPoint]:
        if not lane:
            return list(model)
        if not model:
            return list(lane)
        lane_conf = self._path_confidence(lane)
        model_conf = self._path_confidence(model)
        denom = max(_EPS, lane_conf + model_conf)
        model_weight = model_conf / denom
        xs = sorted({round(p.x, 3) for p in lane + model})
        output = []
        for x in xs:
            lane_y, _ = self._sample_path(lane, x)
            model_y, _ = self._sample_path(model, x)
            output.append(
                PathPoint(
                    x=x,
                    y=lane_y * (1.0 - model_weight) + model_y * model_weight,
                    confidence=self._clamp((lane_conf + model_conf) / 2.0, 0.0, 1.0),
                )
            )
        return output

    @staticmethod
    def _curvature_from_three(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
        ab = math.hypot(b[0] - a[0], b[1] - a[1])
        bc = math.hypot(c[0] - b[0], c[1] - b[1])
        ca = math.hypot(a[0] - c[0], a[1] - c[1])
        denom = max(_EPS, ab * bc * ca)
        cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        return 2.0 * cross / denom

    def trajectory_from_path(
        self,
        generator: str,
        path: list[PathPoint],
        ego_speed_ms: float,
        target_speed_ms: float,
        target_accel_ms2: float,
        confidence: float,
        source_confidence: dict[str, float] | None = None,
    ) -> ShadowTrajectory:
        c = self.config
        points: list[ShadowTrajectoryPoint] = []
        speed = max(0.0, ego_speed_ms)
        accel = 0.0
        distance = 0.0
        prev_xy: list[tuple[float, float]] = []
        count = max(1, int(round(c.horizon_s / c.dt_s)))
        for index in range(count):
            desired_accel = self._clamp((target_speed_ms - speed) * 0.7, -c.emergency_shadow_decel_ms2, c.max_accel_ms2)
            desired_accel = min(desired_accel, target_accel_ms2) if target_accel_ms2 < desired_accel else desired_accel
            delta = self._clamp(desired_accel - accel, -c.max_jerk_ms3 * c.dt_s, c.max_jerk_ms3 * c.dt_s)
            next_accel = self._clamp(accel + delta, -c.emergency_shadow_decel_ms2, c.max_accel_ms2)
            jerk = (next_accel - accel) / c.dt_s
            accel = next_accel
            speed = self._clamp(speed + accel * c.dt_s, 0.0, c.max_speed_ms)
            distance += speed * c.dt_s
            y, heading = self._sample_path(path, distance)
            x = distance
            prev_xy.append((x, y))
            curvature = 0.0
            if len(prev_xy) >= 3:
                curvature = self._curvature_from_three(prev_xy[-3], prev_xy[-2], prev_xy[-1])
            points.append(
                ShadowTrajectoryPoint(
                    t=(index + 1) * c.dt_s,
                    x=x,
                    y=y,
                    heading=heading,
                    speed=speed,
                    accel=accel,
                    jerk=jerk,
                    curvature=curvature,
                )
            )
        return ShadowTrajectory(
            generator=generator,
            points=points,
            confidence=self._clamp(confidence, 0.0, 1.0),
            source_confidence=dict(source_confidence or {}),
        )

    def controlled_stop(self, ego_speed_ms: float) -> ShadowTrajectory:
        c = self.config
        path = [PathPoint(0.0, 0.0), PathPoint(max(10.0, ego_speed_ms * c.horizon_s), 0.0)]
        return self.trajectory_from_path(
            "controlled_stop",
            path,
            ego_speed_ms,
            0.0,
            -c.comfortable_decel_ms2,
            1.0,
            {"guardian": 1.0},
        )

    def guardian(self, trajectory: ShadowTrajectory, objects: list[TrackedObject], world_age_s: float) -> dict[str, Any]:
        c = self.config
        reasons: list[str] = []
        min_object_distance = float("inf")
        if world_age_s > c.stale_world_s and trajectory.generator != "controlled_stop":
            reasons.append("world_stale")
        for point in trajectory.points:
            if point.speed < -_EPS or point.speed > c.max_speed_ms + _EPS:
                reasons.append("speed_bound")
                break
            if point.accel > c.max_accel_ms2 + _EPS or point.accel < -c.emergency_shadow_decel_ms2 - _EPS:
                reasons.append("accel_bound")
                break
            if abs(point.jerk) > c.max_jerk_ms3 + 0.05:
                reasons.append("jerk_bound")
                break
            if abs(point.curvature) > c.max_curvature_inv_m:
                reasons.append("curvature_bound")
                break
            for obj in objects:
                ox = obj.x + obj.vx * point.t
                oy = obj.y + obj.vy * point.t
                distance = math.hypot(point.x - ox, point.y - oy)
                min_object_distance = min(min_object_distance, distance)
                if distance < c.collision_radius_m:
                    reasons.append("predicted_collision")
                    break
            if "predicted_collision" in reasons:
                break
        return {
            "pass": not reasons,
            "reasons": sorted(set(reasons)),
            "min_predicted_object_distance_m": None if math.isinf(min_object_distance) else min_object_distance,
            "live_actuation_allowed": False,
            "raw_vehicle_tx": False,
        }

    def score(self, trajectory: ShadowTrajectory, reference_path: list[PathPoint], objects: list[TrackedObject]) -> float:
        if not trajectory.points:
            return float("inf")
        lateral_errors = []
        jerk = []
        curvature = []
        proximity = []
        for point in trajectory.points:
            ref_y, _ = self._sample_path(reference_path, point.x)
            lateral_errors.append(abs(point.y - ref_y))
            jerk.append(abs(point.jerk))
            curvature.append(abs(point.curvature))
            for obj in objects:
                ox = obj.x + obj.vx * point.t
                oy = obj.y + obj.vy * point.t
                distance = math.hypot(point.x - ox, point.y - oy)
                proximity.append(1.0 / max(0.25, distance))
        confidence_penalty = 1.0 - trajectory.confidence
        return (
            4.0 * (max(proximity) if proximity else 0.0)
            + 1.5 * fmean(lateral_errors)
            + 0.25 * fmean(jerk)
            + 2.0 * fmean(curvature)
            + 1.5 * confidence_penalty
        )

    def run(
        self,
        *,
        ego_speed_ms: float,
        detections: Iterable[dict[str, Any]] = (),
        lane_path: Iterable[dict[str, Any]] = (),
        model_path: Iterable[dict[str, Any]] = (),
        cruise_target_ms: float | None = None,
        model_longitudinal: dict[str, Any] | None = None,
        world_age_s: float = 0.0,
        model_age_s: float = 0.0,
        calibration_valid: bool = True,
        model_latency_ms: float = 0.0,
    ) -> dict[str, Any]:
        c = self.config
        ego_speed_ms = self._clamp(float(ego_speed_ms), 0.0, c.max_speed_ms)
        lane = self._polyline(lane_path)
        model = self._polyline(model_path)
        objects = self.normalize_objects(detections)
        lane_conf = self._path_confidence(lane)
        model_conf = self._path_confidence(model)
        cruise = ego_speed_ms + 3.0 if cruise_target_ms is None else float(cruise_target_ms)

        odd_reasons: list[str] = []
        if world_age_s > c.stale_world_s:
            odd_reasons.append("world_stale")
        if model_age_s > c.stale_model_s and model:
            odd_reasons.append("model_stale")
        if model_latency_ms > 250.0:
            odd_reasons.append("model_latency")
        if not calibration_valid:
            odd_reasons.append("calibration_invalid")
        if lane_conf < c.min_lane_confidence and model_conf < c.min_model_confidence:
            odd_reasons.append("path_unavailable")

        reference = lane if lane_conf >= c.min_lane_confidence else model
        lead = self.closest_in_path_object(ego_speed_ms, objects, reference)
        risk = self.risk_metrics(ego_speed_ms, lead)
        longitudinal = self.longitudinal_candidates(ego_speed_ms, cruise, lead, model_longitudinal)
        chosen_long = next(item for item in longitudinal if item["selected"])

        candidates: list[ShadowTrajectory] = []
        if lane_conf >= c.min_lane_confidence:
            candidates.append(
                self.trajectory_from_path(
                    "lane_path",
                    lane,
                    ego_speed_ms,
                    chosen_long["target_speed_ms"],
                    chosen_long["target_accel_ms2"],
                    lane_conf,
                    {"lane": lane_conf},
                )
            )
        if model_conf >= c.min_model_confidence and model_age_s <= c.stale_model_s:
            candidates.append(
                self.trajectory_from_path(
                    "model_path",
                    model,
                    ego_speed_ms,
                    chosen_long["target_speed_ms"],
                    chosen_long["target_accel_ms2"],
                    model_conf,
                    {"model": model_conf},
                )
            )
        if lane_conf >= c.min_lane_confidence and model_conf >= c.min_model_confidence and model_age_s <= c.stale_model_s:
            hybrid = self._blend_paths(lane, model)
            candidates.append(
                self.trajectory_from_path(
                    "hybrid_path",
                    hybrid,
                    ego_speed_ms,
                    chosen_long["target_speed_ms"],
                    chosen_long["target_accel_ms2"],
                    (lane_conf + model_conf) / 2.0,
                    {"lane": lane_conf, "model": model_conf},
                )
            )
        candidates.append(self.controlled_stop(ego_speed_ms))

        for candidate in candidates:
            candidate.guardian = self.guardian(candidate, objects, world_age_s)
            candidate.score = self.score(candidate, reference or [PathPoint(0.0, 0.0)], objects)
            if candidate.generator == "controlled_stop":
                candidate.score += 2.0
            if odd_reasons and candidate.generator != "controlled_stop":
                candidate.score += 100.0
            if not candidate.guardian["pass"]:
                candidate.score += 1000.0

        safe_candidates = [item for item in candidates if item.guardian["pass"]]
        selected = min(safe_candidates or candidates, key=lambda item: item.score if item.score is not None else float("inf"))
        point = selected.points[min(2, len(selected.points) - 1)] if selected.points else None

        return {
            "architecture": "hybrid_shadow_v2",
            "inspirations": [
                "openpilot process-separated model/radar/planning and conservative longitudinal arbitration",
                "Autoware Vision Pilot multi-model longitudinal/lateral fusion and safety-guardian separation",
            ],
            "odd": {"inside": not odd_reasons, "reasons": odd_reasons},
            "path_confidence": {"lane": lane_conf, "model": model_conf},
            "lead": asdict(lead),
            "risk": risk,
            "longitudinal_candidates": longitudinal,
            "candidates": [
                {
                    "generator": item.generator,
                    "confidence": item.confidence,
                    "score": item.score,
                    "guardian": item.guardian,
                    "points": len(item.points),
                }
                for item in candidates
            ],
            "selected": {
                "generator": selected.generator,
                "confidence": selected.confidence,
                "score": selected.score,
                "guardian": selected.guardian,
                "points": [asdict(item) for item in selected.points],
            },
            "control_target": None
            if point is None
            else {
                "curvature": point.curvature,
                "acceleration": point.accel,
                "speed": point.speed,
                "source": selected.generator,
                "live_actuation_allowed": False,
            },
            "shadow_only": True,
            "live_actuation": False,
            "raw_vehicle_tx": False,
        }


def self_or_zero(value: float) -> float:
    return value if math.isfinite(value) else 0.0
