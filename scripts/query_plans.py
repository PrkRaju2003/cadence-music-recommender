"""Record actual query plans and a small, explicitly local latency measurement."""
import sqlite3
import statistics
import time

from cadence.db import ROOT, database

QUERY = '''SELECT e.track_id,e.played_at FROM listening_sessions s
JOIN playback_events e ON e.session_id=s.id WHERE s.user_id=?
ORDER BY e.played_at DESC LIMIT 20'''


def measure(db):
    samples = []
    for _ in range(100):
        start = time.perf_counter()
        db.execute(QUERY, (1,)).fetchall()
        samples.append((time.perf_counter() - start) * 1000)
    return round(statistics.median(samples), 4)


def main():
    # Work on a disposable copy; production indexes are never changed.
    copy = sqlite3.connect(':memory:')
    with database() as db:
        db.backup(copy)
    lines = ['Recent listener history query', QUERY, '', 'WITH INDEXES:']
    lines += [r[3] for r in copy.execute('EXPLAIN QUERY PLAN ' + QUERY, (1,))]
    lines += [f'Median of 100 local reads: {measure(copy)} ms', '', 'WITHOUT EXPLICIT INDEXES:']
    indexes = [r[0] for r in copy.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")]
    for name in indexes:
        copy.execute('DROP INDEX "' + name.replace('"', '""') + '"')
    # A distinct statement avoids reusing sqlite3's prepared-statement cache.
    lines += [r[3] for r in copy.execute('EXPLAIN QUERY PLAN ' + QUERY + ' ', (1,))]
    lines += [f'Median of 100 local reads: {measure(copy)} ms', '',
              'Small 4,480-event synthetic dataset. Cache effects and hardware affect timings;',
              'these numbers do not establish production throughput or a universal speedup.']
    copy.close()
    (ROOT / 'docs/query-plan.txt').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
