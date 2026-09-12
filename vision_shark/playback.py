from __future__ import annotations

import time
from .domain import Frame

class ReplaySource:
    """Receive-only deterministic playback source for recorded frames."""
    def __init__(self,frames:list[Frame],speed:float=1.0):
        speed=float(speed)
        if speed<=0 or speed>100:raise ValueError('replay speed must be >0 and <=100')
        self.frames=list(frames);self.speed=speed;self.index=0;self.start_mono_ns=0;self.first_ts_ns=self.frames[0].ts_ns if self.frames else 0;self.eof=False;self.dropped=0
    def open(self):self.index=0;self.start_mono_ns=time.monotonic_ns();self.eof=not bool(self.frames)
    def read(self,timeout=.25):
        if self.eof:return None
        src=self.frames[self.index];due=self.start_mono_ns+int((src.ts_ns-self.first_ts_ns)/self.speed);now=time.monotonic_ns()
        if due>now:
            wait=(due-now)/1e9
            if wait>timeout:
                time.sleep(max(0,float(timeout)));return None
            time.sleep(max(0,wait))
        out=src.model_copy(update={'ts_ns':max(0,due),'bus':src.bus})
        self.index+=1
        if self.index>=len(self.frames):self.eof=True
        return out
    def close(self):self.eof=True
