def event(client, **overrides):
    session = client.post('/api/sessions', json={'user_id': 1}).json()['id']
    return {'session_id': session, 'track_id': 1, 'played_ms': 11000,
            'source': 'catalog', 'event_key': 'test-event', **overrides}


def test_catalog_search_and_filters(client):
    assert len(client.get('/api/catalog').json()) == 24
    rows = client.get('/api/catalog?genre=Jazz&search=Light').json()
    assert [r['title'] for r in rows] == ['First Light']
    assert client.get('/api/catalog', params={'search': "' OR 1=1 --"}).json() == []


def test_parallel_browser_bootstrap_requests(client):
    from concurrent.futures import ThreadPoolExecutor
    paths = ['/api/catalog', '/api/users', '/api/genres'] * 5
    with ThreadPoolExecutor(max_workers=6) as executor:
        responses = list(executor.map(client.get, paths))
    assert all(r.status_code == 200 for r in responses)


def test_unknown_listener_and_context_are_not_silently_served(client):
    assert client.get('/api/recommendations/999').status_code == 404
    assert client.get('/api/recommendations/1?context_track=999').status_code == 404
    assert client.get('/api/recommendations/1?limit=100').status_code == 422


def test_hybrid_and_album_contracts(client):
    result = client.get('/api/recommendations/1?context_track=1&limit=5').json()
    assert len(result['items']) == 5
    assert 1 not in [r['id'] for r in result['items']]
    assert result['latency_ms'] >= 0
    assert all(set(r['components']) == {'collaborative', 'sequence', 'popularity'} for r in result['items'])
    albums = client.get('/api/recommendations/1?kind=album&limit=3').json()['items']
    assert len(albums) == 3
    assert all(a['track_ids'] for a in albums)


def test_playback_idempotency_and_conflict(client):
    payload = event(client)
    first = client.post('/api/playback', json=payload)
    assert first.status_code == 201
    duplicate = client.post('/api/playback', json=payload)
    assert duplicate.json()['duplicate'] is True
    assert duplicate.json()['id'] == first.json()['id']
    assert client.post('/api/playback', json={**payload, 'played_ms': 4000}).status_code == 409


def test_playback_validation(client):
    payload = event(client)
    for changes, code in [({'played_ms': 13000}, 422), ({'played_ms': -1}, 422),
                          ({'track_id': 999}, 404), ({'source': 'malicious'}, 422),
                          ({'session_id': 'missing'}, 404)]:
        assert client.post('/api/playback', json={**payload, **changes}).status_code == code


def test_new_listener_cold_start_and_preference_validation(client):
    assert client.post('/api/users', json={'display_name': ' ', 'genre_ids': []}).status_code == 422
    assert client.post('/api/users', json={'display_name': 'Sam', 'genre_ids': [999]}).status_code == 422
    user = client.post('/api/users', json={'display_name': 'Sam', 'genre_ids': [4, 4]}).json()['id']
    recs = client.get(f'/api/recommendations/{user}?limit=5').json()['items']
    assert all(r['genre_id'] == 4 for r in recs)
    assert client.get(f'/api/users/{user}/history').json() == []


def test_event_visible_in_history_and_analytics(client):
    before = client.get('/api/analytics').json()['totals']['plays']
    client.post('/api/playback', json=event(client))
    assert client.get('/api/analytics').json()['totals']['plays'] == before + 1
    assert client.get('/api/users/1/history?limit=1').json()[0]['title'] == 'Night Drive'


def test_audio_supports_partial_content_and_missing_track(client, audio_files):
    result = client.get('/media/1', headers={'Range': 'bytes=0-43'})
    assert result.status_code == 206
    assert result.content[:4] == b'RIFF'
    assert len(result.content) == 44
    assert result.headers['content-type'] == 'audio/wav'
    assert client.get('/media/999').status_code == 404


def test_recommendation_exposures_are_recorded(client, db_path):
    from cadence.db import database
    result = client.get('/api/recommendations/1?limit=4').json()
    with database(db_path) as db:
        rows = db.execute('SELECT rank,score FROM recommendation_items WHERE request_id=? ORDER BY rank',
                          (result['request_id'],)).fetchall()
    assert [r['rank'] for r in rows] == [1, 2, 3, 4]
    assert [r['score'] for r in rows] == sorted([r['score'] for r in rows], reverse=True)
