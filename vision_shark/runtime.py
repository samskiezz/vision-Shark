from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import asdict
from typing import Any

from .domain import Frame
from .live_decoder import LiveDecoder
from .transports import SimulatorSource, SocketCANSource


class Runtime:
    """Own the active acquisition source and decoded live state.

    Physical and simulator sources use the same frame pipeline.  The runtime does
    not silently fall back to simulation when a physical interface fails.
    """

    def __init__(self, storage: Any, max_recent: int = 2000):
        self.storage = storage
        self.max_recent = max_recent
        self.recent: deque[Frame] = deque(maxlen=max_recent)
        self.signals: dict[str, Any] = {}
        self.source: Any | None = None
        self.source_kind: str | None = None
        self.interface: str | None = None
        self.decoder: LiveDecoder | None = None
        self.recording_id: int | None = None
        self.running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self.last_frame_monotonic: float | None = None
        self.frames_seen = 0
        self.decode_errors = 0

    def configure_decoder(self, decoder: LiveDecoder | None) -> None:
        with self._lock:
            if self.recording_id is not None:
                raise RuntimeError("decoder configuration cannot change during a recording")
            self.decoder = decoder
            self.signals.clear()

    def connect_simulator(self, seed: int = 1) -> None:
        self._connect(SimulatorSource(seed=seed), "simulator", "simulator")

    def connect_socketcan(self, interface: str) -> None:
        # SocketCANSource itself enforces the driver-reported listen-only state.
        self._connect(SocketCANSource(interface), "socketcan", interface)

    def _connect(self, source: Any, kind: str, interface: str) -> None:
        self.disconnect()
        source.open()
        with self._lock:
            self.source = source
            self.source_kind = kind
            self.interface = interface
            self.running = True
            self.last_frame_monotonic = None
            self._thread = threading.Thread(target=self._loop, name="vision-shark-rx", daemon=True)
            self._thread.start()

    def disconnect(self) -> None:
        with self._lock:
            self.running = False
            source, thread = self.source, self._thread
            self.source = None
            self._thread = None
        if source is not None:
            try:
                source.close()
            except Exception:
                pass
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        with self._lock:
            self.source_kind = None
            self.interface = None
            self.signals.clear()

    def _loop(self) -> None:
        while self.running:
            source = self.source
            if source is None:
                return
            try:
                frame = source.read(timeout=0.25)
            except Exception:
                with self._lock:
                    self.running = False
                return
            if frame is not None:
                self.ingest(frame)

    def ingest(self, frame: Frame) -> None:
        with self._lock:
            self.frames_seen += 1
            self.last_frame_monotonic = time.monotonic()
            self.recent.append(frame)
            if self.recording_id is not None:
                self.storage.append_frame(self.recording_id, frame)
            if self.decoder is not None:
                try:
                    decoded = self.decoder.decode(frame)
                    if decoded:
                        self.signals.update(decoded)
                except Exception:
                    self.decode_errors += 1

    def status(self) -> dict[str, Any]:
        with self._lock:
            age = None if self.last_frame_monotonic is None else max(0.0, time.monotonic() - self.last_frame_monotonic)
            return {
                "connected": bool(self.running and self.source is not None),
                "source_kind": self.source_kind,
                "interface": self.interface,
                "frames_seen": self.frames_seen,
                "last_frame_age_s": age,
                "signals": dict(self.signals),
                "decode_errors": self.decode_errors,
                "recording_id": self.recording_id,
                "simulated": self.source_kind == "simulator",
            }

    def recent_frames(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(f) for f in self.recent]
