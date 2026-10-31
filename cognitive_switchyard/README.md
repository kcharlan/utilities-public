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

When a session is created through the web backend with both `COGNITIVE_SWITCHYARD_REPO_ROOT` and `COGNITIVE_SWITCHYARD_BRANCH` environment variables, the backend creates a git worktree in a peer directory of the source repo. Workers operate on the worktree, leaving the original checkout untouched. Idle sessions retain their worktrees for subsequent runs. Completed runs retain them for validation and merge review until the operator uses the completion card's cleanup action. Aborted sessions, explicitly ended idle sessions, and deleted or purged sessions clean up their worktrees.

## Architecture

```
                    +-----------------+
                    |    Web UI       |
                    |  (Preact SPA)   |
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

- **Backend:** Python 3.12 through 3.15, FastAPI, uvicorn, aiosqlite, PyYAML
- **Frontend:** Single-file embedded Preact SPA (no runtime asset downloads)
- **State:** SQLite + file-as-state directories
- **uv-managed:** Single entry point (`switchyard`) with a PEP 723 header; uv resolves dependencies on first run (requires [uv](https://docs.astral.sh/uv/), `brew install uv`)

The embedded frontend includes Preact, its icons and fonts in the HTML template. The browser needs no external frontend resources; it communicates with the local server for application data. Browser tests cover offline startup and DAG interactions.

## Quick Start

```bash
# Web UI mode (recommended)
./switchyard serve

# Headless CLI mode
./switchyard start --session my-session --pack claude-code
```

The `serve` command starts a FastAPI server (default `127.0.0.1:8100`; override with `--host`/`--port`) with the embedded SPA and opens it in the default browser. Set `COGNITIVE_SWITCHYARD_NO_BROWSER=1` to suppress browser launch. If the requested port is occupied, the server scans the next 19 ports and uses the first available one.

`start` creates the session if it does not exist (using `--pack`, or `default_pack` from `config.yaml`) and otherwise resumes it; resuming with a different `--pack` is refused. Both `start` and `serve` first delete completed and aborted sessions that finished more than `retention_days` ago.

On first run, `./switchyard` (via uv) resolves its dependencies into uv's shared cache, creates the runtime home at `~/.cognitive_switchyard/`, writes a default `config.yaml`, and syncs built-in packs. The launcher does not create or maintain a private bootstrap virtual environment.

## Data Directories

```
~/.cognitive_switchyard/                # Runtime home
  cognitive_switchyard.db               # SQLite state store
  config.yaml                           # Global settings (retention_days, default_planners, default_workers, default_pack, terminal_app)
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
        session.log
        verify.log
        workers/                        # Per-slot logs
        tasks/                          # Per-task logs
      resolution.json                   # Resolved constraint graph
      summary.json                      # Written when an idle session is ended
      RELEASE_NOTES.md                  # Aggregated "## Operator Actions" sections, when any exist
```

A successful run leaves the session `idle` so it can be run again. Ending an idle session from the web UI (`POST /api/sessions/{id}/end`) marks it completed, writes `summary.json` and `RELEASE_NOTES.md`, and trims the session directory to `summary.json`, `resolution.json`, `logs/session.log`, and `RELEASE_NOTES.md`. Blocked or aborted sessions are not trimmed.

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

Built-in packs are synced to the runtime directory whenever `packs`, `sync-packs`, `init-pack`, `start`, or `serve` runs. Sync updates only runtime copies that still match the last deployed built-in content; a customized runtime copy (or one deployed before the `.builtin_hash` marker existed) is left alone. Use `./switchyard reset-pack <name>` or `reset-all-packs` to overwrite a runtime copy with the bundled version.

## Web UI

The embedded SPA provides four main views:

- **Setup** -- Create sessions, configure packs, set repo root/branch for worktree isolation, run preflight checks, manage intake items
- **Monitor** -- Real-time pipeline strip, streaming phase logs (planning/resolution/execution), worker cards with progress bars and log tails, verification progress countdown, auto-fix attempt tracking
- **History** -- Browse completed/aborted sessions, view release notes and task outcomes
- **Settings** -- Global configuration (retention, default counts, default pack)

The Monitor also opens a task detail view with logs and status, and an interactive dependency DAG view.

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
| `COGNITIVE_SWITCHYARD_SOURCE_REPO` | Web backend | Original repository root, recorded when the backend creates a session worktree; the built-in verifier can reuse its virtualenv. |
| `COGNITIVE_SWITCHYARD_PROJECT_DIR` | Session/operator | Optional repository-relative subdirectory used by the built-in verification scripts in a monorepo. |
| `COGNITIVE_SWITCHYARD_PACK_ROOT` | Orchestrator | Absolute path to the active runtime pack directory, available to hooks and verification commands. |
| `COGNITIVE_SWITCHYARD_NO_BROWSER` | Server/operator | Set to a non-empty value to prevent `serve` from opening a browser. |
| `COGNITIVE_SWITCHYARD_DEBUG` | Server/operator | Set to `1` to emit backend debug traces. |
| `CLAUDE_CODE_WORKER_MODEL` | Operator (optional) | Overrides the `claude-code` pack's worker model (default `sonnet`). |
| `CODEX_WORKER_MODEL` | Operator (optional) | Overrides the `codex` and `codex-hybrid` worker model (default `gpt-5.6-sol`). |
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

From the repository root:

```bash
UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py cognitive_switchyard
```

The suite contains unit, integration, launcher/CLI, and browser E2E tests. If Chromium is missing, install it once with `UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py cognitive_switchyard --install-browsers`. E2E tests start their own Uvicorn server.

Starlette 1.6.0 still emits the following upstream AnyIO deprecation while its
test client module is imported:

```text
DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
```

Keep this warning visible and recheck it when the next stable Starlette release
is available. The default-warning suite also currently reports
`ResourceWarning`s from unclosed SQLite connections and existing subprocess or
stream cleanup paths. Resource-lifecycle cleanup is tracked as a separate
follow-up rather than being hidden by a global warning filter.

```bash
# Run unit/integration tests (fast)
UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py cognitive_switchyard -- --ignore=tests/test_e2e.py --ignore=tests/test_cli.py

# Run E2E tests (starts its own server)
UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py cognitive_switchyard -- -k test_e2e
```

## Documentation

- [Architecture](docs/cognitive_switchyard_design.md) -- Pipeline, pack contract, state model, API, timeout and recovery reference
- [Packet Loop Orchestrator Design](docs/codex_packet_loop_orchestrator_design.md) -- Design of `scripts/codex_packet_loop.zsh`, the packet automation loop used to build this project, and its supported agent CLIs
- [Design-Doc Packetization Playbook](docs/design_doc_packetization_playbook.md) -- The packet loop's default bootstrap input. This copy is the older version used for this project's build; the maintained copy is [`coding/design_orch/docs/design_doc_packetization_playbook.md`](../coding/design_orch/docs/design_doc_packetization_playbook.md)
- [Pack Author Guide](docs/pack_author_guide.md) -- How to create, validate, and iterate on custom runtime packs
- [Operator Guide](docs/operator_guide.md) -- How to bootstrap, run, monitor, and troubleshoot local sessions
- [Built-In Claude Code Pack Guide](docs/builtin_claude_code_pack.md) -- Claude Code pack prerequisites, prompts, and customization points
- [Built-In Codex Hybrid Pack Guide](docs/builtin_codex_hybrid_pack.md) -- Hybrid Claude/Codex pack prerequisites, prompts, and customization points
- [Built-In Codex Pack Guide](docs/builtin_codex_pack.md) -- Codex pack prerequisites, prompts, and customization points
- [Lessons Learned](docs/LESSONS_LEARNED.md) -- Bug patterns and debugging insights
