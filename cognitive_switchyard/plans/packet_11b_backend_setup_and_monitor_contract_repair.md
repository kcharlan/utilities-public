# Packet 11B - Backend Setup and Monitor Contract Repair

## Why This Packet Exists

Packet `11A` repaired live backend event streaming, but packet `12` is still not truly UI-only. The current backend cannot yet power the design's Setup view preflight flow or a reconnection-safe Monitor snapshot without adding more backend semantics during the SPA packet.

This repair packet keeps packet `12` on its intended boundary by finishing the backend contract it is supposed to consume, without introducing any HTML, React, or other frontend implementation.

## Scope

- Add a session-scoped backend preflight route that reuses the existing packet-`04` executable-bit scan, prerequisite checks, and optional pack `preflight` hook without starting orchestration.
- Expand the backend monitor snapshot contract so `/api/sessions/{id}/dashboard` and packet-`11` `state_update` messages expose the worker-card state that packet `12` needs on first paint and after reconnect:
  - session elapsed time
  - configured idle worker slots
  - active worker phase / phase position
  - latest worker detail text
  - per-worker elapsed time
- Cache or derive the latest worker-card fields from the existing packet-`11A` runtime event stream instead of inventing a second backend polling loop.
- Keep packet-`11`/`11A` message types and control-route shapes stable while enriching the payload fields they already imply.

## Non-Goals

- No embedded SPA, `GET /` HTML shell, `html_template.py`, Tailwind, React, or packet-`12` visual work.
- No new WebSocket message types, no backend-only execution loop, and no redesign of packet-`06` through `11A` orchestration semantics.
- No retention trimming, history rendering, pack-author tooling, or packet-`13` operator/documentation work.
- No broad redesign of planning parallelism or other packet-`08` semantics that are not required to keep packet `12` backend-neutral.

## Relevant Design Sections

- `4.3 Lifecycle Hook Contracts`
- `6.3.1.1 Main Monitor View`
- `6.3.1.4 Setup View`
- `6.5 WebSocket Protocol`
- `6.6 REST API Endpoints`
- `7.3 Orchestrator Loop`
- `7.5 WebSocket Manager`
- `10.5 Session State Machine`

## Allowed Files

- `cognitive_switchyard/server.py`
- `cognitive_switchyard/orchestrator.py`
- `cognitive_switchyard/models.py`
- `tests/test_server.py`
- `tests/test_orchestrator.py`
- `tests/fixtures/workers/**`

## Tests To Write First

- `tests/test_server.py::test_session_preflight_route_reports_permission_and_prerequisite_results_without_starting_execution`
- `tests/test_server.py::test_dashboard_payload_includes_configured_idle_workers_and_latest_runtime_progress_fields`
- `tests/test_server.py::test_state_update_snapshot_after_runtime_events_preserves_worker_card_fields_for_reconnecting_clients`
- `tests/test_orchestrator.py::test_execute_session_runtime_events_are_sufficient_to_reconstruct_worker_card_state_without_changing_outcomes`

## Implementation Notes

- Reuse the existing packet-`04` preflight machinery. The repair should expose that result over REST; it must not duplicate permission scans or prerequisite execution logic in ad hoc route code.
- Keep the snapshot enrichment backward compatible. Add fields to `state_update` / dashboard payloads rather than renaming or splitting existing message types.
- Prefer a narrow session-controller cache keyed by session ID and worker slot for latest phase/detail/elapsed state. Packet `11A` already emits the runtime events needed to keep that cache current.
- Idle worker slots must be present in the snapshot up to the effective worker-slot count for the session so packet `12` can render stable worker cards without guessing from only-active rows.
- Packet `12` should remain able to consume this backend repair without adding another backend packet. If the implementation starts pulling in HTML/template work, the boundary is wrong.

## Acceptance Criteria

- A session created through the backend can run a preflight-only check that returns executable-bit findings, prerequisite results, and optional pack-hook output without changing the session to `running`.
- `/api/sessions/{id}/dashboard` returns a monitor snapshot that includes elapsed session time plus one entry per configured worker slot, including explicit idle slots.
- For active workers, the dashboard/state snapshot includes the latest task ID/title plus phase, phase index/total, detail text, and elapsed runtime derived from the live packet-`11A` runtime stream.
- A client that connects or reconnects mid-session can reconstruct the worker-card state from the latest snapshot without waiting for a new progress line to arrive.
- Existing packet-`11` pause/resume/abort/retry routes and packet-`11A` live event streaming remain unchanged apart from the enriched snapshot data.
- No packet-`12` HTML, React, or frontend asset work lands in this repair packet.

## Validation Focus

- Packet-local server integration coverage for the new preflight route and enriched dashboard/state snapshots.
- Reconnect behavior: connect after runtime events have already been emitted and confirm the first snapshot still contains the latest worker-card fields.
- Regression coverage that packet-`11` control routes and packet-`11A` live event message types still pass unchanged.
