"""Global temporal split, one next-play target per eligible user, no future events."""
import json
import math
from collections import defaultdict

from .db import ROOT, catalog, database, interactions
from .recommender import HybridRecommender, MODEL_VERSION

CUTOFF = '2026-10-22T00:00:00+00:00'


def evaluate(connection, k=5):
    # Demo interactions after the seed period do not alter this fixed benchmark.
    events = [e for e in interactions(connection) if e['played_at'] < '2026-10-29']
    train = [e for e in events if e['played_at'] < CUTOFF]
    heldout = defaultdict(list)
    for e in events:
        if e['played_at'] >= CUTOFF and e['completion'] >= .5:
            heldout[e['user_id']].append(e)
    model = HybridRecommender(catalog(connection), train)
    targets = {user: rows[0]['track_id'] for user, rows in heldout.items() if model.user_vectors.get(user)}
    rows = []
    for strategy in ['popularity', 'collaborative', 'sequence', 'hybrid']:
        hits = ndcg = mrr = 0.0
        coverage = set()
        for user, target in targets.items():
            recommended = model.recommend(user, k, strategy=strategy)
            ids = [r['id'] for r in recommended]
            coverage.update(ids)
            if target in ids:
                rank = ids.index(target) + 1
                hits += 1
                ndcg += 1 / math.log2(rank + 1)
                mrr += 1 / rank
        n = len(targets)
        rows.append({'strategy': strategy, 'k': k, 'users': n,
                     'hit_rate': round(hits / n, 4) if n else 0,
                     'ndcg': round(ndcg / n, 4) if n else 0,
                     'mrr': round(mrr / n, 4) if n else 0,
                     'catalog_coverage': round(len(coverage) / len(model.tracks), 4) if model.tracks else 0})
    return {'model': MODEL_VERSION, 'cutoff': CUTOFF, 'train_events': len(train),
            'eligible_users': len(targets), 'results': rows,
            'limitations': 'Synthetic behavioral patterns, 24 tracks, one next-positive-play target per user. Includes repeat listening. Not evidence of production quality or causal uplift.'}


def main():
    with database() as connection:
        report = evaluate(connection)
    target = ROOT / 'docs/evaluation.json'
    target.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
