from __future__ import annotations

from dataclasses import dataclass, asdict, field
from decimal import Decimal, InvalidOperation
from typing import Any
import json, re

_RATE_UNITS={
    'hz':('frequency_hz',Decimal(1)), 'khz':('frequency_hz',Decimal(1_000)),
    'mhz':('frequency_hz',Decimal(1_000_000)), 'ghz':('frequency_hz',Decimal(1_000_000_000)),
    'bps':('bitrate_bps',Decimal(1)), 'kbps':('bitrate_bps',Decimal(1_000)),
    'mbps':('bitrate_bps',Decimal(1_000_000)), 'gbps':('bitrate_bps',Decimal(1_000_000_000)),
    'bit/s':('bitrate_bps',Decimal(1)), 'kbit/s':('bitrate_bps',Decimal(1_000)),
    'mbit/s':('bitrate_bps',Decimal(1_000_000)), 'gbit/s':('bitrate_bps',Decimal(1_000_000_000)),
}
_TIME_UNITS={'ns':Decimal('1e-9'),'us':Decimal('1e-6'),'ms':Decimal('1e-3'),'s':Decimal(1)}

@dataclass(frozen=True)
class Quantity:
    dimension:str
    base_value:Decimal
    source_value:Decimal
    source_unit:str
    def as_float(self)->float:return float(self.base_value)
    def as_dict(self):return {'dimension':self.dimension,'base_value':str(self.base_value),'source_value':str(self.source_value),'source_unit':self.source_unit}


def parse_quantity(text:str)->Quantity:
    m=re.fullmatch(r'\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*([A-Za-z/]+)\s*',str(text))
    if not m:raise ValueError('quantity must look like 500kbps, 100MHz or 2.5ms')
    try:value=Decimal(m.group(1))
    except InvalidOperation as exc:raise ValueError('invalid numeric quantity') from exc
    unit=m.group(2).lower()
    if value<0:raise ValueError('quantity cannot be negative')
    if unit in _RATE_UNITS:
        dimension,mult=_RATE_UNITS[unit];return Quantity(dimension,value*mult,value,unit)
    if unit in _TIME_UNITS:return Quantity('time_s',value*_TIME_UNITS[unit],value,unit)
    raise ValueError(f'unsupported unit: {unit}')


def convert_quantity(text:str,target_unit:str)->Decimal:
    q=parse_quantity(text);unit=target_unit.lower()
    if q.dimension=='time_s':
        if unit not in _TIME_UNITS:raise ValueError('dimension mismatch')
        return q.base_value/_TIME_UNITS[unit]
    if unit not in _RATE_UNITS or _RATE_UNITS[unit][0]!=q.dimension:raise ValueError('dimension mismatch')
    return q.base_value/_RATE_UNITS[unit][1]

@dataclass(frozen=True)
class SignalEvent:
    """Transport-neutral Vision Signal Language event.

    VSL preserves physical/link metadata instead of pretending CAN bitrate and
    Ethernet PHY clock are the same quantity. Higher layers (ISO-TP/UDS) can be
    compared across transports without losing where the bytes came from.
    """
    ts_ns:int
    transport:str
    layer:str
    payload_hex:str
    channel:str=''
    source:str|None=None
    target:str|None=None
    identifier:int|None=None
    metadata:dict[str,Any]=field(default_factory=dict)
    version:int=1
    def __post_init__(self):
        if self.ts_ns<0:raise ValueError('timestamp must be non-negative')
        if self.transport not in {'can','canfd','j2534','isotp','doip','ethernet','simulation'}:raise ValueError('unsupported VSL transport')
        if len(self.payload_hex)%2:raise ValueError('payload hex length must be even')
        bytes.fromhex(self.payload_hex)
    def as_dict(self):return asdict(self)
    def encode(self)->str:return 'VSL1 '+json.dumps(self.as_dict(),sort_keys=True,separators=(',',':'))
    @classmethod
    def decode(cls,line:str):
        if not line.startswith('VSL1 '):raise ValueError('unsupported VSL version')
        return cls(**json.loads(line[5:]))


def from_can_frame(frame,nominal_bitrate:str|None=None,data_bitrate:str|None=None)->SignalEvent:
    meta={'extended':bool(frame.extended),'rtr':bool(frame.rtr),'error':bool(frame.error),'brs':bool(frame.brs),'esi':bool(frame.esi)}
    if nominal_bitrate:meta['nominal_bitrate']=parse_quantity(nominal_bitrate).as_dict()
    if data_bitrate:meta['data_bitrate']=parse_quantity(data_bitrate).as_dict()
    return SignalEvent(frame.ts_ns,'canfd' if frame.can_fd else 'can','data-link',frame.data,frame.bus,identifier=frame.arbitration_id,metadata=meta)

J2534_PROTOCOLS={
    0x01:'j1850vpw',0x02:'j1850pwm',0x03:'iso9141',0x04:'iso14230',0x05:'can',0x06:'iso15765',
    # CAN-FD is provided by J2534-2/11 implementations; numeric IDs can be vendor/API revision specific,
    # so callers should supply protocol_name when importing those records.
}

def from_j2534(ts_ns:int,payload:bytes,protocol_id:int,channel:str='j2534',protocol_name:str|None=None,metadata:dict|None=None)->SignalEvent:
    name=(protocol_name or J2534_PROTOCOLS.get(int(protocol_id)) or f'protocol-0x{int(protocol_id):x}').lower()
    layer='transport' if name in {'iso15765','isotp'} else 'data-link'
    meta={'protocol_id':int(protocol_id),'protocol_name':name,**(metadata or {})}
    return SignalEvent(int(ts_ns),'j2534',layer,payload.hex(),channel,metadata=meta)


def from_doip(ts_ns:int,payload_type:int,payload:bytes,source_address:int|None=None,target_address:int|None=None,endpoint:str|None=None)->SignalEvent:
    layer='diagnostic' if int(payload_type)==0x8001 else 'transport'
    meta={'payload_type':int(payload_type)}
    if endpoint:meta['endpoint']=endpoint
    return SignalEvent(int(ts_ns),'doip',layer,payload.hex(),'doip',None if source_address is None else f'0x{source_address:04x}',None if target_address is None else f'0x{target_address:04x}',metadata=meta)


def uds_payload(event:SignalEvent)->bytes|None:
    """Return the UDS application bytes when VSL knows how to strip transport headers."""
    raw=bytes.fromhex(event.payload_hex)
    if event.transport=='doip' and event.metadata.get('payload_type')==0x8001:
        return raw
    if event.transport in {'isotp','j2534'} and event.layer in {'transport','diagnostic'}:
        return raw
    return None


def classify_event(event:SignalEvent)->dict[str,Any]:
    raw=bytes.fromhex(event.payload_hex);uds=uds_payload(event)
    result={'transport':event.transport,'layer':event.layer,'bytes':len(raw),'channel':event.channel}
    if uds:
        sid=uds[0];result['uds_service']=sid;result['uds_positive_response']=sid>=0x40 and sid!=0x7f;result['uds_negative_response']=sid==0x7f
    return result
