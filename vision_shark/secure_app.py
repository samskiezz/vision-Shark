from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException,Request,Response
from pydantic import BaseModel,Field

from .api import create_app
from .http_security import SecurityManager,SecurityMiddleware


class LoginBody(BaseModel):
    token:str=Field(min_length=16,max_length=512)


def create_secured_app(data_dir:Path|str,admin_token:str,viewer_token:str|None=None):
    """Create the supported operator server with mandatory HTTP security.

    The lower-level ``create_app`` factory remains available for embedded development
    and tests. The CLI ``vision-shark serve`` uses this wrapper exclusively.
    """
    app=create_app(data_dir)
    manager=SecurityManager(admin_token,viewer_token,audit=app.state.audit)
    app.state.security=manager;app.state.security_required=True
    app.add_middleware(SecurityMiddleware,manager=manager)

    @app.post('/api/auth/login')
    def login(body:LoginBody,response:Response):
        session=manager.login(body.token)
        if session is None:raise HTTPException(401,'Invalid access token')
        response.set_cookie('vision_session',session.session_id,max_age=43_200,httponly=True,samesite='strict',secure=False,path='/')
        return {'authenticated':True,'role':session.role,'csrf_token':session.csrf_token,'expires_ns':session.expires_ns}

    @app.get('/api/auth/session')
    def auth_session(request:Request):
        session=manager.get(request.cookies.get('vision_session'))
        if session is None:return {'authenticated':False,'role':None,'csrf_token':None}
        return {'authenticated':True,'role':session.role,'csrf_token':session.csrf_token,'expires_ns':session.expires_ns}

    @app.post('/api/auth/logout')
    def logout(request:Request,response:Response):
        manager.logout(request.cookies.get('vision_session'));response.delete_cookie('vision_session',path='/')
        return {'authenticated':False}

    return app
