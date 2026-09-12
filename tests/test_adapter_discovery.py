import struct
import pytest
from vision_shark.adapter_discovery import _parse_doip_identification
from vision_shark.doip_transport import DoIPReadOnlyClient


def test_doip_identification_parser():
    vin=b'LGXCE6CD1P1234567';logical=0x1000;eid=bytes.fromhex('010203040506');gid=bytes.fromhex('111213141516');payload=vin+struct.pack('!H',logical)+eid+gid+b'\x00\x00';packet=struct.pack('!BBHI',2,0xfd,0x0004,len(payload))+payload
    out=_parse_doip_identification(packet)
    assert out['vin']==vin.decode() and out['logical_address']==logical and out['eid']=='010203040506'


def test_doip_read_only_policy_rejects_mutating_services():
    c=DoIPReadOnlyClient('127.0.0.1',0x1000)
    for service in (0x10,0x11,0x14,0x27,0x2e,0x2f,0x31,0x34,0x36,0x37,0x3d):
        with pytest.raises(PermissionError):c.read_uds(bytes((service,0)))


def test_doip_read_policy_validates_requests_before_network():
    c=DoIPReadOnlyClient('127.0.0.1',0x1000)
    with pytest.raises(ValueError):c.read_uds(b'\x22\xf1')
    with pytest.raises(PermissionError):c.read_uds(b'\x19\x04\xff')
