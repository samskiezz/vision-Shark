from __future__ import annotations

import math
from typing import Any

from .learned_world import WorldModelConfig


def _tolist(value: Any) -> Any:
    if value is None:
        return None
    detach = getattr(value, "detach", None)
    if callable(detach):
        value = detach()
    cpu = getattr(value, "cpu", None)
    if callable(cpu):
        value = cpu()
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return tolist()
    return value


def _softmax(values: list[float]) -> list[float]:
    if not values:
        return []
    finite = [float(value) if math.isfinite(float(value)) else -1e9 for value in values]
    peak = max(finite)
    exp = [math.exp(value - peak) for value in finite]
    total = sum(exp)
    if total <= 0:
        return [1.0 / len(values)] * len(values)
    return [value / total for value in exp]


def _trajectory_points(raw: list[list[float]], *, dt_s: float) -> list[dict[str, float]]:
    points = []
    for index, row in enumerate(raw):
        values = list(row)
        if len(values) < 2:
            continue
        x = float(values[0])
        y = float(values[1])
        speed = float(values[2]) if len(values) > 2 else 0.0
        accel = float(values[3]) if len(values) > 3 else 0.0
        if not all(math.isfinite(value) for value in (x, y, speed, accel)):
            continue
        points.append({
            "t": (index + 1) * float(dt_s),
            "x": x,
            "y": y,
            "speed": max(0.0, speed),
            "accel": accel,
        })
    return points


def bridge_world_model_output(
    outputs: dict[str, Any],
    *,
    config: WorldModelConfig | None = None,
    batch_index: int = 0,
    occupancy_threshold: float = 0.5,
) -> dict[str, Any]:
    """Convert one learned-model batch item into the Planning World interchange.

    The bridge is intentionally inference-only. It does not generate actuator
    commands and carries the learned products into the same counterfactual
    evaluation path used by external/open autonomy models.
    """
    cfg = config or WorldModelConfig()
    cfg.validate()
    if not (0.0 < occupancy_threshold < 1.0):
        raise ValueError("occupancy_threshold must be in (0, 1)")

    trajectories_all = _tolist(outputs.get("ego_trajectories"))
    logits_all = _tolist(outputs.get("trajectory_logits"))
    if trajectories_all is None or logits_all is None:
        raise ValueError("world-model output requires ego_trajectories and trajectory_logits")
    if batch_index < 0 or batch_index >= len(trajectories_all):
        raise ValueError("batch_index is out of range")
    trajectories_raw = trajectories_all[batch_index]
    logits = [float(value) for value in logits_all[batch_index]]
    probabilities = _softmax(logits)
    trajectories: list[dict[str, Any]] = []
    for mode_index, raw in enumerate(trajectories_raw):
        points = _trajectory_points(raw, dt_s=cfg.future_dt_s)
        if len(points) < 2:
            continue
        trajectories.append({
            "candidate_id": f"vision-world-{mode_index}",
            "probability": probabilities[mode_index] if mode_index < len(probabilities) else 0.0,
            "points": points,
            "metadata": {
                "learned_world_model": True,
                "mode_index": mode_index,
                "offline_or_shadow_only": True,
            },
        })

    occupancy_logits_all = _tolist(outputs.get("occupancy_logits"))
    flow_all = _tolist(outputs.get("occupancy_flow"))
    agents_all = _tolist(outputs.get("agent_forecasts"))
    risk_all = _tolist(outputs.get("risk_logits"))
    camera_attention_all = _tolist(outputs.get("camera_attention"))

    occupancy = None
    if occupancy_logits_all is not None:
        occupancy_logits = occupancy_logits_all[batch_index]
        occupancy = []
        logit_threshold = math.log(occupancy_threshold / (1.0 - occupancy_threshold))
        for step_index, grid in enumerate(occupancy_logits):
            cells = []
            for row_index, row in enumerate(grid):
                for column_index, value in enumerate(row):
                    if float(value) >= logit_threshold:
                        cells.append({"row": row_index, "column": column_index, "logit": float(value)})
            occupancy.append({"t": (step_index + 1) * cfg.future_dt_s, "occupied_cells": cells})

    agent_forecasts = None
    if agents_all is not None:
        agent_forecasts = []
        for agent_index, future in enumerate(agents_all[batch_index]):
            points = []
            for step_index, state in enumerate(future):
                values = list(state)
                if len(values) < 2:
                    continue
                points.append({
                    "t": (step_index + 1) * cfg.future_dt_s,
                    "x": float(values[0]),
                    "y": float(values[1]),
                    "vx": float(values[2]) if len(values) > 2 else 0.0,
                    "vy": float(values[3]) if len(values) > 3 else 0.0,
                })
            agent_forecasts.append({"agent_id": f"learned-{agent_index}", "points": points})

    return {
        "model_family": "vision_world_model",
        "trajectories": trajectories,
        "occupancy": occupancy,
        "occupancy_flow": None if flow_all is None else flow_all[batch_index],
        "agent_forecasts": agent_forecasts,
        "risk_field": None if risk_all is None else risk_all[batch_index],
        "camera_attention": None if camera_attention_all is None else camera_attention_all[batch_index],
        "model_metadata": {
            "architecture": "vision_world_model",
            "config": cfg.as_dict(),
            "batch_index": batch_index,
            "weights_included": False,
        },
        "live_actuation": False,
        "raw_vehicle_tx": False,
    }


def bridge_profile() -> dict[str, Any]:
    return {
        "source": "vision_world_model",
        "destination": "planning_world_v2 model interchange",
        "products": ["multimodal_trajectory", "occupancy", "occupancy_flow", "agent_forecasts", "risk_field", "camera_attention"],
        "live_actuation": False,
        "raw_vehicle_tx": False,
    }
