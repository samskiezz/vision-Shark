from __future__ import annotations
from dataclasses import dataclass,asdict
from pathlib import Path
from typing import Any
import hashlib,json,os,tempfile,time

@dataclass(frozen=True)
class VehicleFact:
    key:str; value:Any; confidence:float; source:str
    evidence_refs:tuple[str,...]=(); maturity:str='hypothesis'; first_seen:float=0.; last_verified:float=0.
    def as_dict(self):return asdict(self)

class KnowledgeGraph:
    """Small durable evidence-backed knowledge graph.

    Facts are persisted as one canonical JSON document. Atomic replace means a process
    crash cannot leave a partially-written graph. Vehicle evidence itself remains in
    recording/artifact storage; this file is the rebuildable semantic index.
    """
    def __init__(self,path: str|Path|None=None):
        self._facts:dict[str,VehicleFact]={}
        self.path=Path(path) if path else None
        if self.path:self._load()
    def _load(self):
        if not self.path or not self.path.exists():return
        raw=json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(raw,dict):raise ValueError('knowledge graph must be a JSON object')
        for key,item in raw.items():
            if not isinstance(item,dict):continue
            self._facts[key]=VehicleFact(
                key=key,value=item.get('value'),confidence=float(item.get('confidence',0.)),source=str(item.get('source','unknown')),
                evidence_refs=tuple(item.get('evidence_refs') or ()),maturity=str(item.get('maturity','hypothesis')),
                first_seen=float(item.get('first_seen',0.)),last_verified=float(item.get('last_verified',0.)))
    def _persist(self):
        if not self.path:return
        self.path.parent.mkdir(parents=True,exist_ok=True)
        payload=json.dumps(self.snapshot(),sort_keys=True,separators=(',',':'),ensure_ascii=False)
        fd,tmp=tempfile.mkstemp(prefix='.knowledge-',suffix='.tmp',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:
                f.write(payload);f.flush();os.fsync(f.fileno())
            os.replace(tmp,self.path)
        finally:
            try:os.unlink(tmp)
            except FileNotFoundError:pass
    def put(self,key,value,confidence,source,evidence_refs=(),maturity='hypothesis'):
        confidence=max(0.,min(1.,float(confidence)));now=time.time();old=self._facts.get(key)
        fact=VehicleFact(key,value,confidence,source,tuple(evidence_refs),maturity,old.first_seen if old else now,now)
        self._facts[key]=fact;self._persist();return fact
    def get(self,key):return self._facts.get(key)
    def snapshot(self):return {k:v.as_dict() for k,v in sorted(self._facts.items())}
    def digest(self):return hashlib.sha256(json.dumps(self.snapshot(),sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
