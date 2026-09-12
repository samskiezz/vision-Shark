from __future__ import annotations
from collections import Counter, defaultdict

class LearningEngine:
    """Passive evidence extraction. Results remain hypotheses until independently validated."""
    def analyze(self, frames) -> dict:
        frames=list(frames)
        ids=Counter((f.bus,f.arbitration_id,f.can_fd,f.extended) for f in frames)
        lengths=defaultdict(Counter); payloads=defaultdict(list)
        for f in frames:
            key=(f.bus,f.arbitration_id)
            raw=bytes.fromhex(f.data)
            lengths[key][len(raw)]+=1
            if len(payloads[key])<256: payloads[key].append(raw)
        candidates=[]
        for (bus,aid),samples in payloads.items():
            width=max(map(len,samples),default=0); varying=[]
            for i in range(width):
                vals={s[i] for s in samples if i<len(s)}
                if len(vals)>1:varying.append({'byte':i,'unique':len(vals)})
            candidates.append({'bus':bus,'arbitration_id':aid,'samples':len(samples),'varying_bytes':varying})
        return {
            'frame_count':len(frames),
            'message_inventory':[{'bus':k[0],'arbitration_id':k[1],'can_fd':k[2],'extended':k[3],'count':n} for k,n in ids.most_common()],
            'lengths':{f'{b}:{aid:X}':dict(c) for (b,aid),c in lengths.items()},
            'signal_hypotheses':candidates,
            'status':'hypotheses_only',
        }
