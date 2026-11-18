"""Export deterministic synthetic data into small, resumable SQL batches.

This script reads only a freshly seeded in-memory SQLite database. It never
exports private Supabase accounts or real user playback history.
"""
import sqlite3
from pathlib import Path

from cadence.db import ROOT, initialize
from cadence.seed import seed


def literal(value):
    if value is None:
        return 'NULL'
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def main():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    initialize(db)
    seed(db)
    statements = []
    for table in ['genres','artists','albums','tracks','users','user_genres','listening_sessions','playback_events']:
        for row in db.execute(f'SELECT * FROM {table}'):
            values = dict(row)
            if table == 'users':
                values['is_demo'] = True
            if table == 'listening_sessions':
                values['ended_at'] = None
            columns = ','.join(values)
            vals = ','.join('true' if v is True else literal(v) for v in values.values())
            statements.append(f'INSERT INTO cadence.{table} ({columns}) VALUES ({vals}) ON CONFLICT DO NOTHING;')
    for row in db.execute('SELECT id,ended_at FROM listening_sessions'):
        statements.append(f'UPDATE cadence.listening_sessions SET ended_at={literal(row[1])} WHERE id={literal(row[0])};')
    for table in ['genres','artists','albums','tracks','users','playback_events']:
        statements.append(f"SELECT setval(pg_get_serial_sequence('cadence.{table}','id'),(SELECT max(id) FROM cadence.{table}),true);")
    target = ROOT/'supabase/seed'
    target.mkdir(parents=True,exist_ok=True)
    for index, offset in enumerate(range(0,len(statements),500),1):
        (target/f'{index:02}.sql').write_text('-- Synthetic seed data only. Apply in filename order.\nBEGIN;\n'+ '\n'.join(statements[offset:offset+500])+'\nCOMMIT;\n')
    db.close()
    print(f'Generated {index} SQL seed batches from the fixed synthetic dataset.')


if __name__=='__main__':
    main()
