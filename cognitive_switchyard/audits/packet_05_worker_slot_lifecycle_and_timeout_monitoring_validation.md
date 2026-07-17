# Packet 05 Validation: Worker Slot Lifecycle and Timeout Monitoring

Validated on 2026-03-09 against the live repository state.

## Result

`validated`

## Scope Check

- Reviewed packet-owned implementation in [cognitive_switchyard/worker_manager.py](/Users/example/source/utilities/cognitive_switchyard/cognitive_switchyard/worker_manager.py).
- Reviewed packet-local tests in [tests/test_worker_manager.py](/Users/example/source/utilities/cognitive_switchyard/tests/test_worker_manager.py) plus adjacent regressions in [tests/test_parsers.py](/Users/example/source/utilities/cognitive_switchyard/tests/test_parsers.py) and [tests/test_hook_runner.py](/Users/example/source/utilities/cognitive_switchyard/tests/test_hook_runner.py).
- Checked the referenced protocol contract in `reference/work/execution/WORKER.md` and the packet-listed design sections.
- Validation/fix work stayed inside the packet's allowed implementation and fixture surface, plus the required audit and packet-status trackers.

## Findings Fixed Now

1. Status sidecar lookup used `Path.with_suffix(".status")`, which produced `*.plan.status` for plan files such as `039_example.plan.md`. The packet contract, design doc, and worker protocol require `039_example.status`. Fixed the worker manager and packet fixtures/tests to use the canonical sidecar path.
2. Progress parsing accepted `##PROGRESS##` markers for any task id emitted by the subprocess. In a single-task worker slot, that could surface another task's progress on the wrong slot. Fixed the worker manager to ignore progress markers whose task id does not match the active task, and added packet-local regression coverage.

## Validation Commands

```bash
.venv/bin/python -m pytest tests/test_worker_manager.py -v
.venv/bin/python -m pytest tests/test_parsers.py tests/test_hook_runner.py -v
```

Both commands passed after the packet-local repairs.

## Acceptance Criteria Review

- Shell execution dispatch via direct argument vector: pass.
- Raw worker output captured to per-slot log with latest parsed progress state: pass.
- Structured completion result with parsed status sidecar on success: pass.
- Idle and hard task timeouts enforce TERM then KILL-after-grace behavior: pass.
- Missing or malformed sidecars raise typed errors: pass.
- Packet-02 parser and packet-04 hook-resolution regressions still pass: pass.

## Notes

- The main repaired contract was sidecar naming. Without that fix, packet `05` would have validated against its own fixtures but not against the canonical worker protocol.
