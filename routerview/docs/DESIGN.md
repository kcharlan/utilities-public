# RouterView Design

> Last updated: 2026-07-26

## Overview

RouterView is now a CSV-only OpenRouter analytics dashboard. The application no longer accepts live observability data, manages tunnels, or talks to OpenRouter APIs. Its job is narrower and simpler:

1. import OpenRouter Activity CSV exports
2. store them locally in SQLite
3. render fast, calendar-aware analytics against that imported history

## Goals

- Keep imports safe to repeat
- Preserve imported history locally
- Make calendar-aligned analysis reliable for Today, Yesterday, week, month, quarter, and year views
- Keep the app single-file and uv-managed (PEP 723 header)
- Refresh the visible dashboard immediately after a successful CSV import

## Non-Goals

- Live OTLP ingestion
- OpenRouter Broadcast integration
- Cloudflare or ngrok tunnel setup
- OpenRouter API backfill or key management
- Real-time websocket updates
- Multi-user access or authentication

## Architecture

### Backend

- Python single-file launcher (uv-managed via a PEP 723 inline-metadata header)
- FastAPI for API routes and HTML serving
- SQLite for persistent storage
- Dependencies resolved by uv into its shared cache; no private venv under the home directory

### Frontend

- Embedded React SPA served from the Python file
- Fetch-based data loading
- No websocket client
- Settings panel used for CSV import, purge, and admin refresh actions

## Data Flow

1. User launches RouterView locally.
2. User imports an OpenRouter CSV file.
3. Backend parses each CSV row and inserts it into `generations`.
4. Duplicate `generation_id` rows are skipped.
5. Backend rebuilds daily summaries and anomaly baselines.
6. Frontend reloads summary, chart, breakdown, heatmap, and log data after a successful import.

## Import Semantics

### Source of Truth

`generations` is the canonical imported data set.

### Duplicate Handling

CSV imports use the OpenRouter `generation_id` as the primary key.

- first import of a row: inserted
- later import of the same row: skipped

This prevents re-imports from inflating totals and gives the user accurate import accounting.

### Refresh Behavior

The import endpoint completes its backend recomputation before returning success. The frontend treats a successful import as a data invalidation event and immediately reruns the active dashboard and log queries.

That behavior is specifically meant to keep the Today view current without requiring the user to change ranges.

### Timestamp Handling

Imported timestamps are normalized to UTC. An explicit timezone in the CSV takes precedence. For current OpenRouter IDs in the form `gen-<epoch>-<suffix>`, the embedded Unix epoch is used when a naive CSV timestamp disagrees with it; otherwise a naive timestamp is interpreted as UTC.

The Settings panel also exposes an explicit timestamp rebuild for previously imported rows. It creates a point-in-time SQLite backup before deriving timestamps from recoverable generation IDs, leaves IDs without an embedded epoch unchanged, and then refreshes summaries and anomaly baselines when rows changed.

## Storage

Runtime state lives under `~/.routerview/` by default; `ROUTERVIEW_HOME` overrides that directory:

- `routerview.db`, unless the CLI selects another database with `--db`
- `last_port`, recording the port selected at startup
- `backups/`, created on demand before timestamp rebuilds

Python dependencies are managed by uv (PEP 723 header) and cached in uv's shared cache, not under the runtime home.

RouterView enforces owner-only permissions on runtime directories (`0700`) and mutable files (`0600`). It rejects symbolic links in the runtime tree rather than following or modifying their targets.

## Key Tables

### `generations`

One row per imported request with timestamps, model/provider metadata, token counts, cost fields, latency, flags, and user-facing dimensions used by filters and breakdowns.

### `daily_summaries`

Materialized daily aggregates used by admin refresh tools and any precomputed daily reporting.

### `ingestion_log`

Stores import accounting such as inserted and skipped row counts.

### `settings`

Stores lightweight UI and app settings.

### `saved_views`

Stores named dashboard view configurations.

## HTTP Surface

The active surface area is intentionally smaller than earlier versions:

- analytics reads: summary, timeseries, breakdown, heatmap, generations, dimensions, export
- management writes: CSV import, purge, summary rebuild/refresh, timestamp rebuild, saved views

There are no live ingestion routes and no websocket route.

## UX Notes

- The dashboard opens directly; there is no setup wizard.
- The Settings panel is the import and maintenance surface.
- After import, the import result banner shows inserted vs skipped counts.
- The header no longer carries a live/disconnected indicator.
