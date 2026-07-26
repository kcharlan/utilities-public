# Storage Monitor

Storage Monitor is a local-first macOS disk-usage and cleanup console. It indexes the writable APFS Data volume, inventories local Time Machine snapshots, and surfaces large files and cleanup candidates in a React dashboard. Scan data and action logs remain on the Mac.

The application is a single executable Python file:

- a uv-managed FastAPI backend;
- a localhost-only web server;
- an embedded React UI whose browser libraries are loaded from public CDNs; and
- mutable runtime state under `~/.storage_monitor/` by default.

## Requirements

- macOS with APFS, `diskutil`, and `tmutil`
- [uv](https://docs.astral.sh/uv/) (`brew install uv`)
- a browser with network access to load React, Babel, Tailwind CSS, and Lucide from their CDNs

## Quick Start

From this directory, run:

```zsh
./storage_monitor
```

Or symlink it into your `PATH`:

```zsh
ln -s "$(pwd)/storage_monitor" /usr/local/bin/storage_monitor
storage_monitor
```

On first run, uv resolves FastAPI and uvicorn into its shared cache, so that invocation may briefly use the network. Storage Monitor then:

1. creates its runtime directory and SQLite index;
2. stops a prior Storage Monitor process recorded in that runtime directory, if one is still running;
3. starts a scan;
4. binds to `127.0.0.1`, preferring port 8473 and trying the next 19 ports if necessary; and
5. opens the dashboard in the default browser.

Use `--no-browser` to suppress the browser launch or `--port PORT` (`-p PORT`) to choose a different preferred port:

```zsh
./storage_monitor --no-browser --port 8500
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

The roughly 35-second full-scan figure shown during development was measured on one machine. Actual time depends on directory count, storage performance, permissions, and concurrent disk activity.

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

Runtime files live under `~/.storage_monitor/` by default. Set `STORAGE_MONITOR_HOME` to use another directory. `STORAGE_MONITOR_SCAN_WORKERS` controls the parallel walk size and is clamped to 1–16 workers (default: 8).

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
.venv/bin/python -m pytest -q
```

Runtime smoke checks:

```zsh
./storage_monitor --help
UTILITIES_TESTING=1 STORAGE_MONITOR_HOME="$(mktemp -d)" ./storage_monitor --no-browser --port 8473
```

The second command starts the server and an automatic scan in an isolated runtime directory; stop it with `Ctrl-C`.
