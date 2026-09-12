import time
from fastapi.testclient import TestClient
from vision_shark import __version__
from vision_shark.api import create_app


def test_release_version_and_readiness(tmp_path):
    assert __version__ == "0.8.0"
    c=TestClient(create_app(tmp_path))
    r=c.get('/api/production/readiness')
    assert r.status_code==200
    body=r.json()
    assert body['software_release_ready'] is True
    assert body['mode']=='production-passive-shadow'
    assert body['capabilities']['raw_vehicle_tx'] is False
    assert body['capabilities']['live_actuation'] is False


def test_integrated_workflow_and_durable_recording(tmp_path):
    c=TestClient(create_app(tmp_path))
    r=c.post('/api/vision/connect',json={'simulation':True})
    assert r.status_code==200 and r.json()['source']=='simulator'
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


def test_ui_uses_integrated_orchestrator(tmp_path):
    c=TestClient(create_app(tmp_path))
    html=c.get('/').text
    js=c.get('/static/app.js').text
    assert 'CONNECT VEHICLE' in html and 'IDENTIFY' in html and 'LEARN' in html
    assert '/api/vision/connect' in js and '/api/vision/identify' in js and '/api/vision/learn' in js
    assert 'source-select' not in html
