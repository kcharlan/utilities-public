# Git Fleet

A local multi-repo git dashboard built for monorepos and multi-project setups. Track working state, commit history, branch staleness, and dependency health across all your projects from a single browser tab.

## Quick Start

```bash
./git_dashboard.py
```

Git Fleet runs via [uv](https://docs.astral.sh/uv/) (`brew install uv`) using a PEP 723 inline-metadata header. On first run it creates its runtime home at `~/.git_dashboard/`; uv resolves the dependencies (fastapi, uvicorn[standard], aiosqlite, packaging, pydantic) into its shared cache — that first invocation may briefly hit the network. No manual setup and no virtual environment in your home directory are required. The dashboard opens in your browser at `http://localhost:8300`.

To register a directory of repos on launch:

```bash
./git_dashboard.py --scan ~/source/my-projects
```

## Requirements

- **[uv](https://docs.astral.sh/uv/)** (`brew install uv`) — manages the Python interpreter and dependencies
- **git** in PATH

Optional ecosystem tools enable dependency health checking. Git Fleet launches silently without them — missing tools are detected per-repo at scan time and flagged in the UI only when relevant:

| Ecosystem | Outdated checks | Vulnerability scanning |
|-----------|-----------------|------------------------|
| Python    | PyPI JSON API (built-in) | `pip-audit` |
| Node.js   | `npm outdated` | `npm audit` |
| Go        | `go list -m -u` | `govulncheck` |
| Rust      | `cargo-outdated` | `cargo-audit` |
| Ruby      | `bundle outdated` | `bundler-audit` |
| PHP       | `composer outdated` | `composer audit` |

## Features

### Fleet Overview
Browse all registered repos at a glance. Each card shows current branch, last commit, uncommitted change counts, dependency status (with a green/amber coverage dot indicating tool completeness), and a 13-week activity sparkline. KPI tiles summarize fleet-wide commit velocity, branch health, and dependency status — hover any KPI for a description. Cards with missing disk paths or scan errors are flagged visually.

### Directory Browser
A built-in file browser lets you navigate your filesystem and register directories without touching the command line. Git repos are identified with visual indicators. Click **Scan Dir** in the header to open.

### Full Scan
Runs three passes across all registered repos:

1. **History scan** — aggregates `git log` into daily commit/insertion/deletion stats (incremental; only fetches new data on subsequent runs)
2. **Branch scan** — lists all local branches, marks stale branches (>30 days since last commit), identifies the default branch
3. **Dependency scan** — detects manifest files (`requirements.txt`, `package.json`, `go.mod`, `Cargo.toml`, `Gemfile`, `composer.json`) up to 3 directories deep, parses dependencies, and runs ecosystem health checks

Progress streams in real time via SSE to a toast notification in the UI.

### Monorepo Support
Dependency detection walks subdirectories (up to 3 levels), so monorepos with multiple projects are fully supported. Each dependency tracks its `source_path` — the relative path to the manifest file it came from (e.g., `web_games/multibody_sim/package.json`). The Dependencies tab groups packages by manifest location so you can tell exactly which sub-project owns each dependency.

### Repo Detail View
Click any repo card to drill into four sub-tabs:

- **Activity** — daily commit chart with configurable time ranges (30d / 90d / 180d / 1y / All)
- **Dependencies** — packages grouped by ecosystem and source path, with an **Attention Required** section that surfaces vulnerable, major, and outdated packages at the top. Includes **Export MD** and **Export JSON** buttons for offline reporting and a **Check Now** button for on-demand re-scan. When analysis tools are missing for a repo's ecosystem, an amber notice identifies exactly which tools are needed.
- **Branches** — all local branches with commits ahead, +/− line stats, files changed (vs default branch), last commit date, and stale/active/default badges. Click any branch to select it and auto-navigate to its commits.
- **Commits** — paginated commit history for the selected branch, with date, message, and diffstat. Branch selection persists across tab switches; the header shows which branch you're viewing.

The branch displayed in the repo header is interactive — click it to jump to the Branches tab.

### Analytics
Fleet-wide analytics across all repos:

- **Commit heatmap** — calendar-style daily commit volume
- **Time allocation** — commit distribution across repos
- **Dependency overlap** — packages shared across multiple repos with version spread

### Delete & Cleanup
Hover any repo card to reveal the delete button. Removing a repo deletes all associated data (branches, dependencies, scan history) via cascading foreign keys.

## Usage

```
python git_dashboard.py [options]

Options:
  --port N       Port to listen on (default: 8300; auto-increments if in use)
  --no-browser   Skip opening a browser tab on startup
  --scan PATH    Register and scan a directory on startup
  --help         Show this message and exit
```

## Data Storage

| Item | Location |
|------|----------|
| Database | `~/.git_dashboard/dashboard.db` (SQLite, WAL mode) |

Python dependencies are managed by uv (declared in the launcher's PEP 723 header) and cached in uv's shared cache, not under `~/.git_dashboard/`. The database path can be overridden with the `GIT_DASHBOARD_DB` environment variable.

## Architecture

Single-file Python application (`git_dashboard.py`), uv-managed via a PEP 723 header. The backend is FastAPI + uvicorn with aiosqlite for async database access. The frontend is a React 18 SPA loaded via CDN (React, ReactDOM, Babel Standalone, Recharts) — no build step, no `node_modules`. All JSX is embedded in the Python file as a template string served from `GET /`.

### Database Schema

Six tables with cascading foreign keys:

- **repositories** — registered repos with path, detected runtime, default branch
- **working_state** — current status snapshot (uncommitted changes, current branch, scan errors, missing dependency tools per repo)
- **daily_stats** — historical commit/insertion/deletion rollups by date
- **branches** — branch names, last commit dates, staleness flags
- **dependencies** — parsed manifest entries with version, severity, advisory, and source path
- **scan_log** — scan execution history (type, status, timing, repos scanned)

## Development

The tracked test requirements reproduce the launcher imports plus test-only dependencies in a project venv.

```bash
# Create test venv and install deps
python3 -m venv .venv
.venv/bin/pip install -r tests/requirements-test.txt

# Run unit tests
.venv/bin/python -m pytest tests/ --ignore=tests/test_e2e.py -v

# Run E2E tests (requires the Playwright add-on)
.venv/bin/pip install playwright pytest-playwright
.venv/bin/playwright install chromium
.venv/bin/python -m pytest tests/test_e2e.py -v
```

E2E tests must run in a separate pytest invocation from unit tests (Playwright's event loop conflicts with `asyncio.run()`). The E2E test server uses an isolated temp database so test repos never pollute user data.

## Cross-Platform Notes

- Works on **Windows 10+**, **macOS 12+**, and **Linux** — uv manages the interpreter and dependencies on every platform.
- On macOS/Linux invoke as `./git_dashboard.py`; on Windows use `uv run --script git_dashboard.py`.
- Paths with spaces are handled correctly via `pathlib.Path`.
