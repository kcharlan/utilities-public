# Packet 00 Validation: Canonical Contracts and Scaffold

Date: 2026-03-09
Packet doc: `plans/packet_00_canonical_contracts_and_scaffold.md`
Result: `validated`

## Scope Check

- Reviewed only the packet-00 scaffold surface and tracker/docs updates:
  - `switchyard`
  - `cognitive_switchyard/__init__.py`
  - `cognitive_switchyard/__main__.py`
  - `cognitive_switchyard/cli.py`
  - `tests/test_bootstrap_smoke.py`
  - `tests/test_fixture_baseline.py`
  - `tests/fixtures/*`
  - `README.md`
- The implementation stayed inside the packet boundary. No scheduler, state store, subprocess, API, or UI behavior was introduced.

## Reference Provenance Check

- `tests/fixtures/plan_reference_minimal.plan.md` is a curated slice of [reference/work/execution/done/001_clean_acr_loop.plan.md](/Users/example/source/utilities/cognitive_switchyard/reference/work/execution/done/001_clean_acr_loop.plan.md).
- `tests/fixtures/status_reference_minimal.status` is a curated slice of [reference/work/execution/done/001_clean_acr_loop.status](/Users/example/source/utilities/cognitive_switchyard/reference/work/execution/done/001_clean_acr_loop.status).
- `tests/fixtures/resolution_reference_minimal.md` is a curated slice of [reference/work/execution/RESOLUTION.md](/Users/example/source/utilities/cognitive_switchyard/reference/work/execution/RESOLUTION.md).
- `tests/fixtures/pack_manifest_minimal.yaml` is derived from design doc sections 4.1-4.2 in [docs/cognitive_switchyard_design.md](/Users/example/source/utilities/cognitive_switchyard/docs/cognitive_switchyard_design.md#L193).

## Findings

### 1. Weak contract tests left legacy-name regressions under-constrained

- Severity: Low
- Status: Fixed during validation
- Evidence:
  - [tests/test_bootstrap_smoke.py](/Users/example/source/utilities/cognitive_switchyard/tests/test_bootstrap_smoke.py)
  - [tests/test_fixture_baseline.py](/Users/example/source/utilities/cognitive_switchyard/tests/test_fixture_baseline.py)
- Problem:
  - The original smoke tests proved the happy-path help output, but they did not directly pin the exported canonical constants, did not assert legacy runtime names stayed absent, and did not verify fixture provenance headers.
  - That made packet-00 drift easier: a future edit could reintroduce `~/.switchyard` references or silently replace curated fixtures with unattributed copies while still passing the original tests.
- Repair:
  - Added direct assertions for `PACKAGE_NAME`, `RUNTIME_HOME`, and `BOOTSTRAP_VENV`.
  - Added a `paths` subcommand smoke test.
  - Added negative assertions to keep `~/.switchyard` and `~/.switchyard_venv` out of the supported help surface.
  - Added provenance-header assertions for the curated fixture corpus.

## Validation Runs

- Passed: `.venv/bin/python -m pytest tests/test_bootstrap_smoke.py tests/test_fixture_baseline.py -v`
- Passed: `./switchyard --help`
- Passed: `./switchyard paths`
- Passed: `.venv/bin/python -m cognitive_switchyard --help`

## Acceptance Criteria Review

- `./switchyard --help` no longer fails with `ModuleNotFoundError`: pass.
- `python -m cognitive_switchyard --help` succeeds from repo root: pass.
- `tests/` exists and contains the packet smoke tests: pass.
- `tests/fixtures/` contains the minimal curated corpus for packets 01 and 02: pass.
- Canonical naming/runtime-path choices are enforced by code/tests, not only prose: pass.

## Outcome

Packet 00 is acceptable and now sufficiently pinned for later packets. Tracker status should be `validated`.
