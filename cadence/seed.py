"""Deterministic synthetic listeners and original, generated demo audio."""
import math
import random
import struct
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import ROOT, database, initialize

ALBUMS = [
    ('Soft Circuit', 'After Hours', 'Electronic', '#b5b4ed', ['Night Drive', 'Signal Bloom', 'Last Train']),
    ('Mira Vale', 'Slow Sundays', 'Jazz', '#deb283', ['First Light', 'Paper Cup', 'Blue Window']),
    ('Northbound', 'Open Roads', 'Indie', '#a4be9c', ['Long Way Home', 'Wildflowers', 'Golden Mile']),
    ('Low Tide', 'Still Water', 'Ambient', '#8ab7c6', ['Drift', 'Tidal Memory', 'Quiet Shore']),
    ('Pixel Atlas', 'Neon Sketches', 'Electronic', '#e5a0b5', ['Arcade Hearts', 'Soft Reset', 'Electric Rain']),
    ('Juniper Trio', 'Room for Three', 'Jazz', '#dbc78c', ['Side Street', 'Amber Notes', 'Midnight Table']),
    ('The Folds', 'Little Universes', 'Indie', '#b0b8cd', ['Satellite', 'Almost Summer', 'Small Worlds']),
    ('Oren Fields', 'A Place to Pause', 'Ambient', '#c8b3a0', ['Moss', 'Faraway', 'Breathe Again']),
]


def make_audio(directory=None):
    directory = Path(directory or ROOT / 'data/audio')
    directory.mkdir(parents=True, exist_ok=True)
    sample_rate, seconds = 16000, 12
    for track in range(1, 25):
        target = directory / f'{track}.wav'
        if target.exists():
            continue
        notes = [0, 4, 7, 12, 7, 4, 2, 7]
        frequency = 130.81 * 2 ** ((track % 12) / 12)
        frames = bytearray()
        for n in range(sample_rate * seconds):
            t = n / sample_rate
            beat = int(t * 2) % len(notes)
            phase = (t * 2) % 1
            envelope = min(1, phase * 25) * math.exp(-phase * 2.7)
            fade = min(1, t * 3, (seconds - t) * 3)
            f = frequency * 2 ** (notes[(beat + track) % len(notes)] / 12)
            value = (math.sin(2 * math.pi * f * t) + .22 * math.sin(2 * math.pi * f * 2 * t))
            frames.extend(struct.pack('<h', int(10500 * value * envelope * fade)))
        with wave.open(str(target), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(frames)


def seed(connection):
    """Safe to rerun; never deletes existing listening activity."""
    if connection.execute('SELECT count(*) FROM users').fetchone()[0]:
        return
    rng = random.Random(42)
    genres = ['Electronic', 'Jazz', 'Indie', 'Ambient']
    connection.executemany('INSERT INTO genres VALUES (?,?)', enumerate(genres, 1))
    for album_id, (artist, title, genre, color, titles) in enumerate(ALBUMS, 1):
        connection.execute('INSERT INTO artists VALUES (?,?)', (album_id, artist))
        connection.execute('INSERT INTO albums VALUES (?,?,?,?,?)', (album_id, album_id, title, 2026, color))
        for number, song in enumerate(titles, 1):
            track_id = (album_id - 1) * 3 + number
            connection.execute('INSERT INTO tracks VALUES (?,?,?,?,?,?)',
                               (track_id, album_id, genres.index(genre) + 1, song, number, 12000))
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for user in range(1, 41):
        connection.execute('INSERT INTO users VALUES (?,?,?,?)',
                           (user, 'Alex Morgan' if user == 1 else f'Listener {user:02}',
                            f'listener{user}@example.test', start.isoformat()))
        preferred = (user - 1) % 4 + 1
        connection.execute('INSERT INTO user_genres VALUES (?,?)', (user, preferred))
        candidates = [row[0] for row in connection.execute('SELECT id FROM tracks WHERE genre_id=?', (preferred,))]
        for day in range(28):
            when = start + timedelta(days=day, hours=9 + user % 10, minutes=user)
            session = f'seed-{user}-{day}'
            connection.execute('INSERT INTO listening_sessions(id,user_id,started_at) VALUES (?,?,?)',
                               (session, user, when.isoformat()))
            current = rng.choice(candidates)
            for position in range(4):
                if position:
                    current = current + 1 if current % 3 != 0 and rng.random() < .72 else rng.choice(candidates if rng.random() < .82 else list(range(1, 25)))
                skipped = rng.random() < (.08 if current in candidates else .4)
                played = rng.randint(1000, 3000) if skipped else rng.randint(9000, 12000)
                connection.execute('''INSERT INTO playback_events
                    (session_id,track_id,played_at,played_ms,source,event_key) VALUES (?,?,?,?,?,?)''',
                    (session, current, (when + timedelta(seconds=position * 15)).isoformat(),
                     played, 'seed', f'{session}-{position}'))
            connection.execute('UPDATE listening_sessions SET ended_at=? WHERE id=?',
                               ((when + timedelta(minutes=2)).isoformat(), session))


def main():
    with database() as connection:
        initialize(connection)
        seed(connection)
    make_audio()
    print('Ready: 40 synthetic listeners, 24 original demo tracks. Run uvicorn cadence.api:app --reload.')


if __name__ == '__main__':
    main()
