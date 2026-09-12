from __future__ import annotations

import socket
import struct

DOIP_PORT=13400
VERSION=0x02

class DoIPError(RuntimeError):pass


def _packet(payload_type:int,payload:bytes=b'') -> bytes:
    return struct.pack('!BBHI',VERSION,VERSION^0xff,payload_type,len(payload))+payload


def _recv(sock:socket.socket,limit:int=1024*1024):
    header=b''
    while len(header)<8:
        part=sock.recv(8-len(header))
        if not part:raise DoIPError('DoIP peer closed connection')
        header+=part
    version,inverse,ptype,length=struct.unpack('!BBHI',header)
    if inverse != (version^0xff):raise DoIPError('invalid DoIP inverse version')
    if length>limit:raise DoIPError('DoIP payload exceeds safety bound')
    body=b''
    while len(body)<length:
        part=sock.recv(length-len(body))
        if not part:raise DoIPError('DoIP peer closed connection')
        body+=part
    return ptype,body

class DoIPReadOnlyClient:
    """Minimal bounded DoIP client for identification/status and allowlisted UDS reads.

    No diagnostic-session change, security access, routine control, download,
    transfer, ECU reset, IO control, DTC clear, coding or programming services
    are accepted by this class.
    """
    ALLOWED_UDS_SERVICES={0x19,0x22}
    def __init__(self,host:str,target_address:int,source_address:int=0x0e80,timeout:float=2.0):
        self.host=str(host);self.target_address=int(target_address);self.source_address=int(source_address);self.timeout=float(timeout);self.sock=None
    def connect(self):
        self.close();s=socket.create_connection((self.host,DOIP_PORT),timeout=self.timeout);s.settimeout(self.timeout);self.sock=s
        s.sendall(_packet(0x0005,struct.pack('!HB',self.source_address,0x00)))
        ptype,body=_recv(s)
        if ptype!=0x0006 or len(body)<5:raise DoIPError('routing activation response missing')
        response_code=body[4]
        if response_code not in (0x10,0x11):raise DoIPError(f'routing activation denied: 0x{response_code:02x}')
        return self
    def close(self):
        if self.sock:
            try:self.sock.close()
            finally:self.sock=None
    def read_uds(self,payload:bytes) -> bytes:
        if not payload or payload[0] not in self.ALLOWED_UDS_SERVICES:raise PermissionError('only allowlisted read-only UDS services are exposed')
        if payload[0]==0x19 and (len(payload)<2 or payload[1] not in (0x01,0x02,0x0a)):raise PermissionError('DTC request subfunction is not allowlisted')
        if payload[0]==0x22 and (len(payload)<3 or (len(payload)-1)%2):raise ValueError('ReadDataByIdentifier requires one or more 16-bit DIDs')
        if not self.sock:self.connect()
        self.sock.sendall(_packet(0x8001,struct.pack('!HH',self.source_address,self.target_address)+payload))
        while True:
            ptype,body=_recv(self.sock)
            if ptype==0x8003:raise DoIPError('diagnostic message rejected by DoIP gateway')
            if ptype!=0x8001:continue
            if len(body)<4:raise DoIPError('short diagnostic response')
            source,target=struct.unpack('!HH',body[:4])
            if target!=self.source_address:continue
            return body[4:]
    def read_dids(self,dids:list[int]):
        if not dids:raise ValueError('at least one DID is required')
        payload=b'\x22'+b''.join(struct.pack('!H',int(d)&0xffff) for d in dids)
        return self.read_uds(payload)
    def read_dtcs(self,status_mask:int=0xff):
        return self.read_uds(bytes((0x19,0x02,int(status_mask)&0xff)))
