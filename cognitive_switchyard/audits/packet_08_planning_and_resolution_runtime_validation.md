# Packet 08 Validation Audit

Assessed on 2026-03-10 against `plans/packet_08_planning_and_resolution_runtime.md`.

## Assumptions

- Packet `08` owns only the pre-execution planning/resolution runtime and its handoff into the already-validated execution loop.
- `ready/` plans and SQLite `ready` rows are derived resolution outputs and must not survive a rerun that now halts with review work or resolution conflicts.
- Planning/resolution reruns are expected to be safe on `created`, `planning`, and `resolving` sessions without introducing packet-09 verification behavior.

## Scope Check

- Reviewed packet-local implementation in `cognitive_switchyard/planning_runtime.py`, `cognitive_switchyard/orchestrator.py`, `cognitive_switchyard/state.py`, `cognitive_switchyard/models.py`, and `cognitive_switchyard/parsers.py`.
- Reviewed packet-local tests in `tests/test_planning_runtime.py` and `tests/test_orchestrator.py`.
- The implementation stayed inside the packet allowlist plus the required tracker files.

## Validation Evidence

- `.venv/bin/python -m pytest tests/test_planning_runtime.py tests/test_orchestrator.py -v` -> passed (`20 passed`).
- `.venv/bin/python -m pytest tests/test_state_store.py tests/test_parsers.py tests/test_pack_loader.py tests/test_hook_runner.py -v` -> passed (`37 passed`).
- Targeted rerun probe reproduced and then verified the packet-08 conflict-regeneration bug described below.

## Findings

### [Correctness & Safety] Finding #1: Resolution reruns preserved stale ready work after new conflicts

- **Severity**: High
- **Category**: Correctness & Safety
- **Status**: Fixed during validation
- **Evidence**:
  - `cognitive_switchyard/planning_runtime.py` previously left valid `ready/*.plan.md` files and SQLite `ready` rows in place during `_recover_resolution_inputs()`.
  - A targeted repro showed: first passthrough resolution produced ready task `001`; a second pass with new staged plan `002` depending on missing task `999` returned conflicts while `001.plan.md` and its DB row still remained ready.
- **Impact**:
  - Packet `08` could report `needs resolution` while packet `06` still had stale executable work in `ready/`.
  - A later execution call could consume outdated ready plans even though the current staged batch no longer resolved cleanly.
- **Recommended Fix**:
  - Treat existing `ready/` plans as derived resolution outputs during reruns.
  - Move them back into `staging/` when regenerating resolution inputs, drop duplicate ready copies when staging already exists, and clear the corresponding SQLite task rows before resolving again.
- **Implemented Fix**:
  - `cognitive_switchyard/planning_runtime.py` now reverts all existing `ready/` plans into `staging/` and deletes their persisted ready-task rows before a new resolution pass.
  - `tests/test_planning_runtime.py` now includes `test_resolution_rerun_with_conflicts_clears_stale_ready_outputs_before_halting`.
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**:
  - A rerun that ends in conflicts leaves the affected batch in `staging/`, not `ready/`.
  - `store.list_ready_tasks(session_id)` is empty after the conflicting rerun.
  - Packet and adjacent regression suites pass.

## Remaining Findings

No remaining packet-scope defects were found after the repair and targeted revalidation.

## Verdict

Packet `08` satisfies its acceptance criteria and is validated.
