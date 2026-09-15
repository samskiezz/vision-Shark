from fastapi.testclient import TestClient

from vision_shark.api import create_app
from vision_shark.autonomy.planning_world import (
    CameraCalibration,
    CounterfactualTrajectoryEvaluator,
    LaneTopologyGraph,
    MultiCameraSynchronizer,
    MultimodalAgentForecaster,
    PlanningWorldRuntime,
    PolicyCandidate,
    CandidatePoint,
    fuse_multicamera_detections,
    project_pixel_depth_to_ego,
)


def identity_calibration(camera_id='front'):
    return CameraCalibration(
        camera_id=camera_id,
        fx=1000.0,
        fy=1000.0,
        cx=640.0,
        cy=360.0,
        camera_to_ego=(
            (0.0, 0.0, 1.0, 0.0),
            (-1.0, 0.0, 0.0, 0.0),
            (0.0, -1.0, 0.0, 1.5),
            (0.0, 0.0, 0.0, 1.0),
        ),
        width=1280,
        height=720,
    )


def test_pixel_depth_projection_uses_calibration_transform():
    calibration = identity_calibration()
    x, y, z = project_pixel_depth_to_ego(calibration, 640.0, 360.0, 20.0)
    assert x == 20.0
    assert abs(y) < 1e-9
    assert z == 1.5


def test_camera_sync_detects_missing_and_desync():
    sync = MultiCameraSynchronizer(['front', 'left', 'right'], tolerance_ms=20.0)
    result = sync.evaluate([
        {'camera_id': 'front', 'timestamp_s': 10.000},
        {'camera_id': 'left', 'timestamp_s': 10.040},
    ])
    assert result['synchronized'] is False
    assert result['reason'] == 'missing_camera'
    assert result['missing'] == ['right']
    assert result['span_ms'] >= 39.0


def test_geometry_fusion_merges_same_object_across_cameras():
    fused = fuse_multicamera_detections([
        {'source_track_id': 'a', 'camera_id': 'front', 'class': 'car', 'x': 25.0, 'y': 0.2, 'z': 0.0, 'confidence': 0.8},
        {'source_track_id': 'b', 'camera_id': 'front_left', 'class': 'car', 'x': 25.4, 'y': 0.0, 'z': 0.0, 'confidence': 0.7},
        {'source_track_id': 'c', 'camera_id': 'right', 'class': 'pedestrian', 'x': 12.0, 'y': 5.0, 'z': 0.0, 'confidence': 0.9},
    ], gate_m=1.0)
    assert len(fused) == 2
    car = next(item for item in fused if item.cls == 'car')
    assert car.source_count == 2
    assert set(car.source_cameras) == {'front', 'front_left'}
    assert car.confidence > 0.9


def test_forecaster_produces_multiple_future_modes_for_moving_agent():
    forecaster = MultimodalAgentForecaster()
    hypotheses = forecaster.forecast({'x': 30.0, 'y': 0.0, 'vx': -5.0, 'vy': 0.0, 'confidence': 0.9, 'class': 'car'})
    assert {item.hypothesis_id for item in hypotheses} >= {'constant_velocity', 'decelerate', 'turn_left', 'turn_right'}
    assert all(len(item.points) == 5 for item in hypotheses)
    assert sum(item.probability for item in hypotheses) <= 1.0


def test_counterfactual_evaluator_prefers_clear_trajectory():
    forecaster = MultimodalAgentForecaster()
    forecasts = {'lead': forecaster.forecast({'x': 10.0, 'y': 0.0, 'vx': 0.0, 'vy': 0.0, 'confidence': 1.0, 'class': 'car'})}
    graph = LaneTopologyGraph([
        {'lane_id': 'ego', 'centerline': [{'x': 0, 'y': 0}, {'x': 50, 'y': 0}], 'route_relevance': 1.0},
        {'lane_id': 'left', 'centerline': [{'x': 0, 'y': 4}, {'x': 50, 'y': 4}], 'route_relevance': 0.8},
    ])
    evaluator = CounterfactualTrajectoryEvaluator(collision_radius_m=2.0)
    straight = PolicyCandidate('straight', 'model', 0.8, [
        CandidatePoint(0.5, 5.0, 0.0, 10.0),
        CandidatePoint(1.0, 10.0, 0.0, 10.0),
        CandidatePoint(1.5, 15.0, 0.0, 10.0),
    ])
    offset = PolicyCandidate('offset', 'model', 0.7, [
        CandidatePoint(0.5, 5.0, 4.0, 10.0),
        CandidatePoint(1.0, 10.0, 4.0, 10.0),
        CandidatePoint(1.5, 15.0, 4.0, 10.0),
    ])
    straight_eval = evaluator.evaluate(straight, forecasts, graph)
    offset_eval = evaluator.evaluate(offset, forecasts, graph)
    assert straight_eval['expected_collision_risk'] > offset_eval['expected_collision_risk']
    assert straight_eval['score'] > offset_eval['score']


def test_planning_world_stateful_tracking_and_policy_selection():
    runtime = PlanningWorldRuntime()
    calibration = {
        'camera_id': 'front', 'fx': 1000, 'fy': 1000, 'cx': 640, 'cy': 360,
        'width': 1280, 'height': 720,
        'camera_to_ego': [[0, 0, 1, 0], [-1, 0, 0, 0], [0, -1, 0, 1.5], [0, 0, 0, 1]],
    }
    base = {
        'ego_speed_ms': 10.0,
        'expected_cameras': ['front'],
        'calibrations': [calibration],
        'camera_frames': [{'camera_id': 'front', 'timestamp_s': 1.0}],
        'lanes': [{'lane_id': 'ego', 'centerline': [{'x': 0, 'y': 0}, {'x': 60, 'y': 0}], 'route_relevance': 1.0}],
        'policy_candidates': [
            {'candidate_id': 'straight', 'probability': 0.9, 'points': [
                {'t': 0.5, 'x': 5, 'y': 0, 'speed': 10}, {'t': 1.0, 'x': 10, 'y': 0, 'speed': 10}, {'t': 1.5, 'x': 15, 'y': 0, 'speed': 10}
            ]},
            {'candidate_id': 'left', 'probability': 0.6, 'points': [
                {'t': 0.5, 'x': 5, 'y': 4, 'speed': 10}, {'t': 1.0, 'x': 10, 'y': 4, 'speed': 10}, {'t': 1.5, 'x': 15, 'y': 4, 'speed': 10}
            ]},
        ],
    }
    first = runtime.step({**base, 'timestamp_s': 1.0, 'camera_detections': [{'camera_id': 'front', 'track_id': 'lead', 'class': 'car', 'x': 16.0, 'y': 0.0, 'confidence': 1.0}]})
    second = runtime.step({**base, 'timestamp_s': 2.0, 'camera_frames': [{'camera_id': 'front', 'timestamp_s': 2.0}], 'camera_detections': [{'camera_id': 'front', 'track_id': 'lead', 'class': 'car', 'x': 12.0, 'y': 0.0, 'confidence': 1.0}]})
    assert first['temporal_world']['track_count'] == 1
    assert second['temporal_world']['tracks'][0]['vx'] < 0
    assert second['policy']['selected']['candidate_id'] in {'left', 'fallback-lane_path', 'fallback-controlled_stop'}
    assert second['shadow_only'] is True
    assert second['live_actuation'] is False
    assert second['raw_vehicle_tx'] is False
    assert second['occupancy_flow']['layers']


def test_planning_world_api_is_stateful_and_non_actuating(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    profile = client.get('/api/vision/autonomy/world-v2/profile')
    assert profile.status_code == 200
    assert profile.json()['shadow_only'] is True
    payload = {
        'timestamp_s': 1.0,
        'ego_speed_ms': 8.0,
        'camera_detections': [{'track_id': 'lead', 'class': 'car', 'x': 20.0, 'y': 0.0, 'confidence': 0.9}],
        'lanes': [{'lane_id': 'ego', 'centerline': [{'x': 0, 'y': 0}, {'x': 50, 'y': 0}], 'route_relevance': 1.0}],
        'policy_candidates': [{'candidate_id': 'p0', 'probability': 0.8, 'points': [
            {'t': 0.5, 'x': 4, 'y': 0, 'speed': 8}, {'t': 1.0, 'x': 8, 'y': 0, 'speed': 8}
        ]}],
    }
    response = client.post('/api/vision/autonomy/world-v2/step', json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body['architecture'] == 'planning_world_v2'
    assert body['shadow_only'] is True
    assert body['live_actuation'] is False
    assert body['raw_vehicle_tx'] is False
    reset = client.post('/api/vision/autonomy/world-v2/reset')
    assert reset.status_code == 200
    assert reset.json()['reset'] is True
