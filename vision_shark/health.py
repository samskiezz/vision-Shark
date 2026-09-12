from __future__ import annotations

import time
from dataclasses import dataclass,asdict

@dataclass(frozen=True)
class HealthCheck:
    name:str
    status:str
    detail:str
    required:bool=True
    observed_at_ns:int=0
    def as_dict(self):
        row=asdict(self);row['observed_at_ns']=row['observed_at_ns'] or time.time_ns();return row


def build_health_report(runtime,orchestrator,audit=None,max_frame_age_s:float=2.0)->dict:
    checks=[];status=runtime.status();session=orchestrator.status();source=session.get('source') or status.get('source_kind');transport_proven=False
    if source=='doip':
        proof=session.get('diagnostic_proof') or {};transport_proven=bool(proof.get('routing_active') and proof.get('uds_exchange'))
        checks.append(HealthCheck('doip_routed_diagnostics','ok' if transport_proven else 'error','routed UDS exchange proven' if transport_proven else 'DoIP routed diagnostic exchange is not proven'))
    elif source=='socketcan':
        active=bool(status.get('connected'));frames=int(status.get('frames_seen') or 0);transport_proven=bool(active and frames>0)
        detail=f'passive SocketCAN receiver active; frames observed: {frames}' if transport_proven else ('passive SocketCAN receiver active but no vehicle frames observed' if active else 'passive SocketCAN receiver inactive')
        checks.append(HealthCheck('socketcan_capture','ok' if transport_proven else 'error',detail))
    elif source=='simulator':
        checks.append(HealthCheck('simulation','ok' if status.get('connected') else 'degraded','software simulator connected' if status.get('connected') else 'simulator stopped',required=False))
    elif source=='replay':
        checks.append(HealthCheck('replay','ok' if status.get('connected') else 'degraded','recording replay active' if status.get('connected') else 'recording replay completed/stopped',required=False))
    else:
        checks.append(HealthCheck('vehicle_connection','degraded','no active vehicle, replay or simulation session',required=False))
    if status.get('connected') and source in ('socketcan','simulator','replay'):
        age=status.get('last_frame_age_s');fresh=age is not None and age<=max_frame_age_s
        checks.append(HealthCheck('frame_freshness','ok' if fresh else 'degraded',f'last frame age {age!r}s',required=False))
        drops=int(status.get('receive_drops') or 0);checks.append(HealthCheck('capture_integrity','ok' if drops==0 else 'degraded',f'receive drops: {drops}',required=False))
        decode_errors=int(status.get('decode_errors') or 0);checks.append(HealthCheck('decoder','ok' if decode_errors==0 else 'degraded',f'decode errors: {decode_errors}',required=False))
    checks.append(HealthCheck('knowledge_store','ok',f"knowledge facts: {session.get('knowledge_facts',0)}",required=False))
    if audit is not None:
        verification=audit.verify();checks.append(HealthCheck('audit_chain','ok' if verification.get('ok') else 'error',f"events checked: {verification.get('events_checked',0)}"))
    rows=[c.as_dict() for c in checks]
    if any(x['status']=='error' and x['required'] for x in rows):overall='error'
    elif any(x['status'] in ('error','degraded') for x in rows):overall='degraded'
    else:overall='ok'
    vehicle_ready=bool(session.get('state')=='ready' and source in ('doip','socketcan') and transport_proven)
    return {'status':overall,'checks':rows,'vehicle_ready':vehicle_ready,'vehicle_transport_proven':transport_proven,'diagnostics_read':bool(session.get('capabilities',{}).get('diagnostics_read')),'source':source,'live_actuation':False}
