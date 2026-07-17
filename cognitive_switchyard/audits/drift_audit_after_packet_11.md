# Drift Audit After Packet 11

Date: 2026-03-10
Audit label: `drift audit after packet 11`
Highest validated packet: `11`
Validated packet count: `12`
Overall result: `repair_packet`

## Scope

Reviewed during this audit:

- `README.md`
- `docs/implementation_packet_playbook.md`
- `plans/packet_status.md`
- `plans/packet_status.json`
- Validated packet docs:
  - `plans/packet_00_canonical_contracts_and_scaffold.md`
  - `plans/packet_01_pack_and_session_contract_parsing.md`
  - `plans/packet_02_task_artifact_parsing_and_scheduler_core.md`
  - `plans/packet_03_sqlite_state_store_and_filesystem_projection.md`
  - `plans/packet_04_pack_hook_runner_and_preflight.md`
  - `plans/packet_05_worker_slot_lifecycle_and_timeout_monitoring.md`
  - `plans/packet_06_execution_orchestrator_loop.md`
  - `plans/packet_07_crash_recovery_and_reconciliation.md`
  - `plans/packet_08_planning_and_resolution_runtime.md`
  - `plans/packet_09_verification_and_auto_fix_loop.md`
  - `plans/packet_10_cli_bootstrap_and_built_in_pack_sync.md`
  - `plans/packet_11_fastapi_rest_and_websocket_backend.md`
- Relevant design sections in scope through packet `11`:
  - `3.2`-`3.6`
  - `4.1`-`4.5`
  - `5.1`-`5.3`
  - `6.1`
  - `6.4`-`6.6`
  - `7.1`-`7.5`
  - `9`
  - `10.1`-`10.7`
  - `11`
- Live code under `cognitive_switchyard/`, `tests/`, `switchyard`, and `audits/`
- Existing audit artifacts affecting this review:
  - `audits/drift_audit_after_packet_07.md`
  - `audits/drift_audit_after_packet_07.json`
  - `audits/drift_audit_after_packet_10.md`
  - `audits/drift_audit_after_packet_10.json`
  - `audits/packet_10_cli_bootstrap_and_built_in_pack_sync_validation.md`
  - `audits/packet_11_fastapi_rest_and_websocket_backend_validation.md`

## What Still Aligns

- The validated frontier is still packet `11`; I did not find packet-`12` SPA code, embedded HTML template work, or packet-`13` tooling/docs scope pulled forward.
- Earlier cross-packet contract drift called out after packet `07` is now repaired in the live code:
  - recovery runs before preflight for restartable execution states in `cognitive_switchyard/orchestrator.py:49-92`
  - `session_max` budgeting reuses persisted `started_at` in `cognitive_switchyard/orchestrator.py:107-121`
  - resolution now defaults to `agent` in `cognitive_switchyard/models.py:23-28` and `cognitive_switchyard/pack_loader.py:187-221`
  - configurable status/progress protocol parsing is consumed end-to-end in `cognitive_switchyard/parsers.py:78-213`, `cognitive_switchyard/worker_manager.py:127-192`, and `cognitive_switchyard/recovery.py:42-157`
- Packet boundaries still broadly hold:
  - no packet-`12` HTML/React bundle or `html_template.py`
  - no packet-`13` pack-author/operator tooling
  - packet-`11` remains a backend transport layer rather than a frontend implementation

## Finding

### 1. High: packet-11 transport seam never receives live runtime events from the background orchestrator

Evidence:

- The packet-`11` doc requires the backend to expose a WebSocket transport layer for live state, task-status, log, progress-detail, and alert updates before packet `12` begins.
- The `ConnectionManager` defines the expected packet-`11` broadcast methods in `cognitive_switchyard/server.py:24-80`.
- In live code, those methods are not wired to the running orchestration path:
  - `SessionController._run_session()` just calls `start_session(...)` and publishes one final snapshot after the thread exits in `cognitive_switchyard/server.py:151-169`
  - `SessionController._publish_snapshot()` only calls `broadcast_state()` in `cognitive_switchyard/server.py:163-168`
  - there are no production call sites for `send_log_line()`, `broadcast_task_status_change()`, `broadcast_progress_detail()`, or `broadcast_alert()` outside direct tests (`tests/test_server.py:644-727`)
  - `cognitive_switchyard/orchestrator.py` has no backend event sink parameter; it mutates the store and worker manager only
- Direct probe run during this audit against the real background-session path on 2026-03-10:
  - a two-task session started through `POST /api/sessions/probe/start` transitioned `ready -> active -> done`
  - observed broadcast counts during real execution were:
    - `broadcast_state: 1` only after session completion
    - `send_log_line: 0`
    - `broadcast_task_status_change: 0`
    - `broadcast_progress_detail: 0`
    - `broadcast_alert: 0`

Why this matters:

- Packet `12` is explicitly supposed to consume packet-`11`'s already-stable transport seam. Right now that seam stops at the controller thread boundary.
- The current packet ladder is therefore drifting: the next UI packet would have to add backend runtime semantics that packet `11` was meant to settle first.
- The validated tracker overstates packet `11`'s readiness for packet `12`. REST routes exist, but the live runtime-to-WebSocket coupling that makes the backend a usable monitor transport does not.

Required follow-up:

- Insert an immediate repair packet after `11` that wires live runtime events from the background orchestration path into the existing packet-`11` WebSocket manager without broadening into packet-`12` UI work.
- Strengthen server integration coverage so a real background session, not direct manual calls into `ConnectionManager`, proves the transport seam.

## Repair Packet Created

Because the fix is architecturally unambiguous but broader than the allowed inline `small` repair budget for this audit, I created a dedicated repair packet immediately after the validated frontier:

- `11A` — `plans/packet_11a_live_backend_event_streaming_repair.md`

Tracker updates applied:

- Added packet `11A` to `plans/packet_status.md`
- Added packet `11A` to `plans/packet_status.json`
- Updated packet `12` to depend on `11A` so the repair is the next actionable packet

## Conclusion

This audit found one meaningful cumulative drift: packet `11` established backend route and WebSocket plumbing, but not the live runtime event flow that the packet ladder expects packet `12` to consume. That is not a strategic re-baselining problem, so `halt` is unnecessary. It is also broader than the `small` inline-repair budget for this audit, so I returned `repair_packet` and inserted packet `11A` as the immediate next step.
