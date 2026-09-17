# RouterView

A self-hosted OpenRouter analytics dashboard for CSV imports. Import OpenRouter Activity exports into a local SQLite database, keep the history indefinitely, and analyze usage with calendar-aligned ranges, comparisons, breakdowns, exports, and a full request log.

## Quick Start

RouterView runs via [uv](https://docs.astral.sh/uv/) (`brew install uv`) using a PEP 723 inline-metadata header. No manual environment setup is required to run it.

1. Start the app from this directory:
   ```zsh
   ./routerview
   ```
2. Open Settings in the UI and import an OpenRouter Activity CSV export.

On first run RouterView creates its runtime home at `~/.routerview/`; uv resolves the dependencies (fastapi, uvicorn[standard], aiosqlite, python-multipart) into its shared cache — that first invocation may briefly hit the network. No virtual environment is written to your home directory.

The dashboard loads React 19.3.0, ReactDOM 19.3.0, react-is 19.3.0,
Recharts 3.10.1, Babel Standalone 8.0.5, and exact-version
`@tailwindcss/browser` 4.3.3 from public CDNs, so the browser needs network
access unless those assets are already cached.

To make `routerview` available on your `PATH`, create an optional symlink from this directory:

```zsh
ln -s "$(pwd)/routerview" /usr/local/bin/routerview
```

## CLI

```text
routerview [-p <port>] [--db <path_to_db>] [--host <bind_host>] [--debug]
```

- `-p`, `--port` preferred local port, default `8100`
- `--db` SQLite database path, default `~/.routerview/routerview.db`
- `--host` bind address, default `127.0.0.1`
- `--debug` verbose server logging

## Current Workflow

1. Export usage from OpenRouter as CSV.
2. Import the file through RouterView.
3. Re-import safely when needed. Duplicate `generation_id` rows are skipped and reported as skipped.
4. Explore usage with time ranges such as Today, Yesterday, This Month, or custom windows.

The dashboard refreshes immediately after a successful CSV import, including the active Today view.

## Key Features

- CSV import for OpenRouter Activity exports
- Calendar-aligned ranges and prior-period comparison modes
- KPI cards, timeseries charts, heatmap, and breakdown panels
- Multi-dimensional filters for model, provider, API key, origin, and finish reason
- Paginated generation log with search, sorting, and row expansion
- CSV export for the generation log and breakdown panels; SVG, PNG, and JPG chart export
- Saved views and keyboard shortcuts
- Local SQLite retention in a configurable runtime directory

## Architecture

- Single-file Python/FastAPI backend with an embedded React SPA
- SQLite for storage
- uv-managed via a PEP 723 header, with no repo-local install step

### Frontend compatibility boundary

The embedded, build-free SPA uses an exact-version import map for React 19.3.0,
ReactDOM 19.3.0, and react-is 19.3.0. Babel Standalone 8.0.5 compiles the
module-aware inline JSX, and Recharts 3.10.1 is loaded as ESM while
externalizing those mapped peers so the page has one React graph. Chart
interactions use public tooltip, legend, shape, and cell callbacks rather than
Recharts 2 chart-state fields. Tailwind uses the exact `@tailwindcss/browser`
4.3.3 package with CSS-first `@theme` tokens and an explicit class-based
dark-mode variant. These pins lock direct top-level package versions, but
runtime CDN delivery is not byte-immutable and CDN-generated transitive
dependencies are not fully locked; uncached startup still requires network
access.

### Browser support

The automated browser suite runs with current Playwright Chromium and verifies
the React/Recharts peer resource graph, Tailwind resource graph, custom-theme
and dark-mode computed styles, dark-mode restoration, chart/filter
interactions, and page/console error cleanliness. The ESM frontend requires a
browser with import-map and JavaScript-module support.
Tailwind 4's manual client floors for this browser-delivered UI are Chrome 111,
Safari 16.4, and Firefox 128. Safari and Firefox are not covered by the
automated browser test, so browser-specific behavior on those clients requires
manual verification.

The current design is documented in [docs/DESIGN.md](docs/DESIGN.md).

## Documentation

- [Design Document](docs/DESIGN.md) - current CSV-only architecture and data flow
- [Setup Guide](docs/SETUP_GUIDE.md) - first-run and CSV import workflow

## Data Storage

RouterView stores runtime state under `~/.routerview/` by default. Set `ROUTERVIEW_HOME` to use a different runtime directory.

- `routerview.db` SQLite database, unless `--db` selects another path
- `last_port` last port selected at startup
- `backups/` point-in-time SQLite backups created before timestamp rebuilds

The runtime directory and its subdirectories use owner-only permissions (`0700`); the database, SQLite sidecars, port file, backup files, and other mutable runtime files use `0600`. RouterView hardens existing more-permissive state on startup and refuses symbolic links inside the runtime tree rather than following or changing their targets.

Python dependencies are managed by uv (declared in the launcher's PEP 723 header) and cached in uv's shared cache — not under `~/.routerview/`.

## Tests

```bash
cd /path/to/utilities-public/routerview
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
```
