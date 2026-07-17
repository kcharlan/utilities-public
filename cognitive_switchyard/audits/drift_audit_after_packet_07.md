# Drift Audit After Packet 07

Date: 2026-03-09
Audit label: `drift audit after packet 07`
Highest validated packet: `07`
Validated packet count: `8`
Overall result: `halt`

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
  - `plans/packet_07_crash_recovery_and_reconciliation.md`
- Relevant design sections already in scope for packets `00`-`07`:
  - `3.3`-`3.4`
  - `4.1`-`4.5`
  - `5.1`-`5.3`
  - `6.5`
  - `7.1`-`7.4`
  - `10.1`-`10.7`
  - `11`
- Live code under `cognitive_switchyard/`, `tests/`, and `README.md`
- Existing audit artifacts affecting this review:
  - `audits/drift_audit_state.json`
  - `audits/drift_audit_after_packet_02.md`
  - `audits/drift_audit_after_packet_02.json`
  - `audits/drift_audit_after_packet_03.md`
  - `audits/drift_audit_after_packet_03.json`
  - `audits/drift_audit_after_packet_04.md`
  - `audits/drift_audit_after_packet_04.json`
  - `audits/drift_audit_after_packet_06.md`
  - `audits/drift_audit_after_packet_06.json`
  - `audits/packet_07_crash_recovery_and_reconciliation_validation.md`

## What Still Aligns

- The live implementation frontier is still packet `07`. No packet-`08`+ runtime surfaces are present: no intake/planning/resolution runtime, verification/auto-fix loop, FastAPI backend, WebSocket manager, SPA, bootstrap flow, or built-in pack sync.
- The prior tracker/doc-availability drift is resolved. `plans/packet_status.md`, `plans/packet_status.json`, and the `plans/` directory now agree that packet docs exist through `08`, and only packet `08` is present beyond the validated frontier.
- Packet boundaries still broadly hold through packet `07`:
  - `cognitive_switchyard/recovery.py` is limited to execution-phase recovery and reconciliation.
  - The codebase still lacks future-packet planning/runtime, backend, and UI modules.

## Findings

### 1. High: restart recovery is incorrectly gated behind preflight success

Evidence:

- Packet `07` requires an execution-recovery pass that runs before normal dispatch for `running` and `paused` sessions (`plans/packet_07_crash_recovery_and_reconciliation.md`, Scope and Implementation Notes).
- The design makes recovery a startup boundary before the normal loop (`docs/cognitive_switchyard_design.md:1328-1354`).
- The live orchestrator still runs pack preflight first and returns on failure before recovery is attempted:
  - `cognitive_switchyard/orchestrator.py:40-57`
  - recovery only begins later at `cognitive_switchyard/orchestrator.py:68-75`
- Live repro run during this audit on 2026-03-09:
  - A `running` session with a stranded task in `workers/0` and failing prerequisite checks returned `started=False`, `session_status=created`, while the task row stayed `active`, the plan remained in `workers/0`, and `workers/0/recovery.json` remained present.
  - A `paused` session with the same setup also skipped recovery, returned `session_status=created`, left the stored session state as `paused`, and left the stranded task/metadata untouched.

Why this matters:

- Packet `07`'s main contract is idempotent restart. Right now restart safety depends on preflight succeeding first.
- A crash followed by a preflight failure can leave orphaned worker state unreconciled and can postpone orphan PID cleanup indefinitely.
- The return value is also misleading for paused-session restart failure (`session_status=created` while SQLite still says `paused`), which makes the tracker/runtime contract harder to trust.

Recommended follow-up:

- Repair the startup order before any packet-`08` work proceeds:
  - run recovery first for `running` and `paused` sessions
  - skip dispatch-only preflight for `paused` recovery paths
  - rerun preflight only for the paths that will actually dispatch
- Add regression coverage proving stranded worker plans are recovered even when preflight fails, for both `running` and `paused` sessions.

### 2. Medium: `session_max` resets on restart instead of remaining a session-wide wall-clock limit

Evidence:

- The design defines `session_max` as a wall-clock cap on the entire session from start to completion (`docs/cognitive_switchyard_design.md:1205-1209`).
- The live orchestrator measures session timeout from a fresh in-process monotonic timestamp each time `execute_session()` is called:
  - `cognitive_switchyard/orchestrator.py:83-90`
- The persisted session record stores `created_at` and `completed_at`, but there is no persisted execution-start or elapsed-time field that recovery can reuse:
  - `cognitive_switchyard/state.py:23-31`
  - `cognitive_switchyard/state.py:320-346`

Why this matters:

- After a crash/restart, a long-running session gets a fresh timeout budget.
- Repeated restarts can therefore evade the design's session-wide safety cap, especially now that packet `07` explicitly supports restart.

Recommended follow-up:

- Persist the execution start timestamp or accumulated elapsed runtime in session state and reuse it after recovery.
- Add a packet-`07` regression proving a restarted session still honors the original `session_max` budget.

### 3. Medium: the accepted pack status protocol is still wider than what execution and recovery can consume

Evidence:

- The manifest contract still accepts configurable status/progress protocol fields:
  - `cognitive_switchyard/models.py:76-79`
  - `cognitive_switchyard/pack_loader.py:262-276`
- The parser and runtime still hardcode only the default protocol:
  - progress markers must literally start with `##PROGRESS##` in `cognitive_switchyard/parsers.py:21-27` and `cognitive_switchyard/parsers.py:106-135`
  - worker collection always parses key-value status sidecars in `cognitive_switchyard/worker_manager.py:180-190`
  - recovery classification uses the same key-value parser in `cognitive_switchyard/recovery.py:140-147`
- Tests still cover only the default literal marker and key-value sidecars:
  - `tests/test_parsers.py:79-112`
  - `tests/test_worker_manager.py:122-200`

Why this matters:

- A pack can validate with a custom `status.progress_format` or `status.sidecar_format: json|yaml`, but the live execution/recovery path cannot consume that pack contract.
- This started as a packet-`01` / packet-`02` split and now spans packets `05` and `07`, which means packet `08`, packet `11`, and packet `12` would build on a runtime contract that is narrower than the accepted manifest surface.

Recommended follow-up:

- Make one explicit contract decision before packet `08`:
  - either implement configurable progress/sidecar parsing end-to-end across parser, worker, and recovery paths
  - or narrow the manifest contract so only the currently implemented default protocol is accepted

### 4. Medium: the resolution default still diverges from the design contract

Evidence:

- The design sets `agent` as the default resolution mode (`docs/cognitive_switchyard_design.md:127-134`).
- The live manifest model and loader still default resolution to `passthrough`:
  - `cognitive_switchyard/models.py:20-27`
  - `cognitive_switchyard/pack_loader.py:134-146`
- The tests still pin that drift as expected behavior:
  - `tests/test_pack_loader.py:31-35`

Why this matters:

- Packet `01` exists to freeze pack contracts before the planning/resolution runtime arrives.
- Leaving `passthrough` as the default keeps normalizing the least-safe resolution mode just before packet `08`, where the resolver runtime is the next major delivery surface.

Recommended follow-up:

- Repair the default resolution contract in a deliberate packet-scoped change before packet `08` implementation begins.
- Update the packet-`01` tests and minimal manifest fixture in the same change so the contract is pinned consistently.

## Fixes Applied

- Updated `README.md` so the public status section now reflects the packet-`07` validated frontier and the existence of execution-phase crash recovery.
- Updated `audits/drift_audit_state.json` to record this audit result and keep the audit scheduler state aligned with the current frontier.

## Validation Rerun After Fix

- None. The fixes applied during this audit were documentation/bookkeeping only; no runtime code changed.

## Conclusion

Packet `07` did not introduce packet-`08` scope creep, but the current recovery startup order is a high-severity architecture break: a failed preflight can prevent restart recovery from running at all.

Because packet `07` is supposed to make rerunning the same session safe after a crash, the overall result is `halt` until that ordering bug is corrected. The earlier contract drifts around status/progress protocol handling and resolution defaults also remain unresolved and should be repaired before packet `08` proceeds.
