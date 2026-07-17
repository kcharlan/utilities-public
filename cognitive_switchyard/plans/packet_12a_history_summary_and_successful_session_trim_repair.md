# Packet 12A - History Summary and Successful-Session Trim Repair

## Why This Packet Exists

Packet `12` delivered the SPA and History/Settings views, but the implementation path is still missing a design-required completion contract: successful sessions never emit `summary.json`, never trim down to the minimal retained artifact set, and the History flow still assumes completed sessions keep their full live task trees forever.

Packet `13` is about built-in packs, pack tooling, and operator documentation. It should not inherit or normalize the wrong storage/history model. This repair packet restores the completed-session contract before the project moves on.

## Scope

- Add the canonical successful-session summary artifact (`summary.json`) and write it as the last successful completion step before artifact trimming.
- Trim successful completed sessions down to the design-required retained artifact set:
  - `summary.json`
  - `resolution.json`
  - `logs/session.log`
- Keep failed, blocked-frontier, paused, and aborted sessions untrimmed.
- Expose history/session-final-state payloads from persisted summary data so packet-`12` History behavior no longer depends on untrimmed task directories and worker logs.
- Adjust the packet-`12` History flow so opening a completed session is a read-only history path backed by summary data, not a fallback into the live Monitor/task-log assumptions.
- Add regression coverage for successful completion summary emission, trimming idempotency, summary-backed history serialization, and packet-`12` history behavior after trim.

## Non-Goals

- No new pack schema, pack-author tooling, built-in-pack catalog work, or packet-`13` operator documentation.
- No release-notes generation workflow; if a release-notes artifact exists later, this packet only preserves room for it rather than inventing it now.
- No redesign of active-session monitor, setup, DAG, verification, or auto-fix behavior.
- No trimming of failed or aborted sessions; those remain full-fidelity debugging artifacts by design.

## Relevant Design Sections

- `5.1 Storage Model`
- `6.3.1.5 History View`
- `6.3.1.6 Settings View`
- `6.6 REST API Endpoints`
- `7.3 Orchestrator Loop`
- `10.5 Session State Machine`

## Allowed Files

- `cognitive_switchyard/config.py`
- `cognitive_switchyard/models.py`
- `cognitive_switchyard/state.py`
- `cognitive_switchyard/orchestrator.py`
- `cognitive_switchyard/server.py`
- `cognitive_switchyard/html_template.py`
- `tests/test_state_store.py`
- `tests/test_orchestrator.py`
- `tests/test_server.py`
- `tests/test_html_template.py`

## Tests To Write First

- `tests/test_state_store.py::test_successful_session_summary_round_trips_and_trim_preserves_only_history_artifacts`
- `tests/test_orchestrator.py::test_successful_session_completion_writes_summary_before_trimming_runtime_artifacts`
- `tests/test_orchestrator.py::test_blocked_or_aborted_sessions_do_not_trim_history_debug_artifacts`
- `tests/test_server.py::test_history_session_serialization_reads_summary_data_after_successful_trim`
- `tests/test_html_template.py::test_history_view_opens_trimmed_completed_session_without_requesting_live_task_log_streams`

## Implementation Notes

- Treat the summary artifact as part of the canonical runtime contract, not optional UI convenience data.
- Summary writing and successful-session trimming must be idempotent. Re-running the completion path or reading history after trim must not require the deleted task directories to exist.
- Preserve `resolution.json` and `logs/session.log` exactly where the design expects them. Remove worker logs, verification logs, and per-task state directories only for successful completed sessions.
- Keep the session list source in SQLite, but move completed-session detail/drill-down to summary-backed serialization once trim has occurred.
- Packet `12` already introduced the History UI. This repair should narrow that UI back onto the intended completed-session contract instead of widening backend semantics further.

## Acceptance Criteria

- Successful completed sessions write `summary.json` and retain only `summary.json`, `resolution.json`, and `logs/session.log` under the session directory.
- Failed, blocked, paused, and aborted sessions keep their existing full artifact trees unchanged.
- The backend can serialize completed-session history cards and read-only final-state detail from `summary.json` after trim without depending on deleted task plans or worker logs.
- The packet-`12` History flow can open a trimmed completed session and render its final-state information without falling back to live Monitor/task-log behavior.
- Existing packet-`12` setup/monitor/task-detail behavior for active sessions remains unchanged.

## Validation Focus

- `.venv/bin/python -m pytest tests/test_state_store.py tests/test_orchestrator.py -q`
- `.venv/bin/python -m pytest tests/test_server.py tests/test_html_template.py -q`
