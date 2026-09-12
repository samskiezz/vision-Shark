from vision_shark.knowledge import KnowledgeGraph
from vision_shark.api import create_app
from fastapi.testclient import TestClient


def test_knowledge_graph_survives_restart(tmp_path):
    path=tmp_path/'knowledge.json'
    a=KnowledgeGraph(path);a.put('vehicle.identity',{'vin':'evidence-redacted'},.9,'sealed-session',['sha256:abc'],'validated')
    digest=a.digest()
    b=KnowledgeGraph(path)
    assert b.digest()==digest
    assert b.get('vehicle.identity').maturity=='validated'
    assert b.get('vehicle.identity').evidence_refs==('sha256:abc',)


def test_repository_fetch_routes_are_explicitly_retired(tmp_path):
    c=TestClient(create_app(tmp_path))
    assert c.get('/api/import/repository').status_code==410
    assert c.post('/api/repositories/fetch').status_code==410


def test_orchestrator_rebuilds_persisted_knowledge(tmp_path):
    c=TestClient(create_app(tmp_path))
    assert c.post('/api/vision/connect',json={'simulation':True}).status_code==200
    assert c.post('/api/vision/identify',json={'settle_s':0}).status_code==200
    first=c.get('/api/vision/status').json()
    assert first['knowledge_facts']>=1
    c.post('/api/disconnect')
    c2=TestClient(create_app(tmp_path))
    second=c2.get('/api/vision/status').json()
    assert second['knowledge_facts']>=1
    assert second['knowledge_digest']==first['knowledge_digest']
