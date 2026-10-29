# Project catalog

[Back to Utilities Toolkit](../README.md)

Projects are grouped by purpose rather than source-directory layout. Each linked name opens its README or a documented section of a shared README. Delivery describes how the tool is used; it does not imply an installation guarantee, offline support, or maintenance status. Read the project documentation for prerequisites and limitations.

- [AI tools and observability](#ai-tools-and-observability)
- [Development and data tools](#development-and-data-tools)
- [macOS and system utilities](#macos-and-system-utilities)
- [Finance and calculators](#finance-and-calculators)
- [Documents and media](#documents-and-media)
- [Games and visualizations](#games-and-visualizations)
- [Infrastructure and reference material](#infrastructure-and-reference-material)

## AI tools and observability

| Project | Delivery | Purpose and scope |
| --- | --- | --- |
| [Abacus.AI Usage Export](../abacus%20usage/README.md) | Bookmarklets + Python CLI | Captures ChatLLM credit-usage JSON from the signed-in dashboard and converts it to CSV. The capture uses an internal endpoint that may change. |
| [benchmark-llm](../benchmark-llm/README.md) | CLI | Runs prompt-batch, repository-task, and Python-plugin benchmarks with saved artifacts and command provenance. |
| [Colophon](../colophon/README.md) | macOS CLI → offline page | Explores Codex, Claude Code, OpenCode, and Antigravity sessions, workspaces, token usage, and API-equivalent cost estimates. |
| [LLM Proxy](../docker/llm_proxy/README.md) | Docker service | Adapts T3 Chat and ChatJimmy APIs to OpenAI-compatible chat endpoints, with streaming translation and provider-specific tool-call and retry behavior. |
| [LLM Usage Collector](../docker/llm_collector/README.md) | Browser extension + Docker service | Counts qualifying browser requests to selected LLM services; these are not token counts or billing records. The extension also offers session-local request diagnostics and export. |
| [Model Sentinel](../model_sentinel/README.md) | CLI + local web app | Tracks provider model lists, pricing, and metadata changes. Saved endpoint captures support Hosts comparisons and provider-reported uptime history; the history browser works offline. |
| [RouterView](../routerview/README.md) | Local web app | Imports OpenRouter Activity CSVs into SQLite for historical usage analysis, comparisons, filtering, and exports. |
| [Telltale](../telltale/README.md) | Native macOS app | Monitors Codex and Claude Code usage metadata alongside OpenAI and Claude service status for speed changes, failures, and incidents. A new, evolving menu bar app. |
| [usage-monthly-csv](../usage-monthly-csv/README.md) | Shell CLI | Converts system ccusage Claude/Codex reports into monthly CSVs, including prior-month handling and legacy command fallbacks. |

## Development and data tools

| Project | Delivery | Purpose and scope |
| --- | --- | --- |
| [Apple Health Workout Extractor](../apple-health-extract/README.md) | Python CLI | Extracts workout summaries, heart-rate detail, and incidental exercise bouts from Apple Health XML exports. |
| [Claude Plugin Converter](../Claude_plugin_converter/README.md) | Python CLI | Adapts Claude-style skills and commands for Gemini CLI, currently the only supported target. |
| [Cognitive Switchyard](../cognitive_switchyard/README.md) | CLI + local web app | Orchestrates parallel workloads with runner packs, planning, worktree isolation, verification, bounded auto-fix, and recoverable sessions. |
| [Data Format Converter](../data_format_converter/README.md) | Static page + Python CLI | Converts JSON, XML, YAML, TOON, and TOML. The browser estimates token counts; the CLI converts files without counting tokens. |
| [dloc](../dloc/README.md) | CLI | Summarizes Git-reported insertions, deletions, and net changes by author date; it does not measure the repository's current source-code size. |
| [EditDB](../editdb/README.md) | Local web app | Browses and edits SQLite data, runs SQL, and imports/exports CSV or JSON. Schema-editor rebuilds do not preserve keys, constraints, indexes, or triggers; consult its limitations before use. |
| [Git Fleet](../git-multirepo-dashboard/README.md) | Local web app | Reviews repository activity, working-tree state, branches, and dependency health, including nested manifest discovery and explicit check-coverage reporting. |
| [harscope](../harscope/README.md) | Local web app + validation CLI | Analyzes HAR timing and request details, detects potential secrets, records redaction decisions, and exports sanitized captures and reports. |
| [jtree](../jtree/README.md) | Local web app | Views and edits JSON as a node graph with search, undo/redo, copy/paste, array reordering, and image exports. |
| [worktree-helper](../worktree-helper/README.md) | Terminal UI + CLI | Manages Git worktrees through interactive and command-line workflows. Orphan creation is currently unavailable because of a validation conflict. |

## macOS and system utilities

| Project | Delivery | Purpose and scope |
| --- | --- | --- |
| [Anduril 2 Step Calculator](../anduril_steps/README.md) | Python CLI | Calculates stepped flashlight brightness levels and searches for floor/ceiling/step combinations. |
| [Anker Charge Monitor](../anker_charge_monitor/README.md) | Native macOS app | Displays charger-reported power, voltage, and current for the A2345 six-port charger, with credentials supplied through 1Password. |
| [Brew Version](../brew_version/README.md) | Native macOS app + CLI | Watches Homebrew formula and cask versions, including third-party taps, without upgrading packages. |
| [Docker Disk Compact](../docker/docker-disk-compact/README.md) | macOS shell CLI | Prunes Docker data and measures the physical size of Docker.raw. Offers dry-run and separately selected cleanup options. |
| [launchmaster](../launchmaster/README.md) | Local macOS web app | Inspects and manages launchd jobs, with runtime state and backups kept outside the checkout. |
| [Router Log Analyzer](../router-log-analyzer/README.md) | CLI | Analyzes supported NETGEAR and TP-Link Archer logs, with persistent learning where stable router identity is available and text, Markdown, HTML, or JSON reports. |
| [Storage Monitor](../storage_monitor/README.md) | Local macOS web app + native helper | Indexes APFS storage and presents file exploration, snapshots, and cleanup actions. Requires an explicitly built native walker; the app does not compile it at startup. |
| [Time Machine Snapshot Monitor](../time_machine_snapshot_monitor/README.md) | macOS background monitor + CLI | Alerts about local snapshots still mounted after backup activity stops. Scheduled operation is alert-only; repair is an explicit action. |
| [Toggle Wi-Fi](../toggle_wifi/README.md) | macOS shell command | Resets Wi-Fi once per invocation. Wake detection and scheduling must be configured separately. |

## Finance and calculators

The [Calculation Tools guide](../Calculation%20tools/README.md) documents the standalone calculator pages. Market Atlas is an independently maintained child project with its own build and tests. Keep operational financial inputs and outputs outside the public checkout.

| Project | Delivery | Purpose and scope |
| --- | --- | --- |
| [Actual Budget helpers](../docker/actual-data/README.md) | Docker scripts | Runs a local Actual Budget server. The scripts mount their directory as data storage: use a private operational copy, never the public checkout. |
| [div_conv](../div_conv/README.md) | CLI | Converts supported brokerage activity CSVs to cooked CSV and QIF using private local account and security mappings. |
| [Drawdown](../Calculation%20tools/README.md#drawdownhtml) | Static page | Projects monthly cash flow and principal, supports timed scenario adjustments, and maps longevity across starting-principal and income combinations. |
| [Early Loan Termination Calculator](../Calculation%20tools/README.md#early_loan_termination_calculatorhtml) | Static page | Compares the present value of vendor financing at different payoff months with paying the vendor price upfront. |
| [ETF Monte Carlo](../etf_montecarlo/README.md) | CLI | Bootstraps historical dividend payments for privately configured holdings and reports annual income distributions. |
| [Expense Dock](../expense_dock/README.md) | Local web app + Microsoft Graph | Uploads receipts to OneDrive, creates anonymous read-only receipt links, and appends an Excel tracker through download/edit/upload, with retry state. |
| [HYSA vs CD Excel Generator](../hysa-excel/README.md) | CLI → workbook | Creates a formula-driven comparison workbook from private local inputs. |
| [Lump Sum Calculator](../Calculation%20tools/README.md#lump_sum_calculatorhtml) | Static page | Solves the monthly internal rate of return equating a lump sum with a fixed payment stream and produces comparison tables. |
| [Market Atlas](../Calculation%20tools/backtest/README.md) | Built static app | Compares retirement withdrawal strategies over historical windows, with sweeps, pinned comparisons, and CSV exports. Requires separately prepared external data; data-bearing builds are not for public redistribution. |
| [Money Sense Calculators](../Calculation%20tools/README.md#money_sense_calculatorshtml) | Static page | Provides debt-payoff and savings-growth calculations with monthly tables and CSV exports. |
| [Moneydance Backup Rotation](../moneydance%20backup%20rotation/README.md) | Shell CLI | Prunes configured backups by retention day, with dry-run support and private runtime configuration. |
| [Moneydance JSON → CSV](../md-json/README.md) | Python CLI | Converts exports to flat CSV, resolving account hierarchies and split transactions. |
| [Tax2](../tax2/README.md) | CLI → offline page | Builds a private calculator from validated tax rules, with independent state allocations and QIF, Markdown, and CSV downloads. |

## Documents and media

| Project | Delivery | Purpose and scope |
| --- | --- | --- |
| [docpipe](../docpipe/README.md) | CLI | Converts PDF, DOCX, PPTX, HTML, and XLSX to Markdown and structured JSON. PDF text extraction requires Poppler; PDF tables and OCR are not supported. |
| [Excalidraw Local Environment](../docker/excalidraw/README.md) | Docker stack | Runs an Excalidraw whiteboard. Its current port mapping binds to all host interfaces; review the project configuration before starting it. |
| [HTML Documentation Linearizer](../doc_linearizer/README.md) | Python CLI | Flattens a local multi-page HTML documentation site into Markdown, preserving TOC ordering, heading numbers, and supported assets. |
| [Media Dater](../media-dater/README.md) | Shell CLI | Renames image and video files from ExifTool creation metadata, with collision handling and dry-run support. |
| [Mermaid Live Editor](../docker/mermaid/README.md) | Docker scripts | Runs the diagram editor on the host loopback interface. |
| [PDF Split by Size](../pdf-split/README.md) | Shell CLI | Uses qpdf to split PDFs into sequential size-limited chunks; an oversized single page remains a documented exception. |
| [Transcription Console](../transcription/README.md) | Local Streamlit app | Provides two Whisper-backed interfaces for batch audio transcription and processed-duration tracking. |
| [trim_last](../trim_last/README.md) | Shell CLI | Retains the requested final duration of media files using FFmpeg, with re-encoding or keyframe-limited stream copying. |
| [Video Compiler](../vid-compiler/README.md) | CLI | Creates video recaps from sampled clips and tail segments. Requires FFmpeg with the macOS VideoToolbox encoder. |

## Games and visualizations

| Project | Delivery | Purpose and scope |
| --- | --- | --- |
| [AI Model Timeline](../Calculation%20tools/README.md#ai-model-timelinehtml) | Static page | Explores a curated release dataset by lab, date, and tier through timeline and report views. D3 loads from a CDN. |
| [Gorilla.BAS Reimagined](../web_games/gorilla/README.md) | Static page | Artillery game with AI and local multiplayer, arcade progression, and procedural graphics and audio; no runtime network calls. |
| [MLS Tracker](../mls-tracker/README.md) | Local web app | Explores playoff races using ESPN standings and simplified cutoff projections. It does not model fixtures, tiebreakers, or other teams' movement and is not an official clinch/elimination model. |
| [Multibody Gravity Lab](../web_games/multibody_sim/README.md) | Static page | N-body gravity sandbox and screensaver with collision merges, trails, predictions, and JSON save/load. |
| [Rock Paper Scissors Simulator](../web_games/rps_screen/README.md) | Static page | Particle simulation with elastic collisions, configurable conversion rules, and an automatic restart mode. |

## Infrastructure and reference material

The [Docker guide](../docker/README.md) covers stack organization and update propagation; individual services are listed above by purpose. The [coding guide](../coding/README.md) describes the retained orchestration reference assets.

| Project or resource | Delivery | Purpose and scope |
| --- | --- | --- |
| [Design orchestration kit](../coding/design_orch/README.md) | Reference scripts and prompts | A design-to-implementation packet loop extracted from Git Fleet. Requires adaptation to the target project; review its agent-launch and automatic-commit behavior before reuse. |
| [Local Web Server](../docker/webserver/README.md) | Docker stack | Nginx, FastAPI, Express, and a configurable file browser/reverse proxy for local services and static content. |
| [Memory Snapshot Helpers](../mem_snapshots/README.md) | Command reference | Two manual macOS memory/process snapshot commands. No executable script or automatic scheduling is included. |
| [n8n proof of concept](../docker/n8n-poc/README.md) | Docker stack | Runs loopback-only n8n with private environment configuration and persistent state outside Git. |
| [Reversible Skew](../reversible-skew/README.md) | Experimental Python CLI | Explores blockwise Burrows–Wheeler, Move-to-Front, and run-length transforms, with unchanged-block fallback and reconstruction checks. |
| [Task orchestration scaffold](../coding/task_orch/README.md) | Legacy reference scripts and prompts | Retained source-project snapshot, superseded by Cognitive Switchyard. Its environment and test assumptions require adaptation before reuse. |
| [Video Scene Detection Cheatsheet](../video-scenes/README.md) | Setup helper and command reference | Documents PySceneDetect scene-boundary, splitting, and preview workflows. |

Shared [repository tools](../tools/) include deployment installers, the fleet deployment audit, launcher-header validation, browser/launcher test helpers, and temporary-file leak checks. Their tests live in [tools/tests/](../tools/tests/). See the [deployment guide](local_deployment_sync.md), [maintenance to-do list](todo.md), and [lessons learned](lessons_learned.md) for repository-wide guidance.

When adding or materially changing a project, update its catalog entry alongside its README. Keep detailed setup and behavior in the project documentation; the root README's featured selection is maintained separately.
