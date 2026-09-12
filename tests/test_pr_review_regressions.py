import socket
import struct

from fastapi.testclient import TestClient

from vision_shark.api import create_app
from vision_shark.doip_transport import DoIPReadOnlyClient,_packet
from vision_shark.session import WorkflowState


class FakeSocket:
    def __init__(self,chunks):
        self.chunks=list(chunks);self.sent=[];self.closed=False
    def settimeout(self,value):self.timeout=value
    def sendall(self,data):self.sent.append(data)
    def recv(self,count):
        if not self.chunks:return b''
        chunk=self.chunks[0]
        if len(chunk)<=count:return self.chunks.pop(0)
        self.chunks[0]=chunk[count:];return chunk[:count]
    def close(self):self.closed=True


def test_doip_routing_activation_contains_reserved_bytes(monkeypatch):
    response=struct.pack('!HHBI',0x0e80,0x1000,0x10,0)
    fake=FakeSocket([_packet(0x0006,response)])
    monkeypatch.setattr(socket,'create_connection',lambda *a,**k:fake)
    client=DoIPReadOnlyClient('127.0.0.1',0x1000).connect()
    sent=fake.sent[0]
    version,inverse,payload_type,length=struct.unpack('!BBHI',sent[:8])
    assert inverse==(version^0xff)
    assert payload_type==0x0005 and length==7
    source,activation=struct.unpack('!HB',sent[8:11])
    assert source==0x0e80 and activation==0
    assert sent[11:15]==b'\x00\x00\x00\x00'
    client.close()


def test_disconnect_clears_doip_authority_and_readiness(tmp_path):
    app=create_app(tmp_path);orchestrator=app.state.orchestrator
    orchestrator.session.source='doip';orchestrator.session.interface='Ethernet';orchestrator.session.state=WorkflowState.READY
    orchestrator.session.capabilities['diagnostics_read']=True
    orchestrator.diagnostic_endpoint={'transport':'doip','interface':'Ethernet','endpoint':'169.254.1.2','logical_address':0x1000}
    orchestrator.diagnostic_proof={'routing_active':True,'uds_exchange':True}
    with TestClient(app) as client:
        before=client.get('/api/production/readiness').json()
        assert before['vehicle_communication_proven'] is True
        status=client.post('/api/disconnect').json()
        assert status['state']=='offline' and status['source'] is None
        assert status['diagnostic_endpoint'] is None and status['diagnostic_proof'] is None
        after=client.get('/api/production/readiness').json()
        assert after['vehicle_communication_proven'] is False
        assert client.post('/api/diagnostics/doip/dids',json={'dids':[0xF190]}).status_code==409
