# Utilities Toolkit

> [!WARNING]
> **This is a public-facing repository. Never put sensitive data in source code or commit it here.** Do not add secrets, credentials, personal information, financial or brokerage data, health or location data, production/customer data, private exports, real account or security details, or realistic copies of any of those values to code, tests, fixtures, examples, documentation, logs, screenshots, or generated artifacts.

Use conspicuously synthetic public fixtures. Keep operational configuration and mutable state in the tool's documented user-home runtime directory. Before every commit, review the complete staged diff and file list specifically for sensitive content.

Personal collection of automation scripts, data tooling, and local web apps that back day‑to‑day workflows. Each directory contains an isolated project with its own runtime model — increasingly a [uv](https://docs.astral.sh/uv/)-managed launcher (PEP 723 inline metadata) backed by a dedicated home-directory runtime under `~/.projectname/` so copied or symlinked installs keep working without manual setup.

## Flagship Utilities

The most polished and feature-complete tools in the collection — each is a uv-managed, zero-setup application with a professional-grade web UI.

### cognitive_switchyard
Single-user, local-first task orchestration engine that coordinates parallel execution of arbitrary workloads through a multi-phase pipeline. Work items drop into an intake directory as markdown files, then flow through LLM-driven planning, dependency resolution, constraint-aware parallel dispatch to worker slots, verification, and bounded auto-fix — all visible in a real-time React dashboard. Runner packs make the engine workload-agnostic: the built-in `claude-code` pack turns it into a parallel coding agent orchestrator, but the same pipeline handles any CLI-driven workload. Sessions support git worktree isolation, idempotent crash recovery, streaming phase logs, and a three-trigger verification system (interval, task-driven, and mandatory final). The web UI provides setup, live monitoring with pipeline strip and worker cards, session history, and global settings management.

### routerview
Self-hosted OpenRouter analytics dashboard for CSV imports. It stores imported OpenRouter Activity exports in local SQLite and serves a React dashboard with KPI cards, timeseries charts, breakdown panels, a usage heatmap, and a full generation log viewer. Calendar-aligned comparisons, cumulative cost tracking, saved views, multi-dimensional filtering, and CSV/PNG/SVG/JPG export make it a focused local replacement for the official Activity page without any live observability setup.

### git-multirepo-dashboard (Git Fleet)
Local multi-repo git dashboard built for monorepos and multi-project setups. Register a directory of repos and get a fleet overview with activity sparklines, branch staleness tracking, and full dependency health scanning across Python, Node, Go, Rust, Ruby, and PHP ecosystems. Dependency detection walks subdirectories up to three levels deep, so monorepos with scattered manifest files are fully covered — each dependency tracks exactly which sub-project it belongs to. A full scan aggregates commit history into daily stats, lists all branches with stale/active badges, and runs ecosystem-specific outdated and vulnerability checks. Real-time SSE progress streaming, a built-in directory browser for repo registration, and fleet-wide analytics (commit heatmaps, time allocation, cross-repo dependency overlap) round out the feature set.

### harscope
HAR file analyzer and sanitizer built for developers and security reviewers who need to understand, inspect, and safely share HTTP Archive captures. It renders a full waterfall timeline of network requests, lets you drill into individual request/response pairs with an interactive inspector, and runs value-first secret detection to flag leaked credentials or tokens. Sequence diagrams and dashboard summaries give you a high-level picture at a glance, while inline keyboard-driven redaction lets you surgically sanitize sensitive data before export. Output formats include cleaned HAR, CSV, Markdown, and self-contained HTML reports.

### editdb
Professional-grade, local web-based SQLite database manager that brings an Airtable-style editing experience to any `.db` file. Point it at a database from the command line and get a high-performance React data grid with sticky headers, inline editing, and paginated browsing. The schema designer handles column additions, type changes, and renames through automated migrations, while a built-in SQL console with query history covers ad-hoc exploration. Import and export support CSV and JSON, and the whole tool runs localhost-only with SQL injection protection baked in — no cloud, no accounts, no setup beyond running the script.

### jtree
Interactive JSON viewer and editor that renders any JSON document as a pannable, zoomable node-graph mind map. Instead of scrolling through collapsed trees in a text editor, you explore data spatially — clicking nodes to expand branches, dragging to reposition, and using a minimap for orientation in large documents. Full CRUD editing is built in: add, rename, delete, copy/paste nodes, reorder arrays, and undo/redo up to 50 operations. Search filters across keys, values, or both, and finished visualizations export to SVG, PNG, or JPEG for documentation or presentations.

## Notable Utilities

Capable tools that solve specific problems well and see regular use.

### tax2
Full rules-driven tax engine that computes federal and state income tax from YAML-defined bracket tables, deductions, and credits. It supports dynamic year selection, precomputed lookup tables for fast queries, consistency cross-checking between rules and tables, and QIF export for direct import into Quicken or Moneydance. The web UI offers multiple operational modes — rules compute, table lookup, cross-check, and QIF export — while a CLI mode handles batch table generation for all supported years.

### docpipe
Fully local document conversion pipeline that turns PDF, DOCX, PPTX, HTML, and XLSX files into clean Markdown and structured JSON suitable for LLM ingestion or archival. It handles the messy reality of real-world documents — extracting text, tables, speaker notes, and optionally page images — while falling back gracefully when optional backends are unavailable. Python packages are managed through uv (PEP 723); PDF conversion requires Poppler, and Pandoc enables additional fallback paths.

### expense_dock
Local OneDrive expense intake console for accountants-and-spreadsheet workflows that still need proper file handling. It authenticates against personal Microsoft accounts via Graph, creates `YYYY/YYYY-MM` receipt folders on demand inside a shared OneDrive expense root, uploads receipts with normalized filenames, creates anonymous read-only share links, then downloads and rewrites the Excel tracker in-memory with a new expense row. A focused React workspace separates submission, setup, retry queue, and workbook lookup views, while a persistent status bar keeps auth/config health visible at all times.

### mls-tracker
Live MLS playoff race dashboard that pulls standings from ESPN's public API and layers on clinch/elimination logic, configurable cutoff position analysis, and playoff scenario breakdowns. It shows worst-case and easiest-path projections, identifies which results a team needs from other matches, and dynamically sources team branding (colors and logos) so the display stays current. Built for the stretch run of the season when every match matters and the scenarios get complicated.

## Projects At A Glance

- `abacus usage` – Automates the extraction and processing of ChatLLM credit usage data from the Abacus.AI dashboard.
- `anduril_steps` – A calculator and solver for configuring "Stepped Ramp" brightness levels (1-150) on Anduril 2 flashlights.
- `apple-health-extract` – Parse Apple Health `export.xml` to build workout summaries, heart‑rate detail, and incidental exercise bout analytics.
- `benchmark-llm` – Filesystem-first LLM benchmark runner with three authoring rails: prompt-batch packages, scripted repo-task benchmarks with preserved git worktrees and command provenance, and Python plugin benchmarks via a small `benchsdk` API.
- `Calculation tools` – Browser-based finance calculators for drawdown/solvency, lump-sum, early-loan-payoff, and MoneySense scenarios.
- `Claude_plugin_converter` – Utilities for converting Claude-style plugins (skills and commands) to other CLI formats, currently supporting Gemini CLI.
- `coding` – Curated coding orchestration reference assets. Contains `task_orch/` (legacy task orchestration scaffold, deprecated in favor of Cognitive Switchyard) and `design_orch/` (design-document packetization and implementation loop extracted from Git Fleet).
- `cognitive_switchyard` – Local-first task orchestration engine with multi-phase pipeline (intake, planning, resolution, execution, verification, auto-fix), parallel worker dispatch, git worktree isolation, streaming phase logs, and a real-time React monitoring dashboard. Pluggable runner packs make it workload-agnostic.
- `data_format_converter` – A dual-interface utility for analyzing and converting text data formats (JSON, XML, YAML, TOON, TOML) with LLM token count analysis.
- `div_conv` – Privacy-safe standalone converter for supported Fidelity dividend and Vanguard activity CSV exports, using local-only account/security mappings to produce cooked CSV and QIF output.
- `dloc` – Daily Lines of Code utility that parses git history to report insertions, deletions, and net changes by date.
- `docker` – Grouped home for containerized utilities (see `docker/README.md`).
- `docker/actual-data` – Docker configuration and data for Actual Budget, a local-first personal finance application.
- `docker/docker-disk-compact` – macOS Zsh utility for reclaiming Docker Desktop disk space and measuring the real physical size of `Docker.raw`.
- `docker/excalidraw` – Docker Compose setup for a local Excalidraw whiteboard instance.
- `docker/llm_collector` - Tooling for collecting LLM usage data, including the browser extension, collector service, and Docker runtime.
- `docker/llm_proxy` – Modular, stateless proxy that makes non-standard LLM provider APIs speak the OpenAI `/v1/chat/completions` protocol. Bridges T3.chat and ChatJimmy with streaming SSE translation, tool-calling format conversion, dynamic model discovery, and BYOK auto-retry.
- `docker/mermaid` – Scripts to run a local instance of the Mermaid Live Editor using Docker.
- `docker/webserver` - Local Docker Compose web stack with Nginx, FastAPI, Express, and a configurable file browser/reverse proxy.
- `doc_linearizer` – Command-line tool that flattens multi-page HTML documentation sites into a single Markdown file, preserving TOC order, numbering, and assets.
- `docpipe` – Fully local document conversion pipeline. Converts PDF, DOCX, PPTX, HTML, and XLSX to canonical Markdown + JSON for model ingestion.
- `expense_dock` – uv-managed FastAPI + React SPA for OneDrive-based expense intake. Uploads receipts into `YYYY/YYYY-MM`, creates anonymous receipt links, appends the Excel tracker via download-edit-upload, and keeps retry/status state in a local workspace.
- `editdb` – Professional-grade, local web-based SQLite management utility with a high-performance React data grid and automated schema migrations.
- `etf_montecarlo` – Privacy-safe historical dividend-income bootstrap simulator whose holdings and run parameters live exclusively in private user-home configuration.
- `git-multirepo-dashboard` – Local multi-repo git dashboard with fleet overview, branch staleness tracking, monorepo-aware dependency scanning, and fleet-wide analytics.
- `harscope` – HAR file analyzer and sanitizer with waterfall timing, request inspection, secret detection, sequence diagrams, dashboard stats, and sanitized export.
- `hysa-excel` – Privacy-safe uv launcher that generates a formula-driven HYSA vs CD workbook from local runtime inputs under `~/.hysa-excel/` or explicit private paths.
- `jtree` – Interactive JSON viewer and editor that renders JSON as a pannable/zoomable node-graph mind map with full CRUD, copy/paste, array reordering, undo/redo, search, and SVG/PNG/JPEG export.
- `launchmaster` – Local macOS `launchd` control center with a localhost FastAPI backend, embedded React UI, and runtime state/backups under `~/.launchmaster/`.
- `md-autotax` – Streamlit + CLI tools that use a private local tax table and private QIF label mappings to generate estimated-tax transactions without tracking jurisdiction or account details.
- `md-json` – Moneydance JSON export to CSV converter with account hierarchy resolution and split transaction handling.
- `media-dater` – CLI wrapper for `exiftool` that safely renames image and video files by their creation date with collision handling and dry-run support.
- `mem_snapshots` – Small shell helpers that snapshot macOS memory stats on reboot for later comparison.
- `model_sentinel` – Local CLI tracker for authenticated LLM model lists across providers. Stores saved snapshots in SQLite, diffs adds/removes/metadata drift over time, supports history queries, and can run on a schedule via user-level `launchd`.
- `mls-tracker` – uv-managed FastAPI + React SPA playoff tracker for both MLS conferences, with dynamic ESPN-sourced team branding, configurable cutoff position, and clinch/elimination logic.
- `moneydance backup rotation` – Standalone shell script that prunes NAS-hosted Moneydance backups by retention day, with optional file and syslog logging.
- `pdf-split` – Zsh utility that slices large PDFs into size-limited chunks using `qpdf`.
- `router-log-analyzer` – Standalone NETGEAR router log analyzer with persistent SQLite-backed learning, baseline/config imports, PDF or plain-text parsing, and text/Markdown/HTML/JSON reporting.
- `routerview` – Self-hosted OpenRouter analytics dashboard for CSV imports, with calendar-aligned comparisons, cumulative cost tracking, saved views, and full export. Replaces the official OpenRouter Activity page without any live integration setup.
- `storage_monitor` – Local-first macOS disk-usage and cleanup console. Scans APFS volumes, local snapshots, caches, model stores, and large files, then serves a React dashboard with treemap breakdowns, drill-down directory exploration (with file/folder icons, on-demand scanning, Reveal in Finder, and per-directory Rescan), watchlist-based cleanup actions, and snapshot management.
- `reversible-skew` – Burrows-Wheeler/Move-to-Front experiment with reversible block-wise compression and passthrough heuristics.
- `tax2` – Full rules-driven tax engine with FastAPI + React SPA UI, CLI table generation, and QIF export pipelines.
- `toggle_wifi` – Post-wake automation that briefly toggles Wi-Fi to recover network connectivity on macOS.
- `transcription` – Whisper-backed Streamlit console for bulk transcription with meticulous session/lifetime counters and batching helpers.
- `usage-monthly-csv` – Standalone Zsh utility that runs `ccusage_csv` and `cusage_csv` for the current month, automatically includes the prior month near month boundaries, and writes `MMYY`-suffixed CSV reports to Downloads by default.
- `vid-compiler` – MoviePy-based sampler that stitches highlight reels and tail segments from long raw footage.
- `video-scenes` – Quick reference commands for Detectron-based `scenedetect` workflows.
- `web_games/gorilla` – Modern browser remake of the classic QBasic **Gorilla.BAS** artillery game with AI opponents and local multiplayer.
- `web_games/multibody_sim` – Browser-based N-body gravity sandbox/screensaver with user setup mode, collision merges, trails/leads, and JSON save/load.
- `web_games/rps_screen` – A browser-based Rock Paper Scissors particle simulation with elastic collision physics, auto-restart "screensaver" mode, and customizable game rules.
- `worktree-helper` – Single-file, dependency-free Python utility for managing `git worktree` with a keyboard-driven TUI and full CLI flags. Supports create, delete, list, status, prune, open, cd, lock, unlock, move, repair, and doctor commands.

The runnable projects listed above include a local README with setup and usage guidance; nested example, test, and reference directories may also carry more narrowly scoped READMEs.

## Preferred Delivery Forms

This repo does not have a single preferred application form. It has a small number of preferred forms chosen by fit.

### Installed Utility Updates

Repository source and installed runtime copies are separate release targets. Updating a utility in this repository does not update a copy that a user previously placed on their system.

For any standalone utility installed outside the repository:

1. Complete the utility's full documented validation suite against the repository version.
2. Only after validation succeeds, copy the finished launcher, executable, or built artifact into the user's chosen executable directory on `PATH`.
3. Verify the installed artifact directly with its version, help, health-check, or another safe smoke command.
4. When practical, compare the installed artifact with the validated source or build output so an older copy cannot remain active unnoticed.

The destination is user- and platform-specific. Common choices include `~/.local/bin`, `~/bin`, a user scripts directory, or an administrator-managed executable directory. Project READMEs may show a platform-specific example, but must not treat that example as the only valid installation location.

For the maintained macOS deployment layout, tracked-file synchronization rules, Docker lifecycle checks, rollback procedure, and the read-only drift audit, see [docs/local_deployment_sync.md](docs/local_deployment_sync.md).

Copy-based installs are preferred when the utility must keep working if the repository is moved or removed. Symlinks remain useful during active development, but maintainers must not assume that committing a repository update also deploys it to existing runtime locations.

For Python utilities that a user runs directly, the default question is not "single file or not?" It is:

- does single-file materially help the delivery model?
- or has it become mostly a maintenance cost?

The main preferred forms are below.

### 1. Single-File Python Launcher

Use this when the delivered tool itself should be a single script that can be copied or symlinked into `~/Library/Scripts` (or similar) and run with zero setup beyond invoking the command.

This pattern is a strong fit when:

- the code is still comfortable to maintain in one file
- inspectability and ad hoc local edits matter
- the delivery simplicity is part of the tool's value
- the app is stable enough that file size is not creating real maintenance drag
- the embedded asset story is simple enough to keep inside one script

This is the common form for tools like `editdb`, `routerview`, `div_conv`, `docpipe`, `harscope`, `jtree`, `storage_monitor`, and similar local-first utilities.

Machine prerequisite: [uv](https://docs.astral.sh/uv/) (`brew install uv`). This launcher form depends on it.

Implementation rules:

- Begin the script with the canonical uv shebang and a PEP 723 inline-metadata block declaring the interpreter and dependencies:

  ```python
  #!/usr/bin/env -S uv run --script
  # /// script
  # requires-python = ">=3.12"
  # dependencies = [
  #     "fastapi",
  #     "uvicorn[standard]",
  # ]
  # ///
  ```

  uv resolves and caches the environment on first run (which may hit the network once); subsequent runs are fast. Stdlib-only tools use `dependencies = []`.
- Do **not** hand-roll venv bootstrap: no private venv creation, no `bootstrap_state.json` marker, no `os.execv()` re-exec, no pip invocation. uv owns the environment. The fleet drift guard `tools/check_uv_headers.py` enforces this.
- Resolve a stable runtime home under `~/.toolname/` for *mutable state only*: config, logs, databases, caches, lock files. No venv lives there.
- Avoid colocated config files next to the script. When legacy configuration contains sensitive or operational values, migrate it manually into the documented user-home runtime directory; do not add one-time migration logic to public source.
- If the tool serves a local web UI, embed the SPA in the script only when that keeps the delivery model materially simpler than splitting resources out.

Single-file is still the better fit when the single-file form is buying real simplicity. Large by itself is not a sufficient reason to abandon it.

### 2. Multi-File Python App Shipped as a Single Executable Zipapp

Use this when the user-facing delivery should still be one executable command, but the backend has outgrown a single source file and wants proper internal structure.

This pattern is a strong fit when:

- bootstrap, CLI, server, storage, and reporting logic are becoming tangled
- tests are harder to write because there are poor internal boundaries
- the code is actively growing rather than stabilizing
- you still want a single executable artifact that can be copied or symlinked
- the runtime-home model still makes sense for mutable state

`model_sentinel` is the reference example for this form.

Implementation rules:

- Develop the app as a normal package with multiple modules.
- Keep a top-level `__main__.py` specifically for the zipapp entrypoint.
- Do **not** blindly pass the whole project folder into `python -m zipapp`.
- Build from a staging directory or otherwise package only runtime-required files.
- Exclude non-runtime content such as:
  - `tests/`
  - `docs/`
  - `__pycache__/`
  - local venvs
  - audit notes and maintainer-only helper scripts
- The archive should contain code and immutable packaged resources, not the full working tree.

Runtime organization rules:

- Keep mutable state outside the archive under `~/.toolname/`:
  - config
  - logs
  - databases
  - caches
  - debug output
  - reports
- Keep immutable internal resources inside the packaged app when users are not expected to edit them.
- If assets or templates are meant to be user-editable or need normal filesystem paths, sync them into runtime storage on first run.
- For synced runtime assets, use a safe update model:
  - copy on first run
  - store version/hash metadata
  - overwrite only when the runtime copy still matches the prior standard version
  - preserve user-customized copies
  - provide an explicit reset command for forced refresh

Dependency rules:

- If the app is stdlib-only, the zipapp can run directly. `model_sentinel` is stdlib-only at runtime, so it needs no dependency-management layer.
- If a future zipapp needs third-party dependencies, embed the dependency specification in the packaged app — do not depend on a repo-local `requirements.txt` being present after the repo is gone — and prefer resolving them through uv rather than a hand-rolled private venv.

Asset rules:

- Prefer packaged immutable resources for fixed HTML/CSS/JS/templates that users should not edit.
- Prefer runtime-synced copies for templates, prompts, packs, or other resources users are expected to customize locally.
- Do not copy everything to runtime storage by default. Separate immutable packaged resources from mutable runtime content intentionally.

Install/update rules:

- Build to a temporary path first and move into place atomically.
- Treat the executable as immutable delivery code and the runtime home as mutable operator state.
- Upgrades should replace the executable without clobbering user state.

### 3. Browser-First Static App

Some projects are intentionally pure browser apps, usually as one HTML file or a very small static bundle, with no Python runtime and no bootstrap layer.

This is the right form for things like:

- `web_games/multibody_sim`
- `web_games/gorilla`
- the calculators under `Calculation tools`

Do not force these into the Python zipapp pattern. If they stay backend-free, plain static delivery is usually the better design.

## Choosing Between the Forms

Use the single-file Python launcher when:

- the single-file form is still helping the delivery model
- the app is easy enough to maintain in one file
- inspectability and in-place edits matter more than internal modularity

Use the zipapp form when:

- the single-file form is now mainly hurting maintainability
- the app wants module boundaries and cleaner tests
- you still want one executable distribution artifact

Keep a project browser-first and static when:

- there is no meaningful backend
- no runtime-home/venv model is needed
- the app is naturally served as plain HTML/CSS/JS

Do not use the zipapp pattern for:

- pure static browser apps
- Docker stacks and other multi-service deployments
- very small tools where packaging complexity would add more ceremony than value

## Intentional Code Duplication

Many projects in this repo are designed to be standalone local utilities that can be copied or symlinked into `~/Library/Scripts` (or any other location) and keep working without imports from the source tree or mutable sidecar files in the repo. That delivery model means certain logic blocks are intentionally duplicated across projects rather than extracted into a shared module.

Environment management is no longer duplicated: the hand-rolled self-bootstrapping venv pattern (private venv under `~/.toolname/`, `bootstrap_state.json` marker, `os.execv()` re-exec) that formerly appeared in a dozen launchers has been replaced by uv's PEP 723 inline metadata, so there is now a single declarative header per tool and no bootstrap code to keep in sync. The remaining intentional duplication is narrower: tools that serve a local web UI each carry their own `find_free_port()` implementation, and standalone HTML calculators under `Calculation tools/` each embed their own CSS theme variables.

This is a deliberate tradeoff: some duplication is the cost of standalone deployability and runtime independence. The canonical launcher guidance lives in `agents.md`, `tools/check_uv_headers.py` enforces the uv-header contract across the fleet, and `model_sentinel` is the reference for the packaged multi-file zipapp form.
