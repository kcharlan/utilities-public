# Packet 06: Execution Orchestrator Loop

## Why This Packet Exists

Packet `05` isolates the long-running worker process lifecycle, but it still does not execute a session. The next boundary is the execution-only orchestrator loop that combines persisted session/task state, scheduler eligibility, pack preflight/isolation hooks, and worker slots into the first end-to-end runtime. This packet intentionally stops at execution: it assumes plans are already resolved and ready, and it does not take on recovery, verification, or UI/API concerns.

## Scope

- Add `cognitive_switchyard.orchestrator` for the execution-phase loop over an already-created session with persisted `ready` tasks.
- Run packet-`04` pack preflight once before dispatch begins and block execution startup if preflight fails.
- Mark the session `running`, poll for idle worker slots, select eligible tasks with the existing scheduler, and dispatch up to `phases.execution.max_workers`.
- Call optional `isolate_start` before worker dispatch and optional `isolate_end` after worker completion, passing the documented positional arguments and final task outcome.
- Use the state store as the only public task/session mutation boundary to project plans between `ready`, `workers/<slot>`, `done`, and `blocked`, and to append ordered session events.
- Handle worker completion, worker timeouts, sidecar-parse failures, isolation-hook failures, and `timeouts.session_max` aborts for the execution loop only.
- Mark the session `completed` when all persisted tasks finish in `done` and no blocked tasks remain.

## Non-Goals

- No crash recovery, reconciliation, orphan cleanup, or restart logic; packet `07` owns all restart semantics.
- No planning/runtime intake claiming, staging, human review, or resolution execution; packet `08` owns those phases.
- No verification or auto-fix loop; packet `09` owns global verification/fixer behavior.
- No REST, WebSocket, SPA, or operator-facing CLI workflow changes.
- No filesystem watcher or background server integration; keep the loop single-session and poll-based.
- No built-in pack installation/bootstrap behavior; packet `10` owns that user-facing startup surface.

## Relevant Design Sections

- `3.4` Execution
- `4.2` pack.yaml Schema
- `4.3` Lifecycle Hook Contracts
- `5.1` Storage Model
- `5.2` File-as-State Mapping
- `7.1` Module Structure
- `7.3` Orchestrator Loop
- `7.4` Timeout Model
- `10.5` Session State Machine
- `10.6` Idempotency Guarantees by Operation

## Allowed Files

- `cognitive_switchyard/orchestrator.py`
- `cognitive_switchyard/state.py`
- `cognitive_switchyard/worker_manager.py`
- `cognitive_switchyard/models.py`
- `cognitive_switchyard/hook_runner.py`
- `cognitive_switchyard/pack_loader.py`
- `cognitive_switchyard/config.py`
- `tests/test_orchestrator.py`
- `tests/conftest.py`
- `tests/fixtures/packs/**`
- `tests/fixtures/orchestrator/**`

## Tests To Write First

1. `tests/test_orchestrator.py::test_start_execution_runs_preflight_before_marking_session_running`
2. `tests/test_orchestrator.py::test_dispatch_respects_dependencies_anti_affinity_and_max_workers`
3. `tests/test_orchestrator.py::test_successful_task_runs_isolation_worker_collection_and_done_projection`
4. `tests/test_orchestrator.py::test_failed_or_timed_out_task_moves_to_blocked_and_calls_isolate_end_with_blocked_status`
5. `tests/test_orchestrator.py::test_session_max_timeout_aborts_active_workers_and_marks_session_aborted`
6. `tests/test_orchestrator.py::test_all_done_session_marks_completed_and_records_ordered_events`

## Implementation Notes

- Assume the session already exists in SQLite and its resolved task plans are already registered in `ready/`. This packet must not invent intake/planning/resolution behavior.
- Run pack preflight exactly once per execution start attempt. If preflight fails, leave the session in `created` and return a structured startup failure instead of partially entering the loop.
- Treat `isolation.type: none` as "use the session root as the workspace and skip isolation hooks." Other isolation types still flow through the packet-`04` hook runner.
- Use `state.project_task()` as the only task-location mutator. Do not add ad hoc filesystem moves in the orchestrator.
- Record session events for dispatch, completion, block/timeout reasons, preflight failures, and session timeout handling so later API/UI packets can consume a stable event stream.
- When a worker fails to produce a valid status sidecar, times out, or an isolation hook fails, move that task to `blocked`, free the slot, and keep evaluating any other still-eligible work. Do not add recovery or retry behavior in this packet.
- Keep blocked-frontier behavior explicit in the orchestrator result object instead of inventing new session states beyond the design doc's current `created` / `running` / `completed` / `aborted` semantics.
- Use `reference/work/execution/WORKER.md` and `reference/work/execution/RESOLUTION.md` only as fixture/protocol references for execution sequencing and progress expectations. Do not import planning/resolution runtime behavior into this packet.

## Acceptance Criteria

- Starting execution on a populated session runs pack preflight first and does not mark the session `running` if preflight fails.
- The orchestrator dispatches only eligible `ready` tasks, respects `DEPENDS_ON`, respects `ANTI_AFFINITY`, and never exceeds `phases.execution.max_workers`.
- Successful tasks flow through optional isolation hooks, worker execution, parsed status collection, and state-store projection into `done/`, with ordered session-event recording.
- Failed, timed-out, or sidecar-invalid tasks are projected to `blocked/`, include recorded failure reasons, and free their worker slots without requiring recovery logic.
- `timeouts.session_max` aborts the session, kills any active workers, and preserves artifacts for debugging.
- Sessions with all tasks completed successfully are marked `completed`; blocked-frontier sessions are surfaced through structured orchestrator results without false completion.
- Packet-local tests pass together with regressions for packets `03`, `04`, and `05`.

## Validation Focus

- `.venv/bin/python -m pytest tests/test_orchestrator.py tests/test_worker_manager.py -v`
- `.venv/bin/python -m pytest tests/test_state_store.py tests/test_scheduler.py tests/test_hook_runner.py -v`
