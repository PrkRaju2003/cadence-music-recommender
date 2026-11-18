PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL CHECK(length(trim(display_name)) BETWEEN 1 AND 80),
    email TEXT NOT NULL UNIQUE CHECK(instr(email, '@') > 1),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artists (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS genres (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS albums (
    id INTEGER PRIMARY KEY,
    artist_id INTEGER NOT NULL REFERENCES artists(id),
    title TEXT NOT NULL,
    release_year INTEGER NOT NULL CHECK(release_year BETWEEN 1900 AND 2100),
    color TEXT NOT NULL,
    UNIQUE(artist_id, title)
);
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    album_id INTEGER NOT NULL REFERENCES albums(id),
    genre_id INTEGER NOT NULL REFERENCES genres(id),
    title TEXT NOT NULL,
    track_number INTEGER NOT NULL CHECK(track_number > 0),
    duration_ms INTEGER NOT NULL CHECK(duration_ms BETWEEN 1000 AND 3600000),
    UNIQUE(album_id, track_number)
);
CREATE TABLE IF NOT EXISTS user_genres (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    genre_id INTEGER NOT NULL REFERENCES genres(id),
    PRIMARY KEY(user_id, genre_id)
);
CREATE TABLE IF NOT EXISTS listening_sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    started_at TEXT NOT NULL,
    ended_at TEXT CHECK(ended_at IS NULL OR ended_at >= started_at),
    UNIQUE(id, user_id)
);
CREATE TABLE IF NOT EXISTS playback_events (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES listening_sessions(id),
    track_id INTEGER NOT NULL REFERENCES tracks(id),
    played_at TEXT NOT NULL,
    played_ms INTEGER NOT NULL CHECK(played_ms >= 0),
    source TEXT NOT NULL CHECK(source IN ('catalog', 'recommendation', 'seed')),
    event_key TEXT NOT NULL UNIQUE
);
CREATE TRIGGER IF NOT EXISTS playback_bounds BEFORE INSERT ON playback_events
BEGIN
    SELECT CASE WHEN NEW.played_ms > (SELECT duration_ms FROM tracks WHERE id=NEW.track_id)
        THEN RAISE(ABORT, 'played_ms exceeds track duration') END;
    SELECT CASE WHEN NEW.played_at < (SELECT started_at FROM listening_sessions WHERE id=NEW.session_id)
        THEN RAISE(ABORT, 'playback precedes session') END;
    SELECT CASE WHEN (SELECT ended_at FROM listening_sessions WHERE id=NEW.session_id) IS NOT NULL
        THEN RAISE(ABORT, 'session is closed') END;
END;
CREATE TABLE IF NOT EXISTS likes (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY(user_id, track_id)
);
CREATE TABLE IF NOT EXISTS recommendation_requests (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    requested_at TEXT NOT NULL,
    model_version TEXT NOT NULL,
    strategy TEXT NOT NULL,
    latency_ms REAL NOT NULL CHECK(latency_ms >= 0)
);
CREATE TABLE IF NOT EXISTS recommendation_items (
    request_id TEXT NOT NULL REFERENCES recommendation_requests(id) ON DELETE CASCADE,
    track_id INTEGER NOT NULL REFERENCES tracks(id),
    rank INTEGER NOT NULL CHECK(rank > 0),
    score REAL NOT NULL CHECK(score BETWEEN 0 AND 1.000001),
    PRIMARY KEY(request_id, track_id),
    UNIQUE(request_id, rank)
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_time ON listening_sessions(user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_playback_session_time ON playback_events(session_id, played_at, id);
CREATE INDEX IF NOT EXISTS idx_playback_track_time ON playback_events(track_id, played_at);
CREATE INDEX IF NOT EXISTS idx_playback_time ON playback_events(played_at);
CREATE INDEX IF NOT EXISTS idx_tracks_genre ON tracks(genre_id, id);
CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album_id, track_number);
CREATE INDEX IF NOT EXISTS idx_recommendations_user_time ON recommendation_requests(user_id, requested_at DESC);

CREATE VIEW IF NOT EXISTS track_catalog AS
SELECT t.id, t.title, t.track_number, t.duration_ms, t.album_id,
       a.title AS album, a.color, a.release_year, ar.name AS artist,
       g.id AS genre_id, g.name AS genre
FROM tracks t
JOIN albums a ON a.id=t.album_id
JOIN artists ar ON ar.id=a.artist_id
JOIN genres g ON g.id=t.genre_id;

CREATE VIEW IF NOT EXISTS playback_fact AS
SELECT e.id AS event_id, s.user_id, e.session_id, e.track_id,
       e.played_at, substr(e.played_at,1,10) AS play_date,
       e.played_ms, t.duration_ms,
       ROUND(1.0*e.played_ms/t.duration_ms,4) AS completion,
       CASE WHEN 1.0*e.played_ms/t.duration_ms < 0.3 THEN 1 ELSE 0 END AS skipped,
       e.source
FROM playback_events e
JOIN listening_sessions s ON s.id=e.session_id
JOIN tracks t ON t.id=e.track_id;
