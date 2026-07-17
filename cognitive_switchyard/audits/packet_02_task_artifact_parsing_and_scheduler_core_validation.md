# Packet 02 Validation Audit

Date: 2026-03-09
Status: `validated`
Packet: `plans/packet_02_task_artifact_parsing_and_scheduler_core.md`

## Scope Check

The packet-02 implementation remains inside the allowed file surface:

- `cognitive_switchyard/models.py`
- `cognitive_switchyard/parsers.py`
- `cognitive_switchyard/scheduler.py`
- `tests/test_parsers.py`
- `tests/test_scheduler.py`
- `tests/fixtures/tasks/*`

No state-store, worker, orchestrator, API, or UI modules were added or modified during validation.

## Reference And Boundary Check

- The packet-local task fixtures are curated from the referenced production artifacts:
  - `tests/fixtures/tasks/plan_with_constraints.plan.md` from `reference/work/execution/done/039_fix_chunk_progress_verification.plan.md`
  - `tests/fixtures/tasks/status_blocked.status` from design-doc section 4.4
  - `tests/fixtures/tasks/resolution_minimal.json` from the design-doc JSON contract in section 5.3, aligned with the real dependency report in `reference/work/execution/RESOLUTION.md`
- Spot-check validation confirmed that all current `reference/work/execution/done/*.plan.md` files parse successfully under the packet-02 plan parser.
- Five legacy `reference/work/execution/done/*.status` files still use pre-contract formats (`COMMIT`/`TESTS` or bare `DONE` markers) that do not match the canonical 4.4 sidecar schema. They were not promoted into packet fixtures because they omit required normalized fields.

## Issues Found And Repaired

1. Phase progress parsing accepted impossible counters.
   - `parse_progress_line()` accepted invalid phase markers such as `0/5`, `6/5`, and `1/0`.
   - Repaired in `cognitive_switchyard/parsers.py` by enforcing `phase_total >= 1` and `1 <= phase_index <= phase_total`.

2. Plan-list validation reported the wrong artifact type.
   - Malformed YAML-list `DEPENDS_ON` / `ANTI_AFFINITY` metadata raised `resolution` errors even though the artifact being parsed was a task plan.
   - Repaired in `cognitive_switchyard/parsers.py` by threading the artifact type through shared list parsing helpers.

## Test Coverage Strengthened

- Added a parser test proving YAML-list constraint metadata is accepted and normalized.
- Added parser tests proving invalid phase counters fail explicitly.
- Added a parser test proving malformed plan-list constraints raise `plan`-scoped errors.

## Validation Run

Commands run from repo root:

```bash
.venv/bin/python -m pytest tests/test_parsers.py tests/test_scheduler.py -v
.venv/bin/python -m pytest tests/test_config.py tests/test_pack_loader.py tests/test_fixture_baseline.py -v
.venv/bin/python -m pytest tests -v
./switchyard paths
```

Result:

- `29` tests passed in the full current suite
- Packet-02 parser and scheduler tests passed after the validation repairs
- Adjacent packet-00 and packet-01 regression checks passed
- Canonical path smoke check passed

## Acceptance Criteria Result

- Realistic plan, status, progress, and resolution fixtures parse into typed structures: pass
- Malformed task artifacts fail predictably with explicit tests: pass
- Scheduler eligibility and next-task selection remain deterministic and packet-scoped: pass
- `scheduler.py` remains pure logic with no subprocess, SQLite, FastAPI, or filesystem-mutation behavior: pass

## Outcome

Packet `02` is acceptable and should be tracked as `validated`.
