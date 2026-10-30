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
- A browser with native import-map and ES-module support; Babel Standalone 8
  compiles the module-aware inline JSX in the browser. The maintained
  automated browser target is current Playwright Chromium.

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

**Not Checked** counts declarations whose outdated or vulnerability check is incomplete, including declarations that also have a vulnerability or update finding. Outdated totals include minor and major update severities. Card coverage dots explain unchecked counts and missing tools; the fleet Dependencies view shows the same coverage per repository.

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
- **Dependencies** — packages grouped by ecosystem and manifest path, with vulnerable and outdated packages surfaced first. Independent outdated and vulnerability coverage distinguish checked results from unchecked declarations; incomplete checks retain a reason. Missing dependency tools and discovered manifests are stored with the repository detail, including scans with no dependency rows. Results can be rescanned on demand or exported as Markdown or JSON.
- **Branches** — local branches with default/stale status and live commits-ahead and diff statistics against the default branch.
- **Commits** — paginated live Git history for all refs or a selected branch.

If a registered repository moves, its path can be repaired from the detail view. Removing a repository cascades to its stored working state, history, branches, and dependency rows.

The Dependencies view reloads coverage metadata and the application version on mount and after **Check Now**. It shows declared specifications, evaluated versions (floating selections are not installed versions), both check states, and reasons. **Not Checked** includes partially checked findings. The clean banner requires every declaration to be fully checked and no missing tools or inventory errors. **Manifests Scanned** includes empty and failed files, independently of dependency groups; exports remain available with an empty declaration set.

Markdown reports contain repository identity, generation time, application version, newest declaration check timestamp (explicitly unavailable when no declaration timestamps exist), coverage, missing tools, scope, and the Attention Required, Not Checked, All Dependencies, and Manifests Scanned sections. JSON downloads use `git-fleet-dependency-report` format version 2 with `generated_at`, `git_fleet_version`, `repo`, `missing_tools`, `summary`, `scope`, `manifests`, and `groups`. Scope describes declaration resolution limits, reference exclusions, traversal limits and dependency-group boundaries. The ordinary dependency API remains a grouped list.

### Analytics

Fleet-wide analytics include a one-year commit heatmap, configurable time-allocation charts, and dependency overlap across manifests and repositories. Overlap counts declaration uses separately from distinct repositories and attributes each version to its manifest. Version spreads use semantic version ordering, with non-version text sorted afterward.

## Dependency discovery

Git Fleet searches the repository root and subdirectories up to three levels deep, while skipping common generated and vendored directories. It recognizes:

- `pyproject.toml`, `requirements*.txt` / `requirements*.lock` (including separator suffixes such as `requirements-dev.txt`), and Python scripts with leading PEP 723 metadata
- `package.json`
- `go.mod`
- `Cargo.toml`
- `Gemfile`
- `composer.json`

Python manifest kinds coexist in each directory. Requirements includes retain the physically declaring file, including arbitrary filenames and paths outside the repository. The manifest inventory preserves empty files and read/parse errors. Script metadata is read only from the leading comment/blank-line prelude, using [PEP 723 grammar](https://peps.python.org/pep-0723/#specification); unclosed blocks are ignored and malformed or duplicate script metadata reports an error. PEP 621 optional dependencies and string entries in `dependency-groups` are included; include-group tables are not expanded. Adjacent `uv.lock` supplies unique registry versions for pyproject declarations, with provenance; ambiguous versions block checks. It is not a separate declaration manifest. `requirements.lock` remains an independent declaration source. Each dependency declaration is identified by repository, package manager, manifest path, and identity name. The first repeated identity within one manifest wins; declarations from different manifests remain separate. Python package names are lowercased with runs of hyphens, underscores, and dots normalized to a hyphen. Other managers and fallback reference identifiers retain their spelling.

Version 0.2.0 migrates legacy dependency rows to this declaration key. Existing version values and check timestamps are preserved; legacy advisory and severity values move into a migration note, and coverage becomes unchecked. Rescan dependencies to establish fresh coverage and recover declarations that the former repository-wide key discarded.

Non-Python health checks run separately in each resolved manifest directory, with the repository root used only for legacy rows without a source. A successful process needs valid result structure and declaration evidence before either check becomes checked. Outdated and vulnerability coverage remain independent, and incomplete coverage retains its reason.

For npm, [`outdated`](https://docs.npmjs.com/cli/v11/commands/npm-outdated/) rows need concrete current and latest versions. Missing current versions can come from adjacent `package-lock.json` layouts 1–3 or installed `node_modules` package metadata, read without running package code. A lock is version evidence only. An absent outdated row with a concrete version gets one `npm view <name> version --json` comparison with a 30-second timeout; absent versions, failed comparisons and malformed results remain unchecked. Audit coverage requires the declaration's direct node in the supported adjacent lock and a version matching the displayed current version. A mismatch preserves current/outdated evidence and leaves vulnerability coverage unchecked with a reason. Findings must list that direct node in `nodes`; a same-name nested finding does not implicate the direct declaration. Top-level audit errors, invalid vulnerability mappings or node lists and failure statuses never establish coverage; `ENOLOCK` retains a lockfile-specific reason.

Fleet cards and Per-Repo Health retain analysis errors and missing tools even when no declarations were discovered or every discovered declaration was fully checked. Repository analysis errors are labeled explicitly; declaration-based Not Checked counts remain unchanged.

The shared npm lock reader honors [`npm-shrinkwrap.json` precedence](https://docs.npmjs.com/cli/v11/configuring-npm/npm-shrinkwrap-json/) over `package-lock.json`, using the same supported layouts for version and audit evidence. An invalid or unsupported selected shrinkwrap cannot fall back to package-lock audit coverage.

Go outdated coverage requires its own `go list` module row. Vulnerability checks consume the current [govulncheck streaming protocol](https://pkg.go.dev/golang.org/x/vuln/internal/govulncheck): matching module/version entries in the SBOM establish evaluation, and matching findings establish advisories. OSV database entries alone are not findings. The historical `Vulns` object is unsupported. Composer requests [`outdated --all`](https://getcomposer.org/doc/03-cli.md#outdated) so clean packages have explicit comparison rows. Cargo and Bundler findings-only reports do not establish evaluation of absent declarations; those rows conservatively remain unchecked. Cargo/Bundler audit findings are matched to the current version when known; their clean reports and Composer's clean audit report lack per-declaration evaluation evidence and remain unchecked. Non-comparable versions and unsupported report shapes also retain unchecked reasons.

### Python dependency-health scope

Python health evaluates declarations. Exact declared or unique adjacent-lock versions become `current_version`. Supported PEP 440 ranges and unpinned declarations select the highest allowed PyPI release with non-yanked release files as `wanted_version`, with floating outdated coverage and no invented current version. Prerelease selection follows [`SpecifierSet.filter`](https://packaging.pypa.io/en/stable/specifiers.html#packaging.specifiers.SpecifierSet.filter). The evaluated version is compared with PyPI's latest version, so a capped range can still show an update outside its cap. Unsupported constraints, including Poetry caret/tilde syntax and unresolved dependency tables, remain unchecked when no concrete declared or locked version is available.

Registry successes and failures are cached by normalized package name for one repository scan. Three consecutive timeout/connection failures stop uncached lookups for that scan; a successful lookup resets the count. HTTP and JSON errors do not count toward that limit. Direct VCS/URL references bypass PyPI and auditing and retain their display identity and unchecked reason. Ambiguous lock versions also block both checks.

Vulnerability checks audit only exact evaluated pins from every supported Python manifest. Conflicting versions of one package go into separate batches; repeated pins share results. Temporary audit files live outside the checkout. [`pip-audit`](https://pypi.org/project/pip-audit/) runs with `--no-deps --disable-pip`, and a result counts as checked only when its status, dependency entry, requested version and advisory shape agree. Missing tools, unresolved versions, skipped or absent entries and failed batches retain unchecked reasons. A failed batch does not invalidate another batch.

This scope does not inspect an installed environment or perform full dependency resolution. Markers, `requires-python` and compatibility among packages are not evaluated. Undeclared transitive Python dependencies are not audited. A floating selection describes the declaration at scan time; it is not evidence of an installed version.

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
- A React 19.3.0 SPA, its CSS, and all JSX are embedded in `git_dashboard.py` and served by `GET /`; there is no frontend build or `node_modules`.
- Hash routes select the Fleet, Analytics, and repository detail views.

The frontend uses an exact six-entry import map for React, ReactDOM, their JSX
runtime subpaths, and `react-is`, plus Babel Standalone 8.0.5 for module-aware
inline JSX. Recharts 3.10.1 loads as ESM with its React peers externalized to
that map, so the application and charts share one React graph. The direct
top-level package versions are pinned, but CDN-generated transitive module
resolution and delivered bytes remain network-dependent and are not fully
immutable.

The six SQLite tables are:

- `repositories` — registered path, runtime classification, default branch, and scan timestamps
- `working_state` — the latest quick-scan snapshot and error flags
- `daily_stats` — per-day commit and line-change aggregates
- `branches` — the latest local branch snapshot
- `dependencies` — parsed package and health data
- `scan_log` — fleet scan lifecycle and counts

The maintained design and API reference is [docs/git_dashboard_final_spec.md](docs/git_dashboard_final_spec.md). Source comments that mention numbered packets refer to the original packetized build, planned with the [design-document packetization playbook](../coding/design_orch/docs/design_doc_packetization_playbook.md).

## Development

From the repository root, run the unit and E2E invocations through the shared runner:

```bash
UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py git_fleet
```

If Chromium is missing, install it once:

```bash
UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py git_fleet --install-browsers
```

Run E2E tests separately from the unit suite because Playwright's event loop conflicts with tests that use `asyncio.run()`. E2E startup uses an isolated temporary database and suppresses automatic browser launch.

After changing the launcher's PEP 723 header or bootstrap imports, run the repository-wide uv header guard from the monorepo root:

```bash
uv run --script tools/check_uv_headers.py
```

## Platform notes

The code supports macOS, Linux, and Windows. Unix users can run the executable directly; Windows users should use `uv run --script git_dashboard.py`. Local paths are handled with `pathlib`, and subprocess commands pass arguments directly rather than through a shell.
