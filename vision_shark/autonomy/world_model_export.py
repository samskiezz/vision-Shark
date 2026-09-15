from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .learned_world import WorldModelConfig


OUTPUT_NAMES = (
    "occupancy_logits",
    "occupancy_flow",
    "agent_forecasts",
    "ego_trajectories",
    "trajectory_logits",
    "risk_logits",
    "camera_attention",
)


def _require_torch():
    try:
        import torch
        import torch.nn as nn
    except ImportError as exc:
        raise RuntimeError("PyTorch is required for ONNX export; install vision-shark-app[learning]") from exc
    return torch, nn


def export_world_model_onnx(
    model,
    path: str | Path,
    *,
    config: WorldModelConfig,
    history_steps: int = 4,
    image_height: int = 128,
    image_width: int = 256,
    opset_version: int = 18,
    device: str = "cpu",
) -> dict[str, Any]:
    if history_steps <= 0:
        raise ValueError("history_steps must be positive")
    if image_height <= 0 or image_width <= 0:
        raise ValueError("image dimensions must be positive")
    config.validate()
    torch, nn = _require_torch()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    model = model.to(device).eval()

    class ExportWrapper(nn.Module):
        def __init__(self, inner) -> None:
            super().__init__()
            self.inner = inner

        def forward(self, cameras, ego_history):
            outputs = self.inner(cameras, ego_history)
            return tuple(outputs[name] for name in OUTPUT_NAMES)

    wrapper = ExportWrapper(model)
    cameras = torch.zeros(
        1,
        history_steps,
        config.camera_count,
        config.image_channels,
        image_height,
        image_width,
        dtype=torch.float32,
        device=device,
    )
    ego = torch.zeros(1, history_steps, config.ego_state_dim, dtype=torch.float32, device=device)
    dynamic_axes = {
        "cameras": {0: "batch", 1: "history"},
        "ego_history": {0: "batch", 1: "history"},
    }
    for name in OUTPUT_NAMES:
        dynamic_axes[name] = {0: "batch"}
    torch.onnx.export(
        wrapper,
        (cameras, ego),
        target,
        input_names=["cameras", "ego_history"],
        output_names=list(OUTPUT_NAMES),
        dynamic_axes=dynamic_axes,
        opset_version=int(opset_version),
        do_constant_folding=True,
    )
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    metadata = {
        "format": "vision-shark-world-model-onnx-v1",
        "onnx_file": target.name,
        "onnx_sha256": digest,
        "opset_version": int(opset_version),
        "history_steps_example": int(history_steps),
        "image_shape_example": [int(image_height), int(image_width)],
        "inputs": ["cameras", "ego_history"],
        "outputs": list(OUTPUT_NAMES),
        "config": config.as_dict(),
        "live_actuation": False,
        "raw_vehicle_tx": False,
    }
    target.with_suffix(target.suffix + ".json").write_text(
        json.dumps(metadata, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return metadata


def validate_onnx_artifact(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists() or not target.is_file():
        raise ValueError("ONNX artifact does not exist")
    try:
        import onnx
    except ImportError as exc:
        raise RuntimeError("onnx is required for artifact validation; install vision-shark-app[learning]") from exc
    model = onnx.load(str(target))
    onnx.checker.check_model(model)
    graph_inputs = [item.name for item in model.graph.input]
    graph_outputs = [item.name for item in model.graph.output]
    missing_inputs = sorted({"cameras", "ego_history"} - set(graph_inputs))
    missing_outputs = sorted(set(OUTPUT_NAMES) - set(graph_outputs))
    if missing_inputs or missing_outputs:
        raise ValueError(f"ONNX interface mismatch: missing_inputs={missing_inputs}, missing_outputs={missing_outputs}")
    return {
        "valid": True,
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "inputs": graph_inputs,
        "outputs": graph_outputs,
        "live_actuation": False,
        "raw_vehicle_tx": False,
    }


def export_profile() -> dict[str, Any]:
    return {
        "format": "ONNX",
        "inputs": ["cameras", "ego_history"],
        "outputs": list(OUTPUT_NAMES),
        "dynamic_batch": True,
        "dynamic_history": True,
        "compatible_runtime": "vision_shark.model_runtime.OnnxBackend",
        "live_actuation": False,
        "raw_vehicle_tx": False,
    }
