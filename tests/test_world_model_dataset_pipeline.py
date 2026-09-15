import hashlib
import json

import pytest

from vision_shark.autonomy.learning_dataset import DatasetLoaderConfig, SequenceWindowDataset, build_sequence_windows, split_hashes
from vision_shark.autonomy.learning_provenance import register_dataset_manifest, register_model_checkpoint
from vision_shark.autonomy.training_contracts import dataset_manifest_from_dict
from vision_shark.autonomy.world_model_metrics import (
    agent_forecast_metrics,
    binary_iou,
    flow_endpoint_error,
    multimodal_trajectory_metrics,
    trajectory_ade_fde,
)
from vision_shark.learning_cli import main as learning_main
from vision_shark.model_registry import ProvenanceRegistry


def manifest_dict(sample_count=8):
    samples = []
    for index in range(sample_count):
        samples.append({
            'sample_id': f's{index}',
            'recording_id': 'r1',
            'timestamp_s': index * 0.1,
            'cameras': [
                {'camera_id': 'front', 'timestamp_s': index * 0.1, 'uri': f'front/{index}.jpg'},
                {'camera_id': 'rear', 'timestamp_s': index * 0.1, 'uri': f'rear/{index}.jpg'},
            ],
            'ego_state': {'speed_ms': 5.0 + index},
            'labels': {'ego_trajectory': [[step + 1.0, 0.0, 5.0, 0.0] for step in range(3)]},
        })
    return {
        'dataset_id': 'dataset',
        'version': 'v1',
        'required_cameras': ['front', 'rear'],
        'samples': samples,
    }


def test_sequence_windows_keep_context_when_target_split_filters():
    manifest = dataset_manifest_from_dict(manifest_dict())
    windows = build_sequence_windows(manifest, history_steps=3, sample_ids=['s4'])
    assert len(windows) == 1
    assert windows[0].sample_ids == ('s2', 's3', 's4')


def test_sequence_windows_reject_large_temporal_gap():
    raw = manifest_dict(5)
    raw['samples'][3]['timestamp_s'] = 10.0
    raw['samples'][4]['timestamp_s'] = 10.1
    manifest = dataset_manifest_from_dict(raw)
    windows = build_sequence_windows(manifest, history_steps=3, max_gap_s=0.5)
    assert all('s3' not in window.sample_ids for window in windows)


def test_dataset_profile_does_not_touch_frame_files(tmp_path):
    manifest = dataset_manifest_from_dict(manifest_dict())
    dataset = SequenceWindowDataset(
        manifest,
        frame_roots=[tmp_path],
        config=DatasetLoaderConfig(history_steps=3, future_steps=3, max_agents=2),
    )
    profile = dataset.profile()
    assert profile['windows'] == 6
    assert profile['camera_ids'] == ['front', 'rear']
    assert profile['remote_fetch'] is False
    assert profile['live_actuation'] is False


def test_split_hashes_are_order_independent_per_split():
    first = split_hashes({'train': ['b', 'a'], 'test': ['c']})
    second = split_hashes({'test': ['c'], 'train': ['a', 'b']})
    assert first == second
    assert all(len(value) == 64 for value in first.values())


def test_occupancy_iou_and_flow_epe_metrics():
    perfect = binary_iou([[10, -10], [-10, 10]], [[1, 0], [0, 1]], logits=True)
    assert perfect['iou'] == 1.0
    flow = flow_endpoint_error([1, 0, 0, 1], [0, 0, 0, 0])
    assert flow['epe_mean'] == 1.0
    assert flow['vectors'] == 2.0


def test_multimodal_trajectory_metric_selects_best_mode():
    target = [[1, 0], [2, 0], [3, 0]]
    modes = [target, [[1, 2], [2, 2], [3, 2]]]
    result = multimodal_trajectory_metrics(modes, target, probabilities=[0.8, 0.2])
    assert result['best_mode_index'] == 0
    assert result['min_ade_m'] == 0.0
    assert result['min_fde_m'] == 0.0
    assert result['best_mode_nll'] > 0.0
    identical = trajectory_ade_fde(target, target)
    assert identical['ade_m'] == 0.0


def test_agent_metrics_honor_mask():
    predicted = [[[0, 0], [100, 100]]]
    target = [[[0, 0], [0, 0]]]
    masked = agent_forecast_metrics(predicted, target, mask=[[1, 0]])
    assert masked['agent_ade_m'] == 0.0
    assert masked['agent_fde_m'] == 0.0


def test_dataset_provenance_registration_is_bound_to_manifest_and_split(tmp_path):
    manifest = dataset_manifest_from_dict(manifest_dict())
    split = manifest.split(train=0.5, validation=0.25, test=0.25, salt='fixed')
    registry = ProvenanceRegistry(tmp_path / 'registry.json')
    registered = register_dataset_manifest(registry, manifest, license_id='internal', split=split)
    assert registered['artifact_sha256'] == manifest.sha256()
    assert registered['split_hashes'] == split_hashes(split)
    with pytest.raises(ValueError, match='already registered'):
        register_dataset_manifest(registry, manifest, license_id='internal', split=split)


def test_model_checkpoint_registration_verifies_sidecar_hash(tmp_path):
    manifest = dataset_manifest_from_dict(manifest_dict())
    split = manifest.split(train=0.5, validation=0.25, test=0.25, salt='fixed')
    registry = ProvenanceRegistry(tmp_path / 'registry.json')
    dataset = register_dataset_manifest(registry, manifest, license_id='internal', split=split)
    checkpoint = tmp_path / 'model.pt'
    checkpoint.write_bytes(b'fake-model-checkpoint')
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    checkpoint.with_suffix('.pt.json').write_text(json.dumps({'checkpoint_sha256': digest}), encoding='utf-8')
    model = register_model_checkpoint(
        registry,
        model_name='wm-v1',
        checkpoint_path=checkpoint,
        dataset_names=[dataset['name']],
        evaluation={'minADE': 1.2},
    )
    assert model['artifact_sha256'] == digest
    assert model['datasets'] == [dataset['name']]


def test_model_checkpoint_registration_rejects_tampered_sidecar(tmp_path):
    manifest = dataset_manifest_from_dict(manifest_dict())
    split = manifest.split(train=0.5, validation=0.25, test=0.25, salt='fixed')
    registry = ProvenanceRegistry(tmp_path / 'registry.json')
    dataset = register_dataset_manifest(registry, manifest, license_id='internal', split=split)
    checkpoint = tmp_path / 'model.pt'
    checkpoint.write_bytes(b'checkpoint')
    checkpoint.with_suffix('.pt.json').write_text(json.dumps({'checkpoint_sha256': 'a' * 64}), encoding='utf-8')
    with pytest.raises(ValueError, match='does not match'):
        register_model_checkpoint(
            registry,
            model_name='bad',
            checkpoint_path=checkpoint,
            dataset_names=[dataset['name']],
            evaluation={},
        )


def test_learning_cli_manifest_validate(tmp_path, capsys):
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest_dict()), encoding='utf-8')
    rc = learning_main([
        'manifest-validate',
        '--manifest', str(path),
        '--train-fraction', '0.5',
        '--validation-fraction', '0.25',
        '--test-fraction', '0.25',
        '--split-salt', 'fixed',
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['valid'] is True
    assert payload['samples'] == 8
    assert len(payload['manifest_sha256']) == 64
