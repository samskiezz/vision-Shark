"""Bounded non-transmitting DBC research decoder.

This module intentionally decodes only. Imported definitions do not grant a
vehicle transmit capability or constitute evidence that a signal applies to a
particular vehicle.
"""
from __future__ import annotations
import hashlib, math, re, struct
from .domain import Frame, bit_positions

NUMBER=r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
BO=re.compile(r'^BO_\s+(\d+)\s+(\w+)\s*:\s*(\d+)\s+\w+')
SG=re.compile(r'^SG_\s+(\w+)(?:\s+(M|m\d+M?))?\s*:\s*(\d+)\|(\d+)@([01])([+-])\s*\(('+NUMBER+r'),\s*('+NUMBER+r')\)\s*\[('+NUMBER+r')\|('+NUMBER+r')\]\s*"([^"\r\n]*)"')
LEGAL_FD_LENGTHS={0,1,2,3,4,5,6,7,8,12,16,20,24,32,48,64}

def parse_database(text:str)->dict:
    if not text or len(text.encode())>2*1024**2: raise ValueError('DBC must contain between 1 byte and 2 MiB')
    messages={}; current=None; count=0
    for n,line in enumerate(text.splitlines(),1):
        line=line.strip()
        if line.startswith('BO_ '):
            m=BO.match(line)
            if not m: raise ValueError(f'Invalid message on line {n}')
            ident,name,size=m.groups(); wire=int(ident); size=int(size)
            if size not in LEGAL_FD_LENGTHS: raise ValueError('Invalid CAN payload length')
            ext=bool(wire&0x80000000); can_id=wire&0x1fffffff
            current={'id':wire,'name':name,'arbitration_id':can_id,'extended':ext,'can_fd':size>8,'length':size,'signals':[]}; messages[wire]=current
        elif line.startswith('SG_ '):
            m=SG.match(line)
            if not m or current is None: raise ValueError(f'Invalid signal on line {n}')
            name,mux,start,length,order,sign,scale,offset,lo,hi,unit=m.groups(); start=int(start); length=int(length)
            if not 1<=length<=64: raise ValueError('Invalid signal width')
            order='little' if order=='1' else 'big'
            if max(bit_positions(start,length,order))>=current['length']*8: raise ValueError('Signal exceeds message')
            scale,offset,lo,hi=map(float,(scale,offset,lo,hi))
            current['signals'].append({'name':name,'start_bit':start,'length':length,'byte_order':order,'signed':sign=='-','scale':scale,'offset':offset,'minimum':lo,'maximum':hi,'unit':unit,'is_multiplexer':mux=='M','mux_value':int(mux[1:].rstrip('M')) if mux and mux.startswith('m') else None})
            count+=1
    if not messages or not count: raise ValueError('No DBC messages/signals')
    return {'schema':'vision.dbc/1','source_sha256':hashlib.sha256(text.encode()).hexdigest(),'messages':list(messages.values()),'signal_count':count,'vehicle_validated':False,'scope':'research decode only; no transmit'}

def _raw(data:bytes,s:dict)->int:
    pos=bit_positions(s['start_bit'],s['length'],s['byte_order'])
    if max(pos)>=len(data)*8: raise ValueError('Truncated payload')
    bits=[(data[p//8]>>(p%8))&1 for p in pos]
    if s['byte_order']=='little': return sum(b<<i for i,b in enumerate(bits))
    v=0
    for b in bits:v=(v<<1)|b
    return v

def decode_message(database:dict,frame:Frame)->list[dict]:
    if frame.error or frame.rtr:return []
    msg=next((m for m in database['messages'] if (m['arbitration_id'],m['extended'],m['can_fd'])==(frame.arbitration_id,frame.extended,frame.can_fd)),None)
    if msg is None:return []
    data=bytes.fromhex(frame.data)
    if len(data)!=msg['length']:raise ValueError('Payload length mismatch')
    selector=next((s for s in msg['signals'] if s['is_multiplexer']),None); selector_value=_raw(data,selector) if selector else None
    out=[]
    for s in msg['signals']:
        if s['mux_value'] is not None and s['mux_value']!=selector_value:continue
        raw=_raw(data,s); value=raw
        if s['signed'] and raw&(1<<(s['length']-1)):value-=1<<s['length']
        scaled=value*s['scale']+s['offset']; valid=math.isfinite(scaled)
        out.append({'message':msg['name'],'signal':s['name'],'raw':str(raw),'value':scaled if valid else None,'unit':s['unit'],'finite':valid,'within_declared_range':valid and s['minimum']<=scaled<=s['maximum'],'ts_ns':str(frame.ts_ns),'bus':frame.bus,'dbc_sha256':database['source_sha256']})
    return out
