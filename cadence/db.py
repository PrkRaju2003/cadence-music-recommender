import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def connect(path=None):
    path = Path(path or os.environ.get('CADENCE_DB', ROOT / 'data/cadence.db'))
    path.parent.mkdir(parents=True, exist_ok=True)
    # One connection per request; FastAPI may enter/exit a sync dependency on
    # different worker threads. Connections are never shared between requests.
    connection = sqlite3.connect(path, timeout=10, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    connection.execute('PRAGMA journal_mode=WAL')
    return connection


@contextmanager
def database(path=None):
    connection = connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize(connection):
    connection.executescript((ROOT / 'sql/schema.sql').read_text())


def catalog(connection):
    return [dict(row) for row in connection.execute('SELECT * FROM track_catalog ORDER BY id')]


def interactions(connection):
    return [dict(row) for row in connection.execute('''
        SELECT e.id,e.session_id,s.user_id,e.track_id,e.played_at,
               1.0*e.played_ms/t.duration_ms AS completion
        FROM playback_events e JOIN listening_sessions s ON s.id=e.session_id
        JOIN tracks t ON t.id=e.track_id ORDER BY e.played_at,e.id
    ''')]
