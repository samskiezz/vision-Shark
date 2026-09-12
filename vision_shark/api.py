from __future__ import annotations
from pathlib import Path
from fastapi import FastAPI,HTTPException
from fastapi.responses import FileResponse,PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from . import __version__
from .runtime import Runtime
from .storage import RecordingStore
from .production import ProductionGate
from .transports import list_can_interfaces
from .adapter_discovery import discover_adapters
from .live_decoder import LiveDecoder
from .orchestrator import VisionOrchestrator
from .middleware import RequestBodyDeadlineMiddleware
from .audit_log import EventAuditLog
from .openclaw import OpenClawBridge,EmergencyObservation,EmergencyOrchestrator
from .health import build_health_report
from .fingerprint import fingerprint_frames
from .interchange import load_frames,dump_frames
from .isotp_passive import PassiveIsoTpAssembler

class ConnectBody(BaseModel):source:str;interface:str|None=None
class DecoderBody(BaseModel):dbc_text:str;bus:str='can0';freshness_ms:int=500
class AutoConnectBody(BaseModel):simulation:bool=False
class IdentifyBody(BaseModel):settle_s:float=Field(default=.25,ge=0,le=2)
class RecordBody(BaseModel):metadata:dict=Field(default_factory=dict)
class ReplayBody(BaseModel):speed:float=Field(default=1.0,gt=0,le=100)
class DiagnosticDidsBody(BaseModel):dids:list[int]=Field(min_length=1,max_length=16)
class DiagnosticDtcBody(BaseModel):status_mask:int=Field(default=0xff,ge=0,le=255)
class ImportCaptureBody(BaseModel):format:str=Field(min_length=1,max_length=16);content:str=Field(max_length=4*1024*1024);metadata:dict=Field(default_factory=dict)
class OpenClawReadBody(BaseModel):name:str=Field(min_length=1,max_length=64)
class OpenClawActionBody(BaseModel):action:str=Field(min_length=1,max_length=64);arguments:dict=Field(default_factory=dict);emergency:bool=False
class EmergencyBody(BaseModel):
    driver_responsive:bool|None=None
    medical_alarm:bool=False;crash_detected:bool=False;severe_driver_monitoring_alarm:bool=False;user_requested_help:bool=False;location_available:bool=False
class ShadowBody(BaseModel):
    vehicle_state:dict
    detections:list[dict]=Field(default_factory=list)
    imu:dict|None=None;gnss:dict|None=None
    lanes:list[dict]=Field(default_factory=list);controls:list[dict]=Field(default_factory=list)
    sensor_age_s:float=Field(default=0,ge=0,le=60)
    model_latency_ms:float=Field(default=0,ge=0,le=10000)
    calibration_valid:bool=True

def create_app(data_dir:Path|str='data'):
    root=Path(data_dir);store=RecordingStore(root);gate=ProductionGate(root);audit=EventAuditLog(root)
    app=FastAPI(title='Vision Shark Gateway',version=__version__,docs_url=None,redoc_url=None)
    app.add_middleware(RequestBodyDeadlineMiddleware,max_body_bytes=4*1024*1024,deadline_s=15.0)
    runtime=Runtime(storage=store);orchestrator=VisionOrchestrator(runtime,audit=audit)
    openclaw=OpenClawBridge(readers={
        'vision_status':orchestrator.status,
        'production_readiness':gate.evaluate,
        'recordings':store.list_recordings,
        'knowledge':orchestrator.knowledge.snapshot,
    })
    emergency=EmergencyOrchestrator()
    app.state.runtime=runtime;app.state.store=store;app.state.audit=audit;app.state.orchestrator=orchestrator;app.state.openclaw=openclaw;app.state.emergency=emergency;web=Path(__file__).parent/'web'
    @app.get('/health')
    def health():return {'status':'ok','version':__version__,'mode':gate.PRODUCT_SCOPE,'raw_vehicle_tx':False,'shadow_autonomy':True,'doip_discovery':True,'openclaw_orchestration':True}
    @app.get('/api/system/health')
    def system_health():return build_health_report(runtime,orchestrator,audit)
    @app.get('/api/production/readiness')
    def readiness():return gate.evaluate()
    @app.get('/api/interfaces')
    def interfaces():return {'interfaces':list_can_interfaces()}
    @app.get('/api/adapters')
    def adapters():return {'adapters':discover_adapters(True,True)}
    @app.get('/api/status')
    def status():return runtime.status()
    @app.get('/api/vision/status')
    def vision_status():return orchestrator.status()
    @app.post('/api/vision/connect')
    async def vision_connect(body:AutoConnectBody):
        try:return await orchestrator.connect_auto(body.simulation)
        except (ValueError,RuntimeError,PermissionError,OSError) as e:raise HTTPException(409,str(e)) from e
    @app.post('/api/vision/identify')
    async def vision_identify(body:IdentifyBody):
        try:return await orchestrator.identify_auto(body.settle_s)
        except ValueError as e:raise HTTPException(409,str(e)) from e
    @app.post('/api/vision/learn')
    async def vision_learn():
        try:return await orchestrator.learn_auto()
        except ValueError as e:raise HTTPException(409,str(e)) from e
    @app.post('/api/vision/autonomy/shadow')
    def vision_shadow(body:ShadowBody):return orchestrator.shadow_autonomy(body.model_dump())
    @app.post('/api/diagnostics/doip/dids')
    async def doip_dids(body:DiagnosticDidsBody):
        try:return await orchestrator.read_doip_dids(body.dids)
        except (ValueError,RuntimeError,PermissionError,OSError) as e:raise HTTPException(409,str(e)) from e
    @app.post('/api/diagnostics/doip/dtcs')
    async def doip_dtcs(body:DiagnosticDtcBody):
        try:return await orchestrator.read_doip_dtcs(body.status_mask)
        except (ValueError,RuntimeError,PermissionError,OSError) as e:raise HTTPException(409,str(e)) from e
    @app.get('/api/openclaw/capabilities')
    def openclaw_capabilities():return openclaw.capabilities()
    @app.post('/api/openclaw/read')
    def openclaw_read(body:OpenClawReadBody):
        try:result=openclaw.read(body.name)
        except PermissionError as e:
            audit.append('openclaw','read_denied',{'name':body.name});raise HTTPException(403,str(e)) from e
        audit.append('openclaw','read',{'name':body.name});return {'name':body.name,'result':result}
    @app.post('/api/openclaw/action')
    def openclaw_action(body:OpenClawActionBody):
        try:result=openclaw.execute(body.action,body.arguments,body.emergency)
        except PermissionError as e:
            audit.append('openclaw','action_denied',{'action':body.action,'emergency':body.emergency});raise HTTPException(403,str(e)) from e
        audit.append('openclaw','action',{'action':body.action,'emergency':body.emergency,'status':result.get('status'),'decision':result.get('decision')});return result
    @app.post('/api/openclaw/emergency/evaluate')
    def openclaw_emergency(body:EmergencyBody):
        result=emergency.evaluate(EmergencyObservation(**body.model_dump()));audit.append('openclaw','emergency_evaluated',{'observation':body.model_dump(),'state':result['state'],'actions':[x['action'] for x in result['actions']]});return result
    @app.get('/api/audit')
    def audit_events(limit:int=100):return {'events':audit.list(limit)}
    @app.get('/api/audit/verify')
    def audit_verify():return audit.verify()
    @app.post('/api/connect')
    def connect(body:ConnectBody):
        try:
            if body.source=='simulation':runtime.connect_simulator()
            elif body.source=='socketcan' and body.interface:runtime.connect_socketcan(body.interface)
            else:raise HTTPException(400,'Select simulation or a passive SocketCAN interface; use /api/vision/connect for automatic ENET/DoIP discovery')
        except (ValueError,RuntimeError,PermissionError,OSError) as e:raise HTTPException(409,str(e)) from e
        return runtime.status()
    @app.post('/api/disconnect')
    def disconnect():runtime.disconnect();audit.append('vehicle','disconnected');return runtime.status()
    @app.post('/api/recordings/start')
    def start_recording(body:RecordBody):
        try:recording_id=runtime.start_recording(body.metadata);audit.append('recording','started',{'recording_id':recording_id});return {'recording_id':recording_id}
        except RuntimeError as e:raise HTTPException(409,str(e)) from e
    @app.post('/api/recordings/stop')
    def stop_recording():
        recording_id=runtime.stop_recording();audit.append('recording','stopped',{'recording_id':recording_id});return {'recording_id':recording_id}
    @app.get('/api/recordings')
    def recordings():return {'recordings':store.list_recordings()}
    @app.get('/api/recordings/{recording_id}/frames')
    def recording_frames(recording_id:int):return {'frames':[f.model_dump(mode='json') for f in store.load_frames(recording_id)]}
    @app.post('/api/recordings/{recording_id}/replay')
    def recording_replay(recording_id:int,body:ReplayBody):
        frames=store.load_frames(recording_id)
        if not frames:raise HTTPException(409,'recording has no frames')
        runtime.connect_replay(frames,body.speed,recording_id);audit.append('replay','started',{'recording_id':recording_id,'speed':body.speed,'frames':len(frames)});return runtime.status()
    @app.get('/api/recordings/{recording_id}/fingerprint')
    def recording_fingerprint(recording_id:int):return fingerprint_frames(store.load_frames(recording_id))
    @app.get('/api/recordings/{recording_id}/isotp')
    def recording_isotp(recording_id:int):
        assembler=PassiveIsoTpAssembler();messages=[];frames=store.load_frames(recording_id)
        for frame in frames:messages.extend(x.as_dict() for x in assembler.consume(frame))
        if frames:messages.extend(x.as_dict() for x in assembler.expire(frames[-1].ts_ns+assembler.max_gap_ns+1))
        return {'messages':messages}
    @app.get('/api/recordings/{recording_id}/export')
    def recording_export(recording_id:int,format:str='candump'):
        try:content=dump_frames(store.load_frames(recording_id),format)
        except ValueError as e:raise HTTPException(400,str(e)) from e
        media='text/csv' if format.lower().lstrip('.')=='csv' else 'text/plain';return PlainTextResponse(content,media_type=media)
    @app.post('/api/interchange/import')
    def interchange_import(body:ImportCaptureBody):
        try:frames=load_frames(body.content,body.format)
        except ValueError as e:raise HTTPException(400,str(e)) from e
        rid=store.start_recording('import',body.format,{**body.metadata,'import_format':body.format,'frame_count_expected':len(frames)})
        try:
            for frame in frames:store.append_frame(rid,frame)
            store.stop_recording(rid,{'capture_complete':True,'imported':True})
        except Exception:
            store.stop_recording(rid,{'capture_complete':False,'imported':True});raise
        audit.append('interchange','capture_imported',{'recording_id':rid,'format':body.format,'frames':len(frames)});return {'recording_id':rid,'frames':len(frames)}
    @app.post('/api/decoder')
    def decoder(body:DecoderBody):runtime.configure_decoder(LiveDecoder.from_text(body.dbc_text,body.bus,body.freshness_ms));audit.append('decoder','configured',{'bus':body.bus});return {'attached':True,'provenance':runtime.decoder.provenance()}
    @app.delete('/api/decoder')
    def remove_decoder():runtime.configure_decoder(None);audit.append('decoder','removed');return {'attached':False}
    @app.get('/api/frames')
    def frames():return {'frames':runtime.recent_frames()}
    @app.api_route('/api/import/repository',methods=['GET','POST'])
    @app.api_route('/api/repositories/fetch',methods=['GET','POST'])
    def retired_repository_import():raise HTTPException(410,'Runtime repository fetching was removed; import reviewed local data artifacts instead')
    @app.post('/api/transmit')
    def deny_transmit():raise HTTPException(403,'Raw vehicle transmit, live driving control and firmware flashing are not exposed')
    if web.exists():
        @app.get('/')
        def index():return FileResponse(web/'index.html')
        app.mount('/static',StaticFiles(directory=web),name='static')
    return app
