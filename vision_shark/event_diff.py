from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from .domain import Frame


def event_bit_diff(frames: Iterable[Frame], events: list[dict], window_ms: float = 500.0) -> dict:
    if window_ms <= 0:
        raise ValueError('window_ms must be positive')
    rows = [f for f in frames if not f.error and not f.rtr]
    if not events:
        return {'candidates': [], 'event_count': 0, 'frame_count': len(rows), 'status': 'no_events'}
    windows = []
    half = int(window_ms * 1_000_000)
    for event in events:
        ts = int(event['ts_ns'])
        windows.append((ts-half, ts+half, str(event.get('label') or 'event')))
    grouped = defaultdict(list)
    for frame in rows:
        grouped[(frame.bus, int(frame.arbitration_id), bool(frame.extended), bool(frame.can_fd))].append(frame)
    candidates = []
    for key, items in grouped.items():
        width = max((len(bytes.fromhex(f.data))*8 for f in items), default=0)
        for bit in range(width):
            inside=[];outside=[]
            for frame in items:
                raw=bytes.fromhex(frame.data)
                if bit//8 >= len(raw):
                    continue
                value=(raw[bit//8]>>(bit%8))&1
                if any(start <= int(frame.ts_ns) <= end for start,end,_ in windows):inside.append(value)
                else:outside.append(value)
            if len(inside)<2 or len(set(inside))<2:
                continue
            inside_flip=sum(1 for a,b in zip(inside,inside[1:],strict=False) if a!=b)/max(1,len(inside)-1)
            outside_flip=sum(1 for a,b in zip(outside,outside[1:],strict=False) if a!=b)/max(1,len(outside)-1) if len(outside)>1 else 0.0
            score=max(0.0,inside_flip-outside_flip)
            if score<=0:
                continue
            bus,aid,extended,can_fd=key
            candidates.append({'bus':bus,'arbitration_id':aid,'id_hex':f'0x{aid:X}','extended':extended,'can_fd':can_fd,'bit':bit,'byte':bit//8,'bit_in_byte':bit%8,'inside_flip_rate':round(inside_flip,4),'outside_flip_rate':round(outside_flip,4),'score':round(score,4),'status':'hypothesis'})
    candidates.sort(key=lambda x:(x['score'],x['inside_flip_rate']),reverse=True)
    return {'candidates':candidates,'event_count':len(events),'frame_count':len(rows),'window_ms':window_ms,'status':'hypotheses_only'}
