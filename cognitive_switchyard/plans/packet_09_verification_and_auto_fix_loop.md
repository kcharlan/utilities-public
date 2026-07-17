# Packet 09 - Verification and Auto-Fix Loop

## Why This Packet Exists

Packet `08` gets a session from intake through planning, resolution, and execution, but it still treats per-task completion as the end of the control loop. The design requires a second safety layer: pack-level verification after bounded batches and a bounded fixer retry loop before human escalation.

This packet adds that post-execution control loop without introducing any new CLI, API, or UI surface. The goal is to make execution sessions resilient to integration regressions and task-level failures before packet `10` exposes the engine through a real operator-facing startup path.

## Scope

- Add interval-driven verification after completed-task batches using `phases.verification.interval`.
- Force verification immediately when a completed task has `FULL_TEST_AFTER: yes`.
- Drain active workers before verification starts and prevent new dispatches until verification finishes.
- Execute the pack's verification command, capture output in the canonical session verification log, and emit deterministic session events for pass/fail transitions.
- Add bounded auto-fix retries for two contexts:
  - task execution failures
  - global verification failures
- Persist enough verification/auto-fix state to recover sessions interrupted while verifying or retrying fixes.
- Keep packet `06` execution semantics unchanged when both verification and auto-fix are disabled.

## Non-Goals

- No FastAPI, REST, WebSocket, or SPA work.
- No built-in pack shipping, pack reset commands, or bootstrap changes.
- No planner/resolver auto-fix path; this packet only covers post-execution failures.
- No release-notes generation, history trimming, or operator-documentation work.
- No real Claude CLI coupling in tests; fixer execution should remain injectable and fully testable with local fixtures.

## Relevant Design Sections

- `3.5 Verification (optional)`
- `3.6 Auto-Fix (optional)`
- `4.2 pack.yaml Schema` for `phases.verification.*` and `auto_fix.*`
- `4.4 Hook Contracts` for the existing execution/isolation boundaries that verification must not violate
- `7.4 Main Orchestration Loop` for dispatch pause, drain, verify, and resume semantics
- `8. Crash Recovery & Idempotency` for interrupted `verifying` state handling
- `reference/work/orchestrate.sh` lines around the verify/fixer loop as behavior guidance, not a line-by-line port

## Allowed Files

- `cognitive_switchyard/orchestrator.py`
- `cognitive_switchyard/recovery.py`
- `cognitive_switchyard/state.py`
- `cognitive_switchyard/models.py`
- `cognitive_switchyard/verification_runtime.py`
- `tests/test_orchestrator.py`
- `tests/test_recovery.py`
- `tests/test_state_store.py`
- `tests/test_verification_runtime.py`
- `tests/fixtures/packs/`
- `tests/fixtures/workers/`

## Tests To Write First

- `tests/test_verification_runtime.py::test_interval_verification_waits_for_active_workers_and_writes_verify_log`
- `tests/test_verification_runtime.py::test_full_test_after_flag_forces_verification_before_more_dispatch`
- `tests/test_orchestrator.py::test_task_failure_with_auto_fix_success_reclassifies_task_done_and_resumes_dispatch`
- `tests/test_orchestrator.py::test_verification_failure_without_auto_fix_pauses_session_with_ready_frontier_preserved`
- `tests/test_recovery.py::test_restart_from_verifying_or_auto_fixing_replays_verification_without_duplicate_done_projection`

## Implementation Notes

- Keep verification execution in a packet-local helper module rather than overloading `hook_runner.py`; packet verification is a pack-declared shell command, not a conventional hook path.
- Reuse `SessionPaths.verify_log` as the canonical latest verification artifact. Do not invent a second verification log location.
- Model verification and fixer work as explicit session phases in persisted state. Use `verifying` plus one explicit auto-fix status so packet `07` recovery can resume deterministically instead of treating these phases as generic execution.
- Inject the fixer executor as a callable in tests. Packet `09` should prove the control loop and context-building behavior without depending on an external LLM CLI.
- Build fixer context from the live task plan, latest status sidecar, relevant worker log tail, and the latest verification output when retrying a failed verification.
- For retry enrichment, follow the reference behavior: the second attempt should receive actual verification failures plus a concise summary of what changed in the previous attempt, not the previous fixer's self-reported success text.
- When verification is disabled, preserve packet `06` and packet `08` dispatch behavior exactly.

## Acceptance Criteria

- A session with `phases.verification.enabled: true` and interval `N` triggers verification after every `N` newly completed tasks, only after all active workers have drained.
- A completed task with `FULL_TEST_AFTER: yes` forces the next verification immediately even if the normal interval has not been reached.
- Verification output is captured in `logs/verify.log`, and the orchestrator records explicit pass/fail events that make the session outcome reconstructable from SQLite plus session artifacts.
- If verification passes, dispatch resumes and the completed-since-verification counter resets.
- If verification fails and auto-fix is disabled, the session ends in a deterministic paused/halted state with the ready frontier preserved for a later rerun.
- If task execution fails and auto-fix is enabled, the orchestrator performs up to `auto_fix.max_attempts` fixer retries with enriched context and only marks the task `done` after independent post-fix verification succeeds.
- If verification fails and auto-fix is enabled, the orchestrator performs up to `auto_fix.max_attempts` fixer retries, reruns verification after each attempt, and pauses/halts only after the retry budget is exhausted.
- Restarting a session interrupted during `verifying` or auto-fix work does not duplicate `done` projections, lose ready tasks, or skip the required verification rerun.
- Packet `06` through `08` regression tests continue to pass unchanged when verification and auto-fix are off.

## Validation Focus

- Interval accounting across mixed normal completions and `FULL_TEST_AFTER` tasks.
- No new worker dispatch while verification is active.
- Correct separation between task-failure auto-fix and verification-failure auto-fix.
- Recovery correctness for interrupted `verifying` and auto-fix phases.
- Regression coverage for packet `06`, packet `07`, and packet `08` execution/resolution behavior.
