from __future__ import annotations
from pathlib import Path
from fastapi import FastAPI,HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from . import __version__
from .runtime import Runtime
from .storage import RecordingStore
from .production import ProductionGate
from .transports import list_can_interfaces
from .live_decoder import LiveDecoder
from .orchestrator import VisionOrchestrator
from .middleware import RequestBodyDeadlineMiddleware

class ConnectBody(BaseModel):source:str;interface:str|None=None
class DecoderBody(BaseModel):dbc_text:str;bus:str='can0';freshness_ms:int=500
class AutoConnectBody(BaseModel):simulation:bool=False
class IdentifyBody(BaseModel):settle_s:float=Field(default=.25,ge=0,le=2)
class RecordBody(BaseModel):metadata:dict={}
class ShadowBody(BaseModel):
    vehicle_state:dict
    detections:list[dict]=[]
    imu:dict|None=None;gnss:dict|None=None
    lanes:list[dict]=[];controls:list[dict]=[]
    sensor_age_s:float=Field(default=0,ge=0,le=60)
    model_latency_ms:float=Field(default=0,ge=0,le=10000)
    calibration_valid:bool=True

def create_app(data_dir:Path|str='data'):
    root=Path(data_dir);store=RecordingStore(root);gate=ProductionGate(root)
    app=FastAPI(title='Vision Shark Gateway',version=__version__,docs_url=None,redoc_url=None)
    app.add_middleware(RequestBodyDeadlineMiddleware,max_body_bytes=4*1024*1024,deadline_s=15.0)
    runtime=Runtime(storage=store);app.state.runtime=runtime;app.state.store=store;app.state.orchestrator=VisionOrchestrator(runtime);web=Path(__file__).parent/'web'
    @app.get('/health')
    def health():return {'status':'ok','version':__version__,'mode':gate.PRODUCT_SCOPE,'raw_vehicle_tx':False,'shadow_autonomy':True}
    @app.get('/api/production/readiness')
    def readiness():return gate.evaluate()
    @app.get('/api/interfaces')
    def interfaces():return {'interfaces':list_can_interfaces()}
    @app.get('/api/status')
    def status():return runtime.status()
    @app.get('/api/vision/status')
    def vision_status():return app.state.orchestrator.status()
    @app.post('/api/vision/connect')
    async def vision_connect(body:AutoConnectBody):
        try:return await app.state.orchestrator.connect_auto(body.simulation)
        except (ValueError,RuntimeError,PermissionError,OSError) as e:raise HTTPException(409,str(e)) from e
    @app.post('/api/vision/identify')
    async def vision_identify(body:IdentifyBody):
        try:return await app.state.orchestrator.identify_auto(body.settle_s)
        except ValueError as e:raise HTTPException(409,str(e)) from e
    @app.post('/api/vision/learn')
    async def vision_learn():
        try:return await app.state.orchestrator.learn_auto()
        except ValueError as e:raise HTTPException(409,str(e)) from e
    @app.post('/api/vision/autonomy/shadow')
    def vision_shadow(body:ShadowBody):return app.state.orchestrator.shadow_autonomy(body.model_dump())
    @app.post('/api/connect')
    def connect(body:ConnectBody):
        try:
            if body.source=='simulation':runtime.connect_simulator()
            elif body.source=='socketcan' and body.interface:runtime.connect_socketcan(body.interface)
            else:raise HTTPException(400,'Select simulation or a passive SocketCAN interface')
        except (ValueError,RuntimeError,PermissionError,OSError) as e:raise HTTPException(409,str(e)) from e
        return runtime.status()
    @app.post('/api/disconnect')
    def disconnect():runtime.disconnect();return runtime.status()
    @app.post('/api/recordings/start')
    def start_recording(body:RecordBody):
        try:return {'recording_id':runtime.start_recording(body.metadata)}
        except RuntimeError as e:raise HTTPException(409,str(e)) from e
    @app.post('/api/recordings/stop')
    def stop_recording():return {'recording_id':runtime.stop_recording()}
    @app.get('/api/recordings')
    def recordings():return {'recordings':store.list_recordings()}
    @app.get('/api/recordings/{recording_id}/frames')
    def recording_frames(recording_id:int):return {'frames':[f.__dict__ for f in store.load_frames(recording_id)]}
    @app.post('/api/decoder')
    def decoder(body:DecoderBody):runtime.configure_decoder(LiveDecoder.from_text(body.dbc_text,body.bus,body.freshness_ms));return {'attached':True,'provenance':runtime.decoder.provenance()}
    @app.delete('/api/decoder')
    def remove_decoder():runtime.configure_decoder(None);return {'attached':False}
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
