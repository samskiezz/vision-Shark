from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..model_registry import ProvenanceRegistry
from .learning_dataset import split_hashes
from .training_contracts import DatasetManifest


def register_dataset_manifest(
    registry: ProvenanceRegistry,
    manifest: DatasetManifest,
    *,
    license_id: str,
    split: dict[str, list[str]],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest.validate()
    if not str(license_id).strip():
        raise ValueError("license_id is required")
    all_split_ids = [sample_id for values in split.values() for sample_id in values]
    expected = sorted(sample.sample_id for sample in manifest.samples)
    if sorted(all_split_ids) != expected:
        raise ValueError("split must contain every dataset sample exactly once")
    if len(all_split_ids) != len(set(all_split_ids)):
        raise ValueError("split contains duplicate sample IDs")
    name = f"{manifest.dataset_id}:{manifest.version}"
    return registry.register_dataset(
        name,
        manifest.sha256(),
        str(license_id),
        split_hashes(split),
        {
            "dataset_id": manifest.dataset_id,
            "version": manifest.version,
            "sample_count": len(manifest.samples),
            "required_cameras": list(manifest.required_cameras),
            "label_schema_version": manifest.label_schema_version,
            **dict(metadata or {}),
        },
    )


def checkpoint_sha256(path: str | Path) -> str:
    target = Path(path)
    if not target.is_file():
        raise ValueError("checkpoint does not exist")
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def register_model_checkpoint(
    registry: ProvenanceRegistry,
    *,
    model_name: str,
    checkpoint_path: str | Path,
    dataset_names: list[str],
    evaluation: dict[str, Any],
    calibration_sha256: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not str(model_name).strip():
        raise ValueError("model_name is required")
    if not dataset_names:
        raise ValueError("at least one registered dataset is required")
    digest = checkpoint_sha256(checkpoint_path)
    sidecar_path = Path(checkpoint_path).with_suffix(Path(checkpoint_path).suffix + ".json")
    sidecar = None
    if sidecar_path.is_file():
        try:
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("checkpoint metadata sidecar is invalid") from exc
        claimed = sidecar.get("checkpoint_sha256")
        if claimed is not None and str(claimed).lower() != digest:
            raise ValueError("checkpoint metadata hash does not match checkpoint")
    return registry.register_model(
        str(model_name),
        digest,
        list(dataset_names),
        dict(evaluation),
        calibration_sha256=calibration_sha256,
        metadata={
            "checkpoint_file": Path(checkpoint_path).name,
            "checkpoint_sidecar_present": sidecar is not None,
            "checkpoint_metadata": sidecar,
            **dict(metadata or {}),
        },
    )


def provenance_profile() -> dict[str, Any]:
    return {
        "dataset_identity": "canonical manifest SHA-256",
        "split_identity": "per-split sorted sample-ID SHA-256",
        "model_identity": "checkpoint SHA-256",
        "immutable_registry": True,
        "model_requires_registered_dataset": True,
        "checkpoint_sidecar_hash_verified": True,
        "live_actuation": False,
        "raw_vehicle_tx": False,
    }
