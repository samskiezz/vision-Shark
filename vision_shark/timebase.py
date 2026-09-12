from dataclasses import dataclass
import time
@dataclass
class ClockEstimate:domain:str;offset_ns:float=0.;uncertainty_ns:float=1e9;samples:int=0;last_host_ns:int=0
class TimeAuthority:
 def __init__(self):self.clocks={}
 def observe(self,domain,device_ns,host_ns=None):
  host_ns=time.monotonic_ns() if host_ns is None else int(host_ns);device_ns=int(device_ns);e=self.clocks.setdefault(domain,ClockEstimate(domain));m=host_ns-device_ns
  if e.samples:
   a=.05;e.offset_ns=(1-a)*e.offset_ns+a*m;e.uncertainty_ns=max(1.,(1-a)*e.uncertainty_ns+a*abs(m-e.offset_ns))
  else:e.offset_ns=float(m);e.uncertainty_ns=1e6
  e.samples+=1;e.last_host_ns=host_ns;return e
 def to_host(self,domain,device_ns):
  e=self.clocks[domain];return int(device_ns+e.offset_ns),e.uncertainty_ns
 def health(self,max_uncertainty_ns=5e6):return {k:{'samples':v.samples,'offset_ns':v.offset_ns,'uncertainty_ns':v.uncertainty_ns,'healthy':v.samples>=2 and v.uncertainty_ns<=max_uncertainty_ns} for k,v in self.clocks.items()}
