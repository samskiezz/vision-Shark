from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from typing import Iterable
from .domain import Frame


def _message_key(frame:Frame)->tuple:
    return (frame.bus,int(frame.arbitration_id),bool(frame.extended),bool(frame.can_fd))


def fingerprint_frames(frames:Iterable[Frame])->dict:
    """Build a passive, content-free vehicle fingerprint from observed frame structure.

    Payload bytes are intentionally excluded. The fingerprint uses bus, arbitration
    ID, frame format, observed payload lengths and timing statistics so captures can
    be compared without treating unknown signal content as established semantics.
    """
    rows=list(frames);groups=defaultdict(list)
    for frame in rows:
        if frame.error:continue
        groups[_message_key(frame)].append(frame)
    messages=[]
    for (bus,arb_id,extended,can_fd),items in sorted(groups.items(),key=lambda x:(x[0][0],x[0][1],x[0][2],x[0][3])):
        timestamps=sorted(int(x.ts_ns) for x in items)
        periods=[(b-a)/1e6 for a,b in zip(timestamps,timestamps[1:]) if b>=a]
        lengths=sorted({len(bytes.fromhex(x.data)) for x in items})
        messages.append({
            'bus':bus,'id':arb_id,'id_hex':f'0x{arb_id:X}','extended':extended,'can_fd':can_fd,
            'lengths':lengths,'count':len(items),
            'median_period_ms':None if not periods else round(float(statistics.median(periods)),3),
        })
    first=min((int(x.ts_ns) for x in rows),default=None);last=max((int(x.ts_ns) for x in rows),default=None)
    canonical={'version':1,'frame_count':len(rows),'message_count':len(messages),'duration_ms':None if first is None or last is None else round((last-first)/1e6,3),'messages':messages}
    digest=hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {**canonical,'sha256':digest}


def compare_fingerprints(observed:dict,reference:dict)->dict:
    """Fuzzy structural comparison inspired by automotive CAN fingerprinting.

    Extra messages in the observed capture do not invalidate a match. Missing or
    structurally incompatible reference messages reduce confidence. This never
    identifies a model by itself; the caller must bind a reference to evidence.
    """
    def index(fp):
        return {(m['bus'],int(m['id']),bool(m.get('extended')),bool(m.get('can_fd'))):m for m in fp.get('messages',[])}
    obs=index(observed);ref=index(reference)
    if not ref:return {'score':0.0,'matched':0,'required':0,'missing':[],'incompatible':[]}
    matched=0;missing=[];incompatible=[]
    for key,r in ref.items():
        o=obs.get(key)
        if o is None:
            missing.append({'bus':key[0],'id':key[1]});continue
        if set(o.get('lengths',[])).isdisjoint(set(r.get('lengths',[]))):
            incompatible.append({'bus':key[0],'id':key[1],'observed_lengths':o.get('lengths',[]),'reference_lengths':r.get('lengths',[])});continue
        matched+=1
    score=matched/len(ref)
    return {'score':round(score,4),'matched':matched,'required':len(ref),'missing':missing,'incompatible':incompatible,'observed_extra':max(0,len(obs)-matched)}
