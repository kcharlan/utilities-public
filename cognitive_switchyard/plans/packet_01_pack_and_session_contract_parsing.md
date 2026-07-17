# Packet 01: Pack and Session Contract Parsing

## Why This Packet Exists

The orchestrator depends on stable pack manifests and stable session-directory mapping. Those are contracts, not runtime behavior. They should be implemented and validated before any worker, DB, or orchestration logic exists.

## Scope

- Implement canonical runtime path/config helpers using the names frozen in packet `00`.
- Implement typed models for pack manifests and session configuration.
- Implement `pack.yaml` loading, defaulting, and validation.
- Resolve referenced prompt/script/template paths safely inside a pack directory.
- Implement session-directory helper functions for the standard filesystem layout.
- Return structured validation errors for malformed pack manifests.

## Non-Goals

- No subprocess execution of hooks.
- No executable-bit enforcement side effects beyond pure validation results.
- No SQLite access.
- No task plan/status parsing.
- No scheduler dispatch logic.
- No built-in pack syncing.

## Relevant Design Sections

- `4.1`-`4.5` Pack directory structure, schema, hook contracts, status format, distribution
- `5.1`-`5.2` Session artifact layout and file-as-state mapping
- `7.1`-`7.2` Backend module structure and bootstrap assumptions
- `10.7` Pack-author idempotency requirements

## Allowed Files

- `cognitive_switchyard/config.py`
- `cognitive_switchyard/models.py`
- `cognitive_switchyard/pack_loader.py`
- `tests/test_config.py`
- `tests/test_pack_loader.py`
- `tests/fixtures/packs/**`
- `README.md`

Avoid creating worker/orchestrator/state/API files in this packet.

## Tests To Write First

1. A failing config test that asserts the runtime home, venv, DB, packs, and session paths use the canonical `cognitive_switchyard` names.
2. A failing config test that asserts `session_subdirs()` returns the exact directory set from the design doc.
3. A failing pack-loader test that loads a valid manifest fixture and applies documented defaults.
4. A failing pack-loader test that rejects an invalid manifest fixture with a structured, readable error.
5. A failing path-resolution test that rejects manifest references escaping the pack root.

## Implementation Notes

- Keep validation deterministic and side-effect free.
- Prefer dataclasses or equivalent typed containers over loose dicts for manifest/config results.
- Resolve all referenced paths relative to the pack root, then verify the resolved path still lives under that root.
- It is acceptable for executable-bit checks to return validation findings in this packet; actual session-start enforcement belongs later with preflight/runtime behavior.
- If a field is executor-specific, validate it only when that executor mode is selected.

## Acceptance Criteria

- The project has a canonical config/path module rooted at `~/.cognitive_switchyard`.
- A valid `pack.yaml` fixture loads into typed structures with documented defaults applied.
- Invalid manifests fail with packet-scoped tests that name the exact schema issue.
- Session subdirectory helpers match the design doc exactly.
- The implementation remains pure parsing/validation logic with no subprocess or DB usage.

## Validation Focus

- Confirm every path contract is consistent with packet `00`.
- Confirm validation errors are specific enough for future pack authors to act on.
- Confirm no runtime side effects were added just to make tests pass.
