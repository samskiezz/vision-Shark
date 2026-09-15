from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .autonomy.planning_world import PlanningWorldRuntime


class PlanningWorldStepBody(BaseModel):
    timestamp_s: float
    ego_speed_ms: float = Field(default=0.0, ge=0.0, le=90.0)
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


def install_autonomy_routes(app, audit) -> None:
    runtime = PlanningWorldRuntime()
    app.state.planning_world_v2 = runtime

    @app.get('/api/vision/autonomy/world-v2/profile')
    def planning_world_profile():
        return runtime.architecture_profile()

    @app.post('/api/vision/autonomy/world-v2/reset')
    def planning_world_reset():
        result = runtime.reset()
        audit.append('autonomy', 'planning_world_v2_reset', result)
        return result

    @app.post('/api/vision/autonomy/world-v2/step')
    def planning_world_step(body: PlanningWorldStepBody):
        try:
            result = runtime.step(body.model_dump())
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
                'shadow_only': True,
            },
        )
        return result
