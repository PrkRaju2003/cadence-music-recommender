"""Public, read-only showcase. Only synthetic accounts are visible."""
import json
import time
from functools import lru_cache
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import Field

from .cloud_api import CloudPlayback, ListenerInput
from .db import ROOT
from .recommender import HybridRecommender, MODEL_VERSION
from .sql_reports import REPORTS, ReportInput


class DemoReport(ReportInput):
    user_id: int=Field(default=1,gt=0,strict=True)


def create_demo_app(gateway):
    app=FastAPI(title='Cadence public showcase',docs_url=None,openapi_url=None)

    @lru_cache(maxsize=1)
    def data():
        users=gateway.rpc('demo_users')
        tracks=gateway.rpc('catalog')
        return users,tracks,HybridRecommender(tracks,gateway.rpc('demo_events'))

    def listener(user_id):
        if user_id not in {u['id'] for u in data()[0]}:
            raise HTTPException(404,'Synthetic listener not found')

    @app.get('/')
    def home():
        return FileResponse(ROOT/'cadence/static/index.html')

    @app.get('/api/config')
    def config():
        return {'mode':'showcase','auth_required':False,'database':'Supabase PostgreSQL · synthetic demo'}

    @app.get('/api/users')
    def users():return data()[0]

    @app.get('/api/genres')
    def genres():return gateway.rpc('genres')

    @app.get('/api/catalog')
    def catalog():return data()[1]

    @app.get('/api/recommendations/{user_id}')
    def recommendations(user_id:int,limit:int=Query(6,ge=1,le=24),kind:Literal['track','album']='track',
                        context_track:int|None=Query(None,ge=1),strategy:Literal['hybrid','collaborative','sequence','popularity']='hybrid'):
        listener(user_id)
        model=data()[2]
        if context_track is not None and context_track not in model.tracks:raise HTTPException(404,'Track not found')
        start=time.perf_counter()
        items=model.albums(user_id,limit,context_track=context_track,strategy=strategy) if kind=='album' else model.recommend(user_id,limit,context_track=context_track,strategy=strategy)
        return {'request_id':'demo-'+str(uuid4()),'model':MODEL_VERSION,'kind':kind,'latency_ms':round((time.perf_counter()-start)*1000,3),'items':items}

    @app.post('/api/sessions',status_code=201)
    def session(body:ListenerInput):
        listener(body.user_id)
        return {'id':'demo-'+str(uuid4()),'user_id':body.user_id,'demo':True}

    @app.post('/api/playback/progress',status_code=201)
    @app.post('/api/playback',status_code=201)
    def playback(body:CloudPlayback):
        if not body.session_id.startswith('demo-') or body.track_id not in data()[2].tracks or body.played_ms>data()[2].tracks[body.track_id]['duration_ms']:
            raise HTTPException(422,'Invalid demo playback')
        return {'id':0,'duplicate':False,'demo':True,'stored':False}

    @app.get('/api/analytics')
    def analytics():return gateway.rpc('demo_analytics')

    @app.get('/api/evaluation')
    def evaluation():return json.loads((ROOT/'docs/evaluation.json').read_text())

    @app.get('/api/sql/queries')
    def queries():return [{**r,'sql':r['sql'].replace('cadence.current_user_id()',':demo_listener_id')} for r in REPORTS]

    @app.post('/api/sql/run')
    def sql(body:DemoReport):
        listener(body.user_id)
        report=next(r for r in REPORTS if r['id']==body.report_id)
        rows=gateway.rpc('demo_report',payload={'p_report':body.report_id,'p_user_id':body.user_id,'p_limit':body.limit})
        return {'columns':report['columns'],'rows':rows,'row_count':len(rows),'database':'Supabase PostgreSQL · synthetic data'}

    @app.get('/media/{track_id}')
    def media(track_id:int):
        path=ROOT/'cadence/static/audio'/f'{track_id}.wav'
        if not path.is_file():raise HTTPException(404,'Audio not found')
        return FileResponse(path,media_type='audio/wav')

    return app
