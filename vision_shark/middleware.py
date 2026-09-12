from __future__ import annotations
import asyncio,time
from starlette.responses import JSONResponse

class RequestBodyDeadlineMiddleware:
    """Bound request-body duration and bytes independently of Content-Length."""
    def __init__(self,app,max_body_bytes=4*1024*1024,deadline_s=15.0):self.app=app;self.max_body_bytes=int(max_body_bytes);self.deadline_s=float(deadline_s)
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        started=time.monotonic();seen=0
        async def bounded_receive():
            nonlocal seen
            remaining=self.deadline_s-(time.monotonic()-started)
            if remaining<=0:raise asyncio.TimeoutError
            msg=await asyncio.wait_for(receive(),timeout=remaining)
            if msg['type']=='http.request':
                seen+=len(msg.get('body',b''))
                if seen>self.max_body_bytes:raise OverflowError
            return msg
        try:return await self.app(scope,bounded_receive,send)
        except asyncio.TimeoutError:
            return await JSONResponse({'detail':'Request body deadline exceeded'},status_code=408)(scope,receive,send)
        except OverflowError:
            return await JSONResponse({'detail':'Request body too large'},status_code=413)(scope,receive,send)
