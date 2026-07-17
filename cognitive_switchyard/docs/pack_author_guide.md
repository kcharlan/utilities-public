# Pack Author Guide

Custom packs live under `~/.cognitive_switchyard/packs/<pack-name>`. Cognitive Switchyard loads only runtime packs from that directory, including built-in packs after bootstrap sync.

## Quick Start

Create a scaffold:

```bash
./switchyard init-pack my-pack
./switchyard validate-pack ~/.cognitive_switchyard/packs/my-pack
```

The scaffold creates:

- `pack.yaml`
- `README.md`
- `prompts/`
- `scripts/`
- `templates/`

## Full pack.yaml Schema

### Top-level fields (required)

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Kebab-case identifier (e.g. `my-pack`) |
| `description` | string | Human-readable summary |
| `version` | string | Semver string (e.g. `1.0.0`) |

### `phases` (required mapping)

`phases.execution` is always required and must have `enabled: true`.

#### `phases.planning` (optional)

| Field | Type | Default | Required when |
|-------|------|---------|---------------|
| `enabled` | bool | `false` | — |
| `executor` | string | `agent` | Must be `agent` when enabled |
| `runtime` | string | `claude` | Allowed values: `claude`, `codex` |
| `model` | string | — | Required when `executor: agent` |
| `reasoning_effort` | string | — | Optional for agent runtimes; `low`, `medium`, `high`, or `xhigh` |
| `prompt` | path | — | Required when `executor: agent` |
| `max_instances` | int | `1` | — |

#### `phases.resolution` (optional)

| Field | Type | Default | Required when |
|-------|------|---------|---------------|
| `enabled` | bool | `true` | — |
| `executor` | string | `agent` | Must be `agent`, `script`, or `passthrough` |
| `runtime` | string | `claude` | Used when `executor: agent`; allowed values: `claude`, `codex` |
| `model` | string | — | Required when `executor: agent` |
| `reasoning_effort` | string | — | Optional for agent runtimes; `low`, `medium`, `high`, or `xhigh` |
| `prompt` | path | — | Required when `executor: agent` |
| `script` | path | — | Required when `executor: script` |

#### `phases.execution` (required)

| Field | Type | Default | Required when |
|-------|------|---------|---------------|
| `enabled` | bool | `true` | Must be `true` |
| `executor` | string | `shell` | Must be `agent` or `shell` |
| `model` | string | — | Required when `executor: agent` |
| `reasoning_effort` | string | — | Optional; for shell executors this is exposed via env to the hook |
| `prompt` | path | — | Required when `executor: agent` |
| `command` | path | — | Required when `executor: shell` |
| `max_workers` | int | `2` | — |

#### `phases.verification` (optional)

| Field | Type | Default | Required when |
|-------|------|---------|---------------|
| `enabled` | bool | `false` | — |
| `command` | string | — | Required when enabled |
| `interval` | int | `4` | — |

### `auto_fix` (optional)

| Field | Type | Default | Required when |
|-------|------|---------|---------------|
| `enabled` | bool | `false` | — |
| `max_attempts` | int | `2` | — |
| `runtime` | string | `claude` | Allowed values: `claude`, `codex` |
| `model` | string | — | Required when enabled |
| `reasoning_effort` | string | — | Optional for agent runtimes; `low`, `medium`, `high`, or `xhigh` |
| `prompt` | path | — | Required when enabled |

### `isolation` (optional)

| Field | Type | Default | Allowed values |
|-------|------|---------|----------------|
| `type` | string | `none` | `git-worktree`, `temp-directory`, `none` |
| `setup` | path | — | Path to isolate_start hook |
| `teardown` | path | — | Path to isolate_end hook |

### `prerequisites` (optional list)

Each entry has:
- `name`: human-readable label
- `check`: shell command that exits 0 when the prerequisite is met

### `timeouts` (optional)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `task_idle` | int (seconds) | `420` | Kill task if no output for this many seconds |
| `task_max` | int (seconds) | `0` | Kill task after this many seconds (0 = unlimited) |
| `session_max` | int (seconds) | `14400` | Kill session after this many seconds |

### `status` (optional)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `progress_format` | string (regex) | `##PROGRESS##` | Pattern workers use for progress lines |
| `sidecar_format` | string | `key-value` | Format of `.status` sidecar: `key-value`, `json`, or `yaml` |

---

## Complete Example pack.yaml

```yaml
# Required top-level fields
name: my-pack               # kebab-case, matches directory name
description: My custom pack for running ffmpeg jobs.
version: 1.0.0

phases:
  # Optional: omit if you don't need planning
  planning:
    enabled: true
    executor: agent         # Only valid value when planning is enabled
    runtime: claude         # claude | codex (default: claude)
    model: opus             # Required for agent executor
    reasoning_effort: high  # Optional; low | medium | high | xhigh
    prompt: prompts/planner.md  # Required for agent executor; path relative to pack root
    max_instances: 2        # Max concurrent planner agents (default: 1)

  # Optional: omit or set executor: passthrough to skip resolution
  resolution:
    enabled: true
    executor: agent         # or: script, passthrough
    runtime: claude         # Used for agent executor
    model: opus             # Required for agent executor
    reasoning_effort: high  # Optional for agent executor
    prompt: prompts/resolver.md  # Required for agent executor

  # Required: execution must be enabled
  execution:
    enabled: true           # Must be true
    executor: shell         # or: agent
    reasoning_effort: medium  # Optional; exposed to shell hooks via env
    command: scripts/execute  # Required for shell executor; path relative to pack root
    max_workers: 3          # Max parallel worker slots (default: 2)

  # Optional: omit if you don't need global test verification
  verification:
    enabled: true
    command: '"$COGNITIVE_SWITCHYARD_PACK_ROOT/scripts/verify"'  # Shell command (quoted for spaces)
    interval: 4             # Run verification every N completed tasks (default: 4)

# Optional: omit if auto-fix is not needed
auto_fix:
  enabled: true
  max_attempts: 2           # Max fix attempts before escalating (default: 2)
  runtime: claude           # claude | codex (default: claude)
  model: opus               # Required when enabled
  reasoning_effort: high    # Optional for agent runtime
  prompt: prompts/fixer.md  # Required when enabled; path relative to pack root

# Optional: isolation for worker workspaces
isolation:
  type: git-worktree        # git-worktree | temp-directory | none (default: none)
  setup: scripts/isolate_start   # Called before execution; path relative to pack root
  teardown: scripts/isolate_end  # Called after execution; path relative to pack root

# Optional: checks shown in the UI preflight panel
prerequisites:
  - name: ffmpeg available
    check: command -v ffmpeg >/dev/null 2>&1
  - name: Git available
    check: command -v git >/dev/null 2>&1

# Optional: override default timeouts
timeouts:
  task_idle: 300    # seconds; 0 = unlimited (default: 420)
  task_max: 0       # seconds; 0 = unlimited (default: 0)
  session_max: 14400  # seconds; 0 = unlimited (default: 14400)

# Optional: customize progress/sidecar formats
status:
  progress_format: "##PROGRESS##"  # Regex; workers prefix progress lines with this
  sidecar_format: key-value        # key-value | json | yaml (default: key-value)
```

## Hooks

Hooks are invoked by the orchestrator, not by the pack itself.

### Conventional hooks

The orchestrator looks for hooks in `scripts/` by name, using a two-step search:

1. **Exact name match:** `scripts/<hook_name>` (no extension)
2. **Stem match:** Any file in `scripts/` whose stem (name without extension) matches `<hook_name>`

If multiple stem matches exist, the orchestrator raises an error — remove the ambiguity.

Supported conventional hooks:

| Hook | Trigger | Required |
|------|---------|---------|
| `scripts/execute` | Task execution (`executor: shell`) | Yes for shell executor |
| `scripts/preflight` | Pre-session preflight check | Optional |
| `scripts/isolate_start` | Before each task (isolation setup) | Optional |
| `scripts/isolate_end` | After each task (isolation teardown) | Optional |
| `scripts/resolve` | Resolution phase (`executor: script`) | Required for script resolver |

### Hook rules

- Hook files must stay inside the pack root (no symlinks outside).
- Hook files must be executable (`chmod +x`).
- Text hook scripts must have a shebang (`#!/bin/bash` etc.).
- `scripts/execute` must emit `##PROGRESS##` lines and write a `.status` sidecar next to the task plan file.

### Hook argument signatures

Hooks receive these arguments and environment variables at runtime:

- **`execute`**: `<plan_path>` — path to the `.plan.md` file to execute
- **`verify`**: `<session_dir>` — path to the session root directory
- **`isolate_start`**: `<plan_path>` `<worktree_path>` (for git-worktree isolation)
- **`isolate_end`**: `<plan_path>` `<worktree_path>` (for git-worktree isolation)
- **`preflight`**: `<session_dir>`

All hooks receive `COGNITIVE_SWITCHYARD_PACK_ROOT` in their environment, set to the absolute path of the runtime pack directory.
Shell execution hooks also receive `CODEX_WORKER_REASONING_EFFORT` when `phases.execution.reasoning_effort` is set in the manifest.

## Validation

Run `validate-pack` before using a pack. It checks:

- manifest/schema errors
- missing referenced files
- non-executable scripts
- text hook scripts without a shebang
- invalid `status.progress_format` regex values
- invalid runtime kinds or reasoning-effort values

## Idempotency

Pack authors own idempotency for lifecycle hooks:

- `isolate_start` must recreate an interrupted workspace cleanly.
- `isolate_end` must tolerate already-cleaned or already-merged work.
- `execute` is re-run from scratch after interruption; external side effects must be safe to repeat or intentionally accepted.

## Local Iteration

Recommended loop:

```bash
./switchyard validate-pack ~/.cognitive_switchyard/packs/my-pack
./switchyard start --session author-test --pack my-pack
```

If a successful session plan includes `## Operator Actions`, Cognitive Switchyard aggregates those sections into `RELEASE_NOTES.md` and writes it into the retained session artifacts. If no completed plan contains an `## Operator Actions` section, no `RELEASE_NOTES.md` is generated.
