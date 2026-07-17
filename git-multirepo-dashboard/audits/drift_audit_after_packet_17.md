# Drift Audit — After Packet 17

**Auditor:** Claude Opus 4.6
**Date:** 2026-03-10
**Frontier:** Packet 17 (Dependencies Sub-tab UI)
**Validated packets:** 00, 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15, 16, 17
**Validated count:** 18
**Result:** REPAIR_NOW — 1 small fix applied

---

## Methodology

1. Read all validated packet docs (00–17) and their validation audits.
2. Read `docs/git_dashboard_final_spec.md` — all sections relevant to packets 00–17 (sections 1–5.5, 6).
3. Read `git_dashboard.py` in full (4,816 lines on disk pre-fix, 4,815 post-fix).
4. Read all 18 test files (356 tests total).
5. Ran the full test suite: **356/356 passed** (3.06s) — before and after fix.
6. Compared `plans/packet_status.json` and `plans/packet_status.md` for consistency.
7. Reviewed all prior drift audits (after packets 02, 05, 08, 09, 10, 13, 16).
8. Verified each validated packet's acceptance criteria still hold against the current codebase.
9. Verified CSS custom properties, API contracts, schema, and function inventory.

---

## Tracker State Verification

| Check | Result |
|-------|--------|
| `packet_status.json` and `packet_status.md` agree on all statuses | PASS |
| `highest_validated_packet` = "17" matches both files | PASS |
| Dependency graph matches canonical ladder in playbook | PASS |
| All packets 18–23 are `planned` (no premature status advancement) | PASS |
| Packet doc paths in JSON match actual file paths in `plans/` | PASS |
| `drift_audit_state.json` shows `next_due_validated_count: 18` (we are at 18) | PASS |

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

### Column Usage Audit

- `repositories.last_quick_scan_at`: Defined in both spec and code, never written. Tracked via `working_state.checked_at`. Spec-defined slot for future use. Not drift. (Carryover from all prior audits.)
- `dependencies` table: All columns actively populated by packets 13–16 health check + orchestration pipeline, exposed by packet 17 API and UI.

---

## API Contract Verification

### All 14 Implemented Endpoints

| Endpoint | Spec Shape | Code Shape | Match |
|----------|-----------|------------|-------|
| `GET /` | HTML 200 | HTMLResponse with full SPA template | YES |
| `GET /api/status` | `{tools, version}` | Same | YES |
| `POST /api/repos` | `{registered: N, repos: [...]}` | Same | YES |
| `DELETE /api/repos/{id}` | 204 / 404 | Same | YES |
| `GET /api/repos` | `{repos: [...]}` | Same | YES |
| `GET /api/fleet` | `{repos: [...], kpis: {...}, scanned_at}` | Same | YES |
| `POST /api/fleet/scan` | `{scan_id: <int>}` | Same | YES |
| `GET /api/fleet/scan/{scan_id}/progress` | SSE `text/event-stream` | Same | YES |
| `GET /api/repos/{repo_id}` | `{id, name, ..., working_state, last_full_scan_at}` | Same | YES |
| `GET /api/repos/{repo_id}/history` | `{repo_id, days, data: [...]}` | Same | YES |
| `GET /api/repos/{repo_id}/commits` | `{commits: [...], page, per_page, total}` | Same | YES |
| `GET /api/repos/{repo_id}/branches` | `{branches: [...]}` | Same | YES |
| `GET /api/repos/{repo_id}/deps` | `[{manager, packages, checked_at}]` | Same | YES |
| `POST /api/repos/{repo_id}/scan/deps` | Calls `run_dep_scan_for_repo`, returns updated deps | Same | YES |

### Packet 17 — Deps API Verification

| Aspect | Expected | Actual | Match |
|--------|----------|--------|-------|
| GET /api/repos/{id}/deps shape | Array of `{manager, packages, checked_at}` | Same | YES |
| Package fields | name, current_version, wanted_version, latest_version, severity, advisory_id | Same | YES |
| Sort order | vulnerable → major → outdated → ok, then name | SQL CASE 0/1/2/3 + name | YES |
| Empty repo | `[]` | `[]` | YES |
| 404 for nonexistent | 404 | 404 | YES |
| POST scan/deps | calls run_dep_scan_for_repo, returns updated deps | Same | YES |
| POST scan/deps 404 | 404 for nonexistent repo | 404 | YES |

### GET /api/fleet — Full KPI Audit

| KPI | Status |
|-----|--------|
| total_repos | Correct (len(results)) |
| repos_with_changes | Correct (computed from has_uncommitted) |
| commits_this_week | Correct (from daily_stats) |
| commits_this_month | Correct (from daily_stats) |
| net_lines_this_week | Correct (from daily_stats) |
| stale_branches | Correct (sum of per-repo stale_branch_count) |
| vulnerable_deps | Correct (DB query) |
| outdated_deps | Correct (DB query) |

---

## Packet 17 Acceptance Criteria Reverification

All 15 acceptance criteria verified against the current codebase:

| # | Criterion | Status |
|---|-----------|--------|
| 1 | GET /api/repos/{id}/deps returns 200 with array of manager groups | PASS |
| 2 | Each manager group has manager, packages, checked_at | PASS |
| 3 | Each package has all 6 required fields | PASS |
| 4 | Sort order: vulnerable → major → outdated → ok, then alpha | PASS |
| 5 | Returns `[]` for repo with no dependencies | PASS |
| 6 | Returns 404 for nonexistent repo | PASS |
| 7 | POST scan/deps calls run_dep_scan_for_repo, returns updated deps | PASS |
| 8 | POST scan/deps returns 404 for nonexistent repo | PASS |
| 9 | DepsTab component exists in HTML_TEMPLATE | PASS |
| 10 | DepsTab renders table with Package, Current, Latest, Status columns | PASS |
| 11 | Status text uses correct severity → color mapping (CSS vars) | PASS |
| 12 | "Last checked: X ago" text appears below each manager section | PASS |
| 13 | "Check Now" button present, secondary style, loading/disabled state | PASS |
| 14 | Empty state shows "No dependencies detected" | PASS |
| 15 | All existing tests pass (no regressions) | PASS (356/356) |

---

## CSS Design System vs Spec §5.2

All custom properties in `:root` match spec §5.2. CDN versions still pinned: React 18.2.0, ReactDOM 18.2.0, Babel 7.23.9, Recharts 2.12.7.

**DepsTab CSS var usage (packet 17):**
- `var(--status-green)` for "ok" severity ✓
- `var(--status-yellow)` for "outdated" severity ✓
- `var(--status-orange)` for "major" severity ✓
- `var(--status-red)` for "vulnerable" severity ✓
- `var(--text-muted)` for "Last checked" text ✓
- No hardcoded hex colors in DepsTab ✓

**Net unused CSS tokens:** 2 — `--fresh-border-this-month` (transparent) and `--fresh-border-older` (transparent). Design placeholders by intent. (Carryover from prior audits.)

---

## Cross-Packet Boundary Check

| Check | Result |
|-------|--------|
| No analytics endpoints (packets 18–21) | PASS — no `/api/analytics/*` routes |
| No analytics React components (packets 18–21) | PASS — placeholder text only |
| No error state UI (packet 22) | PASS |
| No polish/accessibility (packet 23) | PASS |
| Placeholder values correct for unimplemented features | PASS |

---

## Code Health

| Check | Result |
|-------|--------|
| Unused imports | 1 found and fixed: `import urllib.error` (line 23, never referenced) |
| Dead code | NONE |
| Unreferenced functions | NONE |
| TODO/FIXME/HACK markers | NONE |
| Logger usage | Active — properly used across all dep check and scan error paths |
| Hardcoded hex colors in React | NONE (all use CSS vars; only `#fff` in CSS rules, acceptable) |
| Scope issues | NONE — prior scan button fix still in place with regression test |

---

## Findings

### Finding 1 — Unused `import urllib.error` (FIXED)

**Category:** Code hygiene
**Severity:** Trivial
**Action:** `repair_now` — applied

Line 23 had `import urllib.error` which was never referenced anywhere in the codebase. The code imports `urllib.request` (used for PyPI lookups in `check_python_outdated`) but all exception handling uses broad `except Exception` clauses. The `urllib.error.URLError` and `urllib.error.HTTPError` types are never caught or referenced.

**Root cause:** Likely imported alongside `urllib.request` as a common pattern during packet 13 implementation. Not caught during validation because it causes no runtime error.

**Fix applied:** Removed the `import urllib.error` line.

**Impact:** No tests broke. 356/356 pass before and after fix.

### Finding 2 — VCS Hygiene: 8 Untracked Test Files (Carryover, Worsened)

**Category:** VCS hygiene
**Severity:** Low
**Action:** Note for operator

Now 8 untracked test files (was 7 in prior audit; packet 17 added `test_deps_subtab_ui.py`):

| File | Packet | Tests |
|------|--------|-------|
| `tests/test_fleet_api.py` | 03 | 9 |
| `tests/test_html_shell.py` | 04 | 10 |
| `tests/test_fleet_overview_ui.py` | 05 | 14 |
| `tests/test_git_full_history.py` | 06 | 15 |
| `tests/test_branch_scan.py` | 07 | 13 |
| `tests/test_full_scan_sse.py` | 08 | 17 |
| `tests/test_project_detail.py` | 10 | 14 |
| `tests/test_deps_subtab_ui.py` | 17 | 11 |

103 tests not version-controlled. Flagged since the packet-05 audit. Not architectural drift, but the untracked count continues to grow with each new packet.

**Recommendation:** Commit all untracked test files before proceeding further.

---

## Data Flow Verification (Packet 17)

### Deps API Pipeline (End-to-End)

1. `GET /api/repos/{id}/deps` → calls `_fetch_repo_deps(db, repo_id)` (line 4646)
2. `_fetch_repo_deps` queries dependencies table with severity-based CASE sort (lines 4592–4637)
3. Groups results by manager, computes MAX checked_at per group
4. Returns `[{manager, packages: [{name, current_version, wanted_version, latest_version, severity, advisory_id}], checked_at}]`
5. `POST /api/repos/{id}/scan/deps` → looks up repo → calls `run_dep_scan_for_repo` → re-queries via `_fetch_repo_deps` → returns updated deps (lines 4649–4660)

### DepsTab UI Pipeline

1. Component fetches `/api/repos/${repoId}/deps` on mount
2. Renders one table section per manager group
3. Severity color mapping via `severityColor()` uses CSS vars correctly
4. Severity text mapping via `severityText()` maps ok→"up to date", outdated→"outdated", major→"major update", vulnerable→advisory_id
5. "Last checked" uses `timeAgo()` function (reused from DetailHeader)
6. "Check Now" button POSTs to `/api/repos/${repoId}/scan/deps`, disables during scan, refetches on completion

---

## Prior Audit Findings Review

| Prior Finding | Source | Current Status |
|---------------|--------|----------------|
| KPI aggregation gap (4 KPIs hardcoded 0) | Packet 08 | Fully resolved — all 8 KPIs from real data |
| Header Full Scan button scope bug | Packet 09 | Fixed, regression test still in place |
| 8 test files untracked | Packet 05+ | **Carryover** — now 8 files (was 7), +test_deps_subtab_ui.py |
| `last_commit_hash` extra field | Packet 05 | Still present, still accepted (additive) |
| 2 transparent CSS border tokens unreferenced | Packet 10 | Design tokens by intent |
| `repositories.last_quick_scan_at` never written | Packet 00+ | Spec-defined slot, not drift |
| SSE step label "branches" stale | Packet 16 | Fixed in packet 16 drift audit |
| Redundant `import re` in check_ruby_outdated | Packet 16 | Fixed in packet 16 drift audit |

---

## Findings Summary

| # | Finding | Category | Severity | Action | Status |
|---|---------|----------|----------|--------|--------|
| 1 | Unused `import urllib.error` never referenced | Code hygiene | Trivial | `repair_now` | **Fixed** |
| 2 | 8 test files untracked (103 tests not version-controlled) | VCS hygiene | Low | Operator: commit | Carryover |

---

## Verdict

| Field | Value |
|-------|-------|
| Status | **repair_now** |
| Severity | low |
| Effort | small |
| Fixes applied | Yes (1 fix: removed unused `import urllib.error`) |
| Validation rerun | targeted (full suite 356/356 before and after fix) |
| Notes | No architectural drift after packet 17. Schema, all 14 API contracts, CSS design system, full dependency pipeline (detection → parsing → 6 ecosystem health checks → DB orchestration → fleet API integration → deps sub-tab UI), and tracker state all match the intended architecture. All 356 tests pass before and after fix. The unused import is a trivial code hygiene fix from packet 13's urllib.request usage. The only carryover finding is 8 untracked test files (operator VCS hygiene, worsened by +1 since packet 16 audit). |
