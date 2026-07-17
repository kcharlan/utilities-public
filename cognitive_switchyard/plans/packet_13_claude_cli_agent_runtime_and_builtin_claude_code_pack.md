# Packet 13 - Claude CLI Agent Runtime and Built-In Claude Code Pack

## Why This Packet Exists

Packet `10` intentionally shipped only a minimal built-in `claude-code` scaffold so bootstrap and pack-sync behavior could be validated without depending on a real external agent CLI. The live codebase still reflects that compromise: the bundled pack only contains a placeholder `pack.yaml`, one trivial `execute` script, and no prompts, templates, preflight hook, verification hook, or isolation workflow.

The runtime has a matching gap. Planning, agent-based resolution, and auto-fix currently work only when tests inject in-memory callables into `start_session()`. The actual CLI and backend start paths do not provide a real Claude runner. Before the project can be handed off through pack-author tooling and operator docs, it needs a real default Claude-backed runtime plus a real reference pack.

## Scope

- Add a dedicated Claude CLI runtime adapter for planning, agent-based resolution, and auto-fix so non-test start paths can execute agent-configured pack phases without injected doubles.
- Keep those agent call sites injectable for tests, but make the runtime adapter the default when the session is started from the CLI or backend.
- Replace the packet-`10` placeholder `claude-code` pack with a real bundled reference pack:
  - full `pack.yaml`
  - prompts for `system`, `planner`, `resolver`, `worker`, and `fixer`
  - templates for intake, plan, and status artifacts
  - scripts for `preflight`, `execute`, `verify`, `isolate_start`, and `isolate_end`
- Source the built-in prompt/content skeleton from the relevant `reference/work/` materials rather than inventing new prompt contracts.
- Add regression coverage for Claude runtime invocation, default runtime wiring from CLI/backend entrypoints, bundled-pack sync fidelity, and built-in preflight behavior.

## Non-Goals

- No `init-pack` or `validate-pack` authoring commands; those belong in the next packet.
- No second built-in pack catalog or proof-of-generality shell packs yet.
- No session `RELEASE_NOTES.md` generation, History release-notes display, or operator-guide work.
- No provider abstraction beyond the concrete Claude CLI path needed for the bundled `claude-code` pack.
- No redesign of packet-`11`/`12` monitor transport or packet-`12A` history trimming semantics.

## Relevant Design Sections

- `3.2 Planning (optional)`
- `3.3 Resolution (optional, recommended)`
- `3.4 Execution`
- `3.5 Verification (optional)`
- `3.6 Auto-Fix (optional)`
- `4.1 Pack Directory Structure`
- `4.2 pack.yaml Schema`
- `4.3 Lifecycle Hook Contracts`
- `4.5 Pack Distribution`
- `10.7 Implementation Requirements for Pack Authors`
- `11. Reference Material for Implementing Agents`

## Allowed Files

- `README.md`
- `cognitive_switchyard/cli.py`
- `cognitive_switchyard/server.py`
- `cognitive_switchyard/orchestrator.py`
- `cognitive_switchyard/planning_runtime.py`
- `cognitive_switchyard/verification_runtime.py`
- `cognitive_switchyard/models.py`
- `cognitive_switchyard/builtin_packs/claude-code/`
- `cognitive_switchyard/agent_runtime.py`
- `tests/test_agent_runtime.py`
- `tests/test_cli.py`
- `tests/test_server.py`
- `tests/test_orchestrator.py`
- `tests/test_planning_runtime.py`
- `tests/test_pack_loader.py`
- `tests/test_hook_runner.py`

## Tests To Write First

- `tests/test_agent_runtime.py::test_claude_cli_runner_builds_planner_invocation_from_model_prompt_and_session_inputs`
- `tests/test_agent_runtime.py::test_claude_cli_runner_raises_typed_error_on_non_zero_exit_or_missing_output`
- `tests/test_cli.py::test_start_command_uses_default_claude_runtime_for_agent_enabled_builtin_pack`
- `tests/test_server.py::test_backend_start_path_uses_default_claude_runtime_when_agent_callables_are_not_injected`
- `tests/test_pack_loader.py::test_builtin_claude_code_pack_manifest_loads_full_prompt_template_and_hook_contracts`
- `tests/test_hook_runner.py::test_builtin_claude_code_preflight_reports_missing_claude_or_git_prerequisites_cleanly`

## Implementation Notes

- Keep the Claude adapter in a dedicated runtime module so tests can stub subprocess execution without mocking the whole orchestrator.
- Do not remove the existing injectable seams in `start_session()` and planning/runtime helpers. Packet `13` should add defaults, not hard-wire tests to the real Claude CLI.
- Planning remains the one phase that must use the runtime adapter directly because the design does not allow script-based planning. Resolution and auto-fix should also use the adapter when configured as `agent`.
- Execution can stay on the validated worker subprocess boundary by keeping the bundled pack's `execution.executor` on the shell/script side and delegating Claude worker invocation to `scripts/execute`.
- The bundled `claude-code` pack should include a real `preflight` hook for Claude/Git prerequisites and a real git-worktree isolation path, but all such checks must remain packet-`04` compatible with executable-bit preflight running first.
- Prompt files should be adapted from `reference/work/SYSTEM.md`, `reference/work/planning/PLANNER.md`, `reference/work/execution/RESOLVER.md`, and `reference/work/execution/WORKER.md`. Keep the prompt corpus repo-local and syncable through the existing packet-`10` built-in-pack flow.
- The built-in pack README only needs to cover the pack's own prerequisites/configuration. Full pack-author and operator docs stay for packet `14`.

## Acceptance Criteria

- Starting a session from the CLI or backend with the bundled `claude-code` pack no longer requires externally injected planner/resolver/fixer callables when the pack enables those agent phases.
- The new Claude runtime adapter builds prompt/model/session invocations deterministically, surfaces subprocess failures as typed runtime errors, and remains unit-testable without requiring the real Claude CLI during validation.
- The bundled `claude-code` pack syncs as a complete reference pack with prompts, templates, hook scripts, and a design-aligned manifest rather than the packet-`10` placeholder scaffold.
- Built-in-pack preflight reports actionable missing-prerequisite failures for Claude CLI and git-worktree usage before a session starts.
- Existing packet-`08` planning semantics, packet-`09` auto-fix recovery behavior, packet-`10` pack sync/reset flows, and packet-`11` backend session start behavior remain covered by regression tests.

## Validation Focus

- `.venv/bin/python -m pytest tests/test_agent_runtime.py tests/test_planning_runtime.py tests/test_orchestrator.py -q`
- `.venv/bin/python -m pytest tests/test_cli.py tests/test_server.py tests/test_pack_loader.py tests/test_hook_runner.py -q`
