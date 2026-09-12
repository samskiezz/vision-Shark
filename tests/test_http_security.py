from fastapi.testclient import TestClient

from vision_shark.api import create_app

VIEWER='viewer-token-000000000000000000000000'
OPERATOR='operator-token-0000000000000000000000'
ADMIN='admin-token-0000000000000000000000000'


def _enable(monkeypatch):
    monkeypatch.setenv('VISION_SECURITY_DISABLED','0')
    monkeypatch.setenv('VISION_VIEWER_TOKEN',VIEWER)
    monkeypatch.setenv('VISION_OPERATOR_TOKEN',OPERATOR)
    monkeypatch.setenv('VISION_ADMIN_TOKEN',ADMIN)


def _login(client,token):
    response=client.post('/api/auth/session',json={'token':token})
    assert response.status_code==200
    return response.json()['csrf_token'],response


def test_security_is_required_for_api_and_metrics(monkeypatch,tmp_path):
    _enable(monkeypatch)
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/health').status_code==200
        assert client.get('/').status_code==200
        assert client.get('/api/status').status_code==401
        assert client.get('/metrics').status_code==401
        status=client.get('/api/auth/status').json()
        assert status['security_enabled'] is True and status['authenticated'] is False


def test_admin_session_requires_csrf_and_idempotency_and_replays(monkeypatch,tmp_path):
    _enable(monkeypatch)
    with TestClient(create_app(tmp_path)) as client:
        csrf,login=_login(client,ADMIN)
        cookie=login.headers.get('set-cookie','').lower()
        assert 'httponly' in cookie and 'samesite=strict' in cookie
        assert client.post('/api/vision/connect',json={'simulation':True}).status_code==403
        missing_key=client.post('/api/vision/connect',json={'simulation':True},headers={'X-CSRF-Token':csrf})
        assert missing_key.status_code==428
        headers={'X-CSRF-Token':csrf,'Idempotency-Key':'connect-simulation-0001'}
        first=client.post('/api/vision/connect',json={'simulation':True},headers=headers)
        assert first.status_code==200 and first.json()['source']=='simulator'
        replay=client.post('/api/vision/connect',json={'simulation':True},headers=headers)
        assert replay.status_code==200 and replay.json()==first.json()
        assert replay.headers.get('idempotency-replayed')=='true'
        conflict=client.post('/api/vision/connect',json={'simulation':False},headers=headers)
        assert conflict.status_code==409
        status=client.get('/api/auth/status').json()
        assert status['authenticated'] is True and status['role']=='admin' and status['csrf_token']==csrf


def test_roles_enforce_viewer_operator_and_admin_boundaries(monkeypatch,tmp_path):
    _enable(monkeypatch)
    with TestClient(create_app(tmp_path)) as viewer:
        csrf,_=_login(viewer,VIEWER)
        assert viewer.get('/api/status').status_code==200
        denied=viewer.post('/api/vision/connect',json={'simulation':True},headers={'X-CSRF-Token':csrf,'Idempotency-Key':'viewer-connect-0001'})
        assert denied.status_code==403
        policy=viewer.post('/api/agent/policy/evaluate',json={'action':'steer','domain':'steering'},headers={'X-CSRF-Token':csrf})
        assert policy.status_code==200 and policy.json()['allowed'] is False
    with TestClient(create_app(tmp_path/'operator')) as operator:
        csrf,_=_login(operator,OPERATOR)
        headers={'X-CSRF-Token':csrf,'Idempotency-Key':'operator-connect-0001'}
        assert operator.post('/api/vision/connect',json={'simulation':True},headers=headers).status_code==200
        admin_only=operator.post('/api/discovery/adapters',json={'include_doip':False,'include_j2534':False},headers={'X-CSRF-Token':csrf,'Idempotency-Key':'operator-discovery-0001'})
        assert admin_only.status_code==403


def test_bearer_auth_supports_automation_without_csrf(monkeypatch,tmp_path):
    _enable(monkeypatch)
    with TestClient(create_app(tmp_path)) as client:
        viewer_headers={'Authorization':f'Bearer {VIEWER}'}
        metrics=client.get('/metrics',headers=viewer_headers)
        assert metrics.status_code==200 and 'vision_gateway_up' in metrics.text
        assert client.post('/api/vision/connect',json={'simulation':True},headers={**viewer_headers,'Idempotency-Key':'viewer-bearer-0001'}).status_code==403
        operator_headers={'Authorization':f'Bearer {OPERATOR}','Idempotency-Key':'operator-bearer-0001'}
        connected=client.post('/api/vision/connect',json={'simulation':True},headers=operator_headers)
        assert connected.status_code==200 and connected.json()['source']=='simulator'


def test_security_mutations_are_audited_without_credentials(monkeypatch,tmp_path):
    _enable(monkeypatch)
    with TestClient(create_app(tmp_path)) as client:
        assert client.post('/api/vision/connect',json={'simulation':True}).status_code==401
        csrf,_=_login(client,ADMIN)
        headers={'X-CSRF-Token':csrf,'Idempotency-Key':'audit-connect-0001'}
        assert client.post('/api/vision/connect',json={'simulation':True},headers=headers).status_code==200
        events=client.get('/api/audit').json()['events']
        security=[e for e in events if e['category']=='security']
        assert any(e['event']=='authentication_denied' for e in security)
        assert any(e['event']=='login' for e in security)
        assert any(e['event']=='request' and e['payload'].get('path')=='/api/vision/connect' for e in security)


def test_explicit_security_disable_keeps_test_and_dev_escape_hatch(monkeypatch,tmp_path):
    monkeypatch.setenv('VISION_SECURITY_DISABLED','1')
    monkeypatch.delenv('VISION_VIEWER_TOKEN',raising=False);monkeypatch.delenv('VISION_OPERATOR_TOKEN',raising=False);monkeypatch.delenv('VISION_ADMIN_TOKEN',raising=False)
    with TestClient(create_app(tmp_path)) as client:
        status=client.get('/api/auth/status').json()
        assert status['security_enabled'] is False and status['authenticated'] is True
        assert client.post('/api/vision/connect',json={'simulation':True}).status_code==200
