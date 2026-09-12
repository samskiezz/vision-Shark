from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

_ALLOWED_STATES={'pending','acknowledged','completed','failed','cancelled'}

class IntentBroker:
    """Durable high-level provider handoff queue.

    An intent is not proof that a vehicle function executed. A provider must
    explicitly acknowledge/complete it. No raw CAN/DoIP/J2534 transmit primitive
    exists here.
    """
    def __init__(self,data_dir:str|Path,audit=None):
        root=Path(data_dir);root.mkdir(parents=True,exist_ok=True);self.path=root/'vision_intents.sqlite3';self.audit=audit;self._lock=threading.RLock();self._db=sqlite3.connect(self.path,check_same_thread=False)
        self._db.execute('PRAGMA journal_mode=WAL');self._db.execute('PRAGMA synchronous=FULL')
        self._db.execute('CREATE TABLE IF NOT EXISTS intents(id TEXT PRIMARY KEY,created_ns INTEGER NOT NULL,updated_ns INTEGER NOT NULL,category TEXT NOT NULL,action TEXT NOT NULL,provider TEXT NOT NULL,state TEXT NOT NULL,arguments_json TEXT NOT NULL,result_json TEXT)');self._db.commit()
    def enqueue(self,category:str,action:str,provider:str,arguments:dict|None=None)->dict:
        now=time.time_ns();intent_id=str(uuid.uuid4());args=dict(arguments or {})
        with self._lock:self._db.execute('INSERT INTO intents(id,created_ns,updated_ns,category,action,provider,state,arguments_json,result_json) VALUES(?,?,?,?,?,?,?,?,NULL)',(intent_id,now,now,category,action,provider,'pending',json.dumps(args,sort_keys=True,separators=(',',':'))));self._db.commit()
        row={'id':intent_id,'created_ns':now,'updated_ns':now,'category':category,'action':action,'provider':provider,'state':'pending','arguments':args,'result':None,'status':'queued'}
        if self.audit:self.audit.append('intent','queued',{'id':intent_id,'category':category,'action':action,'provider':provider})
        return row
    def update(self,intent_id:str,state:str,result:dict|None=None)->dict:
        if state not in _ALLOWED_STATES:raise ValueError('invalid intent state')
        now=time.time_ns();result_json=None if result is None else json.dumps(result,sort_keys=True,separators=(',',':'))
        with self._lock:
            current=self._db.execute('SELECT state FROM intents WHERE id=?',(intent_id,)).fetchone()
            if not current:raise KeyError('intent not found')
            if current[0] in {'completed','failed','cancelled'} and state!=current[0]:raise ValueError('terminal intent cannot transition')
            self._db.execute('UPDATE intents SET state=?,updated_ns=?,result_json=? WHERE id=?',(state,now,result_json,intent_id));self._db.commit()
        if self.audit:self.audit.append('intent','state_changed',{'id':intent_id,'state':state})
        return self.get(intent_id)
    def get(self,intent_id:str)->dict:
        with self._lock:r=self._db.execute('SELECT id,created_ns,updated_ns,category,action,provider,state,arguments_json,result_json FROM intents WHERE id=?',(intent_id,)).fetchone()
        if not r:raise KeyError('intent not found')
        return {'id':r[0],'created_ns':r[1],'updated_ns':r[2],'category':r[3],'action':r[4],'provider':r[5],'state':r[6],'arguments':json.loads(r[7]),'result':None if r[8] is None else json.loads(r[8])}
    def list(self,limit:int=100,state:str|None=None)->list[dict]:
        limit=max(1,min(1000,int(limit)))
        with self._lock:
            if state is None:rows=self._db.execute('SELECT id FROM intents ORDER BY created_ns DESC LIMIT ?',(limit,)).fetchall()
            else:
                if state not in _ALLOWED_STATES:raise ValueError('invalid intent state')
                rows=self._db.execute('SELECT id FROM intents WHERE state=? ORDER BY created_ns DESC LIMIT ?',(state,limit)).fetchall()
        return [self.get(r[0]) for r in rows]
    def close(self):
        with self._lock:self._db.close()
