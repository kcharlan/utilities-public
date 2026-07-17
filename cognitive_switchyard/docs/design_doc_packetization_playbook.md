# Design Doc Packetization Playbook

## Purpose

This playbook tells a planning agent how to convert a large design document into an implementation process that weaker coding agents can execute reliably.

The output is not just a summary. The output is an **operating system for delivery**:

- a project-specific implementation packet playbook
- a packet ladder
- the first 2-3 packet docs
- human-readable and machine-readable packet trackers

Use this playbook when a design document is large enough that direct end-to-end implementation is likely to fail due to scope overload, missed constraints, weak tests, or cross-cutting confusion.

## Core Principle

Do not preserve the design doc's product milestones as coding phases by default.

A design doc often groups work by product outcome:

- backend
- UI
- pack system
- recovery

Those are usually too large for reliable implementation.

Instead, derive **packets**:

- each packet introduces one behavior family
- each packet has explicit tests-first requirements
- each packet has tight file and interface boundaries
- each packet can be implemented without loading the full design doc into working memory

## When To Use `high` vs `xhigh`

Default to `high`.

Use `xhigh` only if one of these is true:

- the design doc is internally inconsistent
- packet boundaries are highly ambiguous
- the system has several interacting state machines
- crash recovery / timeout / retry semantics are central and under-specified
- earlier planning attempts repeatedly failed due to architecture, not execution

## Inputs

Required:

- the design document path
- the current codebase, if any
- this playbook

Optional:

- existing plans
- previous failed phase docs
- audit notes from prior attempts

## Required Outputs

The agent must create all of the following:

- `docs/implementation_packet_playbook.md`
- `plans/packet_status.md`
- `plans/packet_status.json`
- the first 2-3 remaining packet docs in `plans/`

If the repo already contains some of these files, update them in place based on the actual codebase state.

## Analysis Method

Perform the analysis in this order.

### 1. Identify Contract Surfaces

Extract the system contracts that must remain stable across implementation:

- state machine
- directory/state mapping
- file formats
- configuration schema
- public API boundaries
- subprocess / hook contracts
- timeout / retry / recovery rules

These contracts are the spine of the packet ladder.

### 2. Separate Behavior Families

Split the system into behavior families rather than product areas.

Typical behavior families:

- data models and parsers
- filesystem state handling
- database projection
- manifest validation
- pure scheduling logic
- subprocess lifecycle
- orchestration loop
- planning pipeline
- resolution pipeline
- verification
- auto-fix
- recovery
- CLI/bootstrap
- API
- UI
- reference pack

### 3. Identify Cross-Cutting Risk

Mark the areas most likely to cause agent failure:

- code that requires holding several phases in mind at once
- behaviors that depend on both filesystem and DB state
- recovery and idempotency
- timeout interactions
- UI coupled to backend internals
- packs coupled to unstable engine code

These should become later packets or be isolated into their own packets.

### 4. Derive Packet Boundaries

Use these packetization rules:

1. One behavior family per packet.
2. At most one new concurrency or subprocess concern per packet.
3. Do not mix a new runtime semantic with a new integration surface.
4. Do not mix recovery with first-pass execution.
5. Do not mix API and UI in the same packet.
6. Do not start with the reference pack if the generic engine is not yet stable.
7. Prefer pure logic and fixtures early.

### 5. Order the Ladder

Order packets by dependency and cognitive load:

- contracts and fixtures first
- pure data and parsing before stateful runtime
- pure scheduling before worker management
- worker management before orchestration
- orchestration before verification/autofix/recovery
- CLI/API/UI after engine stabilization
- reference pack after generic engine behavior is validated

### 6. Choose the Planning Cadence

The final process must use:

- planning horizon: 2-3 packets
- implementation unit: 1 packet
- validation unit: 1 packet
- full-suite verification cadence: periodic repo-wide verification after a small batch of validated packets, plus a final verification pass at completion
- drift audit cadence: periodic cumulative audit after a small batch of validated packets, plus a final audit at completion

Do not emit a giant detailed plan for the full project. Emit only a packet ladder plus the next 2-3 packet docs.

## Packet Quality Rules

Every packet doc must:

- define why the packet exists
- specify exact scope
- specify explicit non-goals
- identify relevant design doc sections
- name allowed files to create/modify
- specify tests to write first
- define acceptance criteria
- identify validation focus areas

If a packet cannot be described that concretely, it is too large.

## Required Tracker Format

Create both:

- `plans/packet_status.md`
- `plans/packet_status.json`

The JSON tracker must have this shape:

```json
{
  "project_complete": false,
  "highest_validated_packet": null,
  "packets": [
    {
      "id": "00",
      "name": "Contract Extraction",
      "slug": "contract_extraction",
      "status": "planned",
      "depends_on": [],
      "doc": "plans/packet_00_contract_extraction.md",
      "notes": ""
    }
  ]
}
```

Status values:

- `planned`
- `in_progress`
- `implemented`
- `validated`
- `blocked`

`project_complete` stays `false` until the ladder is exhausted and all packets are validated.

## Required Contents of `docs/implementation_packet_playbook.md`

The project-specific implementation playbook must include:

- purpose
- model assignment
- packet rules
- canonical packet ladder for this project
- recommended starting horizon
- repository artifacts and trackers
- required packet template
- planning procedure
- implementation procedure
- validation procedure
- full-suite verification procedure
- drift audit procedure
- escalation rules
- copy-paste prompts for planner, implementer, validator, drift auditor

The playbook should be written so that a future planning or coding agent can read it directly and operate from it without needing this meta-playbook.

## Failure Patterns To Correct

If the design doc already contains "phases," check for these failure modes:

- each phase spans several subsystems
- tests are broad integration tests with weak assertions
- phases require understanding the full project
- cross-cutting concerns land too early
- agent-specific instructions are missing
- acceptance criteria are not executable

When these appear, replace those phases with packets rather than preserving the original structure.

## Deliverable Standard

The output should let a user do this:

1. hand `docs/implementation_packet_playbook.md` to a `high` planner
2. have it generate the next 2 packets
3. hand one packet to a `medium` implementer
4. hand that packet to a `high` validator
5. every few validated packets, run a repo-wide full-suite verification pass
6. every few validated packets, hand the cumulative state to a `high` drift auditor
7. repeat without re-reading the entire design document

## Prompt To Use With This Playbook

Use this prompt in the planning terminal.

```text
Read `docs/design_doc_packetization_playbook.md` and follow it exactly.

Task:
Analyze the design document at `__DESIGN_DOC__` and convert it into a packetized implementation system that smaller coding agents can execute reliably.

Instructions:
- Read `docs/design_doc_packetization_playbook.md` first.
- Read the design document at `__DESIGN_DOC__`.
- Read the current codebase to determine whether any implementation already exists.
- If prior packet docs or trackers exist, reconcile them with the codebase instead of assuming they are correct.
- Extract the core contracts and behavior families.
- Replace oversized product milestones with narrowly-scoped implementation packets.
- Create `docs/implementation_packet_playbook.md`.
- Create `plans/packet_status.md`.
- Create `plans/packet_status.json`.
- Create exactly the first `__PACKET_HORIZON__` remaining packet docs in `plans/`.
- Keep the first packets biased toward contracts, fixtures, parsing, and pure logic.
- Do not start with UI or with a complex reference pack unless the system is already at that stage.
- Make the implementation playbook directly usable by future planner, implementer, and validator agents.
- The implementation playbook must treat drift correction as mostly automatic: prefer `repair_now` or `repair_packet` over halting, and reserve `halt` for strategic operator decisions.
- If drift correction needs a dedicated repair packet, that packet must sort immediately after the current validated frontier by reusing the same numeric packet ID with an uppercase suffix, for example `11A` after `11` and before `12`.
- The implementation playbook must include a periodic full-suite verification pass in addition to packet-local validation.

Output:
- `docs/implementation_packet_playbook.md`
- `plans/packet_status.md`
- `plans/packet_status.json`
- first `__PACKET_HORIZON__` remaining packet docs under `plans/`
```

## Success Condition

This playbook has been applied correctly if:

- the resulting implementation playbook is reusable
- the packet ladder is narrower than the design doc's product milestones
- the first 2-3 packets are executable by a medium coding agent
- the tracker is machine-readable
- the next planning step can happen against the real codebase rather than against a giant up-front plan
