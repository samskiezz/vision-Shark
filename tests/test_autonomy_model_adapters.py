from fastapi.testclient import TestClient

from vision_shark.api import create_app
from vision_shark.autonomy.model_adapters import (
    adapter_profile,
    integrate_curvature_accel,
    normalize_model_output,
)


def test_integrate_curvature_accel_produces_future_trajectory():
    candidate = integrate_curvature_accel(
        ego_speed_ms=10.0,
        controls=[
            {'acceleration': 0.0, 'curvature': 0.00},
            {'acceleration': 0.5, 'curvature': 0.02},
            {'acceleration': 0.0, 'curvature': 0.02},
        ],
        dt_s=0.2,
        candidate_id='policy',
        source='test',
        probability=0.8,
    )
    assert len(candidate['points']) == 3
    assert candidate['points'][-1]['x'] > candidate['points'][0]['x']
    assert candidate['points'][-1]['y'] > 0.0
    assert candidate['probability'] == 0.8


def test_auto_e2e_adapter_converts_control_sequence():
    result = normalize_model_output(
        'auto_e2e',
        {
            'dt_s': 0.1,
            'confidence': 0.75,
            'controls': [
                {'accel': 0.0, 'curvature': 0.0},
                {'accel': 0.1, 'curvature': 0.01},
                {'accel': 0.0, 'curvature': 0.01},
            ],
        },
        ego_speed_ms=12.0,
    )
    assert result['model_family'] == 'auto_e2e'
    assert len(result['policy_candidates']) == 1
    assert result['policy_candidates'][0]['source'] == 'auto_e2e'
    assert result['live_actuation'] is False
    assert result['raw_vehicle_tx'] is False


def test_meteor_adapter_preserves_multitask_products():
    result = normalize_model_output(
        'meteor',
        {
            'bev_lanes': [{'lane_id': 'ego', 'centerline': [{'x': 0, 'y': 0}, {'x': 20, 'y': 0}]}],
            'detections_3d': [{'track_id': 'car1', 'class': 'car', 'x': 15, 'y': 0, 'confidence': 0.9}],
            'occupancy': {'shape': [10, 10]},
            'occupancy_flow': {'shape': [10, 10, 2]},
            'traffic_lights': [{'state': 'green', 'confidence': 0.9}],
            'risk_field': {'near': 0.1},
            'trajectories': [
                {'candidate_id': 'm0', 'probability': 0.7, 'points': [
                    {'t': 0.5, 'x': 5, 'y': 0, 'speed': 10},
                    {'t': 1.0, 'x': 10, 'y': 0, 'speed': 10},
                ]}
            ],
        },
        ego_speed_ms=10.0,
    )
    assert result['model_family'] == 'meteor'
    assert len(result['policy_candidates']) == 1
    assert result['lanes'][0]['lane_id'] == 'ego'
    assert result['model_products']['traffic_lights'][0]['state'] == 'green'
    assert result['model_products']['risk_field']['near'] == 0.1


def test_alpamayo_adapter_carries_reasoning_as_metadata_only():
    result = normalize_model_output(
        'alpamayo',
        {
            'reasoning_trace': 'vehicle ahead slowing; prefer larger gap',
            'trajectory': {
                'candidate_id': 'a0',
                'confidence': 0.6,
                'points': [
                    {'t': 0.5, 'x': 4, 'y': 0, 'speed': 8},
                    {'t': 1.0, 'x': 7, 'y': 0, 'speed': 6},
                ],
            },
        },
        ego_speed_ms=8.0,
    )
    candidate = result['policy_candidates'][0]
    assert candidate['metadata']['reasoning_trace'].startswith('vehicle ahead')
    assert result['live_actuation'] is False


def test_model_adapter_profile_is_explicit_about_scope():
    profile = adapter_profile()
    assert {'meteor', 'auto_e2e', 'openpilot_policy', 'alpamayo'} <= set(profile['supported_model_families'])
    assert profile['weights_included'] is False
    assert profile['third_party_source_copied'] is False
    assert profile['live_actuation'] is False


def test_model_adapter_api(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    profile = client.get('/api/vision/autonomy/model-adapters/profile')
    assert profile.status_code == 200
    response = client.post('/api/vision/autonomy/model-adapters/normalize', json={
        'model_family': 'openpilot_policy',
        'ego_speed_ms': 10.0,
        'output': {
            'dt_s': 0.1,
            'confidence': 0.8,
            'controls': [
                {'acceleration': 0.0, 'curvature': 0.0},
                {'acceleration': -0.2, 'curvature': 0.01},
                {'acceleration': -0.2, 'curvature': 0.01},
            ],
        },
    })
    assert response.status_code == 200
    body = response.json()
    assert body['model_family'] == 'openpilot_policy'
    assert len(body['policy_candidates']) == 1
    assert body['live_actuation'] is False
