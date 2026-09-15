import pytest
from fastapi.testclient import TestClient

from vision_shark.api import create_app
from vision_shark.autonomy.temporal_memory import TemporalSpatialFeatureMemory


def test_time_and_distance_queues_push_independently():
    memory = TemporalSpatialFeatureMemory(time_interval_s=0.1, distance_interval_m=2.0, max_time_entries=8, max_distance_entries=8)
    first = memory.update(0.0, 0.0, {'scene': 'start'})
    assert first['pushed'] == ['time', 'distance']
    second = memory.update(0.05, 0.5, {'scene': 'nearby'})
    assert second['pushed'] == []
    third = memory.update(0.11, 0.8, {'scene': 'time'})
    assert third['pushed'] == ['time']
    fourth = memory.update(0.12, 2.1, {'scene': 'distance'})
    assert fourth['pushed'] == ['distance']
    assert fourth['time_queue_entries'] == 2
    assert fourth['distance_queue_entries'] == 2


def test_distance_memory_preserves_context_during_long_stop():
    memory = TemporalSpatialFeatureMemory(time_interval_s=0.5, distance_interval_m=5.0, max_time_entries=4, max_distance_entries=4)
    memory.update(0.0, 0.0, {'state': 'approach'})
    for timestamp in (1.0, 2.0, 3.0, 4.0):
        memory.update(timestamp, 0.0, {'state': 'stopped', 'timestamp': timestamp})
    snapshot = memory.snapshot()
    assert snapshot['time_queue_entries'] == 4
    assert snapshot['distance_queue_entries'] == 1
    assert snapshot['distance_context_span_m'] == 0.0
    assert snapshot['context'][0]['feature']['state'] == 'approach'


def test_memory_requires_monotonic_time_and_cumulative_distance():
    memory = TemporalSpatialFeatureMemory()
    memory.update(1.0, 10.0, {'state': 'ok'})
    with pytest.raises(ValueError, match='timestamps must be monotonic'):
        memory.update(0.5, 10.0, {'state': 'bad-time'})
    with pytest.raises(ValueError, match='cumulative and monotonic'):
        memory.update(2.0, 9.0, {'state': 'bad-distance'})


def test_memory_context_deduplicates_same_feature_between_queues():
    memory = TemporalSpatialFeatureMemory(time_interval_s=0.1, distance_interval_m=1.0)
    memory.update(0.0, 0.0, {'scene': 'same'})
    context = memory.context()
    assert len(context) == 1
    assert context[0]['feature']['scene'] == 'same'


def test_world_v2_api_returns_and_resets_temporal_memory(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    payload = {
        'timestamp_s': 1.0,
        'ego_speed_ms': 5.0,
        'ego_distance_m': 0.0,
        'camera_detections': [{'track_id': 'lead', 'class': 'car', 'x': 30.0, 'y': 0.0, 'confidence': 0.9}],
        'lanes': [{'lane_id': 'ego', 'centerline': [{'x': 0, 'y': 0}, {'x': 50, 'y': 0}], 'route_relevance': 1.0}],
        'policy_candidates': [{'candidate_id': 'p0', 'probability': 0.8, 'points': [
            {'t': 0.5, 'x': 2.5, 'y': 0, 'speed': 5},
            {'t': 1.0, 'x': 5.0, 'y': 0, 'speed': 5},
        ]}],
    }
    first = client.post('/api/vision/autonomy/world-v2/step', json=payload)
    assert first.status_code == 200
    memory = first.json()['temporal_feature_memory']
    assert memory['time_queue_entries'] == 1
    assert memory['distance_queue_entries'] == 1

    second = client.post('/api/vision/autonomy/world-v2/step', json={**payload, 'timestamp_s': 1.1, 'ego_distance_m': 1.2})
    assert second.status_code == 200
    memory2 = second.json()['temporal_feature_memory']
    assert memory2['time_queue_entries'] >= 2
    assert memory2['distance_queue_entries'] >= 2

    reset = client.post('/api/vision/autonomy/world-v2/reset')
    assert reset.status_code == 200
    assert reset.json()['temporal_memory_reset'] is True

    third = client.post('/api/vision/autonomy/world-v2/step', json={**payload, 'timestamp_s': 0.5, 'ego_distance_m': 0.0})
    assert third.status_code == 200
    assert third.json()['temporal_feature_memory']['time_queue_entries'] == 1
