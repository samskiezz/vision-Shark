from __future__ import annotations
import asyncio,time
from starlette.responses import JSONResponse
class RequestBodyDeadlineMiddleware:
 def __init__(self,app,max_body_bytes=4*1024*1024,deadline_s=15.):self.app=app;self.max_body_bytes=int(max_body_bytes);self.deadline_s=float(deadline_s)
 async def __call__(self,scope,receive,send):
  if scope['type']!='http':return await self.app(scope,receive,send)
  headers={k.lower():v for k,v in scope.get('headers',[])};declared=headers.get(b'content-length')
  if declared:
   try:
    if int(declared)>self.max_body_bytes:return await JSONResponse({'detail':'Request body too large'},status_code=413)(scope,receive,send)
   except ValueError:return await JSONResponse({'detail':'Invalid Content-Length'},status_code=400)(scope,receive,send)
  started=time.monotonic();seen=0;messages=[];more=True
  try:
   while more:
    remaining=self.deadline_s-(time.monotonic()-started)
    if remaining<=0:raise asyncio.TimeoutError
    msg=await asyncio.wait_for(receive(),timeout=remaining);messages.append(msg)
    if msg['type']=='http.disconnect':break
    if msg['type']=='http.request':
     seen+=len(msg.get('body',b''))
     if seen>self.max_body_bytes:raise OverflowError
     more=bool(msg.get('more_body',False))
    else:more=False
  except asyncio.TimeoutError:return await JSONResponse({'detail':'Request body deadline exceeded'},status_code=408)(scope,receive,send)
  except OverflowError:return await JSONResponse({'detail':'Request body too large'},status_code=413)(scope,receive,send)
  index=0
  async def replay_receive():
   nonlocal index
   if index<len(messages):msg=messages[index];index+=1;return msg
   return {'type':'http.request','body':b'','more_body':False}
  return await self.app(scope,replay_receive,send)
