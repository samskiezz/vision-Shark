from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class VoltageFaultEvent(BaseModel):
    start_ms: float = Field(ge=0, le=60_000)
    duration_ms: float = Field(gt=0, le=10_000)
    kind: Literal["sag", "dropout", "ripple", "spike"]
    magnitude_v: float = Field(ge=0, le=60)
    frequency_hz: float | None = Field(default=None, gt=0, le=20_000)

    @model_validator(mode="after")
    def validate_event(self):
        if self.kind == "ripple" and self.frequency_hz is None:
            raise ValueError("ripple events require frequency_hz")
        if self.kind != "ripple" and self.frequency_hz is not None:
            raise ValueError("frequency_hz is only valid for ripple events")
        return self


class BenchVoltageProfile(BaseModel):
    profile_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
    nominal_v: float = Field(default=12.8, ge=1, le=60)
    duration_ms: float = Field(default=5_000, gt=0, le=60_000)
    sample_rate_hz: int = Field(default=1_000, ge=10, le=20_000)
    environment: Literal["replay", "hil_bench"] = "replay"
    physical_vehicle_connected: bool = False
    driver_present: bool = False
    propulsion_enabled: bool = False
    vehicle_mobile: bool = False
    isolated_fixture: bool = True
    events: list[VoltageFaultEvent] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def enforce_lab_only(self):
        if self.physical_vehicle_connected:
            raise ValueError("voltage fault injection is not permitted on a connected vehicle")
        if self.driver_present or self.propulsion_enabled or self.vehicle_mobile:
            raise ValueError("voltage fault injection requires an unoccupied, non-propulsive bench/replay setup")
        if self.environment == "hil_bench" and not self.isolated_fixture:
            raise ValueError("HIL bench voltage testing requires an isolated fixture")
        for event in self.events:
            if event.start_ms + event.duration_ms > self.duration_ms:
                raise ValueError("voltage fault event exceeds profile duration")
        return self


class DiagnosticObservation(BaseModel):
    source: Literal["passive_capture", "import", "hil_bench"] = "passive_capture"
    protocol: Literal["uds", "doip", "can_isotp", "vendor", "unknown"] = "unknown"
    module: str = Field(default="unknown", min_length=1, max_length=128)
    response_hex: str = Field(default="", max_length=16_384)
    timeout: bool = False
    transport_errors: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("response_hex")
    @classmethod
    def validate_hex(cls, value: str) -> str:
        compact = "".join(str(value).split()).lower()
        if len(compact) % 2:
            raise ValueError("diagnostic response hex must have an even length")
        try:
            bytes.fromhex(compact)
        except ValueError as exc:
            raise ValueError("diagnostic response must be hexadecimal") from exc
        return compact


class VoltageSample(BaseModel):
    ts_ns: int = Field(ge=0)
    volts: float
    synthetic: bool = True


def simulate_voltage_profile(profile: BenchVoltageProfile | dict) -> dict:
    value = profile if isinstance(profile, BenchVoltageProfile) else BenchVoltageProfile.model_validate(profile)
    step_ns = int(1_000_000_000 / value.sample_rate_hz)
    count = int(math.floor(value.duration_ms * value.sample_rate_hz / 1_000)) + 1
    samples: list[VoltageSample] = []
    minimum = value.nominal_v
    maximum = value.nominal_v

    for index in range(count):
        ts_ns = index * step_ns
        t_ms = ts_ns / 1_000_000
        volts = value.nominal_v
        for event in value.events:
            if not event.start_ms <= t_ms < event.start_ms + event.duration_ms:
                continue
            if event.kind == "sag":
                volts = max(0.0, value.nominal_v - event.magnitude_v)
            elif event.kind == "dropout":
                volts = 0.0
            elif event.kind == "spike":
                volts = value.nominal_v + event.magnitude_v
            elif event.kind == "ripple":
                phase_s = (t_ms - event.start_ms) / 1_000
                volts = value.nominal_v + event.magnitude_v * math.sin(2 * math.pi * float(event.frequency_hz) * phase_s)
        minimum = min(minimum, volts)
        maximum = max(maximum, volts)
        samples.append(VoltageSample(ts_ns=ts_ns, volts=round(volts, 6)))

    return {
        "profile_id": value.profile_id,
        "environment": value.environment,
        "lab_only": True,
        "physical_voltage_output": False,
        "raw_vehicle_tx": False,
        "sample_rate_hz": value.sample_rate_hz,
        "duration_ms": value.duration_ms,
        "minimum_v": round(minimum, 6),
        "maximum_v": round(maximum, 6),
        "samples": [sample.model_dump(mode="json") for sample in samples],
        "interpretation_guard": "Synthetic replay/HIL voltage faults test reader robustness only; they are not a model of a specific Shark ECU brownout response.",
    }


def communication_health(frames) -> dict:
    frames = sorted(list(frames), key=lambda frame: frame.ts_ns)
    if not frames:
        return {
            "frame_count": 0,
            "rx_frames": 0,
            "tx_frames": 0,
            "error_frames": 0,
            "error_ratio": 0.0,
            "unique_identifiers": 0,
            "buses": {},
            "quality": "no_data",
            "raw_vehicle_tx": False,
        }

    directions = Counter(frame.direction for frame in frames)
    errors = sum(1 for frame in frames if frame.error)
    identifiers = {(frame.bus, frame.arbitration_id, frame.extended, frame.can_fd) for frame in frames if not frame.error}
    bus_times: dict[str, list[int]] = defaultdict(list)
    bus_frames = Counter()
    bus_errors = Counter()
    for frame in frames:
        bus_frames[frame.bus] += 1
        if frame.error:
            bus_errors[frame.bus] += 1
        else:
            bus_times[frame.bus].append(frame.ts_ns)

    buses = {}
    for bus in sorted(bus_frames):
        times = bus_times.get(bus, [])
        gaps_ms = [(b - a) / 1_000_000 for a, b in zip(times, times[1:], strict=False) if b >= a]
        duration_s = max(0.0, (times[-1] - times[0]) / 1_000_000_000) if len(times) > 1 else 0.0
        buses[bus] = {
            "frame_count": bus_frames[bus],
            "error_frames": bus_errors[bus],
            "max_gap_ms": round(max(gaps_ms), 6) if gaps_ms else 0.0,
            "mean_gap_ms": round(sum(gaps_ms) / len(gaps_ms), 6) if gaps_ms else 0.0,
            "observed_frames_per_s": round((len(times) - 1) / duration_s, 3) if duration_s > 0 else 0.0,
        }

    error_ratio = errors / len(frames)
    max_gap = max((item["max_gap_ms"] for item in buses.values()), default=0.0)
    if error_ratio > 0.05:
        quality = "poor"
    elif error_ratio > 0.005 or max_gap > 1_000:
        quality = "degraded"
    else:
        quality = "good"

    return {
        "frame_count": len(frames),
        "rx_frames": directions.get("rx", 0),
        "tx_frames": directions.get("tx", 0),
        "unknown_direction_frames": directions.get("unknown", 0),
        "error_frames": errors,
        "error_ratio": round(error_ratio, 6),
        "unique_identifiers": len(identifiers),
        "can_fd_frames": sum(1 for frame in frames if frame.can_fd),
        "buses": buses,
        "quality": quality,
        "raw_vehicle_tx": False,
        "interpretation_guard": "Observed frame rate and gaps describe capture quality; they do not prove ECU health or bus electrical integrity without physical-layer instrumentation.",
    }


def analyze_diagnostic_observation(observation: DiagnosticObservation | dict) -> dict:
    value = observation if isinstance(observation, DiagnosticObservation) else DiagnosticObservation.model_validate(observation)
    payload = bytes.fromhex(value.response_hex) if value.response_hex else b""
    if value.timeout:
        status = "timeout"
    elif value.transport_errors:
        status = "transport_error"
    elif not payload:
        status = "empty"
    elif payload[0] == 0x7F and len(payload) >= 3:
        status = "negative_response"
    else:
        status = "response_observed"

    result = {
        "source": value.source,
        "protocol": value.protocol,
        "module": value.module,
        "status": status,
        "response_bytes": len(payload),
        "transport_errors": list(value.transport_errors),
        "read_only_analysis": True,
        "raw_vehicle_tx": False,
    }
    if status == "negative_response":
        result["negative_response"] = {
            "requested_service": payload[1],
            "nrc": payload[2],
        }
    return result


COMMUNICATION_SAFETY_PROFILE = {
    "road_vehicle_mode": {
        "voltage_fault_injection": False,
        "physical_voltage_output": False,
        "raw_can_tx": False,
        "diagnostic_write": False,
        "allowed": ["passive voltage measurement", "CAN/CAN-FD receive", "DoIP/diagnostic response capture", "recording health analysis"],
    },
    "bench_hil_mode": {
        "isolated_fixture_required": True,
        "driver_present": False,
        "propulsion_enabled": False,
        "vehicle_mobile": False,
        "allowed": ["synthetic voltage-fault replay", "isolated HIL fault-plan simulation", "parser/reader robustness testing"],
        "physical_vehicle_connected": False,
    },
}
