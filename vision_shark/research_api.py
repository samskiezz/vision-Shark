from __future__ import annotations

import os
from fastapi import HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel,Field

from .adapter_discovery import discover_adapters
from .agent_policy import evaluate_emergency,evaluate_policy
from .anomaly import compare_anomaly
from .ecu_fingerprint import ecu_clock_hypotheses
from .event_diff import event_bit_diff
from .field_api import install_field_routes
from .metrics import prometheus_metrics
from .platform_match import match_platforms
from .segmentation import segment_recording
from .sniffer import sniffer_view
from .trace_import import load_trace
from .tuning_api import install_tuning_routes
from .uds_reference import reference as uds_reference

class EventDiffBody(BaseModel):
    events:list[dict]=Field(default_factory=list,max_length=1000)
    window_ms:float=Field(default=500.0,gt=0,le=60_000)
class TraceImportBody(BaseModel):
    format:str=Field(min_length=1,max_length=8);content:str=Field(max_length=8*1024*1024);metadata:dict=Field(default_factory=dict)
class DiscoveryBody(BaseModel):
    include_doip:bool=False;include_j2534:bool=True
class DoIPConnectBody(BaseModel):
    endpoint:str=Field(min_length=1,max_length=255);logical_address:int=Field(ge=0,le=65535);interface:str='ethernet';discovery_vin:str|None=Field(default=None,max_length=32);eid:str|None=Field(default=None,max_length=64);metadata:dict=Field(default_factory=dict)
class PlatformMatchBody(BaseModel):
    profiles:list[dict]=Field(default_factory=list,max_length=256)
class AgentPolicyBody(BaseModel):
    action:str=Field(min_length=1,max_length=64);domain:str=Field(default='',max_length=64);emergency:bool=False
class AgentEmergencyBody(BaseModel):
    driver_responsive:bool|None=None;medical_alarm:bool=False;crash_detected:bool=False;severe_driver_monitoring_alarm:bool=False;user_requested_help:bool=False;location_available:bool=False


def install_research_routes(app,runtime,store,audit,orchestrator):
    @app.get('/metrics',response_class=PlainTextResponse)
    def metrics():return PlainTextResponse(prometheus_metrics(runtime,orchestrator,store,audit),media_type='text/plain; version=0.0.4; charset=utf-8')

    @app.get('/api/sniffer')
    def sniffer(changed_only:bool=False,changed_within_ms:float=1000.0):
        try:return sniffer_view(list(runtime.recent),changed_only,changed_within_ms)
        except ValueError as exc:raise HTTPException(400,str(exc)) from exc

    @app.post('/api/recordings/{recording_id}/event-diff')
    def recording_event_diff(recording_id:int,body:EventDiffBody):return event_bit_diff(store.load_frames(recording_id),body.events,body.window_ms)

    @app.get('/api/recordings/{recording_id}/ecu-clusters')
    def recording_ecu_clusters(recording_id:int,tolerance_ppm:float=250.0):
        try:return ecu_clock_hypotheses(store.load_frames(recording_id),tolerance_ppm)
        except ValueError as exc:raise HTTPException(400,str(exc)) from exc

    @app.get('/api/recordings/{recording_id}/anomalies')
    def recording_anomalies(recording_id:int,baseline_id:int):return compare_anomaly(store.load_frames(baseline_id),store.load_frames(recording_id))

    @app.post('/api/recordings/{recording_id}/platform-match')
    def recording_platform_match(recording_id:int,body:PlatformMatchBody):return match_platforms(store.load_frames(recording_id),body.profiles)

    @app.get('/api/recordings/{recording_id}/segments')
    def recording_segments(recording_id:int):
        if runtime.decoder is None:raise HTTPException(409,'Attach a reviewed decoder before requesting drive/charge segmentation')
        return segment_recording(store.load_frames(recording_id),runtime.decoder.database)

    @app.get('/api/reference/uds')
    def reference_uds():return uds_reference()

    @app.post('/api/agent/policy/evaluate')
    def agent_policy_evaluate(body:AgentPolicyBody):return evaluate_policy(body.action,body.domain,body.emergency)

    @app.post('/api/agent/policy/emergency')
    def agent_policy_emergency(body:AgentEmergencyBody):return evaluate_emergency(body.model_dump())

    @app.post('/api/import/trace')
    def import_trace(body:TraceImportBody):
        try:frames=load_trace(body.content,body.format)
        except ValueError as exc:raise HTTPException(400,str(exc)) from exc
        rid=store.start_recording('import',body.format,{**body.metadata,'import_format':body.format,'frame_count_expected':len(frames)})
        try:store.append_frames(rid,frames);store.stop_recording(rid,{'capture_complete':True,'imported':True})
        except Exception:store.stop_recording(rid,{'capture_complete':False,'imported':True});raise
        audit.append('interchange','trace_imported',{'recording_id':rid,'format':body.format,'frames':len(frames)});return {'recording_id':rid,'frames':len(frames),'format':body.format}

    @app.post('/api/discovery/adapters')
    def explicit_discovery(body:DiscoveryBody):
        allow=os.getenv('VISION_ALLOW_DOIP_DISCOVERY','').strip().lower() in {'1','true','yes','on'}
        if body.include_doip and not allow:raise HTTPException(403,'DoIP broadcast discovery is disabled; set VISION_ALLOW_DOIP_DISCOVERY=1 to explicitly enable it')
        result=discover_adapters(include_doip=body.include_doip,include_j2534=body.include_j2534)
        audit.append('discovery','adapter_discovery',{'include_doip':body.include_doip,'include_j2534':body.include_j2534,'transmitted':bool(body.include_doip),'results':len(result)})
        return {'adapters':result,'doip_broadcast_transmitted':bool(body.include_doip),'identity_evidence':False}

    @app.post('/api/vision/connect-doip')
    async def explicit_doip_connect(body:DoIPConnectBody):
        try:return await orchestrator.connect_doip_endpoint(body.endpoint,body.logical_address,body.interface,body.discovery_vin,body.eid,body.metadata)
        except (ValueError,RuntimeError,PermissionError,OSError) as exc:raise HTTPException(409,str(exc)) from exc

    install_field_routes(app,store,audit)
    install_tuning_routes(app,audit)
