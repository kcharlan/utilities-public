# Packet 08: Planning and Resolution Runtime

## Why This Packet Exists

After packet `07`, Cognitive Switchyard can safely restart execution sessions, but it still assumes somebody else has already populated `ready/` with fully resolved task plans. The next missing behavior family is the pre-execution pipeline: turn intake items into staged plans, stop for human review when needed, resolve batch constraints into canonical ready plans plus `resolution.json`, and then hand cleanly into the existing execution engine.

## Scope

- Add planning-phase runtime for session `intake/` items, including atomic claiming into `claimed/` and deterministic cleanup of claimed items after plan emission.
- Support planning-enabled packs through an injected planner-agent boundary that consumes the pack's configured `model` and `prompt` without introducing a user-facing provider-selection surface yet.
- Support planning-disabled packs by treating intake `.plan.md` files as already-authored plans and promoting them into `staging/` after validation.
- Route planner output to `staging/` or `review/` based on whether the emitted plan contains a `## Questions for Review` section, and stop before resolution when review work exists.
- Add staged-plan parsing and header-rewrite helpers so resolution can update `DEPENDS_ON`, `ANTI_AFFINITY`, and `EXEC_ORDER` without weakening the packet-`02` ready-plan parser contract.
- Add resolution runtime for `passthrough`, `script`, and injected `agent` modes, always producing canonical `resolution.json` and moving only fully resolved plans into `ready/`.
- Register resolved ready plans in the state store so packet-`06`/`07` execution can immediately consume them.
- Make planning and resolution rerunnable by reverting leftover `claimed/` files to `intake/` and deleting partial `resolution.json` before regenerating it.

## Non-Goals

- No verification or auto-fix loop; packet `09` owns post-execution verification behavior.
- No REST, WebSocket, SPA, file-watcher, or OS-folder-integration work.
- No built-in pack installation, bootstrap flow, or new user-facing CLI commands; packet `10` owns those surfaces.
- No generic external agent-provider registry or settings schema; planner and resolver agent execution stay behind packet-local injected interfaces for now.
- No recovery of active execution workers; packet `07` already owns execution restart semantics.
- No session-history trimming, retention, or operator-document generation.

## Relevant Design Sections

- `3.2` Planning (optional)
- `3.3` Resolution (optional, recommended)
- `4.2` pack.yaml Schema
- `5.1` Storage Model
- `5.2` File-as-State Mapping
- `5.3` Constraint Graph Format
- `7.1` Module Structure
- `7.3` Orchestrator Loop
- `10.3` Planning Phase Recovery
- `10.4` Resolution Phase Recovery
- `10.5` Session State Machine
- `10.6` Idempotency Guarantees by Operation

## Allowed Files

- `cognitive_switchyard/orchestrator.py`
- `cognitive_switchyard/planning_runtime.py`
- `cognitive_switchyard/state.py`
- `cognitive_switchyard/models.py`
- `cognitive_switchyard/parsers.py`
- `cognitive_switchyard/pack_loader.py`
- `cognitive_switchyard/hook_runner.py`
- `cognitive_switchyard/config.py`
- `tests/test_planning_runtime.py`
- `tests/test_orchestrator.py`
- `tests/conftest.py`
- `tests/fixtures/planning/**`
- `tests/fixtures/packs/**`

## Tests To Write First

1. `tests/test_planning_runtime.py::test_planner_claims_oldest_intake_item_and_writes_staged_plan`
2. `tests/test_planning_runtime.py::test_planner_output_with_questions_goes_to_review_and_halts_before_resolution`
3. `tests/test_planning_runtime.py::test_planning_disabled_session_promotes_valid_intake_plan_files_to_staging`
4. `tests/test_planning_runtime.py::test_passthrough_resolution_writes_resolution_json_and_moves_plans_to_ready`
5. `tests/test_planning_runtime.py::test_script_or_agent_resolution_rewrites_plan_headers_and_registers_ready_tasks`
6. `tests/test_orchestrator.py::test_start_session_runs_planning_resolution_then_hands_off_to_execution_when_no_review_items_exist`

## Implementation Notes

- Keep packet-`02` `parse_task_plan()` strict for fully resolved ready plans. Add a separate staged-plan metadata representation instead of loosening an already-validated contract.
- The planner and resolver agent boundaries should be explicit injected callables or protocols. Packet-local tests can supply deterministic doubles; real built-in pack/provider wiring stays for later packets.
- Planning output should stay file-based and atomic: `intake/ -> claimed/ -> staging/ | review/`. If a planner run fails before producing a durable plan, the source item must return to `intake/`.
- `passthrough` resolution must still write `resolution.json` and fill explicit `ANTI_AFFINITY: none` plus `EXEC_ORDER` values so execution always consumes canonical ready plans.
- `script` resolution should use the conventional `resolve` hook discovered in packet `04`; keep the runtime contract centered on `resolution.json`, not ad hoc stdout parsing.
- If any plan remains in `review/` or resolution reports unresolved conflicts, stop before execution and surface a structured "needs review" / "needs resolution" result instead of partially entering packet-`06` dispatch.
- Because planning and resolution are introduced here, include their local rerun safety from design sections `10.3` and `10.4` even though packet `07` could not implement those paths earlier.
- Use `reference/work/planning/PLANNER.md`, `reference/work/execution/RESOLVER.md`, and `reference/work/execution/RESOLUTION.md` only as fixture/protocol references. Do not import unrelated operator workflow or release-note behavior into this packet.

## Acceptance Criteria

- Planning-enabled sessions claim intake items atomically and emit deterministic plan files into `staging/` or `review/`, with `claimed/` cleaned up on success.
- Planning-disabled sessions can consume valid intake `.plan.md` files and stage them without inventing new pack schema.
- Resolution produces a valid `resolution.json`, rewrites plan headers to canonical ready-plan metadata, and registers resolved tasks into the state store.
- `passthrough`, `script`, and injected `agent` resolution modes are each covered by packet-local runtime logic without adding a public provider-selection surface.
- Sessions with review-required plans or unresolved conflicts stop before execution with their artifacts preserved for later intervention.
- Sessions with fully resolved plans can hand directly into the existing execution orchestrator without breaking packet-`06`/`07` behavior.
- Re-running planning or resolution after interruption is safe: leftover `claimed/` work returns to `intake/`, partial `resolution.json` is discarded, and complete `staging/` / `review/` artifacts are preserved.

## Validation Focus

- `.venv/bin/python -m pytest tests/test_planning_runtime.py tests/test_orchestrator.py -v`
- `.venv/bin/python -m pytest tests/test_state_store.py tests/test_parsers.py tests/test_pack_loader.py tests/test_hook_runner.py -v`
