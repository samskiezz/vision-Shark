from __future__ import annotations

import platform
import shutil
import socket
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GateCheck:
    name: str
    ok: bool
    detail: str
    required: bool = True


class ProductionGate:
    """Runtime truth source for the production-safe product boundary.

    Software release readiness never implies physical vehicle compatibility.
    Vehicle communication is only considered proven after a real transport-level
    exchange is observed by the running orchestrator.
    """

    PRODUCT_SCOPE = "production-passive-shadow"

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)

    def evaluate(self, vehicle_status: dict[str, Any] | None = None) -> dict[str, Any]:
        system=platform.system()
        checks = [
            GateCheck("python", sys.version_info >= (3, 11), platform.python_version()),
            GateCheck("writable_data_dir", self._writable_data_dir(), str(self.data_dir.resolve())),
            GateCheck("local_socket_support", hasattr(socket, "socket"), system),
            GateCheck("socketcan_available", hasattr(socket, "AF_CAN"), "required only for Linux physical CAN/CAN-FD", required=False),
            GateCheck("linux_ip_tool", bool(shutil.which("ip")), "required only for Linux SocketCAN", required=False),
            GateCheck("cross_platform_doip_discovery", system in ("Windows","Darwin","Linux"), f"ISO 13400 discovery backend for {system}", required=False),
        ]
        required_ok = all(c.ok for c in checks if c.required)
        vehicle_status=vehicle_status or {}
        source=vehicle_status.get('source')
        diagnostic_proof=vehicle_status.get('diagnostic_proof') or {}
        runtime=vehicle_status.get('runtime') or {}
        if source=='doip':
            vehicle_comm_proven=bool(diagnostic_proof.get('routing_active') and diagnostic_proof.get('uds_exchange'))
            vehicle_comm_detail='DoIP routing and UDS exchange proven' if vehicle_comm_proven else 'DoIP transport not yet proven by routed UDS exchange'
        elif source=='socketcan':
            vehicle_comm_proven=bool(runtime.get('connected') and int(runtime.get('frames_seen') or 0)>0)
            vehicle_comm_detail='passive CAN/CAN-FD frames observed' if vehicle_comm_proven else 'SocketCAN connected but no vehicle frames proven yet'
        elif source=='simulator':
            vehicle_comm_proven=False;vehicle_comm_detail='simulation is not physical vehicle proof'
        else:
            vehicle_comm_proven=False;vehicle_comm_detail='no physical vehicle session'
        return {
            "mode": self.PRODUCT_SCOPE,
            "software_release_ready": required_ok,
            "vehicle_communication_proven": vehicle_comm_proven,
            "vehicle_communication_detail": vehicle_comm_detail,
            "checks": [asdict(c) for c in checks],
            "capabilities": {
                "passive_observation": True,
                "recording": True,
                "replay": True,
                "capture_import_export": True,
                "passive_isotp_reassembly": True,
                "vehicle_fingerprinting": True,
                "dbc_decode": True,
                "learning": True,
                "doip_discovery": True,
                "doip_read_only_diagnostics": True,
                "openclaw_read_orchestration": True,
                "openclaw_emergency_planning": True,
                "tamper_evident_local_audit": True,
                "shadow_autonomy": True,
                "raw_vehicle_tx": False,
                "direct_agent_driving": False,
                "live_actuation": False,
                "firmware_programming": False,
                "security_bypass": False,
            },
            "external_validation_gates": [
                "Australian BYD Shark 6 physical ENET/DoIP response and exact gateway behavior",
                "Australian BYD Shark 6 exact CAN/CAN-FD topology, bitrates, pinout and signal map",
                "exact ECU identities, firmware variants and diagnostic addressing for the target vehicle build",
                "production camera/radar/lidar sensor hardware, time synchronization and calibration",
                "trained and independently validated perception/prediction models with licensed data",
                "independent safety controller and validated steering/braking/propulsion interfaces",
                "closed-loop HIL and closed-course vehicle validation",
                "applicable Australian approval for autonomous-road operation",
            ],
        }

    def _writable_data_dir(self) -> bool:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            probe = self.data_dir / ".vision-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return True
        except OSError:
            return False
