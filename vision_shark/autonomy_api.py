from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .autonomy.data_engine import FleetDataEngine, benchmark_policy
from .autonomy.model_adapters import adapter_profile, normalize_model_output
from .autonomy.planning_world import PlanningWorldRuntime
from .autonomy.temporal_memory import TemporalSpatialFeatureMemory


class PlanningWorldStepBody(BaseModel):
    timestamp_s: float
    ego_speed_ms: float = Field(default=0.0, ge=0.0, le=90.0)
    ego_distance_m: float = Field(default=0.0, ge=0.0)
    expected_cameras: list[str] = Field(default_factory=list, max_length=32)
    camera_frames: list[dict] = Field(default_factory=list, max_length=64)
    calibrations: list[dict] = Field(default_factory=list, max_length=32)
    camera_detections: list[dict] = Field(default_factory=list, max_length=4096)
    detections: list[dict] = Field(default_factory=list, max_length=4096)
    lanes: list[dict] = Field(default_factory=list, max_length=512)
    lane_path: list[dict] = Field(default_factory=list, max_length=1024)
    model_path: list[dict] = Field(default_factory=list, max_length=1024)
    policy_candidates: list[dict] = Field(default_factory=list, max_length=64)
    model_family: str | None = Field(default=None, max_length=64)
    model_output: dict | None = None
    cruise_target_ms: float | None = Field(default=None, ge=0.0, le=90.0)
    model_longitudinal: dict | None = None
    world_age_s: float = Field(default=0.0, ge=0.0, le=60.0)
    model_age_s: float = Field(default=0.0, ge=0.0, le=60.0)
    model_latency_ms: float = Field(default=0.0, ge=0.0, le=10000.0)
    calibration_valid: bool = True
    sync_tolerance_ms: float = Field(default=35.0, gt=0.0, le=1000.0)
    fusion_gate_m: float = Field(default=2.5, gt=0.0, le=25.0)


class ModelAdapterBody(BaseModel):
    model_family: str = Field(min_length=1, max_length=64)
    ego_speed_ms: float = Field(default=0.0, ge=0.0, le=90.0)
    output: dict


class DataEngineScoreBody(BaseModel):
    scenario: dict


class DataEngineSelectBody(BaseModel):
    scenarios: list[dict] = Field(default_factory=list, max_length=10000)
    limit: int = Field(default=100, ge=1, le=10000)
    min_score: float = Field(default=20.0, ge=0.0, le=100.0)
    max_per_fingerprint: int = Field(default=2, ge=1, le=100)


class PolicyBenchmarkBody(BaseModel):
    candidates: list[dict] = Field(default_factory=list, max_length=128)
    reference_trajectory: list[dict] = Field(default_factory=list, max_length=2048)
    selected_candidate_id: str | None = Field(default=None, max_length=128)


def _merge_model_output(payload: dict, model_family: str | None, model_output: dict | None, ego_speed_ms: float) -> tuple[dict, dict | None]:
    if not model_family and not model_output:
        return payload, None
    if not model_family or model_output is None:
        raise ValueError('model_family and model_output must be supplied together')
    normalized = normalize_model_output(model_family, model_output, ego_speed_ms=ego_speed_ms)
    merged = dict(payload)
    merged['policy_candidates'] = list(payload.get('policy_candidates') or []) + list(normalized.get('policy_candidates') or [])
    if not merged.get('lanes') and normalized.get('lanes'):
        merged['lanes'] = list(normalized.get('lanes') or [])
    if not merged.get('camera_detections') and normalized.get('camera_detections'):
        merged['camera_detections'] = list(normalized.get('camera_detections') or [])
    return merged, normalized


def install_autonomy_routes(app, audit) -> None:
    runtime = PlanningWorldRuntime()
    memory = TemporalSpatialFeatureMemory()
    data_engine = FleetDataEngine()
    app.state.planning_world_v2 = runtime
    app.state.temporal_spatial_memory = memory
    app.state.fleet_data_engine = data_engine

    @app.get('/api/vision/autonomy/world-v2/profile')
    def planning_world_profile():
        profile = runtime.architecture_profile()
        profile['temporal_memory'] = {
            'time_interval_s': memory.time_interval_s,
            'distance_interval_m': memory.distance_interval_m,
            'design': 'dual time and distance feature queues',
        }
        profile['data_engine'] = {
            'hard_case_scoring': True,
            'diversity_deduplication': True,
            'training_manifest': True,
            'policy_benchmark': True,
            'data_uploaded': False,
        }
        profile['model_ingest'] = {
            'supported_families': sorted((adapter_profile().get('supported_model_families') or {}).keys()),
            'direct_world_step_integration': True,
            'weights_included': False,
        }
        return profile

    @app.get('/api/vision/autonomy/model-adapters/profile')
    def model_adapters_profile():
        return adapter_profile()

    @app.post('/api/vision/autonomy/model-adapters/normalize')
    def model_adapters_normalize(body: ModelAdapterBody):
        try:
            result = normalize_model_output(body.model_family, body.output, ego_speed_ms=body.ego_speed_ms)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        audit.append(
            'autonomy',
            'model_output_normalized',
            {
                'model_family': result.get('model_family'),
                'policy_candidates': len(result.get('policy_candidates') or []),
                'live_actuation': False,
            },
        )
        return result

    @app.post('/api/vision/autonomy/data-engine/score')
    def data_engine_score(body: DataEngineScoreBody):
        result = data_engine.score_scenario(body.scenario)
        audit.append('autonomy', 'hard_case_scored', {'score': result['score'], 'priority': result['priority'], 'fingerprint': result['fingerprint']})
        return result

    @app.post('/api/vision/autonomy/data-engine/select')
    def data_engine_select(body: DataEngineSelectBody):
        result = data_engine.select(
            body.scenarios,
            limit=body.limit,
            min_score=body.min_score,
            max_per_fingerprint=body.max_per_fingerprint,
        )
        audit.append('autonomy', 'hard_cases_selected', {'input_count': result['input_count'], 'selected_count': result['selected_count']})
        return result

    @app.post('/api/vision/autonomy/data-engine/training-manifest')
    def data_engine_manifest(body: DataEngineSelectBody):
        result = data_engine.training_manifest(body.scenarios, limit=body.limit, min_score=body.min_score)
        audit.append('autonomy', 'training_manifest_built', {'items': len(result['items']), 'sha256': result['sha256']})
        return result

    @app.post('/api/vision/autonomy/policy/benchmark')
    def policy_benchmark(body: PolicyBenchmarkBody):
        result = benchmark_policy(
            candidates=body.candidates,
            reference_trajectory=body.reference_trajectory,
            selected_candidate_id=body.selected_candidate_id,
        )
        audit.append('autonomy', 'policy_benchmarked', {'candidates': len(result['candidates']), 'best_by_ade': result['best_by_ade']})
        return result

    @app.post('/api/vision/autonomy/world-v2/reset')
    def planning_world_reset():
        result = runtime.reset()
        memory.reset()
        result['temporal_memory_reset'] = True
        audit.append('autonomy', 'planning_world_v2_reset', result)
        return result

    @app.post('/api/vision/autonomy/world-v2/step')
    def planning_world_step(body: PlanningWorldStepBody):
        try:
            payload = body.model_dump()
            payload.pop('model_family', None)
            payload.pop('model_output', None)
            payload, normalized_model = _merge_model_output(payload, body.model_family, body.model_output, body.ego_speed_ms)
            result = runtime.step(payload)
            if normalized_model is not None:
                result['model_ingest'] = {
                    'model_family': normalized_model.get('model_family'),
                    'policy_candidates_added': len(normalized_model.get('policy_candidates') or []),
                    'model_products': normalized_model.get('model_products') or {},
                    'adapter_contract': normalized_model.get('adapter_contract'),
                }
            feature = {
                'camera_sync': (result.get('camera_sync') or {}).get('reason'),
                'camera_count': (result.get('camera_sync') or {}).get('camera_count'),
                'fused_detection_count': len((result.get('multicamera_fusion') or {}).get('fused_detections') or []),
                'track_count': (result.get('temporal_world') or {}).get('track_count'),
                'nearest_lane': ((result.get('lane_topology') or {}).get('nearest_lane') or {}).get('lane_id'),
                'scenario_tags': (result.get('scenario_mining') or {}).get('tags', []),
                'selected_candidate': (((result.get('policy') or {}).get('selected') or {}).get('candidate_id')),
                'model_family': None if normalized_model is None else normalized_model.get('model_family'),
                'model_latency_ms': body.model_latency_ms,
            }
            result['temporal_feature_memory'] = memory.update(body.timestamp_s, body.ego_distance_m, feature)
        except (TypeError, ValueError) as exc:
            audit.append('autonomy', 'planning_world_v2_rejected', {'error': str(exc)})
            raise HTTPException(400, str(exc)) from exc
        selected = (result.get('policy') or {}).get('selected') or {}
        audit.append(
            'autonomy',
            'planning_world_v2_step',
            {
                'step': result.get('step'),
                'timestamp_s': result.get('timestamp_s'),
                'tracks': (result.get('temporal_world') or {}).get('track_count'),
                'selected_candidate': selected.get('candidate_id'),
                'scenario_tags': (result.get('scenario_mining') or {}).get('tags', []),
                'model_family': None if normalized_model is None else normalized_model.get('model_family'),
                'memory_time_entries': (result.get('temporal_feature_memory') or {}).get('time_queue_entries'),
                'memory_distance_entries': (result.get('temporal_feature_memory') or {}).get('distance_queue_entries'),
                'shadow_only': True,
            },
        )
        return result
