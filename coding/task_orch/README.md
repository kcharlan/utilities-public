# task_orch

Reusable task orchestration scaffold extracted from `benefit_specification_engine/work`.

This package preserves the queue layout, agent prompts, operator docs, and shell entrypoints for a plan -> resolve -> execute workflow:

1. Put numbered intake items in `task_orch/planning/intake/`
2. Run `task_orch/plan.sh` to turn intake into implementation plans
3. Run `task_orch/stage.sh` to resolve cross-plan dependencies
4. Run `task_orch/orchestrate.sh` to dispatch plans across worker worktrees

What is included:

- Operator documentation: `SYSTEM.md`, `USER_PROCESS.md`, `RUNBOOK_v0.1.79.md`
- Planning assets: `planning/PLANNER.md`, `planning/INTAKE_PROMPT.md`, `planning/NEXT_SEQUENCE`
- Execution assets: `execution/RESOLVER.md`, `execution/WORKER.md`
- Shell entrypoints: `plan.sh`, `stage.sh`, `orchestrate.sh`, `generate_release_notes.sh`
- Empty queue/state directories for intake, staging, ready, blocked, done, and worker slots

What was intentionally removed:

- Historical intake items, plan files, status files, worker logs, resolver logs, trace logs, dashboard output, release notes, and past run artifacts

Notes:

- The scripts and docs now reference `task_orch/` instead of `work/`.
- This is a stripped infrastructure snapshot, not a live project workspace.
- To use it in a real repo, place `task_orch/` at that repo's root so the worktree-based scripts resolve paths correctly.
