Built-in strict runner pack for OpenAI Codex CLI driven planning, resolution,
execution, verification, and auto-fix.

Prerequisites:
- `codex` must be installed and authenticated on `PATH`.
- `git` must be available on `PATH`.
- For git-worktree isolation, set `COGNITIVE_SWITCHYARD_REPO_ROOT` to the
  repository root that workers should execute inside.

Runtime notes:
- Planning, resolution, execution, and auto-fix all use Codex.
- Execution delegates worker calls to `scripts/execute`, which invokes `codex exec`.
- Verification uses `scripts/verify` through the pack-root environment exported
  by the orchestrator. The built-in verifier runs from the effective target
  directory, prefers a worktree-local virtualenv, reuses the source repo's
  virtualenv for compatible worktree sessions, and otherwise bootstraps a
  session-scoped verification env under the session root. It never falls back
  to the switchyard bootstrap venv or naked PATH/Homebrew pytest.
- Default worker model is `gpt-5.4` (override with `CODEX_WORKER_MODEL` env var).
- Default reasoning effort is `xhigh` for planning/resolution and `high` for
  execution/auto-fix.
