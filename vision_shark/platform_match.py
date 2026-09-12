from __future__ import annotations

from collections.abc import Iterable

from .domain import Frame


def observed_signature(frames:Iterable[Frame])->set[tuple[int,int,bool,bool]]:
    return {(int(f.arbitration_id),len(bytes.fromhex(f.data)),bool(f.extended),bool(f.can_fd)) for f in frames if not f.error and not f.rtr}


def match_platforms(frames:Iterable[Frame],profiles:list[dict])->dict:
    observed=observed_signature(frames);matches=[]
    for profile in profiles:
        required=set()
        for item in profile.get('messages',[]):
            required.add((int(item['arbitration_id']),int(item['length']),bool(item.get('extended',False)),bool(item.get('can_fd',False))))
        if not required:continue
        overlap=observed & required;missing=required-observed;extra=observed-required
        score=len(overlap)/len(required)
        matches.append({'name':str(profile.get('name') or 'unnamed'),'score':round(score,4),'matched':len(overlap),'required':len(required),'missing':[{'arbitration_id':x[0],'length':x[1],'extended':x[2],'can_fd':x[3]} for x in sorted(missing)],'observed_extra':len(extra),'evidence':profile.get('evidence'),'status':'structural_hypothesis'})
    matches.sort(key=lambda x:(x['score'],x['matched']),reverse=True)
    return {'observed_messages':len(observed),'matches':matches,'best':matches[0] if matches else None,'status':'hypotheses_only','note':'Address/length overlap does not prove vehicle identity without independent exact-vehicle evidence.'}
