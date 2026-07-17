# Drift Audit After Packet 06

Date: 2026-03-09
Audit label: `drift audit after packet 06`
Highest validated packet: `06`
Validated packet count: `7`
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
  - `plans/packet_05_worker_slot_lifecycle_and_timeout_monitoring.md`
  - `plans/packet_06_execution_orchestrator_loop.md`
- Relevant design sections already in scope for packets `00`-`06`:
  - `3.3`-`3.4`
  - `4.1`-`4.5`
  - `5.1`-`5.3`
  - `6.5`
  - `7.1`-`7.4`
  - `10.5`-`10.7`
  - `11`
- Live code under `cognitive_switchyard/`, `tests/`, and `README.md`
- Existing audit artifacts affecting this review:
  - `audits/drift_audit_after_packet_02.md`
  - `audits/drift_audit_after_packet_02.json`
  - `audits/drift_audit_after_packet_03.md`
  - `audits/drift_audit_after_packet_03.json`
  - `audits/drift_audit_after_packet_04.md`
  - `audits/drift_audit_after_packet_04.json`
  - `audits/drift_audit_state.json`
  - `audits/packet_06_execution_orchestrator_loop_validation.md`

## What Still Aligns

- The live implementation frontier is still packet `06`. No packet-`07`+ runtime modules or surfaces are present: no crash recovery, planning/runtime intake flow, verification/auto-fix loop, FastAPI backend, WebSocket manager, SPA, bootstrap flow, or built-in pack sync.
- Packet boundaries remain intact through packet `06`:
  - `cognitive_switchyard/state.py` is still the persistence/filesystem-projection boundary rather than a recovery or API layer.
  - `cognitive_switchyard/worker_manager.py` is still packet-local worker lifecycle logic rather than a session-level orchestrator.
  - `cognitive_switchyard/orchestrator.py` is still execution-only over already-ready tasks and still rejects non-`created` session starts, keeping packet-`07` restart semantics deferred.
- The packet-`06` validation repairs remain intact. The live orchestrator still carries the `isolate_start` workspace through success, blocked, malformed-sidecar, and session-abort paths, matching `audits/packet_06_execution_orchestrator_loop_validation.md`.
- Current validation remains green:
  - `.venv/bin/python -m pytest tests/test_orchestrator.py tests/test_worker_manager.py -v`
  - `.venv/bin/python -m pytest tests/test_state_store.py tests/test_scheduler.py tests/test_hook_runner.py -v`
  - `.venv/bin/python -m pytest tests/test_pack_loader.py tests/test_parsers.py -v`

## Findings

### 1. Medium: packet trackers overstate future packet-doc availability and currently point to missing files

Evidence:

- `plans/packet_status.md:28-34` lists packet docs for `07` through `13`.
- `plans/packet_status.md:40-42` explicitly claims `plans/packet_07_crash_recovery_and_reconciliation.md` is present beyond the validated frontier.
- `plans/packet_status.json:85-175` records `doc` paths for packets `07` through `13`.
- Live repository inspection shows the `plans/` directory only contains packet docs `00` through `06`; none of the referenced packet-`07`-`13` files exist.

Why this matters:

- The playbook requires the next planning or implementation turn to read the packet doc for the current horizon. The trackers currently instruct that process to read files that are not in the repository.
- This is an invalid tracker-state drift, not just missing future work. It weakens the packet ladder by making the next frontier look more prepared than it is.
- Because packet `07` is the next dependency and packet `06` intentionally defers restart semantics, leaving the next packet doc missing creates avoidable ambiguity at exactly the point where the delivery system is supposed to stay narrow.

Recommended follow-up:

- Before packet `07` planning or implementation begins, bring the trackers back into correspondence with the repo:
  - either create the actual next-horizon packet doc(s) that the trackers claim exist, or
  - downgrade the tracker references so they only point at files that are present.
- Do not continue the packet loop as though packet `07` is ready to implement from an existing doc when it is not.

### 2. Medium: the packet-01 resolution default still diverges from the design contract

Evidence:

- The design sets `agent` as the default resolution mode in `docs/cognitive_switchyard_design.md:127-134`.
- The live manifest model still defaults to `passthrough` in `cognitive_switchyard/models.py:23-28`.
- The loader still applies `passthrough` as the implicit resolution executor in `cognitive_switchyard/pack_loader.py:134-146`.
- The packet-local tests still pin that drift as expected behavior in `tests/test_pack_loader.py:23-47`.

Why this matters:

- Packet `01` exists to freeze pack-manifest contracts before runtime work compounds them.
- Defaulting to `passthrough` continues to normalize the least-safe resolution mode as the baseline pack behavior, contrary to the intended architecture.
- This remains unfixed after packets `05` and `06`, so later packet `08` planning/runtime work will inherit the wrong default unless the contract is corrected first.

Recommended follow-up:

- Repair the default resolution contract in a deliberate packet-scoped change before packet `08` or any additional pack-fixture expansion.
- Update the packet-`01` tests and minimal manifest fixture in the same change so the contract is pinned consistently.

### 3. Medium: accepted custom progress markers are still unsupported by the parser and now by the packet-05/06 runtime path

Evidence:

- The manifest contract still accepts configurable progress markers in `docs/cognitive_switchyard_design.md:274-305`.
- The manifest model and loader still expose that setting in:
  - `cognitive_switchyard/models.py:76-79`
  - `cognitive_switchyard/pack_loader.py:262-276`
- Progress parsing still hardcodes literal `##PROGRESS##` matching in:
  - `cognitive_switchyard/parsers.py:21-27`
  - `cognitive_switchyard/parsers.py:106-135`
- The packet-`05` worker path also hardcodes the same marker before parsing in `cognitive_switchyard/worker_manager.py:334-345`.
- The tests still only exercise the literal default marker in `tests/test_parsers.py:67-112`.

Why this matters:

- This started as a packet-`01`/`02` contract split and is now compounded by packets `05` and `06`, because the live execution path also assumes the literal default marker.
- A pack can currently validate with a non-default `status.progress_format`, but the implemented worker/orchestrator path cannot consume that pack contract.
- If this remains unresolved, packet `11`/`12` backend and UI work will be built on a runtime contract that is narrower than the accepted manifest surface.

Recommended follow-up:

- Make an explicit contract correction before backend/UI progress surfaces are added:
  - either teach progress parsing and worker consumption to honor the configured marker, or
  - narrow the accepted manifest contract so only the default marker is supported for now.
- Do not let packet `11` or `12` assume this mismatch is harmless.

### 4. Low: README had fallen behind the validated frontier again

Evidence before repair:

- `README.md` still said the validated frontier stopped at packet `04` and still claimed session execution was unimplemented, despite the validated packet-`06` tracker state and live orchestrator/worker modules.

Repair applied during this audit:

- Updated `README.md:145-164` so the public status text now reflects packet `06`, the packet-local worker lifecycle surface, and the execution-only orchestrator loop.

Why this was safe to fix now:

- The change was documentation-only and did not alter packet boundaries, runtime contracts, or tracker state.

### 5. Low: drift-audit scheduler state was stale and still pointed at the packet-04 audit frontier

Evidence before repair:

- `audits/drift_audit_state.json:2-7` still pointed to the packet-`04` audit files, recorded `last_audited_packet_id` as `04`, and still had `next_due_validated_count` set from the older `warn` result.

Repair applied during this audit:

- Updated `audits/drift_audit_state.json` to record this packet-`06` drift audit result and the next due count implied by a new `warn`.

Why this was safe to fix now:

- The file is audit bookkeeping only.
- Updating it does not affect packet implementation behavior or the packet-status trackers that were explicitly frozen for this audit.

## Fixes Applied

- Updated `README.md` to reflect the packet-`06` validated frontier and the existence of the worker lifecycle plus execution-only orchestrator surfaces.
- Updated `audits/drift_audit_state.json` so the audit scheduler state no longer points at the packet-`04` frontier.

## Validation Rerun After Fix

Targeted rerun after the README repair:

- `./switchyard --help`
- `./switchyard paths`
- `.venv/bin/python -m cognitive_switchyard --help`

All three commands passed on 2026-03-09.

## Conclusion

Packet `06` did not introduce architecture breakage or future-packet scope creep in the live code. The implementation still follows the intended delivery ladder through the first execution-only session loop.

The overall result remains `warn` because three medium drifts are now live at the same time:

- packet trackers claim next-horizon packet docs that are not actually present
- the resolution default still diverges from the design contract
- configurable progress markers are still accepted but not consumed by the live runtime path

Those issues should be corrected before the implementation flow moves into packet `07` planning, packet `08` resolution runtime work, or packet `11`/`12` progress-surface work.
