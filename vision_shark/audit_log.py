from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path


class EventAuditLog:
    """Append-only local event log with a SHA-256 hash chain.

    This is evidence/audit hardening, not a cryptographic hardware root of trust.
    """
    def __init__(self, data_dir: str | Path):
        root=Path(data_dir);root.mkdir(parents=True,exist_ok=True)
        self.path=root/'vision_audit.sqlite3';self._lock=threading.RLock()
        self._db=sqlite3.connect(self.path,check_same_thread=False)
        self._db.execute('PRAGMA journal_mode=WAL');self._db.execute('PRAGMA synchronous=FULL')
        self._db.execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,created_ns INTEGER NOT NULL,category TEXT NOT NULL,event TEXT NOT NULL,payload_json TEXT NOT NULL,prev_hash TEXT NOT NULL,event_hash TEXT NOT NULL UNIQUE)')
        self._db.commit()

    @staticmethod
    def _canonical(created_ns:int,category:str,event:str,payload:dict,prev_hash:str)->bytes:
        return json.dumps({'created_ns':int(created_ns),'category':str(category),'event':str(event),'payload':payload,'prev_hash':str(prev_hash)},sort_keys=True,separators=(',',':')).encode('utf-8')

    def append(self,category:str,event:str,payload:dict|None=None)->dict:
        created=time.time_ns();payload=dict(payload or {})
        with self._lock:
            row=self._db.execute('SELECT event_hash FROM events ORDER BY id DESC LIMIT 1').fetchone();prev=row[0] if row else '0'*64
            digest=hashlib.sha256(self._canonical(created,category,event,payload,prev)).hexdigest()
            cur=self._db.execute('INSERT INTO events(created_ns,category,event,payload_json,prev_hash,event_hash) VALUES(?,?,?,?,?,?)',(created,category,event,json.dumps(payload,sort_keys=True,separators=(',',':')),prev,digest));self._db.commit()
            return {'id':int(cur.lastrowid),'created_ns':created,'category':category,'event':event,'payload':payload,'prev_hash':prev,'event_hash':digest}

    def list(self,limit:int=100)->list[dict]:
        limit=max(1,min(1000,int(limit)))
        with self._lock:rows=self._db.execute('SELECT id,created_ns,category,event,payload_json,prev_hash,event_hash FROM events ORDER BY id DESC LIMIT ?',(limit,)).fetchall()
        return [{'id':r[0],'created_ns':r[1],'category':r[2],'event':r[3],'payload':json.loads(r[4]),'prev_hash':r[5],'event_hash':r[6]} for r in rows]

    def verify(self)->dict:
        with self._lock:rows=self._db.execute('SELECT id,created_ns,category,event,payload_json,prev_hash,event_hash FROM events ORDER BY id').fetchall()
        prev='0'*64;checked=0
        for r in rows:
            try:payload=json.loads(r[4])
            except json.JSONDecodeError:return {'ok':False,'event_id':r[0],'events_checked':checked,'reason':'invalid_payload_json'}
            expected=hashlib.sha256(self._canonical(r[1],r[2],r[3],payload,prev)).hexdigest()
            if r[5]!=prev:return {'ok':False,'event_id':r[0],'events_checked':checked,'reason':'previous_hash_mismatch'}
            if r[6]!=expected:return {'ok':False,'event_id':r[0],'events_checked':checked,'reason':'event_hash_mismatch'}
            prev=r[6];checked+=1
        return {'ok':True,'events_checked':checked,'head_hash':prev}

    def close(self):
        with self._lock:self._db.close()
