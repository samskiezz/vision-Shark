from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from .domain import Frame


def sniffer_view(frames: Iterable[Frame], changed_only: bool = False, changed_within_ms: float = 1000.0) -> dict:
    if changed_within_ms < 0:
        raise ValueError('changed_within_ms must be non-negative')
    rows = sorted((f for f in frames if not f.error