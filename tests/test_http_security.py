from fastapi.testclient import TestClient

from vision_shark.secure_app import create_secured_app

ADMIN='admin-token-0123456789abcdef'
VIEWER='viewer-token-0123456789abcdef'


def _login(client,token):
    response=client.post('/api/auth/login',json={'token':token})
    assert response.status_code==200
    return response


def test_secure_app_requires_auth_and_sets_hardened_session_cookie(tmp_path):
    app=create_secured_app(tmp_path,ADMIN,VIEWER)
    with TestClient(app) as client:
        assert client.get('/health').status_code==200
        assert client.get('/').status_code==200
        assert client.get('/api/status').status_code==401
        assert client.post('/api/auth/login',json={'token':'wrong-token-0123456789'}).status_code==401
        login=_login(client,ADMIN)
        cookie=login.headers.get('set-cookie','').lower()
        assert 'httponly' in cookie and 'samesite=strict' in cookie and 'vision_session=' in cookie
        session=client.get('/api/auth/session')
        assert session.status_code==200 and session.json()['authenticated'] is True and session.json()['role']=='admin'
        assert client.get('/api/status').status_code==200


def test_csrf_and_idempotency_are_required_for_mutations(tmp_path):
    app=create_secured_app(tmp_path,ADMIN)
    with TestClient(app) as client:
        login=_login(client,ADMIN);csrf=login.json()['csrf_token']
        assert client.post('/api/vision/connect',json={'simulation':True}).status_code==403
        headers={'X-CSRF-Token':csrf}
        assert client.post('/api/vision/connect',json={'simulation':True},headers=headers).status_code==428
        headers['Idempotency-Key']='connect-demo-1'
        first=client.post('/api/vision/connect',json={'simulation':True},headers=headers)
        assert first.status_code==200 and first.json()['source']=='simulator'
        second=client.post('/api/vision/connect',json={'simulation':True},headers=headers)
        assert second.status_code==200 and second.json()==first.json()
        conflict=client.post('/api/vision/connect',json={'simulation':False},headers=headers)
        assert conflict.status_code==409 and 'different request' in conflict.json()['detail']
        audit=client.get('/api/audit').json()['events']
        assert any(x['category']=='security' and x['event']=='idempotent_replay' for x in audit)


def test_viewer_is_read_only_and_logout_revokes_session(tmp_path):
    app=create_secured_app(tmp_path,ADMIN,VIEWER)
    with TestClient(app) as client:
        login=_login(client,VIEWER);csrf=login.json()['csrf_token']
        assert login.json()['role']=='viewer'
        assert client.get('/api/status').status_code==200
        denied=client.post('/api/vision/connect',json={'simulation':True},headers={'X-CSRF-Token':csrf,'Idempotency-Key':'viewer-write'})
        assert denied.status_code==403 and denied.json()['detail']=='Admin role required'
        login=_login(client,ADMIN);csrf=login.json()['csrf_token']
        logout=client.post('/api/auth/logout',headers={'X-CSRF-Token':csrf})
        assert logout.status_code==200
        assert client.get('/api/status').status_code==401


def test_metrics_and_operational_data_are_protected(tmp_path):
    app=create_secured_app(tmp_path,ADMIN)
    with TestClient(app) as client:
        assert client.get('/metrics').status_code==401
        _login(client,ADMIN)
        assert client.get('/metrics').status_code==200
        assert client.get('/api/recordings').status_code==200
