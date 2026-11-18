import sqlite3

import pytest

from cadence.db import catalog, database
from cadence.seed import seed


def test_seed_reproducibility_and_idempotency(db_path):
    with database(db_path) as db:
        before = db.execute('SELECT count(*) FROM playback_events').fetchone()[0]
        seed(db)
        assert db.execute('SELECT count(*) FROM playback_events').fetchone()[0] == before == 4480
        assert len(catalog(db)) == 24
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_relational_constraints(db_path):
    with database(db_path) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('INSERT INTO tracks VALUES (999,999,1,?,1,12000)', ('Orphan',))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('INSERT INTO tracks VALUES (999,1,1,?,1,12000)', ('Duplicate position',))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('INSERT INTO tracks VALUES (999,1,1,?,4,-1)', ('Invalid duration',))


def test_closed_session_and_duration_trigger(db_path):
    with database(db_path) as db:
        for session, played in [('seed-1-0', 1000), ('seed-1-1', 13000)]:
            with pytest.raises(sqlite3.IntegrityError):
                db.execute('''INSERT INTO playback_events
                    (session_id,track_id,played_at,played_ms,source,event_key) VALUES (?,1,?,?,?,?)''',
                           (session, '2026-11-01', played, 'catalog', 'bad-event'))


def test_query_plan_uses_user_and_session_indexes(db_path):
    with database(db_path) as db:
        plan = ' '.join(r[3] for r in db.execute('''EXPLAIN QUERY PLAN
            SELECT e.track_id FROM listening_sessions s
            JOIN playback_events e ON e.session_id=s.id WHERE s.user_id=1'''))
        assert 'idx_sessions_user_time' in plan
        assert 'idx_playback_session_time' in plan
