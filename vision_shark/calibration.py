from __future__ import annotations
from dataclasses import dataclass,asdict
from pathlib import Path
import hashlib,json,math,os,tempfile,time

@dataclass(frozen=True)
class Calibration:
    sensor_id:str
    kind:str
    parameters:dict
    frame_from:str
    frame_to:str
    created_ns:int
    valid_from_ns:int
    valid_until_ns:int|None
    source:str
    sha256:str

class CalibrationRegistry:
    def __init__(self,path:str|Path|None=None):
        self.path=Path(path) if path else None;self._items={}
        if self.path and self.path.exists():
            raw=json.loads(self.path.read_text(encoding='utf-8'))
            for k,v in raw.items():self._items[k]=Calibration(**v)
    def _validate(self,params):
        def walk(v):
            if isinstance(v,(int,float)) and not math.isfinite(float(v)):raise ValueError('non-finite calibration value')
            if isinstance(v,dict):
                for x in v.values():walk(x)
            elif isinstance(v,(list,tuple)):
                for x in v:walk(x)
        walk(params)
    def put(self,sensor_id,kind,parameters,frame_from='sensor',frame_to='vehicle',source='measured',valid_from_ns=None,valid_until_ns=None):
        self._validate(parameters);now=time.time_ns();vf=now if valid_from_ns is None else int(valid_from_ns)
        canonical=json.dumps({'sensor_id':sensor_id,'kind':kind,'parameters':parameters,'frame_from':frame_from,'frame_to':frame_to,'valid_from_ns':vf,'valid_until_ns':valid_until_ns,'source':source},sort_keys=True,separators=(',',':')).encode()
        item=Calibration(sensor_id,kind,parameters,frame_from,frame_to,now,vf,None if valid_until_ns is None else int(valid_until_ns),source,hashlib.sha256(canonical).hexdigest())
        self._items[sensor_id]=item;self._persist();return item
    def get(self,sensor_id,at_ns=None):
        item=self._items.get(sensor_id)
        if item is None:return None
        t=time.time_ns() if at_ns is None else int(at_ns)
        if t<item.valid_from_ns or (item.valid_until_ns is not None and t>item.valid_until_ns):return None
        return item
    def snapshot(self):return {k:asdict(v) for k,v in sorted(self._items.items())}
    def _persist(self):
        if not self.path:return
        self.path.parent.mkdir(parents=True,exist_ok=True);payload=json.dumps(self.snapshot(),sort_keys=True,separators=(',',':'))
        fd,tmp=tempfile.mkstemp(prefix='.calibration-',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(payload);f.flush();os.fsync(f.fileno())
            os.replace(tmp,self.path)
        finally:
            try:os.unlink(tmp)
            except FileNotFoundError:pass
