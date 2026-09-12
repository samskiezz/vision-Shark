from __future__ import annotations
from pydantic import BaseModel, Field, field_validator

class Frame(BaseModel):
    ts_ns:int=Field(ge=0)
    bus:str=Field(min_length=1,max_length=64)
    arbitration_id:int=Field(ge=0,le=0x1fffffff)
    data:str=''
    extended:bool=False
    can_fd:bool=False
    brs:bool=False
    esi:bool=False
    rtr:bool=False
    error:bool=False
    direction:str='rx'
    @field_validator('data')
    @classmethod
    def valid_hex(cls,v):
        if len(v)%2:raise ValueError('CAN payload hex must have an even length')
        try:bytes.fromhex(v)
        except ValueError as e:raise ValueError('CAN payload must be hexadecimal') from e
        if len(v)//2>64:raise ValueError('CAN payload exceeds 64 bytes')
        return v.lower()

def bit_positions(start:int,length:int,byte_order:str)->list[int]:
    if byte_order=='little':return list(range(start,start+length))
    if byte_order!='big':raise ValueError('unknown byte order')
    positions=[]; p=start
    for _ in range(length):
        positions.append(p)
        p=p+15 if p%8==0 else p-1
    return positions

class ConnectRequest(BaseModel):
    source:str
    interface:str|None=None
    pack_id:str|None=None

class VehiclePack(BaseModel):
    pack_id:str
    name:str
    scope:str='research'
    signals:list[dict]=[]
    fingerprints:list[dict]=[]
    evidence:list[dict]=[]
