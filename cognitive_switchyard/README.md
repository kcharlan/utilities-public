# Cognitive Switchyard

A single-user, local-first task orchestration engine that coordinates parallel execution of arbitrary workloads through a multi-phase pipeline. It manages task intake, planning, dependency resolution, parallel dispatch with constraint enforcement, execution, verification, and auto-fix -- with a real-time web UI for monitoring and management.

## Core Concepts

**Workload-agnostic.** The engine owns the *when* and *where* of execution. Workload-specific behavior is defined by **runner packs** -- pluggable configuration bundles that specify how each pipeline phase operates for a given task type (coding with Claude Code, video transcoding with ffmpeg, media downloading with youtube-dl, etc.).

**Recoverable restart.** If the orchestrator crashes or the machine loses power, re-running the same command reconciles persisted task state and resumes incomplete work. Pack hooks and executors remain responsible for making their own external side effects safe to repeat.

**Not** a multi-tenant server, a credential manager, or an agent framework. It *uses* agentic CLIs as executors -- it does not implement agent logic itself.

## Pipeline

```
Intake --> Planning --> Staging --> Resolution --> Ready --> Execution --> Verify --> Done
                         |                                    |             |
                       Review                              Blocked      Auto-Fix
                     (human input)                     (needs escalation)
```

Packs declare which phases they use. All phases are optional except Execution.

- **Intake** -- Raw work items as markdown files dropped into a directory
- **Planning** -- Convert intake items into detailed execution plans (LLM-driven, with streaming output)
- **Resolution** -- Analyze all plans to determine dependencies, mutual exclusions, and execution order
- **Execution** -- Dispatch tasks to parallel worker slots with constraint enforcement
- **Verification** -- Global test suite after task batches complete (interval-based, task-triggered, and mandatory final)
- **Auto-Fix** -- Automatically attempt to fix failures with bounded retries before escalating

## Session Worktree Isolation

When a session is created with both `COGNITIVE_SWITCHYARD_REPO_ROOT` and `COGNITIVE_SWITCHYARD_BRANCH` environment variables, the backend creates a git worktree in a peer directory of the source repo. Workers operate on the worktree, leaving the original repository untouched. Worktrees are cleaned up automatically when sessions complete, abort, or are deleted.

## Architecture

```
                    +-----------------+
                    |    Web UI       |
                    |  (React SPA)    |
                    +--------+--------+
                             |
                        WebSocket + REST
                             |
                    +--------+--------+
                    |  FastAPI Server  |
                    +--------+--------+
                             |
          +------------------+------------------+
          |                  |                   |
 +--------+-------+ +-------+--------+ +--------+-------+
 |  Orchestrator   | |  Pack Loader   | |  State Store   |
 |  (scheduler,    | |  (registry,    | |  (SQLite +     |
 |   dispatcher,   | |   lifecycle    | |   file dirs)   |
 |   collector)    | |   hooks)       | |                |
 +--------+-------+ +-------+--------+ +--------+-------+
          |                  |                   |
 +--------+--------+                    +--------+--------+
 |  Worker Slots    |                    |  Session Dirs   |
 |  (subprocess     |                    |  (intake, ready,|
 |   management)    |                    |   workers, done,|
 +---------+--------+                    |   blocked, logs)|
           |                             +-----------------+
 +---------+---------+
 | Pack scripts      |
 | (isolate_start,   |
 |  execute,         |
 |  verify command,  |
 |  isolate_end)     |
 +-------------------+
```

## Tech Stack

- **Backend:** Python 3.12+, FastAPI, uvicorn, aiosqlite, PyYAML
- **Frontend:** Single-file embedded React 18 SPA (CDN-loaded, no npm/node_modules)
- **State:** SQLite + file-as-state directories
- **uv-managed:** Single entry point (`switchyard`) with a PEP 723 header; uv resolves dependencies on first run (requires [uv](https://docs.astral.sh/uv/), `brew install uv`)

## Quick Start

```bash
# Web UI mode (recommended)
./switchyard serve

# Headless CLI mode
./switchyard start --session my-session --pack claude-code
```

The `serve` command starts a FastAPI server with the embedded React SPA and opens it in the default browser. Set `COGNITIVE_SWITCHYARD_NO_BROWSER=1` to suppress browser launch. If the requested port is occupied, the server scans the next 19 ports and uses the first available one.

On first run, `./switchyard` (via uv) resolves its dependencies into uv's shared cache, creates the runtime home at `~/.cognitive_switchyard/`, writes a default `config.yaml`, and syncs built-in packs. The launcher does not create or maintain a private bootstrap virtual environment.

## Data Directories

```
~/.cognitive_switchyard/                # Runtime home
  cognitive_switchyard.db               # SQLite state store
  config.yaml                           # Global settings (retention, worker counts, default pack)
  packs/                                # Runtime packs (built-in + custom)
    claude-code/
    codex-hybrid/
    codex/
    test-echo/
  sessions/                             # Per-session artifacts
    <session-id>/
      intake/                           # Raw work items (markdown)
      claimed/                          # Items being planned
      staging/                          # Plans awaiting dependency resolution
      review/                           # Plans needing human input
      ready/                            # Plans ready for dispatch
      workers/                          # Active worker slots
      done/                             # Completed plans
      blocked/                          # Plans that need operator attention
      logs/                             # Session and worker logs
        workers/                        # Per-slot logs
        tasks/                          # Per-task logs
```

## Runner Packs

A pack is a directory containing:

```
packname/
  pack.yaml          # Metadata, phase config, capabilities
  prompts/           # Agent prompts (planner, resolver, worker, fixer, system)
  scripts/           # Lifecycle hooks (isolate_start, execute, verify, etc.)
  templates/         # Templates for intake items, plans, status files
```

Built-in packs:

| Pack | Description | Execution |
|------|-------------|-----------|
| `claude-code` | Claude CLI driven software delivery | Shell executor, 4 max workers |
| `codex-hybrid` | Claude planning/fixing with Codex execution | Shell executor, 3 max workers |
| `codex` | Strict OpenAI Codex CLI driven software delivery | Shell executor, 3 max workers |
| `test-echo` | Minimal test pack for pipeline validation | Shell echo script, 4 max workers |

Packs are synced to the runtime directory on first run and can be refreshed with `./switchyard sync-packs` or reset individually with `./switchyard reset-pack <name>`.

## Web UI

The embedded React SPA provides four views:

- **Setup** -- Create sessions, configure packs, set repo root/branch for worktree isolation, run preflight checks, manage intake items
- **Monitor** -- Real-time pipeline strip, streaming phase logs (planning/resolution/execution), worker cards with progress bars and log tails, verification progress countdown, auto-fix attempt tracking
- **History** -- Browse completed/aborted sessions, view release notes and task outcomes
- **Settings** -- Global configuration (retention, default counts, default pack)

Real-time updates flow through WebSocket: state changes, task status transitions, worker log lines, progress detail markers, and alerts.

## Constraint System

- **DEPENDS_ON** -- Hard dependency: task waits until all dependencies reach `done/`
- **ANTI_AFFINITY** -- Mutual exclusion: task waits until no conflicting tasks are active
- **EXEC_ORDER** -- Tiebreaker for dispatch priority among eligible tasks

## Verification System

Three triggers fire the verification command:

1. **Interval** -- Every N completed tasks (configurable, default 4)
2. **Task-driven** -- Tasks with `FULL_TEST_AFTER: yes` force immediate verification
3. **Final** -- Mandatory verification before declaring a session complete

When verification fails, the auto-fix loop runs the fixer agent up to N attempts (configurable, default 2), re-verifying after each fix. If all attempts fail, the session pauses for operator intervention.

## Pack and Server Environment

Session environment values are configured in the Setup view or inherited by the headless CLI. The orchestrator also supplies pack-specific values where noted:

| Variable | Source | Description |
|----------|--------|-------------|
| `COGNITIVE_SWITCHYARD_REPO_ROOT` | Session/operator | Repository in which planning, execution, and verification run. For a UI-created isolated session, the backend rewrites this to the session worktree. |
| `COGNITIVE_SWITCHYARD_BRANCH` | Session/operator | With `COGNITIVE_SWITCHYARD_REPO_ROOT`, requests a session worktree when the session is created through the web backend. |
| `COGNITIVE_SWITCHYARD_PROJECT_DIR` | Session/operator | Optional repository-relative subdirectory used by the built-in verification scripts in a monorepo. |
| `COGNITIVE_SWITCHYARD_PACK_ROOT` | Orchestrator | Absolute path to the active runtime pack directory, available to hooks and verification commands. |
| `COGNITIVE_SWITCHYARD_NO_BROWSER` | Server/operator | Set to a non-empty value to prevent `serve` from opening a browser. |
| `CLAUDE_CODE_WORKER_MODEL` | Operator (optional) | Overrides the `claude-code` pack's worker model (default `sonnet`). |
| `CODEX_WORKER_MODEL` | Operator (optional) | Overrides the `codex` and `codex-hybrid` worker model (default `gpt-5.4`). |
| `CODEX_WORKER_REASONING_EFFORT` | Manifest/orchestrator | Passed to shell execution when `phases.execution.reasoning_effort` is configured. |

## CLI Reference

```bash
./switchyard --help                              # Show all commands
./switchyard paths                               # Print canonical runtime paths
./switchyard packs                               # List available runtime packs
./switchyard sync-packs                          # Sync built-in packs to runtime
./switchyard reset-pack <name>                   # Reset a built-in pack to factory
./switchyard reset-all-packs                     # Reset every built-in pack to factory
./switchyard init-pack <name>                    # Scaffold a new custom pack
./switchyard validate-pack <path>                # Validate pack structure and config
./switchyard start --session <id> --pack <name>  # Start a headless session
./switchyard serve                               # Start the web UI server
```

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -v
```

The suite contains unit, integration, launcher/CLI, and browser E2E tests. The development requirements install Playwright's Python packages; install the Chromium browser once with `.venv/bin/playwright install chromium`. E2E tests start their own Uvicorn server.

```bash
# Run unit/integration tests (fast)
.venv/bin/python -m pytest tests/ --ignore=tests/test_e2e.py --ignore=tests/test_cli.py

# Run E2E tests (starts its own server)
.venv/bin/python -m pytest tests/test_e2e.py
```

## Documentation

- [Design Document](docs/cognitive_switchyard_design.md) -- Full specification
- [Packet Loop Orchestrator Design](docs/codex_packet_loop_orchestrator_design.md) -- Design of the packet automation loop and its supported agent CLIs
- [Pack Author Guide](docs/pack_author_guide.md) -- How to create, validate, and iterate on custom runtime packs
- [Operator Guide](docs/operator_guide.md) -- How to bootstrap, run, monitor, and troubleshoot local sessions
- [Built-In Claude Code Pack Guide](docs/builtin_claude_code_pack.md) -- Claude Code pack prerequisites, prompts, and customization points
- [Built-In Codex Hybrid Pack Guide](docs/builtin_codex_hybrid_pack.md) -- Hybrid Claude/Codex pack prerequisites, prompts, and customization points
- [Built-In Codex Pack Guide](docs/builtin_codex_pack.md) -- Codex pack prerequisites, prompts, and customization points
- [Lessons Learned](docs/LESSONS_LEARNED.md) -- Bug patterns and debugging insights
