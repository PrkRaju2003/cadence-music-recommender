import csv

from cadence.db import database
from cadence.export import export


def test_powerbi_exports_reconcile_and_are_deidentified(db_path, tmp_path):
    with database(db_path) as db:
        export(db, tmp_path / 'exports')
    root = tmp_path / 'exports'
    with (root / 'Playback.csv').open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 4480
    assert sum(float(r['completion']) for r in rows) > 0
    with (root / 'Users.csv').open() as stream:
        users = list(csv.DictReader(stream))
    assert len(users) == 40
    assert 'email' not in users[0]
    assert all(u['listener'].startswith('Listener ') for u in users)
    with (root / 'ModelEvaluation.csv').open() as stream:
        assert len(list(csv.DictReader(stream))) == 4
