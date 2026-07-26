# Cognitive Switchyard -- Generic Task Orchestration Engine

## Design Document v0.1

**Date:** 2026-03-07
**Status:** Draft -- design review

> This is a reusable, unimplemented product design retained for future orchestration work. It does not describe Git Fleet's runtime architecture or claim that Cognitive Switchyard exists in this directory.

---

## 1. What Is Cognitive Switchyard

Cognitive Switchyard is a single-user, local-first task orchestration engine that coordinates parallel execution of arbitrary workloads through a multi-phase pipeline. It manages task intake, planning, dependency resolution, parallel dispatch with constraint enforcement, execution, verification, and auto-fix -- with a real-time web UI for setup, monitoring, and management.

The engine is workload-agnostic. Workload-specific behavior is defined by **runner packs** -- pluggable configuration bundles that specify how each pipeline phase operates for a given task type (coding with Claude Code, video transcoding with ffmpeg, media downloading with youtube-dl, etc.).

### Core Principles

**Separation of concerns:** The orchestrator owns the *when* and *where* of execution. The pack owns the *how*.

**Idempotent restart:** If the orchestrator crashes, is killed, or the machine loses power, the user re-runs the same command and the session resumes from where it left off. No manual cleanup, no data loss, no duplicate work. This applies to every phase -- planning, resolution, and execution. The orchestrator must detect incomplete state on startup and recover automatically.

### What Cognitive Switchyard Is Not

- Not a multi-tenant server. Single user, local machine.
- Not a credential manager. The user's environment must have CLIs authenticated and tools installed. Cognitive Switchyard validates prerequisites at startup and reports failures -- it does not provision, authenticate, or inject secrets.
- Not an agent framework. It *uses* agentic CLIs (Claude Code, Codex, Gemini CLI) as executors. It does not implement agent logic itself.

---

## 2. Architecture Overview

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
                        |  (Python)        |
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
              +------ calls -----+                   |
              |                                      |
     +--------+--------+                    +--------+--------+
     |  Worker Slots    |                    |  Session Dirs   |
     |  (subprocess     |                    |  (intake, ready,|
     |   management)    |                    |   workers, done,|
     +---------+--------+                    |   blocked, logs)|
               |                             +-----------------+
     +---------+---------+
     | Pack Hooks        |
     | (isolate_start,   |
     |  execute,         |
     |  verify,          |
     |  isolate_end)     |
     +-------------------+
```

---

## 3. Pipeline Phases

### Phase Overview

```
Intake --> Planning --> Staging --> Resolution --> Ready --> Execution --> Done
                          |                                    |
                        Review                              Blocked
                      (human input)                     (needs escalation)
```

Packs declare which phases they use. All phases are optional except Execution.

### 3.1 Intake

**What:** Raw work items arrive as markdown files in the session's `intake/` directory.

**How it works:**
- User creates `.md` files externally (any editor) and drops them into the intake directory.
- The UI watches the intake directory via filesystem polling (or inotify if available) and displays new items as they appear.
- Intake items follow a template defined by the pack.
- No in-UI editor. The UI is a monitor, not an authoring tool.

**Intake is closed at session start.** Once the user clicks "Start," the orchestrator snapshots the current intake directory contents as the session's task set. Files dropped into the intake directory after session start are ignored for the current session. This is required because the resolution phase builds a constraint graph over the full task set -- adding tasks after resolution would invalidate dependency and anti-affinity mappings, potentially causing merge conflicts, missed dependencies, or constraint violations. The UI must communicate this clearly: after session start, the intake file list should show a "Session locked" indicator and any new files detected should appear grayed out with a note like "Will not be processed in current session."

**Pack declares:** Intake template (`templates/intake.md`), file naming convention.

### 3.2 Planning (optional)

**What:** Convert intake items into detailed execution plans.

**When used:** Workloads where intake items need decomposition, analysis, or enrichment before execution. Coding tasks, complex multi-step workflows. Not needed for pre-specified batch jobs (ffmpeg transcodes, downloads).

**How it works:**
- Orchestrator launches 1-N planner agents in parallel.
- Each planner claims an intake item (atomic file move to `claimed/`), reads it, reads any referenced context, and produces a plan file in `staging/`.
- If the planner has questions, it writes the plan to `review/` for human input.
- Pack provides the planner prompt and executor config.

**Pack declares:** `phases.planning.enabled`, `phases.planning.executor` (agent type), `phases.planning.model`, `phases.planning.prompt` (path to prompt file), `phases.planning.max_instances` (parallelism cap).

### 3.3 Resolution (optional, recommended)

**What:** Analyze all staged plans as a batch to determine dependencies (DEPENDS_ON), mutual exclusions (ANTI_AFFINITY), and execution order (EXEC_ORDER).

**When used:** Any workload where tasks may have ordering constraints or shared resource conflicts. Recommended even when users declare dependencies -- the resolver validates and augments user declarations.

**How it works:**
- Orchestrator launches a resolver agent that reads ALL staged plans.
- Resolver identifies constraint relationships by analyzing plan metadata: estimated scope (files, resources), stated dependencies, input/output relationships.
- Resolver does NOT need to understand the domain -- it reads what planners surfaced. If Task A produces `audio.wav` and Task B needs `audio.wav`, the resolver infers the dependency from the plan content regardless of whether the workload is coding, transcoding, or anything else.
- Resolver updates each plan's metadata header with constraints and writes a resolution report.
- Resolved plans move to `ready/`. Unresolvable plans (circular deps, conflicts) stay in `staging/` with notes.

**Resolution modes (pack declares which):**
- `agent` (default): LLM agent reads plans and infers constraints. Best for complex, interpretive workloads.
- `script`: Pack provides a script that programmatically determines constraints. Best for workloads with mechanical dependency rules (file existence, sequential numbering).
- `passthrough`: Trust user-declared dependencies only. Fastest, least safe. Use only for trivially independent batch jobs.

User-declared dependencies are always honored. The resolver adds to them, never removes.

**Pack declares:** `phases.resolution.enabled`, `phases.resolution.executor` (agent/script/passthrough), `phases.resolution.prompt` or `phases.resolution.script`.

### 3.4 Execution

**What:** Dispatch tasks to parallel worker slots, enforce constraints, collect results.

**How it works:**
1. Orchestrator polls for idle worker slots and eligible tasks.
2. A task is eligible when:
   - It is in `ready/` status.
   - All DEPENDS_ON tasks are in `done/` status.
   - No ANTI_AFFINITY tasks are currently in `active/` status.
3. Orchestrator selects the next eligible task (lowest EXEC_ORDER, then lowest ID).
4. Orchestrator calls the pack's `isolate_start` hook to create an isolated workspace for the task.
5. Orchestrator calls the pack's `execute` hook, passing the task file and workspace path. This spawns the executor as a subprocess.
6. Executor runs to completion. The orchestrator monitors the subprocess (PID), captures stdout/stderr to log files, and watches for progress markers.
7. On completion, orchestrator reads the status sidecar file written by the executor.
8. If successful, orchestrator calls the pack's `isolate_end` hook (merge/cleanup) and moves the task to `done/`.
9. If failed, orchestrator enters the auto-fix loop (if enabled) or moves the task to `blocked/`.

**Constraint enforcement:**
- DEPENDS_ON (hard dependency): Task waits until all dependency tasks reach `done/`.
- ANTI_AFFINITY (mutual exclusion): Task waits until no conflicting tasks are in `active/`. No ordering implied -- just "not at the same time."
- EXEC_ORDER: Tiebreaker for dispatch priority when multiple tasks are eligible.

**Worker slots:** Configurable count per session. Each slot runs one task at a time. Slots are numbered 0 to N-1.

**Pack declares:** `phases.execution.enabled` (always true), `phases.execution.executor` (agent/shell), `phases.execution.model` (for agent executors), `phases.execution.prompt` (for agent executors), `phases.execution.command` (for shell executors), `phases.execution.max_workers`.

### 3.5 Verification (optional)

**What:** Run a global verification suite after a batch of tasks completes.

**When used:** Workloads where individual task success doesn't guarantee overall system health. Coding tasks (full test suite), media pipelines (playlist validation), data processing (integrity checks).

**How it works:**
- Triggered every N completed tasks (configurable interval), or when a task requests it (FULL_TEST_AFTER: yes).
- Orchestrator pauses new dispatches, waits for active workers to finish, then runs the pack's verify command.
- If verification passes, dispatching resumes.
- If verification fails, orchestrator launches a fixer agent (if auto-fix is enabled) or halts.

**Pack declares:** `phases.verification.enabled`, `phases.verification.command`, `phases.verification.interval`.

### 3.6 Auto-Fix (optional)

**What:** Automatically attempt to fix task failures or verification failures before escalating to human.

**How it works:**
- First attempt: Fixer agent receives error context (status file, last N log lines, task file).
- If first fix fails, second attempt receives enriched context (previous fixer's changes, actual verification output).
- After max attempts exhausted, task moves to `blocked/` for human escalation.
- Fixer result is independently verified (orchestrator re-runs tests, does not trust fixer's self-report).

**Pack declares:** `auto_fix.enabled`, `auto_fix.max_attempts`, `auto_fix.model`, `auto_fix.prompt`.

---

## 4. Runner Pack Specification

### 4.1 Pack Directory Structure

```
packname/
  pack.yaml                # Metadata, phase config, capabilities
  prompts/                 # Agent prompts (if LLM-based phases)
    planner.md
    resolver.md
    worker.md
    fixer.md
    system.md              # Shared rules for all agents in this pack
  scripts/                 # Lifecycle hooks (any executable: .sh, .py, .zsh, etc.)
    isolate_start           # Create isolated workspace for a task
    isolate_end             # Merge results / cleanup workspace
    execute                 # Run one task (for shell-based executors)
    verify                  # Global verification command
    resolve                 # Dependency resolution (for script-based resolution)
    preflight               # Prerequisite checks (run at session start)
  templates/               # Templates for intake items, plans, status files
    intake.md
    plan.md
    status.md
```

**Script naming and execution:** Scripts in `scripts/` have no required file extension. They can be shell scripts (.sh, .zsh), Python scripts (.py), compiled binaries, or anything else that is executable. The orchestrator invokes them via `subprocess` using whatever interpreter the file's shebang line (`#!/usr/bin/env python3`, `#!/bin/bash`, etc.) specifies, or directly if the file is a compiled binary. Pack authors must ensure scripts have the executable bit set (`chmod +x`). The `pack.yaml` references scripts by their relative path (e.g., `scripts/isolate_start.py`, `scripts/verify.zsh`) -- the orchestrator does not assume any extension.

### 4.2 pack.yaml Schema

```yaml
name: string                    # Pack identifier (kebab-case)
description: string             # Human-readable description
version: string                 # Semver

phases:
  planning:
    enabled: boolean            # Default: false
    executor: agent             # "agent" only (planning is always LLM-driven)
    model: string               # Model name (e.g., "opus", "sonnet")
    prompt: path                # Relative path to prompt file
    max_instances: integer      # Max parallel planners (default: 1)

  resolution:
    enabled: boolean            # Default: true
    executor: string            # "agent" | "script" | "passthrough"
    model: string               # Model name (for agent executor)
    prompt: path                # Relative path to prompt file (for agent executor)
    script: path                # Relative path to script (for script executor)

  execution:
    enabled: true               # Always true
    executor: string            # "agent" | "shell"
    model: string               # Model name (for agent executor)
    prompt: path                # Relative path to prompt file (for agent executor)
    command: path               # Relative path to script (for shell executor)
    max_workers: integer        # Default: 2

  verification:
    enabled: boolean            # Default: false
    command: string             # Shell command to run (can reference session vars)
    interval: integer           # Run every N completed tasks (default: 4)

auto_fix:
  enabled: boolean              # Default: false
  max_attempts: integer         # Default: 2
  model: string                 # Model name for fixer agent
  prompt: path                  # Relative path to fixer prompt

isolation:
  type: string                  # "git-worktree" | "temp-directory" | "none"
  setup: path                   # Relative path to isolation setup script (any executable, e.g., "scripts/isolate_start.py")
  teardown: path                # Relative path to isolation teardown script (any executable)

prerequisites:                  # List of checks run at session start
  - name: string                # Human-readable name (e.g., "Claude CLI")
    check: string               # Shell command (exit 0 = pass, non-zero = fail)

timeouts:
  task_idle: integer              # Seconds with no stdout/stderr before killing a task (default: 300)
  task_max: integer               # Max seconds a single task can run before being killed (default: 0 = no limit)
  session_max: integer            # Max seconds for the entire session before aborting (default: 14400 = 4 hours)

status:
  progress_format: string       # Regex for progress markers (default: "##PROGRESS##")
  sidecar_format: string        # "key-value" (default) | "json" | "yaml"
```

### 4.3 Lifecycle Hook Contracts

All hooks are called by the orchestrator. The pack never runs itself.

**`isolate_start` (isolation setup)**
- **Called by:** Orchestrator, before dispatching a task to a worker slot.
- **Arguments:** `$1` = slot number, `$2` = task ID, `$3` = session workspace path
- **Stdout:** Must print the workspace path for the task (e.g., the worktree path, the temp directory path).
- **Exit code:** 0 = success, non-zero = isolation setup failed (task returns to ready queue).
- **Example (git-worktree):** Creates `.worktrees/worker_<slot>` with a new branch, prints the worktree path.
- **Example (temp-directory):** Creates a temp dir under the session workspace, prints the path.

**`isolate_end` (isolation teardown)**
- **Called by:** Orchestrator, after task completion (success or failure).
- **Arguments:** `$1` = slot number, `$2` = task ID, `$3` = workspace path (from isolate_start), `$4` = status ("done" | "blocked")
- **Behavior on "done":** Merge results (e.g., squash merge the worktree branch). Print merge commit SHA if applicable.
- **Behavior on "blocked":** Cleanup without merging. Preserve logs/artifacts for debugging.
- **Exit code:** 0 = success, non-zero = merge/cleanup failed (escalate to human).

**`execute` (task executor, for shell/script-based executors)**
- **Called by:** Orchestrator, within the isolated workspace.
- **Arguments:** `$1` = task file path, `$2` = workspace path
- **Working directory:** Set to the workspace path.
- **Stdout/stderr:** Captured to log file by orchestrator.
- **Progress:** Must emit progress lines to stdout. Two levels are supported:
  - **Phase progress (required):** `##PROGRESS## <task_id> | Phase: <name> | <N>/<total>` -- announces the current phase and position in the phase sequence.
  - **Detail progress (optional):** `##PROGRESS## <task_id> | Detail: <message>` -- freeform status text from the executor, surfaced directly on the worker card. Examples: `Detail: Processing chunk 3/9`, `Detail: Running test suite (47 passed)`, `Detail: Downloading 128MB/512MB`. The orchestrator does not parse or validate detail content -- it passes it through as-is to the UI. Executors can emit detail lines as often as they want; only the latest one is displayed.
- **Status:** Must write a status sidecar file (path: same dir as task file, `.status` extension).
- **Exit code:** 0 = success, non-zero = failure.

**`verify` (global verification)**
- **Called by:** Orchestrator, in the main workspace (not isolated).
- **Arguments:** `$1` = session workspace path
- **Exit code:** 0 = all tests pass, non-zero = verification failed.
- **Stdout/stderr:** Captured to verification log file.

**`preflight` (prerequisite checks)**
- **Called by:** Orchestrator, at session startup before any dispatch.
- **Arguments:** none
- **Behavior:** Runs each prerequisite check. Prints pass/fail per check.
- **Exit code:** 0 = all prerequisites met, non-zero = at least one failed (session cannot start).

**Executable-bit preflight (orchestrator-enforced, before pack preflight):**

Before invoking the pack's own `preflight` hook, the orchestrator scans the pack's `scripts/` directory and checks every file for the executable bit. If any script lacks it, the orchestrator halts immediately and prints a diagnostic listing each non-executable file with the exact fix command:

```
ERROR: Pack 'claude-code' has non-executable scripts:

  scripts/isolate_start.py  -- Run: chmod +x ~/.switchyard/packs/claude-code/scripts/isolate_start.py
  scripts/verify             -- Run: chmod +x ~/.switchyard/packs/claude-code/scripts/verify

Fix the permissions above and re-run.
```

This check is not delegable to the pack -- it runs unconditionally for every pack at every session start. The pack's own `preflight` hook (which validates external prerequisites like CLI availability) only runs after the executable-bit check passes. This prevents confusing "permission denied" errors deep in the pipeline when the real problem is a missing `chmod +x` after creating or copying scripts.

In the UI Setup View, this appears as the first item in the preflight checklist (e.g., "Pack scripts executable: PASS/FAIL") before any pack-defined prerequisite checks.

**Execution mechanism:** The orchestrator invokes all hook scripts via `subprocess.run()` (or `subprocess.Popen()` for long-running hooks like execute). It does not assume a shell interpreter -- scripts must either have a shebang line or be natively executable. The orchestrator passes arguments positionally and captures stdout/stderr. It never wraps calls in `bash -c` or `sh -c` unless the pack.yaml explicitly specifies an interpreter override.

### 4.4 Status Sidecar Format (default: key-value)

```
STATUS: done | blocked
COMMITS: <comma-separated SHAs or "none">
TESTS_RAN: targeted | full | none
TEST_RESULT: pass | fail | skip
BLOCKED_REASON: <one-line reason, only if STATUS: blocked>
NOTES: <freeform, optional>
```

### 4.5 Pack Distribution

- **Built-in packs** ship with Cognitive Switchyard source.
- On first run, bootstrap copies built-in packs to `~/.switchyard/packs/`.
- If a pack already exists in the local directory, it is NOT overwritten (user may have customized).
- `--reset-pack <name>` restores a single built-in pack to factory default.
- `--reset-all-packs` restores all built-in packs.
- Orchestrator loads packs exclusively from `~/.switchyard/packs/`. No special built-in path at runtime.
- Users can add custom packs by creating new directories in `~/.switchyard/packs/`.

---

## 5. State Management

### 5.1 Storage Model

**SQLite database** (`~/.switchyard/switchyard.db`) for queryable metadata:
- Sessions (id, name, pack, config, status, created_at, completed_at)
- Tasks (id, session_id, title, status, phase, worker_slot, depends_on, anti_affinity, exec_order, created_at, started_at, completed_at)
- Worker slots (session_id, slot_number, status, current_task_id)
- Events (session_id, timestamp, event_type, task_id, message) -- for session log

**File directories** for artifacts (per session):
```
~/.switchyard/sessions/<session-id>/
  intake/          # Raw work items
  claimed/         # Items being planned
  staging/         # Plans awaiting resolution
  review/          # Plans needing human input
  ready/           # Resolved, queued for execution
  workers/
    0/             # Worker slot 0 workspace
    1/             # Worker slot 1 workspace
    ...
  done/            # Completed tasks (plan + status + log)
  blocked/         # Failed tasks
  logs/
    session.log    # Orchestrator event log
    verify.log     # Latest verification output
    workers/
      0.log        # Worker 0 log
      1.log        # Worker 1 log
  resolution.json  # Constraint graph (structured, not markdown)
```

**Post-completion trimming (successful sessions only):**

When a session completes successfully (all tasks done, no blocked), the orchestrator automatically trims the session directory down to minimal metadata. The retained structure is:

```
~/.switchyard/sessions/<session-id>/
  summary.json       # Session metadata: pack, config, timing, task count, final statuses
  resolution.json    # Constraint graph (useful for post-hoc analysis)
  logs/
    session.log      # Orchestrator event log (compact record of what happened)
```

Everything else is deleted: `intake/`, `claimed/`, `staging/`, `ready/`, `workers/`, `done/`, `blocked/`, worker logs, verification logs. The work product has already been delivered (merged, exported, etc.) by the pack's `isolate_end` hook, so these artifacts serve no further purpose.

**Failed/aborted sessions are not trimmed.** Their full directory structure is preserved for debugging and manual inspection. The user can purge them manually from the History View, or they expire via the retention policy.

The `summary.json` file is written as the last step of session completion, before any trimming occurs. It contains everything the History View needs to render the session card (name, pack, timestamps, per-task final status, total duration, worker utilization stats). This means the History View never needs to scan the filesystem -- it reads from SQLite for the list and `summary.json` for detail drill-down.

### 5.2 File-as-State Mapping

Task status is determined by which directory contains its plan file:

| Directory | Status | Meaning |
|-----------|--------|---------|
| `intake/` | intake | Raw, unclaimed |
| `claimed/` | planning | Planner is working on it |
| `staging/` | staged | Plan complete, awaiting resolution |
| `review/` | review | Needs human input |
| `ready/` | ready | Resolved, queued for dispatch |
| `workers/<N>/` | active | Executing in worker slot N |
| `done/` | done | Completed successfully |
| `blocked/` | blocked | Failed, needs escalation |

The SQLite database mirrors this state for fast querying by the API/UI. The file system is the source of truth; the database is a read-optimized projection.

### 5.3 Constraint Graph Format

Resolution output is stored as JSON (not markdown) for reliable parsing:

```json
{
  "resolved_at": "2026-03-05T14:16:45Z",
  "tasks": [
    {
      "task_id": "038",
      "depends_on": [],
      "anti_affinity": [],
      "exec_order": 1
    },
    {
      "task_id": "040",
      "depends_on": [],
      "anti_affinity": ["041", "042", "044"],
      "exec_order": 1
    }
  ],
  "groups": [
    {
      "name": "schema-editor",
      "type": "anti_affinity",
      "members": ["040", "041", "042", "044"],
      "shared_resources": ["src/frontend/assets/js/schema-editor.js"]
    }
  ],
  "conflicts": [],
  "notes": "Maximum parallelism: 4 workers"
}
```

---

## 6. Web UI

### 6.1 Technology Stack

- **Backend:** Python FastAPI + uvicorn (uv-managed via a PEP 723 header)
- **Frontend:** Single-file embedded React 18 SPA (CDN-loaded, no npm/node_modules)
- **CDN dependencies:** React 18, ReactDOM 18, Babel Standalone, Tailwind CSS, Lucide Icons, React Flow v11 (all UMD from unpkg/jsdelivr)
- **Real-time:** WebSocket for live state pushes
- **Port:** Auto-scan from preferred default (e.g., 8100), never hardcoded

### 6.2 Aesthetic Direction: Industrial Command Center

**Tone:** Dark-theme operational dashboard. Bloomberg terminal meets modern DevOps monitoring. Authoritative, dense, functional.

**Design principles (from frontend-design skill):**

- **Typography:** Monospace or semi-monospace font for data display (e.g., JetBrains Mono, IBM Plex Mono). A distinctive display font for section headers (e.g., Instrument Sans, DM Sans, or similar). Never Inter, Roboto, Arial, or system defaults. Font pairing must be intentional and memorable.
- **Color:** Deep charcoal or navy background (not pure black). High-contrast accent colors for status: green for done/healthy, amber for active/in-progress, red for blocked/error, blue for ready/queued, dim gray for idle. Dominant dark ground with sharp status accents. No pastel, no purple gradients.
- **Motion:** Staggered reveal on page load. Smooth transitions on status changes (color fade, not jarring swap). Log lines animate in with a subtle slide. Progress bars use CSS transitions. Worker cards pulse subtly when active.
- **Spatial composition:** Dense grid layout with clear information hierarchy. Worker cards as instrument panels. Pipeline flow as a horizontal strip with animated state transitions. Generous use of subtle borders and elevation (box-shadow) to separate zones.
- **Background and texture:** Subtle noise or scan-line texture on the dark background for depth. Faint grid pattern behind the DAG view. Status colors glow slightly against the dark ground (box-shadow with color).

**The memorable element:** The live pipeline flow strip where task counts animate between stages, combined with the worker cards showing real-time log tails scrolling past like terminal output. It should feel like watching a factory floor from a control room.

### 6.3 UI Implementation Specification

This section provides exact values for the implementing agent. Do not deviate from these specifications. Do not substitute fonts, colors, or layout values with "close enough" alternatives.

#### 6.3.0 Design Tokens (CSS Custom Properties)

All visual constants must be defined as CSS custom properties on `:root`. Every component references these tokens -- never hardcode values.

```css
:root {
  /* === Background === */
  --bg-base: #0f1117;           /* Main page background - very dark blue-gray */
  --bg-surface: #161922;        /* Card/panel backgrounds */
  --bg-surface-raised: #1c1f2e; /* Elevated surfaces (modals, dropdowns) */
  --bg-surface-hover: #232738;  /* Hover state on interactive surfaces */
  --bg-input: #0c0e14;          /* Input field backgrounds */
  --bg-log: #0a0c10;            /* Log viewer background (darkest) */

  /* === Text === */
  --text-primary: #e8eaed;      /* Primary text - slightly warm white */
  --text-secondary: #8b8fa3;    /* Secondary/dimmed text */
  --text-muted: #4a4e63;        /* Very dimmed text (idle labels, timestamps) */
  --text-inverse: #0f1117;      /* Text on bright backgrounds */

  /* === Status Colors === */
  --status-done: #34d399;       /* Green - completed/healthy */
  --status-active: #f59e0b;     /* Amber - in progress */
  --status-ready: #3b82f6;      /* Blue - queued/ready */
  --status-blocked: #ef4444;    /* Red - error/blocked */
  --status-staged: #a78bfa;     /* Purple - staged/planning */
  --status-idle: #374151;       /* Dark gray - idle/inactive */
  --status-review: #f97316;     /* Orange - needs human review */

  /* === Status Glows (for box-shadow) === */
  --glow-done: rgba(52, 211, 153, 0.15);
  --glow-active: rgba(245, 158, 11, 0.15);
  --glow-blocked: rgba(239, 68, 68, 0.25);
  --glow-ready: rgba(59, 130, 246, 0.1);

  /* === Borders === */
  --border-subtle: #1e2231;     /* Default card/panel borders */
  --border-medium: #2a2f42;     /* Stronger separation */
  --border-focus: #3b82f6;      /* Focus ring color */

  /* === Typography === */
  --font-display: 'Space Grotesk', 'DM Sans', sans-serif;    /* Headers, labels */
  --font-mono: 'JetBrains Mono', 'IBM Plex Mono', monospace; /* Data, logs, IDs */
  --font-body: 'DM Sans', 'Space Grotesk', sans-serif;       /* Body text */

  /* === Font Sizes === */
  --text-xs: 0.6875rem;    /* 11px - timestamps, fine print */
  --text-sm: 0.75rem;      /* 12px - secondary labels */
  --text-base: 0.8125rem;  /* 13px - body text (dense UI) */
  --text-md: 0.875rem;     /* 14px - primary labels */
  --text-lg: 1rem;         /* 16px - section headers */
  --text-xl: 1.25rem;      /* 20px - page headers */
  --text-2xl: 1.5rem;      /* 24px - view titles */

  /* === Spacing === */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;

  /* === Border Radius === */
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 8px;
  --radius-xl: 12px;

  /* === Transitions === */
  --transition-fast: 150ms ease;
  --transition-base: 250ms ease;
  --transition-slow: 400ms ease;

  /* === Z-index layers === */
  --z-base: 0;
  --z-cards: 10;
  --z-sticky: 20;
  --z-overlay: 30;
  --z-modal: 40;
  --z-tooltip: 50;

  /* === Layout === */
  --topbar-height: 48px;
  --pipeline-strip-height: 44px;
  --worker-card-min-height: 220px;
  --log-tail-lines: 5;          /* Number of visible lines in worker card log tail */
  --sidebar-width: 280px;       /* For views that use sidebar layout */
}
```

#### 6.3.0.1 Google Fonts Import

Load these fonts via the Google Fonts CDN in the HTML `<head>`. Both are required.

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
```

#### 6.3.0.2 Background Texture

Apply a subtle noise texture to the page background using CSS. This creates depth without an image file:

```css
body {
  background-color: var(--bg-base);
  background-image:
    radial-gradient(ellipse at 20% 50%, rgba(59, 130, 246, 0.03) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 20%, rgba(139, 92, 246, 0.02) 0%, transparent 40%);
}

/* Subtle noise via SVG data URI (no external file) */
body::before {
  content: '';
  position: fixed;
  inset: 0;
  opacity: 0.025;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  pointer-events: none;
  z-index: -1;
}
```

#### 6.3.0.3 Animation Keyframes

Define these globally. Components reference them by name.

```css
/* Pulsing glow for active worker cards */
@keyframes pulse-active {
  0%, 100% { box-shadow: 0 0 0 1px var(--status-active), 0 0 8px var(--glow-active); }
  50% { box-shadow: 0 0 0 1px var(--status-active), 0 0 16px var(--glow-active); }
}

/* Red pulsing border for blocked/problem states */
@keyframes pulse-error {
  0%, 100% { box-shadow: 0 0 0 2px var(--status-blocked), 0 0 12px var(--glow-blocked); }
  50% { box-shadow: 0 0 0 2px var(--status-blocked), 0 0 24px var(--glow-blocked); }
}

/* Subtle breathing for idle elements */
@keyframes breathe {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 0.6; }
}

/* Log line slide-in */
@keyframes log-slide-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Count badge number change */
@keyframes count-bump {
  0% { transform: scale(1); }
  50% { transform: scale(1.15); }
  100% { transform: scale(1); }
}

/* Staggered fade-in for page load */
@keyframes fade-in-up {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Progress bar segment fill */
@keyframes segment-fill {
  from { width: 0%; }
  to { width: 100%; }
}
```

#### 6.3.0.4 Component Specifications

**Top Bar:**
- Height: `var(--topbar-height)` (48px)
- Background: `var(--bg-surface)` with 1px bottom border `var(--border-subtle)`
- Position: fixed, top: 0, full width, z-index: `var(--z-sticky)`
- Logo text: "COGNITIVE SWITCHYARD" in `var(--font-display)`, weight 700, size `var(--text-md)`, letter-spacing: 0.08em, uppercase, color `var(--text-primary)`
- Session info: `var(--font-mono)`, size `var(--text-sm)`, color `var(--text-secondary)`
- Control buttons: 28px height, `var(--radius-sm)` corners, `var(--font-body)` weight 500
  - Pause: border 1px `var(--status-active)`, text `var(--status-active)`, bg transparent
  - Resume: bg `var(--status-done)`, text `var(--text-inverse)`
  - Abort: border 1px `var(--status-blocked)`, text `var(--status-blocked)`, bg transparent. On hover: bg `var(--status-blocked)`, text white

**Pipeline Flow Strip:**
- Height: `var(--pipeline-strip-height)` (44px)
- Background: `var(--bg-surface)`
- Bottom border: 1px `var(--border-subtle)`
- Layout: flexbox, row, center-aligned, gap `var(--space-2)`
- Each stage badge:
  - Font: `var(--font-mono)`, size `var(--text-sm)`, weight 500
  - Padding: 2px 10px
  - Border-radius: `var(--radius-sm)`
  - Background: stage-specific color at 15% opacity (e.g., `rgba(52, 211, 153, 0.15)` for done)
  - Text color: stage-specific status color
  - Separator arrows: `var(--text-muted)` color, `var(--font-body)` size `var(--text-xs)`
- Blocked badge (when count > 0): `animation: pulse-error 2s ease-in-out infinite`
- Count changes: `animation: count-bump 300ms ease`
- DAG icon: Lucide `GitBranch` icon, 18px, `var(--text-secondary)`, hover `var(--text-primary)`

**Worker Card:**
- Min-height: `var(--worker-card-min-height)` (220px)
- Background: `var(--bg-surface)`
- Border: 1px `var(--border-subtle)`
- Border-radius: `var(--radius-lg)`
- Padding: `var(--space-4)`
- Grid: 2 columns for 2-4 workers, 3 columns for 5-6. Gap: `var(--space-4)`
- Card header:
  - Slot label: `var(--font-mono)`, `var(--text-xs)`, `var(--text-muted)`, uppercase, letter-spacing 0.05em
  - Task ID: `var(--font-mono)`, `var(--text-md)`, `var(--text-primary)`, weight 600
  - Task title: `var(--font-body)`, `var(--text-sm)`, `var(--text-secondary)`, truncate with ellipsis, max 1 line
  - Status badge: inline, padding 1px 6px, `var(--radius-sm)`, font `var(--text-xs)` weight 600 uppercase
- Progress bar:
  - Height: 6px
  - Background: `var(--bg-input)`
  - Border-radius: 3px
  - Segments: divided into N equal parts (N = total phases). Completed segments filled with `var(--status-done)`. Current segment has animated fill using `var(--status-active)`. Future segments empty.
  - Segment dividers: 1px `var(--bg-surface)` gap
- Elapsed time: `var(--font-mono)`, `var(--text-xs)`, `var(--text-muted)`
- Log tail:
  - Background: `var(--bg-log)`
  - Border-radius: `var(--radius-sm)`
  - Padding: `var(--space-2)` `var(--space-3)`
  - Font: `var(--font-mono)`, `var(--text-xs)`, line-height 1.5
  - Color: `var(--text-secondary)`
  - Max height: calc(var(--log-tail-lines) * 1.5 * var(--text-xs) * 16) -- approximately 5 lines
  - Overflow: hidden (no scrollbar on card view)
  - New lines: `animation: log-slide-in 200ms ease`
- States:
  - Idle: opacity 0.5, log tail shows "Waiting for task..." in `var(--text-muted)`, `animation: breathe 4s ease-in-out infinite`
  - Active: full opacity, `animation: pulse-active 3s ease-in-out infinite`
  - Problem: `animation: pulse-error 1.5s ease-in-out infinite`, additionally a small warning icon (Lucide `AlertTriangle`) appears in the card header, 14px, `var(--status-blocked)`
- Click: `cursor: pointer`, entire card is clickable. Hover: `background: var(--bg-surface-hover)`, `transition: var(--transition-fast)`

**Task Feed Row:**
- Height: 36px
- Border-bottom: 1px `var(--border-subtle)`
- Padding: 0 `var(--space-4)`
- Layout: flexbox, row, center-aligned
- Task ID: `var(--font-mono)`, `var(--text-sm)`, `var(--text-primary)`, width 48px
- Title: `var(--font-body)`, `var(--text-sm)`, `var(--text-secondary)`, flex 1, truncate
- Status badge: same spec as worker card
- Constraint icons: Lucide `Link` for deps (12px), Lucide `Shield` for anti-affinity (12px), `var(--text-muted)`, tooltip on hover showing constraint details
- Time: `var(--font-mono)`, `var(--text-xs)`, `var(--text-muted)`, width 60px, right-aligned
- Blocked row: background `rgba(239, 68, 68, 0.08)`, left border 3px solid `var(--status-blocked)`
- Active row: left border 3px solid `var(--status-active)`
- Hover: `background: var(--bg-surface-hover)`, `cursor: pointer`

**Task Detail View (overlay):**
- Background: `var(--bg-base)` (full page replacement, not modal)
- Top: back button (Lucide `ArrowLeft` + "Back to Monitor"), `var(--font-body)`, `var(--text-sm)`, `var(--text-secondary)`, hover `var(--text-primary)`
- Left panel (40% width):
  - Padding: `var(--space-6)`
  - Task ID: `var(--font-mono)`, `var(--text-xl)`, `var(--text-primary)`
  - Status: large badge, padding 4px 12px, `var(--text-sm)` weight 600
  - Metadata labels: `var(--font-body)`, `var(--text-xs)`, `var(--text-muted)`, uppercase, letter-spacing 0.05em
  - Metadata values: `var(--font-mono)`, `var(--text-sm)`, `var(--text-primary)`
  - Constraint section: DEPENDS_ON listed with status dot (green/gray/amber) + task ID. ANTI_AFFINITY listed with shield icon.
  - Plan content: rendered markdown, `var(--font-body)`, `var(--text-base)`, headings in `var(--font-display)`
  - Scrollable independently
- Right panel (60% width):
  - Background: `var(--bg-log)`
  - Full height (minus topbar)
  - Log content: `var(--font-mono)`, `var(--text-xs)`, line-height 1.6, `var(--text-secondary)`
  - Progress lines (`##PROGRESS##`): background `rgba(245, 158, 11, 0.1)`, left border 2px `var(--status-active)`, full width
  - Error lines (stderr, "ERROR", "FAIL"): color `var(--status-blocked)`
  - Search bar: top of panel, `var(--bg-input)`, border 1px `var(--border-subtle)`, `var(--font-mono)` `var(--text-sm)`, Lucide `Search` icon
  - Auto-scroll: default on. When user scrolls up, auto-scroll pauses. "Jump to latest" button appears (fixed bottom-right of log panel), bg `var(--status-active)`, text `var(--text-inverse)`, `var(--radius-md)`

**DAG View:**
- Full viewport below topbar
- Background: `var(--bg-base)` with faint grid pattern:
  ```css
  background-image:
    linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px);
  background-size: 40px 40px;
  ```
- React Flow config:
  - `fitView` on load
  - Background: transparent (our CSS grid handles it)
  - MiniMap: enabled, bottom-right, bg `var(--bg-surface)`, node colors match status
  - Controls: enabled (zoom buttons), styled to match dark theme
- Node styling (React Flow custom node):
  - Width: 180px, min-height: 60px
  - Background: `var(--bg-surface)`
  - Border: 2px solid, color = status color
  - Border-radius: `var(--radius-lg)`
  - Padding: `var(--space-3)`
  - Task ID: `var(--font-mono)`, `var(--text-md)`, weight 600, status color
  - Title: `var(--font-body)`, `var(--text-xs)`, `var(--text-secondary)`, max 2 lines
  - Status badge: bottom of node, same spec as elsewhere
  - Active nodes: `animation: pulse-active 3s ease-in-out infinite`
  - Blocked nodes: `animation: pulse-error 1.5s ease-in-out infinite`
- Edge styling:
  - DEPENDS_ON: `stroke: var(--text-muted)`, strokeWidth 2, animated (React Flow `animated` prop), markerEnd arrow
  - ANTI_AFFINITY: `stroke: var(--status-staged)`, strokeWidth 1, strokeDasharray "6 4", no marker
- Group backgrounds (anti-affinity clusters):
  - Implemented as React Flow group nodes
  - Background: status color at 5% opacity
  - Border: 1px dashed, status color at 20% opacity
  - Label: `var(--font-body)`, `var(--text-xs)`, `var(--text-muted)`, top-left of group
- Back button: same as Task Detail View

**Setup View:**
- Layout: centered, max-width 640px, margin auto
- Card: `var(--bg-surface)`, border 1px `var(--border-subtle)`, `var(--radius-xl)`, padding `var(--space-8)`
- Title: "New Session" in `var(--font-display)`, `var(--text-2xl)`, `var(--text-primary)`, weight 700
- Form labels: `var(--font-body)`, `var(--text-xs)`, `var(--text-muted)`, uppercase, letter-spacing 0.05em, margin-bottom `var(--space-1)`
- Inputs: `var(--bg-input)`, border 1px `var(--border-subtle)`, `var(--radius-md)`, padding `var(--space-2)` `var(--space-3)`, `var(--font-mono)` `var(--text-base)`, `var(--text-primary)`. Focus: border-color `var(--border-focus)`, outline none
- Pack selector: styled select or custom dropdown. Pack name in `var(--font-display)` weight 600, description below in `var(--text-xs)` `var(--text-secondary)`
- Preflight checks: list with Lucide `CheckCircle` (green) or `XCircle` (red) icons, 16px. Check name in `var(--font-body)` `var(--text-sm)`. Failed checks: text `var(--status-blocked)`
- Intake file list: `var(--bg-log)` background, `var(--radius-md)`, max-height 200px, scrollable. Each file: `var(--font-mono)` `var(--text-sm)`, Lucide `FileText` icon 14px
- Start button: full width, height 44px, bg `var(--status-done)`, text `var(--text-inverse)`, `var(--font-display)` weight 700, `var(--text-md)`, `var(--radius-md)`, uppercase, letter-spacing 0.05em. Disabled state: opacity 0.3, cursor not-allowed. Hover: brightness 1.1
- Advanced section: collapsible, toggle link in `var(--text-xs)` `var(--text-secondary)`, Lucide `ChevronDown`/`ChevronUp`

**History View:**
- Layout: full width, padding `var(--space-6)` horizontal
- Title: "Session History" in `var(--font-display)`, `var(--text-xl)`, weight 600
- Session cards: `var(--bg-surface)`, border 1px `var(--border-subtle)`, `var(--radius-lg)`, padding `var(--space-4)`, margin-bottom `var(--space-3)`
- Session name: `var(--font-display)`, `var(--text-md)`, weight 600
- Pack badge: inline, `var(--font-mono)`, `var(--text-xs)`, bg `var(--bg-surface-raised)`, padding 1px 6px, `var(--radius-sm)`
- Stats: `var(--font-mono)`, `var(--text-sm)`, `var(--text-secondary)`. Green number for completed, red for blocked.
- Date/duration: `var(--font-mono)`, `var(--text-xs)`, `var(--text-muted)`
- Hover: `background: var(--bg-surface-hover)`, cursor pointer
- Empty state: centered text "No sessions yet" in `var(--text-muted)`, Lucide `Inbox` icon 32px above

#### 6.3.0.5 Page Load Animation Sequence

When the Monitor View loads (or on initial page load), apply staggered `animation: fade-in-up 400ms ease forwards` with `opacity: 0` initial state:

1. Top bar: delay 0ms
2. Pipeline strip: delay 80ms
3. Worker cards: delay 160ms, stagger 60ms per card (card 0 at 160ms, card 1 at 220ms, etc.)
4. Task feed: delay 320ms

This creates a cascading reveal from top to bottom.

### 6.3.1 Views (Functional Specification)

#### 6.3.1.1 Main Monitor View

The primary view. Shown during active sessions.

**Top bar (fixed):**
- Session name, pack type badge, elapsed time (live counter)
- Worker utilization: "3/4 active"
- Controls: Pause, Resume, Abort (with confirmation)

**Zone 1: Pipeline flow strip** (~50px height, full width)
- Horizontal flow: `Intake(3) -> Planning(1) -> Staged(0) -> Ready(5) -> Active(2) -> Done(12) | Blocked(0)`
- Each stage is a rounded badge with count. Count updates animate (number ticks up/down).
- Blocked count uses red background and pulses if > 0.
- Small DAG icon at right end of strip. Click opens full-page DAG view.

**Zone 2: Worker cards** (main content area)
- Grid of cards, one per configured worker slot. 2-across for 2-4 workers, 3-across for 5-6.
- Each card contains:
  - **Header:** Slot number, task ID + short title (truncated), status badge
  - **Progress:** Segmented progress bar showing phases (segments defined by pack). Current phase highlighted/animated.
  - **Detail line:** Single line of freeform progress text from the executor, displayed below the progress bar in `var(--font-mono)` at `var(--text-secondary)` color. Shows the latest `Detail:` progress message (e.g., "Processing chunk 3/9"). Hidden when no detail has been emitted. Updates in-place (no animation needed -- just text swap). This gives at-a-glance insight into what the executor is actually doing without reading logs.
  - **Elapsed time** on current task.
  - **Live tail:** 4-5 lines of latest log output, monospace, auto-scrolling. New lines slide in from bottom. Dimmed when idle.
- **Card states:**
  - Idle: Dimmed, no content beyond "idle" label
  - Active: Normal brightness, log tail active, progress bar animating
  - Problem (no progress for configurable threshold): Red border, pulsing glow. The card itself communicates the issue -- no toast/banner needed.
- **Click** anywhere on an active card to drill into full-screen Task Detail View.

**Zone 3: Task feed** (below worker cards, scrollable)
- Compact list of all tasks in session, sorted: blocked (top, red), active, ready, done (bottom, green).
- Each row: task ID, title (truncated), status badge, constraint icons (chain icon for deps, shield icon for anti-affinity), elapsed/completed time.
- Click a row to drill into Task Detail View.
- Blocked tasks show with red background highlight and are always pinned to top.

#### 6.3.1.2 Task Detail View

Full-screen overlay (or page navigation) triggered by clicking a worker card or task feed row.

**Layout: two-column**

**Left column (40%):**
- Task metadata: ID, title, status, worker slot, elapsed time
- Constraints: DEPENDS_ON (with status of each dependency), ANTI_AFFINITY list
- Status sidecar: rendered key-value pairs (STATUS, COMMITS, TEST_RESULT, NOTES)
- Fixer history (if applicable): attempt count, each attempt's outcome, diff summary
- Plan content: rendered markdown of the full plan file

**Right column (60%):**
- Full streaming log output. Monospace, dark background, auto-scrolling.
- Phase markers highlighted (different background color for `##PROGRESS##` lines).
- Search/filter bar at top of log panel.
- Log pauses auto-scroll when user scrolls up; "Jump to bottom" button appears.

**Back button** returns to Main Monitor View.

#### 6.3.1.3 DAG View

Full-page view triggered by clicking the DAG icon in the pipeline strip.

**Technology:** React Flow v11 (UMD via CDN).

**Layout:**
- Interactive node graph filling the viewport.
- Pan, zoom, and drag enabled.

**Nodes:**
- One node per task. Rounded rectangle.
- Node content: Task ID (large), short title (small), status badge.
- Node color by status: gray (ready), blue (active/animated border), green (done), red (blocked), yellow (staged).
- Node border pulses for active tasks.

**Edges:**
- DEPENDS_ON: Solid directed arrows (A -> B means B depends on A).
- ANTI_AFFINITY: Dashed undirected lines (A -- B means they cannot run concurrently).

**Anti-affinity groups:** Tasks sharing anti-affinity are visually clustered. Group background with subtle tinted region and label (e.g., "schema-editor group").

**Interaction:**
- Click a node to see a tooltip with task summary, constraints, current phase.
- Double-click a node to navigate to Task Detail View.

**Back button** returns to Main Monitor View.

#### 6.3.1.4 Setup View

Shown when no session is active, or when creating a new session.

**Layout: centered card**

- **Pack selector:** Dropdown listing available packs from `~/.switchyard/packs/`. Shows pack name and description.
- **Session name:** Text input with auto-generated default (e.g., "coding-run-2026-03-07").
- **Planner count:** Numeric stepper (1 to pack's `max_instances`). Only shown if pack has planning enabled. Since planners operate on independent intake items with no shared state, there are zero conflicts -- parallelism is limited only by machine resources and API rate limits.
- **Worker count:** Numeric stepper (1 to pack's `max_workers`).
- **Verification interval:** Numeric stepper (only shown if pack has verification enabled).
- **Intake directory:** Shows the session's intake path. Instructions: "Drop .md files here to add tasks." Includes an "Open Folder" button (small, inline, icon-only is fine -- e.g., a folder icon from Lucide) that opens the intake directory in the OS file manager (Finder on macOS, Files on Linux). Backend endpoint: `GET /api/session/{id}/open-intake` calls `subprocess.Popen()` with the platform-appropriate command (`open` on macOS, `xdg-open` on Linux). This is a fire-and-forget call -- no response body needed, just 204.
- **Preflight checks:** After pack selection, runs a two-stage preflight. Stage 1 (orchestrator-enforced): scans all pack scripts for executable bit -- if any lack it, shows red X with the exact `chmod +x` command per file. Stage 2 (pack-defined): runs the pack's own `preflight` hook to validate external prerequisites (CLI availability, auth status, etc.). Shows a checklist with green check / red X per item. Cannot start if any check in either stage fails.
- **Intake file list:** Live-updating list of files detected in the intake directory. Shows filename, size, detected time. Each file row has a small "reveal" icon button (e.g., Lucide `external-link` or `folder-open`) that opens the OS file manager with that specific file selected (`open -R <path>` on macOS, `xdg-open <parent-dir>` on Linux). This lets the user jump straight to editing a specific intake file. After session starts, this list becomes read-only with a "Session locked -- intake closed" banner. Any new files detected post-start appear grayed out with strikethrough, labeled "Not in session." The reveal buttons are hidden in locked state.
- **Start button:** Launches the pipeline. Disabled until at least one intake item exists and all preflight checks pass. Clicking Start snapshots the current intake as the session's fixed task set. No additional tasks can be added to a running session.

**Session config overrides (expandable "Advanced" section):**
- Poll interval
- Auto-fix enabled/disabled
- Auto-fix max attempts
- Task idle timeout (seconds) -- kill a task if no stdout/stderr for this long. Default from pack.yaml (typically 300s).
- Task max timeout (seconds) -- hard cap on any single task's wall-clock time. 0 = no limit. Default from pack.yaml.
- Session max timeout (seconds) -- hard cap on total session wall-clock time. Default from pack.yaml (typically 14400s / 4 hours).
- Custom environment variables (key-value pairs passed to executor)

#### 6.3.1.5 History View

Accessible from top navigation at all times.

- List of past sessions: name, pack, date, duration, tasks completed/blocked.
- Click a session to see its final state: dashboard summary, release notes (if generated), task list with final statuses.
- Past session data is read-only (no editing task statuses, rerunning, etc.).
- **Purge controls:** Each session row has a small trash icon button (requires confirmation modal: "Delete session <name> and all its artifacts? This cannot be undone."). Also a "Purge All" button at the top of the list with a confirmation modal showing the count of sessions to be deleted. Purge deletes both the SQLite rows and the session's filesystem directory (`~/.switchyard/sessions/<id>/`).
- **Retention indicator:** Below the session list, a muted-text line showing the current retention setting (e.g., "Auto-purge: sessions older than 30 days" or "Auto-purge: disabled"). Clicking it navigates to the Settings view (or opens an inline editor if no dedicated Settings view exists yet -- see Section 6.3.1.6 below).

#### 6.3.1.6 Settings View

Accessible from a gear icon in the top bar (right side, after nav links). Minimal for now -- this is where global orchestrator preferences live, distinct from per-session config overrides in the Setup View.

- **Session retention:** Numeric input + unit dropdown (days). Default: 30 days. Set to 0 to disable auto-purge. Auto-purge runs on startup: any session (successful or failed/aborted) whose `completed_at` is older than the retention period is fully deleted (SQLite rows + session directory). Note: successful sessions are already trimmed to minimal metadata at completion time (see Section 5.1), so retention purge for those is just clearing the small summary + logs. Failed/aborted sessions retain full artifacts until either manual purge or retention expiry.
- **Default planner count:** Numeric stepper. Pre-fills the Setup View's planner count field. Overridable per session.
- **Default worker count:** Numeric stepper. Pre-fills the Setup View's worker count field. Overridable per session.
- **Default pack:** Dropdown. Pre-selects the pack in Setup View. Overridable per session.

Settings are stored in `~/.switchyard/config.yaml` (not SQLite -- survives DB resets). The file is created with defaults on first bootstrap. Example:

```yaml
retention_days: 30
default_planners: 3
default_workers: 3
default_pack: claude-code
```

### 6.4 Navigation

**Top bar** (persistent across all views):
- Left: Cognitive Switchyard logo/wordmark
- Center: Session name + status (or "No active session")
- Right: Navigation links -- Monitor, Setup, History, then a gear icon for Settings
- Monitor link is only active when a session exists

**View transitions:** Smooth fade or slide. No hard page reloads (SPA routing).

### 6.5 WebSocket Protocol

**Connection:** Client connects to `ws://localhost:<port>/ws` on page load.

**Server pushes (JSON messages):**

```json
{
  "type": "state_update",
  "data": {
    "session": { "status": "running", "elapsed": 1234 },
    "pipeline": { "intake": 3, "planning": 1, "staged": 0, "ready": 5, "active": 2, "done": 12, "blocked": 0 },
    "workers": [
      { "slot": 0, "status": "active", "task_id": "023", "task_title": "Fix auth flow", "phase": "implementing", "phase_num": 3, "phase_total": 5, "detail": "Processing chunk 3/9", "elapsed": 342 },
      { "slot": 1, "status": "active", "task_id": "025", "task_title": "Add export API", "phase": "entry-tests", "phase_num": 2, "phase_total": 5, "detail": null, "elapsed": 128 },
      { "slot": 2, "status": "idle" },
      { "slot": 3, "status": "idle" }
    ]
  }
}
```

```json
{
  "type": "log_line",
  "data": {
    "worker_slot": 0,
    "task_id": "023",
    "line": "##PROGRESS## 023 | Phase: implementing | 3/5",
    "timestamp": "2026-03-07T14:22:01Z"
  }
}
```

```json
{
  "type": "task_status_change",
  "data": {
    "task_id": "023",
    "old_status": "active",
    "new_status": "done",
    "worker_slot": 0,
    "notes": "3 commits merged"
  }
}
```

```json
{
  "type": "progress_detail",
  "data": {
    "worker_slot": 0,
    "task_id": "023",
    "detail": "Processing chunk 4/9",
    "timestamp": "2026-03-07T14:22:15Z"
  }
}
```

Sent whenever the orchestrator parses a `Detail:` progress line from an executor's stdout. Lightweight and high-frequency-safe -- the UI just swaps the text on the worker card. No history is kept; only the latest detail matters.

```json
{
  "type": "alert",
  "data": {
    "severity": "error",
    "task_id": "025",
    "worker_slot": 1,
    "message": "No progress for 5 minutes"
  }
}
```

**Client sends (JSON messages):**

```json
{ "type": "subscribe_logs", "worker_slot": 0 }
{ "type": "unsubscribe_logs", "worker_slot": 0 }
```

Log streaming is per-slot, opt-in. The main monitor view subscribes to the last ~5 lines per active worker (summary mode). The Task Detail View subscribes to full streaming for the selected worker.

### 6.6 REST API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Serve the React SPA (embedded HTML) |
| GET | `/api/packs` | List available packs |
| GET | `/api/packs/{name}` | Pack details and config schema |
| POST | `/api/sessions` | Create a new session |
| GET | `/api/sessions` | List all sessions (active + history) |
| GET | `/api/sessions/{id}` | Session details and current state |
| POST | `/api/sessions/{id}/start` | Begin orchestration |
| POST | `/api/sessions/{id}/pause` | Pause dispatch (active workers continue) |
| POST | `/api/sessions/{id}/resume` | Resume dispatch |
| POST | `/api/sessions/{id}/abort` | Abort session (kill workers, cleanup) |
| GET | `/api/sessions/{id}/tasks` | Task list with status and constraints |
| GET | `/api/sessions/{id}/tasks/{tid}` | Task detail (plan, status, log path) |
| GET | `/api/sessions/{id}/tasks/{tid}/log` | Task log content (with offset/limit for pagination) |
| GET | `/api/sessions/{id}/dag` | Constraint graph (JSON) |
| GET | `/api/sessions/{id}/dashboard` | Dashboard summary data |
| POST | `/api/sessions/{id}/tasks/{tid}/retry` | Manually retry a blocked task |
| GET | `/api/sessions/{id}/intake` | List intake directory contents (pre-start: live updating; post-start: frozen snapshot) |
| GET | `/api/sessions/{id}/open-intake` | Open intake directory in OS file manager. Fire-and-forget (`open` on macOS, `xdg-open` on Linux). Returns 204. |
| GET | `/api/sessions/{id}/reveal-file?path={relative}` | Reveal a specific file in OS file manager (`open -R` on macOS, `xdg-open` parent on Linux). Path is relative to session dir. Returns 204. Validates path is within session directory (no traversal). |
| DELETE | `/api/sessions/{id}` | Purge a completed session (SQLite rows + session directory). Returns 409 if session is active. |
| DELETE | `/api/sessions` | Purge all completed sessions. Returns count of deleted sessions. |
| GET | `/api/settings` | Current global settings (retention, defaults). |
| PUT | `/api/settings` | Update global settings. Writes to `~/.switchyard/config.yaml`. |
| WS | `/ws` | WebSocket for live updates |

---

## 7. Backend Architecture

### 7.1 Module Structure

```
switchyard/
  __init__.py
  cli.py                  # Entry point, argparse (launcher is uv-managed)
  server.py               # FastAPI app, routes, WebSocket handler
  orchestrator.py          # Main orchestration loop (runs in background thread)
  scheduler.py             # Constraint graph, eligibility checking
  worker_manager.py        # Subprocess lifecycle, slot management
  pack_loader.py           # Pack discovery, validation, hook invocation
  state.py                 # SQLite operations, state queries
  models.py                # Dataclasses: Session, Task, WorkerSlot, Constraint, Event
  watcher.py               # File system watcher (intake directory, status files)
  config.py                # Global config, paths, defaults
  html_template.py         # Embedded React SPA HTML string
```

### 7.2 Self-Bootstrapping

Following the established pattern:

1. Main script (`switchyard.py` or `switchyard/cli.py`) contains a `bootstrap()` function.
2. On first run, creates `~/.switchyard_venv`, installs dependencies (fastapi, uvicorn, aiosqlite), re-execs with venv Python.
3. On subsequent runs, venv exists, startup is instant.
4. Also copies built-in packs to `~/.switchyard/packs/` on first run.

**Dependencies:**
- fastapi
- uvicorn
- aiosqlite (async SQLite for non-blocking DB ops)
- watchfiles (efficient filesystem watching -- fallback to polling if unavailable)

### 7.3 Orchestrator Loop

The orchestrator runs in a background thread (not blocking the FastAPI event loop).

```python
# Pseudocode
while session.status == "running":
    # 1. Check for new intake items
    new_items = watcher.check_intake()
    for item in new_items:
        db.create_task(item)
        ws.broadcast(task_status_change)

    # 2. Check for completed workers
    for slot in worker_manager.slots:
        if slot.is_finished():
            result = slot.collect()
            pack.isolate_end(slot, result)
            db.update_task(result)
            ws.broadcast(task_status_change)

            # Verification check
            if should_verify():
                run_verification()

    # 3. Dispatch eligible tasks
    for slot in worker_manager.idle_slots():
        task = scheduler.next_eligible(db.ready_tasks(), db.active_tasks(), db.done_tasks())
        if task:
            workspace = pack.isolate_start(slot, task)
            slot.dispatch(task, workspace)
            db.update_task(task, status="active", worker_slot=slot.number)
            ws.broadcast(task_status_change)

    # 4. Timeout enforcement
    for slot in worker_manager.active_slots():
        idle_seconds = slot.seconds_since_last_output()
        wall_seconds = slot.elapsed()

        if config.task_idle > 0 and idle_seconds >= config.task_idle:
            slot.kill("idle timeout: no output for {idle_seconds}s")
            db.update_task(slot.task, status="blocked", reason=f"Killed: no output for {idle_seconds}s")
            pack.isolate_end(slot, "blocked")
            ws.broadcast(task_status_change)
        elif config.task_max > 0 and wall_seconds >= config.task_max:
            slot.kill("hard timeout: exceeded {wall_seconds}s")
            db.update_task(slot.task, status="blocked", reason=f"Killed: exceeded max task time {config.task_max}s")
            pack.isolate_end(slot, "blocked")
            ws.broadcast(task_status_change)
        elif config.task_idle > 0 and idle_seconds >= config.task_idle * 0.8:
            # Warning at 80% of idle threshold -- card turns to problem state
            ws.broadcast(alert, f"No output for {idle_seconds}s (timeout at {config.task_idle}s)")

    # 5. Session timeout
    if config.session_max > 0 and session.elapsed() >= config.session_max:
        for slot in worker_manager.active_slots():
            slot.kill("session timeout")
        session.status = "aborted"
        session.abort_reason = f"Session max timeout exceeded ({config.session_max}s)"
        ws.broadcast(session_aborted)

    sleep(poll_interval)
```

### 7.4 Timeout Model

Three independent timeout mechanisms protect against runaway tasks and sessions. All are configurable -- pack.yaml sets defaults, user overrides per session in the Advanced config panel.

**Task idle timeout (`task_idle`, default: 300s).** If a task's subprocess produces no stdout or stderr for this many seconds, the orchestrator kills it (SIGTERM, 5s grace, SIGKILL) and moves it to `blocked/` with a reason like "Killed: no output for 300s." This catches hung processes, deadlocked agents, and network stalls. The "no progress" warning on the worker card fires at 80% of the threshold (240s at default) so the user sees it coming. Any output -- log lines, progress markers, even whitespace -- resets the idle timer.

**Task hard timeout (`task_max`, default: 0 / disabled).** Absolute wall-clock cap on any single task. Useful for workloads with known upper bounds (e.g., "no single transcode should take more than 30 minutes"). When set to 0, tasks can run indefinitely (subject only to the idle timeout and session timeout). Killed tasks go to `blocked/` with reason "Killed: exceeded max task time."

**Session timeout (`session_max`, default: 14400s / 4 hours).** Wall-clock cap on the entire session from start to completion. When exceeded, all active workers are killed and the session is marked `aborted` (not `completed`), preserving full artifacts for debugging. This is a safety net against forgetting a running session or infinite retry loops.

**Kill sequence:** SIGTERM first, 5-second grace period for cleanup, then SIGKILL if the process is still alive. The orchestrator records the kill reason in both the task's DB row and the session event log.

**Interaction between timeouts:** Task idle and task max are independent -- whichever fires first wins. Session timeout overrides both and kills everything. A task killed by idle or hard timeout is moved to `blocked/` and the session continues (other tasks keep running, the slot is freed for the next eligible task). A session timeout stops everything.

### 7.5 WebSocket Manager

```python
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.log_subscriptions: dict[int, set[WebSocket]] = {}  # slot -> connections

    async def broadcast_state(self, state: dict):
        """Push full state update to all connected clients."""

    async def send_log_line(self, slot: int, line: str):
        """Push log line to clients subscribed to this slot."""

    async def broadcast_alert(self, alert: dict):
        """Push alert to all connected clients."""
```

---

## 8. Implementation Phases

### Phase 1: Core Orchestrator (CLI only, no UI)

**Goal:** Port the bash orchestration logic to Python. Prove the engine works with a trivial test pack.

**Deliverables:**
- `orchestrator.py`, `scheduler.py`, `worker_manager.py`, `state.py`, `models.py`, `config.py`
- A "test-echo" pack that executes `echo` commands (no LLM needed)
- Pack loader that reads pack.yaml and invokes lifecycle hooks
- SQLite state store
- CLI interface: `switchyard start --pack test-echo --session test-run`
- File-as-state directories
- Constraint enforcement (DEPENDS_ON, ANTI_AFFINITY)
- Basic session log to stdout

**Tests:** Unit tests for scheduler (eligibility logic), worker manager (slot lifecycle), state store (CRUD). Integration test: run 5 echo tasks with mixed dependencies through the full pipeline.

### Phase 2: Pack Interface + Claude Code Pack

**Goal:** Define the full pack contract and port the existing BSE coding workflow as the reference implementation.

**Deliverables:**
- pack.yaml schema validation
- Claude Code pack: prompts (planner, resolver, worker, fixer, system), lifecycle hooks (git-worktree isolation), preflight checks
- Planning phase (launch planner agents via claude CLI)
- Resolution phase (launch resolver agent)
- Auto-fix loop
- Verification integration
- `--reset-pack`, `--reset-all-packs` CLI flags

**Tests:** Integration test with Claude Code pack against a small test repo (3 tasks, 1 dependency, 1 anti-affinity pair).

### Phase 3: Web UI

**Goal:** Build the FastAPI server and embedded React SPA.

**Deliverables:**
- FastAPI server with all REST endpoints
- WebSocket handler with state broadcasting and log streaming
- Embedded React SPA with all five views:
  - Setup View (pack selection, config, preflight, intake monitoring)
  - Main Monitor View (pipeline strip, worker cards with live tail, task feed)
  - Task Detail View (plan, status, full streaming log)
  - DAG View (React Flow interactive graph)
  - History View (past sessions, final state)
- Self-bootstrapping entry point
- Port auto-detection

**Tests:** Manual testing against running orchestrator. Verify WebSocket updates, log streaming, DAG rendering with real constraint data.

### Phase 4: Additional Packs (proof of generality)

**Goal:** Prove the engine is truly generic by implementing non-coding packs.

**Deliverables:**
- ffmpeg transcode pack (shell executor, temp-directory isolation, ffprobe verification)
- youtube-dl download pack (shell executor, output-directory isolation, file-exists verification)
- Documentation: "How to create a pack" guide

**Tests:** End-to-end: run a batch of ffmpeg transcodes through Cognitive Switchyard with dependency constraints.

---

## 9. Reference: Existing System Mapping

How the current BSE orchestrator maps to the Cognitive Switchyard design:

| Current (BSE) | Cognitive Switchyard Equivalent |
|---------------|---------------------|
| `work/planning/intake/` | Session `intake/` directory |
| `work/plan.sh` | Orchestrator planning phase + Claude Code pack planner prompt |
| `work/planning/PLANNER.md` | Pack `prompts/planner.md` |
| `work/stage.sh` | Orchestrator resolution phase + Claude Code pack resolver prompt |
| `work/execution/RESOLVER.md` | Pack `prompts/resolver.md` |
| `work/execution/RESOLUTION.md` | Session `resolution.json` (structured) |
| `work/orchestrate.sh` | `orchestrator.py` + `scheduler.py` + `worker_manager.py` |
| `work/execution/WORKER.md` | Pack `prompts/worker.md` |
| `work/SYSTEM.md` | Pack `prompts/system.md` |
| `work/DASHBOARD.md` | Web UI Main Monitor View (replaces file-based dashboard) |
| `cc-opus()` / `cc-sonnet()` | Pack executor config (model + CLI command) |
| `--dangerously-skip-permissions` | Part of Claude Code pack's execute hook |
| `--allowedTools` | Part of Claude Code pack's per-phase executor config |
| `.worktrees/worker_<N>` | Pack isolation hook (git-worktree type) |
| `FULL_TEST_INTERVAL` | Pack `phases.verification.interval` |
| `generate_release_notes.sh` | Pack post-session hook (optional, pack-specific) |
| `NEXT_SEQUENCE` file | Session-level auto-incrementing task ID in SQLite |
| `##PROGRESS##` markers | Standardized progress format (configurable per pack) |

---

## 10. Crash Recovery and Idempotent Restart

Every phase of the **orchestrator's** pipeline must be idempotent. If the process is interrupted at any point -- crash, SIGKILL, power loss, user Ctrl-C -- re-running the same command must resume cleanly without manual intervention.

**Scope of idempotency guarantee:** Idempotency is a property of the orchestrator, not of user-provided execution scripts. The orchestrator guarantees that its own operations (file moves, state transitions, worker lifecycle, dispatch decisions) are safe to repeat. It does NOT guarantee that the user's executor scripts, pack hooks, or external tools are idempotent. If a user's execute script performs non-idempotent operations (e.g., sending an email, charging a credit card, appending to a remote log without dedup), re-running after a crash may re-execute those operations. Pack authors who perform non-idempotent work in their executors must either: (a) build their own recovery/dedup logic into the executor or `isolate_end` hook, or (b) accept that crash recovery may re-trigger side effects. The orchestrator's contract is: "I will re-dispatch your task cleanly into a fresh isolation workspace" -- what happens inside that workspace is the pack's responsibility.

### 10.1 Recovery Principle

On startup, before entering the normal dispatch loop, the orchestrator runs a recovery pass. Recovery inspects the file-as-state directories and the SQLite database to detect incomplete operations, then rolls them back to the last consistent state. The rule is: **incomplete work is reverted, completed work is preserved.**

### 10.2 Execution Phase Recovery

This is the most complex recovery scenario because workers may have been mid-task with partially committed work in isolation workspaces.

**On restart, the orchestrator must:**

1. **Detect orphaned worker slots.** Scan `workers/<N>/` directories for plan files. Any plan found here was in-flight when the crash occurred.

2. **Check for completed-but-not-collected work.** If a status sidecar file exists alongside the plan and reads `STATUS: done`, the worker finished but the orchestrator crashed before collecting the result. In this case:
   - Run the pack's `isolate_end` hook (merge/cleanup).
   - Move the plan + status + log to `done/`.
   - This preserves completed work.

3. **Revert incomplete work.** If no status sidecar exists, or the sidecar reads `STATUS: blocked` or is malformed, the worker did not finish cleanly. In this case:
   - Run the pack's `isolate_end` hook with status "blocked" (cleanup without merge).
   - Move the plan file back to `ready/` (not `blocked/` -- the failure was infrastructure, not task-level).
   - The task will be re-dispatched on the next eligible cycle.

4. **Clean up isolation artifacts.** Remove any orphaned worktrees, temp directories, or stale branches that the pack's isolation hooks left behind. The pack's `isolate_end` hook handles this, but if `isolate_end` itself fails (e.g., corrupt worktree), the orchestrator must forcibly remove the workspace directory and log a warning.

5. **Kill zombie subprocesses.** Check for any running processes from the previous session (by PID file or process name pattern). Send SIGTERM, wait 5 seconds, then SIGKILL if still running.

6. **Reconcile SQLite with filesystem.** The filesystem is the source of truth. If the database says a task is "active" but the plan file is in `ready/`, update the database to match. Scan all state directories and rebuild the database projection if needed.

### 10.3 Planning Phase Recovery

If planners were interrupted mid-planning:

1. **Plans in `claimed/`.** These were being worked on by a planner. Move them back to `intake/`. The planner's partial work (if any) is discarded -- planning is atomic (either a complete plan lands in `staging/` or the intake item returns to `intake/`).

2. **Plans in `staging/`.** These are complete and valid. Leave them. They will be picked up by the next resolution run.

3. **Plans in `review/`.** These need human input. Leave them. They were already complete enough to surface questions.

### 10.4 Resolution Phase Recovery

Resolution is inherently idempotent. The resolver reads all plans in `staging/`, produces a constraint graph, and moves resolved plans to `ready/`. If interrupted:

1. **Partial `resolution.json`.** Delete it. It will be regenerated on the next resolution run.
2. **Plans partially moved to `ready/`.** Check each plan in `ready/` -- if it has constraint metadata (DEPENDS_ON, ANTI_AFFINITY, EXEC_ORDER), it was fully resolved. If not, move it back to `staging/`.
3. Re-running resolution on already-resolved plans is safe -- it overwrites the constraint metadata with the same values.

### 10.5 Session State Machine

Sessions have explicit states that govern what the orchestrator does on startup:

| State | Meaning | On restart |
|-------|---------|------------|
| `created` | Session exists but hasn't started | Show Setup View, wait for Start |
| `planning` | Planners are running | Recovery: move `claimed/` back to `intake/`, re-launch planners |
| `resolving` | Resolver is running | Recovery: delete partial resolution, re-launch resolver |
| `running` | Execution phase active | Recovery: collect completed, revert incomplete, resume dispatch |
| `paused` | User paused dispatch | Resume as paused (don't auto-resume) |
| `verifying` | Verification suite running | Recovery: re-run verification |
| `completed` | All tasks done, session finished | No recovery needed, show results |
| `aborted` | User aborted | No recovery needed, show final state |

The session state is persisted in SQLite. On restart, the orchestrator reads the state and enters the appropriate recovery path.

### 10.6 Idempotency Guarantees by Operation

| Operation | Idempotent? | How |
|-----------|-------------|-----|
| File move (intake -> claimed) | Yes | Atomic `os.rename()`. If file already gone, another planner claimed it -- skip. |
| Plan write (planner -> staging) | Yes | Write to temp file, then atomic rename. Partial writes don't produce valid plan files. |
| Resolution | Yes | Overwrites constraint metadata. Same input produces same output. |
| Worker dispatch | Yes | Plan moves from `ready/` to `workers/<N>/`. If already in worker slot, skip. |
| Status sidecar write | Yes | Written atomically by executor. Presence = completion signal. |
| Isolation merge (isolate_end) | Idempotent if pack implements it correctly. | Pack contract requires `isolate_end` to be safe to call multiple times. If already merged, the hook must detect this (e.g., branch already deleted) and return success. |
| Database updates | Yes | All writes are conditional (UPDATE WHERE status = expected_status). Race-safe. |

### 10.7 Implementation Requirements for Pack Authors

Pack lifecycle hooks MUST be idempotent:

- `isolate_start`: If the workspace already exists from a previous interrupted run, clean it up and recreate. Do not fail with "already exists."
- `isolate_end`: If the merge was already completed (e.g., branch already merged and deleted), return success. Do not fail with "branch not found."
- `execute`: The orchestrator re-dispatches failed/interrupted tasks from scratch in a fresh isolation workspace -- it does not attempt to resume mid-step. The executor itself does not need to be idempotent *for orchestrator recovery purposes*. However, if the executor performs external side effects (API calls, file uploads, notifications, database writes outside the isolation workspace), the pack author is responsible for making those operations safe to repeat, or for accepting the consequences of re-execution. The orchestrator provides the clean workspace; the pack owns what happens inside it.

---

## 11. Reference Material for Implementing Agents

The `reference/` directory in this project contains the production orchestration system that Cognitive Switchyard was extracted from. It is **read-only reference material** -- do not modify these files. Use them to understand patterns, data formats, edge cases, and battle-tested logic.

### Key Reference Files

| File | What to learn from it |
|------|----------------------|
| `reference/work/orchestrate.sh` | Dispatch loop, constraint enforcement, worker lifecycle, auto-fix loop, recovery logic. This is 900+ lines of production-tested orchestration. Study the polling loop, how eligibility is checked, how worktrees are managed, and how failures cascade. |
| `reference/work/planning/PLANNER.md` | Planner agent prompt. Use as template for the Claude Code pack's `prompts/planner.md`. |
| `reference/work/execution/WORKER.md` | Worker agent prompt. Use as template for the Claude Code pack's `prompts/worker.md`. Note the 5-phase structure and progress marker format. |
| `reference/work/execution/RESOLVER.md` | Resolver agent prompt. Use as template for the Claude Code pack's `prompts/resolver.md`. |
| `reference/work/SYSTEM.md` | Shared rules for all agents. Use as template for `prompts/system.md`. |
| `reference/work/execution/RESOLUTION.md` | Real resolution output from an 8-task batch with complex anti-affinity groups. Use to validate the constraint graph JSON format. |
| `reference/work/DASHBOARD.md` | Dashboard data structure. Shows what information the UI must display. |
| `reference/work/execution/done/*.status` | Real status sidecar files. Validate your sidecar parsing against these. |
| `reference/work/execution/done/*.plan.md` | Real execution plans with metadata headers. Validate your plan parsing against these. |
| `reference/work/plan.sh` | Planner launcher. Shows how parallel planner agents are spawned and managed. |
| `reference/work/stage.sh` | Resolver launcher. Shows the staging workflow. |
| `reference/work/planning/INTAKE_PROMPT.md` | Intake document template and generation prompt. |

### How to Use Reference Material

1. **Before implementing a component**, read the corresponding reference file to understand the production behavior.
2. **Data format validation**: Parse real `.status`, `.plan.md`, and `RESOLUTION.md` files to ensure your parsers handle actual production data.
3. **Edge case awareness**: The `orchestrate.sh` handles crash recovery, zombie worktrees, concurrent planner races, and many other edge cases. Port these carefully.
4. **Prompt engineering**: The prompt files are tuned through many iterations. Start with them as-is for the Claude Code pack, then iterate.

---

## 12. Open Items and Future Considerations

### Decided but not yet detailed
- Exact CLI argument structure (subcommands, flags)
- Error recovery for partial isolation failures (isolate_start succeeds partially)
- Pack config schema validation error messages

### Explicitly deferred
- Multi-tenant / multi-user support
- Pack marketplace / sharing
- CI/CD integration (triggering Cognitive Switchyard from webhooks)
- Mobile-responsive UI (desktop-only for now)

Note: Remote execution (SSH to other machines) is not an orchestrator concern. A pack's execute hook can SSH, rsync, or do whatever it wants -- the orchestrator just runs the hook and captures output. This is handled at the pack level, not the framework level.

### Design constraints for implementing agents
- All frontend code is in a single HTML string (no separate .js/.css files)
- All CDN deps use UMD builds compatible with React 18 (not React 19+). See "React 18 / UMD Lifecycle" below.
- Python backend uses only stdlib + fastapi + uvicorn + aiosqlite (minimal deps)
- No npm install, no node_modules, no webpack/vite
- Port selection must use the `find_free_port()` pattern (never hardcoded)
- Self-bootstrapping: single entry point, no separate install step

### React 18 / UMD Lifecycle Risk

React 19 dropped UMD builds entirely. Our architecture depends on UMD (script-tag loading, no bundler) so we are pinned to React 18. The risk:

**Current status (as of March 2026):** React 18 is in security-support-only mode. React 19 has been stable since late 2024. The React team has not announced an end-of-life date for React 18 security patches, but active feature development is exclusively on 19+.

**Practical risk assessment:** Low for the 12-18 month horizon. React 18 UMD builds are immutable artifacts on CDN (unpkg, jsdelivr) -- they don't disappear when support ends. Security patches to React 18 are unlikely to matter for a locally-hosted, single-user tool that loads no untrusted third-party components. The real risk is ecosystem drift: if React Flow or other dependencies drop React 18 support, we'd be stuck on older versions of those libraries.

**Migration path if needed:** React 19 recommends ESM-based CDNs (esm.sh) for script-tag loading. Migration would require switching CDN URLs and updating any code that uses deprecated React 18 APIs (mostly around `ReactDOM.render` patterns, which we shouldn't be using anyway with React 18's `createRoot`). React Flow v12+ requires React 19 -- so a React upgrade would also mean a React Flow upgrade, which could change APIs.

**Recommendation:** Build on React 18 now. Pin CDN URLs to exact versions (not `@latest`). Accept the risk. If migration becomes necessary, it is a frontend-only change -- the backend, pack system, and orchestrator are completely unaffected.

### Post-Implementation Deliverables

These documents and tools are required after the core implementation is complete, before Cognitive Switchyard is usable by anyone other than the original developer.

**Pack Author Guide** -- how to create, test, and distribute custom packs. Covers: pack.yaml schema (with annotated examples), lifecycle hook contracts (inputs, outputs, exit codes), the progress protocol, status sidecar format, isolation patterns (git-worktree vs temp-directory vs none), preflight prerequisite checks, idempotency requirements for hooks, and testing a pack locally before use. Should include a tutorial walking through building a simple pack from scratch (e.g., a shell-script-based pack that runs linting on files).

**Pack scaffolding tooling** -- a `switchyard init-pack <name>` CLI command that generates a skeleton pack directory with a minimal pack.yaml, placeholder scripts, and a README. Lowers the barrier to entry for pack authors.

**Pack validation tooling** -- a `switchyard validate-pack <path>` CLI command that checks a pack directory for common errors: missing required fields in pack.yaml, scripts without executable bits, missing shebang lines, referenced files that don't exist, invalid progress_format regex. Can be run before a session to catch pack authoring mistakes early.

**User/Operator Guide** -- how to install, configure, and run Cognitive Switchyard. Covers: bootstrapping, global settings (config.yaml), session lifecycle (setup, start, monitor, completion), the UI (with screenshots), timeout configuration, retention/purge, crash recovery behavior, and troubleshooting common issues.

**Built-in Pack Documentation** -- for each pack that ships with Cognitive Switchyard (starting with the Claude Code pack): what it does, what prerequisites it expects, how to configure it, what the planning/execution prompts look like, and how to customize them after bootstrap copies them to `~/.switchyard/packs/`.
