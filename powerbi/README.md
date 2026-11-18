# Cadence Power BI report project

Two source-controlled report pages and an import semantic model:

1. **Engagement:** total plays, distinct listeners, completion rate, skip rate, daily plays, genre distribution, artist engagement.
2. **Model behavior:** recommendation requests, measured ranking latency, track exposure, strategy mix, and offline ranking metrics.

## Open and refresh (Windows)

Use a current version of Power BI Desktop with Power BI Project/PBIP and enhanced report/PBIR support enabled. This project uses TMSL (`model.bim`) for the semantic model, not TMDL.

From the repository root, after installing Python requirements:

```powershell
python -m cadence.seed
python -m cadence.export
python scripts/configure_powerbi.py --data-dir .\exports
```

Open `powerbi/Cadence.pbip` in Power BI Desktop and choose **Refresh**. The `DataFolder` parameter must point to the absolute location of your CSV exports. The configuration script changes it only on your local checkout; avoid committing personal filesystem paths. Alternatively, edit the parameter in Power Query.

The repository includes sample CSVs so the report can be explored without running the API. Recommendation-request charts reflect actual requests made in the demo; a freshly seeded database has no requests until the app is used. Export again after testing the app to refresh these charts.

## Validation boundary

Report JSON is validated against Microsoft's official schemas by `python scripts/validate_powerbi.py`. Tests also check visual-to-model field references and CSV-to-model column alignment. These checks do **not** execute DAX, refresh Power Query, or prove Desktop rendering. Power BI Desktop was unavailable on the macOS authoring machine; opening, refreshing, and checking the report on Windows is still required before claiming a completed Power BI dashboard or publishing it to the Power BI service.

## Data and metric definitions

- `Playback`: one recorded playback event; completion is played milliseconds divided by track duration. Pausing/resuming does not create a new event. Track changes, completion, and best-effort page-exit flushing do.
- `Users` and `Tracks`: dimension tables. User export omits emails and replaces names with `Listener <id>`.
- `RecommendationRequests`: model version, strategy, request time, and measured fitting-plus-ranking latency.
- `RecommendationItems`: one row per exposed track per request, with rank and score. Album requests are logged, but album exposure rows are not included in this track-only fact table.
- `ModelEvaluation`: one row per strategy on the fixed chronological synthetic benchmark. Do not treat offline hit rate as a production conversion metric.

Relationships use single-direction filtering from dimensions to facts. `ModelEvaluation` is intentionally disconnected because it summarizes a fixed experiment rather than a slice of live playback data.

The generation script is `scripts/build_powerbi.py`; it regenerates definitions and resets the CSV parameter. The `report.json` uses the Desktop default theme to avoid missing custom theme resources.

References: [PBIP](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview), [PBIR](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report), [semantic model files](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-dataset), [official JSON schemas](https://github.com/microsoft/json-schemas).
