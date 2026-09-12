from __future__ import annotations
from dataclasses import dataclass,asdict
from enum import Enum
import time

class Authority(str,Enum):
    OBSERVE='observe';CONVENIENCE='convenience';NAVIGATION='navigation';EMERGENCY='emergency'

DRIVING_DOMAINS={'steering','braking','propulsion','gear','parking_brake','adas_actuation'}
CONVENIENCE_ACTIONS={'lock','unlock','horn','lights','hazards','climate','defrost','windows','charge_port','seat_comfort'}
NAVIGATION_ACTIONS={'set_destination','add_waypoint','reroute','route_to_hospital','route_home','find_safe_stop'}
EMERGENCY_ACTIONS={'call_emergency_services','notify_emergency_contact','share_location','request_safe_stop','request_minimum_risk','route_to_hospital'}

@dataclass(frozen=True)
class AgentDecision:
    action:str;authority:str;reason:str;requested_at_ns:int;requires_confirmation:bool=False;handoff:str|None=None
    def as_dict(self):return asdict(self)

class OpenClawPolicy:
    """Policy boundary between an AI agent and vehicle integrations.

    The agent may observe the vehicle, operate configured non-driving convenience
    functions, request navigation changes, and coordinate emergency response.
    Steering/braking/propulsion remain unavailable. Emergency motion requests are
    handed to a separately validated minimum-risk driving controller.
    """
    def authorize(self,action:str,domain:str='',emergency:bool=False)->AgentDecision:
        action=str(action);domain=str(domain);now=time.time_ns()
        if domain in DRIVING_DOMAINS or action in {'steer','brake','accelerate','drive','change_lane','shift_gear'}:
            if emergency:return AgentDecision('request_minimum_risk',Authority.EMERGENCY.value,'Direct driving authority is isolated from the agent',now,False,'validated_vehicle_controller')
            raise PermissionError('OpenClaw has no direct steering, braking or propulsion authority')
        if action in {'request_minimum_risk','request_safe_stop'}:
            return AgentDecision(action,Authority.EMERGENCY.value,'Motion request must be executed by an independently validated vehicle controller',now,False,'validated_vehicle_controller')
        if action in CONVENIENCE_ACTIONS:return AgentDecision(action,Authority.CONVENIENCE.value,'configured non-driving vehicle function',now)
        if action in NAVIGATION_ACTIONS:return AgentDecision(action,Authority.NAVIGATION.value,'navigation intent only; no vehicle actuation',now)
        if action in EMERGENCY_ACTIONS:return AgentDecision(action,Authority.EMERGENCY.value,'emergency coordination action',now)
        raise PermissionError('action is not allowlisted')

@dataclass(frozen=True)
class EmergencyObservation:
    driver_responsive:bool|None=None
    medical_alarm:bool=False
    crash_detected:bool=False
    severe_driver_monitoring_alarm:bool=False
    user_requested_help:bool=False
    location_available:bool=False

class EmergencyOrchestrator:
    """Deterministic emergency coordinator; it does not diagnose a heart attack."""
    def __init__(self,policy:OpenClawPolicy|None=None):self.policy=policy or OpenClawPolicy()
    def evaluate(self,obs:EmergencyObservation)->dict:
        trigger=obs.medical_alarm or obs.crash_detected or obs.severe_driver_monitoring_alarm or obs.user_requested_help or obs.driver_responsive is False
        if not trigger:return {'state':'normal','actions':[]}
        actions=[self.policy.authorize('request_minimum_risk','braking',emergency=True).as_dict()]
        if obs.location_available:
            actions.append(self.policy.authorize('share_location',emergency=True).as_dict())
            actions.append(self.policy.authorize('route_to_hospital',emergency=True).as_dict())
        actions.append(self.policy.authorize('call_emergency_services',emergency=True).as_dict())
        actions.append(self.policy.authorize('notify_emergency_contact',emergency=True).as_dict())
        return {'state':'emergency','actions':actions,'note':'Medical alarms are treated as emergency signals, not as a diagnosis.'}

class OpenClawBridge:
    """Structured tool bridge for an external OpenClaw-compatible agent.

    Providers are injected adapters. No raw CAN/DoIP/J2534 write primitive is
    exposed. Vehicle integrations must implement named high-level functions.
    """
    def __init__(self,readers=None,convenience=None,navigation=None,emergency=None):
        self.readers=dict(readers or {});self.convenience=dict(convenience or {});self.navigation=dict(navigation or {});self.emergency=dict(emergency or {});self.policy=OpenClawPolicy()
    def capabilities(self):
        return {'read':sorted(self.readers),'convenience':sorted(set(self.convenience)&CONVENIENCE_ACTIONS),'navigation':sorted(set(self.navigation)&NAVIGATION_ACTIONS),'emergency':sorted(set(self.emergency)&EMERGENCY_ACTIONS),'direct_driving':False,'driving_handoff':'validated_vehicle_controller'}
    def read(self,name):
        if name not in self.readers:raise PermissionError('reader unavailable')
        return self.readers[name]()
    def execute(self,action,arguments=None,emergency=False):
        decision=self.policy.authorize(action,emergency=emergency);args=dict(arguments or {})
        pools={Authority.CONVENIENCE.value:self.convenience,Authority.NAVIGATION.value:self.navigation,Authority.EMERGENCY.value:self.emergency}
        fn=pools.get(decision.authority,{}).get(decision.action)
        if fn is None:return {'decision':decision.as_dict(),'status':'handoff_required' if decision.handoff else 'adapter_not_configured'}
        result=fn(**args);status='executed'
        if isinstance(result,dict) and isinstance(result.get('status'),str):status=result['status']
        return {'decision':decision.as_dict(),'status':status,'result':result}
