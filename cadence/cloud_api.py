import json
import csv
import io
import zipfile
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .db import ROOT
from .recommender import HybridRecommender, MODEL_VERSION
from .sql_reports import REPORTS, ReportInput
from .supabase import SupabaseAuthError, SupabaseGateway
from .rate_limit import check_rate

ACCESS_COOKIE = 'cadence_access'
REFRESH_COOKIE = 'cadence_refresh'


class EmailAddress(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(max_length=254, pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class Credentials(EmailAddress):
    password: SecretStr = Field(min_length=1, max_length=128)


class Signup(Credentials):
    password: SecretStr = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1,max_length=80)
    genre_id: int = Field(default=1,ge=1,le=4,strict=True)


class PasswordReset(BaseModel):
    model_config = ConfigDict(extra='forbid')
    recovery_token: SecretStr = Field(min_length=1, max_length=8192)
    password: SecretStr = Field(min_length=8, max_length=128)


class ListenerInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_id: int = Field(gt=0,strict=True)


class CloudPlayback(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: str = Field(min_length=1,max_length=80)
    track_id: int = Field(gt=0,strict=True)
    played_ms: int = Field(ge=0,le=3600000,strict=True)
    source: Literal['catalog','recommendation'] = 'catalog'
    event_key: str = Field(min_length=1,max_length=100)


def create_supabase_app(settings, gateway=None):
    gateway = gateway or SupabaseGateway(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        gateway.close()

    app = FastAPI(title='Cadence · Supabase Music API',version='2.0.0',lifespan=lifespan,
                  description='Supabase Auth, owner-scoped PostgreSQL RPCs, and hybrid recommendations.')

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        if request.url.path.startswith('/api/auth/'):
            return JSONResponse({'detail':'Check the form fields and try again.'}, status_code=422)
        return await request_validation_exception_handler(request, error)

    @app.middleware('http')
    async def same_origin_writes(request, call_next):
        origin = request.headers.get('origin')
        if request.method in {'POST','PUT','PATCH','DELETE'} and origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail':'Cross-origin writes are not allowed'},status_code=403)
        try:
            quota = await check_rate(request, gateway)
        except HTTPException as error:
            return JSONResponse({'detail':error.detail},status_code=error.status_code,headers={**(error.headers or {}),'Cache-Control':'no-store'})
        response = await call_next(request)
        if quota:
            response.headers['X-RateLimit-Limit'] = str(quota['limit'])
            response.headers['X-RateLimit-Remaining'] = str(quota['remaining'])
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response

    def set_session(response, request, data):
        secure = settings.secure_cookies or request.url.scheme == 'https'
        for name,value,age in [(ACCESS_COOKIE,data['access_token'],data.get('expires_in',3600)),
                               (REFRESH_COOKIE,data['refresh_token'],60*60*24*30)]:
            response.set_cookie(name,value,max_age=age,httponly=True,secure=secure,samesite='lax',path='/api')

    def identity(request: Request):
        token = request.cookies.get(ACCESS_COOKIE)
        if not token:
            raise HTTPException(401,'Please sign in')
        # Validate on the Auth server, never trust decoded client claims alone.
        account = gateway.user(token)
        if not account.get('id'):
            raise HTTPException(401,'Please sign in again')
        profile = gateway.rpc('profile', token)
        return {'token':token,'profile':profile,'email':account.get('email','')}

    Identity = Annotated[dict, Depends(identity)]

    def owner(viewer, user_id):
        if viewer['profile']['id'] != user_id:
            raise HTTPException(403,'This account cannot access that listener')

    @app.get('/api/config')
    def config():
        return {'mode':'supabase','auth_required':True,'database':'PostgreSQL'}

    @app.get('/api/health')
    def health():
        return {**gateway.rpc('health'),'model':MODEL_VERSION}

    @app.post('/api/auth/signup')
    def signup(body: Signup):
        if not body.display_name.strip():
            raise HTTPException(422,'Display name cannot be blank')
        gateway.request('POST','/auth/v1/signup',payload={
            'email':body.email,'password':body.password.get_secret_value(),
            'data':{'display_name':body.display_name.strip(),'genre_id':body.genre_id}})
        return {'signed_in':False,'requires_confirmation':True}

    def send_account_email(path, payload):
        try:
            gateway.request('POST', path, payload=payload)
        except SupabaseAuthError as error:
            if error.code not in {'user_not_found', 'email_exists', 'user_already_exists'}:
                raise
        return {'accepted':True}

    @app.post('/api/auth/resend')
    def resend(body: EmailAddress):
        return send_account_email('/auth/v1/resend', {'email':body.email,'type':'signup'})

    @app.post('/api/auth/recover')
    def recover(body: EmailAddress):
        return send_account_email('/auth/v1/recover', {'email':body.email})

    def password_grant(email, password):
        return gateway.request('POST','/auth/v1/token?grant_type=password',
                               payload={'email':email,'password':password})

    @app.post('/api/auth/password')
    def reset_password(body: PasswordReset, request: Request, response: Response):
        password = body.password.get_secret_value()
        try:
            account = gateway.request('PUT', '/auth/v1/user', token=body.recovery_token.get_secret_value(),
                                      payload={'password':password})
        except SupabaseAuthError as error:
            if error.status_code == 401 or error.code in {'bad_jwt', 'session_not_found', 'otp_expired'}:
                raise HTTPException(401, {'code':'recovery_expired',
                                          'message':'This reset link has expired. Request a fresh link.'}) from None
            raise
        email = account.get('email')
        account_id = account.get('id')
        fallback = {'updated':True,'signed_in':False,'email':email}
        if not email or not account_id:
            return fallback
        try:
            data = password_grant(email, password)
        except HTTPException:
            # The password change is already committed. The recovery token is not a Cadence session.
            return fallback
        if (data.get('user') or {}).get('id') != account_id:
            return fallback
        set_session(response,request,data)
        return {'updated':True,'signed_in':True}

    @app.post('/api/auth/login')
    def login(body: Credentials, request: Request, response: Response):
        try:
            data = password_grant(body.email, body.password.get_secret_value())
        except SupabaseAuthError as error:
            if error.code == 'email_not_confirmed':
                raise HTTPException(403, {'code':'email_not_confirmed',
                                          'message':'Verify your email before signing in.'}) from None
            if error.code == 'invalid_credentials':
                raise HTTPException(401,'The email or password is incorrect.') from None
            raise
        set_session(response,request,data)
        return {'signed_in':True}

    @app.post('/api/auth/refresh')
    def refresh(request: Request, response: Response):
        token = request.cookies.get(REFRESH_COOKIE)
        if not token:
            raise HTTPException(401,'Please sign in')
        data = gateway.request('POST','/auth/v1/token?grant_type=refresh_token',payload={'refresh_token':token})
        set_session(response,request,data)
        return {'signed_in':True}

    @app.post('/api/auth/logout')
    def logout(request: Request, response: Response):
        token = request.cookies.get(ACCESS_COOKIE)
        try:
            if token:
                gateway.request('POST','/auth/v1/logout?scope=local',token)
        except HTTPException as error:
            if error.status_code not in {400,401,403}:
                raise
        finally:
            response.delete_cookie(ACCESS_COOKIE,path='/api')
            response.delete_cookie(REFRESH_COOKIE,path='/api')
        return {'signed_out':True}

    @app.get('/api/auth/session')
    def auth_session(viewer: Identity):
        return {'user':viewer['profile'],'email':viewer['email']}

    @app.get('/api/catalog')
    def catalog(search: str=Query('',max_length=100),genre: str=Query('',max_length=40)):
        rows = gateway.rpc('catalog')
        return [r for r in rows if (not genre or r['genre']==genre) and
                search.lower() in f"{r['title']} {r['artist']} {r['album']}".lower()]

    @app.get('/api/genres')
    def genres():
        return gateway.rpc('genres')

    @app.get('/api/users')
    def users(viewer: Identity):
        return [viewer['profile']]

    @app.post('/api/sessions',status_code=201)
    def session(body: ListenerInput,viewer: Identity):
        owner(viewer,body.user_id)
        return gateway.rpc('start_session',viewer['token'])

    @app.post('/api/playback',status_code=201)
    def playback(body: CloudPlayback,viewer: Identity):
        return gateway.rpc('record_play',viewer['token'],{'p_'+k:v for k,v in body.model_dump().items()})

    @app.post('/api/playback/progress',status_code=201)
    def progress(body: CloudPlayback,viewer: Identity):
        return gateway.rpc('play_progress',viewer['token'],{'p_'+k:v for k,v in body.model_dump().items()})

    @app.get('/api/users/{user_id}/history')
    def history(user_id: int,viewer: Identity,limit: int=Query(20,ge=1,le=100)):
        owner(viewer,user_id)
        return gateway.rpc('history',viewer['token'],{'p_limit':limit})

    @app.post('/api/users/{user_id}/likes/{track_id}')
    def like(user_id: int,track_id: int,viewer: Identity):
        owner(viewer,user_id)
        return gateway.rpc('like',viewer['token'],{'p_track_id':track_id})

    @app.get('/api/recommendations/{user_id}')
    def recommend(user_id: int,viewer: Identity,limit: int=Query(6,ge=1,le=24),
                  kind: Literal['track','album']='track',context_track: int|None=Query(None,ge=1),
                  strategy: Literal['hybrid','collaborative','sequence','popularity']='hybrid'):
        owner(viewer,user_id)
        started = time.perf_counter()
        tracks = gateway.rpc('catalog')
        if context_track is not None and context_track not in {t['id'] for t in tracks}:
            raise HTTPException(404,'Track not found')
        model = HybridRecommender(tracks,gateway.rpc('training_events',viewer['token']))
        options = {'strategy':strategy,'context_track':context_track,
                   'preferred_genres':viewer['profile'].get('genre_ids',[])}
        items = model.albums(user_id,limit,**options) if kind=='album' else model.recommend(user_id,limit,**options)
        latency = round((time.perf_counter()-started)*1000,3)
        request_id = str(uuid4())
        exposures = [{'track_id':t['id'],'rank':i,'score':t['score']} for i,t in enumerate(items,1)] if kind=='track' else []
        gateway.rpc('log_recommendations',viewer['token'],{'p_id':request_id,'p_model':MODEL_VERSION,
                    'p_strategy':strategy,'p_latency':latency,'p_items':exposures})
        return {'request_id':request_id,'model':MODEL_VERSION,'kind':kind,'latency_ms':latency,'items':items}

    @app.get('/api/analytics')
    def analytics(viewer: Identity):
        return gateway.rpc('analytics',viewer['token'])

    @app.get('/api/evaluation')
    def evaluation(viewer: Identity):
        # Fixed synthetic benchmark; real account histories are never exported.
        return json.loads((ROOT/'docs/evaluation.json').read_text())

    @app.get('/api/sql/queries')
    def queries(viewer: Identity):
        return REPORTS

    @app.get('/api/export')
    def export_analytics(viewer: Identity):
        from .export import CSV_FIELDS
        data=gateway.rpc('export',viewer['token'])
        data['ModelEvaluation']=json.loads((ROOT/'docs/evaluation.json').read_text())['results']
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as output:
            for table,fields in CSV_FIELDS.items():
                stream=io.StringIO()
                writer=csv.DictWriter(stream,fieldnames=fields)
                writer.writeheader()
                writer.writerows(data.get(table,[]))
                output.writestr(table+'.csv',stream.getvalue())
        return Response(archive.getvalue(),media_type='application/zip',
                        headers={'Content-Disposition':'attachment; filename="cadence-my-analytics.zip"'})

    @app.post('/api/sql/run')
    def sql_report(body: ReportInput,viewer: Identity):
        report = next(r for r in REPORTS if r['id']==body.report_id)
        rows = gateway.rpc('sql_report',viewer['token'],{'p_report':body.report_id,'p_limit':body.limit})
        return {'columns':report['columns'],'rows':rows,'row_count':len(rows),'database':'Supabase PostgreSQL'}

    @app.get('/media/{track_id}')
    def audio(track_id: int):
        if track_id not in {t['id'] for t in gateway.rpc('catalog')}:
            raise HTTPException(404,'Track not found')
        path = ROOT/'cadence/static/audio'/f'{track_id}.wav'
        if not path.exists():
            raise HTTPException(503,'Generate demo audio first')
        return FileResponse(path,media_type='audio/wav')

    @app.get('/')
    def home():
        return FileResponse(ROOT/'cadence/static/index.html')

    app.mount('/static',StaticFiles(directory=ROOT/'cadence/static'),name='static')
    from .demo_api import create_demo_app
    app.mount('/demo',create_demo_app(gateway))
    return app
