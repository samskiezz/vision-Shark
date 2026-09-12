from fastapi.testclient import TestClient
from vision_shark.api import create_app
from vision_shark.intent_broker import IntentBroker
from vision_shark.openclaw import OpenClawPolicy


def test_intent_broker_persists_and_enforces_terminal_state(tmp_path):
    broker=IntentBroker(tmp_path)
    item=broker.enqueue('navigation','route_home','navigation_provider',{'destination':'home'})
    assert item['status']=='queued' and item['state']=='pending'
    broker.update(item['id'],'acknowledged',{'provider':'test'})
    done=broker.update(item['id'],'completed',{'ok':True})
    assert done['state']=='completed' and done['result']=={'ok':True}
    try:broker.update(item['id'],'pending')
    except ValueError:pass
    else:raise AssertionError('terminal intent must not reopen')
    broker.close()
    reopened=IntentBroker(tmp_path)
    assert reopened.get(item['id'])['state']=='completed'
    reopened.close()


def test_openclaw_minimum_risk_is_controller_handoff():
    decision=OpenClawPolicy().authorize('request_minimum_risk',emergency=True)
    assert decision.handoff=='validated_vehicle_controller'
    assert decision.authority=='emergency'


def test_openclaw_actions_create_durable_intents(tmp_path):
    client=TestClient(create_app(tmp_path))
    nav=client.post('/api/openclaw/action',json={'action':'route_home','arguments':{},'emergency':False})
    assert nav.status_code==200 and nav.json()['status']=='queued'
    climate=client.post('/api/openclaw/action',json={'action':'climate','arguments':{'temperature_c':21},'emergency':False})
    assert climate.status_code==200 and climate.json()['status']=='queued'
    minimum=client.post('/api/openclaw/action',json={'action':'request_minimum_risk','arguments':{},'emergency':True})
    assert minimum.status_code==200 and minimum.json()['status']=='queued'
    intents=client.get('/api/intents?state=pending').json()['intents']
    providers={x['provider'] for x in intents}
    assert {'navigation_provider','vehicle_convenience_provider','validated_vehicle_controller'} <= providers


def test_emergency_evaluation_dispatches_provider_intents(tmp_path):
    client=TestClient(create_app(tmp_path))
    response=client.post('/api/openclaw/emergency/evaluate',json={'driver_responsive':False,'location_available':True})
    assert response.status_code==200
    body=response.json();assert body['state']=='emergency'
    assert body['dispatch'] and all(x['status']=='queued' for x in body['dispatch'])
    pending=client.get('/api/intents?state=pending').json()['intents']
    actions={x['action'] for x in pending}
    assert {'request_minimum_risk','share_location','route_to_hospital','call_emergency_services','notify_emergency_contact'} <= actions
