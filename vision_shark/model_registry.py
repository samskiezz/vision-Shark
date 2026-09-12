from __future__ import annotations
from pathlib import Path
import json,os,tempfile,time

class ProvenanceRegistry:
    def __init__(self,path:str|Path):self.path=Path(path);self.data={'datasets':{},'models':{}};self._load()
    def _load(self):
        if self.path.exists():
            raw=json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(raw,dict):self.data={'datasets':dict(raw.get('datasets',{})),'models':dict(raw.get('models',{}))}
    def register_dataset(self,name,artifact_sha256,license_id,split_hashes,metadata=None):
        if name in self.data['datasets']:raise ValueError('dataset version already registered')
        item={'name':name,'artifact_sha256':self._sha(artifact_sha256),'license':license_id,'split_hashes':{k:self._sha(v) for k,v in split_hashes.items()},'metadata':metadata or {},'created_ns':time.time_ns()};self.data['datasets'][name]=item;self._persist();return item
    def register_model(self,name,artifact_sha256,dataset_names,evaluation,calibration_sha256=None,metadata=None):
        if name in self.data['models']:raise ValueError('model version already registered')
        missing=[d for d in dataset_names if d not in self.data['datasets']]
        if missing:raise ValueError('unknown datasets: '+','.join(missing))
        item={'name':name,'artifact_sha256':self._sha(artifact_sha256),'datasets':list(dataset_names),'evaluation':evaluation,'calibration_sha256':None if calibration_sha256 is None else self._sha(calibration_sha256),'metadata':metadata or {},'created_ns':time.time_ns()};self.data['models'][name]=item;self._persist();return item
    def resolve_model(self,name):return self.data['models'].get(name)
    def _sha(self,value):
        value=str(value).lower()
        if len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise ValueError('expected sha256 hex')
        return value
    def _persist(self):
        self.path.parent.mkdir(parents=True,exist_ok=True);payload=json.dumps(self.data,sort_keys=True,separators=(',',':'));fd,tmp=tempfile.mkstemp(prefix='.registry-',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(payload);f.flush();os.fsync(f.fileno())
            os.replace(tmp,self.path)
        finally:
            try:os.unlink(tmp)
            except FileNotFoundError:pass
