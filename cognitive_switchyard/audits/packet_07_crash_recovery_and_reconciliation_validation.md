# Packet 07 Validation Audit

Assessed on 2026-03-09 against `plans/packet_07_crash_recovery_and_reconciliation.md`.

## Assumptions

- Packet `07` owns only execution-phase restart/reconciliation behavior for sessions already in `running` or `paused`.
- The filesystem projection remains the source of truth for task location/state during recovery.
- Persisted worker PIDs may belong to processes that are no longer children of the restarted orchestrator process after a crash.

## Scope Check

- Reviewed packet-local implementation in `cognitive_switchyard/orchestrator.py`, `cognitive_switchyard/recovery.py`, `cognitive_switchyard/state.py`, `cognitive_switchyard/models.py`, `cognitive_switchyard/worker_manager.py`, and packet tests in `tests/test_recovery.py` and `tests/test_orchestrator.py`.
- Unrelated worktree changes exist outside the packet allowlist (`README.md`, drift-audit artifacts, packet-08 planning doc). They were not used as delivery evidence for packet `07`.

## Validation Evidence

- `.venv/bin/python -m pytest tests/test_recovery.py tests/test_orchestrator.py -v` -> passed (`14 passed`).
- `.venv/bin/python -m pytest tests/test_state_store.py tests/test_worker_manager.py tests/test_hook_runner.py -v` -> passed (`20 passed`).

## Findings

### [Correctness & Safety] Finding #1: Recovery skipped TERM/KILL for reparented orphan worker PIDs

- **Severity**: High
- **Category**: Correctness & Safety
- **Status**: Fixed during validation
- **Evidence**:
  - `cognitive_switchyard/recovery.py:187` previously returned `False` immediately on `ChildProcessError` from `os.waitpid(pid, os.WNOHANG)`.
  - In a true restart, recovered worker PIDs are typically no longer child processes of the new orchestrator, so `waitpid()` raises `ChildProcessError` even when the worker is still running.
- **Impact**:
  - Packet `07` would fail its orphan-cleanup guarantee after an actual crash/restart.
  - Recovery could move work back to `ready/` while leaving the previous worker process alive, creating duplicate execution and workspace races on redispatch.
- **Recommended Fix**:
  - Treat `ChildProcessError` as "not our child, keep checking" instead of "already exited".
  - Continue liveness detection with `os.kill(pid, 0)` so recorded orphan PIDs still receive the documented TERM-then-KILL sequence.
- **Implemented Fix**:
  - `cognitive_switchyard/recovery.py:187-198` now falls through to `os.kill(pid, 0)` after `ChildProcessError`.
  - `tests/test_recovery.py:132-166` adds a helper that spawns a reparented sleeper PID.
  - `tests/test_recovery.py:300` adds `test_recover_incomplete_worker_terminates_reparented_orphan_process`.
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**:
  - Recovery terminates a persisted PID that is still alive but is not a child of the validating process.
  - The reverted task returns to `ready/`.
  - Packet and adjacent regression suites pass.

## Remaining Findings

No remaining packet-scope defects were found after the repair and targeted revalidation.

## Verdict

Packet `07` satisfies its acceptance criteria and is validated.
