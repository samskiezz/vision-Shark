from fastapi.testclient import TestClient

from vision_shark.api import create_app
from vision_shark.autonomy.data_engine import FleetDataEngine, benchmark_policy, hard_case_score, policy_disagreement, trajectory_metrics


def test_trajectory_metrics_identical_is_zero():
    trajectory = [
        {'t': 0.5, 'x': 5, 'y': 0, 'speed': 10, 'accel': 0},
        {'t': 1.0, 'x': 10, 'y': 0, 'speed': 10, 'accel': 0},
        {'t': 1.5, 'x': 15, 'y': 0, 'speed': 10, 'accel': 0},
    ]
    metric = trajectory_metrics(trajectory, trajectory)
    assert metric.samples == 3
    assert metric.ade_m == 0.0
    assert metric.fde_m == 0.0
    assert metric.speed_mae_ms == 0.0
    assert metric.accel_mae_ms2 == 0.0


def test_policy_disagreement_detects_divergent_futures():
    result = policy_disagreement([
        {'candidate_id': 'straight', 'points': [{'t': 1, 'x': 10, 'y': 0}, {'t': 3, 'x': 30, 'y': 0}]},
        {'candidate_id': 'left', 'points': [{'t': 1, 'x': 10, 'y': 1}, {'t': 3, 'x': 28, 'y': 8}]},
    ], horizon_s=3.0)
    assert result['candidate_count'] == 2
    assert result['max_pairwise_distance_m'] > 8.0


def test_hard_case_score_prioritizes_intervention_and_collision_risk():
    routine = hard_case_score({'scenario_id': 'routine', 'ego_speed_ms': 10})
    critical = hard_case_score({
        'scenario_id': 'critical',
        'ego_speed_ms': 20,
        'driver_intervention': True,
        'collision_risk': 0.9,
        'min_clearance_m': 1.0,
        'policy_disagreement_m': 5.0,
    })
    assert critical.score > routine.score
    assert critical.priority in {'high', 'critical'}
    assert 'driver_intervention' in critical.reasons
    assert 'predicted_collision_risk' in critical.reasons


def test_fleet_selector_deduplicates_similar_scenarios():
    engine = FleetDataEngine()
    scenarios = [
        {'scenario_id': 'a', 'driver_intervention': True, 'road_type': 'urban', 'ego_speed_ms': 10},
        {'scenario_id': 'b', 'driver_intervention': True, 'road_type': 'urban', 'ego_speed_ms': 10},
        {'scenario_id': 'c', 'driver_intervention': True, 'road_type': 'highway', 'ego_speed_ms': 30},
    ]
    result = engine.select(scenarios, limit=10, min_score=20, max_per_fingerprint=1)
    assert result['input_count'] == 3
    assert result['selected_count'] == 2
    assert {item['scenario']['scenario_id'] for item in result['selected']} == {'a', 'c'}
    assert result['data_uploaded'] is False


def test_training_manifest_is_deterministic_and_labels_risk_cases():
    engine = FleetDataEngine()
    scenarios = [{
        'scenario_id': 'risk-1',
        'recording_id': 44,
        'time_window': {'start_s': 12.0, 'end_s': 18.0},
        'driver_intervention': True,
        'route_ambiguity': True,
        'occlusion': True,
        'ego_speed_ms': 12,
    }]
    first = engine.training_manifest(scenarios, min_score=10)
    second = engine.training_manifest(scenarios, min_score=10)
    assert first['sha256'] == second['sha256']
    assert first['items'][0]['recording_id'] == 44
    labels = first['items'][0]['label_requirements']
    assert 'ego_trajectory' in labels
    assert 'lane_topology' in labels
    assert 'occlusion_state' in labels
    assert first['data_uploaded'] is False


def test_benchmark_policy_finds_closest_candidate():
    reference = [
        {'t': 1.0, 'x': 10, 'y': 0, 'speed': 10},
        {'t': 2.0, 'x': 20, 'y': 0, 'speed': 10},
    ]
    result = benchmark_policy(
        candidates=[
            {'candidate_id': 'good', 'source': 'model', 'probability': 0.7, 'points': reference},
            {'candidate_id': 'bad', 'source': 'model', 'probability': 0.3, 'points': [
                {'t': 1.0, 'x': 8, 'y': 4, 'speed': 8},
                {'t': 2.0, 'x': 14, 'y': 7, 'speed': 7},
            ]},
        ],
        reference_trajectory=reference,
        selected_candidate_id='good',
    )
    assert result['best_by_ade'] == 'good'
    good = next(row for row in result['candidates'] if row['candidate_id'] == 'good')
    assert good['selected'] is True
    assert good['metrics']['ade_m'] == 0.0
    assert result['shadow_only'] is True


def test_data_engine_api(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    score = client.post('/api/vision/autonomy/data-engine/score', json={'scenario': {
        'scenario_id': 'intervention', 'driver_intervention': True, 'collision_risk': 0.5, 'ego_speed_ms': 15
    }})
    assert score.status_code == 200
    assert score.json()['score'] >= 35

    manifest = client.post('/api/vision/autonomy/data-engine/training-manifest', json={
        'scenarios': [{'scenario_id': 'intervention', 'driver_intervention': True, 'ego_speed_ms': 15}],
        'limit': 10,
        'min_score': 20,
        'max_per_fingerprint': 1,
    })
    assert manifest.status_code == 200
    assert len(manifest.json()['items']) == 1
    assert manifest.json()['live_actuation'] is False

    benchmark = client.post('/api/vision/autonomy/policy/benchmark', json={
        'candidates': [{'candidate_id': 'p0', 'points': [
            {'t': 1.0, 'x': 5, 'y': 0, 'speed': 5},
            {'t': 2.0, 'x': 10, 'y': 0, 'speed': 5},
        ]}],
        'reference_trajectory': [
            {'t': 1.0, 'x': 5, 'y': 0, 'speed': 5},
            {'t': 2.0, 'x': 10, 'y': 0, 'speed': 5},
        ],
        'selected_candidate_id': 'p0',
    })
    assert benchmark.status_code == 200
    assert benchmark.json()['best_by_ade'] == 'p0'
