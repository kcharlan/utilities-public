# Drift Audit After Packet 13

Date: 2026-03-10
Audit label: `drift audit after packet 13`
Highest validated packet: `13`
Validated packet count: `19`
Overall result: `repair_now`

## Scope

Reviewed during this audit:

- `docs/implementation_packet_playbook.md`
- `plans/packet_status.md`
- `plans/packet_status.json`
- Validated packet docs `plans/packet_00_canonical_contracts_and_scaffold.md` through `plans/packet_13_claude_cli_agent_runtime_and_builtin_claude_code_pack.md`
- Relevant design sections now in scope through packet `13`, especially:
  - `3.2`-`3.6`
  - `4.1`-`4.5`
  - `5.1`-`5.3`
  - `6.1`-`6.6`
  - `7.1`-`7.5`
  - `10.5`-`10.7`
  - `11`
  - `1466`
- Live code under `cognitive_switchyard/`, `tests/`, and `switchyard`
- Existing audit artifacts affecting this review:
  - `audits/drift_audit_after_packet_11d.md`
  - `audits/drift_audit_after_packet_12.md`
  - `audits/drift_audit_after_packet_12a.md`
  - `audits/packet_13_claude_cli_agent_runtime_and_builtin_claude_code_pack_validation.md`
  - `audits/drift_audit_state.json`

## What Still Aligns

- The validated frontier is still packet `13`; I did not find packet-`14` authoring commands, `RELEASE_NOTES.md` generation, history release-notes UI, or operator-doc scope pulled forward into live code.
- The packet-`11A` through `13` repair chain remains intact:
  - runtime-driven backend events still feed the packet-`11` transport seam
  - setup/preflight/runtime override contracts remain backend-owned
  - successful-session history still trims to the packet-`12A` retained artifact set
  - CLI and backend start paths still default to the packet-`13` Claude runtime for agent-enabled phases
- `plans/packet_status.json` and the packet ladder still correctly identify packet `13` as the highest validated frontier and packet `14` as the next planned packet.

## Finding

### 1. Medium: trimmed completed-session history was still partially derived from the mutable live pack manifest

Evidence before repair:

- The design requires successful-session history to be summary-backed after trim so History/detail rendering no longer depends on live runtime artifacts (`docs/cognitive_switchyard_design.md:396-412`, `docs/cognitive_switchyard_design.md:947-955`).
- Packet `12A` narrowed the contract the same way: completed-session history/detail should be served from persisted summary data after trim, not from transient runtime state (`plans/packet_12a_history_summary_and_successful_session_trim_repair.md:17-18`, `plans/packet_12a_history_summary_and_successful_session_trim_repair.md:60-64`).
- Before repair, `StateStore.write_successful_session_summary(...)` persisted `config` and task summaries but did not snapshot `effective_runtime_config` into `summary.json` (`cognitive_switchyard/state.py` before lines `562-643`).
- The packet-`12A` server path already tried to consume `summary["session"]["effective_runtime_config"]`, but if it was absent it silently rebuilt the value from the *current* runtime pack manifest (`cognitive_switchyard/server.py:828-846`).

Why this mattered:

- Completed-session history was still not fully canonical after trim.
- Editing a runtime pack after a session completed could change the historical worker/planner/timeouts view for that already-finished session.
- This is cumulative drift across packet `12A` and packet `13`: the delivery system had the right summary-backed history shape, but not the final immutable contract for completed-session runtime settings.

## Repair Applied Now

I repaired the drift inline.

Applied changes:

- `cognitive_switchyard/state.py` now snapshots the session's effective runtime config into `summary.json` when writing the successful-session summary.
- `tests/test_state_store.py` now verifies the persisted summary includes the expected effective runtime config snapshot.
- `tests/test_server.py` now verifies trimmed history continues to serve the original effective runtime config even if the live runtime pack manifest is changed afterward.

This keeps packet `14` cleanly scoped: immutable completed-session history remains a packet-`12A`/`13` runtime concern, while release notes and pack-author tooling still stay in the next packet.

## Validation

Reran targeted validation after the repair:

- `.venv/bin/python -m pytest tests/test_state_store.py tests/test_server.py -q`
  - Result: `35 passed in 4.80s`

## Residual Note

- `README.md` and the prose lead-in of `plans/packet_status.md` still contain small frontier-description drift around packet `13`, but the canonical tracker fields (`highest validated packet`, JSON tracker, ladder rows) are correct. I did not mutate packet trackers because this audit is not returning `repair_packet`.

## Conclusion

The meaningful cumulative drift after packet `13` was not new UI or pack-tooling leakage. It was that trimmed completed-session history still depended on the mutable current pack manifest for effective runtime settings, which weakened the packet-`12A` summary-backed history contract. The repair was small, architecturally unambiguous, and safely contained, so `repair_now` was the correct result.
