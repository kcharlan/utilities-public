# Storage Monitor

Storage Monitor is a local-first macOS disk-usage and cleanup console. It scans APFS volumes, local snapshots, caches, app data, model stores, and large user files, then presents the results in a React dashboard with graphical breakdowns, reclaim estimates, and explicit cleanup actions.

It follows the repo's uv-managed local web app pattern:

- Python backend (uv-managed via a PEP 723 header; requires [uv](https://docs.astral.sh/uv/), `brew install uv`)
- localhost-only FastAPI server
- embedded React SPA
- runtime home under `~/.storage_monitor/`

## Quick Start

Run the entrypoint directly:

```zsh
./storage_monitor
```

Or symlink it into your `PATH`:

```zsh
ln -s "$(pwd)/storage_monitor" /usr/local/bin/storage_monitor
storage_monitor
```

On first run, uv resolves the launcher's dependencies (fastapi, uvicorn[standard]) into its shared cache — that invocation may briefly hit the network. Storage Monitor creates its runtime home at `~/.storage_monitor/`, creates its SQLite scan database, saves scan history locally, then launches the web UI in your browser.

## Current Capabilities

- **3-zone dashboard**: compact header bar, treemap + accordion breakdowns, tabbed action panel
- **Dark mode**: auto-detects OS preference, manual toggle, persists to localStorage
- **Single-pass scan streaming**: one parallel volume walk feeds every section, with live phase and directory-count progress
- **Treemap visualization**: proportional CSS Grid blocks for the 4 root storage areas with click-to-expand
- **Volume-wide drill-down breakdowns**: the complete Data volume is indexed in one pass, so deep directories open directly from SQLite; file vs folder icons distinguish navigable directories from leaf files
- **Reveal in Finder**: open any drilled-into directory in Finder from the breakdown header
- **Per-directory Rescan**: rescan a single subtree after external changes (e.g. manual deletions in Finder) — updates the directory listing, treemap sizes, and top-level container stats in one action
- APFS container and Data-volume accounting
- Local snapshot inventory with dedicated manager (sort, multi-select, bulk delete)
- Enriched APFS snapshot details, purgeability/shrink-floor badges, and user-controlled snapshot thinning
- Directory growth and shrink comparisons across completed scans
- Read-only cleanup estimates with explicit execution for Homebrew and Docker; uv cleanup is shown as a copyable manual command because Storage Monitor's parent uv process holds the cache lock while the app runs
- Automatic discovery of large cache-named directories outside the fixed watchlist
- Report-only app-leftover heuristics for Containers and Group Containers, with Reveal in Finder
- Visible live data vs APFS-reported usage delta
- Top-level breakdowns for:
  - `/System/Volumes/Data`
  - `~/`
  - `~/Library`
  - `/Applications`
- Watchlist-based scanning for caches, model stores, stale installers, app runtime payloads, and large data buckets
- Volume-wide large-file inventory (files >= 1 GB) in a dedicated tab
- Typical full scans complete in roughly 35 seconds on the benchmarked machine, down from about 128 seconds
- Safe cleanup actions:
  - move cache-like paths to `~/.Trash/`
  - move stale installer staging paths to `~/.Trash/`
  - delete individual or bulk local snapshots
  - reveal a file or directory in Finder
- **Immediate targeted refresh** after actions for metadata, affected breakdowns, and durable cached scan data
- Per-section staleness timestamps ("scanned Xm ago")

## Runtime State

Runtime files live under `~/.storage_monitor/`:

- `storage_monitor.db` -- durable scan index and cached drill-down data; old scan rows are self-pruned and free space is reclaimed automatically. Compact directory history is retained for the 60 most recent scans in `scan_dir_history`, independently of the 30-run report cap.
- `latest_scan.json` -- most recent completed scan
- `history/` -- dated scan snapshots
- `action_log.jsonl` -- cleanup action log
- `last_port` -- most recent port used

## Validation

Create the tracked test environment and run the full suite:

```zsh
cd /Users/example/source/utilities/storage_monitor
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Runtime smoke checks:

```zsh
./storage_monitor --help
UTILITIES_TESTING=1 STORAGE_MONITOR_HOME="$(mktemp -d)" ./storage_monitor --no-browser --port 8473
```
