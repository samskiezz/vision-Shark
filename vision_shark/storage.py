from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterable, Iterator
from pathlib import Path

from .domain import Frame


class RecordingStore:
    def __init__(self, data_dir, commit_every: int = 32, max_commit_interval_s: float = 0.05):
        root = Path(data_dir)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "vision_shark.sqlite3"
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(
            "CREATE TABLE IF NOT EXISTS recordings("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,created_ns INTEGER NOT NULL,"
            "stopped_ns INTEGER,source_kind TEXT,interface TEXT,metadata_json TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS frames("
            "recording_id INTEGER NOT NULL,seq INTEGER NOT NULL,frame_json TEXT NOT NULL,"
            "PRIMARY KEY(recording_id,seq),FOREIGN KEY(recording_id) REFERENCES recordings(id));"
        )
        self._db.commit()
        self.commit_every = max(1, int(commit_every))
        self.max_commit_interval_s = max(0.001, float(max_commit_interval_s))
        self._pending = 0
        self._last_commit = time.monotonic()
        self._next_seq = {}

    def _flush_locked(self, force=False):
        if self._pending and (
            force
            or self._pending >= self.commit_every
            or time.monotonic() - self._last_commit >= self.max_commit_interval_s
        ):
            self._db.commit()
            self._pending = 0
            self._last_commit = time.monotonic()

    def flush(self):
        with self._lock:
            self._flush_locked(True)

    def start_recording(self, source_kind, interface, metadata=None):
        with self._lock:
            self._flush_locked(True)
            meta = dict(metadata or {})
            meta.setdefault("storage_mode", "sqlite-wal-batched")
            meta.setdefault("max_uncommitted_frames", self.commit_every - 1)
            meta.setdefault(
                "max_commit_interval_ms",
                round(self.max_commit_interval_s * 1000, 3),
            )
            cur = self._db.execute(
                "INSERT INTO recordings(created_ns,source_kind,interface,metadata_json) "
                "VALUES(?,?,?,?)",
                (time.time_ns(), source_kind, interface, json.dumps(meta, sort_keys=True)),
            )
            self._db.commit()
            rid = int(cur.lastrowid)
            self._next_seq[rid] = 0
            return rid

    def append_frame(self, recording_id, frame: Frame):
        payload = frame.model_dump(mode="json")
        with self._lock:
            seq = self._next_seq.get(recording_id)
            if seq is None:
                row = self._db.execute(
                    "SELECT COALESCE(MAX(seq),-1)+1 FROM frames WHERE recording_id=?",
                    (recording_id,),
                ).fetchone()
                seq = int(row[0])
                self._next_seq[recording_id] = seq
            self._db.execute(
                "INSERT INTO frames(recording_id,seq,frame_json) VALUES(?,?,?)",
                (
                    recording_id,
                    seq,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                ),
            )
            self._next_seq[recording_id] = seq + 1
            self._pending += 1
            self._flush_locked(False)

    def append_frames(self, recording_id, frames: Iterable[Frame]):
        rows = []
        with self._lock:
            seq = self._next_seq.get(recording_id)
            if seq is None:
                row = self._db.execute(
                    "SELECT COALESCE(MAX(seq),-1)+1 FROM frames WHERE recording_id=?",
                    (recording_id,),
                ).fetchone()
                seq = int(row[0])
            for frame in frames:
                rows.append(
                    (
                        recording_id,
                        seq,
                        json.dumps(
                            frame.model_dump(mode="json"),
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    )
                )
                seq += 1
            if rows:
                self._db.executemany(
                    "INSERT INTO frames(recording_id,seq,frame_json) VALUES(?,?,?)",
                    rows,
                )
                self._next_seq[recording_id] = seq
                self._pending += len(rows)
                self._flush_locked(False)
        return len(rows)

    def append_frames_streaming(
        self,
        recording_id: int,
        frames: Iterable[Frame],
        batch_size: int = 4096,
    ) -> int:
        """Append an arbitrarily large frame iterable in bounded batches."""
        if batch_size < 1 or batch_size > 1_000_000:
            raise ValueError("batch_size must be between 1 and 1000000")
        total = 0
        batch: list[Frame] = []
        for frame in frames:
            batch.append(frame)
            if len(batch) >= batch_size:
                total += self.append_frames(recording_id, batch)
                batch = []
        if batch:
            total += self.append_frames(recording_id, batch)
        return total

    def stop_recording(self, recording_id, final_metadata=None):
        with self._lock:
            self._flush_locked(True)
            row = self._db.execute(
                "SELECT metadata_json FROM recordings WHERE id=?",
                (recording_id,),
            ).fetchone()
            meta = json.loads(row[0]) if row else {}
            meta.update(final_metadata or {})
            self._db.execute(
                "UPDATE recordings SET stopped_ns=?,metadata_json=? WHERE id=?",
                (time.time_ns(), json.dumps(meta, sort_keys=True), recording_id),
            )
            self._db.commit()
            self._pending = 0
            self._last_commit = time.monotonic()
            self._next_seq.pop(recording_id, None)

    def list_recordings(self):
        with self._lock:
            self._flush_locked(True)
            rows = self._db.execute(
                "SELECT r.id,r.created_ns,r.stopped_ns,r.source_kind,r.interface,"
                "r.metadata_json,COUNT(f.seq) FROM recordings r "
                "LEFT JOIN frames f ON f.recording_id=r.id "
                "GROUP BY r.id ORDER BY r.id DESC"
            ).fetchall()
        return [
            {
                "id": row[0],
                "created_ns": row[1],
                "stopped_ns": row[2],
                "source_kind": row[3],
                "interface": row[4],
                "metadata": json.loads(row[5]),
                "frame_count": row[6],
            }
            for row in rows
        ]

    def load_frames(self, recording_id):
        with self._lock:
            self._flush_locked(True)
            rows = self._db.execute(
                "SELECT frame_json FROM frames WHERE recording_id=? ORDER BY seq",
                (recording_id,),
            ).fetchall()
        return [Frame.model_validate_json(row[0]) for row in rows]

    def iter_frames(self, recording_id: int, batch_size: int = 4096) -> Iterator[Frame]:
        """Stream a recording through a separate read connection in bounded batches."""
        if batch_size < 1 or batch_size > 1_000_000:
            raise ValueError("batch_size must be between 1 and 1000000")
        self.flush()
        reader = sqlite3.connect(self.path)
        try:
            cursor = reader.execute(
                "SELECT frame_json FROM frames WHERE recording_id=? ORDER BY seq",
                (recording_id,),
            )
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                for row in rows:
                    yield Frame.model_validate_json(row[0])
        finally:
            reader.close()

    def close(self):
        with self._lock:
            self._flush_locked(True)
            self._db.close()
