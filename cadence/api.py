import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .db import ROOT, catalog, database, initialize, interactions
from .recommender import MODEL_VERSION, HybridRecommender


def now():
    return datetime.now(timezone.utc).isoformat()


class SessionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_id: int = Field(gt=0, strict=True)


class PlaybackInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: str = Field(min_length=1, max_length=80)
    track_id: int = Field(gt=0, strict=True)
    played_ms: int = Field(ge=0, le=3600000, strict=True)
    source: Literal['catalog', 'recommendation'] = 'catalog'
    event_key: str = Field(min_length=1, max_length=100)


class UserInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    display_name: str = Field(min_length=1, max_length=80)
    genre_ids: list[Annotated[int, Field(gt=0, strict=True)]] = Field(default_factory=list, max_length=4)


def create_app(db_path=None):
    @asynccontextmanager
    async def lifespan(app):
        with database(db_path) as connection:
            initialize(connection)
        yield

    app = FastAPI(title='Cadence Music API', version='1.0.0', lifespan=lifespan,
                  description='Portfolio demo. Synthetic listeners and original generated audio; demo identities are not authentication.')

    def get_db():
        with database(db_path) as connection:
            yield connection

    DB = Annotated[sqlite3.Connection, Depends(get_db)]

    def require_user(connection, user):
        if not connection.execute('SELECT 1 FROM users WHERE id=?', (user,)).fetchone():
            raise HTTPException(404, 'User not found')

    @app.get('/api/health')
    def health(db: DB):
        db.execute('SELECT 1')
        return {'status': 'ok', 'model': MODEL_VERSION}

    @app.get('/api/catalog')
    def tracks(db: DB, search: str = Query('', max_length=100), genre: str = Query('', max_length=40)):
        return [dict(r) for r in db.execute('''SELECT * FROM track_catalog
            WHERE (title LIKE ? OR artist LIKE ? OR album LIKE ?) AND (?='' OR genre=?)
            ORDER BY album_id,track_number''', (f'%{search}%',)*3 + (genre, genre))]

    @app.get('/api/genres')
    def genres(db: DB):
        return [dict(r) for r in db.execute('SELECT * FROM genres ORDER BY id')]

    @app.get('/api/users')
    def users(db: DB):
        return [dict(r) for r in db.execute('SELECT id,display_name FROM users ORDER BY id')]

    @app.post('/api/users', status_code=201)
    def new_user(body: UserInput, db: DB):
        if not body.display_name.strip():
            raise HTTPException(422, 'Display name cannot be blank')
        valid_genres = {r[0] for r in db.execute('SELECT id FROM genres')}
        if not set(body.genre_ids).issubset(valid_genres):
            raise HTTPException(422, 'Unknown genre')
        cursor = db.execute('INSERT INTO users(display_name,email,created_at) VALUES (?,?,?)',
                            (body.display_name.strip(), f'{uuid4()}@example.test', now()))
        user_id = cursor.lastrowid
        db.executemany('INSERT INTO user_genres VALUES (?,?)', [(user_id, g) for g in set(body.genre_ids)])
        return {'id': user_id, 'display_name': body.display_name.strip()}

    @app.post('/api/sessions', status_code=201)
    def new_session(body: SessionInput, db: DB):
        require_user(db, body.user_id)
        session_id = str(uuid4())
        db.execute('INSERT INTO listening_sessions(id,user_id,started_at) VALUES (?,?,?)',
                   (session_id, body.user_id, now()))
        return {'id': session_id, 'user_id': body.user_id}

    @app.post('/api/playback', status_code=201)
    def playback(body: PlaybackInput, db: DB):
        session = db.execute('SELECT * FROM listening_sessions WHERE id=?', (body.session_id,)).fetchone()
        track = db.execute('SELECT * FROM tracks WHERE id=?', (body.track_id,)).fetchone()
        if not session or not track:
            raise HTTPException(404, 'Session or track not found')
        existing = db.execute('SELECT * FROM playback_events WHERE event_key=?', (body.event_key,)).fetchone()
        if existing:
            if any(existing[k] != getattr(body, k) for k in ['session_id', 'track_id', 'played_ms', 'source']):
                raise HTTPException(409, 'Event key already used with a different payload')
            return {'id': existing['id'], 'duplicate': True}
        if session['ended_at'] is not None or body.played_ms > track['duration_ms']:
            raise HTTPException(422, 'Closed session or playback exceeds track duration')
        cursor = db.execute('''INSERT INTO playback_events
            (session_id,track_id,played_at,played_ms,source,event_key) VALUES (?,?,?,?,?,?)''',
            (body.session_id, body.track_id, now(), body.played_ms, body.source, body.event_key))
        return {'id': cursor.lastrowid, 'duplicate': False}

    @app.post('/api/users/{user_id}/likes/{track_id}')
    def like(user_id: int, track_id: int, db: DB):
        require_user(db, user_id)
        if not db.execute('SELECT 1 FROM tracks WHERE id=?', (track_id,)).fetchone():
            raise HTTPException(404, 'Track not found')
        db.execute('INSERT OR IGNORE INTO likes VALUES (?,?,?)', (user_id, track_id, now()))
        return {'liked': True}

    @app.get('/api/users/{user_id}/history')
    def history(user_id: int, db: DB, limit: int = Query(20, ge=1, le=100)):
        require_user(db, user_id)
        return [dict(r) for r in db.execute('''SELECT e.id,e.played_at,e.played_ms,c.title,c.artist,c.album
            FROM listening_sessions s JOIN playback_events e ON e.session_id=s.id
            JOIN track_catalog c ON c.id=e.track_id WHERE s.user_id=?
            ORDER BY e.played_at DESC,e.id DESC LIMIT ?''', (user_id, limit))]

    @app.get('/api/recommendations/{user_id}')
    def recommendations(user_id: int, db: DB, limit: int = Query(6, ge=1, le=24),
                        kind: Literal['track', 'album'] = 'track',
                        context_track: int | None = Query(None, ge=1),
                        strategy: Literal['hybrid', 'collaborative', 'sequence', 'popularity'] = 'hybrid'):
        require_user(db, user_id)
        if context_track is not None and not db.execute('SELECT 1 FROM tracks WHERE id=?', (context_track,)).fetchone():
            raise HTTPException(404, 'Context track not found')
        started = time.perf_counter()
        model = HybridRecommender(catalog(db), interactions(db))
        preferred = [r[0] for r in db.execute('SELECT genre_id FROM user_genres WHERE user_id=?', (user_id,))]
        options = dict(preferred_genres=preferred, strategy=strategy, context_track=context_track)
        result = model.albums(user_id, limit, **options) if kind == 'album' else model.recommend(user_id, limit, **options)
        latency = (time.perf_counter() - started) * 1000
        request_id = str(uuid4())
        db.execute('INSERT INTO recommendation_requests VALUES (?,?,?,?,?,?)',
                   (request_id, user_id, now(), MODEL_VERSION, strategy, round(latency, 3)))
        if kind == 'track':
            db.executemany('INSERT INTO recommendation_items VALUES (?,?,?,?)',
                           [(request_id, r['id'], rank, r['score']) for rank, r in enumerate(result, 1)])
        return {'request_id': request_id, 'model': MODEL_VERSION, 'kind': kind,
                'latency_ms': round(latency, 3), 'items': result}

    @app.get('/api/analytics')
    def analytics(db: DB):
        totals = dict(db.execute('''SELECT COUNT(*) AS plays,COUNT(DISTINCT user_id) AS listeners,
            COUNT(DISTINCT session_id) AS sessions,ROUND(SUM(played_ms)/60000.0,2) AS listening_minutes,
            ROUND(AVG(completion)*100,1) AS completion_pct,ROUND(AVG(skipped)*100,1) AS skip_pct
            FROM playback_fact''').fetchone())
        daily = [dict(r) for r in db.execute('''SELECT play_date,COUNT(*) AS plays,
            COUNT(DISTINCT user_id) AS active_users FROM playback_fact GROUP BY play_date ORDER BY play_date''')]
        genre = [dict(r) for r in db.execute('''SELECT c.genre,COUNT(*) AS plays FROM playback_fact f
            JOIN track_catalog c ON c.id=f.track_id GROUP BY c.genre ORDER BY plays DESC''')]
        latency = dict(db.execute('SELECT COUNT(*) AS requests,ROUND(AVG(latency_ms),2) AS avg_latency_ms FROM recommendation_requests').fetchone())
        return {'totals': totals, 'daily': daily, 'genres': genre, 'model': latency,
                'data_note': '40 synthetic seed listeners; browser demo activity is recorded separately by source.'}

    @app.get('/api/evaluation')
    def evaluation(db: DB):
        from .evaluate import evaluate
        return evaluate(db)

    @app.get('/media/{track_id}')
    def audio(track_id: int, db: DB):
        if not db.execute('SELECT 1 FROM tracks WHERE id=?', (track_id,)).fetchone():
            raise HTTPException(404, 'Track not found')
        audio_file = ROOT / 'data/audio' / f'{track_id}.wav'
        if not audio_file.is_file():
            raise HTTPException(503, 'Run python -m cadence.seed to generate demo audio')
        return FileResponse(audio_file, media_type='audio/wav')

    @app.get('/')
    def home():
        return FileResponse(ROOT / 'cadence/static/index.html')

    app.mount('/static', StaticFiles(directory=ROOT / 'cadence/static'), name='static')
    return app


app = create_app()
