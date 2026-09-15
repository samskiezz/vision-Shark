from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Any


@dataclass(frozen=True)
class MemoryEntry:
    timestamp_s: float
    ego_distance_m: float
    feature_digest: str
    feature: dict[str, Any]
    trigger: str


class TemporalSpatialFeatureMemory:
    """Dual time/space feature memory inspired by public video-network designs.

    A time queue preserves short-term motion context. A distance queue preserves
    road context across long stops where purely time-based history would age out.
    The memory stores compact normalized features/evidence only; it is not a
    neural feature tensor implementation.
    """

    def __init__(
        self,
        *,
        time_interval_s: float = 0.027,
        distance_interval_m: float = 1.0,
        max_time_entries: int = 96,
        max_distance_entries: int = 96,
    ):
        if time_interval_s <= 0 or distance_interval_m <= 0:
            raise ValueError("memory intervals must be positive")
        if max_time_entries < 1 or max_distance_entries < 1:
            raise ValueError("memory queue sizes must be positive")
        self.time_interval_s = float(time_interval_s)
        self.distance_interval_m = float(distance_interval_m)
        self.time_queue: deque[MemoryEntry] = deque(maxlen=int(max_time_entries))
        self.distance_queue: deque[MemoryEntry] = deque(maxlen=int(max_distance_entries))
        self._last_timestamp: float | None = None
        self._last_time_push: float | None = None
        self._last_distance_push: float | None = None
        self._last_ego_distance: float | None = None

    def reset(self) -> None:
        self.time_queue.clear()
        self.distance_queue.clear()
        self._last_timestamp = None
        self._last_time_push = None
        self._last_distance_push = None
        self._last_ego_distance = None

    @staticmethod
    def _digest(feature: dict[str, Any]) -> str:
        payload = json.dumps(feature, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(payload).hexdigest()

    def update(self, timestamp_s: float, ego_distance_m: float, feature: dict[str, Any]) -> dict[str, Any]:
        timestamp_s = float(timestamp_s)
        ego_distance_m = float(ego_distance_m)
        if not all(math.isfinite(value) for value in (timestamp_s, ego_distance_m)):
            raise ValueError("memory timestamp and ego distance must be finite")
        if self._last_timestamp is not None and timestamp_s < self._last_timestamp:
            raise ValueError("memory timestamps must be monotonic")
        if self._last_ego_distance is not None and ego_distance_m + 1e-6 < self._last_ego_distance:
            raise ValueError("ego_distance_m must be cumulative and monotonic")
        self._last_timestamp = timestamp_s
        self._last_ego_distance = ego_distance_m
        digest = self._digest(feature)
        pushed: list[str] = []

        if self._last_time_push is None or timestamp_s - self._last_time_push >= self.time_interval_s:
            self.time_queue.append(MemoryEntry(timestamp_s, ego_distance_m, digest, dict(feature), "time"))
            self._last_time_push = timestamp_s
            pushed.append("time")

        if self._last_distance_push is None or ego_distance_m - self._last_distance_push >= self.distance_interval_m:
            self.distance_queue.append(MemoryEntry(timestamp_s, ego_distance_m, digest, dict(feature), "distance"))
            self._last_distance_push = ego_distance_m
            pushed.append("distance")

        return {"pushed": pushed, **self.snapshot()}

    def context(self, *, max_entries: int = 32) -> list[dict[str, Any]]:
        max_entries = max(1, min(256, int(max_entries)))
        combined: dict[tuple[float, str], MemoryEntry] = {}
        for item in list(self.time_queue)[-max_entries:] + list(self.distance_queue)[-max_entries:]:
            combined[(item.timestamp_s, item.feature_digest)] = item
        ordered = sorted(combined.values(), key=lambda item: item.timestamp_s)[-max_entries:]
        return [asdict(item) for item in ordered]

    def snapshot(self) -> dict[str, Any]:
        time_span = 0.0
        if len(self.time_queue) >= 2:
            time_span = self.time_queue[-1].timestamp_s - self.time_queue[0].timestamp_s
        distance_span = 0.0
        if len(self.distance_queue) >= 2:
            distance_span = self.distance_queue[-1].ego_distance_m - self.distance_queue[0].ego_distance_m
        return {
            "time_interval_s": self.time_interval_s,
            "distance_interval_m": self.distance_interval_m,
            "time_queue_entries": len(self.time_queue),
            "distance_queue_entries": len(self.distance_queue),
            "time_context_span_s": time_span,
            "distance_context_span_m": distance_span,
            "context": self.context(max_entries=24),
        }
