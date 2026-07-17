# Drift Audit After Packet 11D

Date: 2026-03-10
Audit label: `drift audit after packet 11D`
Highest validated packet: `11D`
Validated packet count: `16`
Overall result: `repair_now`

## Scope

Reviewed during this audit:

- `README.md`
- `docs/implementation_packet_playbook.md`
- `plans/packet_status.md`
- `plans/packet_status.json`
- Validated packet docs `plans/packet_00_canonical_contracts_and_scaffold.md` through `plans/packet_11d_planner_parallelism_and_setup_planner_count_repair.md`
- `plans/packet_12_embedded_react_spa_monitor.md` as the next packet boundary
- Relevant design sections already in scope through packet `11D`, especially:
  - `3.2`-`3.6`
  - `6.3.1.4`-`6.3.1.6`
  - `6.5`-`6.6`
  - `7.3`-`7.5`
  - `10.3`-`10.7`
- Live code under `cognitive_switchyard/` and `tests/`
- Existing audit artifacts affecting this review:
  - `audits/drift_audit_after_packet_11.md`
  - `audits/drift_audit_after_packet_11a.md`
  - `audits/drift_audit_after_packet_11b.md`
  - `audits/drift_audit_after_packet_11c.md`
  - `audits/drift_audit_state.json`
  - `audits/packet_11d_planner_parallelism_and_setup_planner_count_repair_validation.md`

## What Still Aligns

- The validated frontier is still packet `11D`; I did not find packet-`12` HTML, React/Tailwind assets, or packet-`13` tooling/docs pulled forward into the live code.
- The backend/setup repair chain remains in place:
  - live runtime WebSocket events from packet `11A`
  - reconnect-safe dashboard/preflight contract from packet `11B`
  - session override and intake metadata contract from packet `11C`
  - planner-count transport plus bounded planning parallelism from packet `11D`
- Packet `12` still remains intentionally UI-only in its doc, with backend widening explicitly forbidden unless packet `11` is still missing contract fields it was supposed to stabilize (`plans/packet_12_embedded_react_spa_monitor.md:35-41`, `plans/packet_12_embedded_react_spa_monitor.md:87-90`).

## Finding

### 1. Medium: the retention setting existed, but the design-required startup purge behavior was still missing

Evidence before repair:

- The design requires session retention to be real behavior, not display-only: auto-purge runs on startup for completed or aborted sessions older than the configured retention window (`docs/cognitive_switchyard_design.md:957-966`).
- Packet `12` is supposed to keep History and Settings as consumers of the existing backend contract rather than widening backend semantics (`plans/packet_12_embedded_react_spa_monitor.md:35-41`, `plans/packet_12_embedded_react_spa_monitor.md:90`).
- The live backend already exposed retention as a persisted setting and manual purge routes:
  - settings read/write in `cognitive_switchyard/server.py:550-564`
  - manual session purge routes in `cognitive_switchyard/server.py:533-548`
- Before this repair, there was no retention enforcement step on the validated startup flow; the runtime initialized config and packs, exposed manual purge/settings APIs, and then launched `start`/`serve` without applying the configured retention window.

Why this mattered:

- The Settings view would have exposed a retention control whose behavior was still cosmetic.
- The History view contract would have drifted away from the design's startup purge behavior even though packet `12` is not supposed to add backend semantics.
- This was cumulative architecture drift, but it was bounded and unambiguous enough to repair inline.

## Repair Applied Now

I repaired the drift inline instead of inserting another backend repair packet.

Applied changes:

- Added `StateStore.purge_expired_sessions(...)` so retention cleanup is defined once at the state boundary (`cognitive_switchyard/state.py:562-581`).
- Wired retention purge into the validated `start` startup path before session lookup/creation (`cognitive_switchyard/cli.py:139-156`).
- Wired retention purge into the validated `serve` startup path before backend launch (`cognitive_switchyard/cli.py:175-185`).
- Added targeted regression coverage for:
  - state-layer retention deletion semantics (`tests/test_state_store.py:361-427`)
  - headless `start` startup purge (`tests/test_cli.py:247-295`)
  - `serve` startup purge before backend launch (`tests/test_cli.py:307-350`)

This keeps packet `12` on its intended boundary: the History and Settings views can now consume a retention setting that affects real runtime behavior without requiring another backend packet.

## Validation

Reran targeted validation after the repair:

- `.venv/bin/python -m pytest tests/test_state_store.py tests/test_cli.py -q`
  - Result: `19 passed`

No packet tracker changes were made because this audit returned `repair_now`, not `repair_packet`.

## Conclusion

The cumulative path after packet `11D` had one meaningful remaining backend drift: retention was stored and editable, but not enforced on startup. That would have left the upcoming History/Settings UI consuming a partially cosmetic backend contract. The issue was small and architecturally unambiguous, so I repaired it inline and reran targeted validation. No additional repair packet is needed from this audit.
