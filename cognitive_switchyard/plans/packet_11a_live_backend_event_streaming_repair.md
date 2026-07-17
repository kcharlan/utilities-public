# Packet 11A - Live Backend Event Streaming Repair

## Why This Packet Exists

Packet `11` introduced the FastAPI and WebSocket backend surface, but the live server still stops at a thread boundary: real background sessions mutate SQLite and worker logs without forwarding task-state, progress-detail, log-line, or alert events into the backend transport seam.

Packet `12` depends on packet `11` already exposing those live runtime signals. Without this repair, the SPA packet would be forced to add backend semantics that packet `11` was supposed to stabilize first.

## Scope

- Wire the packet-`11` background session controller to the live execution runtime so real background sessions emit backend events while they are running, not only after completion.
- Forward runtime-originated WebSocket messages for the existing packet-`11` contract:
  - `state_update`
  - `task_status_change`
  - `progress_detail`
  - opt-in per-slot `log_line`
  - timeout/problem `alert`
- Keep the existing packet-`11` REST routes and message-type names stable while repairing the missing live event flow.
- Add integration coverage that starts a real background session through the backend and proves the WebSocket stream is driven by runtime execution rather than by direct test calls into `ConnectionManager`.

## Non-Goals

- No embedded SPA, `GET /` HTML shell, Tailwind setup, React code, or any packet-`12` visual work.
- No new REST endpoints, no new WebSocket message types, and no redesign of the packet-`11` payload contract beyond fields already implied by that packet's accepted transport surface.
- No change to planning, resolution, execution, verification, or auto-fix semantics beyond surfacing their existing runtime transitions to the backend transport layer.
- No pack-author tooling, built-in pack catalog expansion, or packet-`13` operator/documentation work.

## Relevant Design Sections

- `6.5 WebSocket Protocol`
- `6.6 REST API Endpoints`
- `7.3 Orchestrator Loop`
- `7.4 Timeout Model`
- `7.5 WebSocket Manager`
- `10.5 Session State Machine`
- `reference/work/DASHBOARD.md`

## Allowed Files

- `cognitive_switchyard/server.py`
- `cognitive_switchyard/orchestrator.py`
- `cognitive_switchyard/worker_manager.py`
- `cognitive_switchyard/models.py`
- `tests/test_server.py`
- `tests/test_orchestrator.py`
- `tests/fixtures/workers/**`

## Tests To Write First

- `tests/test_server.py::test_background_session_websocket_streams_runtime_task_status_changes_before_completion`
- `tests/test_server.py::test_background_session_websocket_streams_subscribed_log_lines_and_progress_detail_from_real_worker_output`
- `tests/test_server.py::test_background_session_websocket_emits_timeout_or_problem_alerts_from_runtime_polling`
- `tests/test_orchestrator.py::test_execute_session_can_publish_backend_runtime_events_without_changing_task_outcomes`

## Implementation Notes

- Do not add a second execution loop in `server.py`. The repair should expose the already-validated runtime's events, not fork backend-only orchestration behavior.
- Prefer a narrow event-callback or sink interface from the execution runtime into the backend controller over ad hoc polling of SQLite and worker logs from FastAPI routes.
- Keep `log_line` streaming slot-scoped and opt-in. The backend should not broadcast every worker log line to every client.
- Emit state snapshots after the underlying store mutation that makes the snapshot true.
- Treat timeout/problem alerts as packet-`11` runtime signals, not synthetic test-only broadcasts.

## Acceptance Criteria

- Starting a real session through the packet-`11` REST backend emits live `state_update` traffic during execution, not only one final snapshot after the background thread exits.
- Real task dispatch/completion/failure transitions emit `task_status_change` messages from the runtime path.
- When a client subscribes to a worker slot, real worker stdout produces `log_line` messages and `Detail:` progress markers produce `progress_detail` messages without direct test calls into `ConnectionManager`.
- Runtime timeout/problem conditions emit `alert` messages from the live execution path using the existing packet-`11` WebSocket contract.
- Packet-`11` pause/resume/abort behavior and REST route shapes remain unchanged after the repair.
- No packet-`12` HTML, React, or frontend asset work lands in this repair packet.

## Validation Focus

- Integration coverage for live background-session WebSocket traffic rather than isolated connection-manager method calls.
- Correct slot-subscription filtering for `log_line` streaming.
- No regression in packet-`11` REST control flows or packet-`06` through `09` orchestrator behavior.
- Clear separation between runtime event emission and future packet-`12` UI rendering concerns.
