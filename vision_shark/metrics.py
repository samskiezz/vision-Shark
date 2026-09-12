from __future__ import annotations

from .health import build_health_report


def _number(value,default=0):
    try:return float(value)
    except (TypeError,ValueError):return float(default)


def prometheus_metrics(runtime,orchestrator,store,audit)->str:
    """Render bounded low-cardinality Prometheus text metrics.

    Vehicle identifiers, VINs, interface names and diagnostic payloads are deliberately
    excluded so this operational endpoint does not become a high-cardinality evidence
    leak. The endpoint is intended for the loopback production deployment.
    """
    rs=runtime.status();vs=orchestrator.status();health=build_health_report(runtime,orchestrator,audit)
    recordings=store.list_recordings();audit_state=audit.verify();proof=vs.get('diagnostic_proof') or {}
    rows=[
        ('vision_gateway_up','Gateway process is serving metrics',1),
        ('vision_vehicle_ready','Evidence-backed physical communication readiness',1 if health.get('vehicle_ready') else 0),
        ('vision_transport_connected','Runtime receive transport is connected',1 if rs.get('connected') else 0),
        ('vision_frames_seen_total','Frames observed by the current runtime session',_number(rs.get('frames_seen'))),
        ('vision_receive_drops_total','Receive drops reported by the active transport',_number(rs.get('receive_drops'))),
        ('vision_decode_errors_total','Decoder errors observed by the active runtime',_number(rs.get('decode_errors'))),
        ('vision_recordings_total','Durable recordings in the local store',len(recordings)),
        ('vision_knowledge_facts','Current persisted vehicle knowledge facts',_number(vs.get('knowledge_facts'))),
        ('vision_doip_uds_exchange_proven','A routed read-only UDS exchange has been proven',1 if proof.get('uds_exchange') else 0),
        ('vision_audit_chain_ok','Local SHA-256 audit chain verifies',1 if audit_state.get('ok') else 0),
        ('vision_audit_events_checked','Audit events checked by the current verification',_number(audit_state.get('events_checked'))),
    ]
    output=[]
    for name,help_text,value in rows:
        output.append(f'# HELP {name} {help_text}')
        output.append(f'# TYPE {name} gauge')
        output.append(f'{name} {value:g}' if isinstance(value,float) else f'{name} {value}')
    return '\n'.join(output)+'\n'
