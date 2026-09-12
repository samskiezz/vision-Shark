from __future__ import annotations
import time
from dataclasses import dataclass,asdict
from threading import RLock
from typing import Any
@dataclass(frozen=True)
class SignalValue:path:str;value:Any;timestamp_ns:int;quality:str='valid';source:str='unknown';confidence:float=1.;unit:str|None=None
class SemanticSignalBroker:
 def __init__(self):self._values={};self._lock=RLock()
 def publish(self,path,value,*,timestamp_ns=None,quality='valid',source='unknown',confidence=1.,unit=None):
  if not path or path.startswith('.') or '..' in path:raise ValueError('invalid signal path')
  s=SignalValue(path,value,time.monotonic_ns() if timestamp_ns is None else int(timestamp_ns),quality,source,max(0.,min(1.,float(confidence))),unit)
  with self._lock:self._values[path]=s
  return s
 def get(self,path,max_age_s=None):
  with self._lock:s=self._values.get(path)
  if s and max_age_s is not None and (time.monotonic_ns()-s.timestamp_ns)/1e9>max_age_s:return None
  return s
 def snapshot(self,prefix=''):
  with self._lock:return {k:asdict(v) for k,v in self._values.items() if k.startswith(prefix)}
