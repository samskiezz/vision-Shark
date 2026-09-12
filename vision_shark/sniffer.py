from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from .domain import Frame


def _key(frame: Frame) -> tuple[str, int, bool, bool]:
    return frame.bus, int(frame.arbitration_id), bool(frame.extended), bool(frame.can_fd)


def sniffer_view(
    frames: Iterable[Frame], *, changed_only: bool = False, changed_within_ms: float = 1000.0
) -> dict:
    """Build a passive CAN/CAN-FD sniffer snapshot with byte-change ages.

    The function only analyzes already-observed frames. It never transmits or infers
    semantic signal meaning. Change ages are relative to