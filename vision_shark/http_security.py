from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import OrderedDict,deque
from dataclasses import dataclass
from http.cookies import SimpleCookie

from fastapi import HTTPException,Request,Response
from pydantic import BaseModel,Field
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

ROLE_LEVEL={'viewer':1,'operator':2,'admin':3}
SAFE_METHODS={'GET','HEAD','OPTIONS'}
MUTATING_METHODS={'POST','PUT','PATCH','DELETE'}
COOKIE_NAME='vision_session'


def security_disabled()->bool:
    return os.getenv('VISION_SECURITY_DISABLED','').strip().lower() in {'1','true','yes','on'}


def _digest(value:str)->bytes:
    return hashlib.sha256(value.encode('utf-8')).digest()


def _subject(role:str,token:str)->str:
    return f'{role}:{hashlib.sha256(token.encode()).hexdigest()[:16]}'


@dataclass(frozen=True)
class Principal:
    role:str
    subject:str
    auth_kind:str
    csrf_token:str|None=None
    session_id:str|None=None


@dataclass
class Session:
    role:str
    subject:str
    csrf_token:str
    expires_at:float


@dataclass
class IdempotencyRecord:
    method:str
    target:str
    body_sha256:str
    created_at:float
    state:str='pending'
    response_status:int|None=None
    response_headers:list[tuple[bytes,bytes]]|None=None
    response_body:bytes|None=None
    replayable:bool=True


class SecurityManager:
    def __init__(self,enabled:bool|None=None,session_ttl_s:int=8*60*60,idempotency_ttl_s:int=15*60):
        self.enabled=not security_disabled() if enabled is None else bool(enabled)
        self.session_ttl_s=max(300,int(session_ttl_s));self.idempotency_ttl_s=max(60,int(idempotency_ttl_s))
        self._lock=threading.RLock();self._sessions:OrderedDict[str,Session]=OrderedDict();self._idempotency:OrderedDict[tuple[str,str],IdempotencyRecord]=OrderedDict();self._failed_logins=deque(maxlen=64)
        self._tokens={}
        if self.enabled:
            for role,env_name in (('viewer','VISION_VIEWER_TOKEN'),('operator','VISION_OPERATOR_TOKEN'),('admin','VISION_ADMIN_TOKEN')):
                token=os.getenv(env_name)
                if not token:continue
                if len(token)<24:raise RuntimeError(f'{env_name} must be at least 24 characters')
                self._tokens[role]=_digest(token)
            if not self._tokens:raise RuntimeError('HTTP security is enabled but no VISION_VIEWER_TOKEN, VISION_OPERATOR_TOKEN, or VISION_ADMIN_TOKEN is configured')

    def _cleanup(self):
        now=time.monotonic()
        for sid,session in list(self._sessions.items()):
            if session.expires_at<=now:self._sessions.pop(sid,None)
        for key,record in list(self._idempotency.items()):
            if now-record.created_at>self.idempotency_ttl_s:self._idempotency.pop(key,None)
        while len(self._sessions)>128:self._sessions.popitem(last=False)
        while len(self._idempotency)>512:self._idempotency.popitem(last=False)

    def verify_token(self,token:str)->tuple[str,str]|None:
        if not token:return None
        candidate=_digest(token)
        for role in ('admin','operator','viewer'):
            expected=self._tokens.get(role)
            if expected is not None and hmac.compare_digest(candidate,expected):return role,_subject(role,token)
        return None

    def create_session(self,token:str)->tuple[str,Session]:
        now=time.monotonic()
        with self._lock:
            while self._failed_logins and now-self._failed_logins[0]>60:self._failed_logins.popleft()
            if len(self._failed_logins)>=8:raise PermissionError('authentication temporarily rate limited')
            verified=self.verify_token(token)
            if verified is None:
                self._failed_logins.append(now);raise PermissionError('invalid operator token')
            role,subject=verified;sid=secrets.token_urlsafe(32);session=Session(role,subject,secrets.token_urlsafe(24),now+self.session_ttl_s)
            self._sessions[sid]=session;self._sessions.move_to_end(sid);self._cleanup();return sid,session

    def revoke_session(self,sid:str|None):
        if not sid:return
        with self._lock:self._sessions.pop(sid,None)

    def _cookie_sid(self,headers:Headers)->str|None:
        raw=headers.get('cookie')
        if not raw:return None
        cookie=SimpleCookie()
        try:cookie.load(raw)
        except Exception:return None
        morsel=cookie.get(COOKIE_NAME);return None if morsel is None else morsel.value

    def authenticate(self,headers:Headers)->Principal|None:
        if not self.enabled:return Principal('admin','security-disabled','disabled')
        authorization=headers.get('authorization')
        if authorization:
            if not authorization.startswith('Bearer '):return None
            verified=self.verify_token(authorization[7:].strip())
            if verified is None:return None
            role,subject=verified;return Principal(role,subject,'bearer')
        sid=self._cookie_sid(headers)
        if not sid:return None
        with self._lock:
            self._cleanup();session=self._sessions.get(sid)
            if session is None:return None
            self._sessions.move_to_end(sid);return Principal(session.role,session.subject,'session',session.csrf_token,sid)

    def begin_idempotency(self,principal:Principal,key:str,method:str,target:str,body:bytes)->tuple[str,IdempotencyRecord|None]:
        if not 8<=len(key)<=128:return 'invalid',None
        body_sha=hashlib.sha256(body).hexdigest();lookup=(principal.subject,key);now=time.monotonic()
        with self._lock:
            self._cleanup();record=self._idempotency.get(lookup)
            if record is not None:
                if (record.method,record.target,record.body_sha256)!=(method,target,body_sha):return 'conflict',record
                if record.state=='pending':return 'pending',record
                if not record.replayable:return 'unreplayable',record
                return 'replay',record
            record=IdempotencyRecord(method,target,body_sha,now);self._idempotency[lookup]=record;self._cleanup();return 'new',record

    def complete_idempotency(self,principal:Principal,key:str,status:int,headers:list[tuple[bytes,bytes]],body:bytes):
        lookup=(principal.subject,key)
        with self._lock:
            record=self._idempotency.get(lookup)
            if record is None:return
            if status>=500:
                self._idempotency.pop(lookup,None);return
            record.state='completed';record.response_status=int(status)
            if len(body)>512*1024:
                record.replayable=False;record.response_body=None;record.response_headers=None;return
            blocked={b'connection',b'transfer-encoding',b'date',b'server'}
            record.response_headers=[(k,v) for k,v in headers if k.lower() not in blocked];record.response_body=bytes(body)

    def abort_idempotency(self,principal:Principal,key:str):
        with self._lock:self._idempotency.pop((principal.subject,key),None)


def _public_path(path:str)->bool:
    return path=='/' or path=='/health' or path.startswith('/static/') or path in {'/api/auth/session','/api/auth/status'}


def required_role(method:str,path:str)->str|None:
    if _public_path(path) or method=='OPTIONS':return None
    if method in SAFE_METHODS:return 'viewer'
    if path in {'/api/openclaw/read','/api/vision/autonomy/shadow','/api/agent/policy/evaluate','/api/agent/policy/emergency'}:return 'viewer'
    if path.endswith('/event-diff') or path.endswith('/platform-match'):return 'viewer'
    if path=='/api/auth/logout':return 'viewer'
    if path=='/api/discovery/adapters' or path=='/api/decoder':return 'admin'
    return 'operator'


def needs_idempotency(method:str,path:str)->bool:
    role=required_role(method,path)
    return method in MUTATING_METHODS and role in {'operator','admin'} and path not in {'/api/transmit','/api/auth/logout'}


async def _respond_json(scope,receive,send,status:int,detail:str,extra_headers:dict[str,str]|None=None):
    response=JSONResponse({'detail':detail},status_code=status,headers=extra_headers or {})
    await response(scope,receive,send)


def _security_headers(headers:list[tuple[bytes,bytes]])->list[tuple[bytes,bytes]]:
    existing={k.lower() for k,_ in headers};extra=[
        (b'x-content-type-options',b'nosniff'),(b'x-frame-options',b'DENY'),(b'referrer-policy',b'no-referrer'),
        (b'content-security-policy',b"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"),
    ]
    return headers+[item for item in extra if item[0] not in existing]


class ApiSecurityMiddleware:
    def __init__(self,app,manager:SecurityManager,audit=None):self.app=app;self.manager=manager;self.audit=audit

    def _audit(self,event:str,payload:dict):
        if self.audit:self.audit.append('security',event,payload)

    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        method=str(scope.get('method','GET')).upper();path=str(scope.get('path','/'));headers=Headers(scope=scope)
        required=required_role(method,path);principal=self.manager.authenticate(headers)
        if self.manager.enabled and required is not None and principal is None:
            self._audit('authentication_denied',{'method':method,'path':path});return await _respond_json(scope,receive,send,401,'Authentication required',{'www-authenticate':'Bearer'})
        if principal is None:principal=Principal('admin','security-disabled','disabled')
        if required is not None and ROLE_LEVEL[principal.role]<ROLE_LEVEL[required]:
            self._audit('role_denied',{'method':method,'path':path,'role':principal.role,'required':required});return await _respond_json(scope,receive,send,403,'Insufficient role')
        if self.manager.enabled and method in MUTATING_METHODS and principal.auth_kind=='session' and path!='/api/auth/session':
            supplied=headers.get('x-csrf-token','')
            if not principal.csrf_token or not hmac.compare_digest(supplied,principal.csrf_token):
                self._audit('csrf_denied',{'method':method,'path':path,'role':principal.role});return await _respond_json(scope,receive,send,403,'Valid X-CSRF-Token required')

        idem_key=None;idem_record=None
        if self.manager.enabled and needs_idempotency(method,path):
            idem_key=headers.get('idempotency-key','').strip()
            if not idem_key:
                self._audit('idempotency_missing',{'method':method,'path':path,'role':principal.role});return await _respond_json(scope,receive,send,428,'Idempotency-Key required')
            messages=[];body_parts=[];more=True
            while more:
                message=await receive();messages.append(message)
                if message['type']=='http.disconnect':break
                if message['type']=='http.request':body_parts.append(message.get('body',b''));more=bool(message.get('more_body',False))
                else:more=False
            body=b''.join(body_parts);target=path+('?' + scope.get('query_string',b'').decode('latin-1') if scope.get('query_string') else '')
            disposition,idem_record=self.manager.begin_idempotency(principal,idem_key,method,target,body)
            if disposition=='invalid':return await _respond_json(scope,receive,send,400,'Idempotency-Key must be 8 to 128 characters')
            if disposition=='conflict':
                self._audit('idempotency_conflict',{'method':method,'path':path,'role':principal.role});return await _respond_json(scope,receive,send,409,'Idempotency-Key was already used for a different request')
            if disposition=='pending':return await _respond_json(scope,receive,send,409,'Idempotent request is already in progress')
            if disposition=='unreplayable':return await _respond_json(scope,receive,send,409,'Prior idempotent response was too large to replay')
            if disposition=='replay' and idem_record is not None:
                replay_headers=list(idem_record.response_headers or []);replay_headers.append((b'idempotency-replayed',b'true'));replay_headers=_security_headers(replay_headers)
                await send({'type':'http.response.start','status':int(idem_record.response_status or 200),'headers':replay_headers});await send({'type':'http.response.body','body':idem_record.response_body or b'','more_body':False});self._audit('idempotency_replayed',{'method':method,'path':path,'role':principal.role});return
            index=0
            async def replay_receive():
                nonlocal index
                if index<len(messages):message=messages[index];index+=1;return message
                return {'type':'http.request','body':b'','more_body':False}
            downstream_receive=replay_receive
        else:downstream_receive=receive

        response_status=None;response_headers=[];response_body=[]
        async def secured_send(message):
            nonlocal response_status,response_headers
            if message['type']=='http.response.start':
                response_status=int(message['status']);response_headers=_security_headers(list(message.get('headers',[])));message={**message,'headers':response_headers}
            elif message['type']=='http.response.body' and idem_key is not None:
                response_body.append(message.get('body',b''))
            await send(message)
        try:await self.app(scope,downstream_receive,secured_send)
        except Exception:
            if idem_key is not None:self.manager.abort_idempotency(principal,idem_key)
            raise
        if idem_key is not None:self.manager.complete_idempotency(principal,idem_key,response_status or 500,response_headers,b''.join(response_body))
        if self.manager.enabled and method in MUTATING_METHODS and path!='/api/auth/session':self._audit('request',{'method':method,'path':path,'role':principal.role,'auth_kind':principal.auth_kind,'status':response_status})


class LoginBody(BaseModel):
    token:str=Field(min_length=1,max_length=512)


def install_security_routes(app,manager:SecurityManager,audit=None):
    def log(event,payload):
        if audit:audit.append('security',event,payload)

    @app.get('/api/auth/status')
    def auth_status(request:Request):
        principal=manager.authenticate(request.headers)
        if not manager.enabled:return {'security_enabled':False,'authenticated':True,'role':'admin','csrf_token':None}
        if principal is None:return {'security_enabled':True,'authenticated':False,'role':None,'csrf_token':None}
        return {'security_enabled':True,'authenticated':True,'role':principal.role,'csrf_token':principal.csrf_token if principal.auth_kind=='session' else None,'auth_kind':principal.auth_kind}

    @app.post('/api/auth/session')
    def auth_session(body:LoginBody,response:Response,request:Request):
        if not manager.enabled:return {'security_enabled':False,'authenticated':True,'role':'admin','csrf_token':None}
        try:sid,session=manager.create_session(body.token)
        except PermissionError as exc:
            log('login_denied',{'client':request.client.host if request.client else None});raise HTTPException(401,str(exc)) from exc
        response.set_cookie(COOKIE_NAME,sid,max_age=manager.session_ttl_s,httponly=True,samesite='strict',secure=request.url.scheme=='https',path='/')
        log('login',{'role':session.role,'client':request.client.host if request.client else None});return {'security_enabled':True,'authenticated':True,'role':session.role,'csrf_token':session.csrf_token}

    @app.post('/api/auth/logout')
    def auth_logout(request:Request,response:Response):
        principal=manager.authenticate(request.headers)
        if principal is None:raise HTTPException(401,'Authentication required')
        if principal.session_id:manager.revoke_session(principal.session_id)
        response.delete_cookie(COOKIE_NAME,path='/');log('logout',{'role':principal.role,'auth_kind':principal.auth_kind});return {'authenticated':False}
