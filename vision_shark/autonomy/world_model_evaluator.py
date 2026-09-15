from __future__ import annotations

from typing import Any, Iterable

from .training import forward_world_model
from .world_model_metrics import aggregate_metric_reports, evaluate_world_model_products


def _require_torch():
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch is required for learned-model evaluation; install vision-shark-app[learning]") from exc
    return torch


def _cpu_list(value: Any) -> Any:
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


def _move(value: Any, device: str) -> Any:
    torch = _require_torch()
    if isinstance(value, torch.Tensor):
        return value.to(device)
    if isinstance(value, dict):
        return {key: _move(item, device) for key, item in value.items()}
    return value


def _batch_size(batch: dict[str, Any]) -> int:
    cameras = batch.get("cameras")
    if cameras is None:
        raise ValueError("batch requires cameras")
    return int(cameras.shape[0])


def _at(value: Any, index: int) -> Any:
    if value is None:
        return None
    try:
        return value[index]
    except (IndexError, KeyError, TypeError):
        return value


def evaluate_model_batches(model, batches: Iterable[dict[str, Any]], *, device: str = "cpu") -> dict[str, Any]:
    torch = _require_torch()
    model = model.to(device).eval()
    reports: list[dict[str, Any]] = []
    per_sample: list[dict[str, Any]] = []
    with torch.no_grad():
        for batch in batches:
            cameras = _move(batch.get("cameras"), device)
            ego = _move(batch.get("ego_history"), device)
            camera_geometry = _move(batch.get("camera_geometry"), device)
            targets = _move(dict(batch.get("targets") or {}), device)
            if cameras is None or ego is None:
                raise ValueError("batch requires cameras and ego_history")
            outputs = forward_world_model(model, cameras, ego, camera_geometry)
            probabilities = torch.softmax(outputs["trajectory_logits"], dim=-1)
            count = _batch_size(batch)
            sample_ids = batch.get("sample_id") or [str(index) for index in range(count)]
            calibration_ids = batch.get("calibration_ids")
            for index in range(count):
                prediction = {
                    "occupancy_logits": _cpu_list(outputs.get("occupancy_logits")[index]) if outputs.get("occupancy_logits") is not None else None,
                    "occupancy_flow": _cpu_list(outputs.get("occupancy_flow")[index]) if outputs.get("occupancy_flow") is not None else None,
                    "agent_forecasts": _cpu_list(outputs.get("agent_forecasts")[index]) if outputs.get("agent_forecasts") is not None else None,
                    "ego_trajectories": _cpu_list(outputs.get("ego_trajectories")[index]) if outputs.get("ego_trajectories") is not None else None,
                    "trajectory_probabilities": _cpu_list(probabilities[index]),
                }
                target = {
                    "occupancy": _cpu_list(_at(targets.get("occupancy"), index)),
                    "occupancy_flow": _cpu_list(_at(targets.get("occupancy_flow"), index)),
                    "agent_forecasts": _cpu_list(_at(targets.get("agent_forecasts"), index)),
                    "agent_mask": _cpu_list(_at(targets.get("agent_mask"), index)),
                    "ego_trajectory": _cpu_list(_at(targets.get("ego_trajectory"), index)),
                }
                report = evaluate_world_model_products(prediction, target)
                reports.append(report)
                sample_id = sample_ids[index] if isinstance(sample_ids, (list, tuple)) else _at(sample_ids, index)
                row = {"sample_id": str(sample_id), "metrics": report}
                if calibration_ids is not None:
                    row["calibration_ids"] = _cpu_list(_at(calibration_ids, index))
                per_sample.append(row)
    aggregate = aggregate_metric_reports(reports)
    return {
        "aggregate": aggregate,
        "samples": per_sample,
        "evaluated_samples": len(per_sample),
        "geometry_aware": bool(getattr(getattr(model, "config", None), "use_camera_geometry", False)),
        "offline_evaluation": True,
        "live_actuation": False,
        "raw_vehicle_tx": False,
    }


def rank_hard_cases(evaluation: dict[str, Any], *, limit: int = 100) -> list[dict[str, Any]]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    ranked = []
    for row in evaluation.get("samples", []):
        metrics = row.get("metrics") or {}
        trajectory = metrics.get("trajectory") or {}
        occupancy = metrics.get("occupancy") or {}
        agents = metrics.get("agents") or {}
        flow = metrics.get("flow") or {}
        score = 0.0
        reasons = []
        min_ade = float(trajectory.get("min_ade_m", 0.0) or 0.0)
        if min_ade > 0.5:
            score += min(40.0, min_ade * 8.0)
            reasons.append("trajectory_error")
        if "iou" in occupancy:
            iou = float(occupancy.get("iou", 1.0) or 0.0)
            if iou < 0.7:
                score += min(30.0, (0.7 - iou) * 60.0)
                reasons.append("occupancy_error")
        agent_ade = float(agents.get("agent_ade_m", 0.0) or 0.0)
        if agent_ade > 0.5:
            score += min(20.0, agent_ade * 4.0)
            reasons.append("agent_forecast_error")
        flow_epe = float(flow.get("epe_mean", 0.0) or 0.0)
        if flow_epe > 0.5:
            score += min(10.0, flow_epe * 2.0)
            reasons.append("flow_error")
        ranked.append({
            "sample_id": row.get("sample_id"),
            "calibration_ids": row.get("calibration_ids"),
            "score": min(100.0, score),
            "reasons": reasons,
            "metrics": metrics,
        })
    ranked.sort(key=lambda item: (item["score"], str(item.get("sample_id"))), reverse=True)
    return ranked[:limit]
