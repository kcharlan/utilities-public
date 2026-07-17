# Drift Audit — After Packet 18

**Auditor:** Claude Opus 4.6
**Date:** 2026-03-10
**Frontier:** Packet 18 (Analytics: Heatmap)
**Validated packets:** 00, 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15, 16, 17, 18
**Validated count:** 19
**Result:** PASS — no drift, no fixes needed

---

## Methodology

1. Read all validated packet docs (00–18) and their validation audits.
2. Read `docs/git_dashboard_final_spec.md` — all sections relevant to packets 00–18 (§1–§5.6, §8.0 Phase 4).
3. Read `git_dashboard.py` in full (5,028 lines on disk).
4. Read all 19 test files (371 tests total).
5. Ran the full test suite: **371/371 passed** (3.68s).
6. Compared `plans/packet_status.json` and `plans/packet_status.md` for consistency.
7. Reviewed all prior drift audits (after packets 02, 05, 08, 09, 10, 13, 16, 17).
8. Verified each validated packet's acceptance criteria still hold against the current codebase.
9. Verified CSS custom properties, API contracts, schema, and function inventory.

---

## Tracker State Verification

| Check | Result |
|-------|--------|
| `packet_status.json` and `packet_status.md` agree on all statuses | PASS |
| `highest_validated_packet` = "18" matches both files | PASS |
| Dependency graph matches canonical ladder in playbook | PASS |
| All packets 19–23 are `planned` (no premature status advancement) | PASS |
| Packet doc paths in JSON match actual file paths for validated packets | PASS |
| `drift_audit_state.json` shows `next_due_validated_count: 19` (we are at 19) | PASS |
| `full_suite_state.json` shows `last_full_suite_validated_count: 18` | PASS |

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

### All 15 Implemented Endpoints

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
| `GET /api/analytics/heatmap` | `{data: [...], max_count}` | Same | YES |

### Packet 18 — Heatmap API Verification

| Aspect | Expected | Actual | Match |
|--------|----------|--------|-------|
| Endpoint path | `/api/analytics/heatmap` | Same | YES |
| Query | `SUM(commits) GROUP BY date ORDER BY date ASC` | Same | YES |
| Default days | 365 | 365 | YES |
| Response shape | `{data: [{date, count}], max_count}` | Same | YES |
| Empty DB | `{data: [], max_count: 0}` | Same | YES |
| Date format | YYYY-MM-DD string | Same | YES |
| max_count | `max(count) or 0` | Same | YES |

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

## Packet 18 Acceptance Criteria Reverification

All 15 acceptance criteria verified against the current codebase:

| # | Criterion | Status |
|---|-----------|--------|
| 1 | GET /api/analytics/heatmap returns 200 with `{data, max_count}` | PASS |
| 2 | `data` entries have `date` (YYYY-MM-DD) and `count` (int) | PASS |
| 3 | `data` sorted ascending by date | PASS |
| 4 | `max_count` = max count, or 0 if empty | PASS |
| 5 | `days` param filters window (default 365) | PASS |
| 6 | Commits aggregated across repos (SUM) | PASS |
| 7 | Empty DB returns `{data: [], max_count: 0}` | PASS |
| 8 | `function Heatmap` exists in HTML_TEMPLATE | PASS |
| 9 | Grid: 52 columns x 7 rows | PASS |
| 10 | 5-level color scale matches spec | PASS |
| 11 | Day labels (Mon, Wed, Fri) on left | PASS |
| 12 | Month labels along top | PASS |
| 13 | Tooltip shows date + commit count on hover | PASS |
| 14 | Cell hover outline: `2px solid var(--accent-blue)` | PASS |
| 15 | No regressions, all tests pass | PASS (371/371) |

---

## CSS Design System vs Spec §5.2

All 43 custom properties in `:root` match spec §5.2 exactly. CDN versions still pinned: React 18.2.0, ReactDOM 18.2.0, Babel 7.23.9, Recharts 2.12.7.

**Heatmap CSS usage (packet 18):**
- `var(--bg-secondary)` for 0-commit cells — correct
- `rgba(76,141,255,0.2/0.4/0.65/0.9)` for 4-level blue scale — spec-prescribed in §5.6
- `var(--accent-blue)` for cell hover outline — correct
- `var(--bg-card)` for tooltip background — correct
- `var(--border-default)` for tooltip border — correct
- `var(--radius-sm)` for tooltip corner radius — correct
- `var(--text-muted)` for day/month labels — correct
- No hardcoded hex colors in Heatmap component

**Net unused CSS tokens:** 2 — `--fresh-border-this-month` (transparent) and `--fresh-border-older` (transparent). Design placeholders by intent. (Carryover from prior audits.)

---

## Cross-Packet Boundary Check

| Check | Result |
|-------|--------|
| No `/api/analytics/allocation` endpoint (packet 19) | PASS |
| No `/api/analytics/dep-overlap` endpoint (packet 20) | PASS |
| No `TimeAllocation` or `DepOverlap` components (packets 19–20) | PASS |
| No `AnalyticsTab` wiring (packet 21) — analytics tab shows "coming soon" placeholder | PASS |
| Heatmap component defined but NOT rendered (correct for packet 18) | PASS |
| No error state UI (packet 22) | PASS |
| No polish/accessibility (packet 23) | PASS |

---

## Code Health

| Check | Result |
|-------|--------|
| Unused imports | NONE |
| Dead code | `is_valid_repo` defined/tested but not called in production (carryover since packet 01; see note below) |
| Unreferenced functions (beyond is_valid_repo) | NONE |
| TODO/FIXME/HACK markers | NONE |
| Logger usage | Active — properly used across all dep check and scan error paths |
| Hardcoded hex colors in React | 2 instances of `#fff` (lines 2720, 2834) — carryover, not new |

### Note on `is_valid_repo`

This function (line 384) was delivered in packet 01 as an intentional utility (`git rev-parse --is-inside-work-tree`). It has 3 passing tests. The packet 01 validation noted "the orchestration layer (packet 03) will call is_valid_repo before quick_scan_repo" — but packet 03's actual implementation handles invalid repos via error handling within `quick_scan_repo` rather than pre-validation. The function remains available for potential use by packet 22 (Error States & Edge Cases). Not architectural drift — it's a tested utility that was scoped but not yet integrated into a production code path.

---

## Prior Audit Findings Review

| Prior Finding | Source | Current Status |
|---------------|--------|----------------|
| KPI aggregation gap (4 KPIs hardcoded 0) | Packet 08 | Fully resolved |
| Header Full Scan button scope bug | Packet 09 | Fixed, regression test in place |
| 8 test files untracked | Packet 05+ | **Carryover** — now 9 files (was 8, +test_analytics_heatmap.py) |
| `last_commit_hash` extra field | Packet 05 | Still present, still accepted (additive) |
| 2 transparent CSS border tokens unreferenced | Packet 10 | Design tokens by intent |
| `repositories.last_quick_scan_at` never written | Packet 00+ | Spec-defined slot, not drift |
| SSE step label "branches" stale | Packet 16 | Fixed in packet 16 repair |
| Redundant `import re` in check_ruby_outdated | Packet 16 | Fixed in packet 16 repair |
| Unused `import urllib.error` | Packet 17 | Fixed in packet 17 repair |

---

## Findings Summary

| # | Finding | Category | Severity | Action | Status |
|---|---------|----------|----------|--------|--------|
| 1 | 9 test files untracked (was 8, +test_analytics_heatmap.py) | VCS hygiene | Low | Operator: commit | Carryover |
| 2 | `is_valid_repo` defined/tested but not called in production | Code inventory | Trivial | None — available for packet 22 | Carryover |
| 3 | `#fff` hardcoded in 2 places (lines 2720, 2834) | Style consistency | Trivial | None — functional | Carryover |

No new findings introduced by packet 18. All findings are carryover from prior audits.

---

## Verdict

| Field | Value |
|-------|-------|
| Status | **pass** |
| Severity | low |
| Effort | small |
| Fixes applied | No |
| Validation rerun | none |
| Notes | No architectural drift after packet 18. Schema (6 tables), all 15 API contracts, CSS design system (43 properties), heatmap implementation (endpoint + component), and tracker state all match the intended architecture. The heatmap component is correctly defined but not rendered — wiring deferred to packet 21. All 371 tests pass. The only findings are carryover items from prior audits: 9 untracked test files (operator VCS hygiene), `is_valid_repo` utility available but not yet integrated, and 2 trivial `#fff` hardcoded values. |
