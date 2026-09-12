from __future__ import annotations
import json,sqlite3,threading,time
from pathlib import Path
from .domain import Frame

class RecordingStore:
 def __init__(self,data_dir,commit_every:int=32,max_commit_interval_s:float=.05):
  root=Path(data_dir);root.mkdir(parents=True,exist_ok=True);self.path=root/'vision_shark.sqlite3';self._lock=threading.RLock();self._db=sqlite3.connect(self.path,check_same_thread=False);self._db.execute('PRAGMA journal_mode=WAL');self._db.execute('PRAGMA synchronous=FULL');self._db.execute('PRAGMA foreign_keys=ON');self._db.executescript('CREATE TABLE IF NOT EXISTS recordings(id INTEGER PRIMARY KEY AUTOINCREMENT,created_ns INTEGER NOT NULL,stopped_ns INTEGER,source_kind TEXT,interface TEXT,metadata_json TEXT NOT NULL);CREATE TABLE IF NOT EXISTS frames(recording_id INTEGER NOT NULL,seq INTEGER NOT NULL,frame_json TEXT NOT NULL,PRIMARY KEY(recording_id,seq),FOREIGN KEY(recording_id) REFERENCES recordings(id));');self._db.commit();self.commit_every=max(1,int(commit_every));self.max_commit_interval_s=max(.001,float(max_commit_interval_s));self._pending=0;self._last_commit=time.monotonic();self._next_seq={}
 def _flush_locked(self,force=False):
  if self._pending and (force or self._pending>=self.commit_every or time.monotonic()-self._last_commit>=self.max_commit_interval_s):
   self._db.commit();self._pending=0;self._last_commit=time.monotonic()
 def flush(self):
  with self._lock:self._flush_locked(True)
 def start_recording(self,source_kind,interface,metadata=None):
  with self._lock:
   self._flush_locked(True);meta=dict(metadata or {});meta.setdefault('storage_mode','sqlite-wal-batched');meta.setdefault('max_uncommitted_frames',self.commit_every-1);meta.setdefault('max_commit_interval_ms',round(self.max_commit_interval_s*1000,3));cur=self._db.execute('INSERT INTO recordings(created_ns,source_kind,interface,metadata_json) VALUES(?,?,?,?)',(time.time_ns(),source_kind,interface,json.dumps(meta,sort_keys=True)));self._db.commit();rid=int(cur.lastrowid);self._next_seq[rid]=0;return rid
 def append_frame(self,recording_id,frame:Frame):
  payload=frame.model_dump(mode='json')
  with self._lock:
   seq=self._next_seq.get(recording_id)
   if seq is None:
    row=self._db.execute('SELECT COALESCE(MAX(seq),-1)+1 FROM frames WHERE recording_id=?',(recording_id,)).fetchone();seq=int(row[0]);self._next_seq[recording_id]=seq
   self._db.execute('INSERT INTO frames(recording_id,seq,frame_json) VALUES(?,?,?)',(recording_id,seq,json.dumps(payload,sort_keys=True,separators=(',',':'))));self._next_seq[recording_id]=seq+1;self._pending+=1;self._flush_locked(False)
 def append_frames(self,recording_id,frames):
  rows=[]
  with self._lock:
   seq=self._next_seq.get(recording_id)
   if seq is None:
    row=self._db.execute('SELECT COALESCE(MAX(seq),-1)+1 FROM frames WHERE recording_id=?',(recording_id,)).fetchone();seq=int(row[0])
   for frame in frames:
    rows.append((recording_id,seq,json.dumps(frame.model_dump(mode='json'),sort_keys=True,separators=(',',':'))));seq+=1
   if rows:self._db.executemany('INSERT INTO frames(recording_id,seq,frame_json) VALUES(?,?,?)',rows);self._next_seq[recording_id]=seq;self._pending+=len(rows);self._flush_locked(False)
  return len(rows)
 def stop_recording(self,recording_id,final_metadata=None):
  with self._lock:
   self._flush_locked(True);row=self._db.execute('SELECT metadata_json FROM recordings WHERE id=?',(recording_id,)).fetchone();meta=json.loads(row[0]) if row else {};meta.update(final_metadata or {});self._db.execute('UPDATE recordings SET stopped_ns=?,metadata_json=? WHERE id=?',(time.time_ns(),json.dumps(meta,sort_keys=True),recording_id));self._db.commit();self._pending=0;self._last_commit=time.monotonic();self._next_seq.pop(recording_id,None)
 def list_recordings(self):
  with self._lock:self._flush_locked(True);rows=self._db.execute('SELECT r.id,r.created_ns,r.stopped_ns,r.source_kind,r.interface,r.metadata_json,COUNT(f.seq) FROM recordings r LEFT JOIN frames f ON f.recording_id=r.id GROUP BY r.id ORDER BY r.id DESC').fetchall()
  return [{'id':r[0],'created_ns':r[1],'stopped_ns':r[2],'source_kind':r[3],'interface':r[4],'metadata':json.loads(r[5]),'frame_count':r[6]} for r in rows]
 def load_frames(self,recording_id):
  with self._lock:self._flush_locked(True);rows=self._db.execute('SELECT frame_json FROM frames WHERE recording_id=? ORDER BY seq',(recording_id,)).fetchall()
  return [Frame.model_validate_json(r[0]) for r in rows]
 def close(self):
  with self._lock:self._flush_locked(True);self._db.close()
