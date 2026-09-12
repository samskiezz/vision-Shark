from __future__ import annotations
import time
from dataclasses import dataclass,asdict
from threading import RLock
@dataclass
class SensorState:sensor_id:str;kind:str;clock_domain:str;last_timestamp_ns:int=0;frames:int=0;dropped:int=0;healthy:bool=False
class SensorHub:
 def __init__(self,stale_after_s=.5):self.stale_after_s=float(stale_after_s);self._s={};self._lock=RLock()
 def register(self,sensor_id,kind,clock_domain='host'):
  with self._lock:self._s[sensor_id]=SensorState(sensor_id,kind,clock_domain)
  return self._s[sensor_id]
 def observe(self,sensor_id,timestamp_ns=None,dropped=0):
  with self._lock:s=self._s[sensor_id];s.last_timestamp_ns=time.monotonic_ns() if timestamp_ns is None else int(timestamp_ns);s.frames+=1;s.dropped+=int(dropped);s.healthy=True;return s
 def health(self,now_ns=None):
  now=time.monotonic_ns() if now_ns is None else int(now_ns);out={}
  with self._lock:
   for k,s in self._s.items():
    age=None if not s.last_timestamp_ns else max(0.,(now-s.last_timestamp_ns)/1e9);out[k]={**asdict(s),'age_s':age,'healthy':bool(s.frames and age is not None and age<=self.stale_after_s),'drop_ratio':s.dropped/max(1,s.frames+s.dropped)}
  return out
