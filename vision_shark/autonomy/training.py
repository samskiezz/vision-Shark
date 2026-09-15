from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import random
import tempfile
import time
from typing import Any, Iterable

from .learned_world import WorldModelConfig, world_model_loss


@dataclass(frozen=True)
class TrainingConfig:
    epochs: int = 20
    learning_rate: float = 3e-4
    weight_decay: float = 1e-4
    gradient_clip_norm: float = 5.0
    seed: int = 1337
    device: str = "cpu"
    mixed_precision: bool = False

    def validate(self) -> None:
        if self.epochs <= 0:
            raise ValueError("epochs must be positive")
        if not (0.0 < self.learning_rate <= 1.0):
            raise ValueError("learning_rate must be in (0, 1]")
        if not (0.0 <= self.weight_decay <= 1.0):
            raise ValueError("weight_decay must be in [0, 1]")
        if self.gradient_clip_norm <= 0:
            raise ValueError("gradient_clip_norm must be positive")
        if self.seed < 0:
            raise ValueError("seed must be non-negative")


def _require_torch():
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch is required for world-model training; install vision-shark-app[learning]") from exc
    return torch


def set_reproducible_seed(seed: int) -> None:
    torch = _require_torch()
    random.seed(int(seed))
    torch.manual_seed(int(seed))
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(int(seed))
    try:
        torch.use_deterministic_algorithms(True, warn_only=True)
    except (AttributeError, RuntimeError):
        pass


def _move(value: Any, device: str):
    torch = _require_torch()
    if isinstance(value, torch.Tensor):
        return value.to(device)
    if isinstance(value, dict):
        return {key: _move(item, device) for key, item in value.items()}
    if isinstance(value, list):
        return [_move(item, device) for item in value]
    if isinstance(value, tuple):
        return tuple(_move(item, device) for item in value)
    return value


def _batch_parts(batch: Any) -> tuple[Any, Any, dict[str, Any]]:
    if isinstance(batch, dict):
        cameras = batch.get("cameras")
        ego_history = batch.get("ego_history")
        targets = dict(batch.get("targets") or {})
    elif isinstance(batch, (tuple, list)) and len(batch) == 3:
        cameras, ego_history, targets = batch
        targets = dict(targets)
    else:
        raise ValueError("batch must be a mapping or (cameras, ego_history, targets) tuple")
    if cameras is None or ego_history is None:
        raise ValueError("batch requires cameras and ego_history")
    return cameras, ego_history, targets


def train_epoch(
    model,
    batches: Iterable[Any],
    optimizer,
    *,
    device: str = "cpu",
    gradient_clip_norm: float = 5.0,
    loss_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    torch = _require_torch()
    model.train()
    totals: dict[str, float] = {}
    total_loss = 0.0
    batch_count = 0
    for raw_batch in batches:
        cameras, ego_history, targets = _batch_parts(raw_batch)
        cameras = _move(cameras, device)
        ego_history = _move(ego_history, device)
        targets = _move(targets, device)
        optimizer.zero_grad(set_to_none=True)
        outputs = model(cameras, ego_history)
        loss, components = world_model_loss(outputs, targets, weights=loss_weights)
        loss.backward()
        grad_norm = float(torch.nn.utils.clip_grad_norm_(model.parameters(), gradient_clip_norm))
        optimizer.step()
        total_loss += float(loss.detach().cpu())
        totals["gradient_norm"] = totals.get("gradient_norm", 0.0) + grad_norm
        for name, value in components.items():
            totals[name] = totals.get(name, 0.0) + float(value.detach().cpu())
        batch_count += 1
    if batch_count == 0:
        raise ValueError("training epoch received no batches")
    return {
        "loss": total_loss / batch_count,
        "batches": batch_count,
        "components": {name: value / batch_count for name, value in totals.items()},
    }


def evaluate_epoch(
    model,
    batches: Iterable[Any],
    *,
    device: str = "cpu",
    loss_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    torch = _require_torch()
    model.eval()
    total_loss = 0.0
    totals: dict[str, float] = {}
    batch_count = 0
    with torch.no_grad():
        for raw_batch in batches:
            cameras, ego_history, targets = _batch_parts(raw_batch)
            cameras = _move(cameras, device)
            ego_history = _move(ego_history, device)
            targets = _move(targets, device)
            outputs = model(cameras, ego_history)
            loss, components = world_model_loss(outputs, targets, weights=loss_weights)
            total_loss += float(loss.detach().cpu())
            for name, value in components.items():
                totals[name] = totals.get(name, 0.0) + float(value.detach().cpu())
            batch_count += 1
    if batch_count == 0:
        raise ValueError("evaluation epoch received no batches")
    return {
        "loss": total_loss / batch_count,
        "batches": batch_count,
        "components": {name: value / batch_count for name, value in totals.items()},
    }


def fit_world_model(
    model,
    train_batches_factory,
    validation_batches_factory,
    *,
    training: TrainingConfig | None = None,
    loss_weights: dict[str, float] | None = None,
    epoch_callback=None,
) -> dict[str, Any]:
    torch = _require_torch()
    cfg = training or TrainingConfig()
    cfg.validate()
    set_reproducible_seed(cfg.seed)
    device = torch.device(cfg.device)
    model.to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=cfg.learning_rate,
        weight_decay=cfg.weight_decay,
    )
    history: list[dict[str, Any]] = []
    best_validation = float("inf")
    best_epoch = 0
    best_state = None
    for epoch in range(1, cfg.epochs + 1):
        train_result = train_epoch(
            model,
            train_batches_factory(),
            optimizer,
            device=str(device),
            gradient_clip_norm=cfg.gradient_clip_norm,
            loss_weights=loss_weights,
        )
        validation_result = evaluate_epoch(
            model,
            validation_batches_factory(),
            device=str(device),
            loss_weights=loss_weights,
        )
        row = {"epoch": epoch, "train": train_result, "validation": validation_result}
        history.append(row)
        if validation_result["loss"] < best_validation:
            best_validation = validation_result["loss"]
            best_epoch = epoch
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
        if epoch_callback is not None:
            epoch_callback(row)
    if best_state is not None:
        model.load_state_dict(best_state)
    return {
        "epochs": cfg.epochs,
        "best_epoch": best_epoch,
        "best_validation_loss": best_validation,
        "history": history,
        "training_config": asdict(cfg),
        "live_actuation": False,
        "raw_vehicle_tx": False,
    }


def save_checkpoint(
    model,
    path: str | Path,
    *,
    model_config: WorldModelConfig,
    training_config: TrainingConfig,
    dataset_sha256: str,
    metrics: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    torch = _require_torch()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "format": "vision-shark-world-model-checkpoint-v1",
        "created_ns": time.time_ns(),
        "model_config": model_config.as_dict(),
        "training_config": asdict(training_config),
        "dataset_sha256": dataset_sha256,
        "metrics": metrics,
        "extra": dict(extra or {}),
        "live_actuation": False,
        "raw_vehicle_tx": False,
    }
    fd, temporary = tempfile.mkstemp(prefix=".vision-world-", suffix=".pt", dir=target.parent)
    os.close(fd)
    try:
        torch.save({"state_dict": model.state_dict(), "metadata": metadata}, temporary)
        with open(temporary, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    metadata_path = target.with_suffix(target.suffix + ".json")
    metadata_payload = {**metadata, "checkpoint_sha256": digest, "checkpoint_file": target.name}
    metadata_path.write_text(json.dumps(metadata_payload, sort_keys=True, indent=2), encoding="utf-8")
    return metadata_payload


def load_checkpoint(model, path: str | Path, *, device: str = "cpu") -> dict[str, Any]:
    torch = _require_torch()
    target = Path(path)
    payload = torch.load(target, map_location=device, weights_only=False)
    if not isinstance(payload, dict) or "state_dict" not in payload or "metadata" not in payload:
        raise ValueError("invalid Vision world-model checkpoint")
    model.load_state_dict(payload["state_dict"])
    return dict(payload["metadata"])


def training_profile() -> dict[str, Any]:
    return {
        "optimizer": "AdamW",
        "losses": ["occupancy_bce", "flow_smooth_l1", "agent_smooth_l1", "best_mode_trajectory", "trajectory_mode_ce", "risk_bce"],
        "gradient_clipping": True,
        "best_validation_checkpoint": True,
        "deterministic_seed_support": True,
        "checkpoint_provenance": ["model_config", "training_config", "dataset_sha256", "metrics", "checkpoint_sha256"],
        "offline_training": True,
        "live_actuation": False,
        "raw_vehicle_tx": False,
    }
