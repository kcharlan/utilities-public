# Packet 07: Crash Recovery and Reconciliation

## Why This Packet Exists

Packet `06` proves the first execution-only session loop, but it only works from a clean `created` session inside one live process. If the orchestrator dies mid-run, the current code loses worker metadata, leaves `workers/<slot>/` plans stranded, and can drift out of sync with SQLite. The next boundary is execution-phase crash recovery: preserve completed work, revert incomplete work, reconcile the database to the filesystem, and make rerunning the same session safe.

## Scope

- Add an execution-recovery pass that runs before normal dispatch for sessions in `running` or `paused`.
- Persist the minimum per-slot dispatch metadata needed for restart recovery, including the active workspace path and recoverable process identity.
- Scan `workers/<slot>/` for orphaned active plans and classify each one as completed work to preserve or incomplete work to revert.
- Recover completed work by parsing a valid `done` status sidecar, running `isolate_end` with final status `done`, and projecting the task into `done/`.
- Recover incomplete work by terminating any recorded orphaned subprocess, running `isolate_end` with final status `blocked`, and moving the plan back to `ready/` rather than `blocked/`.
- Reconcile SQLite task rows, worker-slot rows, and session status from the filesystem projection so the filesystem remains the source of truth.
- Resume recovered `running` sessions back into the existing execution loop; recover `paused` sessions without dispatching new work.

## Non-Goals

- No planning, `claimed/`, `staging/`, `review/`, or `resolution.json` recovery; packet `08` owns recovery for phases that do not exist yet.
- No verification or auto-fix restart behavior.
- No REST, WebSocket, SPA, or operator-facing pause/resume controls.
- No attempt to resume a task mid-execution inside its previous workspace; interrupted work is always re-dispatched from `ready/`.
- No broad OS process scanning by name or heuristic matching; recovery may only act on explicitly persisted per-session worker metadata.
- No session-history trimming, purge flows, or release-note generation.

## Relevant Design Sections

- `3.4` Execution
- `4.3` Lifecycle Hook Contracts
- `5.1` Storage Model
- `5.2` File-as-State Mapping
- `7.3` Orchestrator Loop
- `7.4` Timeout Model
- `10.1` Recovery Principle
- `10.2` Execution Phase Recovery
- `10.5` Session State Machine
- `10.6` Idempotency Guarantees by Operation
- `10.7` Implementation Requirements for Pack Authors

## Allowed Files

- `cognitive_switchyard/orchestrator.py`
- `cognitive_switchyard/recovery.py`
- `cognitive_switchyard/state.py`
- `cognitive_switchyard/models.py`
- `cognitive_switchyard/worker_manager.py`
- `cognitive_switchyard/hook_runner.py`
- `cognitive_switchyard/config.py`
- `tests/test_recovery.py`
- `tests/test_orchestrator.py`
- `tests/conftest.py`
- `tests/fixtures/recovery/**`
- `tests/fixtures/packs/**`

## Tests To Write First

1. `tests/test_recovery.py::test_recover_done_worker_promotes_task_to_done_and_runs_isolate_end`
2. `tests/test_recovery.py::test_recover_incomplete_worker_returns_task_to_ready_and_clears_slot_projection`
3. `tests/test_recovery.py::test_recover_blocked_or_malformed_sidecar_treats_work_as_incomplete_and_records_warning`
4. `tests/test_recovery.py::test_reconcile_filesystem_resets_task_and_worker_rows_to_match_plan_locations`
5. `tests/test_orchestrator.py::test_execute_session_resumes_running_session_after_recovery_pass`
6. `tests/test_orchestrator.py::test_execute_session_recovers_paused_session_without_dispatching_new_work`

## Implementation Notes

- Keep recovery as a packet-local startup boundary. Do not spread restart-only logic throughout the steady-state polling loop.
- Persist recovery metadata when a task is dispatched, not only in memory. A session-local slot sidecar is preferred over widening unrelated CLI or API contracts.
- Treat execution recovery as binary: completed work is preserved, incomplete work is reverted. Infrastructure interruption must not move a task to `blocked/`.
- If `isolate_end` fails while cleaning up incomplete work, forcibly remove only session-owned workspace paths, append a warning event, and still return the plan to `ready/` so restart stays unblockable.
- Rebuild worker-slot rows from recovered filesystem state instead of trusting packet-`06` in-memory slot ownership.
- `running` sessions should recover and then continue dispatch automatically. `paused` sessions should recover into a stable paused state and return control without starting new workers.
- Packet `06` currently rejects non-`created` sessions. Packet `07` must narrow that guard so restart is supported only for the documented `running` and `paused` states, while keeping other session states explicit errors.
- Use `reference/work/orchestrate.sh` crash-recovery behavior only as sequencing guidance. Keep the Python implementation bounded to the current execution-only architecture.

## Acceptance Criteria

- A previously interrupted session with tasks stranded in `workers/<slot>/` can be restarted without manual cleanup.
- Tasks with a valid `STATUS: done` sidecar are finalized into `done/` exactly once, including `isolate_end` handoff and worker-slot cleanup.
- Tasks without a valid `done` result are cleaned up and moved back to `ready/`, never misclassified as task-level `blocked`.
- Recovery terminates recorded orphaned worker processes with the documented TERM-then-KILL sequence before redispatching their tasks.
- SQLite task rows, worker-slot rows, and session status are reconciled to the filesystem projection after recovery.
- Restarting a `running` session resumes execution; restarting a `paused` session does not dispatch new work until a later explicit resume path exists.
- Packet-local tests pass together with regressions for packets `03`, `05`, and `06`.

## Validation Focus

- `.venv/bin/python -m pytest tests/test_recovery.py tests/test_orchestrator.py -v`
- `.venv/bin/python -m pytest tests/test_state_store.py tests/test_worker_manager.py tests/test_hook_runner.py -v`
