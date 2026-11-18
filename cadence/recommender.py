"""Implicit item-item collaborative filtering + session Markov transitions.

No LLM or remote service is involved. Scores are ranking signals, not probabilities.
"""
import math
from collections import Counter, defaultdict

MODEL_VERSION = 'itemcf-markov-v1'
WEIGHTS = {'collaborative': .5, 'sequence': .35, 'popularity': .15}


def normalize(scores, candidates):
    peak = max((scores.get(t, 0) for t in candidates), default=0)
    return {t: scores.get(t, 0) / peak if peak else 0 for t in candidates}


class HybridRecommender:
    def __init__(self, tracks, events):
        self.tracks = {t['id']: t for t in tracks}
        self.events = sorted(events, key=lambda e: (e['played_at'], e.get('id', 0)))
        self.user_vectors = defaultdict(Counter)
        self.histories = defaultdict(list)
        self.popularity = Counter()
        self.transitions = defaultdict(Counter)
        sessions = defaultdict(list)
        for e in self.events:
            self.histories[e['user_id']].append(e)
            sessions[e['session_id']].append(e)
            if e['completion'] >= .5:
                self.user_vectors[e['user_id']][e['track_id']] += e['completion']
                self.popularity[e['track_id']] += 1
        item_vectors = defaultdict(dict)
        for user, vector in self.user_vectors.items():
            for track, value in vector.items():
                item_vectors[track][user] = math.log1p(value)
        self.similarity = defaultdict(dict)
        norms = {t: math.sqrt(sum(v * v for v in vec.values())) for t, vec in item_vectors.items()}
        for a, av in item_vectors.items():
            for b, bv in item_vectors.items():
                if a != b:
                    dot = sum(value * bv.get(user, 0) for user, value in av.items())
                    self.similarity[a][b] = dot / (norms[a] * norms[b]) if norms[a] * norms[b] else 0
        for session in sessions.values():
            # Adjacent only: a skipped track does not create a fictional transition.
            for a, b in zip(session, session[1:]):
                if a['completion'] >= .5 and b['completion'] >= .5:
                    self.transitions[a['track_id']][b['track_id']] += 1

    def recommend(self, user_id, limit=6, preferred_genres=(), strategy='hybrid', context_track=None):
        if strategy not in {'hybrid', 'collaborative', 'sequence', 'popularity'}:
            raise ValueError('Unknown recommendation strategy')
        if context_track is not None and context_track not in self.tracks:
            raise ValueError('Unknown context track')
        history = self.histories.get(user_id, [])
        last_track = context_track or (history[-1]['track_id'] if history else None)
        candidates = [t for t in self.tracks if t != last_track]
        cf = Counter()
        for seen, weight in self.user_vectors.get(user_id, {}).items():
            for candidate, similarity in self.similarity.get(seen, {}).items():
                cf[candidate] += math.log1p(weight) * similarity
        components = {
            'collaborative': normalize(cf, candidates),
            'sequence': normalize(self.transitions.get(last_track, {}), candidates),
            'popularity': normalize(self.popularity, candidates),
        }
        cold = not self.user_vectors.get(user_id)
        results = []
        for t in candidates:
            if cold and strategy == 'hybrid':
                score = .75 * (self.tracks[t]['genre_id'] in preferred_genres) + .25 * components['popularity'][t]
                reason = 'Genre-based discovery' if self.tracks[t]['genre_id'] in preferred_genres else 'Popular in the catalog'
            else:
                score = sum(WEIGHTS[k] * components[k][t] for k in WEIGHTS) if strategy == 'hybrid' else components[strategy][t]
                strongest = max(WEIGHTS, key=lambda k: WEIGHTS[k] * components[k][t]) if strategy == 'hybrid' else strategy
                reason = {'sequence': 'Often played next', 'collaborative': 'Similar listening patterns', 'popularity': 'Popular in the catalog'}[strongest]
            results.append({**self.tracks[t], 'score': round(score, 6), 'reason': reason,
                            'components': {k: round(v[t], 6) for k, v in components.items()}})
        return sorted(results, key=lambda r: (-r['score'], r['id']))[:limit]

    def albums(self, user_id, limit=4, **kwargs):
        grouped = defaultdict(list)
        for track in self.recommend(user_id, len(self.tracks), **kwargs):
            grouped[track['album_id']].append(track)
        albums = []
        for album_id, tracks in grouped.items():
            best = tracks[0]
            albums.append({'id': album_id, 'title': best['album'], 'artist': best['artist'],
                           'color': best['color'], 'score': round(sum(t['score'] for t in tracks) / len(tracks), 6),
                           'track_ids': [t['id'] for t in tracks]})
        return sorted(albums, key=lambda a: (-a['score'], a['id']))[:limit]
