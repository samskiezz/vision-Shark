from __future__ import annotations
from collections import Counter,defaultdict
import math

class LearningEngine:
    """Passive evidence extraction. Every inferred field remains a hypothesis until independently validated."""
    def analyze(self,frames)->dict:
        frames=list(frames);ids=Counter((f.bus,f.arbitration_id,f.can_fd,f.extended) for f in frames);lengths=defaultdict(Counter);payloads=defaultdict(list);times=defaultdict(list)
        for f in frames:
            key=(f.bus,f.arbitration_id);raw=bytes.fromhex(f.data);lengths[key][len(raw)]+=1
            if len(payloads[key])<2048:payloads[key].append(raw);times[key].append(int(f.ts_ns))
        candidates=[]
        for (bus,aid),samples in payloads.items():
            width=max(map(len,samples),default=0);varying=[];counter=[];checksum=[]
            for i in range(width):
                vals=[s[i] for s in samples if i<len(s)];unique=len(set(vals))
                if unique>1:varying.append({'byte':i,'unique':unique,'entropy_bits':round(self._entropy(vals),4)})
                if len(vals)>=10:
                    inc=sum(1 for a,b in zip(vals,vals[1:],strict=False) if ((b-a)&0xff)==1)/max(1,len(vals)-1)
                    if inc>=.85:counter.append({'byte':i,'increment_ratio':round(inc,4),'modulus':256})
                    matches=sum(1 for s in samples if len(s)>1 and i<len(s) and s[i]==(sum(s[:i])+sum(s[i+1:]))&0xff)
                    if matches/max(1,len(samples))>=.9:checksum.append({'byte':i,'algorithm':'sum8-other-bytes','match_ratio':round(matches/max(1,len(samples)),4)})
            ts=times[(bus,aid)];intervals=[(b-a)/1e6 for a,b in zip(ts,ts[1:],strict=False) if b>=a];period={'median_ms':self._median(intervals),'jitter_ms':self._std(intervals)} if intervals else None
            candidates.append({'bus':bus,'arbitration_id':aid,'samples':len(samples),'varying_bytes':varying,'counter_hypotheses':counter,'checksum_hypotheses':checksum,'periodicity':period})
        return {'frame_count':len(frames),'message_inventory':[{'bus':k[0],'arbitration_id':k[1],'can_fd':k[2],'extended':k[3],'count':n} for k,n in ids.most_common()],'lengths':{f'{b}:{aid:X}':dict(c) for (b,aid),c in lengths.items()},'signal_hypotheses':candidates,'status':'hypotheses_only'}
    def _entropy(self,values):
        if not values:return 0.
        c=Counter(values);n=len(values);return -sum((v/n)*math.log2(v/n) for v in c.values())
    def _median(self,values):
        if not values:return None
        x=sorted(values);m=len(x)//2;return round(x[m] if len(x)%2 else (x[m-1]+x[m])/2,4)
    def _std(self,values):
        if len(values)<2:return 0.
        mean=sum(values)/len(values);return round(math.sqrt(sum((x-mean)**2 for x in values)/len(values)),4)
