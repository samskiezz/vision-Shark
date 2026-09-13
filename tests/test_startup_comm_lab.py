import pytest
from fastapi.testclient import TestClient

from vision_shark.api import create_app
from vision_shark.startup_comm_lab import (
    FlashTransportTrace,
    StartupCommunicationTrace,
    analyze_flash_transport_trace,
    analyze_startup_communication,
)


def test_startup_trace_correlates_low_voltage_with_passive_failures():
    report = analyze_startup_communication(
        {
            "trace_id": "startup-001",
            "physical_vehicle_connected": True,
            "fault_injection_commanded": False,
            "voltage": [
                {"ts_ms": 0, "volts": 12.8, "source": "measured"},
                {"ts_ms": 100, "volts": 9.0, "source": "measured"},
                {"ts_ms": 300, "volts": 12.5, "source": "measured"},
            ],
            "events": [
                {"ts_ms": 20, "module": "gateway", "channel": "can", "event": "frame_seen"},
                {"ts_ms": 110, "module": "gateway", "channel": "can", "event": "timeout"},
                {"ts_ms": 350, "module": "gateway", "channel": "can", "event": "reconnect"},
            ],
        }
    )
    assert report["first_bus_activity_ms"] == 20
    assert report["failure_events"] == 1
    assert report["voltage"]["failures_within_250ms_of_low_voltage"] == 1
    assert report["physical_voltage_output"] is False
    assert report["raw_vehicle_tx"] is False


def test_startup_trace_rejects_live_fault_injection():
    with pytest.raises(ValueError, match="live vehicle voltage fault injection"):
        StartupCommunicationTrace.model_validate(
            {
                "trace_id": "unsafe-startup",
                "physical_vehicle_connected": True,
                "fault_injection_commanded": True,
                "events": [
                    {"ts_ms": 0, "module": "gateway", "channel": "can", "event": "frame_seen"}
                ],
            }
        )


def test_flash_transport_trace_analyzes_existing_capture_only():
    report = analyze_flash_transport_trace(
        {
            "trace_id": "flash-capture-001",
            "transport": "can_isotp",
            "source": "captured",
            "events": [
                {"ts_ms": 0, "direction": "host_to_target", "kind": "request", "bytes_count": 64},
                {"ts_ms": 20, "direction": "target_to_host", "kind": "ack", "bytes_count": 8},
                {"ts_ms": 40, "direction": "local", "kind": "block_complete", "block_index": 0},
                {"ts_ms": 60, "direction": "local", "kind": "disconnect"},
                {"ts_ms": 160, "direction": "local", "kind": "reconnect"},
            ],
        }
    )
    assert report["host_to_target_bytes_observed"] == 64
    assert report["completed_blocks"] == [0]
    assert report["recovery_delays_ms"] == [100]
    assert report["flash_command_generation"] is False
    assert report["raw_vehicle_tx"] is False


def test_flash_transport_trace_rejects_generated_live_vehicle_requests():
    with pytest.raises(ValueError, match="live vehicle flash request generation"):
        FlashTransportTrace.model_validate(
            {
                "trace_id": "unsafe-flash",
                "transport": "doip",
                "source": "captured",
                "physical_vehicle_connected": True,
                "contains_generated_vehicle_requests": True,
                "events": [
                    {"ts_ms": 0, "direction": "host_to_target", "kind": "request", "bytes_count": 8}
                ],
            }
        )


def test_startup_and_flash_analysis_api_paths(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        startup = client.post(
            "/api/research/communication/startup/analyze",
            json={
                "trace_id": "api-startup",
                "physical_vehicle_connected": True,
                "fault_injection_commanded": False,
                "events": [
                    {"ts_ms": 5, "module": "dmo", "channel": "obd2", "event": "response_seen"},
                    {"ts_ms": 50, "module": "dmo", "channel": "obd2", "event": "timeout"},
                ],
                "voltage": [
                    {"ts_ms": 0, "volts": 12.7, "source": "measured"},
                    {"ts_ms": 45, "volts": 9.5, "source": "measured"},
                ],
            },
        )
        assert startup.status_code == 200
        assert startup.json()["modules"]["dmo"]["first_observed_ms"] == 5
        assert startup.json()["raw_vehicle_tx"] is False

        rejected_startup = client.post(
            "/api/research/communication/startup/analyze",
            json={
                "trace_id": "api-unsafe-startup",
                "physical_vehicle_connected": True,
                "fault_injection_commanded": True,
                "events": [
                    {"ts_ms": 0, "module": "gateway", "channel": "can", "event": "frame_seen"}
                ],
            },
        )
        assert rejected_startup.status_code == 422

        flash = client.post(
            "/api/research/communication/flash-trace/analyze",
            json={
                "trace_id": "api-flash",
                "transport": "doip",
                "source": "import",
                "events": [
                    {"ts_ms": 0, "direction": "host_to_target", "kind": "request", "bytes_count": 32},
                    {"ts_ms": 25, "direction": "target_to_host", "kind": "response", "bytes_count": 8},
                ],
            },
        )
        assert flash.status_code == 200
        assert flash.json()["responses_or_acks"] == 1
        assert flash.json()["flash_command_generation"] is False
