# Git Fleet

Git Fleet is a local browser dashboard for tracking many Git repositories. It combines live working-tree state with stored commit, branch, and dependency data so a collection of projects can be reviewed from one place.

## Quick start

Git Fleet is a [uv](https://docs.astral.sh/uv/) script and requires Python 3.12 or newer.

```bash
./git_dashboard.py
```

On Windows, or on Unix systems where the executable bit is unavailable:

```bash
uv run --script git_dashboard.py
```

The first run may download the declared Python dependencies into uv's shared cache. Git Fleet creates `~/.git_dashboard/dashboard.db`, selects the first free loopback port from 8300 through 8319, and opens the dashboard in the default browser.

To discover and register Git repositories below a directory before startup:

```bash
./git_dashboard.py --scan ~/source
```

`--scan` registers repositories. The browser's initial fleet request then performs the live quick scan; use **Full Scan** to populate history, branches, and dependency health.

## Requirements

- [uv](https://docs.astral.sh/uv/) (`brew install uv` on macOS)
- Git in `PATH`
- Network access on first launch and when loading the browser UI, which uses pinned React, Babel, Recharts, and font CDN assets

Git Fleet also requires at least one installed dependency-analysis tool from the ecosystems below. It starts when some tools are missing and shows their availability in the UI; it exits if none of the primary tools or `pip-audit` can be found.

| Ecosystem | Outdated check | Vulnerability check |
| --- | --- | --- |
| Python | PyPI JSON API (no extra CLI) | `pip-audit` |
| Node.js | `npm outdated` | `npm audit` |
| Go | `go list -m -u` | `govulncheck` |
| Rust | `cargo-outdated` | `cargo-audit` |
| Ruby | `bundle outdated` | `bundler-audit` |
| PHP | `composer outdated` | `composer audit` |

## What it shows

### Fleet overview

The overview quick-scans up to eight registered repositories concurrently whenever it loads. Cards show the current branch, most recent commit, staged/modified/untracked counts, dependency summary, branch health, and a 13-week activity sparkline. Fleet KPIs summarize repository state, recent commits and line changes, stale branches, and dependency findings.

The **Scan Dir** browser can navigate local directories and register repositories without a command-line path. Discovery skips hidden, generated, virtual-environment, and dependency directories and does not descend into a repository after finding its `.git` entry.

### Full scan

A full scan processes registered repositories sequentially and stores three kinds of data:

1. Commit history, aggregated by day. Later scans are incremental from `last_full_scan_at`.
2. Local branches, including default/stale status. A non-default branch is stale after 30 days without a commit.
3. Dependencies and health results for supported manifests.

Progress is streamed to the browser with server-sent events. Only one fleet scan may run at a time. Missing paths and per-repository scan failures are retained as visible error state.

### Repository detail

Each repository has four views:

- **Activity** — commit, insertion, and deletion history for 30 days, 90 days, 180 days, one year, or all stored history.
- **Dependencies** — packages grouped by ecosystem and manifest path, with vulnerable and outdated packages surfaced first. Results can be rescanned on demand or exported as Markdown or JSON.
- **Branches** — local branches with default/stale status and live commits-ahead and diff statistics against the default branch.
- **Commits** — paginated live Git history for all refs or a selected branch.

If a registered repository moves, its path can be repaired from the detail view. Removing a repository cascades to its stored working state, history, branches, and dependency rows.

### Analytics

Fleet-wide analytics include a one-year commit heatmap, configurable time-allocation charts, and dependency overlap across repositories.

## Dependency discovery

Git Fleet searches the repository root and subdirectories up to three levels deep, while skipping common generated and vendored directories. It recognizes:

- `pyproject.toml` or `requirements.txt`
- `package.json`
- `go.mod`
- `Cargo.toml`
- `Gemfile`
- `composer.json`

Within one directory, `pyproject.toml` takes precedence over `requirements.txt`. A dependency row records the manifest path that supplied it. The current schema identifies a package by repository, package manager, and package name, so repeated declarations of the same package within one repository are represented once.

## Command-line options

```text
usage: git_dashboard [-h] [--port N] [--no-browser] [--scan PATH] [-y]

--port N       Preferred port (default 8300); checks up to 20 consecutive ports
--no-browser   Do not open a browser tab
--scan PATH    Discover and register repositories below PATH before serving
-y, --yes      Accepted for backward compatibility; currently has no effect
```

`GIT_DASHBOARD_NO_BROWSER=1` also suppresses browser launch. The server binds only to `127.0.0.1`.

## Data and configuration

| Item | Default | Override |
| --- | --- | --- |
| Runtime home | `~/.git_dashboard/` | `GIT_DASHBOARD_HOME` |
| SQLite database | `~/.git_dashboard/dashboard.db` | `GIT_DASHBOARD_DB` |

SQLite uses WAL mode and enables foreign-key enforcement for application connections. Mutable state stays outside the repository.

## Architecture

The application intentionally remains one uv-managed Python file:

- FastAPI and uvicorn provide the local HTTP server.
- aiosqlite provides asynchronous database access.
- Git commands use asynchronous subprocesses without shell interpolation.
- A React 18 SPA, its CSS, and all JSX are embedded in `git_dashboard.py` and served by `GET /`; there is no frontend build or `node_modules`.
- Hash routes select the Fleet, Analytics, and repository detail views.

The six SQLite tables are:

- `repositories` — registered path, runtime classification, default branch, and scan timestamps
- `working_state` — the latest quick-scan snapshot and error flags
- `daily_stats` — per-day commit and line-change aggregates
- `branches` — the latest local branch snapshot
- `dependencies` — parsed package and health data
- `scan_log` — fleet scan lifecycle and counts

The maintained design and API reference is [docs/git_dashboard_final_spec.md](docs/git_dashboard_final_spec.md).

## Development

All Python execution must use a virtual environment. The tracked requirements reproduce the launcher dependencies plus unit-test dependencies:

```bash
python3 -m venv .venv
.venv/bin/pip install -r tests/requirements-test.txt
.venv/bin/python -m pytest tests/ --ignore=tests/test_e2e.py -v
```

Install the Playwright add-on and browser to run the E2E suite:

```bash
.venv/bin/pip install playwright pytest-playwright
.venv/bin/playwright install chromium
.venv/bin/python -m pytest tests/test_e2e.py -v
```

Run E2E tests separately from the unit suite because Playwright's event loop conflicts with tests that use `asyncio.run()`. E2E startup uses an isolated temporary database and suppresses automatic browser launch.

After changing the launcher's PEP 723 header or bootstrap imports, run the repository-wide uv header guard from the monorepo root:

```bash
uv run --script tools/check_uv_headers.py
```

## Platform notes

The code supports macOS, Linux, and Windows. Unix users can run the executable directly; Windows users should use `uv run --script git_dashboard.py`. Local paths are handled with `pathlib`, and subprocess commands pass arguments directly rather than through a shell.
