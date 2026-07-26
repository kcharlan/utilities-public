# Built-In Claude Code Pack

The bundled `claude-code` pack is the reference agent-backed pack shipped with Cognitive Switchyard. After bootstrap, the runtime copy lives at `~/.cognitive_switchyard/packs/claude-code`.

## What It Uses

| Phase | Details |
|-------|---------|
| planning | agent executor, Claude runtime, opus model, max 4 concurrent planners |
| resolution | agent executor, Claude runtime, opus model |
| execution | shell executor, max 4 workers |
| verification | enabled, interval 4, command: `scripts/verify` |
| auto-fix | enabled, max 2 attempts, Claude runtime, opus model |
| isolation | `git-worktree` (setup: `scripts/isolate_start`, teardown: `scripts/isolate_end`) |

Timeouts: task_idle 900s, task_max unlimited, session_max 14400s (4 hours).

## Prerequisites

Validate the runtime copy before use:

```bash
./switchyard validate-pack ~/.cognitive_switchyard/packs/claude-code
```

Typical operator prerequisites:

- Claude CLI available in `PATH`
- authenticated Claude session
- `jq` available in `PATH`
- a valid repository root for git-worktree isolation (when a session branch is selected, `COGNITIVE_SWITCHYARD_REPO_ROOT` will point to the session worktree, not the original repo)

The default execution worker model is `sonnet`. Override it with `CLAUDE_CODE_WORKER_MODEL`.

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
~/.cognitive_switchyard/packs/claude-code/
```

Common customization points:

- prompt wording
- prerequisite checks
- worker/verification script behavior

If you need a clean baseline again:

```bash
./switchyard reset-pack claude-code
```
