# Packet 09 Validation Audit

Assessed on 2026-03-10 against the live repository state.

## Outcome

Packet `09` is `validated`.

## Scope Check

- Packet implementation changes stayed inside the packet runtime/test surface plus the expected tracker/doc updates for implementation and validation.
- I did not find packet-scope code changes outside:
  - `cognitive_switchyard/models.py`
  - `cognitive_switchyard/orchestrator.py`
  - `cognitive_switchyard/state.py`
  - `cognitive_switchyard/verification_runtime.py`
  - `tests/test_orchestrator.py`
  - `tests/test_recovery.py`
  - `tests/test_state_store.py`
  - `tests/test_verification_runtime.py`
- Unrelated worktree items were present (`audits/full_suite_verification_after_packet_08.*`, `tmp_packet08_probe/`) and were ignored because they are outside packet `09` scope.

## Finding Repaired During Validation

### [Correctness] Finding #1: Restarted task auto-fix lost its task-specific retry context

- **Severity**: High
- **Category**: Correctness & Safety
- **Evidence**:
  - `cognitive_switchyard/orchestrator.py` routed recovered `auto_fixing` sessions through the generic verification-failure loop.
  - A task-failure auto-fix interrupted mid-retry resumed with `context_type='verification_failure'` and `task_id=None` instead of preserving the original task context.
  - The repaired regression is now covered by `tests/test_recovery.py::test_restart_from_auto_fixing_task_failure_replays_verification_and_keeps_task_context`.
- **Impact**:
  - Interrupted task auto-fix work could resume the wrong fixer path after restart.
  - The original failed task could remain unresolved even though packet `09` requires deterministic recovery for interrupted auto-fix work.
- **Recommended Fix**:
  - Replay verification on restart for recovered task auto-fix work.
  - If replay passes, mark the original task `done` without redispatch.
  - If replay fails, continue the task-failure retry loop with the persisted task id, attempt counter, and prior summary instead of switching to verification-failure auto-fix.
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**:
  - Recovered task auto-fix retries preserve `task_id` and `context_type='task_failure'`.
  - A recovered verification pass marks the original task `done` exactly once.
  - Retry-budget exhaustion still blocks the task deterministically.

## Validation Evidence

- Packet-local tests plus one adjacent regression check passed:

```bash
.venv/bin/python -m pytest tests/test_verification_runtime.py tests/test_orchestrator.py tests/test_recovery.py tests/test_state_store.py tests/test_planning_runtime.py -q
```

- Result: `41 passed in 8.25s`

## Acceptance Summary

- Interval-triggered verification is covered by `tests/test_verification_runtime.py`.
- `FULL_TEST_AFTER` forced verification before more dispatch is covered by `tests/test_verification_runtime.py`.
- Verification failure without auto-fix preserves the ready frontier and pauses deterministically in `tests/test_orchestrator.py`.
- Task-failure auto-fix success and resumed dispatch are covered by `tests/test_orchestrator.py`.
- Restart recovery now covers both `verifying` replay and recovered task auto-fix replay in `tests/test_recovery.py`.
