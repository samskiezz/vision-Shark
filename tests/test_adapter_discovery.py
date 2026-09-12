import json
import struct
from types import SimpleNamespace
import pytest
import vision_shark.adapter_discovery as discovery
from vision_shark.adapter_discovery import _parse_doip_identification,_windows_interfaces,_mac_interfaces,_broadcasts
from vision_shark.doip_transport import DoIPReadOnlyClient


def test_doip_identification_parser():
    vin=b'LGXCE6CD1P1234567';logical=0x1000;eid=bytes.fromhex('010203040506');gid=bytes.fromhex('111213141516');payload=vin+struct.pack('!H',logical)+eid+gid+b'\x00\x00';packet=struct.pack('!BBHI',2,0xfd,0x0004,len(payload))+payload
    out=_parse_doip_identification(packet)
    assert out['vin']==vin.decode() and out['logical_address']==logical and out['eid']=='010203040506'
    assert out['gid']=='111213141516'


def test_windows_interface_enumeration(monkeypatch):
    rows=[{'InterfaceAlias':'Ethernet','InterfaceIndex':3,'IPAddress':'169.254.12.4','PrefixLength':16},{'InterfaceAlias':'Wi-Fi','InterfaceIndex':7,'IPAddress':'192.168.1.2','PrefixLength':24}]
    monkeypatch.setattr(discovery.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps(rows)))
    out=_windows_interfaces()
    assert out[0]['name']=='Ethernet' and out[0]['ipv4'][0]=={'address':'169.254.12.4','prefixlen':16}


def test_mac_interface_enumeration(monkeypatch):
    text='''lo0: flags=8049<UP,LOOPBACK>\n\tinet 127.0.0.1 netmask 0xff000000\nen5: flags=8863<UP,BROADCAST>\n\tinet 169.254.33.9 netmask 0xffff0000 broadcast 169.254.255.255\n'''
    monkeypatch.setattr(discovery.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=text))
    out=_mac_interfaces()
    assert out==[{'name':'en5','ipv4':[{'address':'169.254.33.9','prefixlen':16}]}]


def test_subnet_broadcast_calculation():
    assert _broadcasts('169.254.33.9',16)[0]=='169.254.255.255'
    assert _broadcasts('192.168.55.10',24)[0]=='192.168.55.255'


def test_doip_read_only_policy_rejects_mutating_services():
    c=DoIPReadOnlyClient('127.0.0.1',0x1000)
    for service in (0x10,0x11,0x14,0x27,0x2e,0x2f,0x31,0x34,0x36,0x37,0x3d):
        with pytest.raises(PermissionError):c.read_uds(bytes((service,0)))


def test_doip_read_policy_validates_requests_before_network():
    c=DoIPReadOnlyClient('127.0.0.1',0x1000)
    with pytest.raises(ValueError):c.read_uds(b'\x22\xf1')
    with pytest.raises(PermissionError):c.read_uds(b'\x19\x04\xff')
