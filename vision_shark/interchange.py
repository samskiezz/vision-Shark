from __future__ import annotations

import csv
import io
import json
import re
from typing import Iterable
from .domain import Frame

_CANDUMP_HASH=re.compile(r'^\s*(?:\((?P<ts>\d+(?:\.\d+)?)\)\s+)?(?P<bus>[A-Za-z0-9_.-]+)\s+(?P<id>[0-9A-Fa-f]{1,8})(?P<sep>##|#)(?P<body>[0-9A-Fa-f]*)\s*$')
_CANDUMP_PRETTY=re.compile(r'^\s*(?P<bus>[A-Za-z0-9_.-]+)\s+(?P<id>[0-9A-Fa-f]{1,8})\s+\[(?P<len>\d+)\]\s*(?P<body>(?:[0-9A-Fa-f]{2}\s*)*)$')
_FIELDS=['ts_ns','bus','arbitration_id','data','extended','can_fd','brs','esi','rtr','error','direction']

def parse_candump(text:str,max_frames:int=1_000_000)->list[Frame]:
    frames=[];synthetic_ts=0
    for line_no,line in enumerate(str(text).splitlines(),1):
        if not line.strip():continue
        m=_CANDUMP_HASH.match(line)
        if m:
            arb=int(m.group('id'),16);is_fd=m.group('sep')=='##';body=m.group('body');brs=False;esi=False
            if is_fd:
                if not body:raise ValueError(f'candump line {line_no}: missing CAN-FD flags')
                flags=int(body[0],16);brs=bool(flags&1);esi=bool(flags&2);body=body[1:]
            ts=int(float(m.group('ts'))*1_000_000_000) if m.group('ts') else synthetic_ts;synthetic_ts=max(synthetic_ts+1,ts+1)
            frames.append(Frame(ts_ns=ts,bus=m.group('bus'),arbitration_id=arb,data=body,extended=arb>0x7ff,can_fd=is_fd,brs=brs,esi=esi))
        else:
            m=_CANDUMP_PRETTY.match(line)
            if not m:raise ValueError(f'unsupported candump line {line_no}')
            body=''.join(m.group('body').split());declared=int(m.group('len'))
            if len(body)//2!=declared:raise ValueError(f'candump line {line_no}: length mismatch')
            arb=int(m.group('id'),16);frames.append(Frame(ts_ns=synthetic_ts,bus=m.group('bus'),arbitration_id=arb,data=body,extended=arb>0x7ff));synthetic_ts+=1
        if len(frames)>max_frames:raise ValueError('capture exceeds frame limit')
    return frames

def export_candump(frames:Iterable[Frame])->str:
    lines=[]
    for f in frames:
        ident=f'{f.arbitration_id:08X}' if f.extended else f'{f.arbitration_id:03X}'
        if f.can_fd:
            flags=(1 if f.brs else 0)|(2 if f.esi else 0);payload=f'{ident}##{flags:X}{f.data.upper()}'
        else:payload=f'{ident}#{f.data.upper()}'
        lines.append(f'({f.ts_ns/1e9:.9f}) {f.bus} {payload}')
    return '\n'.join(lines)+('\n' if lines else '')

def parse_jsonl(text:str,max_frames:int=1_000_000)->list[Frame]:
    frames=[]
    for line_no,line in enumerate(str(text).splitlines(),1):
        if not line.strip():continue
        try:frames.append(Frame.model_validate(json.loads(line)))
        except Exception as exc:raise ValueError(f'invalid JSONL frame at line {line_no}: {exc}') from exc
        if len(frames)>max_frames:raise ValueError('capture exceeds frame limit')
    return frames

def export_jsonl(frames:Iterable[Frame])->str:
    return ''.join(json.dumps(f.model_dump(mode='json'),sort_keys=True,separators=(',',':'))+'\n' for f in frames)

def parse_csv(text:str,max_frames:int=1_000_000)->list[Frame]:
    reader=csv.DictReader(io.StringIO(str(text)))
    if not reader.fieldnames or not {'ts_ns','bus','arbitration_id','data'}<=set(reader.fieldnames):raise ValueError('CSV requires ts_ns,bus,arbitration_id,data columns')
    frames=[]
    for row in reader:
        def b(name):return str(row.get(name,'')).strip().lower() in ('1','true','yes','y')
        arb_text=str(row['arbitration_id']).strip();arb=int(arb_text,16) if arb_text.lower().startswith('0x') else int(arb_text)
        frames.append(Frame(ts_ns=int(row['ts_ns']),bus=row['bus'],arbitration_id=arb,data=row.get('data',''),extended=b('extended'),can_fd=b('can_fd'),brs=b('brs'),esi=b('esi'),rtr=b('rtr'),error=b('error'),direction=row.get('direction') or 'rx'))
        if len(frames)>max_frames:raise ValueError('capture exceeds frame limit')
    return frames

def export_csv(frames:Iterable[Frame])->str:
    out=io.StringIO();writer=csv.DictWriter(out,fieldnames=_FIELDS,lineterminator='\n');writer.writeheader()
    for f in frames:
        row=f.model_dump(mode='json');writer.writerow({k:row.get(k) for k in _FIELDS})
    return out.getvalue()

def load_frames(content:str,fmt:str)->list[Frame]:
    fmt=str(fmt).lower().lstrip('.')
    if fmt in ('candump','log'):return parse_candump(content)
    if fmt in ('jsonl','ndjson'):return parse_jsonl(content)
    if fmt=='csv':return parse_csv(content)
    raise ValueError('supported formats: candump/log, jsonl/ndjson, csv')

def dump_frames(frames:Iterable[Frame],fmt:str)->str:
    fmt=str(fmt).lower().lstrip('.')
    if fmt in ('candump','log'):return export_candump(frames)
    if fmt in ('jsonl','ndjson'):return export_jsonl(frames)
    if fmt=='csv':return export_csv(frames)
    raise ValueError('supported formats: candump/log, jsonl/ndjson, csv')
