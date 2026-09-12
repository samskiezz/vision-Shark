import sqlite3
from fastapi.testclient import TestClient
from vision_shark.api import create_app


def test_app_lifespan_closes_persistent_stores(tmp_path):
    app=create_app(tmp_path)
    store=app.state.store;audit=app.state.audit;intents=app.state.intents
    with TestClient(app) as client:
        assert client.get('/health').status_code==200
        assert client.post('/api/vision/connect',json={'simulation':True}).status_code==200
    for db in (store._db,audit._db,intents._db):
        try:db.execute('SELECT 1')
        except sqlite3.ProgrammingError:pass
        else:raise AssertionError('SQLite store was not closed on application shutdown')


def test_isotp_api_supports_explicit_extended_addressing(tmp_path):
    client=TestClient(create_app(tmp_path))
    capture='(1.000000000) can0 700#F1100962F1903132\n(1.010000000) can0 700#F1213334353637\n'
    imported=client.post('/api/interchange/import',json={'format':'candump','content':capture,'metadata':{}})
    assert imported.status_code==200
    rid=imported.json()['recording_id']
    result=client.get(f'/api/recordings/{rid}/isotp?addressing=extended&address_extension=241')
    assert result.status_code==200
    body=result.json();assert body['addressing']=='extended' and body['address_extension']==241
    assert body['messages'][0]['payload_hex']=='62f190313233343536'
    assert body['messages'][0]['complete'] is True
    bad=client.get(f'/api/recordings/{rid}/isotp?addressing=auto')
    assert bad.status_code==400
