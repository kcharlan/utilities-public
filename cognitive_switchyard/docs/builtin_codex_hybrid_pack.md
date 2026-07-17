# Built-In Codex Hybrid Pack

The bundled `codex-hybrid` pack is the explicit hybrid Claude/Codex runner pack shipped with Cognitive Switchyard. After bootstrap, the runtime copy lives at `~/.cognitive_switchyard/packs/codex-hybrid`.

## What It Uses

| Phase | Details |
|-------|---------|
| planning | agent executor, Claude runtime, opus model, max 3 concurrent planners |
| resolution | agent executor, Claude runtime, opus model |
| execution | shell executor, max 3 workers (Codex CLI, `high` reasoning effort) |
| verification | enabled, interval 4, command: `scripts/verify` |
| auto-fix | enabled, max 2 attempts, Claude runtime, opus model |
| isolation | `git-worktree` (setup: `scripts/isolate_start`, teardown: `scripts/isolate_end`) |

Timeouts: task_idle 300s, task_max unlimited, session_max 14400s (4 hours).

Planning, resolution, and auto-fix use Claude. Execution uses Codex.

## Prerequisites

Validate the runtime copy before use:

```bash
./switchyard validate-pack ~/.cognitive_switchyard/packs/codex-hybrid
```

Typical operator prerequisites:

- Claude CLI available in `PATH`
- authenticated Claude session
- Codex CLI available in `PATH`
- authenticated OpenAI session
- a valid repository root for git-worktree isolation (when a session branch is selected, `COGNITIVE_SWITCHYARD_REPO_ROOT` will point to the session worktree, not the original repo)

## Worker Model

The default worker model is `gpt-5.4`. Override with the `CODEX_WORKER_MODEL` environment variable:

```bash
CODEX_WORKER_MODEL=o3 ./switchyard start --session demo --pack codex-hybrid
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
~/.cognitive_switchyard/packs/codex-hybrid/
```

Common customization points:

- prompt wording
- prerequisite checks
- worker/verification script behavior
- default model (`CODEX_WORKER_MODEL`)

If you need a clean baseline again:

```bash
./switchyard reset-pack codex-hybrid
```
