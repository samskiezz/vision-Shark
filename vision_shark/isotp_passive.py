from __future__ import annotations

from dataclasses import dataclass,asdict
from .domain import Frame

@dataclass(frozen=True)
class IsoTpMessage:
    ts_ns:int
    bus:str
    arbitration_id:int
    payload_hex:str
    frame_count:int
    complete:bool=True
    reason:str='complete'
    addressing:str='normal'
    address_extension:int|None=None
    def as_dict(self):return asdict(self)

class PassiveIsoTpAssembler:
    """Receive-only ISO 15765-2 reassembler for normal or extended addressing.

    Extended addressing is explicit: the first payload octet is treated as the
    address extension and the PCI starts at byte 1. No flow-control frame or
    other vehicle transmit primitive exists in this assembler.
    """
    def __init__(self,max_payload:int=1024*1024,max_gap_ns:int=2_000_000_000,addressing:str='normal',address_extension:int|None=None):
        addressing=str(addressing).lower()
        if addressing not in {'normal','extended'}:raise ValueError('addressing must be normal or extended')
        if address_extension is not None and not 0<=int(address_extension)<=0xff:raise ValueError('address extension out of range')
        if addressing=='normal' and address_extension is not None:raise ValueError('address_extension requires extended addressing')
        self.max_payload=max(1,int(max_payload));self.max_gap_ns=max(1,int(max_gap_ns));self.addressing=addressing;self.address_extension=None if address_extension is None else int(address_extension);self._streams={}
    def _key(self,frame:Frame,ae:int|None):return (frame.bus,int(frame.arbitration_id),bool(frame.extended),bool(frame.can_fd),ae)
    def _split(self,raw:bytes):
        if self.addressing=='normal':return None,raw
        if len(raw)<2:return None,b''
        ae=raw[0]
        if self.address_extension is not None and ae!=self.address_extension:return ae,b''
        return ae,raw[1:]
    def _message(self,ts_ns,bus,arb_id,payload_hex,frames,complete=True,reason='complete',ae=None):
        return IsoTpMessage(ts_ns,bus,arb_id,payload_hex,frames,complete,reason,self.addressing,ae)
    def consume(self,frame:Frame)->list[IsoTpMessage]:
        if frame.error or frame.rtr:return []
        raw=bytes.fromhex(frame.data)
        if not raw:return []
        out=self.expire(frame.ts_ns);ae,pdu=self._split(raw)
        if self.addressing=='extended' and (not pdu or (self.address_extension is not None and ae!=self.address_extension)):return out
        if not pdu:return out
        kind=pdu[0]>>4;key=self._key(frame,ae)
        if kind==0:
            length=pdu[0]&0x0f;start=1
            if length==0:
                if len(pdu)<2:return out
                length=pdu[1];start=2
            if length>len(pdu)-start:return out+[self._message(frame.ts_ns,frame.bus,frame.arbitration_id,pdu[start:].hex(),1,False,'short_single_frame',ae)]
            return out+[self._message(frame.ts_ns,frame.bus,frame.arbitration_id,pdu[start:start+length].hex(),1,ae=ae)]
        if kind==1:
            if len(pdu)<2:return out
            total=((pdu[0]&0x0f)<<8)|pdu[1];start=2
            if total==0:
                if len(pdu)<6:return out
                total=int.from_bytes(pdu[2:6],'big');start=6
            if total<=0 or total>self.max_payload:return out+[self._message(frame.ts_ns,frame.bus,frame.arbitration_id,'',1,False,'payload_length_out_of_bounds',ae)]
            payload=bytearray(pdu[start:]);self._streams[key]={'total':total,'payload':payload,'next_seq':1,'frames':1,'last':frame.ts_ns,'bus':frame.bus,'id':frame.arbitration_id,'ae':ae}
            if len(payload)>=total:
                state=self._streams.pop(key);return out+[self._message(frame.ts_ns,frame.bus,frame.arbitration_id,bytes(state['payload'][:total]).hex(),1,ae=ae)]
            return out
        if kind==2:
            state=self._streams.get(key)
            if state is None:return out
            seq=pdu[0]&0x0f
            if seq!=state['next_seq']:
                self._streams.pop(key,None);return out+[self._message(frame.ts_ns,frame.bus,frame.arbitration_id,bytes(state['payload']).hex(),state['frames'],False,'sequence_mismatch',ae)]
            state['payload'].extend(pdu[1:]);state['frames']+=1;state['last']=frame.ts_ns;state['next_seq']=(seq+1)&0x0f
            if len(state['payload'])>=state['total']:
                self._streams.pop(key,None);return out+[self._message(frame.ts_ns,frame.bus,frame.arbitration_id,bytes(state['payload'][:state['total']]).hex(),state['frames'],ae=ae)]
            return out
        return out
    def expire(self,now_ns:int)->list[IsoTpMessage]:
        now=int(now_ns);out=[]
        for key,state in list(self._streams.items()):
            if now-state['last']>self.max_gap_ns:
                self._streams.pop(key,None);out.append(self._message(state['last'],state['bus'],state['id'],bytes(state['payload']).hex(),state['frames'],False,'timeout',state['ae']))
        return out
    def reset(self):self._streams.clear()
