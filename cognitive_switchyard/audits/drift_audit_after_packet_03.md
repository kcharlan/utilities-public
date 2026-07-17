# Drift Audit After Packet 03

Date: 2026-03-09
Audit label: `drift audit after packet 03`
Highest validated packet: `03`
Validated packet count: `4`
Overall result: `warn`

## Scope

Reviewed during this audit:

- `docs/implementation_packet_playbook.md`
- `plans/packet_status.md`
- `plans/packet_status.json`
- Validated packet docs:
  - `plans/packet_00_canonical_contracts_and_scaffold.md`
  - `plans/packet_01_pack_and_session_contract_parsing.md`
  - `plans/packet_02_task_artifact_parsing_and_scheduler_core.md`
  - `plans/packet_03_sqlite_state_store_and_filesystem_projection.md`
- Relevant design sections already in scope for packets `00`-`03`:
  - `3.3`-`3.4`
  - `4.1`-`4.5`
  - `5.1`-`5.3`
  - `6.5`
  - `7.1`-`7.2`
  - `10.5`-`10.7`
  - `11`
- Live code under `cognitive_switchyard/` and `tests/`
- Existing audit artifacts affecting this review:
  - `audits/drift_audit_state.json`
  - `audits/drift_audit_after_packet_02.md`
  - `audits/drift_audit_after_packet_02.json`
  - `audits/packet_00_canonical_contracts_and_scaffold_validation.md`
  - `audits/packet_01_pack_and_session_contract_parsing_validation.md`
  - `audits/packet_02_task_artifact_parsing_and_scheduler_core_validation.md`
  - `audits/packet_03_sqlite_state_store_and_filesystem_projection_validation.md`

## What Still Aligns

- The validated frontier in the live codebase is still packet `03`. No packet-`04`+ runtime modules (`worker_manager.py`, `orchestrator.py`, server/UI files, built-in packs) have been introduced.
- Packet `03` stayed inside its intended boundary:
  - `cognitive_switchyard/state.py` is limited to SQLite initialization, session/task/worker-slot/event persistence, and filesystem projection.
  - The earlier packets remain pure scaffold/parsing/scheduler logic.
- Tracker state is internally consistent:
  - `plans/packet_status.md` and `plans/packet_status.json` both mark packets `00`-`03` as `validated`.
  - Both trackers still identify packet `04` as the next implementation target.
- The packet ladder has not been eroded by runtime scope creep. The codebase still lacks hook execution, worker subprocess lifecycle, orchestrator dispatch, recovery, REST, and UI behavior.

## Findings

### 1. Medium: the packet-01 resolution default is still drifted away from the design contract

Evidence:

- The design sets `agent` as the default resolution mode in `docs/cognitive_switchyard_design.md:127-134`.
- The live manifest model still defaults resolution to `passthrough` in `cognitive_switchyard/models.py:23-28`.
- The loader still applies the same `passthrough` default in `cognitive_switchyard/pack_loader.py:106-110`.
- The tests still pin that drift as expected behavior in `tests/test_pack_loader.py:21-45`.
- This same issue was already identified in `audits/drift_audit_after_packet_02.md:45-65` and was not corrected by packet `03`.

Why this matters:

- Packet `01` exists to freeze the pack contract before runtime work.
- Leaving `passthrough` as the default normalizes the least-safe resolution mode as the baseline pack behavior.
- If this carries forward, packet `08` will inherit the wrong contract and future pack fixtures/docs will continue encoding it.

Recommended follow-up:

- Repair the default resolution contract in a deliberate packet-scoped change before more pack fixtures or resolution-runtime work lands.
- Do not hide that repair inside packet `08`; update the packet-`01` contract tests and any fixtures/docs that currently encode the wrong default.

### 2. Medium: accepted custom progress markers still cannot be consumed by the only progress parser

Evidence:

- The manifest contract still accepts configurable progress markers in `docs/cognitive_switchyard_design.md:274-276`.
- The live manifest types and loader still expose that setting in:
  - `cognitive_switchyard/models.py:76-79`
  - `cognitive_switchyard/pack_loader.py:223-236`
- The progress parser still hardcodes literal `##PROGRESS##` matching in:
  - `docs/cognitive_switchyard_design.md:303-305`
  - `cognitive_switchyard/parsers.py:21-27`
  - `cognitive_switchyard/parsers.py:106-127`
- This same cross-packet gap was already identified in `audits/drift_audit_after_packet_02.md:67-88` and remains unresolved after packet `03`.

Why this matters:

- Packet `01` says packs may declare a non-default progress marker.
- Packet `02` provides the only parser later worker/runtime packets can rely on, but it only understands the default marker.
- If this stays unresolved, packet `05` worker log parsing and later backend/UI progress surfaces will be built on a narrower contract than the pack layer currently accepts.

Recommended follow-up:

- Make an explicit contract decision before packet `05`:
  - either teach progress parsing to honor the configured marker, or
  - narrow the accepted manifest contract so only the default marker is supported for now.

### 3. Low: the README had fallen behind the validated packet frontier

Evidence before repair:

- `README.md` said the validated frontier stopped at packet `02` and still described the state store as absent, even though `plans/packet_status.md:7-14` and `plans/packet_status.json` mark packet `03` as validated.

Repair applied during this audit:

- Updated `README.md:118-160` so the public status text now matches the packet-`03` repository state without changing trackers or code behavior.

Why this was safe to fix now:

- The change was documentation-only.
- It did not alter packet boundaries, implementation contracts, or tracker state.

## Fixes Applied

- Updated `README.md` to reflect the packet-`03` validated frontier and the presence of the first SQLite-backed state-store/filesystem projection layer.

## Validation Rerun After Fix

Targeted smoke rerun after the README repair:

- `./switchyard --help`
- `./switchyard paths`
- `.venv/bin/python -m cognitive_switchyard --help`

All three commands passed on 2026-03-09.

## Conclusion

Packet `03` did not introduce new architectural drift or packet-boundary erosion. The repository still follows the intended delivery ladder through the first SQLite state layer.

The overall result remains `warn` because the two medium contract drifts from the prior audit are still live:

- wrong default resolution semantics
- accepted-but-unusable custom progress marker configuration

Those should be corrected deliberately before progress-consuming worker work in packet `05` and before resolution-runtime work in packet `08`.
