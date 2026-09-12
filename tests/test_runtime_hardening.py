import asyncio
import struct
from fastapi.testclient import TestClient
from vision_shark.adapter_discovery import _broadcasts,_parse_doip_identification
from vision_shark.audit_log import EventAuditLog
from vision_shark.api import create_app
from vision_shark.doip_transport import DoIPError,parse_uds_response
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
