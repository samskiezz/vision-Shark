from __future__ import annotations

import ipaddress
import json
import socket
import struct
import subprocess
import sys
from dataclasses import dataclass, asdict

DOIP_PORT = 13400
DOIP_VERSION = 0x02

@dataclass(frozen=True)
class AdapterCandidate:
    transport: str
    interface: str
    confidence: float
    detail: str
    endpoint: str | None = None
    logical_address: int | None = None
    vin: str | None = None
    eid: str | None = None

    def as_dict(self):
        return asdict(self)


def _network_interfaces() -> list[dict]:
    if sys.platform == 'linux':
        try:
            rows = json.loads(subprocess.run(
                ['ip','-json','address','show'], capture_output=True, text=True,
                timeout=3, check=True).stdout)
        except Exception:
            return []
        out=[]
        for row in rows:
            name=row.get('ifname','')
            if name == 'lo' or row.get('operstate') not in ('UP','UNKNOWN'):
                continue
            ipv4=[]
            for info in row.get('addr_info',[]):
                if info.get('family') == 'inet':ipv4.append(info.get('local'))
            out.append({'name':name,'ipv4':[x for x in ipv4 if x]})
        return out
    return []


def _parse_doip_identification(packet: bytes):
    if len(packet) < 8:return None
    version,inverse,payload_type,length=struct.unpack('!BBHI',packet[:8])
    if inverse != (version ^ 0xff) or payload_type != 0x0004 or len(packet) < 8+length:return None
    payload=packet[8:8+length]
    if len(payload) < 32:return None
    vin=payload[:17].decode('ascii','replace').strip('\x00 ')
    logical=struct.unpack('!H',payload[17:19])[0]
    eid=payload[19:25].hex()
    return {'vin':vin or None,'logical_address':logical,'eid':eid,'protocol_version':version}


def discover_doip(timeout_s: float = 0.75) -> list[AdapterCandidate]:
    """Read-only DoIP vehicle-identification discovery over IPv4.

    This sends only ISO 13400 vehicle-identification discovery. It does not
    perform routing activation or send UDS diagnostic requests.
    """
    header=struct.pack('!BBHI',DOIP_VERSION,DOIP_VERSION ^ 0xff,0x0001,0)
    found=[];seen=set()
    for iface in _network_interfaces():
        for local in iface['ipv4'] or [None]:
            sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM,socket.IPPROTO_UDP)
            try:
                sock.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1)
                sock.settimeout(timeout_s)
                if local:sock.bind((local,0))
                sock.sendto(header,('255.255.255.255',DOIP_PORT))
                while True:
                    try:data,addr=sock.recvfrom(4096)
                    except socket.timeout:break
                    parsed=_parse_doip_identification(data)
                    if not parsed:continue
                    key=(addr[0],parsed['logical_address'])
                    if key in seen:continue
                    seen.add(key);found.append(AdapterCandidate('doip',iface['name'],.95,'ISO 13400 vehicle identification response',addr[0],parsed['logical_address'],parsed['vin'],parsed['eid']))
            except OSError:
                pass
            finally:
                sock.close()
    return found


def discover_adapters(include_doip: bool = True) -> list[dict]:
    """Rank usable OBD transport backends without assuming the connector protocol."""
    from .transports import list_can_interfaces
    out=[]
    for item in list_can_interfaces(allow_vcan=False):
        if item.get('passive_eligible') and item.get('up'):
            out.append(AdapterCandidate('socketcan',item['name'],1.0,'driver-reported passive CAN/CAN-FD interface').as_dict())
    if include_doip:
        out.extend(x.as_dict() for x in discover_doip())
    out.sort(key=lambda x:x['confidence'],reverse=True)
    return out
