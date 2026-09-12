from __future__ import annotations
from pydantic import BaseModel, Field, field_validator, model_validator

LEGAL_FD_LENGTHS={0,1,2,3,4,5,6,7,8,12,16,20,24,32,48,64}

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
    @field_validator('direction')
    @classmethod
    def valid_direction(cls,v):
        v=str(v).lower()
        if v not in {'rx','tx','unknown'}:raise ValueError('direction must be rx, tx or unknown')
        return v
    @model_validator(mode='after')
    def physical_invariants(self):
        n=len(self.data)//2
        if not self.extended and self.arbitration_id>0x7ff:raise ValueError('standard CAN identifier exceeds 11 bits')
        if self.can_fd:
            if n not in LEGAL_FD_LENGTHS:raise ValueError('invalid CAN-FD payload length')
            if self.rtr:raise ValueError('CAN-FD does not support RTR frames')
        else:
            if n>8:raise ValueError('classic CAN payload exceeds 8 bytes')
            if self.brs or self.esi:raise ValueError('BRS/ESI are CAN-FD-only flags')
        if self.rtr and n:raise ValueError('RTR frames cannot contain data')
        return self

def bit_positions(start:int,length:int,byte_order:str)->list[int]:
    if byte_order=='little':return list(range(start,start+length))
    if byte_order!='big':raise ValueError('unknown byte order')
    positions=[];p=start
    for _ in range(length):
        positions.append(p);p=p+15 if p%8==0 else p-1
    return positions

class ConnectRequest(BaseModel):
    source:str
    interface:str|None=None
    pack_id:str|None=None

class VehiclePack(BaseModel):
    pack_id:str
    name:str
    scope:str='research'
    signals:list[dict]=Field(default_factory=list)
    fingerprints:list[dict]=Field(default_factory=list)
    evidence:list[dict]=Field(default_factory=list)
