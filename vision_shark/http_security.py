from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass

from starlette.responses import JSONResponse

_MUTATING={'POST','PUT','PATCH','DELETE'}
_PUBLIC_PREFIXES=('/static/',)
_PUBLIC_EXACT={'/','/health','/api/auth/login','/api/auth/session'}

@dataclass(frozen=True)
class Session:
    session_id:str
    csrf_token:str
    role:str
    created_ns:int
    expires_ns:int

class SecurityManager:
    """In-memory local gateway sessions backed by operator-provided bearer secrets."""
    def __init__(self,admin_token:str,viewer_token:str|None=None,audit=None,ttl_s:int=43_200):
        if not admin_token or len(admin_token)<16:raise ValueError('admin token must be at least 16 characters')
        if viewer_token is not None and len(viewer_token)<16:raise ValueError('viewer token must be at least 16 characters')
        self._admin_digest=self._digest(admin_token);self._viewer_digest=None if viewer_token is None else self._digest(viewer_token)
        self.audit=audit;self.ttl_ns=int(ttl_s)*1_000_000_000;self._sessions={};self._idempotency={};self._lock=threading.RLock()
    @staticmethod
    def _digest(value:str)->bytes:return hashlib.sha256(value.encode('utf-8')).digest()
    def _audit(self,event,payload=None):
        if self.audit:self.audit.append('security',event,payload or {})
    def login(self,token:str)->Session|None:
        digest=self._digest(str(token));role=None
        if hmac.compare_digest(digest,self._admin_digest):role='admin'
        elif self._viewer_digest is not None and hmac.compare_digest(digest,self._viewer_digest):role='viewer'
        if role is None:self._audit('login_denied');return None
        now=time.time_ns();session=Session(secrets.token_urlsafe(32),secrets.token_urlsafe(32),role,now,now+self.ttl_ns)
        with self._lock:self._sessions[session.session_id]=session
        self._audit('login_success',{'role':role});return session
    def get(self,session_id:str|None)->Session|None:
        if not session_id:return None
        now=time.time_ns()
        with self._lock:
            session=self._sessions.get(session_id)
            if session is None:return None
            if session.expires_ns<=now:
                self._sessions.pop(session_id,None);self._audit('session_expired',{'role':session.role});return None
            return session
    def logout(self,session_id:str|None):
        if not session_id:return
        with self._lock:
            session=self._sessions.pop(session_id,None)
            for key in [k for k in self._idempotency if k[0]==session_id]:self._idempotency.pop(key,None)
        if session:self._audit('logout',{'role':session.role})
    def idempotency_reserve(self,session_id:str,key:str,request_hash:str):
        now=time.time_ns();cache_key=(session_id,key)
        with self._lock:
            for stale,row in list(self._idempotency.items()):
                if row['expires_ns']<=now:self._idempotency.pop(stale,None)
            row=self._idempotency.get(cache_key)
            if row is not None:
                if row['request_hash']!=request_hash:raise ValueError('Idempotency-Key reused with a different request')
                if row.get('pending'):raise RuntimeError('Request with this Idempotency-Key is already in progress or its outcome is uncertain')
                return row
            self._idempotency[cache_key]={'request_hash':request_hash,'pending':True,'expires_ns':now+15*60*1_000_000_000}
            while len(self._idempotency)>2048:self._idempotency.pop(next(iter(self._idempotency)))
            return None
    def idempotency_complete(self,session_id:str,key:str,request_hash:str,status:int,headers:list[tuple[bytes,bytes]],body:bytes):
        if len(body)>2*1024*1024:return
        safe_headers=[(k,v) for k,v in headers if k.lower() not in {b'set-cookie',b'content-length',b'transfer-encoding'}]
        with self._lock:self._idempotency[(session_id,key)]={'request_hash':request_hash,'pending':False,'status':int(status),'headers':safe_headers,'body':bytes(body),'expires_ns':time.time_ns()+15*60*1_000_000_000}

class SecurityMiddleware:
    def __init__(self,app,manager:SecurityManager,cookie_name:str='vision_session',max_body_bytes:int=8*1024*1024,deadline_s:float=15.0):
        self.app=app;self.manager=manager;self.cookie_name=cookie_name;self.max_body_bytes=int(max_body_bytes);self.deadline_s=float(deadline_s)
    @staticmethod
    def _headers(scope):return {k.lower():v for k,v in scope.get('headers',[])}
    def _cookie(self,headers):
        raw=headers.get(b'cookie',b'').decode('latin1','ignore')
        for item in raw.split(';'):
            name,sep,value=item.strip().partition('=')
            if sep and name==self.cookie_name:return value
        return None
    async def _body(self,receive):
        chunks=[];seen=0;started=time.monotonic();more=True
        while more:
            remaining=self.deadline_s-(time.monotonic()-started)
            if remaining<=0:raise TimeoutError
            msg=await asyncio.wait_for(receive(),timeout=remaining)
            if msg['type']=='http.disconnect':break
            if msg['type']=='http.request':
                chunk=msg.get('body',b'');seen+=len(chunk)
                if seen>self.max_body_bytes:raise OverflowError
                chunks.append(chunk);more=bool(msg.get('more_body',False))
            else:more=False
        return b''.join(chunks)
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        path=scope.get('path','');method=scope.get('method','GET').upper();headers=self._headers(scope)
        public=path in _PUBLIC_EXACT or any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES)
        session=self.manager.get(self._cookie(headers))
        if public:return await self.app(scope,receive,send)
        if session is None:
            self.manager._audit('authentication_required',{'path':path,'method':method});return await JSONResponse({'detail':'Authentication required'},status_code=401)(scope,receive,send)
        if method in _MUTATING:
            if session.role!='admin':
                self.manager._audit('role_denied',{'path':path,'method':method,'role':session.role});return await JSONResponse({'detail':'Admin role required'},status_code=403)(scope,receive,send)
            csrf=headers.get(b'x-csrf-token',b'').decode('utf-8','ignore')
            if not csrf or not hmac.compare_digest(csrf,session.csrf_token):
                self.manager._audit('csrf_denied',{'path':path,'method':method,'role':session.role});return await JSONResponse({'detail':'Valid X-CSRF-Token required'},status_code=403)(scope,receive,send)
        if method not in _MUTATING or path=='/api/auth/logout':return await self.app(scope,receive,send)
        idem=headers.get(b'idempotency-key',b'').decode('utf-8','ignore').strip()
        if not idem or len(idem)>128:return await JSONResponse({'detail':'Idempotency-Key required for state-changing requests'},status_code=428)(scope,receive,send)
        declared=headers.get(b'content-length')
        if declared:
            try:
                if int(declared)>self.max_body_bytes:return await JSONResponse({'detail':'Request body too large'},status_code=413)(scope,receive,send)
            except ValueError:return await JSONResponse({'detail':'Invalid Content-Length'},status_code=400)(scope,receive,send)
        try:body=await self._body(receive)
        except TimeoutError:return await JSONResponse({'detail':'Request body deadline exceeded'},status_code=408)(scope,receive,send)
        except OverflowError:return await JSONResponse({'detail':'Request body too large'},status_code=413)(scope,receive,send)
        query=scope.get('query_string',b'');request_hash=hashlib.sha256(method.encode()+b'\0'+path.encode()+b'\0'+query+b'\0'+body).hexdigest()
        try:cached=self.manager.idempotency_reserve(session.session_id,idem,request_hash)
        except (ValueError,RuntimeError) as exc:return await JSONResponse({'detail':str(exc)},status_code=409)(scope,receive,send)
        if cached is not None:
            self.manager._audit('idempotent_replay',{'path':path,'method':method,'role':session.role});return await self._send_cached(cached,send)
        sent_start=None;body_parts=[]
        async def replay_receive():return {'type':'http.request','body':body,'more_body':False}
        async def capture_send(message):
            nonlocal sent_start
            if message['type']=='http.response.start':sent_start=message
            elif message['type']=='http.response.body':body_parts.append(message.get('body',b''))
            await send(message)
        try:await self.app(scope,replay_receive,capture_send)
        except Exception:
            self.manager._audit('mutation_outcome_uncertain',{'path':path,'method':method,'role':session.role});raise
        if sent_start is not None:self.manager.idempotency_complete(session.session_id,idem,request_hash,sent_start['status'],list(sent_start.get('headers',[])),b''.join(body_parts))
    @staticmethod
    async def _send_cached(cached,send):
        await send({'type':'http.response.start','status':cached['status'],'headers':cached['headers']+[(b'content-length',str(len(cached['body'])).encode())]})
        await send({'type':'http.response.body','body':cached['body'],'more_body':False})
