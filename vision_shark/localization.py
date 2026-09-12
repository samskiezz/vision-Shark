from __future__ import annotations
from dataclasses import dataclass,asdict
import math,time

@dataclass
class PoseEstimate:
    timestamp_ns:int;x_m:float=0.;y_m:float=0.;yaw_rad:float=0.;speed_mps:float=0.;position_variance:float=100.;yaw_variance:float=10.;source:str='uninitialised'

class LocalizationFilter:
    """Small deterministic 2-D fusion core for replay/shadow use; no claim of vehicle validation."""
    def __init__(self):self.state=PoseEstimate(time.monotonic_ns())
    def predict(self,dt_s,accel_mps2=0.,yaw_rate_rps=0.,timestamp_ns=None):
        dt=max(0.,min(1.,float(dt_s)));s=self.state
        speed=max(0.,s.speed_mps+float(accel_mps2)*dt);yaw=s.yaw_rad+float(yaw_rate_rps)*dt
        self.state=PoseEstimate(time.monotonic_ns() if timestamp_ns is None else int(timestamp_ns),s.x_m+math.cos(yaw)*speed*dt,s.y_m+math.sin(yaw)*speed*dt,yaw,speed,s.position_variance+.25*dt,s.yaw_variance+.02*dt,'dead_reckoning');return self.state
    def update_gnss(self,x_m,y_m,variance,timestamp_ns=None):
        variance=max(1e-6,float(variance));s=self.state;k=s.position_variance/(s.position_variance+variance)
        self.state=PoseEstimate(time.monotonic_ns() if timestamp_ns is None else int(timestamp_ns),s.x_m+k*(float(x_m)-s.x_m),s.y_m+k*(float(y_m)-s.y_m),s.yaw_rad,s.speed_mps,(1-k)*s.position_variance,s.yaw_variance,'gnss_fused');return self.state
    def update_speed(self,speed_mps,variance=.25):
        variance=max(1e-6,float(variance));prior=max(.01,self.state.position_variance);k=prior/(prior+variance);self.state.speed_mps=max(0.,self.state.speed_mps+k*(float(speed_mps)-self.state.speed_mps));return self.state
    def snapshot(self):return asdict(self.state)
