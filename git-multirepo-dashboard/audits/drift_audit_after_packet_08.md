# Drift Audit — After Packet 08

**Auditor:** Claude Opus 4.6
**Date:** 2026-03-10
**Frontier:** Packet 08 (Full Scan Orchestration & SSE)
**Validated packets:** 00, 01, 02, 03, 04, 05, 06, 07, 08
**Result:** REPAIR_NOW — KPI aggregation gap fixed inline

---

## Methodology

1. Read all validated packet docs (00–08) and their validation audits.
2. Read `docs/git_dashboard_final_spec.md` sections 1–5, 9 (all sections relevant to packets 00–08).
3. Read `git_dashboard.py` in full (2244 lines on disk before fix).
4. Read all 9 test files (154 tests total).
5. Ran the full test suite: **154/154 passed** (1.97s) before fix.
6. Compared `plans/packet_status.json` and `plans/packet_status.md` for consistency.
7. Reviewed prior drift audits (`drift_audit_after_packet_02.md`, `drift_audit_after_packet_05.md`).
8. Verified each validated packet's acceptance criteria still hold against the current codebase.
9. Applied inline repairs, re-ran full suite: **154/154 passed** (1.73s) after fix.

---

## Tracker State Verification

| Check | Result |
|-------|--------|
| `packet_status.json` and `packet_status.md` agree on all statuses | PASS |
| `highest_validated_packet` = "08" matches both files | PASS |
| Dependency graph matches canonical ladder in playbook | PASS |
| All packets 09–23 are `planned` (no premature status advancement) | PASS |
| Packet doc paths in JSON match actual file paths in `plans/` | PASS |
| `drift_audit_state.json` shows `next_due_validated_count: 9` (we are at 9) | PASS |

---

## Schema vs Spec (Section 2)

All 6 tables in `_SCHEMA_SQL` match spec section 2 exactly. No schema changes since the prior drift audits.

| Table | Columns match | Constraints match | FKs match |
|-------|--------------|-------------------|-----------|
| repositories | YES | YES | N/A |
| daily_stats | YES | YES (PK, FK CASCADE) | YES |
| branches | YES | YES (PK, FK CASCADE) | YES |
| dependencies | YES | YES (PK, FK CASCADE) | YES |
| working_state | YES | YES (PK, FK CASCADE) | YES |
| scan_log | YES | YES (AUTOINCREMENT) | N/A |

WAL mode: enabled via `PRAGMA journal_mode=WAL` in schema script.

---

## API Contract Verification

### All Implemented Endpoints

| Endpoint | Spec Shape | Code Shape | Match |
|----------|-----------|------------|-------|
| `GET /` | HTML 200 | HTMLResponse with full SPA template | YES |
| `GET /api/status` | `{tools, version}` | Same | YES |
| `POST /api/repos` | `{registered: N, repos: [...]}` | Same | YES |
| `DELETE /api/repos/{id}` | 204 / 404 | Same | YES |
| `GET /api/repos` | Additive (packet 02) | `{repos: [...]}` | Accepted |
| `GET /api/fleet` | `{repos: [...], kpis: {...}, scanned_at}` | Same | YES |
| `POST /api/fleet/scan` | `{scan_id: <int>}` | Same | YES |
| `GET /api/fleet/scan/{scan_id}/progress` | SSE `text/event-stream` | Same | YES |

### GET /api/fleet — Per-Repo Fields (Spec §4.1)

| Field | Present | Correct type/source |
|-------|---------|---------------------|
| id, name, path, runtime, default_branch | YES | From repositories table |
| current_branch | YES | From quick scan |
| last_commit_date, last_commit_message | YES | From quick scan |
| has_uncommitted, modified_count, untracked_count, staged_count | YES | From quick scan |
| branch_count | YES | From branches table (packet 08) |
| stale_branch_count | YES | From branches table (packet 08) |
| dep_summary | YES | null placeholder (packet 16) |
| sparkline | YES | [] placeholder (packet 09) |
| last_commit_hash | YES | Additive, forward-compatible |

### GET /api/fleet — KPIs (Spec §4.1)

| KPI | Status Before Fix | Status After Fix |
|-----|-------------------|------------------|
| total_repos | Correct (computed) | Correct |
| repos_with_changes | Correct (computed) | Correct |
| commits_this_week | **DRIFT**: hardcoded 0 | **FIXED**: from daily_stats |
| commits_this_month | **DRIFT**: hardcoded 0 | **FIXED**: from daily_stats |
| net_lines_this_week | **DRIFT**: hardcoded 0 | **FIXED**: from daily_stats |
| stale_branches | **DRIFT**: hardcoded 0 | **FIXED**: sum of per-repo stale_branch_count |
| vulnerable_deps | Correct placeholder (0) | Correct (packet 16) |
| outdated_deps | Correct placeholder (0) | Correct (packet 16) |

### POST /api/fleet/scan (Spec §4.2)

| Check | Result |
|-------|--------|
| Accepts `{"type": "full"}` and `{"type": "deps"}` | YES |
| Returns `{"scan_id": <int>}` | YES |
| 409 on concurrent scan (dual guard: in-memory + DB) | YES |
| Invalid type returns 422 | YES |

### GET /api/fleet/scan/{scan_id}/progress (Spec §4.3)

| Check | Result |
|-------|--------|
| Content-type `text/event-stream` | YES |
| In-progress events include `repo`, `step`, `progress`, `total`, `status` | YES |
| Final event includes `progress`, `total`, `status` (no repo/step) | YES |
| `step` value is "branches" (last step in full scan loop) | Accepted |

**Note on `step` value:** The spec §4.3 example shows both `"history"` and `"branches"` as step values. The implementation sends one event per repo with `step: "branches"` (the last step completed per repo). This was explicitly specified in the packet 08 doc and accepted during validation. Fine-grained per-step events would require restructuring the scan loop and is not needed for the packet 09 UI.

---

## Packets 06–08 Acceptance Criteria Reverification

### Packet 06 (Git Full History Scan) — All 15 Criteria Still Hold

| # | Criterion | Status |
|---|-----------|--------|
| 1 | parse_git_log parses multi-commit output | PASS |
| 2 | Merge commits get 0 for numeric fields | PASS |
| 3 | All shortstat variations handled | PASS |
| 4 | Empty input returns empty list | PASS |
| 5 | aggregate_daily_stats sums per YYYY-MM-DD | PASS |
| 6 | Same-day commits grouped | PASS |
| 7 | scan_full_history invokes correct git command | PASS |
| 8 | `--after={since}` included when since provided | PASS |
| 9 | `--after` omitted when since is None | PASS |
| 10 | upsert_daily_stats writes correct rows | PASS |
| 11 | upsert replaces on PK conflict | PASS |
| 12 | run_full_history_scan reads last_full_scan_at | PASS |
| 13 | Updates last_full_scan_at after scan | PASS |
| 14 | Returns commit count | PASS |
| 15 | All existing tests pass | PASS (154/154) |

### Packet 07 (Branch Scan) — All 13 Criteria Still Hold

| # | Criterion | Status |
|---|-----------|--------|
| 1 | parse_branches parses null-byte delimited output | PASS |
| 2 | Default branch identified | PASS |
| 3 | Stale detection (>30 days) | PASS |
| 4 | Missing/invalid dates → stale | PASS |
| 5 | Empty input → empty list | PASS |
| 6 | Branch names with slashes handled | PASS |
| 7 | scan_branches invokes correct git command | PASS |
| 8 | upsert_branches writes correct rows | PASS |
| 9 | DELETE+INSERT replaces full set | PASS |
| 10 | Empty branch list clears rows | PASS |
| 11 | run_branch_scan returns count | PASS |
| 12 | CASCADE delete removes branches | PASS |
| 13 | All existing tests pass | PASS (154/154) |

### Packet 08 (Full Scan Orchestration & SSE) — All 16 Criteria Still Hold

| # | Criterion | Status |
|---|-----------|--------|
| 1 | POST returns {scan_id: int} | PASS |
| 2 | scan_log row created | PASS |
| 3 | 409 on concurrent scan | PASS |
| 4 | Invalid type returns 422 | PASS |
| 5 | Succeeds after previous completed | PASS |
| 6 | Calls history + branch scan per repo | PASS |
| 7 | Sequential processing | PASS |
| 8 | Continue on per-repo error | PASS |
| 9 | Updates repos_scanned after each repo | PASS |
| 10 | Sets completed status + finished_at | PASS |
| 11 | Sets failed when all repos fail | PASS |
| 12 | SSE content-type text/event-stream | PASS |
| 13 | SSE event shapes correct | PASS |
| 14 | type=deps completes immediately | PASS |
| 15 | Fleet endpoint returns branch counts from DB | PASS |
| 16 | All existing tests pass | PASS (154/154) |

---

## CSS Design System vs Spec §5.2

No changes to CSS since prior audit. All 46 custom properties in `:root` still match spec §5.2 verbatim. CDN versions still pinned: React 18.2.0, ReactDOM 18.2.0, Babel 7.23.9, Recharts 2.12.7.

---

## Cross-Packet Boundary Check

| Check | Result |
|-------|--------|
| No features from packet 09+ (sparklines, detail view, deps) | PASS |
| No dependency parsing beyond runtime classification | PASS |
| Header buttons (Scan Dir, Full Scan) have no-op handlers | PASS |
| Placeholder values correct for unimplemented features | PASS |
| No loading skeletons (packet 23) | PASS |
| No error state UI (packet 22) | PASS |

---

## Findings

### Finding 1 — KPI Aggregation Gap (REPAIRED)

**Category:** Architectural drift
**Severity:** Medium
**Action:** `repair_now`

The fleet KPIs `commits_this_week`, `commits_this_month`, `net_lines_this_week`, and `stale_branches` were hardcoded to 0 with comments indicating they'd be populated by packets 06 and 07. Both packets are validated and the underlying data (daily_stats, branches tables) has been available since packet 08. However, no packet explicitly wired the aggregate queries into the fleet endpoint's KPI computation.

**Root cause:** Packets 06 and 07 explicitly deferred API wiring as non-goals. Packet 08 populated per-repo branch_count/stale_branch_count but only partially closed the gap — it didn't aggregate these into the KPI sum, and didn't touch the daily_stats-based KPIs at all. The comments in the code ("populated by packet 06/07") created a false expectation that wasn't fulfilled by those packets' scopes.

**Fix applied:** Added 3 aggregate queries to `get_fleet()` to compute `commits_this_week`, `commits_this_month`, and `net_lines_this_week` from `daily_stats`, and changed `stale_branches` to sum from per-repo results already in memory. ~15 lines of code. All 154 tests pass after fix.

### Finding 2 — Stale Comments (REPAIRED)

**Category:** Cosmetic
**Severity:** Trivial
**Action:** `repair_now`

Three stale comments from the development process:

1. `get_ui()` docstring: "Serve the SPA shell (placeholder until packet 04)." → Fixed to "Serve the SPA shell."
2. `--scan` help text: "(wired in packet 02/03)" → Removed implementation note.
3. `get_fleet()` docstring: referenced "placeholder values for fields populated by later packets (sparkline, dep_summary, branch_count, stale_branch_count)" — branch fields are no longer placeholders. → Fixed.

### Finding 3 — VCS Hygiene (Operator Action Needed)

**Category:** VCS hygiene
**Severity:** Low
**Action:** Note for operator

6 test files are untracked (not committed to git):

| File | Packet | Tests |
|------|--------|-------|
| `tests/test_fleet_api.py` | 03 | 8 |
| `tests/test_html_shell.py` | 04 | 10 |
| `tests/test_fleet_overview_ui.py` | 05 | 14 |
| `tests/test_git_full_history.py` | 06 | 15 |
| `tests/test_branch_scan.py` | 07 | 13 |
| `tests/test_full_scan_sse.py` | 08 | 16 |

This was flagged at 3 files in the prior audit (after packet 05). The problem has doubled to 6 files. Additionally, `git_dashboard.py` has uncommitted changes spanning packets 03–08 plus this audit's fix.

**Recommendation:** Commit all outstanding work before proceeding to packet 09.

### Finding 4 — `orch_launch.sh` Untracked (Carryover)

**Category:** Housekeeping
**Severity:** Trivial
**Action:** Note for operator

The `orch_launch.sh` orchestrator launcher script remains in the project root, untracked. First flagged in the prior audit.

---

## Prior Audit Findings Review

| Prior Finding | Status |
|---------------|--------|
| 3 test files untracked | Worsened (now 6 files) |
| Packet 05 code uncommitted | Still uncommitted (plus packets 06–08 now) |
| Stale `get_ui()` docstring | **Fixed in this audit** |
| Stale `--scan` help text | **Fixed in this audit** |
| `orch_launch.sh` untracked | Still untracked |
| `last_commit_hash` extra field | Still present, still accepted (additive) |

---

## Findings Summary

| # | Finding | Category | Severity | Action |
|---|---------|----------|----------|--------|
| 1 | KPI aggregation gap (4 KPIs hardcoded 0 despite data) | Architectural drift | Medium | **repair_now** (DONE) |
| 2 | 3 stale comments/docstrings | Cosmetic | Trivial | **repair_now** (DONE) |
| 3 | 6 test files untracked (76 tests not version-controlled) | VCS hygiene | Low | Operator: commit |
| 4 | `orch_launch.sh` untracked artifact | Housekeeping | Trivial | Operator: commit or gitignore |

---

## Verdict

| Field | Value |
|-------|-------|
| Status | **repair_now** |
| Severity | medium |
| Effort | small |
| Fixes applied | Yes |
| Validation rerun | targeted |
| Notes | 4 fleet KPIs wired to existing data (daily_stats + branches). 3 stale comments cleaned. 154/154 tests pass. VCS hygiene (6 untracked test files) deferred to operator. |
