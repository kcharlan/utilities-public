# Cognitive Switchyard Implementation Packet Playbook

## Purpose

This playbook converts `docs/cognitive_switchyard_design.md` into a packetized delivery system for Cognitive Switchyard. It is written for future planner, implementer, and validator agents so they can work packet-by-packet without re-planning the whole project each turn.

The repository is currently a planning scaffold, not a working engine. The packet ladder must therefore start by fixing contract ambiguity and establishing fixtures before any stateful runtime work.

## Current Repository Baseline

Assessed on 2026-03-09 from the live repository state:

- Present: design docs, implementation plan, automation helpers under `scripts/`, a root `switchyard` launcher, `requirements.txt`, and read-only `reference/` artifacts.
- Missing: importable `cognitive_switchyard` package, tests, built-in packs, state store, orchestrator, FastAPI server, UI.
- Verified failure state:
  - `./switchyard --help` fails with `ModuleNotFoundError: No module named 'cognitive_switchyard'`.
  - `.venv/bin/python -m pytest tests -v` fails because `tests/` does not exist.
- Interpretation rule: README and design-doc claims about implemented phases are not delivery evidence. The codebase state is the source of truth.

## Canonical Contract Decisions

The design materials contain naming inconsistencies. Future agents must implement these canonical choices unless a later packet explicitly changes them:

- Python package name: `cognitive_switchyard`
- Root user-facing launcher in the repo: `switchyard`
- Python module entrypoint: `python -m cognitive_switchyard`
- Runtime home directory: `~/.cognitive_switchyard`
- Private bootstrap venv: `~/.cognitive_switchyard_venv`
- The design doc's `switchyard/` package path and `~/.switchyard` runtime path are treated as legacy names and must not be implemented as-is.

Packet `00` is responsible for freezing these contracts in code/tests so later packets do not drift.

## Model Assignment

- Planner: `xhigh` until packet `00` is validated, then `high`
  - Reason: the repo currently disagrees with the design doc on package/runtime naming, and the first packet must resolve those contracts cleanly.
- Implementer: `medium` for packets `00`-`05`, `high` for packets `06`-`13`
  - Reason: early packets are intentionally narrow and parser-heavy; later packets introduce threads, subprocesses, recovery, REST, and UI.
- Validator: `high` for every packet, `xhigh` for packets `07`, `11`, and `12`
  - Reason: recovery, backend concurrency, and SPA/WS synchronization are the highest-regression areas.
- Drift auditor: `high` for routine audits, `xhigh` when the last audit result required repair work or when auditing after packets `07`, `11`, or `12`
  - Reason: drift audits are cumulative architecture checks rather than packet-local reviews and need stronger judgment when the run is already showing signs of drift.

## Packet Rules

- One behavior family per packet.
- Do not mix a new runtime semantic with a new integration surface.
- Do not mix filesystem recovery with first-pass execution.
- Do not mix API work with UI work.
- Keep worker/subprocess concerns out of packets that are still establishing contracts and parsers.
- Prefer reference-derived fixtures over ad hoc fake formats whenever a parser is introduced.
- Keep packet-scoped validation executable from the repo root.
- If a packet needs more than 3 new modules and more than 1 new external interaction surface, split it.

## Canonical Packet Ladder

| ID | Name | Why This Boundary Exists |
|---|---|---|
| `00` | Canonical Contracts and Scaffold | Resolve naming/path contradictions, create package/test skeleton, and pin fixture corpus. |
| `01` | Pack and Session Contract Parsing | Encode pack manifest rules and session directory mapping without runtime side effects. |
| `02` | Task Artifact Parsing and Scheduler Core | Implement pure parsing and dispatch eligibility logic before DB/process orchestration. |
| `03` | SQLite State Store and Filesystem Projection | Build the query/update layer once contracts and scheduler inputs are stable. |
| `04` | Pack Hook Runner and Preflight | Add executable/script invocation and prerequisite validation without worker orchestration yet. |
| `05` | Worker Slot Lifecycle and Timeout Monitoring | Isolate subprocess lifecycle, log capture, progress parsing, and timeout handling. |
| `06` | Execution Orchestrator Loop | Combine state store, scheduler, hooks, and workers into the execution pipeline only. |
| `07` | Crash Recovery and Reconciliation | Add idempotent restart, orphan cleanup, and state reconciliation after first-pass execution works. |
| `08` | Planning and Resolution Runtime | Add planner/resolver phases after the execution engine is stable. |
| `09` | Verification and Auto-Fix Loop | Add batch verification and fixer retries after planning/execution semantics are stable. |
| `10` | CLI, Bootstrap, and Built-In Pack Sync | Finalize user-facing startup/bootstrap once engine internals are proven. |
| `11` | FastAPI REST and WebSocket Backend | Expose stable engine state over HTTP/WS without UI concerns. |
| `12` | Embedded React SPA Monitor | Build the SPA once REST/WS contracts exist. |
| `13` | Built-In Packs, Pack Tooling, and Operator Docs | Prove generality and ship pack author/operator workflows last. |

## Recommended Starting Horizon

- Horizon now: `3` packets (`00`-`02`)
- Horizon after packet `02` is validated: `2` packets at a time
- Implementation unit: `1` packet
- Validation unit: `1` packet

Do not expand the next horizon until the current highest packet is validated and the trackers are updated.

## Repository Artifacts and Trackers

- Packet playbook: `docs/implementation_packet_playbook.md`
- Human tracker: `plans/packet_status.md`
- Machine tracker: `plans/packet_status.json`
- Packet docs: `plans/packet_XX_<slug>.md`
- Preferred fixture location for implementation packets: `tests/fixtures/`
- Read-only reference material: `reference/`
- Drift audit reports: `audits/drift_audit_*.md`
- Drift audit machine output: `audits/drift_audit_*.json`
- Drift audit scheduler state: `audits/drift_audit_state.json`

Automation scripts under `scripts/` help run planning loops, but they are not substitutes for the packet tracker or packet docs.

## Required Packet Template

Every packet doc must contain these sections, in this order:

1. `Why This Packet Exists`
2. `Scope`
3. `Non-Goals`
4. `Relevant Design Sections`
5. `Allowed Files`
6. `Tests To Write First`
7. `Implementation Notes`
8. `Acceptance Criteria`
9. `Validation Focus`

If any of those sections cannot be written concretely, the packet is too large.

## Planning Procedure

1. Read this playbook.
2. Read `plans/packet_status.md` and `plans/packet_status.json`.
3. Inspect the actual codebase state for the packet and its dependencies.
4. Open only the packet doc(s) within the current horizon.
5. Inspect `reference/work/` for artifacts relevant to the packet horizon.
6. If the tracker overstates completion, downgrade the packet status before planning more work.
7. Only generate or revise the next 2-3 packet docs, never a full-project detailed rewrite.
8. Preserve the canonical contract decisions unless the packet explicitly exists to change them.

## Implementation Procedure

1. Read this playbook.
2. Read exactly one packet doc to implement.
3. Read only the design-doc sections listed in that packet.
4. Inspect current files inside the packet's allowed file set.
5. Inspect any packet-relevant artifacts under `reference/work/`.
6. Write the packet's tests first.
7. Implement only enough code to satisfy the packet's acceptance criteria.
8. Run the packet-scoped validation commands.
9. Update `plans/packet_status.md` and `plans/packet_status.json` to `implemented` only if tests pass; use `blocked` with notes otherwise.

## Validation Procedure

1. Read this playbook.
2. Read the target packet doc and its acceptance criteria.
3. Confirm the implementation stayed inside the packet's allowed file set.
4. Verify any claimed `reference/work/` usage against the referenced artifacts.
5. Re-run the packet's tests and one adjacent smoke check where relevant.
6. Check for regressions against earlier packet contracts and fixture formats.
7. Mark the packet `validated` only if all acceptance criteria and validation checks pass.

## Full-Suite Verification Procedure

Run a repo-wide full-suite verification pass:

- Every `3` newly validated packets during the automation loop
- Immediately after any cumulative drift audit that returns `repair_now`
- At project completion, even if the normal interval is not due

Default verification command for this repository:

- `.venv/bin/python -m pytest tests -v`

Rules:

- This is separate from packet-local validation.
- The goal is cumulative regression detection across the whole validated frontier.
- If the full-suite pass fails, treat it as a real regression signal rather than a packet-local inconvenience.
- Do not replace the full-suite pass with a narrower subset just because the current packet passed locally.

## Drift Audit Procedure

Run a cumulative drift audit:

- Every `3` newly validated packets during the automation loop
- At project completion, even if the normal interval is not due

The drift audit checks cumulative alignment between:

- `docs/cognitive_switchyard_design.md`
- this playbook
- validated packet docs
- live code and trackers

The drift audit is not packet validation. It looks for architecture drift, packet boundary erosion, stale tracker state, and places where cumulative implementation is diverging from the intended delivery system.

Each drift audit writes:

- `audits/drift_audit_<label>.md`
- `audits/drift_audit_<label>.json`

The JSON result must use:

- `status`: `pass` | `repair_now` | `repair_packet` | `halt`
- `severity`: `low` | `medium` | `high`
- `effort`: `small` | `medium` | `high`

Decision rules:

- `pass`: no meaningful drift
- `repair_now`: the issue is technically bounded and architecturally unambiguous enough to repair immediately, even if it touches earlier validated packets
- `repair_packet`: the issue is still unambiguous, but it should land as a dedicated repair packet inserted immediately after the validated frontier
- `halt`: only for strategic ambiguity, major contract re-baselining, or other changes that would redefine the intended path
- Repair packet IDs must sort immediately after the validated frontier using the same numeric prefix plus an uppercase suffix, for example `11A` after `11` and before `12`.

Tracker rule:

- The drift audit must not change `plans/packet_status.md` or `plans/packet_status.json` unless it is explicitly returning `repair_packet`.
- If it returns `repair_packet`, it must create a narrowly scoped repair packet doc, update both trackers, and ensure that repair packet becomes the next actionable packet.

## Escalation Rules

Escalate instead of improvising when any of these happen:

- A packet requires changing the canonical naming/runtime path choices from this playbook.
- The design doc and real code disagree on a behavior that affects persistence, recovery, or public API shape.
- A packet needs both subprocess/runtime behavior and new API/UI work.
- A parser packet cannot be verified with stable fixtures or reference artifacts.
- A recovery packet cannot prove idempotency with a deterministic test harness.
- A validator finds that a supposedly completed dependency packet never had passing tests.
- A drift finding implies a strategic operator choice rather than an implementable correction.

When escalating, present 2-3 narrow alternatives and state which packet boundary is wrong.

## Planner Prompt

```text
Read `docs/implementation_packet_playbook.md` first and follow it exactly.

Task:
Plan the next packet horizon for Cognitive Switchyard using the live repository state.

Instructions:
- Read `plans/packet_status.md` and `plans/packet_status.json`.
- Inspect the codebase to verify the status of the next unvalidated packets.
- Read only the packet docs inside the current horizon.
- If tracker state and code disagree, fix the trackers first.
- Create or update only the next 2 packet docs after the highest validated packet.
- Keep packets narrow and consistent with the canonical ladder in the playbook.
```

## Implementer Prompt

```text
Read `docs/implementation_packet_playbook.md` first and follow it exactly.

Task:
Implement `__PACKET_DOC__` for Cognitive Switchyard.

Instructions:
- Read only the design-doc sections listed in the packet.
- Stay inside the packet's allowed file set.
- Write the packet's tests first.
- Implement only the behavior required for the packet acceptance criteria.
- Run the packet-scoped validation commands.
- Update `plans/packet_status.md` and `plans/packet_status.json` before finishing.
```

## Validator Prompt

```text
Read `docs/implementation_packet_playbook.md` first and follow it exactly.

Task:
Validate the implementation for `__PACKET_DOC__`.

Instructions:
- Re-read the packet acceptance criteria and validation focus.
- Verify the implementation stayed within the packet boundary.
- Run the packet's tests and any listed smoke checks.
- Look for regressions in previously validated packet contracts.
- Update `plans/packet_status.md` and `plans/packet_status.json` to `validated` only if the packet fully passes.
```

## Drift Auditor Prompt

```text
Read `docs/implementation_packet_playbook.md` first and follow it exactly.

Task:
Run a cumulative drift audit for the current validated frontier.

Instructions:
- Read `plans/packet_status.md` and `plans/packet_status.json`.
- Read the validated packet docs up to the current highest validated packet.
- Read the relevant design-doc sections for the areas already implemented.
- Compare the cumulative implementation, packet ladder, and tracker state against the intended architecture and packet boundaries.
- Prefer automatic correction over operator escalation when the repair is architecturally unambiguous.
- Return `repair_now` when you can fix the problem safely now and support it with targeted validation.
- Return `repair_packet` when the fix is broader than an inline audit patch but still unambiguous; in that case create a narrowly scoped repair packet immediately after the validated frontier and update both trackers.
- Return `halt` only for strategic ambiguity or major architectural choice.
- Do not broaden scope into future packets except to insert the immediate repair packet when returning `repair_packet`.
- Write both the markdown audit report and the machine-readable JSON result.
```
