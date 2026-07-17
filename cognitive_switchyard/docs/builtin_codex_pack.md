# Built-In Codex Pack

The bundled `codex` pack is the strict OpenAI Codex CLI runner pack shipped with Cognitive Switchyard. After bootstrap, the runtime copy lives at `~/.cognitive_switchyard/packs/codex`.

## What It Uses

| Phase | Details |
|-------|---------|
| planning | agent executor, Codex runtime, `gpt-5.4`, `xhigh`, max 3 concurrent planners |
| resolution | agent executor, Codex runtime, `gpt-5.4`, `xhigh` |
| execution | shell executor, max 3 workers (Codex CLI, `high` reasoning effort) |
| verification | enabled, interval 4, command: `scripts/verify` |
| auto-fix | enabled, max 2 attempts, Codex runtime, `gpt-5.4`, `high` |
| isolation | `git-worktree` (setup: `scripts/isolate_start`, teardown: `scripts/isolate_end`) |

Timeouts: task_idle 300s, task_max unlimited, session_max 14400s (4 hours).

Planning, resolution, execution, and auto-fix all use Codex. This pack is intended to remain usable when Claude is unavailable.

## Prerequisites

Validate the runtime copy before use:

```bash
./switchyard validate-pack ~/.cognitive_switchyard/packs/codex
```

Typical operator prerequisites:

- Codex CLI available in `PATH`
- authenticated OpenAI session
- a valid repository root for git-worktree isolation (when a session branch is selected, `COGNITIVE_SWITCHYARD_REPO_ROOT` will point to the session worktree, not the original repo)

## Worker Model

The default worker model is `gpt-5.4`. Override with the `CODEX_WORKER_MODEL` environment variable:

```bash
CODEX_WORKER_MODEL=o3 ./switchyard start --session demo --pack codex
```

## Prompt Files

The pack includes:

- `prompts/system.md`
- `prompts/planner.md`
- `prompts/resolver.md`
- `prompts/worker.md`
- `prompts/fixer.md`

## Customization

Edit the runtime copy, not the bundled source copy:

```bash
~/.cognitive_switchyard/packs/codex/
```

Common customization points:

- prompt wording
- prerequisite checks
- worker/verification script behavior
- default model (`CODEX_WORKER_MODEL`)
- reasoning effort defaults in `pack.yaml`

If you need a clean baseline again:

```bash
./switchyard reset-pack codex
```
