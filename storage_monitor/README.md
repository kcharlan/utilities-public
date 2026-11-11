# Storage Monitor

Storage Monitor is a local-first macOS disk-usage and cleanup console. It indexes the writable APFS Data volume, inventories local Time Machine snapshots, and surfaces large files and cleanup candidates in a dashboard. Scan data and action logs remain on the Mac.

The application pairs a single executable Python launcher with a native C
`getattrlistbulk` walker. The walker indexes the volume; the launcher owns scan
orchestration, SQLite persistence, provider probes, and the dashboard. The
launcher refuses to start if the walker is missing or speaks a different
protocol. The running application never compiles anything.

The launcher provides:

- a uv-managed FastAPI backend;
- a localhost-only web server;
- an embedded offline browser UI; and
- mutable runtime state under `~/.storage_monitor/` by default.

## Native walker boundary

The C helper owns filesystem enumeration only. Python retains path translation,
hardlink ownership, rollup, SQLite writes and provider probes so full scans and
directory refreshes share their accounting rules. Provider probes overlap the
walk; there is no second Python walker or runtime compilation fallback.

Protocol 2 uses NUL-delimited fields, preserving filenames with tabs, newlines
and undecodable bytes. `D` reports directory-local allocation, non-directory
entry count, and newest modification time in whole epoch seconds, including the
directory itself. `E` reports a directory path and errno when it cannot be read.
`H` reports
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
- a modern browser

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
2. acquires an exclusive instance lock for that runtime directory, reporting an error if another instance holds it;
3. starts a scan;
4. binds to `127.0.0.1`, preferring port 8473 and trying the next 19 ports if necessary; and
5. opens the dashboard in the default browser.

The frontend embeds Preact, hooks, htm, and its styles in the launcher. The
dashboard makes no external browser requests and works offline after uv has
resolved its dependencies. The automated browser suite covers Playwright
Chromium, theme persistence, representative styles, and browser errors; Safari
and Firefox are not covered by that suite.

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

- A fixed watchlist covers common caches, model stores, stale installers, runtime payloads, and large user-controlled data locations. Model stores, VS Code extensions, and user data are review-only.
- The index also discovers known cache directory names under the home directory. Matches of at least 100 MiB are listed individually; smaller matches of at least 1 MiB are grouped for review. The findings limit applies per category, and the report records how many items and bytes were omitted.
- Developer artifacts of at least 50 MiB can be moved to Trash when their newest indexed modification is at least 30 days old. These include `node_modules`, Python `.venv`/`venv`, Swift `.build`, Rust `target`, CocoaPods `Pods`, and Next.js `.next` only when the corresponding project or environment marker is present, plus Xcode DerivedData children and `~/.gradle/caches`. Fresh or undated artifacts are review-only. Python `__pycache__` folders are grouped for review without a cleanup action.
- Running apps are checked once per report. Their cache entries are review-only; if the check fails, Library cache entries are review-only. Other matching app-owned findings warn and name the running app before a move. Quit the app first.
- Shared cache folders (`~/.cache`, `~/Library/Caches`) are never offered as one target. Their entries of at least 100 MiB are listed individually. A Library cache entry is eligible for Trash only when its name matches an installed non-Apple app's bundle ID or app name, or is one of the developer caches Homebrew, pip, npm, Yarn, Gradle, or CocoaPods; its owner must not be running and existing protections still apply. The same eligibility applies to nested cache folders. Other entries are review-only, including unknown Apple-owned names. Entries of `~/.cache` remain review-only, apart from the existing named-cache policies.
- Discovered caches are review-only when they sit in a location macOS manages or syncs: any `com.apple.*` container or cache, `~/Library/Metadata`, `Messages`, `Mail`, `Safari`, `Mobile Documents`, `CloudStorage`, `~/Documents`, `~/Desktop`, and uv's own cache.
- Potential leftovers in `~/Library/Containers` and `~/Library/Group Containers` are heuristic, report-only results with a Reveal in Finder action. The list shows at most 40 and reports the count and bytes omitted.
- Homebrew and Docker integrations provide estimates and explicit cleanup actions when their command-line tools are installed and usable.
- uv cache size is reported as an upper bound with a copyable `uv cache prune` command. Quit Storage Monitor before running it because the parent uv process holds the cache lock.
- Temporary directory groups show current-user regular files and indexed directories at least three days old, excluding Apple and live system names. The preview excludes directories with a socket or FIFO within two levels. Before moving a directory, the bulk Trash action uses the native walker to recheck descendant modification times and refuses directories containing a socket or FIFO at any depth or that it cannot fully verify. It reports refusals and continues. The per-user cache directory is size-only.
- Stale `.superpowers` workspaces can be moved to Trash after 14 days. Worktree children and home temporary-name residue are review-only; remove worktrees using their owning manager. Directories containing managed worktrees are protected too, with a live check before a move. Agent and tool runtime homes (`.claude`, `.codex`, `.config`, `.gemini`, `.t3`, `.lmstudio`, `.docker`, `.local`, `.venvs`, and Storage Monitor's runtime home) are size-only and protected from cleanup. Device backups are review-only.
- The Trash row shows indexed size; empty it in Finder to free space. Storage Monitor does not empty it.

### Snapshots and actions

- The snapshot manager inventories local Time Machine snapshots, shows APFS purgeability and container-shrink details when available, supports sorting and multi-selection, and can request snapshot thinning.
- Cache-like and stale-installer paths are moved to `~/.Trash/` after a confirmation; they are not permanently deleted by Storage Monitor, and space is freed only when the Trash is emptied. Items are renamed `storage-monitor-<timestamp>-<name>`, so Finder's Put Back is unavailable; the original path is recorded in `action_log.jsonl`.
- The move is a rename. If macOS refuses it, the action fails and nothing is changed; Storage Monitor never copies and deletes instead. The server also refuses the protected locations above regardless of what the page requests.
- Snapshot deletion and thinning are permanent operations delegated to macOS.
- Finder reveal actions are available for files, directories, and report-only candidates.
- After cleanup actions, Storage Monitor refreshes affected index paths, APFS metadata, and the persisted report without requiring another full scan. If a refreshed directory loses the owner of a hard-linked file, a surviving link elsewhere remains uncounted until its own directory is refreshed or a full scan runs. An ancestor's newest modification time may remain too recent until the next full scan.

Review every proposed action before running it. Estimates are approximate, APFS free-space changes can be delayed, and provider commands may reclaim less than their displayed upper bound.

## Runtime State

Runtime files live under `~/.storage_monitor/` by default. Set `STORAGE_MONITOR_HOME` to use another directory. `STORAGE_MONITOR_SCAN_WORKERS` controls the parallel walk size and is clamped to 1–16 workers (default: 8). `STORAGE_MONITOR_WALKER` overrides the helper path; otherwise the launcher finds the helper beside an installed launcher or under `native/build` in a development checkout.

- `storage_monitor.db` — the active volume index, cached drill-down data, up to 30 scan-run records, and compact directory history for up to 60 scans. Obsolete index rows are pruned after a successful scan; SQLite is vacuumed when reclaimable database space exceeds 100 MiB.
- `latest_scan.json` — the most recent completed or refreshed report.
- `history/` — timestamped JSON reports; only the newest 60 are retained.
- `action_log.jsonl` — append-only records of cleanup actions and their results.
- `last_port` — the port selected by the most recent launch.
- `pid` — an instance lock file containing the process ID. A second instance using the same runtime home exits without signalling the first.
- `config.json` — private settings, created with empty values and mode `0600`. `watchlist` adds entries with the fields shown in `config.example.json`; paths must be below the home directory. A requested cleanup action is allowed only for `trash_path` entries that pass the same protection checks as built-in findings. `ignore_paths` accepts absolute or `~/` paths, including outside the home directory, and hides findings at or below each path. Temporary bulk actions also leave ignored entries and any containing directory alone. `stale_days` maps discovery rule IDs to age thresholds from 1 through 3650 days. Invalid configuration produces a warning and defaults are used.

Personal data locations are not added automatically. To monitor an export or
other personal data folder, add a review-only `watchlist` entry to the private
config, using `cleanup_kind: null` and `actionable: false`. For example, use
this for an Apple Health export or sleep-therapy data folder if desired. The
example file contains synthetic paths only and is not read automatically.

## Validation

From the repository root, run the project suite:

```zsh
UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py storage_monitor
```

If Chromium is missing, install it once with `UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py storage_monitor --install-browsers`.

The complete suite includes unit, native protocol, integration, and Chromium
browser tests, with no skips. By default it builds the walker into a temporary
directory. Run the complete suite against both sanitizer builds as well:

```zsh
make -C storage_monitor/native sanitize tsan
STORAGE_MONITOR_WALKER="$PWD/storage_monitor/native/build/sanitize/storage_monitor_walk" UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py storage_monitor
STORAGE_MONITOR_WALKER="$PWD/storage_monitor/native/build/tsan/storage_monitor_walk" UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py storage_monitor
```

From the repository root, run the deployment and fleet fixture suites:

```zsh
node --test tools/tests/deploy_storage_monitor.test.mjs tools/tests/deploy_colophon.test.mjs tools/tests/deploy_brew_version.test.mjs tools/tests/deploy_calculator_pages.test.mjs
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
refuse to run if it cannot be read. From this directory, using a virtual
environment with the launcher's runtime dependencies, the tools accept:

```zsh
VENV_PYTHON=/path/to/venv/bin/python
"$VENV_PYTHON" tests/perf/measure_scan.py --help
"$VENV_PYTHON" tests/parity/compare_walkers.py --help
"$VENV_PYTHON" tests/perf/measure_scan.py --runtime-home /private/output/runtime --output /private/output/performance.json --runs 3
"$VENV_PYTHON" tests/parity/compare_walkers.py --baseline-ref BASELINE_REF --root /private/input --output /private/output/parity.json
```

Replace the illustrative private paths and `BASELINE_REF` with approved local
destinations and the historical Python-walker revision. Performance phase times
overlap and must not be summed; compare whole-scan and walker durations under
comparable permissions, cache state, and background disk activity.
