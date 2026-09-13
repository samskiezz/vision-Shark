from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class StartupBusEvent(BaseModel):
    ts_ms: float = Field(ge=0, le=600_000)
    module: str = Field(default="unknown", min_length=1, max_length=128)
    channel: Literal["can", "can_fd", "doip", "obd2", "uds", "vendor", "unknown"] = "unknown"
    event: Literal[
        "frame_seen",
        "response_seen",
        "negative_response",
        "timeout",
        "transport_error",
        "disconnect",
        "reconnect",
    ]
    source: Literal["passive_capture", "import", "hil_bench"] = "passive_capture"


class StartupVoltagePoint(BaseModel):
    ts_ms: float = Field(ge=0, le=600_000)
    volts: float = Field(ge=0, le=80)
    source: Literal["measured", "synthetic"] = "measured"


class StartupCommunicationTrace(BaseModel):
    trace_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
    events: list[StartupBusEvent] = Field(min_length=1, max_length=50_000)
    voltage: list[StartupVoltagePoint] = Field(default_factory=list, max_length=100_000)
    physical_vehicle_connected: bool = False
    fault_injection_commanded: bool = False

    @model_validator(mode="after")
    def reject_live_fault_injection(self):
        if self.physical_vehicle_connected and self.fault_injection_commanded:
            raise ValueError("live vehicle voltage fault injection is not permitted")
        return self


class FlashTraceEvent(BaseModel):
    ts_ms: float = Field(ge=0, le=86_400_000)
    direction: Literal["host_to_target", "target_to_host", "local"]
    kind: Literal[
        "request",
        "response",
        "ack",
        "timeout",
        "transport_error",
        "disconnect",
        "reconnect",
        "keepalive",
        "block_complete",
    ]
    block_index: int | None = Field(default=None, ge=0, le=10_000_000)
    bytes_count: int = Field(default=0, ge=0, le=16_777_216)
    note: str = Field(default="", max_length=500)


class FlashTransportTrace(BaseModel):
    trace_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
    transport: Literal["can_isotp", "doip", "vendor", "unknown"] = "unknown"
    source: Literal["captured", "import", "hil_bench", "simulator"] = "captured"
    events: list[FlashTraceEvent] = Field(min_length=1, max_length=200_000)
    contains_generated_vehicle_requests: bool = False
    physical_vehicle_connected: bool = False

    @model_validator(mode="after")
    def observation_only(self):
        if self.physical_vehicle_connected and self.contains_generated_vehicle_requests:
            raise ValueError("live vehicle flash request generation is not permitted")
        return self


def _sorted_events(events):
    return sorted(events, key=lambda item: item.ts_ms)


def analyze_startup_communication(trace: StartupCommunicationTrace | dict) -> dict:
    value = trace if isinstance(trace, StartupCommunicationTrace) else StartupCommunicationTrace.model_validate(trace)
    events = _sorted_events(value.events)
    voltage = sorted(value.voltage, key=lambda item: item.ts_ms)

    by_module: dict[str, list[StartupBusEvent]] = defaultdict(list)
    for event in events:
        by_module[event.module].append(event)

    modules = {}
    successful_kinds = {"frame_seen", "response_seen", "negative_response", "reconnect"}
    for module, module_events in sorted(by_module.items()):
        successes = [item for item in module_events if item.event in successful_kinds]
        failures = [item for item in module_events if item.event in {"timeout", "transport_error", "disconnect"}]
        channels = sorted({item.channel for item in module_events})
        modules[module] = {
            "first_observed_ms": successes[0].ts_ms if successes else None,
            "last_observed_ms": successes[-1].ts_ms if successes else None,
            "successful_observations": len(successes),
            "failure_observations": len(failures),
            "channels": channels,
        }

    failure_times = [item.ts_ms for item in events if item.event in {"timeout", "transport_error", "disconnect"}]
    low_voltage_points = []
    if voltage:
        nominal = max(point.volts for point in voltage)
        threshold = nominal * 0.80
        low_voltage_points = [point for point in voltage if point.volts <= threshold]
    else:
        nominal = None
        threshold = None

    correlated_failures = 0
    if low_voltage_points and failure_times:
        low_times = [point.ts_ms for point in low_voltage_points]
        for failure_ts in failure_times:
            if any(abs(failure_ts - low_ts) <= 250 for low_ts in low_times):
                correlated_failures += 1

    first_any = min(
        (item["first_observed_ms"] for item in modules.values() if item["first_observed_ms"] is not None),
        default=None,
    )
    return {
        "trace_id": value.trace_id,
        "first_bus_activity_ms": first_any,
        "modules": modules,
        "failure_events": len(failure_times),
        "voltage": {
            "samples": len(voltage),
            "observed_max_v": round(nominal, 6) if nominal is not None else None,
            "low_voltage_threshold_v": round(threshold, 6) if threshold is not None else None,
            "low_voltage_samples": len(low_voltage_points),
            "failures_within_250ms_of_low_voltage": correlated_failures,
        },
        "read_only_analysis": True,
        "raw_vehicle_tx": False,
        "physical_voltage_output": False,
        "interpretation_guard": (
            "Timing correlation can identify startup communication windows and brownout sensitivity, "
            "but does not establish a bypass, unlock or safe flash window."
        ),
    }


def analyze_flash_transport_trace(trace: FlashTransportTrace | dict) -> dict:
    value = trace if isinstance(trace, FlashTransportTrace) else FlashTransportTrace.model_validate(trace)
    events = _sorted_events(value.events)
    start_ms = events[0].ts_ms
    end_ms = events[-1].ts_ms
    duration_s = max(0.0, (end_ms - start_ms) / 1_000)

    transferred = sum(item.bytes_count for item in events if item.direction == "host_to_target")
    responses = sum(1 for item in events if item.kind in {"response", "ack"})
    timeouts = sum(1 for item in events if item.kind == "timeout")
    transport_errors = sum(1 for item in events if item.kind == "transport_error")
    disconnects = [item for item in events if item.kind == "disconnect"]
    reconnects = [item for item in events if item.kind == "reconnect"]
    completed_blocks = sorted(
        {item.block_index for item in events if item.kind == "block_complete" and item.block_index is not None}
    )

    recovery_delays_ms = []
    for disconnect in disconnects:
        later = next((item for item in reconnects if item.ts_ms >= disconnect.ts_ms), None)
        if later is not None:
            recovery_delays_ms.append(later.ts_ms - disconnect.ts_ms)

    reliability_denominator = max(1, responses + timeouts + transport_errors)
    success_ratio = responses / reliability_denominator
    throughput_bps = transferred / duration_s if duration_s > 0 else 0.0

    return {
        "trace_id": value.trace_id,
        "transport": value.transport,
        "source": value.source,
        "duration_ms": round(end_ms - start_ms, 6),
        "host_to_target_bytes_observed": transferred,
        "observed_throughput_bytes_per_s": round(throughput_bps, 3),
        "responses_or_acks": responses,
        "timeouts": timeouts,
        "transport_errors": transport_errors,
        "disconnects": len(disconnects),
        "reconnects": len(reconnects),
        "recovery_delays_ms": [round(item, 6) for item in recovery_delays_ms],
        "completed_blocks": completed_blocks,
        "observed_response_success_ratio": round(success_ratio, 6),
        "read_only_analysis": True,
        "raw_vehicle_tx": False,
        "flash_command_generation": False,
        "interpretation_guard": (
            "This analyzes captured or simulated transport behavior only. It does not generate programming requests, "
            "SecurityAccess, unlocks or ECU writes."
        ),
    }
