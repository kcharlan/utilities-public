# Cognitive Switchyard Architecture

This is the architecture reference for Cognitive Switchyard: its boundaries, the
contracts between the engine and runner packs, the state model, and the
recovery guarantees. It records intent and invariants that are not obvious from
any single module. For commands, operator workflow, and the full `pack.yaml`
schema, use [`README.md`](../README.md), the
[Operator Guide](operator_guide.md), and the
[Pack Author Guide](pack_author_guide.md). Where this document and the code
disagree, the code and its tests win; fix this document.

Paths below are relative to the `cognitive_switchyard/` package unless stated
otherwise.

---

## 1. Purpose and Boundaries

Cognitive Switchyard is a single-user, local-first engine that runs a batch of
work items through a multi-phase pipeline: intake, planning, dependency
resolution, constrained parallel execution, verification, and auto-fix. A
FastAPI server and an embedded UI provide setup and live monitoring; the
same pipeline also runs headless from the CLI.

The engine is workload-agnostic. Workload-specific behavior lives in **runner
packs**: directories whose manifest, prompts, and scripts define how each phase
behaves for one kind of task. The bundled packs (`claude-code`, `codex-hybrid`,
`codex`, `test-echo`) are coding and smoke-test workflows; nothing in the engine
is coding-specific.

### Core principles

- **Separation of concerns.** The orchestrator owns *when* and *where* work runs
  (scheduling, worker slots, state, recovery). The pack owns *how* (prompts,
  isolation, execution, verification command).
- **Filesystem as source of truth.** A task's state is the directory holding
  its plan file. SQLite is a queryable projection that can be rebuilt from the
  directories (section 5).
- **Recoverable restart.** After a crash, kill, or power loss, starting or
  resuming the same session reconciles persisted state and resumes incomplete
  work (section 8). Hooks and executors that cause external side effects own
  their own idempotency.

### What it is not

- Not a multi-tenant or networked service. The server has no authentication
  and no Host/Origin validation, and it can launch agents with permission
  bypass enabled, so it must stay bound to `127.0.0.1` (the `serve` default).
- Not a credential manager. Agent CLIs must already be installed and
  authenticated; preflight reports missing prerequisites but never provisions
  or injects secrets.
- Not an agent framework. It invokes supported agent CLIs (Claude Code and
  Codex) as subprocesses for planning, resolution, auto-fix, and, through pack
  scripts, execution.

---

## 2. Architecture Overview

```
                        +-----------------+
                        |    Web UI       |
                        |  (Preact SPA)   |
                        +--------+--------+
                                 |
                            WebSocket + REST
                                 |
                        +--------+--------+        CLI (switchyard start)
                        |  FastAPI Server  |        runs the same pipeline
                        |  SessionController|       in the foreground
                        +--------+--------+
                                 | one background thread per running session
              +------------------+------------------+
              |                  |                   |
     +--------+-------+ +-------+--------+ +--------+-------+
     |  Orchestrator   | |  Pack Loader   | |  State Store   |
     |  planning +     | |  manifest,     | |  SQLite +      |
     |  resolution,    | |  hook lookup,  | |  session dirs  |
     |  scheduler,     | |  built-in sync | |                |
     |  verification   | |                | |                |
     +--------+-------+ +-------+--------+ +--------+-------+
              |                  |
     +--------+--------+  +------+-------------------------+
     | Agent runtimes   |  | Pack scripts and commands      |
     | (Claude / Codex  |  | isolate_start, execute,        |
     |  CLI subprocess) |  | isolate_end, resolve,          |
     +------------------+  | preflight, verification cmd    |
                           +--------------------------------+
```

Worker slots are subprocesses managed by `worker_manager.py`; agent phases
(planner, resolver, fixer) run through `agent_runtime.py`. When a session is
created through the web backend with `COGNITIVE_SWITCHYARD_REPO_ROOT` and
`COGNITIVE_SWITCHYARD_BRANCH`, the server creates a session git worktree as a
peer directory of the source repository and points the session's repo root at
it, so workers never touch the original checkout. Worktree lifetime is
described in the Operator Guide.

---

## 3. Pipeline and Run Lifecycle

```
Intake --> Planning --> Staging --> Resolution --> Ready --> Execution --> Done
              |                         |                       |
              +-------> Review <--------+                    Blocked
                     (human input)
                                Verification / Auto-Fix gate dispatch
```

All phases except execution are optional per pack.

### 3.1 Intake and runs

Work items are Markdown files placed in the session's `intake/` directory by
the operator (any editor; the UI only lists, opens, and reveals them). The
`intake/` directory also holds `NEXT_SEQUENCE` and, for packs that ship
`prompts/intake.md`, a seeded `CLAUDE.md`; neither is a work item.

Sessions are **multi-run**. A run plans and resolves the intake batch present
at its start, executes it, and then leaves the session `idle`. Starting the
session again from `idle` begins a new run if there is new intake, ready work,
or blocked work. A session becomes `completed` only when the operator ends an
idle session (section 5.1).

Intake is batch-oriented because resolution builds one constraint graph over
the whole batch: adding tasks after resolution would invalidate dependency and
anti-affinity decisions. The UI marks intake as locked once a session leaves
`created`, and files that arrive later are processed by the next run.

An intake item whose ID prefix matches a plan already in `done/` aborts
planning (duplicate work). An item whose ID is already live in `staging/`,
`ready/`, `review/`, or a worker slot is skipped.

### 3.2 Planning (optional)

Planning turns intake items into execution plans.

- Up to the effective planner count of planner agents run in parallel. Each
  claims an item by atomic rename from `intake/` to `claimed/`.
- The planner agent returns plan text; the orchestrator parses it and writes it
  atomically to `staging/<id>.plan.md`, or to `review/` when the plan body
  contains `## Questions for Review`. Unparseable output or a planner exception
  produces a review plan that preserves the error for the operator.
- Agent planning requires `COGNITIVE_SWITCHYARD_REPO_ROOT` in the session
  environment and runs the agent there.
- With planning disabled, intake files must already be `.plan.md` plans and
  move straight to `staging/`.

Plans are Markdown with YAML front matter. `PLAN_ID` is required;
`DEPENDS_ON`, `ANTI_AFFINITY`, `EXEC_ORDER`, and `FULL_TEST_AFTER` are the
constraint fields (section 5.3).

### 3.3 Resolution (optional, recommended)

Resolution analyzes all staged plans together and assigns `DEPENDS_ON`,
`ANTI_AFFINITY`, and `EXEC_ORDER`. The resolver reads what planners surfaced
(scope, inputs, outputs, declared dependencies); it does not need to
understand the workload.

| Executor | Behavior |
|----------|----------|
| `agent` (default) | Resolver agent returns `resolution.json` content. If the agent fails, every input plan moves to `review/`. |
| `script` | The pack's `resolve` hook must write `resolution.json` at the session root. |
| `passthrough` | Uses declared `DEPENDS_ON` verbatim, sets `EXEC_ORDER` from dependency depth, and flags unknown or circular dependencies. |

For every task in the graph, the orchestrator rewrites the plan's front matter
with the resolved constraints, writes it to `ready/`, and upserts its database
row. Plans missing from the graph or named in a conflict (unknown or circular
dependency) move to `review/`. Execution proceeds with whatever reached
`ready/`.

Declared dependencies are preserved verbatim only by `passthrough`. Agent and
script resolvers are expected by their prompt or script contract to keep and
extend declared dependencies; the engine uses their output as written.

### 3.4 Execution

The orchestrator loop dispatches ready tasks into worker slots `0..N-1`, where
N is the effective worker count (the session override capped at the pack's
`max_workers`).

A task is eligible when it is `ready`, every `DEPENDS_ON` task is `done`, and
no task in its own `ANTI_AFFINITY` list is `active`. Anti-affinity is checked
only from the dispatching task's list, so resolvers should write it
symmetrically. Among eligible tasks the lowest `(EXEC_ORDER, task_id)` wins.

For each dispatch:

1. `isolate_start` creates the task workspace and prints its path. With
   `isolation.type: none`, both isolation hooks are skipped and the workspace
   is the session root. A failing hook or empty output blocks the task.
2. The plan moves to `workers/<N>/` and the pack's `execution.command` is
   launched with the plan path and workspace. Output goes to
   `logs/workers/<N>.log` and `logs/tasks/<task_id>.log`.
3. Recovery metadata (`workers/<N>/recovery.json`) is written immediately after
   launch, since it records the PID.
4. On exit, the **status sidecar** decides the outcome (section 4.4). A missing
   or invalid sidecar is a failure even with exit code 0.
5. On success, `isolate_end` runs with `done` (merge). If it fails, the task is
   blocked. Otherwise the task moves to `done/`.
6. On failure or timeout, the task goes through task auto-fix when eligible
   (section 3.6), otherwise `isolate_end` runs with `blocked` and the task moves
   to `blocked/`.

The run ends when nothing is ready or active. With blocked tasks remaining, the
loop returns and leaves them for the operator (retry, move, or a new run).
Otherwise final verification runs if due, and the session becomes `idle`. If
ready tasks exist but none can ever become eligible and no worker is active,
the loop records a `session.deadlock` event and returns without changing the
session status.

### 3.5 Verification (optional)

Verification runs the pack's `phases.verification.command` (a shell string,
not a hook) with the session root as working directory, logging to
`logs/verify.log`. It runs only when no task is active. Three triggers exist:

- **Interval:** every `interval` completed tasks. Dispatch is frozen in advance
  when completed plus in-flight tasks would reach the interval, so the batch
  drains before verification instead of overshooting it.
- **Task-driven:** dispatching a `FULL_TEST_AFTER: yes` task freezes further
  dispatch, and its completion requests verification. The scheduler delays such
  tasks to coincide with the interval verification when it can.
- **Final:** once per run before going idle, if the run completed any task.

A pass clears the freeze and resumes dispatch. A failure starts the
verification auto-fix loop if auto-fix is enabled; otherwise the session moves
to `paused`.

### 3.6 Auto-fix (optional)

Auto-fix runs the pack's fixer agent with bounded attempts
(`auto_fix.max_attempts`) before escalating to the operator.

- **Task failure:** applies only when auto-fix is enabled **and** verification
  is enabled with a command. The task workspace is kept for the fixer; each
  attempt gets the plan, status sidecar, worker log, verification log, failure
  kind, and the previous attempt's summary and verification output. A fix
  counts only if the verification command then passes; the orchestrator never
  trusts the fixer's own report. Success runs `isolate_end` with `done`;
  exhaustion runs it with `blocked` and blocks the task.
- **Verification failure:** each attempt is followed by re-verification.
  Exhausting the attempts moves the session to `paused`.

---

## 4. Runner Pack Contract

The [Pack Author Guide](pack_author_guide.md) is the maintained reference for
the `pack.yaml` schema, defaults, validation, and conventional hook discovery.
This section records the invocation contract the orchestrator guarantees.

### 4.1 Pack layout

```
packname/
  pack.yaml       # Manifest
  README.md
  prompts/        # Agent prompts; prompts/intake.md is seeded into intake/CLAUDE.md
  scripts/        # Hooks and helper scripts (any executable with a shebang)
  templates/      # Intake, plan, and status templates for authors and agents
```

Packs load only from `~/.cognitive_switchyard/packs/`. Built-in packs are
copied there by sync on every stateful CLI command; sync replaces only runtime
copies that still match their recorded `.builtin_hash`, so customized copies
survive until `reset-pack` or `reset-all-packs`.

### 4.2 Manifest

See the Pack Author Guide for every field. Invariants the engine relies on:

- `phases.execution` is required and enabled. The worker dispatcher launches
  `phases.execution.command`; `executor: agent` validates but is not wired into
  dispatch, so agent-backed workers are shell commands that invoke a CLI.
- Agent phases (`planning`, `resolution` with `executor: agent`, `auto_fix`)
  select a runtime (`claude` or `codex`), a model, a prompt, and an optional
  reasoning effort.
- `timeouts` and `status` defaults apply per pack; session config can override
  worker count, planner count, timeouts, auto-fix, verification interval, poll
  interval, and environment.

### 4.3 Hook invocation contracts

| Hook | Arguments | CWD | When |
|------|-----------|-----|------|
| `preflight` | none | pack root | Session start, after prerequisite checks |
| `isolate_start` | `slot task_id session_root` | session root | Before each dispatch; must print the workspace path |
| `execute` (`execution.command`) | `plan_path workspace_path` | workspace | Per task, long-running |
| `isolate_end` | `slot task_id workspace_path final_status` | workspace, or pack root if it no longer exists | After each task; `final_status` is `done` or `blocked` |
| `resolve` | `session_root` | session root | Resolution with `executor: script`; must write `resolution.json` |

Hooks are executed directly (shebang or native binary), never through
`sh -c`, with positional arguments and captured output. The verification
command and `prerequisites[].check` strings are the exceptions: they run with
`shell=True`.

**Preflight order.** Session start runs three stages and stops at the first
failure: (1) an orchestrator-enforced recursive scan of `scripts/` for the
executable bit, reporting a `chmod +x` fix command per file; (2) the manifest's
`prerequisites` checks, run from the pack root; (3) the optional `preflight`
hook. The scan cannot be delegated to the pack. It exists so a missing
`chmod +x` fails up front instead of surfacing as "permission denied" deep in
the pipeline. The UI runs the same preflight from its **Run Preflight**
button.

**Environment.** Hooks receive only the variables the orchestrator passes plus
the parent environment minus `CLAUDECODE` and any inherited
`COGNITIVE_SWITCHYARD_*` variables. The orchestrator passes the session
environment, `COGNITIVE_SWITCHYARD_PACK_ROOT`, and
`CODEX_WORKER_REASONING_EFFORT` when `phases.execution.reasoning_effort` is
set. `isolate_end` also receives `SWITCHYARD_COMMIT_MSG`, built from the plan
title and body, when a plan is available.

**Idempotency.** `isolate_start` must recreate a workspace left by an
interrupted run. `isolate_end` must succeed when the work is already merged or
cleaned up. `execute` is re-run from scratch in a fresh workspace after
interruption; any external side effects it causes must be safe to repeat or
accepted as repeatable.

### 4.4 Status sidecar

The executor writes `<task_id>.status` next to its plan file. Format is set by
`status.sidecar_format` (`key-value` default, `json`, or `yaml`).

```
STATUS: done | blocked
COMMITS: <comma-separated SHAs or "none">
TESTS_RAN: targeted | full | none
TEST_RESULT: pass | fail | skip
BLOCKED_REASON: <one-line reason>
NOTES: <freeform, optional>
```

`STATUS`, `COMMITS`, `TESTS_RAN`, and `TEST_RESULT` are required. `TESTS_RAN`
matches by prefix (`targeted ...`, `full ...`). `BLOCKED_REASON` is required
with `blocked` and rejected with `done`.

### 4.5 Progress protocol

Executors report progress on stdout using `status.progress_format`
(default `##PROGRESS##`, treated as a regex):

```
##PROGRESS## <task_id> | Phase: <name> | <N>/<total>
##PROGRESS## <task_id> | Detail: <freeform message>
```

Phase lines drive the worker card's segmented progress bar. Detail lines are
passed to the UI unparsed, and only the latest is shown. A repeated identical
detail line is treated as a heartbeat and does not reset the idle timer
(section 7). Phase-level agent output (planning, resolution, verification,
auto-fix) is streamed separately, with `##DETAIL## ` lines becoming phase detail
updates.

---

## 5. State Model

### 5.1 Storage model

The runtime home is `~/.cognitive_switchyard/` (directory layout in the
README). `config.yaml` holds global settings (`retention_days`,
`default_planners`, `default_workers`, `default_pack`, `terminal_app`) outside
SQLite so they survive database resets.

**SQLite** (`cognitive_switchyard.db`, stdlib `sqlite3`) holds:

- `sessions`: id, name, pack, status, `config_json` (session overrides and
  environment), timestamps, and `runtime_state_json` (run number, run timing,
  verification and dispatch-freeze flags, auto-fix context and attempt).
- `tasks`: keyed by `(session_id, task_id)`; title, status, worker slot,
  constraints, `full_test_after`, `plan_relpath`, timestamps. Rows exist from
  resolution onward; intake and claimed items are counted from the filesystem.
- `worker_slots`: slot status and current task.
- `events`: the session event log shown in the UI and kept in
  `logs/session.log`.

**Per-session files** (`sessions/<id>/`): the state directories in 5.2, plus
`resolution.json`, `logs/` (`session.log`, `verify.log`, `workers/<N>.log`,
`tasks/<task_id>.log`), `workers/<N>/recovery.json` and status sidecars while a
task runs, and, after End Session, `summary.json` and `RELEASE_NOTES.md`.

**End and trimming.** Ending an idle session marks it `completed`, writes
`RELEASE_NOTES.md` (aggregated `## Operator Actions` sections from done plans,
only when any exist) and `summary.json`, then trims the directory to those two
files, `resolution.json`, and `logs/session.log`. The work product was already
delivered by `isolate_end`. Blocked and aborted sessions are never trimmed. The
History view reads the database for the list and `summary.json` for detail.

**Retention.** When `serve` or `start` runs, completed and aborted sessions
whose `completed_at` is older than `retention_days` are deleted with their
worktrees (`0` disables). Idle sessions are never auto-purged.

### 5.2 File-as-state mapping

| Directory | Status | Meaning |
|-----------|--------|---------|
| `intake/` | intake | Raw, unclaimed |
| `claimed/` | planning | Claimed by a planner |
| `staging/` | staged | Planned, awaiting resolution |
| `review/` | review | Needs human input |
| `ready/` | ready | Resolved, queued for dispatch |
| `workers/<N>/` | active | Executing in slot N |
| `done/` | done | Completed |
| `blocked/` | blocked | Failed; needs operator action |

The filesystem is the source of truth. A status change commits the database row
first and then moves the file; if the process dies in between,
`reconcile_filesystem_projection()` restores the row from the file location.
Reconciliation also marks rows whose plan file has disappeared as `blocked`. It
runs during recovery and on demand through the Rescan action
(`POST /api/sessions/{id}/rescan`).

### 5.3 Constraint graph format

Resolution output is JSON (`resolution.json`) for reliable parsing:

```json
{
  "resolved_at": "2026-03-05T14:16:45Z",
  "tasks": [
    { "task_id": "038", "depends_on": [], "anti_affinity": [], "exec_order": 1 },
    { "task_id": "040", "depends_on": [], "anti_affinity": ["041", "042"], "exec_order": 1 }
  ],
  "groups": [
    {
      "name": "schema-editor",
      "type": "anti_affinity",
      "members": ["040", "041", "042"],
      "shared_resources": ["src/frontend/assets/js/schema-editor.js"]
    }
  ],
  "conflicts": [],
  "notes": "Maximum parallelism: 4 workers"
}
```

`tasks` is required, with `task_id` and `exec_order` required per task.
`resolved_at`, `groups`, `conflicts`, and `notes` are optional. Agent output
wrapped in a code fence is accepted. The orchestrator normalizes and rewrites
the file after parsing.

| Constraint | Semantics |
|------------|-----------|
| `DEPENDS_ON` | Hard dependency: wait until every listed task is `done` |
| `ANTI_AFFINITY` | Mutual exclusion: never run while a listed task is `active`; no ordering implied |
| `EXEC_ORDER` | Dispatch priority among eligible tasks (lower first) |
| `FULL_TEST_AFTER` | Freeze dispatch while the task runs and verify after it completes |

---

## 6. Server, API, and UI

### 6.1 Frontend delivery

The UI is a single embedded HTML string (`html_template.py`) served at `/`
with a bootstrap JSON payload. There is no npm, bundler, or `node_modules`.

The embedded frontend uses Preact, project CSS, inlined fonts and icons, and a first-party DAG canvas. It loads without external browser resources and communicates with the local server for application data. Browser tests cover offline startup and DAG interactions.

Visual direction: a dense, dark operational dashboard with status-colored
accents. The design tokens live in the template's `:root` block.

### 6.2 UI views

- **Setup:** two-step flow (Create Session, then Start Session); pack, counts,
  repo root, branch (or create branch), and project directory; verification
  interval and Advanced auto-fix overrides, which start blank ("Pack default")
  with the selected pack's value from `/api/packs` as the hint and are sent
  only when the operator sets them; poll interval and the three timeouts (sent
  as `task_idle`, `task_max`, `session_max`; blank keeps the pack default, `0`
  means no limit); intake list with Open Intake, Intake
  Terminal, Refresh, and per-file reveal; Run Preflight showing the three
  preflight stages.
- **Monitor:** pipeline strip (including Review and Verifying, with Rescan and
  Reprocess), phase log streams for planning, resolution, verification, and
  auto-fix, worker cards, task feed, verification and auto-fix status, and New
  Run and End Session controls when idle. Worker cards warn at two-thirds of
  `task_idle`; the server raises its alert at 80%.
- **Task detail:** metadata, constraints, plan path, events, live or retained
  log, and Move or Reveal actions.
- **DAG:** Interactive graph of `resolution.json`. Each node shows its task
  title and status, colored by status; `task_status_change` messages update
  them while the view is open. Double-click a node to open the task.
- **History and Settings:** completed and aborted sessions with release notes
  and task outcomes, and Purge All, which deletes exactly those listed
  sessions; global settings from `config.yaml`.

### 6.3 WebSocket protocol

Clients connect to `/ws`. Server messages are `{"type": ..., "data": ...}`:

| Type | Target | Payload |
|------|--------|---------|
| `state_update` | all clients | Full dashboard payload, as returned by `GET /api/sessions/{id}/dashboard`: session (including run number and timing), pipeline counts and directories, workers, recent events, runtime state, effective runtime config, planning agents |
| `log_line` | subscribers of `worker_slot` | `worker_slot`, `task_id`, `line`, `timestamp`, plus parsed phase fields for phase lines |
| `log_line` (phase) | all clients | Same shape with `worker_slot: -1` and `task_id` like `__phase_verification__` |
| `task_status_change` | all clients | `task_id`, `old_status`, `new_status`, `worker_slot`, `notes`, timing fields |
| `progress_detail` | all clients | `worker_slot`, `task_id`, `detail`, `timestamp` |
| `alert` | all clients | `severity`, `message`, and the task and slot when applicable |

Clients send `{"type": "subscribe_logs", "worker_slot": N}` and
`{"type": "unsubscribe_logs", "worker_slot": N}`. A subscriber receives every
line for that slot. The server keeps the idle timer authoritative: worker idle
state reaches clients through `state_update` snapshots (throttled to one per
second when no new output arrives), not through client-side resets.

### 6.4 REST API

Routes are defined in `server.py` `create_app()`; `tests/test_server.py` covers
them.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Embedded SPA |
| GET | `/api/packs`, `/api/packs/{name}` | Pack list (with the Setup defaults: worker and planner limits, verification interval, auto-fix enabled and attempts) and detail |
| POST | `/api/browse-directory` | Native folder picker |
| POST | `/api/resolve-path` | Expand a path; report git status and branch |
| POST | `/api/repo-branches`, `/api/repo-create-branch` | List or create branches in a repo |
| POST | `/api/sessions` | Create a session (201; 409 if it exists); creates the session worktree when requested |
| GET | `/api/sessions` | List sessions |
| DELETE | `/api/sessions` | Purge every completed and aborted session and its worktree; idle sessions are kept |
| GET | `/api/sessions/{id}` | Session plus recent events |
| DELETE | `/api/sessions/{id}` | Purge one `created`, `idle`, `completed`, or `aborted` session (409 otherwise or while its thread runs) |
| POST | `/api/sessions/{id}/start` | Launch the pipeline in a background thread (202) |
| POST | `/api/sessions/{id}/pause`, `/resume`, `/abort` | Status control (202); resume from `idle` starts a new run |
| POST | `/api/sessions/{id}/end` | End an idle session: complete, summarize, trim, clean up the worktree (202; 409 unless idle) |
| POST | `/api/sessions/{id}/reprocess` | Re-run planning, resolution, and execution on existing files (202; `created`, `idle`, or `paused` with no active workers) |
| POST | `/api/sessions/{id}/rescan` | Reconcile the database with the filesystem |
| POST | `/api/sessions/{id}/cleanup-worktree` | Remove the session worktree after review |
| POST | `/api/sessions/{id}/force-reset` | Abort if needed, remove worktree and `switchyard-*` branches, delete rows and directory |
| POST | `/api/sessions/{id}/preflight` | Run the three-stage preflight |
| GET | `/api/sessions/{id}/dashboard` | Dashboard payload (same shape as `state_update`) |
| GET | `/api/sessions/{id}/dag` | `resolution.json`, or a graph built from task rows, with each known task's `title` and `status` joined from the state store (or `summary.json` once ended) |
| GET | `/api/sessions/{id}/intake` | Intake files with lock and snapshot flags |
| POST | `/api/sessions/{id}/open-intake`, `/open-intake-terminal` | Open intake in the file manager or the configured terminal (204) |
| POST | `/api/sessions/{id}/reveal-file?path=` | Reveal a session-relative file; path traversal rejected (204) |
| GET | `/api/sessions/{id}/tasks`, `/tasks/{tid}` | Task list and detail |
| GET | `/api/sessions/{id}/tasks/{tid}/log?offset=&limit=` | Paginated task log |
| POST | `/api/sessions/{id}/tasks/{tid}/retry` | Move a task back to `ready` (202) |
| POST | `/api/sessions/{id}/tasks/{tid}/move` | Move a task between allowed states (`{"target_status": ...}`; 409 if not allowed) |
| GET, PUT | `/api/settings` | Read or write `config.yaml` |
| WS | `/ws` | Live updates |

---

## 7. Timeout Model

Three independent limits protect against runaway work. Pack `timeouts` set the
defaults; session config can override them.

- **Task idle (`task_idle`, default 420 s).** A worker with no output for this
  long is killed. Any output line resets the timer except a detail line
  identical to the previous one (a heartbeat). The server raises a warning
  alert at 80% of the limit.
- **Task max (`task_max`, default 0 = unlimited).** Wall-clock cap per task,
  with a warning alert at 80%.
- **Stale execute.** If an agent's output file already contains its final
  result line, the execute script has produced no output for 30 s, and no
  status sidecar exists yet, the worker is killed. This catches wrappers that
  hang after their agent exits.
- **Session max (`session_max`, default 14400 s).** Measured from the start of
  the current run's execution phase; planning, resolution, and idle time are
  excluded. On expiry every worker is killed, its task is blocked, and the
  session becomes `aborted` with full artifacts kept.

Kills send SIGTERM, wait a 5-second grace period, then SIGKILL. A task killed
by idle, max, or stale-execute is handled like any task failure (auto-fix if
eligible, otherwise blocked); the slot is freed and the run continues. The
reason goes to the event log, the session log, and an error alert.

---

## 8. Crash Recovery and Restart

Idempotency is guaranteed for the orchestrator's own operations: file moves,
state transitions, worker lifecycle, and dispatch decisions. It does not cover
pack scripts or external tools. The orchestrator promises to re-dispatch an
interrupted task cleanly into a fresh workspace; what happens inside that
workspace is the pack's responsibility (section 4.3).

The rule is: **incomplete work is reverted, completed work is preserved.**

### 8.1 When recovery runs

Recovery runs when a session in `running`, `paused`, `verifying`, or
`auto_fixing` is re-entered by `switchyard start` or by Start or Resume in the
UI. Starting the server does not recover sessions by itself. An unhandled
exception in a session thread marks the session `aborted`.

### 8.2 Execution recovery

`recovery.py` `recover_execution_session()`:

1. For each `workers/<N>/` holding a plan, read `recovery.json`
   (`{"task_id", "workspace_path", "pid"}`) to locate the workspace.
2. Classify by sidecar. `STATUS: done` means completed but uncollected: run
   `isolate_end` with `done` (a failure is logged as a warning), project the
   task to `done`, and clear the metadata.
3. Anything else (no sidecar, `blocked`, or malformed) is incomplete: terminate
   the recorded PID (SIGTERM, grace, SIGKILL), run `isolate_end` with
   `blocked`, delete the sidecar, and return the task to **`ready`**, since the
   failure was infrastructure, not the task. If `isolate_end` fails, the
   workspace is force-removed only when it lies inside the session directory.
4. `cleanup_orphaned_workspaces()` handles `recovery.json` files with no plan:
   it terminates the PID and runs `isolate_end` with `blocked`, falling back to
   removal. Steps 3 and 4 skip `isolate_end` when `isolation.type` is `none`.
5. `reconcile_filesystem_projection()` brings the database in line with the
   directories.

`recovery.json` is written right after the worker process starts and cleared
after `isolate_end` and the state projection commit. A crash between launch and
that write leaves no metadata: the plan is still reverted to `ready`, but the
process is not terminated by PID and `isolate_end` receives the session root as
its workspace.

### 8.3 Planning and resolution recovery

- Every planning run first moves `claimed/` items back to `intake/`. Planning
  is atomic per item: a plan lands complete in `staging/` or `review/`, or the
  item returns to intake. Staged and review plans are kept.
- Every resolution run first deletes `resolution.json`, moves each `ready/`
  plan back to `staging/`, deletes its task row, and then re-resolves the whole
  set. Re-running resolution is therefore always safe.

### 8.4 Session state machine

| State | Meaning | On start or resume |
|-------|---------|--------------------|
| `created` | Draft; not started, or reset after planning or resolution stopped without ready work | Run preflight, planning, resolution, execution |
| `planning` | Planners running | Re-enter planning; `claimed/` returns to intake |
| `resolving` | Resolver running | Re-run resolution over staging plus ready |
| `running` | Execution active | Execution recovery, then resume dispatch |
| `paused` | Operator pause, or verification or auto-fix exhausted | Start re-enters as paused; Resume sets `running` and continues |
| `verifying` | Verification command running | Recover, then replay verification |
| `auto_fixing` | Fixer running | Recover, replay verification, then continue the fix loop from the next attempt |
| `idle` | Run finished | New run if new intake, ready, or blocked work exists; End Session completes it |
| `completed` | Ended by the operator; trimmed | Read-only history |
| `aborted` | Operator abort, session timeout, or thread crash | Read-only history; artifacts kept |

Pausing stops new dispatch. Active workers finish, and then the loop exits.

### 8.5 Idempotency by operation

| Operation | How |
|-----------|-----|
| Claim (intake to claimed) | Atomic `rename`; a missing file means another planner claimed it |
| Plan, resolution, and recovery-metadata writes | Write to a temp file, then atomic rename |
| Resolution | Recomputed from scratch on each run (8.3) |
| Status change | Database commit, then file move; reconciliation repairs a crash in between |
| Dispatch | One task per slot; dispatching to a busy slot is an error, not a skip |
| Status sidecar | Written by the executor; its presence and validity signal completion |
| `isolate_start` and `isolate_end` | Pack contract: safe to repeat (4.3) |

---

## 9. Design Constraints and Deferred Items

### Constraints

- The frontend stays a single embedded HTML string with no runtime asset downloads.
- The launcher `switchyard` is a uv PEP 723 script and the single entry point.
  Its header is authoritative for runtime dependencies; `requirements.txt` and
  `requirements-dev.txt` reproduce the development and test environment. There
  is no private venv or bootstrap re-exec. Runtime-home setup is in
  `runtime_env.py`.
- The server port is scanned from the preferred default (`find_free_port()`,
  20 ports from 8100), never hard-coded.
- Remote execution is a pack concern: an execute hook may SSH or rsync
  anywhere; the orchestrator only runs it and captures output.

### Deferred

- Multi-tenant or multi-user operation
- Pack marketplace or sharing
- CI/CD or webhook-triggered sessions
- Mobile-first UI (responsive rules are best-effort; the console is
  desktop-oriented)
- Non-coding example packs

---

## 10. Maintainer References

| Area | Implementation and contract tests |
|------|-----------------------------------|
| Runtime paths and session directories | `config.py`, `runtime_env.py` |
| Pack parsing, sync, and hook safety | `pack_loader.py`, `hook_runner.py`, `tests/test_pack_loader.py`, `tests/test_hook_runner.py` |
| Scheduling and artifact formats | `scheduler.py`, `parsers.py`, `tests/test_scheduler.py`, `tests/test_parsers.py` |
| Persistence and recovery | `state.py`, `recovery.py`, `tests/test_state_store.py`, `tests/test_recovery.py` |
| Planning, resolution, and agent runtimes | `planning_runtime.py`, `agent_runtime.py`, `tests/test_planning_runtime.py`, `tests/test_agent_runtime.py` |
| Execution, verification, and auto-fix | `orchestrator.py`, `worker_manager.py`, `verification_runtime.py`, and their test modules |
| API and frontend contracts | `server.py`, `html_template.py`, `tests/test_server.py`, `tests/test_html_template.py`, `tests/test_e2e.py` |
| Built-in packs | `builtin_packs/`, `docs/builtin_*_pack.md`, `tests/test_builtin_verify_scripts.py` |
