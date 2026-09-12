from __future__ import annotations
from dataclasses import dataclass,asdict
from typing import Any
import hashlib,json,time

@dataclass(frozen=True)
class VehicleFact:
    key:str; value:Any; confidence:float; source:str
    evidence_refs:tuple[str,...]=(); maturity:str='hypothesis'; first_seen:float=0.; last_verified:float=0.
    def as_dict(self):return asdict(self)

class KnowledgeGraph:
    def __init__(self):self._facts={}
    def put(self,key,value,confidence,source,evidence_refs=(),maturity='hypothesis'):
        confidence=max(0.,min(1.,float(confidence)));now=time.time();old=self._facts.get(key)
        fact=VehicleFact(key,value,confidence,source,tuple(evidence_refs),maturity,old.first_seen if old else now,now)
        self._facts[key]=fact;return fact
    def snapshot(self):return {k:v.as_dict() for k,v in sorted(self._facts.items())}
    def digest(self):return hashlib.sha256(json.dumps(self.snapshot(),sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
