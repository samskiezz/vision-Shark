from __future__ import annotations
from collections import OrderedDict
import threading,time
from .dbc import parse_database,decode_message

class LiveDecoder:
    def __init__(self,database,artifact_id=None,artifact_hash=None,bus='can0',freshness_ms=500):
        if len(database['messages'])>256 or database['signal_count']>1024:raise ValueError('live decoder resource limit exceeded')
        self.database=database;self.artifact_id=artifact_id;self.artifact_hash=artifact_hash;self.bus=bus;self.freshness_ms=freshness_ms
        self._index={(m['arbitration_id'],m['extended'],m['can_fd']):dict(database,messages=[m]) for m in database['messages']}
        self._values=OrderedDict();self._lock=threading.RLock();self.matched_frames=0;self.decode_errors=0;self.last_error=None
    @classmethod
    def from_text(cls,text,bus='can0',freshness_ms=500):return cls(parse_database(text),bus=bus,freshness_ms=freshness_ms)
    def provenance(self):return {'database_id':self.artifact_id,'artifact_sha256':self.artifact_hash,'dbc_sha256':self.database['source_sha256'],'bus':self.bus,'freshness_ms':self.freshness_ms,'vehicle_validated':False}
    def feed(self,frame,received_at=None):
        if frame.bus!=self.bus or frame.error or frame.rtr:return
        db=self._index.get((frame.arbitration_id,frame.extended,frame.can_fd))
        if db is None:return
        now=time.monotonic() if received_at is None else received_at
        with self._lock:
            try:values=decode_message(db,frame)
            except ValueError as exc:self.decode_errors+=1;self.last_error=str(exc)[:200];return
            self.matched_frames+=1
            message=db['messages'][0]['name']
            for key,old in self._values.items():
                if key[0]==message:old['active']=False
            for value in values:
                key=(value['message'],value['signal']);self._values[key]=dict(value,received_at=now,active=True,valid=value['finite'] and value['within_declared_range'])
                self._values.move_to_end(key)
            while len(self._values)>512:self._values.popitem(last=False)
    def decode(self,frame):
        self.feed(frame);return {v['signal']:v['value'] for v in self.snapshot(True,'live')['values'] if not v['stale']}
    def snapshot(self,running,source,now=None):
        now=time.monotonic() if now is None else now;values=[]
        with self._lock:
            for value in self._values.values():
                item={k:v for k,v in value.items() if k!='received_at'};age=(now-value['received_at'])*1000
                item['age_ms']=round(max(0,age));item['stale']=not running or age<0 or age>self.freshness_ms or not item['active'] or not item['valid'];item['quality']='synthetic_research' if source=='simulation' else 'unvalidated_research';values.append(item)
        return dict(self.provenance(),matched_frames=self.matched_frames,decode_errors=self.decode_errors,last_error=self.last_error,values=values,source=source,diagnostic_or_control_authority=False)
