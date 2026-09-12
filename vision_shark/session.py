from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

class WorkflowState(str, Enum):
    OFFLINE='offline'
    DISCOVERING_HARDWARE='discovering_hardware'
    INITIALISING_INTERFACE='initialising_interface'
    DISCOVERING_NETWORKS='discovering_networks'
    PASSIVE_CAPTURE='passive_capture'
    IDENTIFYING_VEHICLE='identifying_vehicle'
    INVENTORYING_ECUS='inventorying_ecus'
    MATCHING_PROFILE='matching_profile'
    READY='ready'
    LEARNING='learning'
    ANALYSING='analysing'
    VERIFYING='verifying'
    DEGRADED='degraded'
    ERROR='error'

@dataclass
class VehicleSession:
    state: WorkflowState = WorkflowState.OFFLINE
    source: str | None = None
    interface: str | None = None
    vehicle: dict[str, Any] = field(default_factory=dict)
    networks: list[dict[str, Any]] = field(default_factory=list)
    ecus: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    capabilities: dict[str, Any] = field(default_factory=lambda: {
        'observation': True,
        'diagnostics_read': False,
        'learning': True,
        'shadow_autonomy': True,
        'live_actuation': False,
        'firmware_programming': False,
    })
    progress: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def step(self, name: str, status: str='ok', **detail: Any) -> None:
        self.progress.append({'step': name, 'status': status, **detail})
        self.progress = self.progress[-100:]

    def snapshot(self) -> dict[str, Any]:
        out = asdict(self)
        out['state'] = self.state.value
        return out
