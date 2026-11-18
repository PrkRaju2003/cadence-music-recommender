"""Named, bounded read-only reports. This is not an arbitrary SQL console."""
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


class ReportInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    report_id: Literal['top_tracks','daily_activity','catalog_summary']
    limit: int = Field(default=20, ge=1, le=50, strict=True)


REPORTS = [
    {'id':'top_tracks','name':'My top tracks','columns':['title','artist','plays','completion_pct'],
     'sql':'''SELECT c.title, c.artist, COUNT(*) AS plays,
       ROUND(AVG(f.completion) * 100, 1) AS completion_pct
FROM cadence.playback_fact f
JOIN cadence.track_catalog c ON c.id = f.track_id
WHERE f.user_id = cadence.current_user_id()
GROUP BY c.id, c.title, c.artist
ORDER BY plays DESC, c.title
LIMIT :limit;'''},
    {'id':'daily_activity','name':'My daily activity','columns':['play_date','plays','minutes'],
     'sql':'''SELECT play_date, COUNT(*) AS plays,
       ROUND(SUM(played_ms) / 60000.0, 2) AS minutes
FROM cadence.playback_fact
WHERE user_id = cadence.current_user_id()
GROUP BY play_date
ORDER BY play_date DESC
LIMIT :limit;'''},
    {'id':'catalog_summary','name':'Catalog by genre','columns':['genre','tracks','albums'],
     'sql':'''SELECT genre, COUNT(*) AS tracks,
       COUNT(DISTINCT album_id) AS albums
FROM cadence.track_catalog
GROUP BY genre
ORDER BY genre
LIMIT :limit;'''},
]


def local_report(db, report, limit, user_id=1):
    sql = report['sql'].replace('cadence.current_user_id()', ':user_id').replace('cadence.', '')
    return [dict(r) for r in db.execute(sql, {'user_id':user_id,'limit':limit})]
