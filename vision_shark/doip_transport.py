from __future__ import annotations

import socket
import struct
import time

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


def parse_uds_response(payload:bytes,requested_service:int|None=None)->dict:
    if not payload:return {'ok':False,'kind':'empty','raw_hex':''}
    sid=payload[0]
    if sid==0x7f:
        return {'ok':False,'kind':'negative_response','request_service':payload[1] if len(payload)>1 else None,'nrc':payload[2] if len(payload)>2 else None,'raw_hex':payload.hex()}
    expected=None if requested_service is None else ((int(requested_service)+0x40)&0xff)
    return {'ok':expected is None or sid==expected,'kind':'positive_response' if expected is None or sid==expected else 'unexpected_response','service':sid,'raw_hex':payload.hex()}

class DoIPReadOnlyClient:
    """Bounded DoIP client exposing only allowlisted read-only UDS services.

    It cannot change diagnostic session, unlock security, clear DTCs, perform IO
    control, run routines, download, transfer, reset, code or program ECUs.
    """
    ALLOWED_UDS_SERVICES={0x19,0x22}
    def __init__(self,host:str,target_address:int,source_address:int=0x0e80,timeout:float=2.0):
        self.host=str(host);self.target_address=int(target_address);self.source_address=int(source_address);self.timeout=float(timeout);self.sock=None;self.routing_active=False;self.alive_checks=0
        if not 0<=self.target_address<=0xffff or not 0<=self.source_address<=0xffff:raise ValueError('DoIP logical address out of range')
        if self.timeout<=0 or self.timeout>30:raise ValueError('DoIP timeout must be >0 and <=30 seconds')
    def _answer_alive_check(self):
        if not self.sock:raise DoIPError('alive check received without active socket')
        self.sock.sendall(_packet(0x0008,struct.pack('!H',self.source_address)));self.alive_checks+=1
    def connect(self):
        self.close();s=socket.create_connection((self.host,DOIP_PORT),timeout=self.timeout);s.settimeout(self.timeout);self.sock=s
        try:
            s.sendall(_packet(0x0005,struct.pack('!HB',self.source_address,0x00)))
            while True:
                ptype,body=_recv(s)
                if ptype==0x0007:
                    self._answer_alive_check();continue
                if ptype!=0x0006 or len(body)<5:raise DoIPError('routing activation response missing')
                client_addr,entity_addr,response_code=struct.unpack('!HHB',body[:5])
                if client_addr!=self.source_address:raise DoIPError('routing activation client logical address mismatch')
                if entity_addr!=self.target_address:raise DoIPError('routing activation entity logical address mismatch')
                if response_code==0x11:raise DoIPError('routing activation requires confirmation; confirmation workflow is not implemented')
                if response_code!=0x10:raise DoIPError(f'routing activation denied: 0x{response_code:02x}')
                self.routing_active=True;return self
        except Exception:
            self.close();raise
    def close(self):
        if self.sock:
            try:self.sock.close()
            finally:self.sock=None
        self.routing_active=False
    def __enter__(self):return self.connect()
    def __exit__(self,*_):self.close()
    def read_uds(self,payload:bytes) -> bytes:
        if not payload or payload[0] not in self.ALLOWED_UDS_SERVICES:raise PermissionError('only allowlisted read-only UDS services are exposed')
        if payload[0]==0x19 and (len(payload)<2 or payload[1] not in (0x01,0x02,0x0a)):raise PermissionError('DTC request subfunction is not allowlisted')
        if payload[0]==0x22 and (len(payload)<3 or (len(payload)-1)%2):raise ValueError('ReadDataByIdentifier requires one or more 16-bit DIDs')
        if not self.sock:self.connect()
        self.sock.sendall(_packet(0x8001,struct.pack('!HH',self.source_address,self.target_address)+payload))
        while True:
            ptype,body=_recv(self.sock)
            if ptype==0x0007:
                self._answer_alive_check();continue
            if ptype==0x8003:raise DoIPError('diagnostic message rejected by DoIP gateway')
            if ptype!=0x8001:continue
            if len(body)<4:raise DoIPError('short diagnostic response')
            source,target=struct.unpack('!HH',body[:4])
            if target!=self.source_address:continue
            if source!=self.target_address:raise DoIPError('diagnostic response source logical address mismatch')
            return body[4:]
    def read_dids(self,dids:list[int]):
        if not dids:raise ValueError('at least one DID is required')
        payload=b'\x22'+b''.join(struct.pack('!H',int(d)&0xffff) for d in dids)
        return self.read_uds(payload)
    def read_dtcs(self,status_mask:int=0xff):
        return self.read_uds(bytes((0x19,0x02,int(status_mask)&0xff)))
    def prove_readonly_session(self)->dict:
        """Prove routing plus one standard identification read without guessing OEM DIDs.

        DID F190 (VIN) is used only as a standards-based probe. A positive or
        standards-compliant negative UDS response proves routed diagnostic exchange.
        """
        started=time.monotonic_ns();self.connect()
        try:
            response=self.read_dids([0xF190]);parsed=parse_uds_response(response,0x22);vin=None
            uds_exchange=parsed.get('kind') in {'positive_response','negative_response'}
            if parsed['ok'] and len(response)>=3 and response[1:3]==b'\xf1\x90':
                value=response[3:].rstrip(b'\x00\xff')
                try:vin=value.decode('ascii').strip() or None
                except UnicodeDecodeError:vin=None
            return {'routing_active':True,'uds_exchange':uds_exchange,'probe_did':'F190','response':parsed,'vin':vin,'alive_checks':self.alive_checks,'latency_ms':round((time.monotonic_ns()-started)/1e6,3)}
        finally:self.close()
