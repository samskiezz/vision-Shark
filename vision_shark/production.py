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

    Production scope is deliberately limited to local passive vehicle observation,
    evidence/recording/replay, learning and shadow autonomy. Live vehicle actuation,
    firmware programming and security bypass are outside this release boundary.
    """

    PRODUCT_SCOPE = "production-passive-shadow"

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)

    def evaluate(self) -> dict[str, Any]:
        checks = [
            GateCheck("python", sys.version_info >= (3, 11), platform.python_version()),
            GateCheck("writable_data_dir", self._writable_data_dir(), str(self.data_dir.resolve())),
            GateCheck("local_socket_support", hasattr(socket, "socket"), platform.system()),
            GateCheck("linux_socketcan_available", hasattr(socket, "AF_CAN"), "required only for physical CAN", required=False),
            GateCheck("linux_ip_tool", bool(shutil.which("ip")), "required only for physical SocketCAN", required=False),
        ]
        required_ok = all(c.ok for c in checks if c.required)
        return {
            "mode": self.PRODUCT_SCOPE,
            "software_release_ready": required_ok,
            "checks": [asdict(c) for c in checks],
            "capabilities": {
                "passive_observation": True,
                "recording": True,
                "replay": True,
                "dbc_decode": True,
                "learning": True,
                "shadow_autonomy": True,
                "raw_vehicle_tx": False,
                "live_actuation": False,
                "firmware_programming": False,
                "security_bypass": False,
            },
            "external_validation_gates": [
                "Australian BYD Shark 6 exact CAN/CAN-FD topology and signal map",
                "exact ECU/diagnostic addressing for the target vehicle build",
                "production camera/radar/lidar sensor hardware and calibration",
                "trained and independently validated perception/prediction models",
                "validated steering/braking/propulsion interfaces",
                "closed-course safety validation and applicable road approval for autonomous control",
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
