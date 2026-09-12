from __future__ import annotations
from dataclasses import asdict
import math,time
from .types import EgoState,ObjectTrack,WorldModel,Trajectory,TrajectoryPoint,ControlTarget

class AutonomyRuntime:
    """Executable perception-normalization -> world -> planning -> selector -> shadow-control pipeline.
    It intentionally has no vehicle transmit primitive.
    """
    def localize(self,vehicle_state,imu=None,gnss=None):
        speed=float(vehicle_state.get('speed',0) or 0);yaw=float((imu or {}).get('yaw',vehicle_state.get('yaw',0)) or 0)
        return EgoState(time.time(),float((gnss or {}).get('x',0)),float((gnss or {}).get('y',0)),yaw,speed,float(vehicle_state.get('accel',0) or 0),.2 if gnss and gnss.get('valid') else 2.)
    def perceive(self,detections):
        return [ObjectTrack(str(d.get('track_id',i)),str(d.get('class','unknown')),float(d.get('x',0)),float(d.get('y',0)),float(d.get('vx',0)),float(d.get('vy',0)),float(d.get('confidence',.5)),float(d.get('age_s',0))) for i,d in enumerate(detections or []) if float(d.get('confidence',.5))>=.2]
    def odd(self,world,health):
        reasons=[]
        if world.ego.covariance>5:reasons.append('localization_uncertain')
        if world.freshness_s>.5:reasons.append('world_model_stale')
        if not health['sensors_ok']:reasons.append('sensor_health')
        return {'inside':not reasons,'state':'inside' if not reasons else 'outside','reasons':reasons}
    def generate(self,world,target_speed,fallback=False):
        pts=[];speed=world.ego.speed;x=world.ego.x;y=world.ego.y;heading=world.ego.yaw
        for i in range(20):
            accel=-min(3.,max(.5,speed/2)) if fallback else max(-3.,min(2.,(target_speed-speed)*.8))
            speed=max(0.,speed+accel*.2);x+=math.cos(heading)*speed*.2;y+=math.sin(heading)*speed*.2
            pts.append(TrajectoryPoint((i+1)*.2,x,y,heading,speed,accel))
        return Trajectory('controlled_stop' if fallback else 'classical_lane_follow',pts,.95 if fallback else .7,{'fallback':fallback})
    def safe(self,traj,world,odd):
        if not odd['inside'] and not traj.metadata.get('fallback'):return False
        for p in traj.points:
            if p.speed<0 or p.speed>140 or p.accel>3 or p.accel<-5:return False
            if any(math.hypot(p.x-o.x,p.y-o.y)<1.5 for o in world.objects):return False
        return True
    def run(self,vehicle_state,detections=None,imu=None,gnss=None,lanes=None,controls=None,sensor_age_s=0.,model_latency_ms=0.,calibration_valid=True):
        ego=self.localize(vehicle_state,imu,gnss);objects=self.perceive(detections)
        world=WorldModel(ego,objects,list(lanes or []),list(controls or []),float(sensor_age_s))
        reasons=[]
        if sensor_age_s>.5:reasons.append('sensor_stale')
        if model_latency_ms>250:reasons.append('model_latency')
        if not calibration_valid:reasons.append('calibration')
        health={'healthy':not reasons,'sensors_ok':sensor_age_s<=.5,'reasons':reasons}
        odd=self.odd(world,health);mode='lane_follow' if odd['inside'] else 'fallback';target=max(0.,ego.speed+5.) if mode=='lane_follow' else 0.
        candidates=[self.generate(world,target,False),self.generate(world,0.,True)]
        selected=next((t for t in candidates if self.safe(t,world,odd)),candidates[-1])
        p=selected.points[min(2,len(selected.points)-1)];control=ControlTarget(p.curvature,p.accel,p.speed,selected.generator,False)
        return {'ego':asdict(ego),'objects':[asdict(o) for o in objects],'odd':odd,'health':health,'behavior':{'mode':mode,'target_speed':target},'candidates':[{'generator':t.generator,'confidence':t.confidence,'points':len(t.points)} for t in candidates],'selected':{'generator':selected.generator,'confidence':selected.confidence,'points':[asdict(p) for p in selected.points]},'control_target':asdict(control),'live_actuation':False}
