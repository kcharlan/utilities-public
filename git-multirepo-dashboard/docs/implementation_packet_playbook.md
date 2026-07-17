# Git Fleet — Implementation Packet Playbook

## Purpose

This playbook governs the packetized implementation of **Git Fleet**, a local multi-repo git dashboard. It is the operating manual for planner, implementer, and validator agents working on this project.

The design document is at `docs/git_dashboard_final_spec.md`. This playbook replaces the design doc's Phase 1–4 milestones with narrowly-scoped packets that a mid-level coding agent can implement one at a time without loading the full 1350-line spec into working memory.

---

## Model Assignment

| Role | Model | Effort |
|---|---|---|
| Planner | Opus / high | Reads this playbook + codebase, emits next 2–3 packet docs |
| Implementer | Sonnet / medium-high | Reads one packet doc + referenced spec sections, writes code |
| Validator | Opus / high | Reads packet doc + runs acceptance criteria, reports pass/fail |
| Drift Auditor | Opus / high | Reads cumulative tracker + codebase, flags divergence |

---

## Packet Rules

1. One behavior family per packet.
2. At most one new concurrency or subprocess concern per packet.
3. Do not mix a new runtime semantic with a new integration surface.
4. Do not mix recovery/error handling with first-pass execution (error states come in a later packet).
5. Do not mix API and UI in the same packet (except when the UI is trivially wiring to an existing API).
6. Prefer pure logic and fixtures early; UI comes after the engine stabilizes.
7. Each packet targets 200–600 lines of net new code. If larger, split it.

---

## Canonical Packet Ladder

| ID | Name | Behavior Family | Depends On |
|---|---|---|---|
| 00 | Bootstrap & Schema | Bootstrap, venv, preflight, SQLite schema, CLI args | — |
| 01 | Git Quick Scan | Git subprocess: quick scan (status, log -1, rev-parse) | 00 |
| 02 | Repo Discovery & Registration API | POST /api/repos, DELETE, recursive git discovery | 00, 01 |
| 03 | Fleet API & Quick Scan Orchestration | GET /api/fleet, semaphore(8) parallel quick scan, working_state upsert | 01, 02 |
| 04 | HTML Shell & Design System | HTML_TEMPLATE, CSS custom properties, React shell, hash routing, nav tabs | 00 |
| 05 | Fleet Overview UI | KPI row, project grid, cards (compact 3-row), sort/filter, empty state | 03, 04 |
| 06 | Git Full History Scan | git log parser, daily_stats upsert, incremental --after | 01 |
| 07 | Branch Scan | git branch parser, stale detection, branches table upsert | 01 |
| 08 | Full Scan Orchestration & SSE | POST /api/fleet/scan, scan_log, SSE progress stream, sequential scan loop | 06, 07 |
| 09 | Sparklines & Scan Progress UI | Hover sparklines on cards, progress bar, scan toast | 05, 08 |
| 10 | Project Detail View & Activity Chart | GET /api/repos/{id}, GET /api/repos/{id}/history, detail header, Recharts diverging area chart, time range selector | 03, 06 |
| 11 | Commits & Branches Sub-tabs | GET /api/repos/{id}/commits (paginated), GET /api/repos/{id}/branches, table UI | 07, 10 |
| 12 | Dependency Detection & Parsing | File detection priority, parse requirements.txt / pyproject.toml / package.json / go.mod / Cargo.toml / Gemfile / composer.json, runtime classification | 00 |
| 13 | Python Dep Health (Outdated + Vuln) | PyPI JSON API for outdated, pip-audit for vuln, severity classification | 12 |
| 14 | Node Dep Health | npm outdated + npm audit, JSON parsing, severity classification | 12 |
| 15 | Go / Rust / Ruby / PHP Dep Health | Remaining ecosystem checks (go list, govulncheck, cargo outdated/audit, bundle outdated/audit, composer outdated/audit) | 12 |
| 16 | Dep Scan Orchestration | Dep scan flow (type=deps), integrate into full scan, dep_summary on fleet cards | 08, 13, 14, 15 |
| 17 | Dependencies Sub-tab UI | GET /api/repos/{id}/deps, deps table, severity badges, "Check Now" button | 10, 16 |
| 18 | Analytics: Heatmap | GET /api/analytics/heatmap, GitHub-style grid component | 06 |
| 19 | Analytics: Time Allocation | GET /api/analytics/allocation, stacked area chart, legend toggle | 06 |
| 20 | Analytics: Dep Overlap | GET /api/analytics/dep-overlap, expandable table | 16 |
| 21 | Analytics Tab Wiring | Analytics tab with all three sections, time range selectors | 18, 19, 20 |
| 22 | Error States & Edge Cases | Path-not-found card state, scan-failed badge, offline indicator, concurrent scan rejection (409) | 03, 08, 16 |
| 23 | Polish & Accessibility | Focus states, keyboard nav, view transitions, loading skeletons, scrollbar styling, tool-status banner | 05, 10, 21 |

**Note on packet 15:** This is the widest packet (4 ecosystems). If any ecosystem proves complex during implementation, split it into 15A (Go), 15B (Rust), 15C (Ruby/PHP). The planner should reassess when packet 14 is validated.

---

## Recommended Starting Horizon

Plan packets **00, 01, 02** first. These establish the bootstrap, git operations, and data layer that everything else depends on. No UI, no network calls, no charts.

---

## Repository Artifacts and Trackers

| File | Purpose |
|---|---|
| `docs/git_dashboard_final_spec.md` | Design document (read-only reference) |
| `docs/design_doc_packetization_playbook.md` | Meta-playbook (read-only reference) |
| `docs/implementation_packet_playbook.md` | This file — operating manual |
| `plans/packet_status.md` | Human-readable tracker |
| `plans/packet_status.json` | Machine-readable tracker |
| `plans/packet_NN_slug.md` | Individual packet docs |
| `git_dashboard.py` | The single implementation file |
| `README.md` | User-facing docs (created in packet 00) |
| `.venv/` | Local test venv (dev-only, gitignored) |
| `requirements-dev.txt` | Dev/test dependencies |

---

## Development Environment

This project uses two separate Python virtual environments:

- **Runtime venv** (`~/.git_dashboard_venv`): Created by the app's `bootstrap()` function. Contains only runtime dependencies (fastapi, uvicorn, etc.). Managed by the application itself.
- **Test venv** (`.venv/` in project root): Contains dev-only dependencies (pytest) plus all runtime dependencies so tests can import project modules. Managed by the developer or by packet 00's test setup.

### Test venv setup

```bash
python3 -m venv .venv
.venv/bin/pip install pytest httpx
.venv/bin/pip install fastapi uvicorn[standard] aiosqlite packaging
```

### Test runner command

```bash
.venv/bin/python -m pytest tests -v
```

This matches the orchestrator's `FULL_TEST_COMMAND` default. All agents (implementer, validator, drift auditor) must use this command to run tests.

### Bootstrap packet responsibility

Packet 00 must include creating the test venv and installing test dependencies as part of its scope. The `.venv/` directory is gitignored.

---

## Required Packet Template

Every packet doc in `plans/` must use this structure:

```markdown
# Packet NN: <Name>

## Why This Packet Exists
<1–2 sentences>

## Scope
<Bullet list of what this packet delivers>

## Non-Goals
<What is explicitly NOT in this packet>

## Relevant Design Doc Sections
<Section numbers and names from git_dashboard_final_spec.md>

## Allowed Files
<Exact file paths>

## Tests to Write First
<Specific test scenarios with expected behavior>

## Implementation Notes
<Key details the implementer needs: data shapes, algorithms, constraints>

## Acceptance Criteria
<Numbered list of verifiable conditions>

## Validation Focus Areas
<What the validator should pay extra attention to>
```

---

## Planning Procedure

The planner agent reads this playbook and the codebase, then:

1. Check `plans/packet_status.json` for the current frontier (highest validated packet).
2. Identify the next 2–3 packets on the ladder that are `planned`.
3. For each, read the relevant design doc sections.
4. Read the current codebase to understand what exists.
5. Write the packet doc following the template above.
6. Update `plans/packet_status.json` (status remains `planned`).
7. Update `plans/packet_status.md`.

**Do not plan more than 3 packets ahead.** The codebase changes and earlier packets may shift later boundaries.

---

## Implementation Procedure

The implementer agent receives one packet doc and:

1. Read the packet doc completely.
2. Read the referenced design doc sections.
3. Read the allowed files to understand current state.
4. Write tests first (as specified in the packet).
5. Implement the code changes.
6. Run the tests. Iterate until all pass.
7. Run any broader validation (e.g., `python git_dashboard.py --help` should not crash).
8. Update `plans/packet_status.json`: set status to `implemented`.
9. Update `plans/packet_status.md`.

**Implementer constraints:**
- Only modify files listed in "Allowed Files."
- If a dependency on a prior packet is missing or broken, stop and report. Do not work around it.
- If the packet doc is ambiguous, prefer the design doc. If both are ambiguous, stop and report.

---

## Validation Procedure

The validator agent receives the packet doc and the current codebase:

1. Read the packet doc's acceptance criteria.
2. Run the tests specified in the packet.
3. Manually verify each acceptance criterion.
4. Check for regressions: run all existing tests.
5. Verify no files outside the allowed list were modified.
6. If all criteria pass, update `plans/packet_status.json`: set status to `validated`.
7. If any criterion fails, report the failure with details. Status stays `implemented`.

---

## Full-Suite Verification Procedure

Run after every 3–4 validated packets, and once at completion.

The orchestrator runs `.venv/bin/python -m pytest tests -v` (the `FULL_TEST_COMMAND` default). The test venv must exist before this can succeed — see the Development Environment section.

1. Start the application: `python git_dashboard.py --yes --no-browser`.
2. Verify the server starts without errors.
3. Run all existing tests via `.venv/bin/python -m pytest tests -v`.
4. Hit every implemented API endpoint with a basic request and verify response shape.
5. If the UI is implemented, load `http://localhost:8300` and verify no console errors.
6. Report results. Any failure blocks further packets until fixed.

---

## Drift Audit Procedure

Run after every 4–5 validated packets, and once at completion:

1. Read `plans/packet_status.json` for the current state.
2. Read `docs/git_dashboard_final_spec.md` for the intended design.
3. Read the codebase (`git_dashboard.py` primarily).
4. For each validated packet, verify the acceptance criteria still hold.
5. Check for:
   - API response shapes that deviate from the spec.
   - CSS custom properties that are defined but unused (or vice versa).
   - Dead code from prior packets that was superseded.
   - Schema columns that exist in code but not in the spec (or vice versa).
6. Report findings with one of:
   - `repair_now`: Fix immediately, no new packet needed.
   - `repair_packet`: Create a repair packet (e.g., `11A`) immediately after the current validated frontier.
   - `halt`: Strategic issue requiring operator decision.

**Bias toward `repair_now` and `repair_packet`.** Reserve `halt` for cases where continuing would compound the problem.

---

## Escalation Rules

| Situation | Action |
|---|---|
| Packet too large during implementation | Implementer stops, reports to planner. Planner splits the packet. |
| Acceptance criterion is untestable | Validator reports. Planner rewrites the criterion. |
| Prior packet's output doesn't match expectations | Implementer stops. Validator re-validates the prior packet. |
| Design doc is ambiguous or contradictory | Escalate to operator (human). Do not guess. |
| Drift audit finds > 3 deviations | Create a repair packet before continuing. |
| Full-suite verification fails | Block all new packets until fixed. |

---

## Copy-Paste Prompts

### Planner Prompt

```text
Read `docs/implementation_packet_playbook.md` and follow it exactly.

Task: Plan the next 2–3 packets for the Git Fleet project.

1. Read `plans/packet_status.json` to find the current frontier.
2. Read the codebase to understand what exists.
3. For each packet to plan, read the relevant sections of `docs/git_dashboard_final_spec.md`.
4. Write each packet doc in `plans/` following the required template.
5. Update `plans/packet_status.md` and `plans/packet_status.json`.
6. Do NOT implement any code.
```

### Implementer Prompt

```text
Read `docs/implementation_packet_playbook.md` and follow it exactly.

Task: Implement packet __PACKET_ID__ (`plans/__PACKET_FILE__`).

1. Read the packet doc completely.
2. Read the referenced design doc sections in `docs/git_dashboard_final_spec.md`.
3. Read the allowed files.
4. Write tests first, then implement.
5. Run tests. Iterate until all pass.
6. Update `plans/packet_status.json` and `plans/packet_status.md` to `implemented`.
7. Only modify files listed in the packet's "Allowed Files" section.
```

### Validator Prompt

```text
Read `docs/implementation_packet_playbook.md` and follow it exactly.

Task: Validate packet __PACKET_ID__ (`plans/__PACKET_FILE__`).

1. Read the packet doc's acceptance criteria.
2. Run all tests (packet-specific and existing).
3. Verify each acceptance criterion.
4. Check for regressions.
5. If all pass: update status to `validated`.
6. If any fail: report details, leave status as `implemented`.
```

### Drift Auditor Prompt

```text
Read `docs/implementation_packet_playbook.md` and follow it exactly.

Task: Drift audit for Git Fleet.

1. Read `plans/packet_status.json`.
2. Read `docs/git_dashboard_final_spec.md`.
3. Read `git_dashboard.py`.
4. For each validated packet, verify acceptance criteria still hold.
5. Check for API shape deviations, unused CSS properties, dead code, schema mismatches.
6. Report findings as `repair_now`, `repair_packet`, or `halt`.
```

### Full-Suite Verification Prompt

```text
Read `docs/implementation_packet_playbook.md` and follow it exactly.

Task: Full-suite verification for Git Fleet.

1. Start the app: `python git_dashboard.py --yes --no-browser`
2. Run all tests.
3. Hit every implemented API endpoint and verify response shapes.
4. If UI exists, load the page and check for console errors.
5. Report results.
```
