import pytest
from fastapi.testclient import TestClient

from vision_shark.api import create_app
from vision_shark.autonomy.learned_world import WorldModelConfig, build_torch_world_model, world_model_loss, world_model_profile
from vision_shark.autonomy.model_adapters import normalize_model_output
from vision_shark.autonomy.training_contracts import dataset_manifest_from_dict
from vision_shark.autonomy.world_model_bridge import bridge_world_model_output


def sample_manifest():
    return {
        'dataset_id': 'shark-shadow-v1',
        'version': '2026.09.15',
        'required_cameras': ['front', 'rear'],
        'samples': [
            {
                'sample_id': 's1',
                'recording_id': 'r1',
                'timestamp_s': 1.0,
                'cameras': [
                    {'camera_id': 'front', 'timestamp_s': 1.0, 'uri': 'frames/r1/front/1.jpg'},
                    {'camera_id': 'rear', 'timestamp_s': 1.0, 'uri': 'frames/r1/rear/1.jpg'},
                ],
                'ego_state': {'speed_ms': 8.0},
                'labels': {'ego_trajectory': [{'t': 0.2, 'x': 1.6, 'y': 0.0}]},
                'scenario_tags': ['urban'],
            },
            {
                'sample_id': 's2',
                'recording_id': 'r1',
                'timestamp_s': 1.2,
                'cameras': [
                    {'camera_id': 'front', 'timestamp_s': 1.2, 'uri': 'frames/r1/front/2.jpg'},
                    {'camera_id': 'rear', 'timestamp_s': 1.2, 'uri': 'frames/r1/rear/2.jpg'},
                ],
                'ego_state': {'speed_ms': 8.2},
                'labels': {'ego_trajectory': [{'t': 0.2, 'x': 1.64, 'y': 0.0}]},
                'scenario_tags': ['urban'],
            },
        ],
    }


def small_config():
    return WorldModelConfig(
        camera_count=2,
        ego_state_dim=4,
        hidden_dim=32,
        bev_height=2,
        bev_width=2,
        future_steps=2,
        trajectory_modes=2,
        max_agents=1,
    )


def fake_outputs():
    return {
        'ego_trajectories': [[
            [[1.0, 0.0, 5.0, 0.0], [2.0, 0.0, 5.0, 0.0]],
            [[0.9, 0.3, 4.8, -0.1], [1.8, 0.7, 4.6, -0.2]],
        ]],
        'trajectory_logits': [[2.0, 0.0]],
        'occupancy_logits': [[
            [[2.0, -2.0], [-1.0, 3.0]],
            [[1.0, -3.0], [0.0, 2.0]],
        ]],
        'occupancy_flow': [[
            [[[0.0, 0.0], [0.0, 0.0]], [[0.0, 0.0], [0.0, 0.0]]],
            [[[0.1, 0.0], [0.0, 0.0]], [[0.0, 0.0], [0.0, 0.0]]],
        ]],
        'agent_forecasts': [[[
            [10.0, 1.0, -1.0, 0.0],
            [9.8, 1.0, -1.0, 0.0],
        ]]],
        'risk_logits': [[
            [[-1.0, 0.0], [1.0, 2.0]],
            [[-2.0, 0.0], [1.5, 2.5]],
        ]],
        'camera_attention': [[[0.7, 0.3]]],
    }


def test_dataset_manifest_hash_and_split_are_deterministic():
    manifest = dataset_manifest_from_dict(sample_manifest())
    first_hash = manifest.sha256()
    second_hash = dataset_manifest_from_dict(sample_manifest()).sha256()
    assert first_hash == second_hash
    assert len(first_hash) == 64
    first_split = manifest.split(train=0.5, validation=0.25, test=0.25, salt='fixed')
    second_split = manifest.split(train=0.5, validation=0.25, test=0.25, salt='fixed')
    assert first_split == second_split
    assert sorted(first_split['train'] + first_split['validation'] + first_split['test']) == ['s1', 's2']


def test_dataset_manifest_rejects_missing_required_camera():
    raw = sample_manifest()
    raw['samples'][0]['cameras'] = raw['samples'][0]['cameras'][:1]
    with pytest.raises(ValueError, match='missing required cameras'):
        dataset_manifest_from_dict(raw)


def test_world_model_bridge_produces_planning_candidates_and_products():
    bridged = bridge_world_model_output(fake_outputs(), config=small_config())
    assert bridged['model_family'] == 'vision_world_model'
    assert len(bridged['trajectories']) == 2
    assert bridged['trajectories'][0]['probability'] > bridged['trajectories'][1]['probability']
    assert bridged['occupancy'][0]['occupied_cells']
    assert bridged['agent_forecasts'][0]['points'][0]['x'] == 10.0
    assert bridged['live_actuation'] is False
    normalized = normalize_model_output('vision_world_model', bridged, ego_speed_ms=5.0)
    assert len(normalized['policy_candidates']) == 2
    assert normalized['policy_candidates'][0]['source'] == 'vision_world_model'
    assert normalized['model_products']['occupancy']
    assert normalized['raw_vehicle_tx'] is False


def test_world_model_profile_declares_real_trainable_heads_without_weights():
    profile = world_model_profile(small_config())
    assert profile['trainable'] is True
    assert profile['weights_included'] is False
    assert 'occupancy_logits' in profile['output_products']
    assert 'ego_trajectories' in profile['output_products']
    assert profile['live_actuation'] is False


def test_training_api_validates_manifest_and_bridges_output(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    profile = client.get('/api/vision/autonomy/training/profile')
    assert profile.status_code == 200
    assert profile.json()['model']['trainable'] is True

    validated = client.post('/api/vision/autonomy/training/manifest/validate', json={
        'manifest': sample_manifest(),
        'train_fraction': 0.5,
        'validation_fraction': 0.25,
        'test_fraction': 0.25,
        'split_salt': 'fixed',
    })
    assert validated.status_code == 200
    assert validated.json()['valid'] is True
    assert validated.json()['samples'] == 2

    bridge = client.post('/api/vision/autonomy/training/bridge', json={
        'outputs': fake_outputs(),
        'config': small_config().as_dict(),
        'batch_index': 0,
    })
    assert bridge.status_code == 200
    assert len(bridge.json()['trajectories']) == 2
    assert bridge.json()['raw_vehicle_tx'] is False


def test_torch_model_forward_and_loss_when_learning_extra_is_installed():
    torch = pytest.importorskip('torch')
    cfg = small_config()
    model = build_torch_world_model(cfg)
    cameras = torch.randn(1, 2, cfg.camera_count, cfg.image_channels, 32, 32)
    ego = torch.randn(1, 2, cfg.ego_state_dim)
    outputs = model(cameras, ego)
    assert outputs['occupancy_logits'].shape == (1, cfg.future_steps, cfg.bev_height, cfg.bev_width)
    assert outputs['ego_trajectories'].shape == (1, cfg.trajectory_modes, cfg.future_steps, 4)
    target = {
        'occupancy': torch.zeros_like(outputs['occupancy_logits']),
        'occupancy_flow': torch.zeros_like(outputs['occupancy_flow']),
        'agent_forecasts': torch.zeros_like(outputs['agent_forecasts']),
        'ego_trajectory': torch.zeros(1, cfg.future_steps, 4),
        'risk': torch.zeros_like(outputs['risk_logits']),
    }
    loss, components = world_model_loss(outputs, target)
    assert torch.isfinite(loss)
    assert {'occupancy', 'flow', 'agents', 'trajectory', 'risk'} <= set(components)
    loss.backward()
    assert any(parameter.grad is not None for parameter in model.parameters())
