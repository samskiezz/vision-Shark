from __future__ import annotations

import hashlib
import hmac
import json
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
        with self._lock:session=self._sessions.pop(session_id,None)
        if session:self._audit('logout',{'role':session.role})
    def idempotency_get(self,session_id:str,key:str,request_hash:str):
        now=time.time_ns();cache_key=(session_id,key)
        with self._lock:
            row=self._idempotency.get(cache_key)
            if row is None:return None
            if row['expires_ns']<=now:self._idempotency.pop(cache_key,None);return None
            if row['request_hash']!=request_hash:raise ValueError('Idempotency-Key reused with a different request')
            return row
    def idempotency_put(self,session_id:str,key:str,request_hash:str,status:int,headers:list[tuple[bytes,bytes]],body:bytes):
        if len(body)>2*1024*1024:return
        safe_headers=[(k,v) for k,v in headers if k.lower() not in {b'set-cookie',b'content-length',b'transfer-encoding'}]
        with self._lock:self._idempotency[(session_id,key)]={'request_hash':request_hash,'status':int(status),'headers':safe_headers,'body':bytes(body),'expires_ns':time.time_ns()+15*60*1_000_000_000}

class SecurityMiddleware:
    def __init__(self,app,manager:SecurityManager,cookie_name:str='vision_session'):
        self.app=app;self.manager=manager;self.cookie_name=cookie_name
    @staticmethod
    def _headers(scope):return {k.lower():v for k,v in scope.get('headers',[])}
    def _cookie(self,headers):
        raw=headers.get(b'cookie',b'').decode('latin1','ignore')
        for item in raw.split(';'):
            name,sep,value=item.strip().partition('=')
            if sep and name==self.cookie_name:return value
        return None
    @staticmethod
    async def _body(receive):
        chunks=[];more=True
        while more:
            msg=await receive()
            if msg['type']=='http.disconnect':break
            if msg['type']=='http.request':chunks.append(msg.get('body',b''));more=bool(msg.get('more_body',False))
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
        body=await self._body(receive);request_hash=hashlib.sha256(method.encode()+b'\0'+path.encode()+b'\0'+body).hexdigest()
        try:cached=self.manager.idempotency_get(session.session_id,idem,request_hash)
        except ValueError as exc:return await JSONResponse({'detail':str(exc)},status_code=409)(scope,receive,send)
        if cached is not None:
            self.manager._audit('idempotent_replay',{'path':path,'method':method,'role':session.role})
            async def replay_send(message):
                if message['type']=='http.response.start':return await send({'type':'http.response.start','status':cached['status'],'headers':cached['headers']})
                if message['type']=='http.response.body':return await send({'type':'http.response.body','body':cached['body'],'more_body':False})
                return await send(message)
            return await replay_send({'type':'http.response.start'} ) if False else await self._send_cached(cached,send)
        sent_start=None;body_parts=[]
        async def replay_receive():return {'type':'http.request','body':body,'more_body':False}
        async def capture_send(message):
            nonlocal sent_start
            if message['type']=='http.response.start':sent_start=message
            elif message['type']=='http.response.body':body_parts.append(message.get('body',b''))
            await send(message)
        await self.app(scope,replay_receive,capture_send)
        if sent_start is not None and not sent_start.get('status',500)>=500:
            self.manager.idempotency_put(session.session_id,idem,request_hash,sent_start['status'],list(sent_start.get('headers',[])),b''.join(body_parts))
    @staticmethod
    async def _send_cached(cached,send):
        await send({'type':'http.response.start','status':cached['status'],'headers':cached['headers']+[(b'content-length',str(len(cached['body'])).encode())]})
        await send({'type':'http.response.body','body':cached['body'],'more_body':False})
