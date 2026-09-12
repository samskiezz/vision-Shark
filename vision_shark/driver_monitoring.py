from dataclasses import dataclass,asdict
@dataclass
class DriverState:available:bool;attentive:bool;eyes_open:bool;gaze_on_road:bool;hands_available:bool;confidence:float;warning_level:int;reasons:list[str]
class DriverMonitor:
 def evaluate(self,obs):
  conf=max(0.,min(1.,float(obs.get('confidence',0))));eyes=bool(obs.get('eyes_open'));gaze=bool(obs.get('gaze_on_road'));hands=bool(obs.get('hands_available'));face=bool(obs.get('face_detected'));reasons=[]
  if not face:reasons.append('driver_not_detected')
  if not eyes:reasons.append('eyes_closed')
  if not gaze:reasons.append('gaze_off_road')
  if not hands:reasons.append('hands_unavailable')
  attentive=face and eyes and gaze and conf>=.5;return asdict(DriverState(face,attentive,eyes,gaze,hands,conf,0 if attentive else (2 if face else 3),reasons))
