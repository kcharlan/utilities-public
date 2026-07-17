# Packet 03: SQLite State Store and Filesystem Projection

## Why This Packet Exists

Packets `00` through `02` froze the canonical contracts and implemented the pure parsing and scheduler inputs. The next dependency for any real runtime work is durable session/task state that survives process restarts and mirrors the on-disk task layout. This packet creates that persistence boundary before any subprocess, timeout, or orchestrator-loop behavior exists.

## Scope

- Add the first `cognitive_switchyard.state` module with idempotent SQLite schema initialization at the canonical runtime database path.
- Introduce typed persistence records for sessions, tasks, worker slots, and session events.
- Materialize canonical session directory trees under `~/.cognitive_switchyard/sessions/<session-id>/` and expose helper paths for session-local artifacts such as `resolution.json`, `logs/session.log`, `logs/verify.log`, and `logs/workers/<slot>.log`.
- Store parsed task-plan scheduler metadata (`task_id`, `title`, `depends_on`, `anti_affinity`, `exec_order`, `full_test_after`) in SQLite.
- Add filesystem-projection helpers that move plan files between canonical state directories and keep mirrored task status / worker-slot fields in SQLite consistent with the plan file location.
- Add scheduler-facing query helpers that return ready/active/done task views from persisted state without introducing dispatch logic.

## Non-Goals

- No orchestrator loop, file watcher, REST API, WebSocket, or UI work.
- No subprocess execution, hook invocation, timeout handling, or worker lifecycle management.
- No crash recovery, reconciliation, or orphan cleanup; packet `07` owns restart semantics.
- No planner or resolver runtime behavior; packet `08` owns moving real intake/staging batches through those phases.
- No session trimming, `summary.json`, or retention-policy behavior; those depend on successful end-to-end execution and belong later.

## Relevant Design Sections

- `5.1 Storage Model`
- `5.2 File-as-State Mapping`
- `5.3 Constraint Graph Format`
- `7.1 Module Structure`

## Allowed Files

- `cognitive_switchyard/state.py`
- `cognitive_switchyard/models.py`
- `cognitive_switchyard/config.py`
- `cognitive_switchyard/__init__.py`
- `tests/test_state_store.py`
- `tests/test_config.py`
- `tests/conftest.py`
- `tests/fixtures/state/**`

## Tests To Write First

- `tests/test_state_store.py::test_initialize_state_store_is_idempotent`
- `tests/test_state_store.py::test_create_session_materializes_canonical_session_layout`
- `tests/test_state_store.py::test_register_task_plan_persists_scheduler_fields`
- `tests/test_state_store.py::test_project_task_between_ready_worker_done_and_blocked_states`
- `tests/test_state_store.py::test_append_and_list_session_events_in_timestamp_order`

## Implementation Notes

- Preserve the canonical packet-`00` contracts only. Any design-doc references to `switchyard/` or `~/.switchyard` are legacy names and must not appear in code, tests, or diagnostics.
- Keep the schema minimal and queryable: `sessions`, `tasks`, `worker_slots`, and `events` are enough for this packet.
- The filesystem is the source of truth for task state. Public state-layer write APIs should move the plan artifact into its target directory and update the mirrored SQLite row as one repository-facing operation; do not add a DB-only status mutator that can drift away from the file location.
- Treat `workers/<slot>/` as the active-state directory. Packet `03` only needs to track the assigned worker-slot number and the task's projected location there; subprocess metadata belongs to packet `05`.
- Reuse the packet-`02` `TaskPlan` / scheduler dataclasses where possible. Add new state-record types only for persistence fields that the existing parser/scheduler models do not carry.
- Reserve helper paths for `resolution.json` and log files now so later packets do not invent alternate locations, but do not implement planner/resolver execution, verification logs, or trimming behavior in this packet.
- Use deterministic timestamp/ID injection points in tests instead of wall-clock sleeps.

## Acceptance Criteria

- Initializing the state store repeatedly does not fail, duplicate schema objects, or alter the canonical session-subdirectory contract.
- Creating a session produces both a SQLite session row and the canonical per-session directory layout rooted at `~/.cognitive_switchyard/sessions/<session-id>/`.
- Persisted tasks retain their scheduler fields and can be queried back as scheduler-ready views for later dispatch code.
- A task plan can be projected between `ready`, `workers/<slot>`, `done`, and `blocked`, with SQLite status and worker-slot fields staying consistent with the plan file location.
- Session events can be appended and queried back in chronological order.
- Packet-local tests pass together with packet `02` regression coverage for parsers and scheduler behavior.

## Validation Focus

- `.venv/bin/python -m pytest tests/test_state_store.py -v`
- `.venv/bin/python -m pytest tests/test_config.py tests/test_parsers.py tests/test_scheduler.py -v`
