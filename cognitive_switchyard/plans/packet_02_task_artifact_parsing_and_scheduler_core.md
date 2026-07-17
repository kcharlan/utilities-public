# Packet 02: Task Artifact Parsing and Scheduler Core

## Why This Packet Exists

The orchestrator's dispatch behavior depends on correct parsing of task artifacts and on deterministic eligibility logic. That logic is pure and testable; it should be finished before introducing SQLite, workers, or crash recovery.

## Scope

- Implement parsing for:
  - plan metadata headers used by execution tasks
  - status sidecar files
  - progress lines (`Phase:` and `Detail:` variants)
  - `resolution.json`
- Implement typed task/constraint models needed by the scheduler.
- Implement pure scheduler functions for:
  - determining whether a task is eligible
  - selecting the next task by `EXEC_ORDER` then task ID
  - enforcing `DEPENDS_ON`
  - enforcing `ANTI_AFFINITY`
- Add tests using the fixture corpus from packet `00` plus any packet-local synthetic scheduler cases.

## Non-Goals

- No filesystem moves.
- No SQLite or persistence layer.
- No subprocess management or timeout handling.
- No orchestration loop.
- No planner or resolver process launching.
- No API/UI code.

## Relevant Design Sections

- `3.3` Resolution behavior and modes
- `3.4` Execution eligibility rules and constraint enforcement
- `4.3` Lifecycle hook progress protocol
- `4.4` Status sidecar format
- `5.2`-`5.3` File-as-state mapping and constraint graph JSON
- `6.5` WebSocket payload expectations for progress detail
- `10.6` Idempotency table for dispatch/state transitions
- `11` Reference material for plan/status examples

## Allowed Files

- `cognitive_switchyard/models.py`
- `cognitive_switchyard/parsers.py`
- `cognitive_switchyard/scheduler.py`
- `tests/test_parsers.py`
- `tests/test_scheduler.py`
- `tests/fixtures/tasks/**`

Do not create `state.py`, `worker_manager.py`, `orchestrator.py`, or server/UI files in this packet.

## Tests To Write First

1. A failing parser test for a real or curated plan fixture that extracts task ID, title, dependency metadata, anti-affinity metadata, execution order, and optional full-test flags.
2. A failing parser test for valid and malformed status sidecar fixtures.
3. A failing parser test for `##PROGRESS## ... | Phase: ...` and `##PROGRESS## ... | Detail: ...` lines.
4. A failing parser test for `resolution.json` into typed task constraints.
5. A failing scheduler test that confirms dependencies block execution until all upstream tasks are done.
6. A failing scheduler test that confirms active anti-affinity peers block execution.
7. A failing scheduler test that confirms stable next-task ordering is `EXEC_ORDER`, then task ID.

## Implementation Notes

- Keep scheduler functions pure. They should accept typed task/constraint inputs and return results without touching the filesystem or database.
- Parsing functions should raise typed, packet-local errors on malformed inputs rather than returning partial silent results.
- If reference plan files contain extra metadata not needed yet, parse only the fields required by the design doc and preserve the remainder as opaque body content.
- Treat parser normalization as part of the contract. Later packets should consume normalized structures, not re-parse raw text ad hoc.

## Acceptance Criteria

- Realistic plan, status, progress, and resolution fixtures parse into typed structures.
- Malformed task artifacts fail predictably with explicit tests.
- Scheduler eligibility and task selection are deterministic and fully covered by packet-scoped tests.
- `scheduler.py` remains pure logic with no imports from subprocess, SQLite, FastAPI, or filesystem-mutation modules.

## Validation Focus

- Confirm parser outputs line up with the execution and WebSocket contracts in the design doc.
- Confirm the packet did not smuggle in persistence or worker runtime behavior.
- Confirm scheduler tests cover both positive and blocking cases for dependencies and anti-affinity.
