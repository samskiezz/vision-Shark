from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, Field

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


def install_autonomy_routes(app, audit) -> None:
    runtime = PlanningWorldRuntime()
    memory = TemporalSpatialFeatureMemory()
    app.state.planning_world_v2 = runtime
    app.state.temporal_spatial_memory = memory

    @app.get('/api/vision/autonomy/world-v2/profile')
    def planning_world_profile():
        profile = runtime.architecture_profile()
        profile['temporal_memory'] = {
            'time_interval_s': memory.time_interval_s,
            'distance_interval_m': memory.distance_interval_m,
            'design': 'dual time and distance feature queues',
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
            result = runtime.step(body.model_dump())
            feature = {
                'camera_sync': (result.get('camera_sync') or {}).get('reason'),
                'camera_count': (result.get('camera_sync') or {}).get('camera_count'),
                'fused_detection_count': len((result.get('multicamera_fusion') or {}).get('fused_detections') or []),
                'track_count': (result.get('temporal_world') or {}).get('track_count'),
                'nearest_lane': ((result.get('lane_topology') or {}).get('nearest_lane') or {}).get('lane_id'),
                'scenario_tags': (result.get('scenario_mining') or {}).get('tags', []),
                'selected_candidate': (((result.get('policy') or {}).get('selected') or {}).get('candidate_id')),
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
                'memory_time_entries': (result.get('temporal_feature_memory') or {}).get('time_queue_entries'),
                'memory_distance_entries': (result.get('temporal_feature_memory') or {}).get('distance_queue_entries'),
                'shadow_only': True,
            },
        )
        return result
