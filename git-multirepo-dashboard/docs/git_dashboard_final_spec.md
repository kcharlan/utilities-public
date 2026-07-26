# Git Fleet: Current Design Reference

**Status:** Implemented and maintained
**Last reconciled with code:** 2026-07-26

This document records the durable architecture and behavioral contracts of Git Fleet. It replaces the original implementation-oriented specification, whose bootstrap, schema, and milestone descriptions had diverged from the completed application. `git_dashboard.py` remains the executable source of truth.

## Product boundary

Git Fleet is a single-user, local-only dashboard for observing multiple Git repositories. It provides:

- live working-tree and most-recent-commit state
- stored daily commit history and branch snapshots
- dependency discovery and ecosystem-specific health checks
- fleet and repository-level visualizations

It does not modify repository contents, check out branches, install ecosystem tools, update dependencies, or expose a remotely accessible service. Repository removal affects only Git Fleet's database.

## Delivery architecture

The product is deliberately delivered as one executable Python file:

```text
git-multirepo-dashboard/
  git_dashboard.py
  README.md
  pytest.ini
  tests/
```

`git_dashboard.py` has a canonical uv shebang and PEP 723 dependency block:

- Python 3.12+
- FastAPI
- uvicorn with standard extras
- aiosqlite
- packaging
- pydantic

There is no application-managed virtual environment and no frontend build. uv resolves and caches Python dependencies. The React 18 SPA, CSS, and JSX are embedded in `HTML_TEMPLATE`; ReactDOM, PropTypes, Babel Standalone, Recharts, and fonts load from pinned public CDNs.

The FastAPI application binds to `127.0.0.1`. Port 8300 is preferred, but startup probes as many as 20 consecutive ports and uses the first available one. Automatic browser launch can be disabled with `--no-browser`, `GIT_DASHBOARD_NO_BROWSER`, or test mode.

## Runtime state

Runtime paths are resolved once when the module loads:

| State | Default | Override |
| --- | --- | --- |
| Runtime home | `~/.git_dashboard` | `GIT_DASHBOARD_HOME` |
| Database | `<runtime-home>/dashboard.db` | `GIT_DASHBOARD_DB` |

The runtime home contains mutable state only. SQLite is initialized idempotently, uses WAL mode, and has small additive migrations for columns introduced after the first schema version.

## Startup contracts

Startup performs these steps:

1. Parse `--port`, `--no-browser`, `--scan`, and the backward-compatible no-op `--yes` flag.
2. Require Python 3.12 or newer and Git in `PATH`.
3. Discover optional ecosystem tools and require at least one of `npm`, `go`, `cargo`, `bundle`, `composer`, or `pip-audit`.
4. Create and migrate the SQLite database.
5. If `--scan PATH` is supplied, recursively discover and register repositories below the path.
6. Select a free loopback port, optionally schedule browser launch, register signal handlers, and start uvicorn.

Missing individual ecosystem tools do not stop startup. Their paths or null values are exposed by `GET /api/status` for the UI's tool-status banner. The application does not prompt for confirmation.

`--scan` performs discovery and registration only. A live quick scan occurs when the browser loads the fleet endpoint; history, branch, and dependency data are populated by a full or dependency scan.

## Data model

The database has six tables.

### `repositories`

The durable registry. IDs are the first 16 hexadecimal characters of SHA-256 over the resolved absolute path.

Key fields:

- `id`, `name`, unique `path`
- `default_branch`, `runtime`
- `added_at`, `last_quick_scan_at`, `last_full_scan_at`

### `working_state`

One latest quick-scan snapshot per repository:

- dirty flag and modified, untracked, and staged counts
- current branch
- latest commit hash, message, and date
- check timestamp
- `scan_error` and `dep_check_error`

### `daily_stats`

Daily aggregates keyed by repository and date:

- commits
- insertions and deletions
- files changed

### `branches`

The latest local-branch snapshot keyed by repository and branch name:

- last commit date
- default-branch flag
- stale flag

The default branch is never presented as stale even if its stored date exceeds the threshold.

### `dependencies`

Dependency health keyed by repository, manager, and package name:

- current, wanted, and latest versions
- severity: `ok`, `outdated`, `major`, or `vulnerable`
- advisory identifier and check timestamp
- manifest `source_path`

Because `source_path` is not part of the primary key and parsing deduplicates by manager/name, repeated declarations of the same package within one repository are represented once.

### `scan_log`

Fleet scan records:

- scan type (`full` or `deps`)
- start and finish timestamps
- repositories scanned
- lifecycle status (`running`, `completed`, or `failed`)

All repository-owned tables reference `repositories` with cascading deletion. API database connections enable foreign-key enforcement.

## Repository discovery and runtime classification

Discovery walks a selected root recursively, pruning hidden directories and common generated directories such as `.venv`, `node_modules`, `dist`, and `build`. It recognizes a repository when a `.git` entry exists, verifies/deduplicates the top level with `git rev-parse --show-toplevel`, and stops descending below that repository.

Runtime classification checks root-level manifests for Python, Node.js, Go, Rust, Ruby, PHP, and Docker. Multiple non-Docker ecosystems yield `mixed`; Docker combined with one language does not. Without a manifest, a shell-file majority yields `shell`, root `index.html` yields `html`, and the fallback is `unknown`.

Registration is idempotent for an existing absolute path. The path-repair endpoint changes the registered path without changing the path-derived ID.

## Scan model

### Quick scan

`GET /api/fleet` executes live Git queries for every registered repository with a concurrency limit of eight:

- validate the work tree
- parse porcelain status
- read the latest commit
- read the current branch

Results update `working_state` without erasing error fields created by broader scans. The endpoint then joins stored branches, dependencies, 13-week sparklines, and fleet KPIs into the response.

### Full history

The history scanner parses `git log --all` with ISO dates and short statistics, aggregates commits and line changes by day, and upserts `daily_stats`. After the initial scan it passes `last_full_scan_at` as the incremental lower bound and updates that timestamp after the scan.

### Branches

The branch scanner replaces the stored local-branch snapshot. A branch with no commit date is stale; otherwise a non-default branch becomes stale after 30 days. The detail API computes commits-ahead and diff statistics live against the configured default branch.

### Fleet orchestration

`POST /api/fleet/scan` accepts `{"type": "full"}` or `{"type": "deps"}` and returns a scan ID immediately. A module-level guard and a persisted `running` scan-log check reject overlap with HTTP 409.

The background task processes repositories sequentially. A full scan runs history, branch, and dependency scans; a dependency scan runs only dependency work. Progress is buffered through an `asyncio.Queue` and streamed by `GET /api/fleet/scan/{scan_id}/progress`. The active scan marker is cleared in a `finally` block.

Missing repository paths and per-repository failures are recorded and do not prevent remaining repositories from being attempted. The scan is `completed` when the fleet is empty or at least one repository succeeds; total failure is `failed`.

## Dependency model

Manifest discovery walks through depth three and skips hidden, virtual-environment, generated, and vendored directories. It recognizes:

| File | Manager |
| --- | --- |
| `pyproject.toml`, `requirements.txt` | `pip` |
| `package.json` | `npm` |
| `go.mod` | `gomod` |
| `Cargo.toml` | `cargo` |
| `Gemfile` | `bundler` |
| `composer.json` | `composer` |

Within one directory, only the highest-priority manifest for an ecosystem is selected; `pyproject.toml` precedes `requirements.txt`. Manifests in different directories are considered, subject to repository-wide manager/name deduplication.

Parsing is intentionally lightweight:

- Python supports PEP 621, Poetry, exact requirements pins, ranges/unpinned names, extras, markers, and circular-safe requirements includes.
- Node reads dependencies and devDependencies.
- Go reads block and single-line requirements.
- Cargo reads dependencies and dev-dependencies.
- Bundler recognizes conventional `gem` declarations.
- Composer reads require and require-dev while excluding PHP/platform extensions.

Outdated and vulnerability checks fail open so one external tool or network error does not discard other parsed dependencies. The scanner records a repository-level incomplete-analysis flag. Python outdated checks call the PyPI JSON API; other ecosystems use the tools listed in the README.

## HTTP API

The local SPA consumes these JSON and streaming endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Embedded SPA |
| GET | `/api/status` | Version and ecosystem-tool paths |
| GET | `/api/browse` | Local directory listing |
| GET | `/api/repos` | Registry listing without a scan |
| POST | `/api/repos` | Discover/register below a path |
| DELETE | `/api/repos/{id}` | Remove a registry entry and cascaded data |
| PATCH | `/api/repos/{id}` | Repair a repository path |
| GET | `/api/fleet` | Quick-scan and return fleet state/KPIs |
| POST | `/api/fleet/scan` | Start a `full` or `deps` fleet scan |
| GET | `/api/fleet/scan/{scan_id}/progress` | SSE progress |
| GET | `/api/repos/{id}` | Repository detail |
| GET | `/api/repos/{id}/history` | Stored daily history |
| GET | `/api/repos/{id}/commits` | Live paginated Git history |
| GET | `/api/repos/{id}/branches` | Stored branches plus live comparison stats |
| GET | `/api/repos/{id}/deps` | Grouped stored dependency results |
| POST | `/api/repos/{id}/scan/deps` | Synchronous single-repository dependency scan |
| GET | `/api/analytics/heatmap` | Fleet daily commit totals |
| GET | `/api/analytics/allocation` | Per-repository commit series |
| GET | `/api/analytics/dep-overlap` | Packages used by at least two repositories |

## UI contracts

The SPA uses hash routing and has Fleet and Analytics top-level tabs plus repository detail routes. An error boundary prevents an uncaught render error from leaving a blank root.

Important interaction contracts:

- Full scans show both a slim progress bar and an SSE-driven toast.
- Cards remain keyboard reachable; delete controls do not steal the card navigation action.
- Repository detail preserves the selected branch across Branches and Commits.
- Dependency findings can be exported entirely in the browser as Markdown or JSON.
- Missing CDN resources or JavaScript errors are covered by the separate Playwright suite.

## Testing contracts

Unit/API tests and Playwright E2E tests are separate invocations because Playwright's event loop conflicts with tests using `asyncio.run()`.

```bash
.venv/bin/python -m pytest tests/ --ignore=tests/test_e2e.py -v
.venv/bin/python -m pytest tests/test_e2e.py -v
```

The E2E server must use a temporary database and suppress normal browser launch. See `README.md` for environment setup and `docs/test_coverage_improvements.md` for known non-blocking gaps.
