# Packet 13 Validation Audit

Date: 2026-03-10
Packet: `plans/packet_13_claude_cli_agent_runtime_and_builtin_claude_code_pack.md`
Verdict: `validated`

## Scope Checked

- Read `docs/implementation_packet_playbook.md` and the packet doc first.
- Reviewed the packet implementation in the allowed file set:
  - `cognitive_switchyard/agent_runtime.py`
  - `cognitive_switchyard/orchestrator.py`
  - `cognitive_switchyard/builtin_packs/claude-code/`
  - `tests/test_agent_runtime.py`
  - `tests/test_cli.py`
  - `tests/test_server.py`
  - `tests/test_orchestrator.py`
  - `tests/test_planning_runtime.py`
  - `tests/test_pack_loader.py`
  - `tests/test_hook_runner.py`
- Verified the bundled prompt corpus against the packet's referenced source materials:
  - `reference/work/SYSTEM.md`
  - `reference/work/planning/PLANNER.md`
  - `reference/work/execution/RESOLVER.md`
  - `reference/work/execution/WORKER.md`

## Validation Result

Validation found two concrete packet-scope defects and repaired them before final sign-off:

1. The default Claude runtime only passed the phase prompt to the CLI, so the bundled shared `prompts/system.md` rules were never included for planning, resolution, or auto-fix.
2. The bundled `claude-code` preflight hook validated the synced runtime pack directory instead of `COGNITIVE_SWITCHYARD_REPO_ROOT`, which would fail real git-worktree starts outside the repository and would not report a missing repo-root configuration clearly.

After repair, no packet-scope defect remained.

The implementation now meets the packet acceptance criteria:

- CLI and backend session starts default to the Claude runtime for the bundled `claude-code` agent phases without requiring injected planner/resolver/fixer callables.
- The Claude runtime builds deterministic model/prompt/session invocations, raises typed runtime errors, and now bundles the shared system prompt with each phase prompt.
- The synced `claude-code` built-in pack ships prompts, templates, verification/preflight/isolation hooks, and a design-aligned manifest.
- Built-in pack preflight reports missing Claude/Git prerequisites and now validates `COGNITIVE_SWITCHYARD_REPO_ROOT` for git-worktree usage before execution starts.

## Test Evidence

- `.venv/bin/python -m pytest tests/test_agent_runtime.py tests/test_hook_runner.py -q`
  - Result: `12 passed in 0.92s`
- `.venv/bin/python -m pytest tests/test_agent_runtime.py tests/test_planning_runtime.py tests/test_orchestrator.py tests/test_cli.py tests/test_server.py tests/test_pack_loader.py tests/test_hook_runner.py -q`
  - Result: `86 passed in 15.53s`

## Notes

- Validation stayed inside packet scope and stopped once the repaired packet tests and adjacent regressions were decisive.
