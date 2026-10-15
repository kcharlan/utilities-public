# Storage Monitor

Storage Monitor is a local-first macOS disk-usage and cleanup console. It indexes the writable APFS Data volume, inventories local Time Machine snapshots, and surfaces large files and cleanup candidates in a React dashboard. Scan data and action logs remain on the Mac.

The application pairs a single executable Python launcher with a native C
`getattrlistbulk` walker. The walker indexes the volume; the launcher owns scan
orchestration, SQLite persistence, provider probes, and the dashboard. The
launcher refuses to start if the walker is missing or speaks a different
protocol. The running application never compiles anything.

The launcher provides:

- a uv-managed FastAPI backend;
- a localhost-only web server;
- an embedded React UI whose browser libraries are loaded from public CDNs; and
- mutable runtime state under `~/.storage_monitor/` by default.

## Native walker boundary

The C helper owns filesystem enumeration only. Python retains path translation,
hardlink ownership, rollup, SQLite writes and provider probes so full scans and
directory refreshes share their accounting rules. Provider probes overlap the
walk; there is no second Python walker or runtime compilation fallback.

Protocol 1 uses NUL-delimited fields, preserving filenames with tabs, newlines
and undecodable bytes. `D` reports directory-local allocation; `H` reports
hardlink candidates; `L` reports large files; `P` reports progress; a final `S`
reports counts and duration. Python rejects truncated streams, records after
the summary, nonzero exits and missing summaries before accepting a walk.
The launcher and helper protocol versions must agree at startup and deployment.

Allocated file bytes use `ATTR_FILE_ALLOCSIZE`, corresponding to `st_blocks *
512`, rather than data-fork-only allocation; apparent bytes use
`ATTR_FILE_DATALENGTH`. Opened child directories are checked against the root
device so a mount encountered inside the tree is skipped. Large-file and
progress thresholds are supplied by Python as helper arguments. Changes to this
boundary must preserve the native protocol, hardlink, mount and filename tests.

## Requirements

- macOS with APFS, `diskutil`, and `tmutil`
- [uv](https://docs.astral.sh/uv/) (`brew install uv`)
- Xcode Command Line Tools (`xcode-select --install`), providing Apple clang and `make` to build `storage_monitor_walk`
- Node.js, for `tools/deploy_storage_monitor.mjs`
- a browser with network access to load React, Babel, Tailwind CSS, and Lucide from their CDNs

## Build and Deploy

For development, build the walker explicitly, then run from this directory:

```zsh
make -C native
UV_PYTHON_DOWNLOADS=never ./storage_monitor
```

The launcher finds `native/build/storage_monitor_walk`. Symlinking the repository
launcher into your `PATH` still works after this build:

```zsh
ln -s "$(pwd)/storage_monitor" /usr/local/bin/storage_monitor
UV_PYTHON_DOWNLOADS=never storage_monitor
```

For installed use, validate and stage the reviewed launcher and native build
inputs, then preview and deploy the launcher and walker together:

```zsh
node ../tools/deploy_storage_monitor.mjs --dry-run
node ../tools/deploy_storage_monitor.mjs
node ../tools/deploy_storage_monitor.mjs --audit
```

See [deployment details](../docs/local_deployment_sync.md#storage-monitor-deployment)
for receipts, rebuilds, backups, rollback, and fleet audits.

On first run, uv resolves FastAPI and uvicorn into its shared cache, so that invocation may briefly use the network. Storage Monitor then:

1. creates its runtime directory and SQLite index;
2. stops a prior Storage Monitor process recorded in that runtime directory, if one is still running;
3. starts a scan;
4. binds to `127.0.0.1`, preferring port 8473 and trying the next 19 ports if necessary; and
5. opens the dashboard in the default browser.

The build-free frontend uses React 19.3.0 and ReactDOM 19.3.0 through an
exact-version import map. Its six direct ESM entries pin `react`, both JSX
runtime subpaths, `react-dom`, `react-dom/client`, and react-is 19.3.0;
ReactDOM and react-is externalize the shared React peer. Babel Standalone 8.0.5
compiles the module-aware inline JSX. Tailwind CSS 4.3.3 is loaded through the
exact-version `@tailwindcss/browser` package. A minimal `text/tailwindcss`
block declares the generated utilities, while first-party theme and component
rules remain in a normal stylesheet so the dashboard keeps its core styling if
the Tailwind CDN is unavailable.

The direct top-level package versions in the import map and script URLs are
exact, which prevents drift in those requested versions. CDN-generated
transitive dependencies are not fully locked, however, and the interface still
requires network access at runtime. Exact pins are not byte-immutable delivery
guarantees; offline or byte-for-byte reproducible use would require a separate
vendoring or release-artifact flow.

The automated browser smoke covers the current Playwright Chromium only. For
manual clients, Tailwind 4 requires Chrome 111 or newer, Safari 16.4 or newer,
or Firefox 128 or newer. Safari and Firefox are not covered by the automated
suite. The browser smoke also verifies the current Lucide UMD API, representative
Tailwind-generated utility styles, theme persistence, and browser error
cleanliness.

Use `--no-browser` to suppress the browser launch or `--port PORT` (`-p PORT`) to choose a different preferred port:

```zsh
UV_PYTHON_DOWNLOADS=never ./storage_monitor --no-browser --port 8500
```

## Current Capabilities

### Storage index and dashboard

- A single parallel walk indexes `/System/Volumes/Data`, excluding mounted external and network volumes under `/System/Volumes/Data/Volumes`.
- Live scan phases and directory counts stream to the dashboard.
- The treemap and drill-down views cover the Data volume, home directory, `~/Library`, and `/Applications` from the same index.
- Deep directories are served from SQLite; files and folders are visually distinguished.
- A directory can be revealed in Finder or rescanned after files change outside the app.
- The summary compares indexed Data-volume usage with APFS-reported usage.
- Files with an apparent size of at least 1 GiB are listed in a dedicated tab; `/private/var/vm` is excluded.
- Completed scans can be compared in the Growth tab after at least two scans.
- The dashboard follows the OS light/dark preference until manually overridden; the override is stored in browser local storage.

Full-scan time depends on directory count, storage performance, permissions, and concurrent disk activity.

### Cleanup intelligence

- A fixed watchlist covers common caches, model stores, stale installers, runtime payloads, and large user-controlled data locations.
- The index also discovers cache-named directories of at least 100 MiB under the home directory.
- Potential leftovers in `~/Library/Containers` and `~/Library/Group Containers` are heuristic, report-only results with a Reveal in Finder action.
- Homebrew and Docker integrations provide estimates and explicit cleanup actions when their command-line tools are installed and usable.
- uv cache size is reported as an upper bound with a copyable `uv cache prune` command. Quit Storage Monitor before running it because the parent uv process holds the cache lock.

### Snapshots and actions

- The snapshot manager inventories local Time Machine snapshots, shows APFS purgeability and container-shrink details when available, supports sorting and multi-selection, and can request snapshot thinning.
- Cache-like and stale-installer paths are moved to `~/.Trash/`; they are not permanently deleted by Storage Monitor.
- Snapshot deletion and thinning are permanent operations delegated to macOS.
- Finder reveal actions are available for files, directories, and report-only candidates.
- After cleanup actions, Storage Monitor refreshes affected index paths, APFS metadata, and the persisted report without requiring another full scan.

Review every proposed action before running it. Estimates are approximate, APFS free-space changes can be delayed, and provider commands may reclaim less than their displayed upper bound.

## Runtime State

Runtime files live under `~/.storage_monitor/` by default. Set `STORAGE_MONITOR_HOME` to use another directory. `STORAGE_MONITOR_SCAN_WORKERS` controls the parallel walk size and is clamped to 1–16 workers (default: 8). `STORAGE_MONITOR_WALKER` overrides the helper path; otherwise the launcher finds the helper beside an installed launcher or under `native/build` in a development checkout.

- `storage_monitor.db` — the active volume index, cached drill-down data, up to 30 scan-run records, and compact directory history for up to 60 scans. Obsolete index rows are pruned after a successful scan; SQLite is vacuumed when reclaimable database space exceeds 100 MiB.
- `latest_scan.json` — the most recent completed or refreshed report.
- `history/` — timestamped JSON reports. These files are not automatically pruned.
- `action_log.jsonl` — append-only records of cleanup actions and their results.
- `last_port` — the port selected by the most recent launch.
- `pid` — the current process ID, used to replace a prior instance on the next launch.

## Validation

Create an isolated test environment and run the project suite:

```zsh
cd /path/to/utilities-public/storage_monitor
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
```

The complete suite includes unit, native protocol, integration, and Chromium
browser tests, with no skips. By default it builds the walker into a temporary
directory. Run the complete suite against both sanitizer builds as well:

```zsh
make -C native sanitize tsan
STORAGE_MONITOR_WALKER="$PWD/native/build/sanitize/storage_monitor_walk" .venv/bin/python -m pytest -q
STORAGE_MONITOR_WALKER="$PWD/native/build/tsan/storage_monitor_walk" .venv/bin/python -m pytest -q
```

From the repository root, run the deployment and fleet fixture suites:

```zsh
node --test tools/tests/deploy_storage_monitor.test.mjs tools/tests/deploy_colophon.test.mjs tools/tests/deploy_ai_model_timeline.test.mjs
node --test tools/tests/check_static_deployments.test.mjs
zsh tools/tests/test_check_local_deployments.zsh
uv run --no-python-downloads --script tools/check_uv_headers.py
```

Return to `storage_monitor/` for the remaining runtime smoke and performance
commands:

```zsh
cd storage_monitor
make -C native
UV_PYTHON_DOWNLOADS=never ./storage_monitor --help
UTILITIES_TESTING=1 STORAGE_MONITOR_HOME="$(mktemp -d)" UV_PYTHON_DOWNLOADS=never ./storage_monitor --no-browser --port 8473
```

The final command starts the server and an automatic scan in an
isolated runtime directory. Request `/api/state` on the selected port until
`scan_status.phase` is `idle` with no error, then stop it with `Ctrl-C`.

Real-disk performance and historical-walker parity checks require owner
approval. Keep runtime homes, JSON outputs, and any path diagnostics outside
every public checkout. Both tools check Git's registered worktree inventory and
refuse to run if it cannot be read. From this directory, the tools accept:

```zsh
.venv/bin/python tests/perf/measure_scan.py --help
.venv/bin/python tests/parity/compare_walkers.py --help
.venv/bin/python tests/perf/measure_scan.py --runtime-home /private/output/runtime --output /private/output/performance.json --runs 3
.venv/bin/python tests/parity/compare_walkers.py --baseline-ref BASELINE_REF --root /private/input --output /private/output/parity.json
```

Replace the illustrative private paths and `BASELINE_REF` with approved local
destinations and the historical Python-walker revision. Performance phase times
overlap and must not be summed; compare whole-scan and walker durations under
comparable permissions, cache state, and background disk activity.
