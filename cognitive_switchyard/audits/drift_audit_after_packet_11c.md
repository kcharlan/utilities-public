# Drift Audit After Packet 11C

Date: 2026-03-10
Audit label: `drift audit after packet 11C`
Highest validated packet: `11C`
Validated packet count: `15`
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
  - `plans/packet_11c_setup_session_configuration_and_intake_contract_repair.md`
- Relevant design sections already in scope through packet `11C`:
  - `3.2`-`3.6`
  - `4.1`-`4.5`
  - `5.1`-`5.3`
  - `6.1`
  - `6.3.1.1`
  - `6.3.1.4`
  - `6.4`-`6.6`
  - `7.1`-`7.5`
  - `10.1`-`10.7`
  - `11`
- Live code under `cognitive_switchyard/`, `tests/`, `switchyard`, and `audits/`
- Existing audit artifacts affecting this review:
  - `audits/drift_audit_after_packet_11.md`
  - `audits/drift_audit_after_packet_11.json`
  - `audits/drift_audit_after_packet_11a.md`
  - `audits/drift_audit_after_packet_11a.json`
  - `audits/drift_audit_after_packet_11b.md`
  - `audits/drift_audit_after_packet_11b.json`
  - `audits/packet_11c_setup_session_configuration_and_intake_contract_repair_validation.md`
  - `audits/drift_audit_state.json`
  - `audits/full_suite_state.json`

## What Still Aligns

- The validated frontier is still packet `11C`; I did not find packet-`12` HTML, `html_template.py`, React/Tailwind assets, or packet-`13` tooling/docs pulled forward into the live code.
- The earlier backend transport repairs remain in place:
  - packet `11A` live runtime events still flow from the real orchestrator path into the backend transport seam
  - packet `11B` preflight and reconnect-safe monitor snapshot enrichment are still present
  - packet `11C` session runtime overrides plus intake metadata are still present
- The packet ladder still broadly holds:
  - no second orchestrator in the server layer
  - no SPA implementation mixed into the backend modules
  - packet `12` remains the next intended UI packet rather than a mixed backend/frontend packet

## Finding

### 1. High: packet `12` would still have to widen backend/runtime semantics because the Setup View planner-count contract is still missing

Evidence:

- The design requires the planning phase to launch `1-N` planner agents in parallel and the Setup View to expose a real planner-count control (`docs/cognitive_switchyard_design.md:106-110`, `docs/cognitive_switchyard_design.md:922-945`).
- Packet `11C` explicitly positioned packet `12` as UI-only after finishing the setup-side contract, and packet `12` explicitly forbids adding backend/runtime semantics unless they were already required by the accepted transport contract (`plans/packet_11c_setup_session_configuration_and_intake_contract_repair.md:5-20`, `plans/packet_11c_setup_session_configuration_and_intake_contract_repair.md:73-82`, `plans/packet_12_embedded_react_spa_monitor.md:35-41`).
- The live setup/runtime path still does not support planner count end to end:
  - session overrides do not include `planner_count`, and unknown fields are normalized away before storage/serialization in `cognitive_switchyard/models.py:287-318` and `cognitive_switchyard/models.py:431-507`
  - `POST /api/sessions` stores only the recognized override subset, so a client-supplied planner count would be silently dropped, and session serialization exposes no effective planner-count value in `cognitive_switchyard/server.py:324-357` and `cognitive_switchyard/server.py:803-824`
  - planning still runs strictly serially; `run_planning_phase()` loops over intake items one by one and never consults `phases.planning.max_instances` or any session-scoped planner setting in `cognitive_switchyard/planning_runtime.py:91-149`
- The current README also understates the validated frontier and still says FastAPI/REST and WebSocket transport are not implemented (`README.md:150-173`). That is lower-severity documentation drift, but it reinforces that the public-facing tracker story is lagging the actual packet frontier.

Why this matters:

- Packet `12` would otherwise have to choose between two bad options:
  - omit the design-specified planner-count control from the Setup View
  - render a control that the backend/runtime ignores, making it cosmetic
- That is cumulative architectural drift, not a UI implementation detail. The intended path is still "backend/runtime contract first, SPA second," and the planner-count seam is part of that contract.
- The missing work is architecturally unambiguous and stays within the current delivery direction, so `halt` is unnecessary. It is broader than the allowed inline `small` repair budget for this audit because it crosses the packet-`08` planning runtime and the packet-`11C` setup transport seam.

## Repair Packet Created

I inserted a dedicated repair packet immediately after the validated frontier:

- `11D` — `plans/packet_11d_planner_parallelism_and_setup_planner_count_repair.md`

Tracker updates applied:

- Added packet `11D` to `plans/packet_status.md`
- Added packet `11D` to `plans/packet_status.json`
- Updated packet `12` to depend on `11D`, making the repair packet the next actionable packet

Audit scheduler state updated:

- `audits/drift_audit_state.json` now records this audit as the latest cumulative review and marks the next audit due immediately after a validated `11D`

## Additional Observation

### Low: root README status prose is stale

- `README.md:150-173` still describes the repository as validated only through packet `10` and claims FastAPI/REST and WebSocket transport are not implemented.
- This does not change the packet decision for this audit, but it is documentation drift that should be corrected during the next adjacent documentation touch.

## Conclusion

Packet `11C` repaired most of the backend setup contract, but packet `12` is still not truly UI-only because the planner-count control from the design has no real backend/runtime contract behind it yet. The missing work is clear and bounded, so the correct result is `repair_packet`, with packet `11D` inserted before the SPA packet.
