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
    def as_dict(self):return asdict(self)

class PassiveIsoTpAssembler:
    """Receive-only ISO 15765-2 reassembler.

    The assembler never emits flow-control frames and has no transmit primitive.
    Streams are keyed by observed bus/arbitration ID/frame format, so unknown ECU
    traffic can be reconstructed without assuming request/response address pairs.
    """
    def __init__(self,max_payload:int=1024*1024,max_gap_ns:int=2_000_000_000):
        self.max_payload=max(1,int(max_payload));self.max_gap_ns=max(1,int(max_gap_ns));self._streams={}
    @staticmethod
    def _key(frame:Frame):return (frame.bus,int(frame.arbitration_id),bool(frame.extended),bool(frame.can_fd))
    def consume(self,frame:Frame)->list[IsoTpMessage]:
        if frame.error or frame.rtr:return []
        raw=bytes.fromhex(frame.data)
        if not raw:return []
        out=self.expire(frame.ts_ns);kind=raw[0]>>4;key=self._key(frame)
        if kind==0:
            length=raw[0]&0x0f;start=1
            if length==0:
                if len(raw)<2:return out
                length=raw[1];start=2
            if length>len(raw)-start:return out+[IsoTpMessage(frame.ts_ns,frame.bus,frame.arbitration_id,raw[start:].hex(),1,False,'short_single_frame')]
            return out+[IsoTpMessage(frame.ts_ns,frame.bus,frame.arbitration_id,raw[start:start+length].hex(),1)]
        if kind==1:
            if len(raw)<2:return out
            total=((raw[0]&0x0f)<<8)|raw[1];start=2
            if total==0:
                if len(raw)<6:return out
                total=int.from_bytes(raw[2:6],'big');start=6
            if total<=0 or total>self.max_payload:
                return out+[IsoTpMessage(frame.ts_ns,frame.bus,frame.arbitration_id,'',1,False,'payload_length_out_of_bounds')]
            payload=bytearray(raw[start:]);self._streams[key]={'total':total,'payload':payload,'next_seq':1,'frames':1,'started':frame.ts_ns,'last':frame.ts_ns,'bus':frame.bus,'id':frame.arbitration_id}
            if len(payload)>=total:
                state=self._streams.pop(key);return out+[IsoTpMessage(frame.ts_ns,frame.bus,frame.arbitration_id,bytes(state['payload'][:total]).hex(),1)]
            return out
        if kind==2:
            state=self._streams.get(key)
            if state is None:return out
            seq=raw[0]&0x0f
            if seq!=state['next_seq']:
                self._streams.pop(key,None);return out+[IsoTpMessage(frame.ts_ns,frame.bus,frame.arbitration_id,bytes(state['payload']).hex(),state['frames'],False,'sequence_mismatch')]
            state['payload'].extend(raw[1:]);state['frames']+=1;state['last']=frame.ts_ns;state['next_seq']=(seq+1)&0x0f
            if len(state['payload'])>=state['total']:
                self._streams.pop(key,None);return out+[IsoTpMessage(frame.ts_ns,frame.bus,frame.arbitration_id,bytes(state['payload'][:state['total']]).hex(),state['frames'])]
            return out
        return out
    def expire(self,now_ns:int)->list[IsoTpMessage]:
        now=int(now_ns);out=[]
        for key,state in list(self._streams.items()):
            if now-state['last']>self.max_gap_ns:
                self._streams.pop(key,None);out.append(IsoTpMessage(state['last'],state['bus'],state['id'],bytes(state['payload']).hex(),state['frames'],False,'timeout'))
        return out
    def reset(self):self._streams.clear()
