from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from typing import Iterable
from .domain import Frame


def _message_key(frame:Frame)->tuple:
    return (frame.bus,int(frame.arbitration_id),bool(frame.extended),bool(frame.can_fd))


def _digest(value)->str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def fingerprint_frames(frames:Iterable[Frame])->dict:
    """Build passive capture and structural fingerprints from observed frame shape.

    Payload bytes are intentionally excluded. ``capture_sha256`` identifies this
    particular observation including counts/timing. ``structural_sha256`` excludes
    count/timing so repeated captures of the same observed message structure remain
    comparable. ``sha256`` is a compatibility alias for the structural digest.
    Neither digest alone proves a vehicle model.
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
        messages.append({'bus':bus,'id':arb_id,'id_hex':f'0x{arb_id:X}','extended':extended,'can_fd':can_fd,'lengths':lengths,'count':len(items),'median_period_ms':None if not periods else round(float(statistics.median(periods)),3)})
    first=min((int(x.ts_ns) for x in rows),default=None);last=max((int(x.ts_ns) for x in rows),default=None)
    capture={'version':2,'frame_count':len(rows),'message_count':len(messages),'duration_ms':None if first is None or last is None else round((last-first)/1e6,3),'messages':messages}
    structural=[{'bus':m['bus'],'id':m['id'],'extended':m['extended'],'can_fd':m['can_fd'],'lengths':m['lengths']} for m in messages]
    capture_sha=_digest(capture);structural_sha=_digest({'version':2,'messages':structural})
    return {**capture,'capture_sha256':capture_sha,'structural_sha256':structural_sha,'sha256':structural_sha}


def compare_fingerprints(observed:dict,reference:dict,ignore_bus:bool=False)->dict:
    """Fuzzy structural comparison inspired by automotive CAN fingerprinting.

    Extra messages in the observed capture do not invalidate a match. Missing or
    structurally incompatible reference messages reduce confidence. ``ignore_bus``
    permits comparison when OS interface names changed between otherwise equivalent
    single-network captures. Exact model identity still requires external evidence.
    """
    def key(m):
        base=(int(m['id']),bool(m.get('extended')),bool(m.get('can_fd')))
        return base if ignore_bus else (m.get('bus',''),)+base
    def index(fp):return {key(m):m for m in fp.get('messages',[])}
    obs=index(observed);ref=index(reference)
    if not ref:return {'score':0.0,'matched':0,'required':0,'missing':[],'incompatible':[],'ignore_bus':ignore_bus}
    matched=0;missing=[];incompatible=[]
    for k,r in ref.items():
        o=obs.get(k)
        if o is None:
            missing.append({'bus':r.get('bus'),'id':int(r['id'])});continue
        if set(o.get('lengths',[])).isdisjoint(set(r.get('lengths',[]))):
            incompatible.append({'bus':r.get('bus'),'id':int(r['id']),'observed_lengths':o.get('lengths',[]),'reference_lengths':r.get('lengths',[])});continue
        matched+=1
    score=matched/len(ref)
    return {'score':round(score,4),'matched':matched,'required':len(ref),'missing':missing,'incompatible':incompatible,'observed_extra':max(0,len(obs)-matched),'ignore_bus':ignore_bus}
