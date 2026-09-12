from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable

from .domain import Frame

_NOMINAL_MS=(5.0,10.0,20.0,50.0,100.0,200.0,500.0,1000.0)


def _nearest_nominal(period_ms: float) -> float:
    return min(_NOMINAL_MS,key=lambda x:abs(x-period_ms))


def ecu_clock_hypotheses(frames: Iterable[Frame], tolerance_ppm: float = 250.0) -> dict:
    if tolerance_ppm <= 0:
        raise ValueError('tolerance_ppm must be positive')
    groups=defaultdict(list)
    for frame in frames:
        if frame.error or frame.rtr:continue
        groups[(frame.bus,int(frame.arbitration_id))].append(int(frame.ts_ns))
    members=[]
    for (bus,aid),timestamps in groups.items():
        timestamps=sorted(timestamps)
        if len(timestamps)<8:continue
        intervals=[(b-a)/1e6 for a,b in zip(timestamps,timestamps[1:],strict=False) if b>a]
        if len(intervals)<6:continue
        measured=float(statistics.median(intervals));nominal=_nearest_nominal(measured)
        skew_ppm=((measured-nominal)/nominal)*1_000_000.0
        jitter=statistics.pstdev(intervals) if len(intervals)>1 else 0.0
        members.append({'bus':bus,'arbitration_id':aid,'id_hex':f'0x{aid:X}','samples':len(timestamps),'measured_period_ms':round(measured,6),'nominal_period_ms':nominal,'skew_ppm':round(skew_ppm,3),'jitter_ms':round(jitter,6)})
    members.sort(key=lambda x:(x['bus'],x['skew_ppm']))
    clusters=[]
    for member in members:
        placed=False
        for cluster in clusters:
            if cluster['bus']==member['bus'] and abs(cluster['center_skew_ppm']-member['skew_ppm'])<=tolerance_ppm:
                cluster['members'].append(member);cluster['center_skew_ppm']=round(statistics.mean(x['skew_ppm'] for x in cluster['members']),3);placed=True;break
        if not placed:clusters.append({'cluster':len(clusters)+1,'bus':member['bus'],'center_skew_ppm':member['skew_ppm'],'members':[member]})
    return {'clusters':clusters,'identifier_count':len(members),'tolerance_ppm':float(tolerance_ppm),'status':'ecu_membership_hypotheses_only','limitations':['host/kernel timestamp jitter affects separation','clock-aware attackers can spoof timing fingerprints','clusters do not identify a physical ECU without independent evidence']}
