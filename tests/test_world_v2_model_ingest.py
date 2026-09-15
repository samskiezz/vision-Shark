from fastapi.testclient import TestClient

from vision_shark.api import create_app


def test_world_v2_accepts_auto_e2e_output_directly(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    response = client.post('/api/vision/autonomy/world-v2/step', json={
        'timestamp_s': 1.0,
        'ego_speed_ms': 10.0,
        'ego_distance_m': 0.0,
        'lanes': [{'lane_id': 'ego', 'centerline': [{'x': 0, 'y': 0}, {'x': 80, 'y': 0}], 'route_relevance': 1.0}],
        'model_family': 'auto_e2e',
        'model_output': {
            'dt_s': 0.2,
            'confidence': 0.8,
            'controls': [
                {'accel': 0.0, 'curvature': 0.0},
                {'accel': 0.1, 'curvature': 0.0},
                {'accel': 0.0, 'curvature': 0.0},
                {'accel': -0.1, 'curvature': 0.0},
            ],
        },
    })
    assert response.status_code == 200
    body = response.json()
    assert body['model_ingest']['model_family'] == 'auto_e2e'
    assert body['model_ingest']['policy_candidates_added'] == 1
    assert body['policy']['candidate_count'] >= 2
    assert body['temporal_feature_memory']['time_queue_entries'] == 1
    assert body['shadow_only'] is True
    assert body['live_actuation'] is False
    assert body['raw_vehicle_tx'] is False


def test_world_v2_accepts_meteor_multitask_output_directly(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    response = client.post('/api/vision/autonomy/world-v2/step', json={
        'timestamp_s': 1.0,
        'ego_speed_ms': 8.0,
        'ego_distance_m': 0.0,
        'model_family': 'meteor',
        'model_output': {
            'bev_lanes': [{'lane_id': 'ego', 'centerline': [{'x': 0, 'y': 0}, {'x': 50, 'y': 0}], 'route_relevance': 1.0}],
            'detections_3d': [{'track_id': 'lead', 'class': 'car', 'x': 25, 'y': 0, 'z': 0, 'confidence': 0.9}],
            'traffic_lights': [{'state': 'green', 'confidence': 0.95}],
            'occupancy': {'cells': 100},
            'trajectories': [{
                'candidate_id': 'meteor-main',
                'probability': 0.85,
                'points': [
                    {'t': 0.5, 'x': 4, 'y': 0, 'speed': 8},
                    {'t': 1.0, 'x': 8, 'y': 0, 'speed': 8},
                    {'t': 1.5, 'x': 12, 'y': 0, 'speed': 8},
                ],
            }],
        },
    })
    assert response.status_code == 200
    body = response.json()
    assert body['model_ingest']['model_family'] == 'meteor'
    assert body['model_ingest']['model_products']['traffic_lights'][0]['state'] == 'green'
    assert body['lane_topology']['lane_count'] == 1
    assert body['policy']['candidate_count'] >= 2


def test_world_v2_rejects_incomplete_model_adapter_pair(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    response = client.post('/api/vision/autonomy/world-v2/step', json={
        'timestamp_s': 1.0,
        'ego_speed_ms': 5.0,
        'model_family': 'auto_e2e',
    })
    assert response.status_code == 400
    assert 'model_family and model_output' in response.json()['detail']
