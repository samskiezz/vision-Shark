from __future__ import annotations

from .openclaw import EmergencyObservation,EmergencyOrchestrator,OpenClawPolicy


def evaluate_policy(action:str,domain:str='',emergency:bool=False)->dict:
    policy=OpenClawPolicy()
    try:decision=policy.authorize(action,domain,emergency)
    except PermissionError as exc:return {'allowed':False,'error':str(exc),'direct_driving':False}
    return {'allowed':True,'decision':decision.as_dict(),'direct_driving':False}


def evaluate_emergency(observation:dict)->dict:
    obs=EmergencyObservation(**observation);result=EmergencyOrchestrator().evaluate(obs)
    result['simulation_only']=True;result['direct_driving']=False;return result
