# Packet 14 - Pack Tooling, Release Notes, and Operator Docs

## Why This Packet Exists

After packet `13`, Cognitive Switchyard should finally have a real bundled reference pack and a real Claude-backed runtime path. The remaining gap is handoff usability: the project still lacks the design's pack scaffolding and validation commands, still lacks durable operator-facing release notes for completed sessions, and still has no authored documentation for pack builders or operators.

This packet is the final handoff surface. It turns the validated engine into something another human can create packs for, operate locally, and understand without reverse-engineering the repository.

## Scope

- Add `switchyard init-pack <name>` to scaffold a new runtime pack directory with a minimal but valid pack skeleton:
  - `pack.yaml`
  - `README.md`
  - `prompts/`
  - `scripts/`
  - `templates/`
- Add `switchyard validate-pack <path>` to report pack-authoring failures before a session starts:
  - manifest/schema errors
  - missing referenced files
  - non-executable scripts
  - text hook scripts missing a shebang
  - invalid `status.progress_format` regex
- Generate session-level `RELEASE_NOTES.md` for successful sessions from completed-plan `## Operator Actions` sections before trim occurs.
- Preserve `RELEASE_NOTES.md` in the successful-session retained artifact set and expose it through the History/detail backend and read-only SPA history flow only when present.
- Add the missing authored docs:
  - pack author guide
  - user/operator guide
  - built-in `claude-code` pack guide
  - README pointers to the new docs and commands

## Non-Goals

- No new orchestration phases, no new transport layers, and no new UI views.
- No remote pack registry, marketplace, or install-from-URL flow.
- No additional built-in packs beyond the packet-`13` `claude-code` reference pack.
- No generalized post-session hook system; release-notes generation in this packet is the concrete session artifact required by the current design and reference workflow.
- No changes to Claude runtime semantics beyond what packet `13` established.

## Relevant Design Sections

- `4.1 Pack Directory Structure`
- `4.2 pack.yaml Schema`
- `4.3 Lifecycle Hook Contracts`
- `4.5 Pack Distribution`
- `6.3.1.5 History View`
- `7.1 Module Structure`
- `7.2 Self-Bootstrapping`
- `10.7 Implementation Requirements for Pack Authors`
- `Post-Implementation Deliverables`

## Allowed Files

- `README.md`
- `docs/pack_author_guide.md`
- `docs/operator_guide.md`
- `docs/builtin_claude_code_pack.md`
- `cognitive_switchyard/cli.py`
- `cognitive_switchyard/pack_loader.py`
- `cognitive_switchyard/parsers.py`
- `cognitive_switchyard/models.py`
- `cognitive_switchyard/config.py`
- `cognitive_switchyard/state.py`
- `cognitive_switchyard/orchestrator.py`
- `cognitive_switchyard/server.py`
- `cognitive_switchyard/html_template.py`
- `tests/test_cli.py`
- `tests/test_pack_loader.py`
- `tests/test_orchestrator.py`
- `tests/test_server.py`
- `tests/test_html_template.py`

## Tests To Write First

- `tests/test_cli.py::test_init_pack_creates_runtime_scaffold_with_expected_contract_files_and_executable_placeholders`
- `tests/test_cli.py::test_validate_pack_reports_manifest_reference_permission_shebang_and_regex_failures`
- `tests/test_orchestrator.py::test_successful_session_generates_release_notes_before_trim_and_retains_them_after_trim`
- `tests/test_server.py::test_history_session_detail_includes_release_notes_when_trimmed_session_retains_artifact`
- `tests/test_html_template.py::test_history_view_renders_release_notes_panel_for_completed_session_detail`

## Implementation Notes

- `init-pack` should scaffold into the runtime packs directory by default so the generated pack is immediately discoverable by the existing CLI/backend surfaces.
- The scaffold should be validator-clean on creation. Do not require the user to `chmod +x` or create missing placeholder files before the generated pack can even be inspected.
- Reuse existing manifest parsing logic for `validate-pack` instead of inventing a second schema checker. Add validator-specific checks on top of `load_pack_manifest()` findings.
- Shebang validation should apply only to text executables that the orchestrator would invoke directly. Do not reject compiled/native executables simply because they do not begin with `#!`.
- Release notes should be derived from plan content already in the session tree. Parse the completed plans' `## Operator Actions` sections, write a deterministic `RELEASE_NOTES.md`, and preserve it alongside `summary.json`, `resolution.json`, and `logs/session.log`.
- History/detail backend payloads and the packet-`12` History UI should treat release notes as optional. Active-session monitor behavior must remain unchanged.
- All new docs must use the canonical `cognitive_switchyard` package name and `~/.cognitive_switchyard*` runtime paths, not the design doc's legacy `switchyard`/`~/.switchyard` names.

## Acceptance Criteria

- `switchyard init-pack <name>` creates a discoverable runtime pack scaffold whose files and permissions match the documented pack contract.
- `switchyard validate-pack <path>` exits successfully for a valid pack and returns actionable non-zero diagnostics for schema, missing-file, permission, shebang, and progress-regex errors.
- Successful completed sessions write `RELEASE_NOTES.md` before trimming, retain it after trim, and expose it through history/detail serialization without requiring deleted live task artifacts.
- The packet-`12` History flow renders release notes for completed sessions when the artifact exists and remains read-only for trimmed sessions.
- Repository docs exist for pack authors, operators, and the bundled `claude-code` pack, and the README links to them plus the new CLI commands.

## Validation Focus

- `.venv/bin/python -m pytest tests/test_cli.py tests/test_pack_loader.py -q`
- `.venv/bin/python -m pytest tests/test_orchestrator.py tests/test_server.py tests/test_html_template.py -q`
