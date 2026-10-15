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

There is no application-managed virtual environment and no frontend build. uv resolves and caches Python dependencies. The React 19.3.0 SPA, CSS, and JSX are embedded in `HTML_TEMPLATE`. An exact six-entry ESM import map covers React, ReactDOM, their JSX runtime subpaths, and aligned `react-is`; Babel Standalone 8.0.5 compiles the module-aware inline JSX. Recharts 3.10.1 loads as ESM with those React peers externalized so charts and application code share one React graph. Direct top-level package versions are pinned, while CDN-generated transitive module resolution and delivered bytes remain network-dependent rather than fully immutable. Fonts also load from public CDNs.

The FastAPI application binds to `127.0.0.1`. Port 8300 is preferred, but startup probes as many as 20 consecutive ports and uses the first available one. Automatic browser launch can be disabled with `--no-browser`, `GIT_DASHBOARD_NO_BROWSER`, or test mode.

## Runtime state

Runtime paths are resolved once when the module loads:

| State | Default | Override |
| --- | --- | --- |
| Runtime home | `~/.git_dashboard` | `GIT_DASHBOARD_HOME` |
| Database | `<runtime-home>/dashboard.db` | `GIT_DASHBOARD_DB` |

The runtime home contains mutable state only. SQLite is initialized idempotently and uses WAL mode. Startup applies additive column migrations followed by the transactional 0.2.0 dependency-key rebuild when needed. The rebuild preserves version values and timestamps, normalizes Python names, coalesces missing or NULL sources to an empty string, and keeps the first row by rowid on a normalized-key collision. Legacy severity and advisory values move into a rescan note; active advisory is cleared and severity/outdated/vulnerability coverage become unchecked. Already migrated rows are unchanged.

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
- JSON-text `missing_dep_tools` (tool/description objects) and `dep_manifests` (manifest inventory), returned as parsed arrays by repository detail; fleet returns missing tools

Quick scans preserve dependency metadata. Dependency scans persist metadata and dependency rows in one savepoint, including empty results. A write failure rolls back the scan snapshot before re-raising, so a later caller commit cannot publish partial coverage. Releasing the savepoint preserves an existing caller-owned transaction.

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

Dependency declarations keyed by `(repo_id, manager, source_path, name)`:

- non-null manifest `source_path`, defaulting to an empty string
- declared specification text and current, wanted, and latest versions
- severity, defaulting to `unchecked`
- independent `outdated_state` and `vuln_state`, defaulting to `unchecked`
- active advisory identifier, check note, and check timestamp

Parsing retains the first repeated identity within a manifest and preserves declarations from different manifests. Python package identity lowercases names and replaces runs of hyphens, underscores, and dots with a hyphen. Other manager names and fallback reference identifiers retain their spelling. The dependency API exposes the declared text, row timestamp, and coverage fields alongside the versions and manifest attribution.

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

Repository `dep_summary.unchecked` and fleet `kpis.unchecked_deps` count rows unless `outdated_state` is `checked` or `floating` and `vuln_state` is `checked`. Findings do not override incomplete coverage. Outdated counts include `outdated` and `major` severities; vulnerable counts use `vulnerable` severity.

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
| `pyproject.toml`, requirements `.txt`/`.lock` files, leading PEP 723 script metadata | `pip` |
| `package.json` | `npm` |
| `go.mod` | `gomod` |
| `Cargo.toml` | `cargo` |
| `Gemfile` | `bundler` |
| `composer.json` | `composer` |

Python manifest kinds coexist within each directory. Requirements filenames match `^requirements(?:[-_.][A-Za-z0-9_.-]+)?\.(?:txt|lock)$`, case-insensitively. Python suffixes and suffixless shebang files are script candidates; only metadata in their leading comment/blank-line prelude is read. PEP 723 grammar and closing-line precedence follow the [reference implementation](https://peps.python.org/pep-0723/#reference-implementation); unclosed blocks are ignored, while duplicate script blocks, malformed TOML and invalid dependency values become inventory errors. Manifests in different directories are considered independently; declaration deduplication is scoped to manager, manifest path, and identity name.

Parsing is intentionally lightweight:

- Python requirements and PEP 621 declarations share a `packaging.requirements.Requirement` parser. Extras and markers remain in textual `declared_spec`; markers are not evaluated against the scanner's environment. Exact PEP 440 pins become versions; wildcard pins and ranges remain unpinned. Requirements continuations are joined, inline comments and per-requirement options are stripped, and recursive includes remain circular-safe. PEP 621 optional dependencies and string dependency-group entries are included, without include-group expansion or Poetry group support. Poetry retains its supported scalar/table values and stores declaration text as a string. Adjacent `uv.lock` supplies unique normalized-name registry versions and a `version_source` path; ambiguous versions set `resolution_blocked` with an unchecked reason, bypassing checker calls. Absent names use ordinary resolution, and direct references keep their own coverage path. The lock is a version source, not a declaration manifest.
- Named direct URLs and legacy `egg` references use normalized distribution identities. Bare wheel URLs derive the name and display version from the wheel filename. Other bare references use host plus path as a fallback identity, preserving its spelling through deduplication. VCS revisions are extracted from the URL path, separately from authority user information; their display is `git:<revision>` (or the corresponding VCS), with `default branch` when absent. Direct references bypass PyPI and pip-audit, retaining unchecked coverage with `direct VCS/URL reference; not compared with PyPI or audited`. All audit inputs contain only exact evaluated registry pins in private temporary files outside the repository. Resolving VCS commits or remote package metadata is outside the scan contract. See [pip VCS support](https://pip.pypa.io/en/stable/topics/vcs-support/) for supported URL forms.
- Node reads dependencies and devDependencies.
- Go reads block and single-line requirements.
- Cargo reads dependencies and dev-dependencies.
- Bundler recognizes conventional `gem` declarations.
- Composer reads require and require-dev while excluding PHP/platform extensions.

Dependency parsing and blocking health checks run in `analyze_repo_deps` through `asyncio.to_thread`, keeping API and SSE work responsive. The analyzer returns enriched declarations, an incomplete-analysis flag, missing tool objects, and manifest inventory. A checker crash invalidates coverage only for its manager; other managers continue.

Coverage is independent: `outdated_state` is `checked`, `floating`, or `unchecked`; `vuln_state` is `checked` or `unchecked`. Exit status, result shape, and row evidence must support a checked result. Missing evidence gets a retained reason. Advisory evidence has highest severity precedence, followed by proven major/outdated results; remaining incomplete coverage yields `unchecked`, and complete clean coverage yields `ok`. Finalization is idempotent and preserves checker-selected floating and direct-reference display values. Only exact PEP 440 Python parser versions and Go parser versions default current versions; other managers obtain concrete versions from tools.

Non-Python orchestrators group declarations by the resolved parent of `source_path`; only legacy empty sources fall back to the repository root. Each inner checker keeps its existing signature and receives its manifest directory as the working directory. npm current versions prefer the outdated row, supported adjacent package-lock v1/v2/v3 entries, then installed package metadata. Listed rows need a latest comparison; absent rows need a concrete version plus a successful bounded `npm view` comparison (30 seconds). Lock evidence never substitutes for that comparison. Audit error objects, missing/invalid vulnerability mappings or affected-node lists and unexpected statuses invalidate npm audit coverage; `ENOLOCK` records the lockfile requirement. Both clean and vulnerable audit coverage require a concrete direct-node lock version matching the displayed current version; a mismatch retains current/outdated evidence and an unchecked vulnerability reason. If no current version exists, concrete audited lock evidence may supply it. Findings additionally require the declaration's `node_modules/<name>` location in the audit entry's `nodes` list. Same-name nested findings cannot establish a direct declaration's vulnerability.

Go `list` needs a valid row for the declaration; absent and replaced modules remain unchecked. govulncheck consumes the current v1 streaming protocol with initial config and validates SBOM/module/version and finding/trace evidence. The successful JSON stream exits zero. Only a matching evaluated module version establishes clean vulnerability coverage, and only matching findings supply advisories; OSV entries describe database candidates. Legacy `Vulns` objects are rejected. Composer outdated requests `--all`, validates `installed` entries including `latest-status`, and retains explicit clean comparison rows. Cargo outdated and Bundler outdated reports without evaluated declaration membership leave absent rows unchecked. Cargo/Bundler audit rows require package, version and advisory IDs, with version attribution preserved; absent findings in those reports or Composer audit do not establish per-declaration coverage. Unexpected statuses, missing required keys/fields, duplicate comparison rows and non-comparable versions remain unchecked, preserving the other check's independent state. See the [npm outdated contract](https://docs.npmjs.com/cli/v11/commands/npm-outdated/), [govulncheck protocol](https://pkg.go.dev/golang.org/x/vuln/internal/govulncheck) and [Composer commands](https://getcomposer.org/doc/03-cli.md#outdated).

The shared npm lock reader selects `npm-shrinkwrap.json` before `package-lock.json`, using the same layouts 1–3 and direct-node parser for outdated version evidence and audit attribution. An unreadable, malformed or unsupported selected shrinkwrap returns no lock evidence and never silently falls back to package-lock. See [npm lock precedence](https://docs.npmjs.com/cli/v11/configuring-npm/npm-shrinkwrap-json/), the [virtual-tree audit implementation](https://raw.githubusercontent.com/npm/cli/latest/workspaces/arborist/lib/arborist/index.js), and [audit affected-node serialization](https://raw.githubusercontent.com/npm/cli/latest/workspaces/arborist/lib/vuln.js).

`parse_deps_for_repo(repo_path, manifests_out=None)` populates an inventory of `{path, kind, dependencies, error}` records. Paths are resolved repository-relative POSIX paths or absolute paths for external includes. Requirements recursion shares resolved-path inventory and visited state: declarations retain their physically declaring `source_file`, each file counts only its own declarations, and empty, included, and failed files survive. `dep_manifests` persists the inventory atomically with coverage; errors set `DepAnalysis.any_error`. Empty files need no dependency group. Python outdated checks call the PyPI JSON API; other ecosystems use the tools listed in the README.

### Python health evaluation and scope

The evaluated version is the validated current declared/locked PEP 440 version, or a floating selection stored only in `wanted_version`. `_floating_specifier` accepts PEP 508 requirement syntax or standalone PEP 440 constraints; unsupported Poetry syntax remains unchecked. `resolve_floating_version` selects the highest allowed release using [`SpecifierSet.filter`](https://packaging.pypa.io/en/stable/specifiers.html#packaging.specifiers.SpecifierSet.filter), excluding invalid versions and releases without a non-yanked file. When there is no releases mapping, valid `info.version` is the fallback candidate. Compare the evaluated version to the registry's latest version with `classify_severity`, including versions beyond a declaration's cap. Exact evaluations set `outdated_state=checked`; floating evaluations set `outdated_state=floating`.

`check_python_outdated` caches registry payloads and failure notes by normalized name within the repository scan. `_PYPI_MAX_CONSECUTIVE_FAILURES` is three: timeout/connection failures count toward it and successful lookups reset it. HTTP and JSON errors do not count. Once open, the breaker marks uncached lookups unchecked without a request; cached results remain usable.

`_pip_audit_batches` deduplicates normalized `(name, version)` pins and separates conflicting versions of one name. `_audit_python_pins` writes exact-pin inputs outside the checkout and invokes pip-audit with `--no-deps --disable-pip --format json --progress-spinner off` and a 300-second timeout. The [documented status](https://pypi.org/project/pip-audit/) must be 0 for clean results or 1 for advisory results. The report also requires a dependencies list, unique normalized result names, valid advisory dictionaries with nonempty string IDs, and a matching version if returned. Missing/skipped requested entries remain unchecked; malformed output or contradictory status invalidates that batch. Results map back by normalized name and audited version across manifests, preferring current versions over floating selections. Tool absence, unresolved versions and process failures retain reasons.

Scope: this is declaration evaluation, not installed-environment inspection or full dependency resolution. It does not evaluate markers, `requires-python` or inter-package compatibility, and it does not audit undeclared transitive Python dependencies. Direct references and ambiguous lock versions retain their separate unchecked contracts.

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
| GET | `/api/analytics/dep-overlap` | Identities with at least two manifest declaration uses |

`/api/status` also returns `dependency_scope`, the report's scan-boundary metadata. Discovery depth and skipped directories come from the scanner's runtime constants. `/api/repos/{id}/deps` and its scan endpoint retain the grouped-list response, with declared specifications, versions, independent states, notes and timestamps on each package.

### Dependency overlap response

`GET /api/analytics/dep-overlap` returns `{ "packages": [...] }`. Each entry groups declarations by manager and identity name, includes `count` (declaration uses), `repo_count` (distinct repositories), and `repos[]` with `repo_id`, `name`, `version`, and `source_path`. Groups with fewer than two uses are excluded; results sort by use count descending. `version_spread` uses distinct non-null versions ordered by `packaging.version.Version`, followed by invalid version text in lexical order. Empty version sets produce an empty spread. Expanded rows display each manifest beside its version and use repository ID plus source path as their React key.

## UI contracts

The SPA uses hash routing and has Fleet and Analytics top-level tabs plus repository detail routes. An error boundary prevents an uncaught render error from leaving a blank root.

Important interaction contracts:

- Full scans show both a slim progress bar and an SSE-driven toast.
- Cards remain keyboard reachable; delete controls do not steal the card navigation action.
- Repository detail preserves the selected branch across Branches and Commits.
- Dependency findings can be exported entirely in the browser as Markdown or JSON.
- Missing CDN resources or JavaScript errors are covered by the separate Playwright suite.

`summarizeDeps(groups, manifests)` returns declaration and inventory manifest counts, individual `ok`, `outdated`, `major`, and `vulnerable` severity counts, state-based `unchecked`, and `fullyChecked`. A fully checked declaration has outdated state `checked`/`floating` and vulnerability state `checked`. Inventory counts include empty and failed files, independent of nonempty groups.

The Dependencies tab fetches detail metadata and application status on mount and after Check Now. It displays the declared text, current version or explicitly labeled floating evaluated selection, both check states, headline status and retained reasons. Partially checked findings appear in both Attention Required and Not Checked. An incomplete banner also covers missing tools, manifest errors and persisted analysis errors. The clean banner requires a nonempty declaration set, no findings, complete check states, and complete analysis metadata. Fleet KPIs, per-repository summaries and card coverage titles expose Not Checked independently of findings. Cards consume the independent `dep_check_error` signal and show an Analysis error label. Per-Repo Health includes repositories with analysis errors or missing tools even with no declaration rows; its badges retain those reasons for fully checked rows too. Repository-level errors never manufacture unchecked declarations or alter the state-based KPI predicate.

### Downloaded dependency reports

JSON downloads have `{format: "git-fleet-dependency-report", format_version: 2, generated_at, git_fleet_version, repo: {id, name}, missing_tools, summary, scope, manifests, groups}`. Only this downloaded envelope is versioned; the dependency API remains a grouped list. Scope documents Python declaration-evaluation limits, direct-reference exclusions, runtime discovery limits, PEP 723 prelude handling and dependency-group boundaries.

Markdown reports include repository/report identity, generation time, app version, newest declaration check timestamp (or No declaration check timestamp available), coverage, missing tools and Scope. Attention Required, Not Checked and All Dependencies tables retain declared specifications, version displays, both check states, headline statuses, sources and reasons. Manifests Scanned lists inventory paths, kinds, declaration counts and errors. Empty inventories and declaration sets remain exportable.

## Testing contracts

Unit/API tests and Playwright E2E tests are separate invocations because Playwright's event loop conflicts with tests using `asyncio.run()`.

```bash
.venv/bin/python -m pytest tests/ --ignore=tests/test_e2e.py -v
.venv/bin/python -m pytest tests/test_e2e.py -v
```

The E2E server must use a temporary database and suppress normal browser launch. See `README.md` for environment setup.
