from __future__ import annotations
from dataclasses import dataclass,field
from typing import Any
@dataclass
class EgoState:
    t:float;x:float=0.;y:float=0.;yaw:float=0.;speed:float=0.;accel:float=0.;covariance:float=1.
@dataclass
class ObjectTrack:
    track_id:str;cls:str;x:float;y:float;vx:float=0.;vy:float=0.;confidence:float=.5;age_s:float=0.
@dataclass
class WorldModel:
    ego:EgoState;objects:list[ObjectTrack]=field(default_factory=list);lanes:list[dict[str,Any]]=field(default_factory=list);controls:list[dict[str,Any]]=field(default_factory=list);freshness_s:float=0.
@dataclass
class TrajectoryPoint:
    t:float;x:float;y:float;heading:float;speed:float;accel:float=0.;jerk:float=0.;curvature:float=0.
@dataclass
class Trajectory:
    generator:str;points:list[TrajectoryPoint];confidence:float=.5;metadata:dict[str,Any]=field(default_factory=dict)
@dataclass
class ControlTarget:
    curvature:float;acceleration:float;speed:float;source:str='shadow';live_actuation_allowed:bool=False
