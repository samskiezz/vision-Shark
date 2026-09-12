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
    """Own the active receive source, durable recording and decoded live state."""

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
        self.last_error: str | None = None

    def configure_decoder(self, decoder: LiveDecoder | None) -> None:
        with self._lock:
            if self.recording_id is not None:
                raise RuntimeError("decoder configuration cannot change during a recording")
            self.decoder = decoder
            self.signals.clear()

    def connect_simulator(self, seed: int = 1) -> None:
        self._connect(SimulatorSource(seed=seed), "simulator", "simulator")

    def connect_socketcan(self, interface: str) -> None:
        self._connect(SocketCANSource(interface), "socketcan", interface)

    def _connect(self, source: Any, kind: str, interface: str) -> None:
        self.disconnect()
        source.open()
        with self._lock:
            self.source = source
            self.source_kind = kind
            self.interface = interface
            self.running = True
            self.last_error = None
            self.last_frame_monotonic = None
            self._thread = threading.Thread(target=self._loop, name="vision-shark-rx", daemon=True)
            self._thread.start()

    def start_recording(self, metadata: dict | None = None) -> int:
        with self._lock:
            if not self.running:
                raise RuntimeError("connect before recording")
            if self.storage is None:
                raise RuntimeError("durable storage is unavailable")
            if self.recording_id is not None:
                raise RuntimeError("recording already active")
            self.recording_id = self.storage.start_recording(self.source_kind, self.interface, metadata)
            return self.recording_id

    def stop_recording(self) -> int | None:
        with self._lock:
            rid = self.recording_id
            self.recording_id = None
        if rid is not None and self.storage is not None:
            self.storage.stop_recording(rid)
        return rid

    def disconnect(self) -> None:
        self.stop_recording()
        with self._lock:
            self.running = False
            source, thread = self.source, self._thread
            self.source = None
            self._thread = None
        if source is not None:
            try:
                source.close()
            except OSError as exc:
                self.last_error = f"source close failed: {exc}"
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
            except Exception as exc:
                with self._lock:
                    self.last_error = f"receive failed: {type(exc).__name__}: {exc}"
                    self.running = False
                return
            if frame is not None:
                self.ingest(frame)

    def ingest(self, frame: Frame) -> None:
        with self._lock:
            self.frames_seen += 1
            self.last_frame_monotonic = time.monotonic()
            self.recent.append(frame)
            if self.recording_id is not None and self.storage is not None:
                self.storage.append_frame(self.recording_id, frame)
            if self.decoder is not None:
                try:
                    decoded = self.decoder.decode(frame)
                    if decoded:
                        self.signals.update(decoded)
                except Exception as exc:
                    self.decode_errors += 1
                    self.last_error = f"decode failed: {type(exc).__name__}: {exc}"

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
                "last_error": self.last_error,
            }

    def recent_frames(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(f) for f in self.recent]
