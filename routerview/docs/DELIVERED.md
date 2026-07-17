# RouterView Delivered Reference

## Overview

RouterView is a single-file, uv-managed Python application (PEP 723 header) for analyzing OpenRouter usage from CSV imports. It stores imported generations in SQLite and serves an embedded React dashboard for filtering, comparison, export, and log inspection.

## Data Ingestion

- **CSV import only** via `POST /api/import/csv`
- **Deduplication by `generation_id`** using `ON CONFLICT(id) DO NOTHING`
- **Duplicate accounting** reports repeated rows as `skipped`
- **Post-import refresh** rebuilds daily summaries, refreshes anomaly baselines, and the frontend reloads the active dashboard state immediately after a successful import

## Dashboard

- KPI cards for requests, cost, cost per request, latency, cache hit rate, and tokens
- Calendar-aligned time ranges plus custom ranges
- Comparison modes for prior period, DoD, WoW, MoM, QoQ, and YoY
- Area, line, bar, and heatmap chart modes
- Breakdown panels for model, API key, and provider
- Filter bar for model, provider, API key, origin, and finish reason
- Paginated generation log with search, sorting, configurable columns, and row expansion
- Saved views persisted in SQLite
- CSV and image export

## Settings Panel

- CSV import
- Database health summary
- Purge by date
- Summary refresh controls

There is no live OpenRouter broadcast setup, tunnel management, API backfill, or websocket status indicator in the current build.

## Architecture

- Single Python file: FastAPI backend plus embedded React SPA
- uv-managed via a PEP 723 header (dependencies resolved into uv's shared cache; no private venv)
- Runtime state under `~/.routerview/`
- SQLite database at `~/.routerview/routerview.db`

## Database Tables

- `generations` - one row per imported OpenRouter generation
- `daily_summaries` - materialized daily aggregates
- `ingestion_log` - import run accounting
- `settings` - UI and system settings
- `saved_views` - named dashboard configurations

## API Endpoints

### Primary UI

| Method | Path | Description |
|---|---|---|
| GET | `/` | Serve the embedded dashboard |
| GET | `/api/health` | Health summary and database stats |
| GET | `/api/settings` | Read stored settings |
| PUT | `/api/settings` | Update settings |

### Analytics Data

| Method | Path | Description |
|---|---|---|
| GET | `/api/summary` | KPI summary for a range |
| GET | `/api/timeseries` | Chart series for a range |
| GET | `/api/breakdown` | Breakdown aggregates |
| GET | `/api/heatmap` | Hour-by-day usage heatmap |
| GET | `/api/generations` | Paginated generation log |
| GET | `/api/dimensions` | Filter dimension values |
| GET | `/api/export/csv` | Export generations, summary, or breakdown data |

### Data Management

| Method | Path | Description |
|---|---|---|
| POST | `/api/import/csv` | Import an OpenRouter CSV export |
| POST | `/api/purge` | Delete data before a date |
| POST | `/api/admin/refresh-summaries` | Refresh summaries for the last 2 days |
| POST | `/api/admin/rebuild-summaries` | Full summary rebuild |
| GET | `/api/views` | List saved views |
| POST | `/api/views` | Create or update a saved view |
| DELETE | `/api/views/{id}` | Delete a saved view |

## CLI

```text
routerview [-p PORT] [--db PATH] [--host HOST] [--debug]
```

| Flag | Default | Description |
|---|---|---|
| `-p/--port` | 8100 | Preferred port, auto-increments if busy |
| `--db` | `~/.routerview/routerview.db` | SQLite database path |
| `--host` | `127.0.0.1` | Bind address |
| `--debug` | off | Verbose server logging |

## Known Limitations

- CSV import is the only ingestion path
- Imports depend on the fields present in the OpenRouter export
- Desktop-first layout
- Single-user, no authentication
- No live ingestion or external OpenRouter integration
