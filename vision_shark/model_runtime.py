from __future__ import annotations
import json,time
from dataclasses import dataclass
from pathlib import Path
@dataclass
class InferenceResult:outputs:dict;latency_ms:float;backend:str;model_id:str
class JsonRuleBackend:
 def __init__(self,path):self.spec=json.loads(Path(path).read_text())
 def infer(self,inputs):
  out={}
  for name,rule in self.spec.get('outputs',{}).items():
   if 'constant' in rule:out[name]=rule['constant'];continue
   src=inputs.get(rule.get('input'));out[name]=None if src is None else src*float(rule.get('scale',1))+float(rule.get('offset',0))
  return out
class OnnxBackend:
 def __init__(self,path,providers=None):
  try:import onnxruntime as ort
  except ImportError as e:raise RuntimeError('onnxruntime optional dependency is required for ONNX inference') from e
  self.session=ort.InferenceSession(str(path),providers=providers or ort.get_available_providers())
 def infer(self,inputs):
  names=[x.name for x in self.session.get_outputs()];return dict(zip(names,self.session.run(names,inputs)))
class ModelRuntime:
 def __init__(self,model_id,backend):self.model_id=model_id;self.backend=backend
 def infer(self,inputs):
  start=time.perf_counter_ns();outputs=self.backend.infer(inputs);return InferenceResult(outputs,(time.perf_counter_ns()-start)/1e6,type(self.backend).__name__,self.model_id)
