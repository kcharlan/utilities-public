# task_orch

Legacy task orchestration scaffold extracted from
`benefit_specification_engine/work`.

It preserves the agent prompts and shell entrypoints for this workflow:

1. Put numbered intake items in `task_orch/planning/intake/`
2. Run `task_orch/plan.sh` to create plans in `planning/staging/` or
   `planning/review/`
3. Run `task_orch/stage.sh` to add dependency and anti-affinity metadata and
   move resolved plans to `execution/ready/`
4. Run `task_orch/orchestrate.sh` to dispatch eligible plans to isolated git
   worktrees, squash-merge successful branches, run periodic and final tests,
   and aggregate operator actions into `RELEASE_NOTES.md`

## Included files

- Operator documentation: `SYSTEM.md`, `USER_PROCESS.md`
- Planning assets: `planning/PLANNER.md`, `planning/INTAKE_PROMPT.md`, `planning/NEXT_SEQUENCE`
- Execution assets: `execution/RESOLVER.md`, `execution/WORKER.md`
- Shell entrypoints: `plan.sh`, `stage.sh`, `orchestrate.sh`, `generate_release_notes.sh`

Generated queue/state directories are not tracked in this snapshot. Create them
before the first run:

```bash
mkdir -p \
  task_orch/planning/{intake,claimed,staging,review} \
  task_orch/execution/{ready,workers,active,done,blocked}
```

Historical intake items, implementation plans, status files, worker and
resolver logs, traces, dashboards, release notes, and completed deployment
runbooks were intentionally removed.

## Important limitations

This is a source-project snapshot, not a drop-in generic orchestrator.
`orchestrate.sh` and the retained agent prompts still assume:

- `task_orch/` is directly under the target git repository root;
- the Claude CLI is installed and accepts the model names `opus` and `sonnet`;
- the current branch is not `main`;
- the target project has `.venv/bin/pytest`, `scripts/test_all.sh`,
  `CLAUDE.md`, and `docs/LESSONS_LEARNED.md`;
- full-suite runs use the source project's `BSE_DATA_DIR` and
  `BSE_ENABLE_DEV_ENDPOINTS` environment variables; and
- macOS utilities such as `open` are available for the final release-note
  prompt.

Customize those assumptions in the scripts and prompt contracts before using
the scaffold in a different repository. The commands launch Claude with
permission bypass enabled, create and delete worktrees and temporary branches,
commit worker changes, and squash-merge successful work; review them before
running.

The queue lifecycle and current operator steps are documented in
`USER_PROCESS.md`. `SYSTEM.md` is the shared contract loaded by planner,
resolver, worker, and fixer agents.
