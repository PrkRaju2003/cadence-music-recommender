"""Export de-identified analytics tables for the included Power BI project."""
import csv
from pathlib import Path

from .db import ROOT, database
from .evaluate import evaluate


def write_csv(path, rows, fields):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def export(connection, directory=None):
    directory = Path(directory or ROOT / 'exports')
    directory.mkdir(parents=True, exist_ok=True)
    queries = {
        'Playback': 'SELECT * FROM playback_fact ORDER BY event_id',
        'Tracks': 'SELECT id AS track_id,title,album_id,album,artist,genre,duration_ms FROM track_catalog',
        'Users': "SELECT id AS user_id,'Listener ' || id AS listener FROM users",
        'RecommendationRequests': 'SELECT id AS request_id,user_id,requested_at,model_version,strategy,latency_ms FROM recommendation_requests',
        'RecommendationItems': 'SELECT * FROM recommendation_items',
    }
    for name, query in queries.items():
        cursor = connection.execute(query)
        fields = [c[0] for c in cursor.description]
        write_csv(directory / f'{name}.csv', [dict(r) for r in cursor], fields)
    metrics = evaluate(connection)['results']
    write_csv(directory / 'ModelEvaluation.csv', metrics, list(metrics[0]))
    return directory


if __name__ == '__main__':
    with database() as connection:
        print(export(connection))
