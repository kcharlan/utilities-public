# Drift Audit — After Packet 10

**Auditor:** Claude Opus 4.6
**Date:** 2026-03-10
**Frontier:** Packet 10 (Project Detail View & Activity Chart)
**Validated packets:** 00, 01, 02, 03, 04, 05, 06, 07, 08, 09, 10
**Result:** PASS — No meaningful drift detected

---

## Methodology

1. Read all validated packet docs (00–10) and their validation audits.
2. Read `docs/git_dashboard_final_spec.md` — all sections relevant to packets 00–10 (§1–§6, §9).
3. Read `git_dashboard.py` in full (2,966 lines on disk).
4. Read all 12 test files (178 tests total).
5. Ran the full test suite: **178/178 passed** (1.67s).
6. Compared `plans/packet_status.json` and `plans/packet_status.md` for consistency.
7. Reviewed all prior drift audits (after packets 02, 05, 08, 09).
8. Verified each validated packet's acceptance criteria still hold against the current codebase.

---

## Tracker State Verification

| Check | Result |
|-------|--------|
| `packet_status.json` and `packet_status.md` agree on all statuses | PASS |
| `highest_validated_packet` = "10" matches both files | PASS |
| Dependency graph matches canonical ladder in playbook | PASS |
| All packets 11–23 are `planned` (no premature status advancement) | PASS |
| Packet doc paths in JSON match actual file paths in `plans/` | PASS |
| `drift_audit_state.json` shows `next_due_validated_count: 11` (we are at 11) | PASS |

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
| `GET /api/repos/{repo_id}` | `{id, name, path, runtime, default_branch, working_state, last_full_scan_at}` | Same | YES |
| `GET /api/repos/{repo_id}/history` | `{repo_id, days, data: [{date, commits, insertions, deletions, files_changed}]}` | Same | YES |

### Packet 10 Endpoints — Detailed Verification

**GET /api/repos/{repo_id}** (spec §4 lines 498–511):
- Returns: `id`, `name`, `path`, `runtime`, `default_branch`, `working_state` (dict with all working_state columns), `last_full_scan_at` — **matches spec exactly**.
- 404 on missing repo — correct.

**GET /api/repos/{repo_id}/history** (spec §4 lines 514–527):
- Returns: `repo_id`, `days`, `data` (list of `{date, commits, insertions, deletions, files_changed}`) — **matches spec exactly**.
- Default `days=90` — correct.
- 404 on missing repo — correct.
- Date filtering via `date >= cutoff` with `cutoff = today - timedelta(days=days)` — correct.
- Only dates with activity included — correct.

### GET /api/fleet — Per-Repo Fields (Spec §4.1)

| Field | Present | Correct |
|-------|---------|---------|
| id, name, path, runtime, default_branch | YES | YES |
| current_branch, last_commit_date, last_commit_message | YES | YES |
| has_uncommitted, modified_count, untracked_count, staged_count | YES | YES |
| branch_count, stale_branch_count | YES | YES |
| dep_summary | YES | null placeholder (packet 16) |
| sparkline | YES | 13-element list from compute_sparklines() |
| last_commit_hash | YES | Additive, forward-compatible |

### GET /api/fleet — KPIs

| KPI | Status |
|-----|--------|
| total_repos | Correct (computed) |
| repos_with_changes | Correct (computed) |
| commits_this_week | Correct (from daily_stats) |
| commits_this_month | Correct (from daily_stats) |
| net_lines_this_week | Correct (from daily_stats) |
| stale_branches | Correct (sum of per-repo stale_branch_count) |
| vulnerable_deps | Correct placeholder (0, packet 16) |
| outdated_deps | Correct placeholder (0, packet 16) |

---

## Packet 10 Acceptance Criteria Reverification — All 18 Still Hold

| # | Criterion | Status |
|---|-----------|--------|
| 1 | `GET /api/repos/{valid_id}` returns 200 with correct fields | PASS |
| 2 | `GET /api/repos/{invalid_id}` returns 404 | PASS |
| 3 | `GET /api/repos/{id}/history?days=90` returns correct shape | PASS |
| 4 | History defaults to 90 days when `days` param omitted | PASS |
| 5 | History excludes dates outside requested window | PASS |
| 6 | History returns 404 for non-existent repos | PASS |
| 7 | Card click navigates to `#/repo/{id}`, renders ProjectDetail | PASS |
| 8 | Detail header shows name, path, runtime badge, branch, scan time | PASS |
| 9 | Back button navigates to `#/fleet` | PASS |
| 10 | Sub-tabs: Activity, Commits, Branches, Dependencies | PASS |
| 11 | Activity is default sub-tab | PASS |
| 12 | Diverging area chart: insertions (green up), deletions (red down), net (blue line) | PASS |
| 13 | TimeRangeSelector: 30d, 90d, 180d, 1y, All; default 90d | PASS |
| 14 | Changing range refetches and updates chart | PASS |
| 15 | Tooltip: date, insertions, deletions, net, commits | PASS |
| 16 | Global table CSS defined (.table-container, .table-header, .table-row, .table-empty) | PASS |
| 17 | Commits, Branches, Dependencies render PlaceholderTab | PASS |
| 18 | All tests pass (178/178, no regressions) | PASS |

---

## CSS Design System vs Spec §5.2

No changes to CSS since prior audit. All 46 custom properties in `:root` still match spec §5.2 verbatim. CDN versions still pinned: React 18.2.0, ReactDOM 18.2.0, Babel 7.23.9, Recharts 2.12.7.

Global table CSS classes added in packet 10 match spec §5.5 lines 943–954:
- `.table-container` — width 100%, border-radius, overflow hidden
- `.table-header` — bg-secondary, font styling, padding, bottom border
- `.table-row` — padding, alternating backgrounds, hover state
- `.table-empty` — centered muted text

---

## Activity Chart Implementation vs Spec §5.5

The spec has a minor internal contradiction: line 958 names `<ComposedChart>` while line 967 says `<AreaChart>`. The implementation uses `<AreaChart>` with `stackOffset="sign"` (following line 967) and represents the net line as `<Area fill="none">` — the correct workaround for the Recharts limitation where `<Line>` inside `<AreaChart>` is silently ignored. This is architecturally sound.

| Spec requirement | Implementation | Match |
|-----------------|----------------|-------|
| `stackOffset="sign"` | Present on AreaChart | YES |
| Insertions: green area upward, 20% opacity, strokeWidth 1.5 | Correct | YES |
| Deletions: negated values, red area downward, 20% opacity, strokeWidth 1.5 | Correct | YES |
| Net: blue line overlay, strokeWidth 2, no fill | `Area fill="none"` stroke blue, strokeWidth 2 | YES |
| Zero reference line | `ReferenceLine y={0}` with border-default stroke | YES |
| 300px height, 100% width | `ResponsiveContainer width="100%" height={300}` | YES |
| Tooltip with styled container | CustomTooltip with correct colors and layout | YES |
| fillDateGaps for continuous date series | Present, fills zeros for missing dates | YES |

---

## Cross-Packet Boundary Check

| Check | Result |
|-------|--------|
| No commits sub-tab content (packet 11) | PASS — PlaceholderTab |
| No branches sub-tab content (packet 11) | PASS — PlaceholderTab |
| No dependency parsing beyond runtime classification (packet 12+) | PASS |
| No analytics features (packets 18–21) | PASS |
| No error state UI (packet 22) | PASS |
| No polish/accessibility enhancements (packet 23) | PASS |
| Placeholder values correct for unimplemented features | PASS |

---

## Code Health

| Check | Result |
|-------|--------|
| Unused imports | NONE — all imports actively used (including `Timer` at line 2958) |
| Dead code | NONE |
| Unreferenced functions | NONE |
| Scope issues (closures, prop drilling) | NONE — prior Full Scan button fix still in place |
| Function-level import in `get_repo_history` (`import datetime as _dt_mod`) | Intentional — avoids shadowing top-level `datetime` class import |

---

## Prior Audit Findings Review

| Prior Finding | Source Audit | Current Status |
|---------------|-------------|----------------|
| KPI aggregation gap (4 KPIs hardcoded 0) | Packet 08 | Fixed, still correct |
| Header Full Scan button scope bug | Packet 09 | Fixed, regression test in place (test_full_scan_button_uses_prop_not_closure) |
| 7 test files untracked | Packet 09 | Carryover — still 7 files (test_sparklines_progress.py was committed; test_project_detail.py added) |
| `orch_launch.sh` untracked | Packet 05 | **Resolved** — now tracked in git |
| Stale docstrings/comments | Packet 08 | Fixed, no new stale comments |
| `last_commit_hash` extra field | Packet 05 | Still present, still accepted (additive) |

---

## Findings

### Finding 1 — VCS Hygiene: 7 Untracked Test Files (Carryover)

**Category:** VCS hygiene
**Severity:** Low
**Action:** Note for operator

7 test files remain untracked (not committed to git):

| File | Packet | Tests |
|------|--------|-------|
| `tests/test_fleet_api.py` | 03 | 9 |
| `tests/test_html_shell.py` | 04 | 10 |
| `tests/test_fleet_overview_ui.py` | 05 | 14 |
| `tests/test_git_full_history.py` | 06 | 15 |
| `tests/test_branch_scan.py` | 07 | 13 |
| `tests/test_full_scan_sse.py` | 08 | 17 |
| `tests/test_project_detail.py` | 10 | 13 |

This represents 91 tests not version-controlled. The working tree is otherwise clean (no uncommitted changes to tracked files). `test_sparklines_progress.py` was committed during the packet 09 drift repair; `test_project_detail.py` was added by packet 10.

**Recommendation:** Commit all untracked test files before proceeding to packet 11.

---

## Findings Summary

| # | Finding | Category | Severity | Action |
|---|---------|----------|----------|--------|
| 1 | 7 test files untracked (91 tests not version-controlled) | VCS hygiene | Low | Operator: commit |

---

## Verdict

| Field | Value |
|-------|-------|
| Status | **pass** |
| Severity | low |
| Effort | N/A |
| Fixes applied | No |
| Validation rerun | none |
| Notes | No architectural drift. Schema, API contracts, CSS design system, UI components, and tracker state all match the intended architecture. All 178 tests pass. The only finding is a carryover VCS hygiene issue (7 untracked test files) which is operator-actionable, not architectural drift. Prior findings from packet 09 audit (Full Scan button scope bug) remain fixed with regression test in place. orch_launch.sh is now tracked (resolved). |
