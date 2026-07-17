# Drift Audit After Packet 04

Date: 2026-03-09
Audit label: `drift audit after packet 04`
Highest validated packet: `04`
Validated packet count: `5`
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
  - `plans/packet_04_pack_hook_runner_and_preflight.md`
- Relevant design sections already in scope for packets `00`-`04`:
  - `3.3`-`3.4`
  - `4.1`-`4.5`
  - `5.1`-`5.3`
  - `6.5`
  - `7.1`-`7.2`
  - `10.5`-`10.7`
  - `11`
- Live code under `cognitive_switchyard/`, `tests/`, and `README.md`
- Existing audit artifacts affecting this review:
  - `audits/drift_audit_state.json`
  - `audits/drift_audit_after_packet_02.md`
  - `audits/drift_audit_after_packet_02.json`
  - `audits/drift_audit_after_packet_03.md`
  - `audits/drift_audit_after_packet_03.json`
  - `audits/packet_00_canonical_contracts_and_scaffold_validation.md`
  - `audits/packet_01_pack_and_session_contract_parsing_validation.md`
  - `audits/packet_02_task_artifact_parsing_and_scheduler_core_validation.md`
  - `audits/packet_03_sqlite_state_store_and_filesystem_projection_validation.md`
  - `audits/packet_04_pack_hook_runner_and_preflight_validation.md`

## What Still Aligns

- The validated frontier in the live codebase is still packet `04`. No packet-`05`+ modules or behavior (`worker_manager.py`, `orchestrator.py`, crash recovery, planner/resolver runtime, FastAPI, WebSocket, SPA, built-in packs) have been introduced.
- Packet `04` stayed inside its intended boundary:
  - `cognitive_switchyard/hook_runner.py` is limited to executable-bit scanning, prerequisite execution, optional preflight execution, and short-lived direct hook invocation.
  - `cognitive_switchyard/pack_loader.py` remains the pure manifest/hook-path contract layer rather than taking on worker lifecycle or orchestration behavior.
- Tracker state is internally consistent:
  - `plans/packet_status.md` and `plans/packet_status.json` both mark packets `00`-`04` as `validated`.
  - Both trackers still identify packet `05` as the next implementation target and do not claim packet-`05` docs exist yet.
- The current validated surface is green:
  - `.venv/bin/python -m pytest tests -v`
  - `./switchyard --help`
  - `./switchyard paths`
  - `.venv/bin/python -m cognitive_switchyard --help`

## Findings

### 1. Medium: the packet-01 resolution default is still drifted away from the design contract

Evidence:

- The design sets `agent` as the default resolution mode in `docs/cognitive_switchyard_design.md:127-134`.
- The live manifest model still defaults resolution to `passthrough` in `cognitive_switchyard/models.py:23-28`.
- The loader still applies the same `passthrough` default in `cognitive_switchyard/pack_loader.py:134-146`.
- The tests still pin that drift as expected behavior in `tests/test_pack_loader.py:25-49`.
- This same issue was already identified in `audits/drift_audit_after_packet_02.md` and `audits/drift_audit_after_packet_03.md` and was not corrected by packet `04`.

Why this matters:

- Packet `01` exists to freeze pack contracts before runtime packets build on them.
- Leaving `passthrough` as the default keeps normalizing the least-safe resolution mode as the baseline pack behavior.
- If this continues into packet `08`, the planning/resolution runtime will inherit the wrong default and existing fixtures/tests will make the repair noisier.

Recommended follow-up:

- Repair the default resolution contract in a deliberate packet-scoped change before packet `08` or any further pack-fixture expansion.
- Update the packet-`01` tests and minimal manifest fixture at the same time so the contract is pinned consistently.

### 2. Medium: accepted custom progress markers still cannot be consumed by the only progress parser

Evidence:

- The manifest contract still accepts configurable progress markers in `docs/cognitive_switchyard_design.md:274-305`.
- The live manifest types and loader still expose that setting in:
  - `cognitive_switchyard/models.py:76-79`
  - `cognitive_switchyard/pack_loader.py:262-276`
- The progress parser still hardcodes literal `##PROGRESS##` matching in:
  - `cognitive_switchyard/parsers.py:21-27`
  - `cognitive_switchyard/parsers.py:106-135`
- The current packet tests only exercise the literal default marker in `tests/test_parsers.py:79-112`.
- This same cross-packet gap was already identified in `audits/drift_audit_after_packet_02.md` and `audits/drift_audit_after_packet_03.md` and remains unresolved after packet `04`.

Why this matters:

- Packet `01` says packs may declare a non-default progress marker.
- Packet `02` provides the parser later worker/runtime packets will depend on, but it only understands the default marker.
- Packet `05` is the first worker/log/progress packet. If the contract stays split going into packet `05`, that packet will either have to silently narrow the accepted pack surface or retrofit parsing under worker-lifecycle pressure.

Recommended follow-up:

- Make the contract decision before packet `05` implementation proceeds:
  - either teach progress parsing to honor the configured marker, or
  - narrow the accepted manifest contract so only the default marker is supported for now.

### 3. Low: the README had fallen behind the validated packet frontier again

Evidence before repair:

- `README.md` still said the validated frontier stopped at packet `03` and still listed hook running as absent, even though `plans/packet_status.md` / `plans/packet_status.json` and the live code validate packet `04`.

Repair applied during this audit:

- Updated `README.md` so the public status section now reflects packet `04` and the existence of packet-scoped hook/preflight helpers without changing trackers or runtime behavior.

Why this was safe to fix now:

- The change was documentation-only and tightly scoped.
- It did not alter packet boundaries, contracts, or implementation behavior.

## Fixes Applied

- Updated `README.md` to reflect the packet-`04` validated frontier and the presence of hook discovery/preflight helpers.
- Updated `audits/drift_audit_state.json` to record this audit result and keep the audit scheduler state aligned with the new frontier.

## Validation Rerun After Fix

Broader rerun after the README repair:

- `.venv/bin/python -m pytest tests -v`
- `./switchyard --help`
- `./switchyard paths`
- `.venv/bin/python -m cognitive_switchyard --help`

All commands passed on 2026-03-09.

## Conclusion

Packet `04` did not introduce new packet-boundary erosion or future-packet implementation creep. The cumulative path still matches the intended delivery ladder through pack hook/preflight support.

The overall result remains `warn` because the two medium contract drifts from the prior audits are still live and now sit directly in front of upcoming packet work:

- wrong default resolution semantics
- accepted-but-unusable custom progress marker configuration

Those should be corrected deliberately before worker progress handling in packet `05` and before resolution runtime work in packet `08`.
