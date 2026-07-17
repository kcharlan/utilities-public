# Packet 05: Worker Slot Lifecycle and Timeout Monitoring

## Why This Packet Exists

Packets `00` through `04` established the canonical contracts, scheduler inputs, durable task/session projection, and short-lived pack hooks. The next missing runtime boundary is the long-running worker process itself: one task in one slot, with output capture, progress parsing, completion collection, and timeout enforcement. That behavior needs to be isolated and validated before an orchestrator loop starts moving real session state.

## Scope

- Add `cognitive_switchyard.worker_manager` as the packet-owned runtime boundary for one long-running execution subprocess per worker slot.
- Launch the pack's execution command with direct argument vectors (`<execute> <task-plan-path> <workspace-path>`) using `subprocess.Popen`, not shell wrapping.
- Capture worker stdout/stderr into the canonical per-slot log file while preserving incremental lines for polling callers.
- Parse progress markers from worker output with the existing packet-`02` progress parser and expose the latest phase/detail state per slot.
- Detect process completion, locate the status sidecar adjacent to the active task plan, and return structured completion results that include parsed sidecar content when present and valid.
- Enforce `timeouts.task_idle` and `timeouts.task_max`, including SIGTERM followed by SIGKILL-after-grace when the worker does not exit cleanly.

## Non-Goals

- No SQLite writes, session-state transitions, or task projection between `ready/`, `workers/<slot>/`, `done/`, and `blocked/`.
- No task selection, dependency checks, anti-affinity enforcement, or orchestration loop behavior.
- No session-level timeout handling; `timeouts.session_max` belongs to packet `06`.
- No planner/resolver runtime, verification loop, auto-fix loop, or API/UI work.
- No agent-executor launch semantics; this packet only covers manifest-resolved executable commands for execution.
- No `isolate_start` or `isolate_end` decision-making; the caller supplies the workspace path and decides when isolation hooks run.

## Relevant Design Sections

- `3.4` Execution
- `4.2` pack.yaml Schema
- `4.3` Lifecycle Hook Contracts
- `5.2` File-as-State Mapping
- `7.1` Module Structure
- `7.4` Timeout Model
- `10.6` Idempotency Guarantees by Operation

## Allowed Files

- `cognitive_switchyard/worker_manager.py`
- `cognitive_switchyard/models.py`
- `cognitive_switchyard/parsers.py`
- `cognitive_switchyard/pack_loader.py`
- `tests/test_worker_manager.py`
- `tests/conftest.py`
- `tests/fixtures/packs/**`
- `tests/fixtures/workers/**`

## Tests To Write First

1. `tests/test_worker_manager.py::test_dispatch_shell_worker_writes_worker_log_and_collects_status_sidecar`
2. `tests/test_worker_manager.py::test_worker_progress_markers_update_latest_progress_without_hiding_raw_output`
3. `tests/test_worker_manager.py::test_idle_timeout_terminates_worker_and_reports_timeout_result`
4. `tests/test_worker_manager.py::test_task_max_timeout_terminates_long_running_worker_after_grace_period`
5. `tests/test_worker_manager.py::test_collect_rejects_missing_or_malformed_status_sidecar_with_typed_error`
6. `tests/test_worker_manager.py::test_packet_04_execution_hook_resolution_regression_still_passes`

## Implementation Notes

- Keep worker-slot state in memory and packet-local. Packet `06` will decide how worker lifecycle events map onto persisted session/task state.
- Inject the clock, poll interval, and kill-grace duration so timeout tests stay deterministic and do not rely on coarse sleeps.
- Write all worker output to the canonical slot log path under `logs/workers/<slot>.log`; progress markers are parsed in addition to, not instead of, raw log capture.
- Reuse packet-`02` `parse_progress_line()` and `parse_status_sidecar()` so later packets consume one normalized artifact contract.
- Treat timeout outcomes and sidecar-validation failures as structured worker results or typed errors, not as implicit filesystem moves or SQLite mutations.
- Use `reference/work/execution/WORKER.md` only as a protocol/fixture reference for the progress phases and sidecar expectations. Do not import broader plan-execution behavior from it into this packet.

## Acceptance Criteria

- A shell-based execution command can be launched for a task plan in a numbered worker slot and monitored until exit.
- The worker manager writes the full raw output stream to the slot log and exposes parsed latest-progress state from `##PROGRESS##` markers.
- On normal completion, the worker manager returns structured exit metadata plus a parsed status sidecar result.
- On idle-timeout or hard-timeout, the worker manager kills the subprocess with the documented TERM-then-KILL sequence and returns a structured timeout result.
- Missing or malformed status sidecars fail through explicit packet-local tests and typed errors rather than silent partial success.
- Packet-local tests pass together with adjacent regressions for packet `02` parsers and packet `04` execution-hook resolution.

## Validation Focus

- `.venv/bin/python -m pytest tests/test_worker_manager.py -v`
- `.venv/bin/python -m pytest tests/test_parsers.py tests/test_hook_runner.py -v`
