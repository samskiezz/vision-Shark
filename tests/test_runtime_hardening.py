import asyncio
import struct
from fastapi.testclient import TestClient
from vision_shark.adapter_discovery import _broadcasts,_parse_doip_identification
from vision_shark.audit_log import EventAuditLog
from vision_shark.api import create_app
from vision_shark.doip_transport import DoIPError,parse_uds_response
from vision_shark.health import build_health_report
from vision_shark.orchestrator import VisionOrchestrator
from vision_shark.runtime import Runtime
from vision_shark.storage import RecordingStore


def _doip_candidate():
    return {'transport':'doip','interface':'Ethernet','confidence':.98,'detail':'test','endpoint':'169.254.10.20','logical_address':0x1000,'vin':'LGXCE6CD1P1234567','eid':'010203040506','usable':True,'metadata':{}}


def test_subnet_and_global_broadcast_targets():
    targets=_broadcasts('169.254.10.5',16)
    assert targets[0]=='169.254.255.255'
    assert '255.255.255.255' in targets


def test_doip_identification_and_uds_response_parsing():
    vin=b'LGXCE6CD1P1234567';payload=vin+struct.pack('!H',0x1000)+bytes.fromhex('010203040506111213141516')+b'\x00\x00'
    packet=struct.pack('!BBHI',2,0xfd,0x0004,len(payload))+payload
    out=_parse_doip_identification(packet)
    assert out['vin']==vin.decode() and out['logical_address']==0x1000
    assert parse_uds_response(b'\x62\xf1\x90ABC',0x22)['ok'] is True
    negative=parse_uds_response(b'\x7f\x22\x31',0x22)
    assert negative['ok'] is False and negative['nrc']==0x31


def test_audit_log_hash_chain(tmp_path):
    audit=EventAuditLog(tmp_path)
    first=audit.append('test','one',{'value':1});second=audit.append('test','two',{'value':2})
    assert second['prev_hash']==first['event_hash']
    assert audit.verify()['ok'] is True
    assert len(audit.list())==2
    audit.close()


def test_doip_connect_requires_routed_proof(monkeypatch,tmp_path):
    import vision_shark.orchestrator as module
    store=RecordingStore(tmp_path);runtime=Runtime(store);orch=VisionOrchestrator(runtime)
    monkeypatch.setattr(module,'discover_adapters',lambda *args,**kwargs:[_doip_candidate()])
    class FailingClient:
        def __init__(self,*args,**kwargs):pass
        def prove_readonly_session(self):raise DoIPError('routing activation denied')
    monkeypatch.setattr(module,'DoIPReadOnlyClient',FailingClient)
    result=asyncio.run(orch.connect_auto(False))
    assert result['state']=='error'
    assert result['capabilities']['diagnostics_read'] is False
    assert orch.diagnostic_proof['uds_exchange'] is False
    store.close()


def test_doip_connect_sets_diagnostics_only_after_proof(monkeypatch,tmp_path):
    import vision_shark.orchestrator as module
    store=RecordingStore(tmp_path);runtime=Runtime(store);orch=VisionOrchestrator(runtime)
    monkeypatch.setattr(module,'discover_adapters',lambda *args,**kwargs:[_doip_candidate()])
    class ProvenClient:
        def __init__(self,*args,**kwargs):pass
        def prove_readonly_session(self):return {'routing_active':True,'uds_exchange':True,'probe_did':'F190','response':{'ok':True},'vin':'LGXCE6CD1P1234567','latency_ms':1.2}
    monkeypatch.setattr(module,'DoIPReadOnlyClient',ProvenClient)
    result=asyncio.run(orch.connect_auto(False))
    assert result['state']=='ready'
    assert result['capabilities']['diagnostics_read'] is True
    assert result['vehicle']['status']=='doip_diagnostics_proven'
    store.close()


def test_disconnect_revokes_doip_diagnostic_authority(tmp_path):
    app=create_app(tmp_path);orch=app.state.orchestrator
    orch.session.source='doip';orch.session.capabilities['diagnostics_read']=True
    orch.diagnostic_endpoint=_doip_candidate();orch.diagnostic_proof={'routing_active':True,'uds_exchange':True}
    c=TestClient(app)
    disconnected=c.post('/api/disconnect')
    assert disconnected.status_code==200
    state=disconnected.json()
    assert state['source'] is None and state['diagnostic_endpoint'] is None and state['diagnostic_proof'] is None
    assert state['capabilities']['diagnostics_read'] is False
    assert c.post('/api/diagnostics/doip/dids',json={'dids':[0xF190]}).status_code==409


def test_health_requires_observed_socketcan_frames():
    class RuntimeStub:
        def __init__(self,frames):self.frames=frames
        def status(self):return {'connected':True,'source_kind':'socketcan','frames_seen':self.frames,'last_frame_age_s':0.1,'receive_drops':0,'decode_errors':0}
    class OrchestratorStub:
        def status(self):return {'state':'ready','source':'socketcan','knowledge_facts':0,'capabilities':{}}
    assert build_health_report(RuntimeStub(0),OrchestratorStub())['vehicle_ready'] is False
    ready=build_health_report(RuntimeStub(1),OrchestratorStub())
    assert ready['vehicle_ready'] is True and ready['vehicle_transport_proven'] is True


def test_health_requires_routed_doip_proof():
    class RuntimeStub:
        def status(self):return {'connected':False,'source_kind':None}
    class OrchestratorStub:
        def __init__(self,proof):self.proof=proof
        def status(self):return {'state':'ready','source':'doip','diagnostic_proof':self.proof,'knowledge_facts':0,'capabilities':{'diagnostics_read':bool(self.proof.get('uds_exchange'))}}
    assert build_health_report(RuntimeStub(),OrchestratorStub({'routing_active':True,'uds_exchange':False}))['vehicle_ready'] is False
    assert build_health_report(RuntimeStub(),OrchestratorStub({'routing_active':True,'uds_exchange':True}))['vehicle_ready'] is True


def test_live_openclaw_and_audit_api(tmp_path):
    c=TestClient(create_app(tmp_path))
    caps=c.get('/api/openclaw/capabilities')
    assert caps.status_code==200 and caps.json()['direct_driving'] is False
    assert c.post('/api/openclaw/read',json={'name':'vision_status'}).status_code==200
    assert c.post('/api/openclaw/action',json={'action':'steer','arguments':{},'emergency':False}).status_code==403
    emergency=c.post('/api/openclaw/emergency/evaluate',json={'driver_responsive':False,'location_available':True})
    assert emergency.status_code==200 and emergency.json()['state']=='emergency'
    verify=c.get('/api/audit/verify')
    assert verify.status_code==200 and verify.json()['ok'] is True
