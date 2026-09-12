import time
from fastapi.testclient import TestClient
from vision_shark import __version__
from vision_shark.api import create_app


def test_release_version_and_readiness(tmp_path):
    assert __version__ == "0.9.0"
    c=TestClient(create_app(tmp_path))
    r=c.get('/api/production/readiness')
    assert r.status_code==200
    body=r.json()
    assert body['software_release_ready'] is True
    assert body['vehicle_communication_proven'] is False
    assert body['mode']=='production-passive-shadow'
    assert body['capabilities']['doip_read_only_diagnostics'] is True
    assert body['capabilities']['openclaw_read_orchestration'] is True
    assert body['capabilities']['raw_vehicle_tx'] is False
    assert body['capabilities']['live_actuation'] is False


def test_integrated_workflow_and_durable_recording(tmp_path):
    c=TestClient(create_app(tmp_path))
    r=c.post('/api/vision/connect',json={'simulation':True})
    assert r.status_code==200 and r.json()['source']=='simulator'
    assert c.get('/api/production/readiness').json()['vehicle_communication_proven'] is False
    time.sleep(.12)
    assert c.post('/api/vision/identify',json={'settle_s':0}).status_code==200
    assert c.post('/api/vision/learn').status_code==200
    rid=c.post('/api/recordings/start',json={'metadata':{'test':True}}).json()['recording_id']
    time.sleep(.12)
    assert c.post('/api/recordings/stop').json()['recording_id']==rid
    rows=c.get('/api/recordings').json()['recordings']
    assert rows and rows[0]['frame_count']>0
    frames=c.get(f'/api/recordings/{rid}/frames').json()['frames']
    assert frames and frames[0]['bus']=='sim0'
    assert c.post('/api/transmit').status_code==403
    c.post('/api/disconnect')


def test_ui_uses_proof_health_diagnostics_and_openclaw(tmp_path):
    c=TestClient(create_app(tmp_path))
    html=c.get('/').text
    js=c.get('/static/app.js').text
    for text in ('CONNECT VEHICLE','IDENTIFY','LEARN','COMMS PROOF','READ VIN / F190','OpenClaw'):
        assert text in html
    for endpoint in ('/api/vision/connect','/api/vision/identify','/api/vision/learn','/api/system/health','/api/diagnostics/doip/dids','/api/diagnostics/doip/dtcs','/api/openclaw/capabilities','/api/intents?state=pending'):
        assert endpoint in js
    assert 'source-select' not in html
    assert 'proof.uds_exchange' in js
    assert 'VEHICLE READY' in js
