from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from statistics import fmean
from typing import Any, Iterable


@dataclass(frozen=True)
class TrajectoryMetric:
    ade_m: float | None
    fde_m: float | None
    speed_mae_ms: float | None
    accel_mae_ms2: float | None
    samples: int


@dataclass(frozen=True)
class HardCaseScore:
    score: float
    priority: str
    reasons: tuple[str, ...]
    fingerprint: str


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _point_at(points: list[dict[str, Any]], t: float) -> dict[str, float] | None:
    clean = []
    for raw in points:
        try:
            item = {
                "t": float(raw.get("t", 0.0)),
                "x": float(raw.get("x", 0.0)),
                "y": float(raw.get("y", 0.0)),
                "speed": float(raw.get("speed", raw.get("speed_ms", 0.0)) or 0.0),
                "accel": float(raw.get("accel", raw.get("acceleration", 0.0)) or 0.0),
            }
        except (TypeError, ValueError):
            continue
        if item["t"] >= 0 and all(math.isfinite(value) for value in item.values()):
            clean.append(item)
    clean.sort(key=lambda item: item["t"])
    if not clean:
        return None
    if t <= clean[0]["t"]:
        return clean[0]
    if t >= clean[-1]["t"]:
        return clean[-1]
    for left, right in zip(clean, clean[1:], strict=False):
        if left["t"] <= t <= right["t"]:
            dt = max(1e-9, right["t"] - left["t"])
            ratio = (t - left["t"]) / dt
            return {
                key: left[key] + ratio * (right[key] - left[key])
                for key in ("t", "x", "y", "speed", "accel")
            }
    return clean[-1]


def trajectory_metrics(predicted: Iterable[dict[str, Any]], reference: Iterable[dict[str, Any]]) -> TrajectoryMetric:
    predicted_list = list(predicted)
    reference_list = list(reference)
    times = []
    for raw in reference_list:
        t = _finite(raw.get("t"), -1.0)
        if t >= 0:
            times.append(t)
    if not times:
        return TrajectoryMetric(None, None, None, None, 0)
    position_errors: list[float] = []
    speed_errors: list[float] = []
    accel_errors: list[float] = []
    for t in sorted(set(times)):
        pred = _point_at(predicted_list, t)
        ref = _point_at(reference_list, t)
        if pred is None or ref is None:
            continue
        position_errors.append(math.hypot(pred["x"] - ref["x"], pred["y"] - ref["y"]))
        speed_errors.append(abs(pred["speed"] - ref["speed"]))
        accel_errors.append(abs(pred["accel"] - ref["accel"]))
    if not position_errors:
        return TrajectoryMetric(None, None, None, None, 0)
    return TrajectoryMetric(
        ade_m=fmean(position_errors),
        fde_m=position_errors[-1],
        speed_mae_ms=fmean(speed_errors),
        accel_mae_ms2=fmean(accel_errors),
        samples=len(position_errors),
    )


def policy_disagreement(candidates: Iterable[dict[str, Any]], horizon_s: float = 3.0) -> dict[str, Any]:
    points: list[tuple[str, float, float]] = []
    for index, candidate in enumerate(candidates or []):
        point = _point_at(list(candidate.get("points") or []), horizon_s)
        if point is None:
            continue
        points.append((str(candidate.get("candidate_id", index)), point["x"], point["y"]))
    pairwise: list[dict[str, Any]] = []
    for index, left in enumerate(points):
        for right in points[index + 1:]:
            distance = math.hypot(left[1] - right[1], left[2] - right[2])
            pairwise.append({"left": left[0], "right": right[0], "distance_m": distance})
    maximum = max((item["distance_m"] for item in pairwise), default=0.0)
    mean = fmean(item["distance_m"] for item in pairwise) if pairwise else 0.0
    return {
        "horizon_s": float(horizon_s),
        "candidate_count": len(points),
        "mean_pairwise_distance_m": mean,
        "max_pairwise_distance_m": maximum,
        "pairs": pairwise[:128],
    }


def scenario_fingerprint(scenario: dict[str, Any]) -> str:
    compact = {
        "tags": sorted(str(item) for item in scenario.get("scenario_tags", scenario.get("tags", [])) or []),
        "classes": sorted(str(item) for item in scenario.get("object_classes", []) or []),
        "weather": str(scenario.get("weather", "unknown")),
        "lighting": str(scenario.get("lighting", "unknown")),
        "road_type": str(scenario.get("road_type", "unknown")),
        "speed_bucket": round(_finite(scenario.get("ego_speed_ms")) / 5.0) * 5,
        "route_action": str(scenario.get("route_action", "unknown")),
        "risk_bucket": round(_finite(scenario.get("collision_risk")) * 10.0) / 10.0,
    }
    payload = json.dumps(compact, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def hard_case_score(scenario: dict[str, Any]) -> HardCaseScore:
    score = 0.0
    reasons: set[str] = set(str(item) for item in scenario.get("scenario_tags", scenario.get("tags", [])) or [])

    if bool(scenario.get("driver_intervention", False)):
        score += 35.0
        reasons.add("driver_intervention")
    if bool(scenario.get("safety_fallback", False)):
        score += 25.0
        reasons.add("safety_fallback")

    risk = max(0.0, min(1.0, _finite(scenario.get("collision_risk"))))
    if risk > 0:
        score += 35.0 * risk
        reasons.add("predicted_collision_risk")

    clearance = scenario.get("min_clearance_m")
    if clearance is not None:
        clearance_value = max(0.0, _finite(clearance))
        if clearance_value < 8.0:
            score += max(0.0, 18.0 * (1.0 - clearance_value / 8.0))
            reasons.add("low_clearance")

    disagreement = max(0.0, _finite(scenario.get("policy_disagreement_m")))
    if disagreement > 1.0:
        score += min(20.0, disagreement * 2.5)
        reasons.add("policy_disagreement")

    uncertainty = max(0.0, min(1.0, _finite(scenario.get("perception_uncertainty"))))
    if uncertainty > 0.35:
        score += 15.0 * uncertainty
        reasons.add("perception_uncertainty")

    if bool(scenario.get("camera_desync", False)):
        score += 8.0
        reasons.add("camera_desync")
    if bool(scenario.get("occlusion", False)):
        score += 8.0
        reasons.add("occlusion")
    if bool(scenario.get("rare_object", False)):
        score += 10.0
        reasons.add("rare_object")
    if bool(scenario.get("route_ambiguity", False)):
        score += 8.0
        reasons.add("route_ambiguity")

    score = min(100.0, score)
    if score >= 70:
        priority = "critical"
    elif score >= 45:
        priority = "high"
    elif score >= 20:
        priority = "medium"
    else:
        priority = "routine"
    return HardCaseScore(score, priority, tuple(sorted(reasons)), scenario_fingerprint(scenario))


class FleetDataEngine:
    """Fleet/shadow hard-case selection and training-manifest builder.

    Inspired by the public Tesla data-engine loop: deploy in shadow, detect
    interventions/disagreement/uncertainty, mine similar cases, deduplicate for
    diversity, label/review, retrain and re-evaluate. This module performs only
    local scoring/selection; it does not upload vehicle data or control a car.
    """

    def score_scenario(self, scenario: dict[str, Any]) -> dict[str, Any]:
        result = hard_case_score(scenario)
        return {
            "score": result.score,
            "priority": result.priority,
            "reasons": list(result.reasons),
            "fingerprint": result.fingerprint,
        }

    def select(
        self,
        scenarios: Iterable[dict[str, Any]],
        *,
        limit: int = 100,
        min_score: float = 20.0,
        max_per_fingerprint: int = 2,
    ) -> dict[str, Any]:
        limit = max(1, min(10000, int(limit)))
        max_per_fingerprint = max(1, min(100, int(max_per_fingerprint)))
        scored: list[dict[str, Any]] = []
        for index, scenario in enumerate(scenarios):
            score = self.score_scenario(scenario)
            scored.append({"index": index, "scenario": scenario, **score})
        scored.sort(key=lambda item: (float(item["score"]), item["priority"]), reverse=True)
        selected: list[dict[str, Any]] = []
        fingerprint_counts: dict[str, int] = {}
        for item in scored:
            if item["score"] < min_score:
                continue
            fingerprint = item["fingerprint"]
            if fingerprint_counts.get(fingerprint, 0) >= max_per_fingerprint:
                continue
            fingerprint_counts[fingerprint] = fingerprint_counts.get(fingerprint, 0) + 1
            selected.append(item)
            if len(selected) >= limit:
                break
        return {
            "input_count": len(scored),
            "selected_count": len(selected),
            "min_score": float(min_score),
            "max_per_fingerprint": max_per_fingerprint,
            "selected": selected,
            "shadow_only": True,
            "data_uploaded": False,
        }

    def training_manifest(
        self,
        scenarios: Iterable[dict[str, Any]],
        *,
        limit: int = 100,
        min_score: float = 20.0,
    ) -> dict[str, Any]:
        selection = self.select(scenarios, limit=limit, min_score=min_score)
        manifest = []
        for rank, item in enumerate(selection["selected"], 1):
            scenario = item["scenario"]
            manifest.append(
                {
                    "rank": rank,
                    "scenario_id": str(scenario.get("scenario_id", item["index"])),
                    "fingerprint": item["fingerprint"],
                    "score": item["score"],
                    "priority": item["priority"],
                    "reasons": item["reasons"],
                    "recording_id": scenario.get("recording_id"),
                    "time_window": scenario.get("time_window"),
                    "label_requirements": sorted(set(
                        ["ego_trajectory", "dynamic_agents", "free_space"]
                        + (["lane_topology"] if "route_ambiguity" in item["reasons"] else [])
                        + (["occlusion_state"] if "occlusion" in item["reasons"] else [])
                    )),
                    "review_state": "unreviewed",
                }
            )
        digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        return {
            "manifest_version": 1,
            "sha256": digest,
            "items": manifest,
            "selection": {key: value for key, value in selection.items() if key != "selected"},
            "purpose": "offline hard-case labeling/training queue",
            "data_uploaded": False,
            "live_actuation": False,
        }


def benchmark_policy(
    *,
    candidates: Iterable[dict[str, Any]],
    reference_trajectory: Iterable[dict[str, Any]],
    selected_candidate_id: str | None = None,
) -> dict[str, Any]:
    rows = []
    for index, candidate in enumerate(candidates or []):
        candidate_id = str(candidate.get("candidate_id", index))
        metrics = trajectory_metrics(candidate.get("points") or [], reference_trajectory)
        rows.append(
            {
                "candidate_id": candidate_id,
                "source": candidate.get("source"),
                "probability": candidate.get("probability"),
                "selected": candidate_id == selected_candidate_id,
                "metrics": {
                    "ade_m": metrics.ade_m,
                    "fde_m": metrics.fde_m,
                    "speed_mae_ms": metrics.speed_mae_ms,
                    "accel_mae_ms2": metrics.accel_mae_ms2,
                    "samples": metrics.samples,
                },
            }
        )
    valid = [row for row in rows if row["metrics"]["ade_m"] is not None]
    best = min(valid, key=lambda row: row["metrics"]["ade_m"]) if valid else None
    disagreement = policy_disagreement(candidates)
    return {
        "candidates": rows,
        "best_by_ade": None if best is None else best["candidate_id"],
        "policy_disagreement": disagreement,
        "shadow_only": True,
        "live_actuation": False,
    }
