from __future__ import annotations

import math
from typing import Any


SUPPORTED_MODEL_FAMILIES = {
    "meteor": {
        "reference": "AutowareFoundation METEOR",
        "inputs": "8 surround cameras + calibration + ego speed",
        "outputs": [
            "bev_lanes",
            "depth",
            "3d_detections",
            "segmentation",
            "occupancy",
            "occupancy_flow",
            "agent_forecasting",
            "traffic_lights",
            "risk_field",
            "multimodal_trajectory",
        ],
    },
    "auto_e2e": {
        "reference": "AutowareFoundation AutoE2E",
        "inputs": "multi-camera + history + egomotion",
        "outputs": ["future_acceleration", "future_curvature", "trajectory"],
    },
    "openpilot_policy": {
        "reference": "comma.ai openpilot learned driving policy",
        "inputs": "camera history + vehicle state",
        "outputs": ["curvature", "acceleration", "policy_confidence"],
    },
    "alpamayo": {
        "reference": "NVIDIA Alpamayo research VLA",
        "inputs": "multi-camera/video + driving context + optional reasoning prompt",
        "outputs": ["reasoning_trace", "trajectory", "action_prediction"],
    },
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def integrate_curvature_accel(
    *,
    ego_speed_ms: float,
    controls: list[dict[str, Any]],
    dt_s: float,
    candidate_id: str,
    source: str,
    probability: float = 0.5,
    wheelbase_m: float = 3.0,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert curvature/acceleration predictions into an ego-frame trajectory.

    This deterministic bicycle/arc integration is an interchange adapter, not a
    vehicle controller. It creates comparable shadow-policy candidates from
    model families that emit controls instead of Cartesian future points.
    """
    dt_s = float(dt_s)
    if dt_s <= 0 or dt_s > 1.0:
        raise ValueError("dt_s must be in (0, 1]")
    if wheelbase_m <= 0:
        raise ValueError("wheelbase_m must be positive")
    speed = max(0.0, float(ego_speed_ms))
    x = 0.0
    y = 0.0
    heading = 0.0
    points: list[dict[str, float]] = []
    for index, raw in enumerate(controls):
        accel = _clamp(float(raw.get("accel", raw.get("acceleration", 0.0)) or 0.0), -8.0, 5.0)
        if raw.get("curvature") is not None:
            curvature = _clamp(float(raw.get("curvature", 0.0) or 0.0), -0.5, 0.5)
        elif raw.get("steering_angle_rad") is not None:
            steering = _clamp(float(raw.get("steering_angle_rad", 0.0) or 0.0), -1.2, 1.2)
            curvature = math.tan(steering) / wheelbase_m
        else:
            curvature = 0.0
        speed = max(0.0, speed + accel * dt_s)
        heading += speed * curvature * dt_s
        x += speed * math.cos(heading) * dt_s
        y += speed * math.sin(heading) * dt_s
        points.append(
            {
                "t": (index + 1) * dt_s,
                "x": x,
                "y": y,
                "speed": speed,
                "accel": accel,
                "curvature": curvature,
                "heading": heading,
            }
        )
    if len(points) < 2:
        raise ValueError("at least two control samples are required")
    return {
        "candidate_id": candidate_id,
        "source": source,
        "probability": _clamp(float(probability), 0.0, 1.0),
        "points": points,
        "metadata": dict(metadata or {}),
    }


def _normalize_xy_trajectory(raw: dict[str, Any], *, index: int, source: str) -> dict[str, Any] | None:
    points: list[dict[str, float]] = []
    for point_index, point in enumerate(raw.get("points", raw.get("trajectory", [])) or []):
        try:
            t = float(point.get("t", point_index * float(raw.get("dt_s", 0.2))))
            x = float(point.get("x", 0.0))
            y = float(point.get("y", 0.0))
            speed = float(point.get("speed", point.get("speed_ms", 0.0)) or 0.0)
            accel = float(point.get("accel", point.get("acceleration", 0.0)) or 0.0)
        except (TypeError, ValueError):
            continue
        if t < 0 or not all(math.isfinite(value) for value in (t, x, y, speed, accel)):
            continue
        points.append({"t": t, "x": x, "y": y, "speed": speed, "accel": accel})
    if len(points) < 2:
        return None
    return {
        "candidate_id": str(raw.get("candidate_id", raw.get("id", f"{source}-{index}"))),
        "source": source,
        "probability": _clamp(float(raw.get("probability", raw.get("confidence", 0.5)) or 0.0), 0.0, 1.0),
        "points": sorted(points, key=lambda item: item["t"]),
        "metadata": dict(raw.get("metadata") or {}),
    }


def adapt_meteor(output: dict[str, Any], *, ego_speed_ms: float) -> dict[str, Any]:
    del ego_speed_ms
    trajectories = output.get("trajectories", output.get("multimodal_trajectory", [])) or []
    candidates = []
    for index, raw in enumerate(trajectories):
        candidate = _normalize_xy_trajectory(raw, index=index, source="meteor_e2e")
        if candidate is not None:
            candidates.append(candidate)
    return {
        "model_family": "meteor",
        "policy_candidates": candidates,
        "lanes": list(output.get("lanes", output.get("bev_lanes", [])) or []),
        "camera_detections": list(output.get("detections_3d", output.get("objects", [])) or []),
        "model_products": {
            "depth": output.get("depth"),
            "segmentation": output.get("segmentation"),
            "occupancy": output.get("occupancy"),
            "occupancy_flow": output.get("occupancy_flow"),
            "agent_forecasts": output.get("agent_forecasts"),
            "traffic_lights": output.get("traffic_lights"),
            "risk_field": output.get("risk_field"),
        },
    }


def adapt_auto_e2e(output: dict[str, Any], *, ego_speed_ms: float) -> dict[str, Any]:
    trajectories = output.get("trajectories") or []
    candidates: list[dict[str, Any]] = []
    for index, raw in enumerate(trajectories):
        candidate = _normalize_xy_trajectory(raw, index=index, source="auto_e2e")
        if candidate is not None:
            candidates.append(candidate)
    controls = output.get("controls") or output.get("accel_curvature") or []
    if controls:
        candidates.append(
            integrate_curvature_accel(
                ego_speed_ms=ego_speed_ms,
                controls=list(controls),
                dt_s=float(output.get("dt_s", 0.1)),
                candidate_id=str(output.get("candidate_id", "auto-e2e-policy")),
                source="auto_e2e",
                probability=float(output.get("confidence", 0.5) or 0.0),
                metadata={"visual_history": bool(output.get("visual_history_used", True)), "egomotion_history": bool(output.get("egomotion_history_used", True))},
            )
        )
    return {"model_family": "auto_e2e", "policy_candidates": candidates, "model_products": {}}


def adapt_openpilot_policy(output: dict[str, Any], *, ego_speed_ms: float) -> dict[str, Any]:
    controls = output.get("controls") or output.get("policy") or []
    if not controls:
        return {"model_family": "openpilot_policy", "policy_candidates": [], "model_products": {}}
    candidate = integrate_curvature_accel(
        ego_speed_ms=ego_speed_ms,
        controls=list(controls),
        dt_s=float(output.get("dt_s", 0.05)),
        candidate_id=str(output.get("candidate_id", "openpilot-policy")),
        source="openpilot_policy",
        probability=float(output.get("confidence", 0.5) or 0.0),
        metadata={"learned_policy": True, "adapter_only": True},
    )
    return {"model_family": "openpilot_policy", "policy_candidates": [candidate], "model_products": {}}


def adapt_alpamayo(output: dict[str, Any], *, ego_speed_ms: float) -> dict[str, Any]:
    del ego_speed_ms
    trajectories = output.get("trajectories") or ([output.get("trajectory")] if output.get("trajectory") else [])
    candidates = []
    reasoning = output.get("reasoning", output.get("reasoning_trace"))
    for index, raw in enumerate(trajectories):
        if not isinstance(raw, dict):
            continue
        enriched = dict(raw)
        metadata = dict(enriched.get("metadata") or {})
        if reasoning is not None:
            metadata["reasoning_trace"] = reasoning
        enriched["metadata"] = metadata
        candidate = _normalize_xy_trajectory(enriched, index=index, source="alpamayo_vla")
        if candidate is not None:
            candidates.append(candidate)
    return {
        "model_family": "alpamayo",
        "policy_candidates": candidates,
        "model_products": {"reasoning_trace": reasoning, "action_prediction": output.get("action_prediction")},
    }


def normalize_model_output(model_family: str, output: dict[str, Any], *, ego_speed_ms: float = 0.0) -> dict[str, Any]:
    family = str(model_family).strip().lower()
    if family == "meteor":
        result = adapt_meteor(output, ego_speed_ms=ego_speed_ms)
    elif family == "auto_e2e":
        result = adapt_auto_e2e(output, ego_speed_ms=ego_speed_ms)
    elif family == "openpilot_policy":
        result = adapt_openpilot_policy(output, ego_speed_ms=ego_speed_ms)
    elif family == "alpamayo":
        result = adapt_alpamayo(output, ego_speed_ms=ego_speed_ms)
    else:
        raise ValueError(f"unsupported model family: {family}")
    return {
        **result,
        "adapter_contract": "planning_world_v2",
        "live_actuation": False,
        "raw_vehicle_tx": False,
        "supported_profile": SUPPORTED_MODEL_FAMILIES[family],
    }


def adapter_profile() -> dict[str, Any]:
    return {
        "supported_model_families": SUPPORTED_MODEL_FAMILIES,
        "purpose": "Normalize public/open autonomy model outputs into Vision Planning World v2 shadow-policy inputs.",
        "weights_included": False,
        "third_party_source_copied": False,
        "live_actuation": False,
        "raw_vehicle_tx": False,
    }
