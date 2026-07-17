# Packet 11 - FastAPI REST and WebSocket Backend

## Why This Packet Exists

Packet `10` gives the project a real bootstrap and headless CLI surface, but the validated engine is still only operable from blocking command-line entrypoints. The design's next boundary is a stable backend transport layer that can expose session state, control actions, and live updates to a future UI without mixing in any frontend implementation.

This packet creates that transport seam. It should wrap the already-validated planning, execution, recovery, and verification runtime in a testable FastAPI and WebSocket backend while keeping packet `12`'s embedded SPA entirely out of scope.

## Scope

- Add a `serve` operator path that bootstraps the runtime, finds an available local port, and starts a FastAPI app without hardcoding a single port.
- Introduce a backend app module with a testable app factory rather than embedding route setup directly in the CLI.
- Expose the packet-local REST transport surface needed by the future SPA:
  - packs and pack-detail reads
  - session creation, listing, detail, start, pause, resume, abort, purge, and retry
  - task list/detail/log reads
  - dashboard and DAG reads
  - intake listing plus `open-intake` and `reveal-file`
  - settings read/update
- Add a WebSocket endpoint and connection manager for:
  - full state snapshots
  - task status changes
  - per-slot log streaming
  - progress-detail updates
  - timeout/problem alerts
- Run the existing orchestrator in a background thread or equivalent controller so HTTP and WebSocket handling remain responsive while sessions are active.
- Add the backend-side serialization and query helpers needed to turn SQLite-plus-filesystem state into stable API payloads for packet `12`.

## Non-Goals

- No embedded React SPA, HTML template, Tailwind config, React Flow view, or operator-facing CSS work.
- No redesign of packet `06` through `10` orchestration semantics; the server must call into the existing runtime rather than fork its own control loop.
- No new pack contract, planning semantics, verification semantics, or recovery semantics beyond the transport hooks needed to surface them.
- No browser-specific UX work such as navigation, animations, card layouts, or DAG styling.
- No `GET /` production SPA shell in this packet. Packet `12` owns the operator-facing root document.

## Relevant Design Sections

- `6.1 Technology Stack`
- `6.5 WebSocket Protocol`
- `6.6 REST API Endpoints`
- `7.1 Module Structure`
- `7.3 Orchestrator Loop`
- `7.4 Timeout Model`
- `7.5 WebSocket Manager`
- `10.5 Session State Machine`
- `reference/work/DASHBOARD.md`

## Allowed Files

- `switchyard`
- `README.md`
- `cognitive_switchyard/cli.py`
- `cognitive_switchyard/config.py`
- `cognitive_switchyard/models.py`
- `cognitive_switchyard/orchestrator.py`
- `cognitive_switchyard/state.py`
- `cognitive_switchyard/pack_loader.py`
- `cognitive_switchyard/hook_runner.py`
- `cognitive_switchyard/server.py`
- `tests/test_cli.py`
- `tests/test_server.py`
- `tests/test_state_store.py`
- `tests/fixtures/packs/`
- `tests/fixtures/tasks/`
- `tests/fixtures/workers/`

## Tests To Write First

- `tests/test_server.py::test_serve_command_scans_to_next_free_port_and_starts_app`
- `tests/test_server.py::test_get_packs_and_pack_detail_serialize_runtime_manifests`
- `tests/test_server.py::test_session_dashboard_task_and_dag_endpoints_reflect_live_store_state`
- `tests/test_server.py::test_pause_resume_abort_and_retry_routes_delegate_to_background_session_controller`
- `tests/test_server.py::test_open_intake_and_reveal_file_reject_traversal_outside_session_root`
- `tests/test_server.py::test_websocket_broadcasts_state_updates_alerts_and_slot_scoped_log_lines`

## Implementation Notes

- Keep the server boundary in a dedicated `server.py` module with an app factory so route behavior can be exercised under pytest without booting a real subprocess.
- The existing orchestrator entrypoints are blocking. Packet `11` should introduce a small session-controller layer around them rather than teaching FastAPI handlers to run orchestration inline.
- Prefer deriving API payloads from the validated `StateStore` plus canonical session paths. Do not create a second in-memory source of truth for tasks, worker slots, or session status.
- Add only the state-store query helpers that are required to support the documented transport payloads. If an endpoint needs an aggregate view, make that aggregation explicit and reusable rather than overloading existing packet `03` methods.
- The WebSocket manager should support global state broadcasts plus slot-scoped log subscriptions exactly as the design describes. Keep the subscription model server-side; the UI should not need to filter every log line client-side.
- `open-intake` and `reveal-file` must validate that requested paths stay within the target session directory before invoking `open`, `open -R`, or `xdg-open`.
- Port selection must follow the repo's required free-port scan pattern. The `serve` command's default port is only a preference, not a promise.
- Do not add `html_template.py` in this packet. If the backend needs a root placeholder for tests, keep it minimal and explicitly temporary.

## Acceptance Criteria

- The CLI exposes a `serve` path that starts a FastAPI backend on the first available port at or above the requested default and keeps the process responsive while sessions run.
- The backend exposes the packet-local REST contracts needed for packs, sessions, tasks, dashboard, DAG, intake, purge, and settings workflows using JSON payloads derived from live runtime state.
- Session-control endpoints can create or resume a session and route it into the existing orchestrator runtime on a background thread without blocking request handling.
- The WebSocket endpoint broadcasts `state_update`, `task_status_change`, `progress_detail`, and `alert` messages, and it supports opt-in per-slot `log_line` streaming.
- File-manager helper endpoints reject traversal attempts and only operate on paths within the canonical session directory.
- Packet `06` through `10` behavior is preserved when exercised through the backend rather than the headless CLI.
- No embedded SPA document, React code, or packet `12` visual implementation lands in this packet.

## Validation Focus

- Background-thread safety around start, pause, resume, abort, and retry flows.
- API payload correctness against SQLite-plus-filesystem source state.
- WebSocket broadcast timing and slot-subscription filtering.
- Free-port selection and `serve` CLI wiring.
- Path-containment enforcement for intake/file reveal endpoints.
- Regression coverage for the packet `10` CLI bootstrap surface and the packet `06` through `09` orchestration runtime.
