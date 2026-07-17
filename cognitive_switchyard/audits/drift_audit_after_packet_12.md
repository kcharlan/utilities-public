# Drift Audit After Packet 12

Date: 2026-03-10
Audit label: `drift audit after packet 12`
Highest validated packet: `12`
Validated packet count: `17`
Overall result: `repair_packet`

## Scope

Reviewed during this audit:

- `README.md`
- `docs/implementation_packet_playbook.md`
- `plans/packet_status.md`
- `plans/packet_status.json`
- Validated packet docs `plans/packet_00_canonical_contracts_and_scaffold.md` through `plans/packet_12_embedded_react_spa_monitor.md`
- Relevant design sections already in scope through packet `12`, especially:
  - `3.2`-`3.6`
  - `4.1`-`4.5`
  - `5.1`-`5.3`
  - `6.1`-`6.6`
  - `7.1`-`7.5`
  - `10.1`-`10.7`
  - `11`
- Live code under `cognitive_switchyard/` and `tests/`
- Existing audit artifacts affecting this review:
  - `audits/drift_audit_after_packet_11.md`
  - `audits/drift_audit_after_packet_11a.md`
  - `audits/drift_audit_after_packet_11b.md`
  - `audits/drift_audit_after_packet_11c.md`
  - `audits/drift_audit_after_packet_11d.md`
  - `audits/packet_12_embedded_react_spa_monitor_validation.md`
  - `audits/drift_audit_state.json`
  - `audits/full_suite_state.json`

## What Still Aligns

- The validated frontier is still packet `12`; I did not find packet-`13` pack-tooling, pack-init/validate commands, or operator-documentation scope pulled forward into the live code.
- The canonical packet-`00` contract is still intact in the live runtime:
  - package name `cognitive_switchyard`
  - repo launcher `switchyard`
  - runtime home `~/.cognitive_switchyard`
  - bootstrap venv `~/.cognitive_switchyard_venv`
- The packet-`11A` through `11D` repair chain remains in place:
  - live runtime events still feed the packet-`11` backend transport seam
  - reconnect-safe monitor snapshots and setup preflight remain backend-owned
  - session overrides plus planner-count parallelism still flow end-to-end into setup/runtime behavior
- Packet `12` remains a single embedded HTML/React document over the packet-`11` transport seam rather than an npm frontend or a second backend orchestration path.
- `plans/packet_status.md` and `plans/packet_status.json` correctly identified packet `12` as the highest validated frontier before this audit; no tracker downgrade was needed.

## Finding

### 1. High: the design-required successful-session summary/trim contract is still missing, so packet `12` history behavior is built on the wrong storage model

Evidence:

- The design requires successful sessions to emit `summary.json`, trim down to minimal retained artifacts, and let History read its drill-down data from that summary rather than from live task trees:
  - `docs/cognitive_switchyard_design.md:396-412`
  - `docs/cognitive_switchyard_design.md:947-955`
  - `docs/cognitive_switchyard_design.md:961-964`
- Packet `03` explicitly deferred summary/trimming work for a later packet, but no validated packet through `12` ever picked that runtime contract up:
  - `plans/packet_03_sqlite_state_store_and_filesystem_projection.md:22`
  - `plans/packet_03_sqlite_state_store_and_filesystem_projection.md:57`
- The live completion path still marks the session `completed` and returns immediately, with no summary emission or trim step:
  - `cognitive_switchyard/orchestrator.py:213-230`
- The runtime path model still has no canonical summary artifact or trim helper at the state/config boundary:
  - `cognitive_switchyard/config.py:33-49`
  - no `summary.json` references under `cognitive_switchyard/`
- The packet-`12` server/bootstrap path and History UI still assume completed sessions keep their live session/task trees:
  - server root bootstrap serializes sessions directly from SQLite and only distinguishes active bootstrap state, not trimmed history summaries (`cognitive_switchyard/server.py:883-913`)
  - History rows open a completed session back into the Monitor path (`cognitive_switchyard/html_template.py:1236-1241`)
  - the History view itself is just a list over live session rows plus purge buttons, with no summary-backed final-state rendering (`cognitive_switchyard/html_template.py:2014-2057`)

Why this matters:

- This is no longer a packet-local omission. The current path diverges from the intended delivery system's storage contract:
  - successful sessions remain full task-artifact trees until purge/retention
  - packet-`12` History behavior depends on artifacts the design says should be trimmed away at completion
- Packet `13` is about built-in packs, pack tooling, and operator docs. It is not the right place to redefine or backfill successful-session storage semantics.
- The packet-`11D` retention repair is only partially aligned while successful sessions still skip the summary-plus-trim step the Settings/History design assumes.

## Repair Packet Created

I inserted a dedicated repair packet immediately after the validated frontier:

- `12A` — `plans/packet_12a_history_summary_and_successful_session_trim_repair.md`

Tracker updates applied:

- Added packet `12A` to `plans/packet_status.md`
- Added packet `12A` to `plans/packet_status.json`
- Updated packet `13` to depend on `12A`, making the repair packet the next actionable packet

Audit scheduler state updated:

- `audits/drift_audit_state.json` now records this audit as the latest cumulative review and marks the next audit due immediately after a validated `12A`

## Additional Observation

### Low: root README status prose is still stale

- `README.md:154-173` still says the repository is only validated through packet `10` and still claims FastAPI/REST, WebSocket transport, and the embedded SPA are not implemented.
- This does not change the packet decision for this audit, but it remains documentation drift adjacent to the validated frontier.

## Conclusion

Packet `12` completed the SPA surface, but the design-required successful-session history contract is still missing from the runtime. That leaves the current History flow coupled to untrimmed live artifacts and pushes a core storage semantic into a later phase where it does not belong. The repair is architecturally unambiguous but broader than the allowed inline `small` repair budget for this audit, so the correct result is `repair_packet`, with packet `12A` inserted before packet `13`.
