from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from .domain import Frame


class RecordingStore:
    """Durable local SQLite frame store with deterministic ordered replay."""

    def __init__(self, data_dir: str | Path):
        root = Path(data_dir);root.mkdir(parents=True, exist_ok=True);self.path = root / "vision_shark.sqlite3";self._lock = threading.RLock();self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL");self._db.execute("PRAGMA synchronous=FULL");self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript("""
        CREATE TABLE IF NOT EXISTS recordings(id INTEGER PRIMARY KEY AUTOINCREMENT,created_ns INTEGER NOT NULL,stopped_ns INTEGER,source_kind TEXT,interface TEXT,metadata_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS frames(recording_id INTEGER NOT NULL,seq INTEGER NOT NULL,frame_json TEXT NOT NULL,PRIMARY KEY(recording_id,seq),FOREIGN KEY(recording_id) REFERENCES recordings(id));
        """);self._db.commit()

    def start_recording(self, source_kind: str | None, interface: str | None, metadata: dict | None = None) -> int:
        with self._lock:
            cur=self._db.execute("INSERT INTO recordings(created_ns,source_kind,interface,metadata_json) VALUES(?,?,?,?)",(time.time_ns(),source_kind,interface,json.dumps(metadata or {},sort_keys=True)));self._db.commit();return int(cur.lastrowid)

    def append_frame(self, recording_id: int, frame: Frame) -> None:
        payload=frame.model_dump(mode="json")
        with self._lock:
            row=self._db.execute("SELECT COALESCE(MAX(seq),-1)+1 FROM frames WHERE recording_id=?",(recording_id,)).fetchone();seq=int(row[0]);self._db.execute("INSERT INTO frames(recording_id,seq,frame_json) VALUES(?,?,?)",(recording_id,seq,json.dumps(payload,sort_keys=True,separators=(",",":"))));self._db.commit()

    def stop_recording(self, recording_id: int) -> None:
        with self._lock:self._db.execute("UPDATE recordings SET stopped_ns=? WHERE id=?",(time.time_ns(),recording_id));self._db.commit()

    def list_recordings(self) -> list[dict]:
        with self._lock:rows=self._db.execute("SELECT r.id,r.created_ns,r.stopped_ns,r.source_kind,r.interface,r.metadata_json,COUNT(f.seq) FROM recordings r LEFT JOIN frames f ON f.recording_id=r.id GROUP BY r.id ORDER BY r.id DESC").fetchall()
        return [{"id":r[0],"created_ns":r[1],"stopped_ns":r[2],"source_kind":r[3],"interface":r[4],"metadata":json.loads(r[5]),"frame_count":r[6]} for r in rows]

    def load_frames(self, recording_id: int) -> list[Frame]:
        with self._lock:rows=self._db.execute("SELECT frame_json FROM frames WHERE recording_id=? ORDER BY seq",(recording_id,)).fetchall()
        return [Frame.model_validate_json(r[0]) for r in rows]

    def close(self) -> None:
        with self._lock:self._db.close()
