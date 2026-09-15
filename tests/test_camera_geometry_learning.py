import json

import pytest

from vision_shark.autonomy.camera_geometry import (
    GEOMETRY_VECTOR_DIM,
    calibration_registry_from_dict,
    calibration_registry_sha256,
    calibration_registry_summary,
    camera_geometry_from_dict,
)
from vision_shark.autonomy.learned_world import WorldModelConfig, world_model_profile
from vision_shark.autonomy.learning_dataset import DatasetLoaderConfig, SequenceWindowDataset
from vision_shark.autonomy.training import forward_world_model
from vision_shark.autonomy.training_contracts import dataset_manifest_from_dict
from vision_shark.learning_cli import main as learning_main


def identity_transform(x=0.0, y=0.0, z=0.0):
    return [
        [1.0, 0.0, 0.0, x],
        [0.0, 1.0, 0.0, y],
        [0.0, 0.0, 1.0, z],
        [0.0, 0.0, 0.0, 1.0],
    ]


def registry_dict():
    return {
        "calibrations": {
            "rig-au-001": {
                "vehicle_variant": "AU-test",
                "firmware": "test-only",
                "source": "unit-test",
                "cameras": [
                    {
                        "camera_id": "front",
                        "width": 1920,
                        "height": 1080,
                        "fx": 1200.0,
                        "fy": 1190.0,
                        "cx": 960.0,
                        "cy": 540.0,
                        "camera_to_ego": identity_transform(1.2, 0.0, 1.4),
                    },
                    {
                        "camera_id": "rear",
                        "width": 1920,
                        "height": 1080,
                        "fx": 1180.0,
                        "fy": 1185.0,
                        "cx": 960.0,
                        "cy": 540.0,
                        "camera_to_ego": identity_transform(-1.1, 0.0, 1.3),
                    },
                ],
            }
        }
    }


def manifest_dict(sample_count=5):
    samples = []
    for index in range(sample_count):
        samples.append({
            "sample_id": f"s{index}",
            "recording_id": "r1",
            "timestamp_s": index * 0.1,
            "calibration_id": "rig-au-001",
            "cameras": [
                {"camera_id": "front", "timestamp_s": index * 0.1, "uri": f"front/{index}.jpg"},
                {"camera_id": "rear", "timestamp_s": index * 0.1, "uri": f"rear/{index}.jpg"},
            ],
            "ego_state": {"speed_ms": 5.0},
            "labels": {"ego_trajectory": [[float(step), 0.0, 5.0, 0.0] for step in range(3)]},
        })
    return {
        "dataset_id": "geometry-dataset",
        "version": "v1",
        "required_cameras": ["front", "rear"],
        "samples": samples,
    }


def test_camera_geometry_vector_is_normalized_and_fixed_width():
    raw = registry_dict()["calibrations"]["rig-au-001"]["cameras"][0]
    camera = camera_geometry_from_dict(raw)
    vector = camera.vector()
    assert len(vector) == GEOMETRY_VECTOR_DIM
    assert vector[0] == pytest.approx(1200.0 / 1920.0)
    assert vector[2] == pytest.approx(0.5)
    assert vector[-1] == pytest.approx(1.4)


def test_camera_geometry_rejects_non_homogeneous_transform():
    raw = dict(registry_dict()["calibrations"]["rig-au-001"]["cameras"][0])
    raw["camera_to_ego"] = identity_transform()
    raw["camera_to_ego"][3][3] = 2.0
    with pytest.raises(ValueError, match="bottom row"):
        camera_geometry_from_dict(raw)


def test_calibration_registry_hash_is_deterministic():
    registry = calibration_registry_from_dict(registry_dict())
    first = calibration_registry_sha256(registry)
    second = calibration_registry_sha256(dict(reversed(list(registry.items()))))
    assert first == second
    summary = calibration_registry_summary(registry)
    assert summary["valid"] is True
    assert summary["calibration_registry_sha256"] == first
    assert summary["calibrations"][0]["camera_ids"] == ["front", "rear"]


def test_sequence_dataset_reports_strict_geometry_contract(tmp_path):
    manifest = dataset_manifest_from_dict(manifest_dict())
    rigs = calibration_registry_from_dict(registry_dict())
    dataset = SequenceWindowDataset(
        manifest,
        frame_roots=[tmp_path],
        calibration_rigs=rigs,
        config=DatasetLoaderConfig(
            history_steps=3,
            future_steps=3,
            max_agents=2,
            require_calibration=True,
        ),
    )
    profile = dataset.profile()
    assert profile["windows"] == 3
    assert profile["camera_geometry_shape"] == [2, GEOMETRY_VECTOR_DIM]
    assert profile["calibration_rigs"] == 1
    assert profile["require_calibration"] is True


def test_geometry_model_profile_declares_third_input():
    config = WorldModelConfig(camera_count=2, use_camera_geometry=True)
    profile = world_model_profile(config)
    assert profile["geometry_aware"] is True
    assert profile["input_contract"]["camera_geometry"] == f"[batch,time,cameras,{GEOMETRY_VECTOR_DIM}]"


def test_forward_world_model_routes_geometry_without_torch():
    class Config:
        use_camera_geometry = True

    class GeometryModel:
        config = Config()

        def __call__(self, *args):
            return args

    result = forward_world_model(GeometryModel(), "camera", "ego", "geometry")
    assert result == ("camera", "ego", "geometry")
    with pytest.raises(ValueError, match="requires camera_geometry"):
        forward_world_model(GeometryModel(), "camera", "ego")

    class LegacyConfig:
        use_camera_geometry = False

    class LegacyModel:
        config = LegacyConfig()

        def __call__(self, *args):
            return args

    assert forward_world_model(LegacyModel(), "camera", "ego", "ignored") == ("camera", "ego")


def test_learning_cli_validates_calibration_registry(tmp_path, capsys):
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(registry_dict()), encoding="utf-8")
    rc = learning_main(["calibration-validate", "--calibration-registry", str(path)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True
    assert payload["calibration_count"] == 1
    assert len(payload["calibration_registry_sha256"]) == 64
