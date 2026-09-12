from __future__ import annotations
from pathlib import Path
from fastapi import FastAPI,HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import __version__
from .runtime import Runtime
from .transports import list_can_interfaces
from .live_decoder import LiveDecoder

class ConnectBody(BaseModel):source:str;interface:str|None=None
class DecoderBody(BaseModel):dbc_text:str;bus:str='can0';freshness_ms:int=500

def create_app(data_dir:Path|str='data'):
    app=FastAPI(title='Vision Shark Gateway',version=__version__,docs_url=None,redoc_url=None)
    runtime=Runtime(storage=None);app.state.runtime=runtime;web=Path(__file__).parent/'web'
    @app.get('/health')
    def health():return {'status':'ok','version':__version__,'raw_vehicle_tx':False}
    @app.get('/api/interfaces')
    def interfaces():return {'interfaces':list_can_interfaces()}
    @app.get('/api/status')
    def status():return runtime.status()
    @app.post('/api/connect')
    def connect(body:ConnectBody):
        if body.source=='simulation':runtime.connect_simulator()
        elif body.source=='socketcan' and body.interface:runtime.connect_socketcan(body.interface)
        else:raise HTTPException(400,'Select simulation or a passive SocketCAN interface')
        return runtime.status()
    @app.post('/api/disconnect')
    def disconnect():runtime.disconnect();return runtime.status()
    @app.post('/api/decoder')
    def decoder(body:DecoderBody):runtime.configure_decoder(LiveDecoder.from_text(body.dbc_text,body.bus,body.freshness_ms));return {'attached':True,'provenance':runtime.decoder.provenance()}
    @app.delete('/api/decoder')
    def remove_decoder():runtime.configure_decoder(None);return {'attached':False}
    @app.get('/api/frames')
    def frames():return {'frames':runtime.recent_frames()}
    @app.post('/api/transmit')
    def deny_transmit():raise HTTPException(403,'Raw vehicle transmit, driving control and firmware flashing are not exposed by this observation build')
    if web.exists():
        @app.get('/')
        def index():return FileResponse(web/'index.html')
        app.mount('/static',StaticFiles(directory=web),name='static')
    return app
