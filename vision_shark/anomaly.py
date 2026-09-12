from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable

from .domain import Frame


def _entropy(values: list[int]) -> float:
    if not values:
        return 0.0
    counts=Counter(values);n=len(values)
    return -sum((c/n)*math.log2(c/n) for c in counts.values())


def _stats(frames: Iterable[Frame]) -> dict:
    groups=defaultdict(list)
    for frame in frames:
        if frame.error or frame.rtr:continue
        groups[(frame.bus,int(frame.arbitration_id),bool(frame.extended),bool(frame.can_fd))].append(frame)
    out={}
    for key,items in groups.items():
        items=sorted(items,key=lambda f:int(f.ts_ns));intervals=[(int(b.ts_ns)-int(a.ts_ns))/1e6 for a,b in zip(items,items[1:],strict=False) if int(b.ts_ns)>=int(a.ts_ns)]
        bytes_flat=[v for f in items for v in bytes.fromhex(f.data)]
        duration_s=max(1e-9,(int(items[-1].ts_ns)-int(items[0].ts_ns))/1e9) if len(items)>1 else 0.0
        out[key]={'count':len(items),'rate_hz':0.0 if duration_s<=0 else len(items)/duration_s,'median_period_ms':None if not intervals else statistics.median(intervals),'jitter_ms':0.0 if len(intervals)<2 else statistics.pstdev(intervals),'lengths':sorted({len(bytes.fromhex(f.data)) for f in items}),'entropy_bits':_entropy(bytes_flat)}
    return out


def compare_anomaly(baseline: Iterable[Frame], observed: Iterable[Frame]) -> dict:
    base=_stats(baseline);obs=_stats(observed);findings=[]
    for key,b in base.items():
        o=obs.get(key);bus,aid,extended,can_fd=key
        meta={'bus':bus,'arbitration_id':aid,'id_hex':f'0x{aid:X}','extended':extended,'can_fd':can_fd}
        if o is None:
            findings.append({**meta,'kind':'missing_identifier','severity':'observation'});continue
        if set(b['lengths'])!=set(o['lengths']):findings.append({**meta,'kind':'length_change','baseline':b['lengths'],'observed':o['lengths'],'severity':'observation'})
        if b['rate_hz']>0 and abs(o['rate_hz']-b['rate_hz'])/b['rate_hz']>=0.5:findings.append({**meta,'kind':'rate_shift','baseline_hz':round(b['rate_hz'],3),'observed_hz':round(o['rate_hz'],3),'severity':'observation'})
        if abs(o['entropy_bits']-b['entropy_bits'])>=0.75:findings.append({**meta,'kind':'entropy_shift','baseline_bits':round(b['entropy_bits'],3),'observed_bits':round(o['entropy_bits'],3),'severity':'observation'})
        if b['jitter_ms']>0 and o['jitter_ms']>max(b['jitter_ms']*2,b['jitter_ms']+2):findings.append({**meta,'kind':'jitter_increase','baseline_ms':round(b['jitter_ms'],3),'observed_ms':round(o['jitter_ms'],3),'severity':'observation'})
    for key,o in obs.items():
        if key in base:continue
        bus,aid,extended,can_fd=key;findings.append({'bus':bus,'arbitration_id':aid,'id_hex':f'0x{aid:X}','extended':extended,'can_fd':can_fd,'kind':'new_identifier','observed_count':o['count'],'severity':'observation'})
    return {'baseline_messages':len(base),'observed_messages':len(obs),'findings':findings,'status':'operator_observations_only'}
