from fastapi.testclient import TestClient

from vision_shark.api import create_app
from vision_shark.autonomy.hybrid import HybridShadowPlanner


def test_hybrid_planner_selects_safe_candidate():
    planner = HybridShadowPlanner()
    result = planner.run(
        ego_speed_ms=15.0,
        detections=[{"track_id": "lead", "class": "car", "x": 45.0, "y": 0.1, "vx": 12.0, "confidence": 0.95}],
        lane_path=[{"x": 0.0, "y": 0.0, "confidence": 0.9}, {"x": 80.0, "y": 0.2, "confidence": 0.9}],
        model_path=[{"x": 0.0, "y": 0.0, "confidence": 0.8}, {"x": 80.0, "y": 0.4, "confidence": 0.8}],
        cruise_target_ms=22.0,
        model_longitudinal={"target_speed_ms": 20.0, "confidence": 0.8},
    )
    assert result["architecture"] == "hybrid_shadow_v2"
    assert result["lead"]["present"] is True
    assert result["selected"]["guardian"]["pass"] is True
    assert result["control_target"]["live_actuation_allowed"] is False
    assert result["live_actuation"] is False
    assert result["raw_vehicle_tx"] is False


def test_critical_lead_forces_conservative_longitudinal_candidate():
    planner = HybridShadowPlanner()
    result = planner.run(
        ego_speed_ms=20.0,
        detections=[{"track_id": "lead", "class": "car", "x": 8.0, "y": 0.0, "vx": 0.0, "confidence": 1.0}],
        lane_path=[{"x": 0.0, "y": 0.0, "confidence": 1.0}, {"x": 60.0, "y": 0.0, "confidence": 1.0}],
        cruise_target_ms=25.0,
    )
    assert result["risk"]["risk"] == "critical"
    selected = [x for x in result["longitudinal_candidates"] if x["selected"]]
    assert len(selected) == 1
    assert selected[0]["source"] == "lead_gap"
    assert selected[0]["target_speed_ms"] < 20.0


def test_stale_world_prefers_controlled_stop():
    planner = HybridShadowPlanner()
    result = planner.run(
        ego_speed_ms=12.0,
        lane_path=[{"x": 0.0, "y": 0.0, "confidence": 1.0}, {"x": 60.0, "y": 0.0, "confidence": 1.0}],
        world_age_s=2.0,
    )
    assert "world_stale" in result["odd"]["reasons"]
    assert result["selected"]["generator"] == "controlled_stop"


def test_hybrid_shadow_api_is_non_actuating(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/vision/autonomy/hybrid-shadow",
            json={
                "ego_speed_ms": 10.0,
                "lane_path": [{"x": 0, "y": 0, "confidence": 1}, {"x": 50, "y": 0, "confidence": 1}],
                "model_path": [{"x": 0, "y": 0, "confidence": 0.7}, {"x": 50, "y": 0.2, "confidence": 0.7}],
                "cruise_target_ms": 14.0,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["shadow_only"] is True
        assert body["live_actuation"] is False
        assert body["raw_vehicle_tx"] is False
