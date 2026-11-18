from cadence.db import catalog, database, interactions
from cadence.evaluate import CUTOFF, evaluate
from cadence.recommender import HybridRecommender


def test_scores_deterministic_bounded_and_no_immediate_repeat(db_path):
    with database(db_path) as db:
        model = HybridRecommender(catalog(db), interactions(db))
    one = model.recommend(1, 10, context_track=1)
    assert one == model.recommend(1, 10, context_track=1)
    assert len({r['id'] for r in one}) == len(one)
    assert all(0 <= r['score'] <= 1 and r['id'] != 1 for r in one)


def test_sequence_does_not_bridge_sessions_or_skipped_events():
    tracks = [{'id': t, 'genre_id': 1} for t in [1, 2, 3]]
    events = [dict(id=i, session_id=s, user_id=1, track_id=t, completion=c, played_at=str(i))
              for i, s, t, c in [(1, 'a', 1, 1), (2, 'a', 2, .1), (3, 'a', 3, 1), (4, 'b', 2, 1)]]
    model = HybridRecommender(tracks, events)
    assert not any(model.transitions.values())


def test_next_track_model_learns_observed_transition():
    tracks = [{'id': t, 'genre_id': 1} for t in [1, 2, 3]]
    events = [dict(id=i, session_id='a', user_id=1, track_id=t, completion=1, played_at=str(i))
              for i, t in enumerate([1, 2], 1)]
    model = HybridRecommender(tracks, events)
    assert model.recommend(1, strategy='sequence', context_track=1)[0]['id'] == 2


def test_evaluation_temporal_split_and_baselines(db_path):
    with database(db_path) as db:
        report = evaluate(db)
        train_count = sum(e['played_at'] < CUTOFF for e in interactions(db))
    assert report['train_events'] == train_count == 3360
    assert report['eligible_users'] == 40
    assert {r['strategy'] for r in report['results']} == {'hybrid', 'sequence', 'collaborative', 'popularity'}
    assert all(0 <= r[key] <= 1 for r in report['results'] for key in ['hit_rate', 'ndcg', 'mrr', 'catalog_coverage'])


def test_empty_history_graceful_and_genre_aware():
    model = HybridRecommender([{'id': 1, 'genre_id': 1}, {'id': 2, 'genre_id': 2}], [])
    assert model.recommend(99, preferred_genres=[2])[0]['id'] == 2
    assert HybridRecommender([], []).recommend(99) == []
