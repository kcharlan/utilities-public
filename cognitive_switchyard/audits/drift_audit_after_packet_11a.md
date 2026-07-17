# Drift Audit After Packet 11A

Date: 2026-03-10
Audit label: `drift audit after packet 11A`
Highest validated packet: `11A`
Validated packet count: `13`
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
  - `plans/packet_11a_live_backend_event_streaming_repair.md`
- Relevant design sections already in scope through packet `11A`:
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
  - `audits/drift_audit_after_packet_10.md`
  - `audits/drift_audit_after_packet_10.json`
  - `audits/drift_audit_after_packet_11.md`
  - `audits/drift_audit_after_packet_11.json`
  - `audits/packet_11_fastapi_rest_and_websocket_backend_validation.md`
  - `audits/packet_11a_live_backend_event_streaming_repair_validation.md`
  - `audits/drift_audit_state.json`
  - `audits/full_suite_state.json`

## What Still Aligns

- The validated frontier is still packet `11A`; I did not find packet-`12` HTML, `html_template.py`, React/Tailwind assets, or packet-`13` pack-author/operator tooling pulled forward into the live code.
- The packet-`11`/`11A` backend remains transport-only rather than a second orchestrator: the live runtime still flows through `start_session(...)` with packet-`11A` runtime events coming from the real execution loop (`cognitive_switchyard/server.py:157-168`, `cognitive_switchyard/orchestrator.py:1183-1289`).
- The earlier packet-`11` live-event-streaming drift is repaired: real background sessions now emit runtime `task_status_change`, `progress_detail`, `log_line`, and `alert` traffic before completion (`tests/test_server.py:808-966`).
- Packet boundaries still broadly hold:
  - no packet-`12` root SPA shell
  - no `html_template.py`
  - no packet-`13` pack scaffolding / validation / operator documentation surfaces

## Finding

### 1. High: packet `12` would still have to widen backend semantics because packet `11`/`11A` do not yet provide the setup-side preflight contract or a reconnection-safe monitor snapshot

Evidence:

- Packet `12` is explicitly supposed to stay UI-only and consume the existing backend contract. Its non-goals forbid adding new backend semantics unless packet `11` is still missing fields it was supposed to stabilize (`plans/packet_12_embedded_react_spa_monitor.md:35-41`), and its acceptance criteria require the Setup view to show preflight results plus the Monitor view to render worker cards from backend data (`plans/packet_12_embedded_react_spa_monitor.md:83-90`).
- The design's Setup view requires backend-visible preflight checks and session-start gating before UI start (`docs/cognitive_switchyard_design.md:928-945`).
- The design's `state_update` snapshot contract includes reconnect-safe session/worker fields that the worker cards need on first paint: elapsed session time, explicit idle slots, phase, phase position, detail text, and worker elapsed time (`docs/cognitive_switchyard_design.md:991-1004`).
- The live backend cannot currently supply that setup/monitor contract:
  - session creation accepts only `id`, `name`, and `pack`; it does not expose any preflight route or other setup-side transport for packet `12` to call before start (`cognitive_switchyard/server.py:248-276`)
  - `SessionController.create_session(...)` and `_run_session()` do not add any setup/preflight backend seam; `_run_session()` goes straight into `start_session(...)` with hardcoded `poll_interval=0.05` (`cognitive_switchyard/server.py:103-109`, `cognitive_switchyard/server.py:157-167`)
  - `build_dashboard_payload(...)` only serializes slots already present in `worker_slots` and includes only `slot`, `status`, `task_id`, and `task_title`; it omits session elapsed, idle placeholders up to the configured worker count, and the latest phase/detail/elapsed worker fields (`cognitive_switchyard/server.py:469-502`)
  - the packet-`11` server test suite currently locks in that thinner dashboard payload shape (`tests/test_server.py:520-546`)
- The current tracker overstates the readiness of the next packet. `plans/packet_status.md` says packet `12` is the next horizon "without widening backend scope," but the live backend still lacks the setup/monitor transport needed to keep that statement true.

Why this matters:

- The next packet would otherwise have to add exactly the kind of backend work the playbook separates out of UI packets: setup preflight transport and monitor-state enrichment.
- That is cumulative drift, not a packet-`12` implementation detail. The delivery path is no longer "backend stable, UI next"; it is "UI next, but only after another backend repair."
- Because the missing work is backend-only and architecturally unambiguous, this does not require a strategic `halt`, but it is broader than the allowed inline `small` repair budget for this audit.

## Repair Packet Created

I inserted a dedicated repair packet immediately after the validated frontier:

- `11B` — `plans/packet_11b_backend_setup_and_monitor_contract_repair.md`

Tracker updates applied:

- Added packet `11B` to `plans/packet_status.md`
- Added packet `11B` to `plans/packet_status.json`
- Updated packet `12` to depend on `11B`, making the repair packet the next actionable packet

Audit scheduler state updated:

- `audits/drift_audit_state.json` now records this audit as the latest cumulative review and marks the next audit due immediately after a validated `11B`

## Conclusion

Packet `11A` repaired live runtime event streaming, but the backend is still short of the setup/monitor transport contract that packet `12` is supposed to consume without backend rework. The missing pieces are architecturally clear and backend-only, so `halt` is unnecessary. They are also broader than the allowed inline repair budget for this audit, so the correct result is `repair_packet`, with packet `11B` inserted before the SPA packet.
