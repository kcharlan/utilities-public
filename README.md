# Utilities Toolkit

> [!WARNING]
> This repository is public. Never commit sensitive data; use synthetic examples and keep private configuration and runtime data outside the checkout.

Personal collection of automation scripts, data tooling, static browser apps, and local services. Each project documents its own runtime model. Eighteen Python launchers and Model Sentinel's standalone build step use [uv](https://docs.astral.sh/uv/) with PEP 723 inline metadata; other projects are shell utilities, static HTML/JavaScript applications, conventional Python environments, or Docker Compose stacks.

## Flagship Utilities

The most polished and feature-complete tools in the collection — each is a uv-managed, zero-setup application with a professional-grade web UI.

### cognitive_switchyard
Single-user, local-first task orchestration engine that coordinates parallel CLI work through a multi-phase pipeline. Work items flow from Markdown intake through LLM-driven planning, dependency resolution, constraint-aware worker dispatch, verification, and bounded auto-fix, with progress shown in a React dashboard. Runner packs define workload-specific hooks and shell commands; the built-in coding packs support Claude Code and Codex-oriented workflows. Sessions support isolation, crash recovery, streaming phase logs, and interval, task-driven, and final verification.

### routerview
Self-hosted OpenRouter analytics dashboard for CSV imports. It stores imported OpenRouter Activity exports in local SQLite and serves a React dashboard with KPI cards, timeseries charts, breakdown panels, a usage heatmap, and a full generation log viewer. Calendar-aligned comparisons, cumulative cost tracking, saved views, multi-dimensional filtering, and CSV/PNG/SVG/JPG export make it a focused local replacement for the official Activity page without any live observability setup.

### git-multirepo-dashboard (Git Fleet)
Local multi-repo git dashboard for monorepos and multi-project setups. Register repository roots to get activity sparklines, branch staleness, commit history, dependency-health checks across six ecosystems, real-time SSE scan progress, a directory browser, and fleet analytics. Manifest discovery covers nested projects, with documented deduplication limits for repositories that expose the same project through overlapping roots.

### harscope
HAR file analyzer and sanitizer built for developers and security reviewers who need to understand, inspect, and safely share HTTP Archive captures. It renders a waterfall timeline, provides request/response inspection, runs value-first secret detection, creates sequence and dashboard views, and supports keyboard-driven redaction. Six export formats cover sanitized archives, findings, tabular data, and shareable reports.

### editdb
Local web-based SQLite database manager with a React data grid, inline editing, paginated browsing, schema changes, a raw SQL console, and CSV/JSON import and export. It binds to loopback by default and is intended for trusted local use; it has no authentication, and schema rebuilds can discard constraints, indexes, and triggers that the editor does not recreate.

### jtree
Interactive JSON viewer and editor that renders any JSON document as a pannable, zoomable node-graph mind map. Instead of scrolling through collapsed trees in a text editor, you explore data spatially — clicking nodes to expand branches, dragging to reposition, and using a minimap for orientation in large documents. Full CRUD editing is built in: add, rename, delete, copy/paste nodes, reorder arrays, and undo/redo up to 50 operations. Search filters across keys, values, or both, and finished visualizations export to SVG, PNG, or JPEG for documentation or presentations.

## Notable Utilities

Capable tools that solve specific problems well and see regular use.

### tax2
Builds a private offline HTML calculator from validated federal and state YAML rules. The browser computes monthly estimates with independent state allocations and downloads QIF payments, a Markdown rate schedule, and a CSV lookup reference. The uv launcher exits after building and opening the page; rerun it after rule or preference edits. See [Tax2](tax2/README.md).

### docpipe
Fully local document conversion pipeline that turns PDF, DOCX, PPTX, HTML, and XLSX files into clean Markdown and structured JSON suitable for LLM ingestion or archival. It handles the messy reality of real-world documents — extracting text, tables, speaker notes, and optionally page images — while falling back gracefully when optional backends are unavailable. Python packages are managed through uv (PEP 723); PDF conversion requires Poppler, and Pandoc enables additional fallback paths.

### expense_dock
Local OneDrive expense intake console for accountants-and-spreadsheet workflows that still need proper file handling. It authenticates against personal Microsoft accounts via Graph, creates `YYYY/YYYY-MM` receipt folders on demand inside a shared OneDrive expense root, uploads receipts with normalized filenames, creates anonymous read-only share links, then downloads and rewrites the Excel tracker in-memory with a new expense row. A focused React workspace separates submission, setup, retry queue, and workbook lookup views, while a persistent status bar keeps auth/config health visible at all times.

### mls-tracker
Exploratory MLS playoff-race dashboard that pulls standings and branding from ESPN's public API. It models a configurable cutoff using a 34-game season, current points-per-game projections, wins-only paths, maximum-tie paths, and best/worst case summaries. The labels are planning aids rather than official clinch/elimination determinations: fixtures, tiebreakers, and movement by other teams are not modeled.

## Projects At A Glance

- `abacus usage` – Automates the extraction and processing of ChatLLM credit usage data from the Abacus.AI dashboard.
- `anduril_steps` – A calculator and solver for configuring "Stepped Ramp" brightness levels (1-150) on Anduril 2 flashlights.
- `anker_charge_monitor` – Native macOS [Anker Charge Monitor](anker_charge_monitor/README.md) menu bar app for A2345 six-port charger readings, with 1Password credentials kept in process memory. Requires macOS 27 and Swift 6; the Node.js deployment CLI installs its signed app at `/Applications/Anker Charge Monitor.app`.
- `apple-health-extract` – Parse Apple Health `export.xml` to build workout summaries, heart‑rate detail, and incidental exercise bout analytics.
- `benchmark-llm` – Filesystem-first LLM benchmark runner with three authoring rails: prompt-batch packages, scripted repo-task benchmarks with preserved git worktrees and command provenance, and Python plugin benchmarks via a small `benchsdk` API.
- `brew_version` – Native macOS [Brew Version](brew_version/README.md) menu bar app and Swift CLI for watching Homebrew package versions, including third-party taps. Building requires macOS 27 and Xcode or Command Line Tools with Swift 6; deployment requires Node.js.
- `Calculation tools` – Four standalone finance calculators, an [AI model timeline](Calculation%20tools/ai-model-timeline.html), and the independently maintained [Market Atlas backtest app](Calculation%20tools/backtest/README.md). Market Atlas keeps historical data and local builds outside the public repository; its canonical [installed app](http://127.0.0.1:7711/calculators/backtest/index.html) uses the explicit index route.
- `Claude_plugin_converter` – Utilities for converting Claude-style plugins (skills and commands) to other CLI formats, currently supporting Gemini CLI.
- `coding` – Curated coding orchestration reference assets. Contains `task_orch/` (legacy task orchestration scaffold, deprecated in favor of Cognitive Switchyard) and `design_orch/` (design-document packetization and implementation loop extracted from Git Fleet).
- `cognitive_switchyard` – Local-first task orchestration engine with multi-phase pipeline (intake, planning, resolution, execution, verification, auto-fix), parallel worker dispatch, git worktree isolation, streaming phase logs, and a real-time React monitoring dashboard. Pluggable runner packs make it workload-agnostic.
- `colophon` – Independently maintained macOS C17 [session explorer](colophon/README.md) that compiles local Codex, Claude Code, OpenCode, and Antigravity sessions into a private offline HTML page, with token usage and API-equivalent estimates, including globally deduplicated Antigravity retries.
- `data_format_converter` – A dual-interface utility for analyzing and converting text data formats (JSON, XML, YAML, TOON, TOML) with LLM token count analysis.
- `div_conv` – Privacy-safe standalone converter for supported Fidelity dividend and Vanguard activity CSV exports, using local-only account/security mappings to produce cooked CSV and QIF output.
- `dloc` – Daily Lines of Code utility that parses git history to report insertions, deletions, and net changes by date.
- `docker` – Grouped home for containerized utilities, plus `propagate-updates.zsh`, which refreshes and audits stack lockfiles and redeploys running stacks (see `docker/README.md`).
- `docker/actual-data` – Docker helpers for Actual Budget. The current scripts mount the project directory as `/data`, so run them only from a private operational copy and never from a public working copy that could stage financial data.
- `docker/docker-disk-compact` – macOS Zsh utility for reclaiming Docker Desktop disk space and measuring the real physical size of `Docker.raw`.
- `docker/excalidraw` – Docker Compose setup for a local Excalidraw whiteboard instance.
- `docker/llm_collector` - Tooling for collecting LLM usage data, including the browser extension, collector service, and Docker runtime.
- `docker/llm_proxy` – Modular, stateless proxy that makes non-standard LLM provider APIs speak the OpenAI `/v1/chat/completions` protocol. Bridges T3.chat and ChatJimmy with streaming SSE translation, tool-calling format conversion, dynamic model discovery, and BYOK auto-retry.
- `docker/mermaid` – Scripts to run a local instance of the Mermaid Live Editor using Docker.
- `docker/n8n-poc` – Loopback-only n8n proof-of-concept stack with private environment configuration and persistent state outside Git.
- `docker/webserver` - Local Docker Compose web stack with Nginx, FastAPI, Express, and a configurable file browser/reverse proxy.
- `doc_linearizer` – Command-line tool that flattens multi-page HTML documentation sites into a single Markdown file, preserving TOC order, numbering, and assets.
- `docpipe` – Fully local document conversion pipeline. Converts PDF, DOCX, PPTX, HTML, and XLSX to canonical Markdown + JSON for model ingestion.
- `editdb` – Professional-grade, local web-based SQLite management utility with a React data grid, inline editing, schema changes, a SQL console, and CSV/JSON import and export.
- `expense_dock` – uv-managed FastAPI + React SPA for OneDrive-based expense intake. Uploads receipts into `YYYY/YYYY-MM`, creates anonymous receipt links, appends the Excel tracker via download-edit-upload, and keeps retry/status state in a local workspace.
- `etf_montecarlo` – Privacy-safe historical dividend-income bootstrap simulator whose holdings and run parameters live exclusively in private user-home configuration.
- `git-multirepo-dashboard` – Local multi-repo git dashboard with fleet overview, branch staleness tracking, monorepo-aware dependency scanning, and fleet-wide analytics.
- `harscope` – HAR file analyzer and sanitizer with waterfall timing, request inspection, secret detection, sequence diagrams, dashboard stats, and sanitized export.
- `hysa-excel` – Privacy-safe uv launcher that generates a formula-driven HYSA vs CD workbook from local runtime inputs under `~/.hysa-excel/` or explicit private paths.
- `jtree` – Interactive JSON viewer and editor that renders JSON as a pannable/zoomable node-graph mind map with full CRUD, copy/paste, array reordering, undo/redo, search, and SVG/PNG/JPEG export.
- `launchmaster` – Local macOS `launchd` control center with a localhost FastAPI backend, embedded React UI, and runtime state/backups under `~/.launchmaster/`.
- `md-json` – Moneydance JSON export to CSV converter with account hierarchy resolution and split transaction handling.
- `media-dater` – CLI wrapper for `exiftool` that safely renames image and video files by their creation date with collision handling and dry-run support.
- `mem_snapshots` – Two manual shell commands for capturing macOS memory and process snapshots; scheduling is optional and not included.
- `mls-tracker` – uv-managed FastAPI + React SPA playoff tracker for both MLS conferences, with dynamic ESPN-sourced team branding, a configurable cutoff position, and planning-oriented clinch/elimination indicators that do not model fixtures or tiebreakers.
- `model_sentinel` – Local CLI tracker for authenticated LLM model lists across providers. Stores saved snapshots in SQLite, diffs additions/removals/metadata drift, serves an offline Activity/Models/Catalog history browser, and can run on a schedule via user-level `launchd`.
- `moneydance backup rotation` – Standalone shell script that prunes NAS-hosted Moneydance backups by retention day, with optional file and syslog logging.
- `pdf-split` – Zsh utility that slices large PDFs into size-limited chunks using `qpdf`.
- `reversible-skew` – Burrows-Wheeler/Move-to-Front experiment with reversible block-wise compression and passthrough heuristics.
- `router-log-analyzer` – Standalone NETGEAR and TP-Link Archer router log analyzer with SQLite-backed learning where stable router identity is available, baseline/policy imports, PDF or plain-text parsing, and text/Markdown/HTML/JSON reporting.
- `routerview` – Self-hosted OpenRouter analytics dashboard for CSV imports, with calendar-aligned comparisons, cumulative cost tracking, saved views, and full export. Replaces the official OpenRouter Activity page without any live integration setup.
- `storage_monitor` – Local-first macOS disk-usage and cleanup console. Scans APFS volumes, local snapshots, caches, model stores, and large files, then serves a React dashboard with treemap breakdowns, drill-down directory exploration (with file/folder icons, on-demand scanning, Reveal in Finder, and per-directory Rescan), watchlist-based cleanup actions, and snapshot management. A native `getattrlistbulk` walker (C) indexes the volume; building and deploying it requires Xcode Command Line Tools and Node.js.
- `tax2` – Private built-page tax calculator with offline browser computation, QIF payments, and Markdown/CSV reference downloads.
- `telltale` – Native macOS [Telltale](telltale/README.md) menu bar app that watches Codex usage metadata and OpenAI status for slowdowns, failures and incidents. Requires macOS 27 and Swift 6; the Node.js deployment CLI installs its signed app at `/Applications/Telltale.app`.
- `time_machine_snapshot_monitor` – Hourly alert-only macOS monitor for Time Machine local snapshots that remain mounted after backup activity stops, with an explicit safe-repair action, bounded logs, and user-level `launchd` installation.
- `toggle_wifi` – macOS helper that briefly toggles Wi-Fi when invoked; wake detection or scheduling must be configured separately.
- `transcription` – Whisper-backed Streamlit console for bulk transcription with meticulous session/lifetime counters and batching helpers.
- `trim_last` – FFmpeg-based CLI that retains the final requested number of seconds from one or more media files.
- `usage-monthly-csv` – Standalone Zsh utility that converts the system `ccusage` Claude/Codex JSON reports to CSV, falls back to legacy CSV commands when `ccusage` or `jq` is unavailable, automatically includes the prior month near month boundaries, and writes `MMYY`-suffixed CSV reports to Downloads by default.
- `vid-compiler` – uv-managed, FFmpeg-based sampler that stitches highlight reels and tail segments from long raw footage.
- `video-scenes` – Setup and command reference for PySceneDetect scene-boundary workflows.
- `web_games/gorilla` – Modern browser remake of the classic QBasic **Gorilla.BAS** artillery game with AI opponents and local multiplayer.
- `web_games/multibody_sim` – Browser-based N-body gravity sandbox/screensaver with user setup mode, collision merges, trails/leads, and JSON save/load.
- `web_games/rps_screen` – A browser-based Rock Paper Scissors particle simulation with elastic collision physics, auto-restart "screensaver" mode, and adjustable pass-through and save-chance options.
- `worktree-helper` – Single-file, standard-library Python utility for managing `git worktree` through a curses TUI or CLI. The documented branch-based create flows work; orphan creation is currently unavailable because of a validation conflict.

The runnable projects listed above include a local README with setup and usage guidance; nested example, test, and reference directories may also carry more narrowly scoped READMEs.

## Development and deployment

Each project README describes its setup, runtime, and validation commands.
Contributor conventions and the rules for choosing a CLI, built page, static
page, or local server live in [agents.md](agents.md).

Standalone delivery takes several forms: uv-managed scripts for small Python
tools, a packaged executable for multi-file apps such as
[Model Sentinel](model_sentinel/README.md), native binaries such as
[Colophon](colophon/README.md), [Brew Version](brew_version/README.md),
[Anker Charge Monitor](anker_charge_monitor/README.md) and [Telltale](telltale/README.md), and
self-contained HTML for browser-only apps.
Some utilities deliberately duplicate small helpers so copied commands remain
independent of this checkout.

Shared repository tooling lives in `tools/`: the native and calculator-page
installers (`deploy_*.mjs`), the read-only fleet deployment audit
(`check_local_deployments.zsh`), the uv launcher header guard
(`check_uv_headers.py`), and the `testkit.py` browser and launcher test helpers.
Their tests are in `tools/tests/`.

Repository updates do not update installed copies. See the
[deployment guide](docs/local_deployment_sync.md) for installation, verification,
and rollback, the [maintenance to-do list](docs/todo.md) for open follow-ups, and
the [lessons learned](docs/lessons_learned.md) for cross-project pitfalls.
