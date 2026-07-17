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

## Test Quality Standards

Tests in the "Tests to Write First" section must meet these standards. Tests that merely call an endpoint and check the status code provide false confidence — they pass even when the feature is broken.

### Required Coverage Per Behavior

- **Happy path + at least 2 adversarial scenarios**: error inputs, missing state, boundary values, invalid combinations
- **Error path coverage is mandatory**: every endpoint or function that can fail must have a test that triggers the failure and asserts the error response (status code, message content, absence of side effects)
- **Cascade and cleanup verification**: any operation that touches related data (deletes with FK cascades, scans that update multiple tables) must assert all affected tables, not just the primary one
- **State reset after failure**: any operation that sets runtime state (flags, locks, active IDs) must have a test that triggers mid-operation failure and verifies the state is cleaned up

### Assertion Quality

- Assertions must verify **behavior, not just shape**: checking `status_code == 200` and `"repos" in response` is insufficient — must assert counts, specific values, state changes, or side effects
- For database-backed operations, verify the DB state after the operation (SELECT counts, check specific rows), not just the HTTP response
- For operations with side effects (creates, updates, deletes), verify both the response AND the resulting state

### Anti-Patterns (Do Not Write These)

- "Call and check shape" tests that would pass even if the feature returned hardcoded data
- Tests that only check the primary table after a cascade operation (leaves orphaned rows undetected)
- Tests that never trigger error/failure paths (100% happy-path coverage, 0% error-path)
- Tests that mock so aggressively the real code path is never exercised
- Tests that use the wrong fixture scope (module-scoped client hitting DB endpoints that need function-scoped isolation)

### Packet Template Requirements

The "Tests to Write First" section in each packet must specify for each behavior:

1. The happy-path test and what the assertion proves
2. At least one error/edge-case test (what input breaks it? what state is missing?)
3. What specific assertion proves correctness (not just "returns 200" but "returns 200 with 2 repos and both have 'id' matching sha256[:16] of their path")

The "Validation Focus Areas" section must answer:

1. Are error paths tested, or only happy paths?
2. Do assertions verify actual values/state, or just response shape?
3. Could these tests pass even if the feature is broken? (If yes, they're too weak.)
4. Are side effects verified? (DB rows created/deleted, files written, state flags reset)

### End-to-End Browser Tests (for projects with a web UI)

Unit tests cannot catch rendering failures, broken CDN loads, dead buttons, layout occlusion, or JavaScript reference errors. Projects that serve a web UI must include Playwright-based E2E tests as a separate test suite.

**What E2E tests must cover:**

1. **Page loads without JS errors** — listen for `pageerror` events; assert none
2. **CDN dependencies load** — listen for `requestfailed`; assert no CDN/font failures
3. **React/Vue/framework mounts** — assert the root element has content (not empty)
4. **Every button is clickable and wired** — no `onClick={() => {}}` stubs; verify each button triggers observable behavior (dialog, navigation, API call, DOM change)
5. **Fixed/absolute positioned elements don't occlude content** — verify banners, modals, and alerts are visible (bounding box check) and not behind fixed headers
6. **Tab/route navigation works** — click each nav tab, verify URL changes and content renders without errors
7. **API roundtrip via browser** — use `page.evaluate(fetch(...))` to verify key API endpoints return expected JSON from the real server

**E2E test infrastructure requirements:**

- The implementation playbook must specify that E2E tests live in a separate file (e.g., `tests/test_e2e.py`) and must be run in a separate pytest invocation from unit tests (Playwright's event loop conflicts with `asyncio.run()`)
- The app must support a `--no-browser` flag and/or `GIT_DASHBOARD_NO_BROWSER=1` env var so E2E test fixtures can start the server without stealing focus
- The E2E test file must include a server fixture that starts the real app on a random port, waits for it to accept connections, and shuts it down after tests complete
- Packet 00 (bootstrap) must install Playwright and Chromium as part of the test environment setup

**When to add E2E tests:**

- The first packet that produces visible UI (HTML shell, React mount) must include at least tests 1-3 above
- Each subsequent UI packet must add E2E tests for the new UI elements it introduces
- The final packet must include a full E2E smoke test covering all tabs and primary user flows

### Safety and Behavioral Contracts

After identifying structural phases, do a second pass over the design doc looking specifically for:

- **Conditional behavior** (if X then Y, else Z) — test BOTH branches
- **Adversarial properties** (don't trust output from X, verify independently) — test that trusting X alone is insufficient
- **Cleanup/teardown that varies by status** — test each status value
- **Retry loops with bounded attempts** — test exhaustion and each intermediate state
- **Features that a component defines but another component must consume** (config fields, hooks, frontmatter keys) — test the full wiring, not just one side

These ALWAYS get their own dedicated packets with their own tests — never combined with the structural packet that builds the mechanism. When structural and safety tests share a packet, generators write tests for the easy structural parts and skip the hard behavioral contracts.

### Assertion Principles

- **Assert outcomes, not mechanisms**: "The directory still exists after failure" is better than "The cleanup function received the correct status." Every test should answer: "What would a human check to confirm this worked?"
- **Anti-patterns to avoid**: `assert result.returncode == 0` without checking what the script did; `assert mock.called_with(correct_args)` without checking the effect; testing that a function was invoked but not testing the state after completion
- **Every behavioral statement in a spec requires a test**: If a spec section describes what the code does in prose, there must be a test exercising that exact behavior. Prose is not coverage — only executable assertions are.

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
- **development environment** (see below)
- planning procedure
- implementation procedure
- validation procedure
- full-suite verification procedure
- drift audit procedure
- escalation rules
- copy-paste prompts for planner, implementer, validator, drift auditor

### Development Environment Section

The implementation playbook must specify how the project's test environment is set up and invoked. This is critical because the orchestrator's full-suite verification uses a configurable `FULL_TEST_COMMAND` that must match the project's actual environment.

The development environment section must define:

1. **Test venv location**: A local `.venv/` in the project root, separate from any runtime venv the application creates for itself (e.g., `~/.appname_venv`). The test venv holds dev-only dependencies (pytest, etc.) that should not pollute the runtime venv.
2. **Test venv setup command**: The exact command to create and populate the test venv. Example: `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt` or `.venv/bin/pip install pytest <runtime-deps>`.
3. **Test runner command**: The exact command the orchestrator and developers use to run tests. Must match the orchestrator's `FULL_TEST_COMMAND` default (`.venv/bin/python -m pytest tests -v`).
4. **Bootstrap packet responsibility**: Packet 00 (or whichever packet handles bootstrap) must create the test venv and install test dependencies as part of its scope. The test venv must exist before any tests can run.

This prevents a common failure mode: the orchestrator's full-suite verification fails with exit code 127 because the test runner command references a venv that was never created.

The playbook should be written so that a future planning or coding agent can read it directly and operate from it without needing this meta-playbook.

## Failure Patterns To Correct

If the design doc already contains "phases," check for these failure modes:

- each phase spans several subsystems
- tests are broad integration tests with weak assertions
- phases require understanding the full project
- cross-cutting concerns land too early
- agent-specific instructions are missing
- acceptance criteria are not executable
- tests only check the primary table after cascade operations (leaves orphaned rows undetected)
- tests never trigger error or failure paths (100% happy-path, 0% error-path)
- runtime state (flags, locks, active scan IDs) is set but never tested for cleanup after failure
- tests use the wrong fixture scope (module-scoped fixtures hitting endpoints that require per-test isolation)

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
8. packet-level tests cover both success and failure paths, with assertions that would fail if the behavior regressed

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
