# coding

This directory collects reusable coding orchestration tools and reference process assets.

- [`design_orch/`](design_orch/): a design-document packetization and
  implementation loop extracted from Git Fleet. It can drive Codex or Claude
  through bootstrap, planning, implementation, validation, full-suite
  verification, and drift-audit stages.
- [`task_orch/`](task_orch/): a legacy Claude-based intake, planning,
  dependency-resolution, and worktree execution scaffold extracted from
  Benefit Specification Engine. It is retained as a reference snapshot and is
  being superseded by Cognitive Switchyard. Its orchestrator still contains
  source-project test and environment assumptions; read its README before
  attempting to reuse it.

These folders are curated infrastructure snapshots. Historical tickets,
packet runs, logs, completed deployment notes, and other project-specific
execution artifacts are intentionally excluded. Generated queue, plan, audit,
and log directories are also not tracked.
