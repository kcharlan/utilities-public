# MLS Tracker

A local dashboard for exploring MLS playoff races across both conferences. It pulls standings from the ESPN public API, applies team branding (colors and logos), and computes simplified scenarios by comparing a selected team with the team currently at a configurable cutoff position.

## Running

```bash
./mls_tracker
```

Requires [uv](https://docs.astral.sh/uv/) (`brew install uv`); the launcher uses a PEP 723 inline-metadata header. The first run resolves its dependencies (fastapi, uvicorn, requests) into uv's shared cache — that invocation may briefly hit the network; subsequent runs are fast. A browser tab opens automatically to `http://127.0.0.1:8501`.

The dashboard also needs internet access while running: the backend calls ESPN, and the frontend loads React, Babel, Tailwind CSS, Lucide Icons, and Google Fonts from CDNs.

### Options

```
--port PORT, -p PORT    Port to serve on (default: 8501)
--no-browser            Don't open browser automatically
```

## Features

- **Both conferences**: Eastern and Western Conference standings tables.
- **Dynamic team theming**: Colors and logos fetched from ESPN's teams API — no hardcoded team configs.
- **Configurable playoff cutoff**: Analyze scenarios against any position (default: 9th).
- **Cutoff-team status model**: Labels the target as clinched if its current points exceed the selected cutoff team's maximum, or eliminated if its own maximum falls below that team's current points.
- **Playoff scenarios**: Shows a wins-only path and a maximum-ties path to finish one point above the cutoff team's projected total.
- **Need-help analysis**: When the target's maximum is below the cutoff team's projected total, shows how many additional points that cutoff team can earn.
- **Dark mode**: Toggle or auto-detect from system preference, persisted in localStorage.
- **5-minute data cache** with manual refresh button.

The scenario model assumes a 34-game season and projects only the team currently occupying the selected cutoff position at its current points-per-game rate. It does not model the rest of the conference, MLS tiebreakers, schedule interactions, or competition-rule changes, so its status labels are exploratory rather than official clinch/elimination determinations.

## Architecture

Single-file FastAPI + embedded React SPA (no Node.js build tooling required).

- **Backend**: FastAPI + uvicorn serving JSON API endpoints and an HTML template.
- **Frontend**: React 18 + Tailwind CSS + Lucide Icons, all loaded via CDN with in-browser Babel JSX transpilation.
- **Data sources**:
  - Standings: `https://site.api.espn.com/apis/v2/sports/soccer/usa.1/standings?season={year}`
  - Teams: `https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/teams`

## API Endpoints

```
GET  /                              → React SPA
GET  /api/data?season={year}        → Conference standings + team metadata
GET  /api/scenarios?season=&team=&cutoff=  → Playoff scenarios for a team
POST /api/refresh                   → Invalidate data cache
```

## Tests

```bash
cd /path/to/utilities-public/mls-tracker
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest -q
```
