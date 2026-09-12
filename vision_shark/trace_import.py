from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .domain import Frame

_NSEC=Decimal(1_000_000_000)
_ASC=re.compile(r'^\s*(?P<ts>\d+(?:\.\d+)?)\s+(?P<bus>\d+)\s+(?P<id>[0-9A-Fa-f]+)(?P<ext>x)?\s+(?P<dir>Rx|Tx)\s+(?P<kind>d|r)\s+(?P<len>\d+)\s*(?P<data>(?:[0-9A-Fa-f]{2}\s*)*)$',re.I)
_TRC=re.compile(r'^\s*(?:\d+\)\s+)?(?P<ts>\d+(?:\.\d+)?)\s+(?P<dir>Rx|Tx)\s+(?P<id>[0-9A-Fa-f]+)\s+(?P<kind>DT|RTR|FD)\s+(?P<len>\d+)\s*(?P<data>(?:[0-9A-Fa-f]{2}\s*)*)$',re.I)


def _ns(value:str)->int:
    try:scaled=Decimal(value)*_NSEC
    except InvalidOperation as exc:raise ValueError('invalid timestamp') from exc
    return int(scaled.to_integral_value())


def parse_asc(text:str,max_frames:int=1_000_000)->list[Frame]:
    frames=[]
    for line_no,line in enumerate(str(text).splitlines(),1):
        stripped=line.strip()
        if not stripped or stripped.lower().startswith(('date ','base ','internal events','begin triggerblock','end triggerblock')):continue
        m=_ASC.match(line)
        if not m:continue
        declared=int(m.group('len'));body=''.join(m.group('data').split())
        rtr=m.group('kind').lower()=='r'
        if not rtr and len(body)//2!=declared:raise ValueError(f'ASC line {line_no}: length mismatch')
        aid=int(m.group('id'),16);frames.append(Frame(ts_ns=_ns(m.group('ts')),bus=f"can{max(0,int(m.group('bus'))-1)}",arbitration_id=aid,data='' if rtr else body,extended=bool(m.group('ext')) or aid>0x7ff,rtr=rtr,direction=m.group('dir').lower()))
        if len(frames)>max_frames:raise ValueError('capture exceeds frame limit')
    if not frames:raise ValueError('no supported ASC frames found')
    return frames


def parse_trc(text:str,max_frames:int=1_000_000)->list[Frame]:
    frames=[]
    for line_no,line in enumerate(str(text).splitlines(),1):
        stripped=line.strip()
        if not stripped or stripped.startswith(';') or stripped.startswith(';$'):continue
        m=_TRC.match(line)
        if not m:continue
        kind=m.group('kind').upper();declared=int(m.group('len'));body=''.join(m.group('data').split());rtr=kind=='RTR';fd=kind=='FD'
        if not rtr and len(body)//2!=declared:raise ValueError(f'TRC line {line_no}: length mismatch')
        aid=int(m.group('id'),16);frames.append(Frame(ts_ns=_ns(m.group('ts')),bus='can0',arbitration_id=aid,data='' if rtr else body,extended=aid>0x7ff,can_fd=fd,rtr=rtr,direction=m.group('dir').lower()))
        if len(frames)>max_frames:raise ValueError('capture exceeds frame limit')
    if not frames:raise ValueError('no supported TRC frames found')
    return frames


def load_trace(content:str,fmt:str)->list[Frame]:
    name=str(fmt).lower().lstrip('.')
    if name=='asc':return parse_asc(content)
    if name=='trc':return parse_trc(content)
    raise ValueError('supported trace formats: asc, trc')
