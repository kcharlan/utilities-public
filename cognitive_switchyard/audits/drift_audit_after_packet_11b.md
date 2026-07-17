# Drift Audit After Packet 11B

Date: 2026-03-10
Audit label: `drift audit after packet 11B`
Highest validated packet: `11B`
Validated packet count: `14`
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
  - `plans/packet_11b_backend_setup_and_monitor_contract_repair.md`
- Relevant design sections in scope through packet `11B`:
  - `3.2`
  - `3.4`-`3.6`
  - `4.3`
  - `5.1`-`5.3`
  - `6.3.1.1`
  - `6.3.1.4`
  - `6.5`
  - `6.6`
  - `7.1`-`7.5`
  - `10.5`-`10.7`
- Live code under `cognitive_switchyard/`, `tests/`, `switchyard`, and `audits/`
- Existing audit artifacts affecting this review:
  - `audits/drift_audit_after_packet_11.md`
  - `audits/drift_audit_after_packet_11.json`
  - `audits/drift_audit_after_packet_11a.md`
  - `audits/drift_audit_after_packet_11a.json`
  - `audits/packet_11b_backend_setup_and_monitor_contract_repair_validation.md`
  - `audits/drift_audit_state.json`

## What Still Aligns

- The validated frontier is still packet `11B`; I did not find packet-`12` HTML, `html_template.py`, React/Tailwind assets, or packet-`13` tooling/docs pulled forward into the live code.
- The packet-`11`/`11A`/`11B` backend remains transport-first rather than a second orchestrator:
  - live background execution still flows through `start_session(...)`
  - live task/log/progress/alert messages still originate from the real runtime event sink
  - reconnect-safe worker-card state is still derived from runtime events rather than a second polling loop
- The packet-`11B` repair itself is present in the live code:
  - session-scoped preflight route in `cognitive_switchyard/server.py`
  - elapsed/session snapshot enrichment in `cognitive_switchyard/server.py`
  - reconnect-safe worker-card cache in `cognitive_switchyard/server.py` and `cognitive_switchyard/models.py`
- Packet boundaries still broadly hold:
  - no packet-`12` root SPA shell
  - no `html_template.py`
  - no packet-`13` pack-author/operator tooling surface

## Finding

### 1. High: packet `12` would still have to widen backend semantics because the Setup View contract remains incomplete after packet `11B`

Evidence:

- Packet `12` is still supposed to stay UI-only. Its non-goals explicitly forbid adding new REST/WebSocket/backend semantics unless packet `11` is still missing transport fields it was supposed to stabilize (`plans/packet_12_embedded_react_spa_monitor.md`).
- The design's Setup View requires backend-visible session setup data beyond pack selection and preflight:
  - planner / worker / verification controls
  - advanced runtime overrides
  - intake-file metadata and locked-session behavior
  - `open-intake` / reveal flows
  (`docs/cognitive_switchyard_design.md:922-945`)
- The live backend still exposes only a thin session/setup contract:
  - session creation accepts only `id`, `name`, and `pack` in `cognitive_switchyard/server.py:313-327`
  - `SessionController.create_session(...)` persists only those three fields plus timestamps in `cognitive_switchyard/server.py:116-122`
  - session serialization omits `config_json` or any effective runtime config in `cognitive_switchyard/server.py:739-757`
  - the intake-list route returns only `path` and `is_dir` in `cognitive_switchyard/server.py:446-458`, not file size, detected time, or locked/in-snapshot metadata for post-start rendering
- The existing runtime still derives execution behavior from pack defaults rather than session-scoped setup state:
  - dashboard worker cards always size themselves from `pack_manifest.phases.execution.max_workers` in `cognitive_switchyard/server.py:557-619`
  - execution dispatch also uses `pack_manifest.phases.execution.max_workers` directly in `cognitive_switchyard/orchestrator.py:224-239`
  - verification cadence and session timeout still come straight from `pack_manifest` in `cognitive_switchyard/orchestrator.py:113-126` and `cognitive_switchyard/orchestrator.py:164-190`
  - `sessions.config_json` exists in the persistence layer, but the live backend/runtime does not surface or consume it beyond storage plumbing in `cognitive_switchyard/state.py:90-131`
- The tracker had smaller stale-state drift too:
  - `plans/packet_status.md` still said the repository had packets `00` through `11A` validated even though `11B` was already validated
  - the "docs beyond the validated frontier" list still included `11B`, which was no longer beyond the frontier

Why this matters:

- Packet `11B` repaired preflight and monitor snapshots, but packet `12` would still need backend work to render a real Setup View rather than a partially cosmetic one.
- That is cumulative architecture drift, not a UI implementation detail. The packet ladder is still not "backend stable, SPA next"; it is "SPA next, but only after one more backend repair."
- The missing work is architecturally unambiguous and stays within the existing delivery direction, so `halt` is unnecessary. It is also broader than the allowed inline `small` repair budget for this audit.

## Repair Packet Created

I inserted a dedicated repair packet immediately after the validated frontier:

- `11C` — `plans/packet_11c_setup_session_configuration_and_intake_contract_repair.md`

Tracker updates applied:

- Added packet `11C` to `plans/packet_status.md`
- Added packet `11C` to `plans/packet_status.json`
- Updated packet `12` to depend on `11C`
- Repaired stale packet-status prose so the validated frontier and next horizon match the live repository state

Audit scheduler state updated:

- `audits/drift_audit_state.json` now records this audit as the latest cumulative review and marks the next audit due immediately after a validated `11C`

## Conclusion

Packet `11B` completed the backend preflight and monitor repair, but the backend still does not provide the full setup-side session contract that packet `12` is supposed to consume without widening backend scope. Because the missing work is clear and bounded to the existing architecture, the correct result is `repair_packet`, with packet `11C` inserted before the SPA packet.
