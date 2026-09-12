from __future__ import annotations
from dataclasses import dataclass,asdict,field
import math,time

@dataclass
class EgoState:
    t:float;x:float=0.;y:float=0.;yaw:float=0.;speed:float=0.;accel:float=0.;covariance:float=1.
@dataclass
class ObjectTrack:
    track_id:str;cls:str;x:float;y:float;vx:float=0.;vy:float=0.;confidence:float=.5;age_s:float=0.
@dataclass
class TrajectoryPoint:
    t:float;x:float;y:float;heading:float;speed:float;accel:float=0.;jerk:float=0.;curvature:float=0.
@dataclass
class Trajectory:
    generator:str;points:list[TrajectoryPoint];confidence:float=.5;metadata:dict=field(default_factory=dict)

class AutonomyRuntime:
    """Executable perception-normalization -> world -> behavior -> trajectory -> shadow-control pipeline.

    It deliberately returns abstract shadow targets only and has no transport or vehicle-TX handle.
    """
    def _ego(self,v,imu=None,gnss=None):
        return EgoState(time.time(),float((gnss or {}).get('x',0)),float((gnss or {}).get('y',0)),float((imu or {}).get('yaw',v.get('yaw',0)) or 0),float(v.get('speed',0) or 0),float(v.get('accel',0) or 0),.2 if gnss and gnss.get('valid') else 2.)
    def _objects(self,detections):
        out=[]
        for i,d in enumerate(detections or []):
            if float(d.get('confidence',0))<.2:continue
            out.append(ObjectTrack(str(d.get('track_id',i)),str(d.get('class','unknown')),float(d.get('x',0)),float(d.get('y',0)),float(d.get('vx',0)),float(d.get('vy',0)),float(d.get('confidence',0)),float(d.get('age_s',0))))
        return out
    def _trajectory(self,ego,target_speed,fallback=False):
        pts=[];speed=ego.speed;x=ego.x;y=ego.y;dt=.2
        for i in range(20):
            accel=-min(3.,max(.5,speed/2.)) if fallback else max(-3.,min(2.,(target_speed-speed)*.8))
            speed=max(0.,speed+accel*dt);x+=math.cos(ego.yaw)*speed*dt;y+=math.sin(ego.yaw)*speed*dt
            pts.append(TrajectoryPoint((i+1)*dt,x,y,ego.yaw,speed,accel))
        return Trajectory('controlled_stop' if fallback else 'classical_lane_follow',pts,.95 if fallback else .7,{'fallback':fallback})
    def run(self,vehicle_state,detections=None,imu=None,gnss=None,lanes=None,controls=None,sensor_age_s=0.,model_latency_ms=0.,calibration_valid=True):
        ego=self._ego(vehicle_state,imu,gnss);objects=self._objects(detections);reasons=[]
        if sensor_age_s>.5:reasons.append('sensor_stale')
        if model_latency_ms>250:reasons.append('model_latency')
        if ego.covariance>5:reasons.append('localization')
        if not calibration_valid:reasons.append('calibration')
        fallback=bool(reasons);target=0. if fallback else min(100.,ego.speed+5.)
        if not fallback:
            for o in objects:
                if 0<o.x<20 and abs(o.y)<2.5:target=min(target,max(0.,ego.speed-8.))
        traj=self._trajectory(ego,target,fallback)
        p=traj.points[min(2,len(traj.points)-1)]
        predictions={o.track_id:[{'dt':d,'x':o.x+o.vx*d,'y':o.y+o.vy*d} for d in (.5,1.,1.5,2.,2.5,3.)] for o in objects}
        return {'ego':asdict(ego),'objects':[asdict(o) for o in objects],'prediction':predictions,'odd':{'inside':not fallback,'reasons':reasons},'behavior':{'mode':'fallback' if fallback else 'lane_follow','target_speed':target},'selected':{'generator':traj.generator,'confidence':traj.confidence,'points':[asdict(x) for x in traj.points]},'control_target':{'curvature':p.curvature,'acceleration':p.accel,'speed':p.speed,'live_actuation_allowed':False},'live_actuation':False}
