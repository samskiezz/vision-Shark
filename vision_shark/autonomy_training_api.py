from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .autonomy.learned_world import WorldModelConfig, world_model_profile
from .autonomy.training import training_profile
from .autonomy.training_contracts import dataset_manifest_from_dict, training_contract_profile
from .autonomy.world_model_bridge import bridge_profile, bridge_world_model_output


class ManifestBody(BaseModel):
    manifest: dict
    train_fraction: float = Field(default=0.8, ge=0.0, le=1.0)
    validation_fraction: float = Field(default=0.1, ge=0.0, le=1.0)
    test_fraction: float = Field(default=0.1, ge=0.0, le=1.0)
    split_salt: str = Field(default="vision-shark", min_length=1, max_length=256)


class ModelProfileBody(BaseModel):
    config: dict = Field(default_factory=dict)


class BridgeBody(BaseModel):
    outputs: dict
    config: dict = Field(default_factory=dict)
    batch_index: int = Field(default=0, ge=0, le=4096)
    occupancy_threshold: float = Field(default=0.5, gt=0.0, lt=1.0)


def _model_config(raw: dict) -> WorldModelConfig:
    allowed = set(WorldModelConfig.__dataclass_fields__)
    unexpected = sorted(set(raw) - allowed)
    if unexpected:
        raise ValueError("unknown world-model config fields: " + ",".join(unexpected))
    config = WorldModelConfig(**raw)
    config.validate()
    return config


def install_autonomy_training_routes(app, audit) -> None:
    @app.get('/api/vision/autonomy/training/profile')
    def autonomy_training_profile():
        return {
            "data_contract": training_contract_profile(),
            "model": world_model_profile(),
            "training": training_profile(),
            "bridge": bridge_profile(),
            "offline_or_shadow_only": True,
            "live_actuation": False,
            "raw_vehicle_tx": False,
        }

    @app.post('/api/vision/autonomy/training/model-profile')
    def autonomy_model_profile(body: ModelProfileBody):
        try:
            return world_model_profile(_model_config(body.config))
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post('/api/vision/autonomy/training/manifest/validate')
    def autonomy_manifest_validate(body: ManifestBody):
        try:
            manifest = dataset_manifest_from_dict(body.manifest)
            splits = manifest.split(
                train=body.train_fraction,
                validation=body.validation_fraction,
                test=body.test_fraction,
                salt=body.split_salt,
            )
        except (TypeError, ValueError) as exc:
            audit.append('autonomy', 'training_manifest_rejected', {'error': str(exc)})
            raise HTTPException(400, str(exc)) from exc
        result = {
            "dataset_id": manifest.dataset_id,
            "version": manifest.version,
            "samples": len(manifest.samples),
            "sha256": manifest.sha256(),
            "splits": splits,
            "split_counts": {name: len(values) for name, values in splits.items()},
            "valid": True,
            "live_actuation": False,
            "raw_vehicle_tx": False,
        }
        audit.append('autonomy', 'training_manifest_validated', {
            "dataset_id": manifest.dataset_id,
            "samples": len(manifest.samples),
            "sha256": result['sha256'],
        })
        return result

    @app.post('/api/vision/autonomy/training/bridge')
    def autonomy_training_bridge(body: BridgeBody):
        try:
            config = _model_config(body.config)
            result = bridge_world_model_output(
                body.outputs,
                config=config,
                batch_index=body.batch_index,
                occupancy_threshold=body.occupancy_threshold,
            )
        except (TypeError, ValueError, IndexError) as exc:
            raise HTTPException(400, str(exc)) from exc
        audit.append('autonomy', 'world_model_output_bridged', {
            "trajectories": len(result.get('trajectories') or []),
            "batch_index": body.batch_index,
            "live_actuation": False,
        })
        return result
