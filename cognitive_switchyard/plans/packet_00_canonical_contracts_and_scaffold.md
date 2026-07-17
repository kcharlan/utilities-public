# Packet 00: Canonical Contracts and Scaffold

## Why This Packet Exists

The repository currently has contradictory naming/path guidance and a broken launcher. No later packet is safe until the project has one canonical package name, one canonical runtime home, an importable Python skeleton, and a stable fixture/test baseline.

## Scope

- Freeze the canonical implementation names in code and tests:
  - package: `cognitive_switchyard`
  - launcher: `switchyard`
  - runtime home: `~/.cognitive_switchyard`
  - bootstrap venv: `~/.cognitive_switchyard_venv`
- Create the minimal importable package and CLI/help scaffold needed for later packets.
- Repair the root `switchyard` launcher so it imports the real package.
- Create the initial `tests/` tree and a small curated fixture corpus under `tests/fixtures/`.
- Capture only the reference artifacts needed by the next packets:
  - at least 1 plan fixture
  - at least 1 status sidecar fixture
  - at least 1 resolution fixture
  - at least 1 pack-manifest fixture

## Non-Goals

- No SQLite schema or state store.
- No scheduler logic beyond placeholder imports.
- No subprocess execution, preflight, or hook invocation.
- No planning/resolution runtime.
- No REST, WebSocket, or UI code.
- No attempt to make the system operational beyond import/help/test scaffold.

## Relevant Design Sections

- `4.1`-`4.5` Runner pack structure and pack contracts
- `5.1`-`5.3` Storage model, file-as-state mapping, constraint graph
- `7.1`-`7.2` Module structure and self-bootstrapping
- `10.5`-`10.7` Session states and idempotency requirements
- `11` Reference material for implementing agents

## Allowed Files

- `switchyard`
- `cognitive_switchyard/__init__.py`
- `cognitive_switchyard/__main__.py`
- `cognitive_switchyard/cli.py`
- `tests/__init__.py`
- `tests/conftest.py`
- `tests/test_bootstrap_smoke.py`
- `tests/test_fixture_baseline.py`
- `tests/fixtures/**`
- `README.md`

Do not modify design docs, runtime logic modules, or `reference/`.

## Tests To Write First

1. A failing smoke test that imports `cognitive_switchyard`.
2. A failing smoke test that invokes `python -m cognitive_switchyard --help` successfully.
3. A failing test that runs `./switchyard --help` and asserts it exits cleanly.
4. A failing fixture-baseline test that asserts the curated fixture files exist under `tests/fixtures/` and are readable.

## Implementation Notes

- Keep the initial CLI surface minimal: enough for `--help` and a placeholder subcommand structure, but do not stub behavior that belongs to later packets.
- Use the root launcher as the supported executable surface and keep it thin.
- Curate, do not bulk-copy, reference artifacts. Prefer a tiny corpus with filenames that indicate what each fixture validates.
- If README examples still mention the now-invalid state, update only the package/home naming and current bootstrap reality.

## Acceptance Criteria

- `./switchyard --help` no longer fails with `ModuleNotFoundError`.
- `python -m cognitive_switchyard --help` succeeds from the repo root.
- `tests/` exists and contains the packet's smoke tests.
- `tests/fixtures/` exists and contains the minimal curated corpus needed by packets `01` and `02`.
- The canonical naming/runtime-path choices are enforced by code/tests, not left implicit in prose only.

## Validation Focus

- Make sure this packet does not leak into config parsing, scheduling, or runtime behavior.
- Confirm fixture copies are minimal and traced back to either the design doc or `reference/`.
- Confirm the launcher/package naming is internally consistent with the repo after the change.
