import pytest
from vision_shark.openclaw import OpenClawPolicy,OpenClawBridge,EmergencyObservation,EmergencyOrchestrator

def test_direct_driving_is_never_agent_authority():
    p=OpenClawPolicy()
    for action,domain in [('steer','steering'),('brake','braking'),('accelerate','propulsion'),('shift_gear','gear')]:
        with pytest.raises(PermissionError):p.authorize(action,domain)

def test_emergency_driving_request_becomes_controller_handoff():
    d=OpenClawPolicy().authorize('brake','braking',emergency=True)
    assert d.action=='request_minimum_risk'
    assert d.handoff=='validated_vehicle_controller'

def test_convenience_and_navigation_are_high_level_only():
    calls=[]
    b=OpenClawBridge(convenience={'hazards':lambda:calls.append('hazards') or True},navigation={'route_home':lambda destination=None:{'destination':destination}})
    assert b.execute('hazards')['status']=='executed'
    assert b.execute('route_home',{'destination':'home'})['result']['destination']=='home'
    assert calls==['hazards']

def test_emergency_plan_requests_stop_location_hospital_and_help():
    result=EmergencyOrchestrator().evaluate(EmergencyObservation(driver_responsive=False,location_available=True))
    actions=[x['action'] for x in result['actions']]
    assert result['state']=='emergency'
    assert actions[0]=='request_minimum_risk'
    assert 'share_location' in actions and 'route_to_hospital' in actions and 'call_emergency_services' in actions

def test_no_alarm_does_nothing():
    assert EmergencyOrchestrator().evaluate(EmergencyObservation())=={'state':'normal','actions':[]}
