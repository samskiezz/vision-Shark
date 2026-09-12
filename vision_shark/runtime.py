from __future__ import annotations
import threading,time
from collections import deque
from dataclasses import asdict
from typing import Any
from .domain import Frame
from .live_decoder import LiveDecoder
from .transports import SimulatorSource,SocketCANSource
from .playback import ReplaySource

class Runtime:
    def __init__(self,storage:Any,max_recent:int=2000):
        self.storage=storage;self.max_recent=max_recent;self.recent:deque[Frame]=deque(maxlen=max_recent);self.signals={};self.source=None;self.source_kind=None;self.interface=None;self.decoder=None;self.recording_id=None;self.running=False;self._thread=None;self._lock=threading.RLock();self.last_frame_monotonic=None;self.frames_seen=0;self.decode_errors=0;self.last_error=None;self.receive_drops=0
    def configure_decoder(self,decoder:LiveDecoder|None):
        with self._lock:
            if self.recording_id is not None:raise RuntimeError('decoder configuration cannot change during a recording')
            self.decoder=decoder;self.signals.clear()
    def connect_simulator(self,seed:int=1):self._connect(SimulatorSource(seed=seed),'simulator','simulator')
    def connect_socketcan(self,interface:str):self._connect(SocketCANSource(interface),'socketcan',interface)
    def connect_replay(self,frames:list[Frame],speed:float=1.0,recording_id:int|None=None):self._connect(ReplaySource(frames,speed),'replay',f'recording:{recording_id}' if recording_id is not None else 'memory')
    def _connect(self,source,kind,interface):
        self.disconnect();source.open()
        with self._lock:
            self.recent.clear();self.frames_seen=0;self.source=source;self.source_kind=kind;self.interface=interface;self.running=True;self.last_error=None;self.last_frame_monotonic=None;self.receive_drops=int(getattr(source,'dropped',0));self._thread=threading.Thread(target=self._loop,name='vision-shark-rx',daemon=True);self._thread.start()
    def start_recording(self,metadata:dict|None=None)->int:
        with self._lock:
            if not self.running:raise RuntimeError('connect before recording')
            if self.source_kind=='replay':raise RuntimeError('recording a replay is disabled; export or copy the source recording instead')
            if self.storage is None:raise RuntimeError('durable storage is unavailable')
            if self.recording_id is not None:raise RuntimeError('recording already active')
            meta=dict(metadata or {});meta['receive_drops_at_start']=self.receive_drops;meta['timestamp_domain']='monotonic';self.recording_id=self.storage.start_recording(self.source_kind,self.interface,meta);return self.recording_id
    def stop_recording(self):
        with self._lock:rid=self.recording_id;self.recording_id=None;drops=self.receive_drops
        if rid is not None and self.storage is not None:self.storage.stop_recording(rid,{'receive_drops_at_stop':drops,'capture_complete':drops==0})
        return rid
    def disconnect(self):
        self.stop_recording()
        with self._lock:self.running=False;source,thread=self.source,self._thread;self.source=None;self._thread=None
        if source is not None:
            try:source.close()
            except OSError as exc:self.last_error=f'source close failed: {exc}'
        if thread and thread is not threading.current_thread():thread.join(timeout=2.)
        with self._lock:self.source_kind=None;self.interface=None;self.signals.clear()
    def _loop(self):
        while self.running:
            source=self.source
            if source is None:return
            try:frame=source.read(timeout=.25);self.receive_drops=int(getattr(source,'dropped',self.receive_drops))
            except Exception as exc:
                with self._lock:self.last_error=f'receive failed: {type(exc).__name__}: {exc}';self.running=False
                return
            if frame is not None:self.ingest(frame)
            elif getattr(source,'eof',False):
                with self._lock:self.running=False
                return
    def ingest(self,frame:Frame):
        with self._lock:
            self.frames_seen+=1;self.last_frame_monotonic=time.monotonic();self.recent.append(frame)
            if self.recording_id is not None and self.storage is not None:self.storage.append_frame(self.recording_id,frame)
            if self.decoder is not None:
                try:
                    decoded=self.decoder.decode(frame)
                    if decoded:self.signals.update(decoded)
                except Exception as exc:self.decode_errors+=1;self.last_error=f'decode failed: {type(exc).__name__}: {exc}'
    def status(self):
        with self._lock:
            age=None if self.last_frame_monotonic is None else max(0.,time.monotonic()-self.last_frame_monotonic)
            return {'connected':bool(self.running and self.source is not None),'source_kind':self.source_kind,'interface':self.interface,'frames_seen':self.frames_seen,'last_frame_age_s':age,'signals':dict(self.signals),'decode_errors':self.decode_errors,'recording_id':self.recording_id,'simulated':self.source_kind=='simulator','last_error':self.last_error,'receive_drops':self.receive_drops,'capture_complete_so_far':self.receive_drops==0,'timestamp_domain':'monotonic'}
    def recent_frames(self):
        with self._lock:return [asdict(f) for f in self.recent]
