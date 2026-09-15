from __future__ import annotations

import math
from statistics import fmean
from typing import Any, Iterable


def _finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("metric inputs must be finite")
    return number


def _flatten(values: Any) -> list[float]:
    if isinstance(values, (list, tuple)):
        result: list[float] = []
        for item in values:
            result.extend(_flatten(item))
        return result
    return [_finite(values)]


def binary_iou(logits_or_scores: Any, target: Any, *, threshold: float = 0.5, logits: bool = True) -> dict[str, float]:
    if not 0.0 < threshold < 1.0:
        raise ValueError("threshold must be in (0, 1)")
    prediction = _flatten(logits_or_scores)
    truth = _flatten(target)
    if len(prediction) != len(truth):
        raise ValueError("prediction and target shapes do not match")
    cutoff = math.log(threshold / (1.0 - threshold)) if logits else threshold
    pred_positive = [value >= cutoff for value in prediction]
    true_positive = [value >= 0.5 for value in truth]
    intersection = sum(1 for pred, actual in zip(pred_positive, true_positive, strict=True) if pred and actual)
    union = sum(1 for pred, actual in zip(pred_positive, true_positive, strict=True) if pred or actual)
    positives = sum(true_positive)
    predicted = sum(pred_positive)
    iou = 1.0 if union == 0 else intersection / union
    precision = 1.0 if predicted == 0 and positives == 0 else (intersection / predicted if predicted else 0.0)
    recall = 1.0 if positives == 0 and predicted == 0 else (intersection / positives if positives else 0.0)
    return {"iou": iou, "precision": precision, "recall": recall, "intersection": float(intersection), "union": float(union)}


def flow_endpoint_error(predicted: Any, target: Any) -> dict[str, float]:
    pred = _flatten(predicted)
    truth = _flatten(target)
    if len(pred) != len(truth) or len(pred) % 2:
        raise ValueError("flow inputs must have equal even-length vector components")
    errors = [math.hypot(pred[index] - truth[index], pred[index + 1] - truth[index + 1]) for index in range(0, len(pred), 2)]
    return {
        "epe_mean": fmean(errors) if errors else 0.0,
        "epe_max": max(errors, default=0.0),
        "vectors": float(len(errors)),
    }


def trajectory_ade_fde(predicted: Iterable[Iterable[float]], target: Iterable[Iterable[float]]) -> dict[str, float]:
    pred = [list(point) for point in predicted]
    truth = [list(point) for point in target]
    if len(pred) != len(truth) or not pred:
        raise ValueError("trajectory inputs must be non-empty with matching lengths")
    distances: list[float] = []
    for left, right in zip(pred, truth, strict=True):
        if len(left) < 2 or len(right) < 2:
            raise ValueError("trajectory points require x and y")
        distances.append(math.hypot(_finite(left[0]) - _finite(right[0]), _finite(left[1]) - _finite(right[1])))
    return {"ade_m": fmean(distances), "fde_m": distances[-1], "steps": float(len(distances))}


def multimodal_trajectory_metrics(
    modes: Iterable[Iterable[Iterable[float]]],
    target: Iterable[Iterable[float]],
    probabilities: Iterable[float] | None = None,
) -> dict[str, Any]:
    trajectories = [list(mode) for mode in modes]
    if not trajectories:
        raise ValueError("at least one trajectory mode is required")
    metrics = [trajectory_ade_fde(mode, target) for mode in trajectories]
    best_index = min(range(len(metrics)), key=lambda index: metrics[index]["ade_m"])
    result: dict[str, Any] = {
        "min_ade_m": metrics[best_index]["ade_m"],
        "min_fde_m": min(metric["fde_m"] for metric in metrics),
        "best_mode_index": best_index,
        "mode_metrics": metrics,
    }
    if probabilities is not None:
        probs = [_finite(value) for value in probabilities]
        if len(probs) != len(trajectories) or any(value < 0 for value in probs):
            raise ValueError("mode probabilities must be non-negative and match trajectory modes")
        total = sum(probs)
        if total <= 0:
            raise ValueError("mode probabilities must sum to a positive value")
        normalized = [value / total for value in probs]
        best_probability = max(normalized[best_index], 1e-12)
        result["best_mode_nll"] = -math.log(best_probability)
        result["probability_mass_best_mode"] = normalized[best_index]
    return result


def agent_forecast_metrics(predicted: Any, target: Any, mask: Any | None = None) -> dict[str, float]:
    pred_agents = list(predicted)
    truth_agents = list(target)
    if len(pred_agents) != len(truth_agents):
        raise ValueError("agent prediction and target counts do not match")
    mask_agents = None if mask is None else list(mask)
    errors: list[float] = []
    final_errors: list[float] = []
    agents = 0
    for agent_index, (pred_future, truth_future) in enumerate(zip(pred_agents, truth_agents, strict=True)):
        pred_future = list(pred_future)
        truth_future = list(truth_future)
        if len(pred_future) != len(truth_future):
            raise ValueError("agent future lengths do not match")
        per_agent: list[float] = []
        for step_index, (left, right) in enumerate(zip(pred_future, truth_future, strict=True)):
            active = True
            if mask_agents is not None:
                agent_mask = mask_agents[agent_index]
                active = bool(agent_mask[step_index] if isinstance(agent_mask, (list, tuple)) else agent_mask)
            if not active:
                continue
            left_values = list(left)
            right_values = list(right)
            if len(left_values) < 2 or len(right_values) < 2:
                raise ValueError("agent states require x and y")
            per_agent.append(math.hypot(_finite(left_values[0]) - _finite(right_values[0]), _finite(left_values[1]) - _finite(right_values[1])))
        if per_agent:
            agents += 1
            errors.extend(per_agent)
            final_errors.append(per_agent[-1])
    return {
        "agent_ade_m": fmean(errors) if errors else 0.0,
        "agent_fde_m": fmean(final_errors) if final_errors else 0.0,
        "agents": float(agents),
        "points": float(len(errors)),
    }


def evaluate_world_model_products(prediction: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if prediction.get("occupancy_logits") is not None and target.get("occupancy") is not None:
        metrics["occupancy"] = binary_iou(prediction["occupancy_logits"], target["occupancy"], logits=True)
    if prediction.get("occupancy_flow") is not None and target.get("occupancy_flow") is not None:
        metrics["flow"] = flow_endpoint_error(prediction["occupancy_flow"], target["occupancy_flow"])
    if prediction.get("agent_forecasts") is not None and target.get("agent_forecasts") is not None:
        metrics["agents"] = agent_forecast_metrics(prediction["agent_forecasts"], target["agent_forecasts"], target.get("agent_mask"))
    if prediction.get("ego_trajectories") is not None and target.get("ego_trajectory") is not None:
        metrics["trajectory"] = multimodal_trajectory_metrics(
            prediction["ego_trajectories"],
            target["ego_trajectory"],
            prediction.get("trajectory_probabilities"),
        )
    if not metrics:
        raise ValueError("no compatible prediction/target products were supplied")
    return metrics


def aggregate_metric_reports(reports: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(reports)
    if not rows:
        raise ValueError("at least one metric report is required")
    scalar_values: dict[str, list[float]] = {}
    for report in rows:
        for product, values in report.items():
            if not isinstance(values, dict):
                continue
            for name, value in values.items():
                if isinstance(value, (int, float)) and math.isfinite(float(value)):
                    scalar_values.setdefault(f"{product}.{name}", []).append(float(value))
    return {
        "samples": len(rows),
        "means": {name: fmean(values) for name, values in sorted(scalar_values.items())},
    }
