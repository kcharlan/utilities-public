# Drift Audit — After Packet 09

**Auditor:** Claude Opus 4.6
**Date:** 2026-03-10
**Frontier:** Packet 09 (Sparklines & Scan Progress UI)
**Validated packets:** 00, 01, 02, 03, 04, 05, 06, 07, 08, 09
**Result:** REPAIR_NOW — Header Full Scan button scope bug fixed inline

---

## Methodology

1. Read all validated packet docs (00–09) and their validation audits.
2. Read `docs/git_dashboard_final_spec.md` sections 1–6, 9 (all sections relevant to packets 00–09).
3. Read `git_dashboard.py` in full (2479 lines on disk before fix).
4. Read all 10 test files (164 tests total).
5. Ran the full test suite: **164/164 passed** (1.72s) before fix.
6. Compared `plans/packet_status.json` and `plans/packet_status.md` for consistency.
7. Reviewed prior drift audits (`drift_audit_after_packet_02.md`, `drift_audit_after_packet_05.md`, `drift_audit_after_packet_08.md`).
8. Verified each validated packet's acceptance criteria still hold against the current codebase.
9. Applied inline repair + regression test, re-ran full suite: **165/165 passed** (2.05s) after fix.

---

## Tracker State Verification

| Check | Result |
|-------|--------|
| `packet_status.json` and `packet_status.md` agree on all statuses | PASS |
| `highest_validated_packet` = "09" matches both files | PASS |
| Dependency graph matches canonical ladder in playbook | PASS |
| All packets 10–23 are `planned` (no premature status advancement) | PASS |
| Packet doc paths in JSON match actual file paths in `plans/` | PASS |
| `drift_audit_state.json` shows `next_due_validated_count: 10` (we are at 10) | PASS |

---

## Schema vs Spec (Section 2)

All 6 tables in `_SCHEMA_SQL` match spec section 2 exactly. No schema changes since prior audits.

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
| branch_count | YES | From branches table |
| stale_branch_count | YES | From branches table |
| dep_summary | YES | null placeholder (packet 16) |
| sparkline | YES | 13-element list from compute_sparklines() |
| last_commit_hash | YES | Additive, forward-compatible |

### GET /api/fleet — KPIs (Spec §4.1)

| KPI | Status |
|-----|--------|
| total_repos | Correct (computed) |
| repos_with_changes | Correct (computed) |
| commits_this_week | Correct (from daily_stats, fixed in prior audit) |
| commits_this_month | Correct (from daily_stats, fixed in prior audit) |
| net_lines_this_week | Correct (from daily_stats, fixed in prior audit) |
| stale_branches | Correct (sum of per-repo stale_branch_count) |
| vulnerable_deps | Correct placeholder (0, packet 16) |
| outdated_deps | Correct placeholder (0, packet 16) |

---

## Packet 09 Acceptance Criteria Reverification — All 14 Still Hold

| # | Criterion | Status |
|---|-----------|--------|
| 1 | compute_sparklines returns dict of repo_id → 13-int list | PASS |
| 2 | GET /api/fleet sparkline is 13-element list per repo | PASS |
| 3 | Repos with no daily_stats get [0]*13 | PASS |
| 4 | Data older than 91 days excluded | PASS |
| 5 | SparklineOverlay renders on hover | PASS |
| 6 | Full Scan button sends POST /api/fleet/scan | PASS (after fix) |
| 7 | EventSource opens to SSE endpoint | PASS |
| 8 | ScanProgressBar appears below nav tabs | PASS |
| 9 | ScanToast shows at bottom-right | PASS |
| 10 | On completion, progress bar turns green | PASS |
| 11 | Toast auto-dismisses 2s after completion | PASS |
| 12 | Fleet data refetched on completion | PASS |
| 13 | Button disabled while scanning | PASS |
| 14 | All tests pass (165/165 after fix) | PASS |

---

## CSS Design System vs Spec §5.2

No changes to CSS since prior audit. All 46 custom properties in `:root` still match spec §5.2 verbatim. CDN versions still pinned: React 18.2.0, ReactDOM 18.2.0, Babel 7.23.9, Recharts 2.12.7.

Toast animations (`toastSlideIn`, `toastSlideOut`) correctly defined in `<style>` block for packet 09.

---

## Cross-Packet Boundary Check

| Check | Result |
|-------|--------|
| No features from packet 10+ (detail view, deps, analytics) | PASS |
| No dependency parsing beyond runtime classification | PASS |
| Placeholder values correct for unimplemented features | PASS |
| No loading skeletons (packet 23) | PASS |
| No error state UI (packet 22) | PASS |
| No focus states / keyboard nav (packet 23) | PASS |

---

## Findings

### Finding 1 — Header Full Scan Button Scope Bug (REPAIRED)

**Category:** Runtime bug
**Severity:** Medium
**Action:** `repair_now`

The `Header` component receives `onFullScan` as a prop (line 1295) but the Full Scan button's `onClick` at line 1338 referenced `handleFullScan` directly — a function defined inside the `App` component's scope. Since `handleFullScan` is defined with `async function` inside `App()`, it is hoisted to `App`'s function scope only and is NOT accessible from `Header`'s scope chain. At runtime in the browser, this would cause a `ReferenceError: handleFullScan is not defined`, making the Full Scan button non-functional.

**Root cause:** Packet 09's implementer wired `handleFullScan` at the `App` level and passed it to `Header` as `onFullScan`, but the button's `onClick` used the original function name instead of the prop name. The tests only checked that the HTML template string contained `handleFullScan` near the button, not that the correct variable was used in the correct scope.

**Fix applied:** Changed `onClick={handleFullScan}` to `onClick={onFullScan}` at line 1338. 1 character of code (one identifier). Added a regression test (`test_full_scan_button_uses_prop_not_closure`) that specifically verifies the button within the Header component body uses the `onFullScan` prop.

### Finding 2 — VCS Hygiene (Operator Action Needed, Carryover)

**Category:** VCS hygiene
**Severity:** Low
**Action:** Note for operator

7 test files are untracked (not committed to git):

| File | Packet | Tests |
|------|--------|-------|
| `tests/test_fleet_api.py` | 03 | 8 |
| `tests/test_html_shell.py` | 04 | 10 |
| `tests/test_fleet_overview_ui.py` | 05 | 14 |
| `tests/test_git_full_history.py` | 06 | 15 |
| `tests/test_branch_scan.py` | 07 | 13 |
| `tests/test_full_scan_sse.py` | 08 | 16 |
| `tests/test_sparklines_progress.py` | 09 | 11 |

This was flagged at 3 files in the packet-05 audit, grew to 6 in the packet-08 audit, and is now 7 files (87 tests unversioned). Additionally, `git_dashboard.py` has uncommitted changes spanning packets 03–09 plus two audit fixes.

**Recommendation:** Commit all outstanding work before proceeding to packet 10.

### Finding 3 — `orch_launch.sh` Untracked (Carryover)

**Category:** Housekeeping
**Severity:** Trivial
**Action:** Note for operator

The `orch_launch.sh` orchestrator launcher script remains in the project root, untracked. First flagged in the packet-05 audit.

---

## Prior Audit Findings Review

| Prior Finding | Status |
|---------------|--------|
| KPI aggregation gap (4 KPIs hardcoded 0) | Fixed in packet-08 audit, still correct |
| 6 test files untracked | Worsened (now 7 files, +test_sparklines_progress.py) |
| Stale docstrings/comments | Fixed in packet-08 audit, no new stale comments |
| `orch_launch.sh` untracked | Still untracked |
| `last_commit_hash` extra field | Still present, still accepted (additive) |

---

## Findings Summary

| # | Finding | Category | Severity | Action |
|---|---------|----------|----------|--------|
| 1 | Header Full Scan button references out-of-scope variable | Runtime bug | Medium | **repair_now** (DONE) |
| 2 | 7 test files untracked (87 tests not version-controlled) | VCS hygiene | Low | Operator: commit |
| 3 | `orch_launch.sh` untracked artifact | Housekeeping | Trivial | Operator: commit or gitignore |

---

## Verdict

| Field | Value |
|-------|-------|
| Status | **repair_now** |
| Severity | medium |
| Effort | small |
| Fixes applied | Yes |
| Validation rerun | targeted |
| Notes | Header Full Scan button used handleFullScan (App scope) instead of onFullScan (prop) — would ReferenceError at runtime. Changed to onFullScan. Regression test added. 165/165 tests pass. VCS hygiene (7 untracked test files) deferred to operator. |
