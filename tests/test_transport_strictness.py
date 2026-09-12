import socket
import struct
import pytest
from vision_shark.doip_transport import DoIPReadOnlyClient,DoIPError,_packet
from vision_shark.domain import Frame
from vision_shark.fingerprint import fingerprint_frames,compare_fingerprints
from vision_shark.playback import ReplaySource

class FakeSocket:
    def __init__(self,chunks):self.chunks=list(chunks);self.sent=[];self.closed=False
    def settimeout(self,value):self.timeout=value
    def sendall(self,data):self.sent.append(data)
    def recv(self,count):
        if not self.chunks:return b''
        chunk=self.chunks[0]
        if len(chunk)<=count:return self.chunks.pop(0)
        self.chunks[0]=chunk[count:];return chunk[:count]
    def close(self):self.closed=True

def _wire(ptype,body):return _packet(ptype,body)

def test_routing_confirmation_required_fails_closed(monkeypatch):
    body=struct.pack('!HHBI',0x0e80,0x1000,0x11,0)
    fake=FakeSocket([_wire(0x0006,body)])
    monkeypatch.setattr(socket,'create_connection',lambda *a,**k:fake)
    with pytest.raises(DoIPError,match='requires confirmation'):
        DoIPReadOnlyClient('127.0.0.1',0x1000).connect()
    assert fake.closed

def test_routing_logical_address_mismatch_rejected(monkeypatch):
    body=struct.pack('!HHBI',0x0e80,0x1001,0x10,0)
    fake=FakeSocket([_wire(0x0006,body)])
    monkeypatch.setattr(socket,'create_connection',lambda *a,**k:fake)
    with pytest.raises(DoIPError,match='entity logical address mismatch'):
        DoIPReadOnlyClient('127.0.0.1',0x1000).connect()

def test_diagnostic_response_wrong_source_rejected():
    body=struct.pack('!HH',0x1001,0x0e80)+b'\x62\xf1\x90ABC'
    fake=FakeSocket([_wire(0x8001,body)])
    client=DoIPReadOnlyClient('127.0.0.1',0x1000);client.sock=fake;client.routing_active=True
    with pytest.raises(DoIPError,match='source logical address mismatch'):
        client.read_dids([0xF190])

def test_structural_fingerprint_stable_across_duration_and_counts():
    a=[Frame(ts_ns=1,bus='can0',arbitration_id=0x100,data='0102'),Frame(ts_ns=1001,bus='can0',arbitration_id=0x200,data='00')]
    b=[Frame(ts_ns=50,bus='can0',arbitration_id=0x100,data='ffff'),Frame(ts_ns=60,bus='can0',arbitration_id=0x100,data='0000'),Frame(ts_ns=999999,bus='can0',arbitration_id=0x200,data='aa')]
    fa=fingerprint_frames(a);fb=fingerprint_frames(b)
    assert fa['structural_sha256']==fb['structural_sha256']==fa['sha256']==fb['sha256']
    assert fa['capture_sha256']!=fb['capture_sha256']

def test_fingerprint_can_compare_changed_os_bus_name():
    a=fingerprint_frames([Frame(ts_ns=1,bus='can0',arbitration_id=0x123,data='00')])
    b=fingerprint_frames([Frame(ts_ns=2,bus='pcan0',arbitration_id=0x123,data='11')])
    assert compare_fingerprints(a,b)['score']==0
    assert compare_fingerprints(a,b,ignore_bus=True)['score']==1

def test_replay_source_is_receive_only_and_retimes_monotonically():
    frames=[Frame(ts_ns=1_000_000_000,bus='can0',arbitration_id=1,data='00'),Frame(ts_ns=1_001_000_000,bus='can0',arbitration_id=2,data='01')]
    source=ReplaySource(frames,speed=100);source.open();first=source.read(.1);second=source.read(.1)
    assert first.arbitration_id==1 and second.arbitration_id==2
    assert second.ts_ns>=first.ts_ns and source.eof
    assert not hasattr(source,'send')
