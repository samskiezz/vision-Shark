from __future__ import annotations

import ipaddress
import json
import re
import socket
import struct
import subprocess
import sys
from dataclasses import asdict, dataclass, field

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
    usable: bool = True
    metadata: dict = field(default_factory=dict)

    def as_dict(self):
        return asdict(self)


def _linux_interfaces() -> list[dict]:
    try:
        rows = json.loads(subprocess.run(
            ['ip', '-json', 'address', 'show'], capture_output=True, text=True,
            timeout=3, check=True).stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []
    out=[]
    for row in rows:
        name=row.get('ifname','')
        if name == 'lo' or row.get('operstate') not in ('UP','UNKNOWN'):
            continue
        ipv4=[]
        for info in row.get('addr_info',[]):
            if info.get('family') == 'inet' and info.get('local'):
                ipv4.append({'address':info['local'],'prefixlen':int(info.get('prefixlen',24))})
        out.append({'name':name,'ipv4':ipv4})
    return out


def _windows_interfaces() -> list[dict]:
    ps = (
        "Get-NetIPAddress -AddressFamily IPv4 | "
        "Where-Object {$_.IPAddress -ne '127.0.0.1' -and $_.AddressState -ne 'Duplicate'} | "
        "Select-Object InterfaceAlias,InterfaceIndex,IPAddress,PrefixLength | ConvertTo-Json -Compress"
    )
    try:
        raw=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',ps],capture_output=True,text=True,timeout=5,check=True).stdout.strip()
        if not raw:return []
        rows=json.loads(raw);rows=rows if isinstance(rows,list) else [rows]
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []
    grouped={}
    for row in rows:
        addr=row.get('IPAddress');name=str(row.get('InterfaceAlias') or row.get('InterfaceIndex') or 'ethernet')
        if not addr:continue
        grouped.setdefault(name,[]).append({'address':addr,'prefixlen':int(row.get('PrefixLength') or 24)})
    return [{'name':k,'ipv4':v} for k,v in grouped.items()]


def _prefix_from_hex_netmask(value: str) -> int:
    try:
        mask=int(value,16);return (mask & 0xffffffff).bit_count()
    except ValueError:
        return 24


def _mac_interfaces() -> list[dict]:
    try:raw=subprocess.run(['ifconfig'],capture_output=True,text=True,timeout=4,check=True).stdout
    except (OSError, subprocess.SubprocessError):return []
    out=[];name=None;ipv4=[]
    for line in raw.splitlines()+['END:']:
        if line and not line[0].isspace():
            if name and name!='lo0' and ipv4:out.append({'name':name,'ipv4':ipv4})
            name=line.split(':',1)[0];ipv4=[];continue
        m=re.search(r'\binet\s+(\d+\.\d+\.\d+\.\d+)\s+netmask\s+(0x[0-9a-fA-F]+)',line)
        if m and m.group(1)!='127.0.0.1':ipv4.append({'address':m.group(1),'prefixlen':_prefix_from_hex_netmask(m.group(2))})
    return out


def _fallback_interfaces() -> list[dict]:
    seen=[]
    try:
        for info in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET,socket.SOCK_DGRAM):
            addr=info[4][0]
            if addr!='127.0.0.1' and addr not in seen:seen.append(addr)
    except OSError:pass
    return [{'name':'default','ipv4':[{'address':x,'prefixlen':24} for x in seen]}] if seen else []


def network_interfaces() -> list[dict]:
    if sys.platform.startswith('linux'):out=_linux_interfaces()
    elif sys.platform.startswith('win'):out=_windows_interfaces()
    elif sys.platform=='darwin':out=_mac_interfaces()
    else:out=[]
    return out or _fallback_interfaces()


def _broadcasts(address: str, prefixlen: int) -> list[str]:
    try:
        net=ipaddress.ip_interface(f'{address}/{prefixlen}').network
        return [str(net.broadcast_address),'255.255.255.255']
    except ValueError:
        return ['255.255.255.255']


def _parse_doip_identification(packet: bytes):
    if len(packet) < 8:return None
    version,inverse,payload_type,length=struct.unpack('!BBHI',packet[:8])
    if inverse != (version ^ 0xff) or payload_type != 0x0004 or len(packet) < 8+length:return None
    payload=packet[8:8+length]
    if len(payload) < 32:return None
    vin=payload[:17].decode('ascii','replace').strip('\x00 ')
    logical=struct.unpack('!H',payload[17:19])[0]
    eid=payload[19:25].hex();gid=payload[25:31].hex();further_action=payload[31] if len(payload)>31 else None
    return {'vin':vin or None,'logical_address':logical,'eid':eid,'gid':gid,'further_action':further_action,'protocol_version':version}


def discover_doip(timeout_s: float = 0.75) -> list[AdapterCandidate]:
    """Cross-platform, bounded ISO 13400 vehicle-identification discovery over IPv4."""
    if timeout_s<=0 or timeout_s>10:raise ValueError('DoIP discovery timeout must be >0 and <=10 seconds')
    header=struct.pack('!BBHI',DOIP_VERSION,DOIP_VERSION ^ 0xff,0x0001,0)
    found=[];seen=set();interfaces=network_interfaces();probes=[]
    for iface in interfaces:
        for item in iface.get('ipv4',[]):
            addr=item['address'];prefix=int(item.get('prefixlen',24));probes.append((iface['name'],addr,_broadcasts(addr,prefix)))
    if not probes:probes=[('default',None,['255.255.255.255'])]
    for iface_name,local,targets in probes:
        sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM,socket.IPPROTO_UDP)
        try:
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1);sock.settimeout(timeout_s)
            if local:sock.bind((local,0))
            for target in dict.fromkeys(targets):
                try:sock.sendto(header,(target,DOIP_PORT))
                except OSError:continue
            while True:
                try:data,addr=sock.recvfrom(4096)
                except TimeoutError:break
                parsed=_parse_doip_identification(data)
                if not parsed:continue
                key=(addr[0],parsed['logical_address'])
                if key in seen:continue
                seen.add(key);found.append(AdapterCandidate('doip',iface_name,.98,'ISO 13400 vehicle-identification response',addr[0],parsed['logical_address'],parsed['vin'],parsed['eid'],True,{'gid':parsed['gid'],'further_action':parsed['further_action'],'protocol_version':parsed['protocol_version'],'local_address':local}))
        except OSError:pass
        finally:sock.close()
    return found


def discover_j2534_registry() -> list[AdapterCandidate]:
    """Discover installed Windows J2534 providers without loading or executing vendor DLLs."""
    if not sys.platform.startswith('win'):return []
    try:import winreg
    except ImportError:return []
    roots=[r'SOFTWARE\PassThruSupport.04.04',r'SOFTWARE\WOW6432Node\PassThruSupport.04.04',r'SOFTWARE\PassThruSupport.05.00'];out=[];seen=set()
    for path in roots:
        try:key=winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,path)
        except OSError:continue
        with key:
            idx=0
            while True:
                try:name=winreg.EnumKey(key,idx);idx+=1
                except OSError:break
                try:sub=winreg.OpenKey(key,name)
                except OSError:continue
                with sub:
                    values={}
                    for value_name in ('Name','Vendor','FunctionLibrary','ConfigApplication','ProtocolsSupported'):
                        try:values[value_name]=winreg.QueryValueEx(sub,value_name)[0]
                        except OSError:pass
                dll=str(values.get('FunctionLibrary') or '');marker=(name,dll)
                if marker in seen:continue
                seen.add(marker);out.append(AdapterCandidate('j2534',str(values.get('Name') or name),.60,'Installed SAE J2534 pass-thru provider',dll or None,usable=False,metadata={'vendor':values.get('Vendor'),'protocols':values.get('ProtocolsSupported'),'reason':'provider detected; live J2534 backend not enabled in passive production path'}))
    return out


def discover_adapters(include_doip: bool = True, include_j2534: bool = True) -> list[dict]:
    """Rank OBD transport backends without assuming J1962 means one protocol."""
    from .transports import list_can_interfaces
    out=[]
    for item in list_can_interfaces(allow_vcan=False):
        if item.get('passive_eligible') and item.get('up'):
            out.append(AdapterCandidate('socketcan',item['name'],1.0,'driver-reported passive CAN/CAN-FD interface',usable=True,metadata={'ctrlmode':item.get('ctrlmode',[])}).as_dict())
    if include_doip:out.extend(x.as_dict() for x in discover_doip())
    if include_j2534:out.extend(x.as_dict() for x in discover_j2534_registry())
    out.sort(key=lambda x:(bool(x.get('usable')),x['confidence']),reverse=True);return out
