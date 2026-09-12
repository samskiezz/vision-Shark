import pytest
from fastapi.testclient import TestClient

from vision_shark.api import create_app
from vision_shark.communication_lab import (
    BenchVoltageProfile,
    DiagnosticObservation,
    communication_health,
    simulate_voltage_profile,
    analyze_diagnostic_observation,
)
from vision_shark.domain import Frame


def test_voltage_profile_is_lab_only_and_rejects_connected_vehicle():
    with pytest.raises(ValueError, match="not permitted on a connected vehicle"):
        BenchVoltageProfile(
            profile_id="unsafe-connected",
            physical_vehicle_connected=True,
        )

    with pytest.raises(ValueError, match="unoccupied, non-propulsive"):
        BenchVoltageProfile(
            profile_id="unsafe-driver",
            driver_present=True,
        )

    with pytest.raises(ValueError, match="isolated fixture"):
        BenchVoltageProfile(
            profile_id="unsafe-hil",
            environment="hil_bench",
            isolated_fixture=False,
        )


def test_synthetic_voltage_profile_never_exposes_physical_output():
    result = simulate_voltage_profile(
        {
            "profile_id": "brownout-replay-1",
            "nominal_v": 12.8,
            "duration_ms": 100,
            "sample_rate_hz": 1000,
            "events": [
                {"start_ms": 20, "duration_ms": 20, "kind": "sag", "magnitude_v": 4.8},
                {"start_ms": 60, "duration_ms": 10, "kind": "dropout", "magnitude_v": 0},
            ],
        }
    )
    assert result["lab_only"] is True
    assert result["physical_voltage_output"] is False
    assert result["raw_vehicle_tx"] is False
    assert result["minimum_v"] == 0.0
    assert result["maximum_v"] == 12.8
    assert len(result["samples"]) == 101


def test_communication_health_reports_capture_quality_without_ecu_claims():
    frames = [
        Frame(ts_ns=0, bus="can0", arbitration_id=0x123, data="01"),
        Frame(ts_ns=10_000_000, bus="can0", arbitration_id=0x123, data="02"),
        Frame(ts_ns=20_000_000, bus="can0", arbitration_id=0x456, data="03"),
        Frame(ts_ns=30_000_000, bus="can0", arbitration_id=0x000, data="", error=True),
    ]
    report = communication_health(frames)
    assert report["frame_count"] == 4
    assert report["rx_frames"] == 4
    assert report["error_frames"] == 1
    assert report["unique_identifiers"] == 2
    assert report["quality"] == "poor"
    assert report["raw_vehicle_tx"] is False
    assert "do not prove ECU health" in report["interpretation_guard"]


def test_diagnostic_observation_parses_existing_negative_response_read_only():
    observation = DiagnosticObservation(
        source="passive_capture",
        protocol="uds",
        module="unknown-dmo-module",
        response_hex="7f2213",
    )
    result = analyze_diagnostic_observation(observation)
    assert result["status"] == "negative_response"
    assert result["negative_response"] == {"requested_service": 0x22, "nrc": 0x13}
    assert result["read_only_analysis"] is True
    assert result["raw_vehicle_tx"] is False


def _import_recording(client):
    response = client.post(
        "/api/interchange/import",
        json={
            "format": "candump",
            "content": "(1.000000000) can0 123#0102\n(1.010000000) can0 123#0304\n",
            "metadata": {"source": "communication-lab-test"},
        },
    )
    assert response.status_code == 200
    return response.json()["recording_id"]


def test_communication_lab_api_surfaces_are_non_actuating(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        safety = client.get("/api/research/communication/safety-profile")
        assert safety.status_code == 200
        assert safety.json()["road_vehicle_mode"]["voltage_fault_injection"] is False
        assert safety.json()["road_vehicle_mode"]["raw_can_tx"] is False

        replay = client.post(
            "/api/research/communication/voltage-replay",
            json={
                "profile_id": "api-replay",
                "duration_ms": 50,
                "sample_rate_hz": 100,
                "events": [{"start_ms": 10, "duration_ms": 10, "kind": "sag", "magnitude_v": 3}],
            },
        )
        assert replay.status_code == 200
        assert replay.json()["physical_voltage_output"] is False

        rejected = client.post(
            "/api/research/communication/voltage-replay",
            json={"profile_id": "vehicle-connected", "physical_vehicle_connected": True},
        )
        assert rejected.status_code == 422

        diagnostic = client.post(
            "/api/research/diagnostics/analyze-observation",
            json={
                "source": "import",
                "protocol": "doip",
                "module": "captured-response",
                "response_hex": "62f190313233",
            },
        )
        assert diagnostic.status_code == 200
        assert diagnostic.json()["status"] == "response_observed"
        assert diagnostic.json()["raw_vehicle_tx"] is False

        recording_id = _import_recording(client)
        health = client.get(f"/api/research/recordings/{recording_id}/communication-health")
        assert health.status_code == 200
        assert health.json()["recording_id"] == recording_id
        assert health.json()["frame_count"] == 2
        assert health.json()["quality"] == "good"
