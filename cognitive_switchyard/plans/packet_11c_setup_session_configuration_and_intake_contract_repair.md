# Packet 11C - Setup Session Configuration and Intake Contract Repair

## Why This Packet Exists

Packet `11B` repaired backend preflight and monitor snapshots, but packet `12` is still not truly UI-only. The live backend can create sessions only from `{id, name, pack}`, derives runtime behavior directly from pack defaults, and exposes only a thin intake listing. The design's Setup View requires a richer setup-side contract: session-scoped configuration, effective runtime settings, and intake metadata/locked-state information before the UI lands.

Without this repair, packet `12` would have to add backend semantics or ship Setup View controls that are only cosmetic. This packet finishes the backend setup contract so the SPA can remain a consumer of an already-settled transport surface.

## Scope

- Add typed session-configuration overrides persisted through the existing `sessions.config_json` field and expose them through backend session create/detail/list payloads.
- Define an effective session-runtime config that merges global defaults, pack defaults/limits, and stored session overrides for the fields the validated runtime already knows how to consume.
- Route the effective worker-slot count, verification interval, timeout values, auto-fix enable/max-attempts, poll interval, and custom environment variables into the existing execution/verification runtime instead of hard-coding pack defaults everywhere.
- Extend the backend intake-list payload to include the metadata the Setup View needs to render a real file list:
  - filename / relative path
  - file size
  - detected timestamp
  - whether the session is locked for intake
  - whether an intake file is outside the current session snapshot
- Keep packet-`11`/`11A`/`11B` REST and WebSocket route shapes stable except for additive payload enrichment needed by packet `12`.

## Non-Goals

- No embedded HTML, React, Tailwind, or other packet-`12` frontend work.
- No new pack-manifest schema or pack-author tooling changes.
- No redesign of the planning/runtime architecture beyond wiring session configuration into the already-validated runtime seams.
- No release-note generation, history redesign, retention-policy work, or packet-`13` operator/documentation scope.

## Relevant Design Sections

- `3.2` Planning (optional)
- `3.4` Execution
- `3.5` Verification (optional)
- `3.6` Auto-Fix (optional)
- `6.3.1.4` Setup View
- `6.5` WebSocket Protocol
- `6.6` REST API Endpoints
- `7.3` Orchestrator Loop
- `7.4` Timeout Model
- `10.5` Session State Machine
- `10.6` Idempotency Guarantees by Operation

## Allowed Files

- `cognitive_switchyard/server.py`
- `cognitive_switchyard/orchestrator.py`
- `cognitive_switchyard/state.py`
- `cognitive_switchyard/models.py`
- `cognitive_switchyard/worker_manager.py`
- `tests/test_server.py`
- `tests/test_orchestrator.py`
- `tests/test_state_store.py`
- `tests/test_worker_manager.py`

## Tests To Write First

- `tests/test_state_store.py::test_session_config_json_round_trips_through_session_records`
- `tests/test_server.py::test_create_session_accepts_session_overrides_and_returns_effective_runtime_config`
- `tests/test_server.py::test_intake_listing_includes_file_metadata_and_locked_state_for_setup_view`
- `tests/test_server.py::test_dashboard_uses_effective_session_worker_count_not_pack_max_workers`
- `tests/test_orchestrator.py::test_execute_session_uses_session_runtime_overrides_for_worker_count_verification_interval_and_timeouts`
- `tests/test_orchestrator.py::test_session_custom_environment_overrides_reach_worker_and_verification_commands`

## Implementation Notes

- Reuse `sessions.config_json`; do not spread one-off override columns across the schema.
- Keep a clear distinction between stored overrides and effective config. Store only the operator-selected overrides; derive the effective values when serializing or starting a session.
- Do not mutate `PackManifest` in place to represent session overrides. Use explicit effective-config helpers so the pack contract remains canonical and reusable.
- The effective worker count must drive both runtime dispatch and dashboard/state snapshots; packet `11B`'s "configured idle workers" contract should now mean the session's effective worker-slot count, not only the pack default.
- Intake metadata should stay filesystem-derived and session-root-contained. Do not add file watching or a new persistence layer just to support detected time / locked-state rendering.
- When no session overrides are provided, the runtime behavior must remain identical to the currently validated packet-`11B` path.

- Packet `12` should be able to consume this repair without adding another backend packet. If implementation starts drifting into HTML/template work, the boundary is wrong.

## Acceptance Criteria

- Backend session create/detail/list payloads include stored setup overrides plus the effective runtime config needed by packet `12` Setup View.
- The existing runtime consumes effective session overrides for worker count, verification interval, timeout values, auto-fix enable/max-attempts, poll interval, and custom environment variables without regressing pack-default behavior.
- `/api/sessions/{id}/dashboard` and `state_update` snapshots use the effective session worker-slot count, including explicit idle slots up to that count.
- `/api/sessions/{id}/intake` returns setup-view-ready file metadata plus session-lock / in-snapshot information without broadening into UI logic.
- Packet `11` through `11B` control routes and runtime event message types remain stable apart from additive session/setup payload enrichment.
- No packet-`12` HTML, React, or frontend assets land in this repair packet.

## Validation Focus

- `.venv/bin/python -m pytest tests/test_server.py tests/test_orchestrator.py -q`
- `.venv/bin/python -m pytest tests/test_state_store.py tests/test_worker_manager.py -q`
