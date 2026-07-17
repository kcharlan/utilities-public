# Drift Audit — After Packet 21

**Auditor:** Claude Opus 4.6
**Date:** 2026-03-10
**Frontier:** Packet 21 (Analytics Tab Wiring)
**Validated packets:** 00, 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21
**Validated count:** 22
**Result:** PASS — no drift, no fixes needed

---

## Methodology

1. Read all validated packet docs (00–21) and their validation audits.
2. Read `docs/git_dashboard_final_spec.md` — sections §1–§5.6, all API contracts (§3–§4), schema (§2).
3. Read `git_dashboard.py` in full (5,417 lines on disk).
4. Read all 22 test files (402 tests total).
5. Ran the full test suite: **402/402 passed** (3.20s).
6. Compared `plans/packet_status.json` and `plans/packet_status.md` for consistency.
7. Reviewed all prior drift audits (after packets 02, 05, 08, 09, 10, 13, 16, 17, 18).
8. Verified each validated packet's acceptance criteria still hold against the current codebase.
9. Verified CSS custom properties, API contracts, schema, and function inventory.

---

## Tracker State Verification

| Check | Result |
|-------|--------|
| `packet_status.json` and `packet_status.md` agree on all statuses | PASS |
| `highest_validated_packet` = "21" matches both files | PASS |
| Dependency graph matches canonical ladder in playbook | PASS |
| Packets 22–23 are `planned` (no premature status advancement) | PASS |
| Packet doc paths in JSON match actual file paths for validated packets | PASS |
| `drift_audit_state.json` shows `next_due_validated_count: 22` (we are at 22) | PASS |
| `full_suite_state.json` shows `last_full_suite_validated_count: 18` | STALE (see note) |
| `full_suite_verification_after_packet_20` exit_code: 1 | EXPLAINED (see note) |

### Note: full_suite_state.json Staleness

The `full_suite_state.json` records `last_full_suite_validated_count: 18` (from the post-packet-17-repair verification). The `full_suite_verification_after_packet_20` ran at validated_count 21 but **failed** (exit_code 1). The failure was caused by `tests/test_analytics_tab_wiring.py` being on disk before packet 21's implementation — the test file asserts that `AnalyticsTab` exists and the "Analytics — coming soon" placeholder is removed, both of which only became true after packet 21 was implemented.

This is a timing artifact: the implementer wrote tests first (per procedure), but the full-suite verification ran between test-writing and implementation. The packet 21 validation subsequently confirmed **402/402 pass**, and this audit independently verified the same. The `full_suite_state.json` tracker remains stale but will be corrected by the next formal full-suite verification.

---

## Schema vs Spec (Section 2)

All 6 tables in `_SCHEMA_SQL` match spec section 2 exactly. No changes since prior audit.

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

### All 17 Implemented Endpoints

| Endpoint | Spec Status | Code Shape Match |
|----------|-------------|------------------|
| `GET /` | Supporting (§1) | HTMLResponse with full SPA template — YES |
| `GET /api/status` | Supporting (§1) | `{tools, version}` — YES |
| `POST /api/repos` | Spec §4 | `{registered: N, repos: [...]}` — YES |
| `DELETE /api/repos/{repo_id}` | Spec §4 | 204 / 404 — YES |
| `GET /api/repos` | Supporting | `{repos: [...]}` — YES |
| `GET /api/fleet` | Spec §4 | `{repos: [...], kpis: {...}, scanned_at}` — YES |
| `POST /api/fleet/scan` | Spec §4 | `{scan_id: <int>}` — YES |
| `GET /api/fleet/scan/{scan_id}/progress` | Spec §4 | SSE `text/event-stream` — YES |
| `GET /api/repos/{repo_id}` | Spec §4 | Detail with working_state, last_full_scan_at — YES |
| `GET /api/repos/{repo_id}/history` | Spec §4 | `{repo_id, days, data: [...]}` — YES |
| `GET /api/repos/{repo_id}/commits` | Spec §4 | `{commits, page, per_page, total}` — YES |
| `GET /api/repos/{repo_id}/branches` | Spec §4 | `{branches: [...]}` — YES |
| `GET /api/repos/{repo_id}/deps` | Spec §4 | `[{manager, packages, checked_at}]` — YES |
| `POST /api/repos/{repo_id}/scan/deps` | Supporting (packet 16) | Updated deps list — YES |
| `GET /api/analytics/heatmap` | Spec §4 | `{data: [{date, count}], max_count}` — YES |
| `GET /api/analytics/allocation` | Spec §4 | `{series: [{repo_id, name, data}]}` — YES |
| `GET /api/analytics/dep-overlap` | Spec §4 | `{packages: [{name, manager, repos, version_spread, count}]}` — YES |

All 13 spec-defined endpoints (§4) are implemented with matching response shapes. 4 additional supporting endpoints exist in code (legitimate functional needs: UI shell, tool status, repo listing, per-repo dep trigger).

### Packets 19–21 Analytics API Verification

| Endpoint | Packet | Expected | Actual | Match |
|----------|--------|----------|--------|-------|
| `GET /api/analytics/heatmap` | 18 | SUM(commits) per day, days filter (default 365), sorted ASC | Same | YES |
| `GET /api/analytics/allocation` | 19 | Per-repo commit series, days filter (default 90), only active repos | Same | YES |
| `GET /api/analytics/dep-overlap` | 20 | 2+ repo threshold, sorted count desc, version_spread min–max | Same | YES |

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

## Packets 19–21 Acceptance Criteria Reverification

### Packet 19: Analytics: Time Allocation (15 criteria)

All 15 criteria verified. `GET /api/analytics/allocation` returns correct series structure. `TimeAllocation` component: Recharts AreaChart, stackOffset=none, 10-color ALLOC_COLORS palette (spec-prescribed), weekly aggregation for days>=90, >10 repos merged into "Other", legend toggle, internal TimeRangeSelector.

### Packet 20: Analytics: Dep Overlap (15 criteria)

All 15 criteria verified. `GET /api/analytics/dep-overlap` returns correct package structure (2+ repo threshold, count desc sort, version spread). `DepOverlap` component: expandable rows with chevron toggle, 24px indent, data-table class, empty state message.

### Packet 21: Analytics Tab Wiring (14 criteria)

All 14 criteria verified. `AnalyticsTab` defined at line 4636. ContentArea renders `<AnalyticsTab />` at line 4686–4687. "Analytics — coming soon" placeholder removed. Three sections with correct headers (18px, var(--font-heading), weight 600, margin-bottom 16px). 32px gap. All three child components rendered with no props (self-fetching).

---

## CSS Design System vs Spec §5.2

45 CSS custom properties defined in `:root`. CDN versions pinned: React 18.2.0, ReactDOM 18.2.0, Babel 7.23.9, Recharts 2.12.7.

### CSS Variables Usage Audit

| Category | Defined | Referenced | Notes |
|----------|---------|-----------|-------|
| Background/surface (`--bg-*`) | 5 | 5 | All used |
| Border (`--border-*`) | 2 | 2 | All used |
| Text (`--text-*`) | 3 | 3 | All used |
| Accent (`--accent-*`) | 2 | 2 | All used |
| Status colors (`--status-*`) | 4 | 4 | All used |
| Status backgrounds (`--status-*-bg`) | 4 | 3 | `--status-red-bg` unreferenced |
| Freshness fills (`--fresh-*`) | 4 | 4 | All used |
| Freshness borders (`--fresh-border-*`) | 4 | 2 | `--fresh-border-this-month` and `--fresh-border-older` unreferenced (transparent) |
| Runtime colors (`--runtime-*`) | 9 | 9 | All used via `var(--runtime-${type})` in RuntimeBadge |
| Typography (`--font-*`) | 3 | 3 | All used |
| Radius (`--radius-*`) | 3 | 2 | `--radius-lg` unreferenced |
| Transitions (`--transition-*`) | 3 | 3 | All used |

**Net unreferenced CSS tokens:** 4 — `--status-red-bg`, `--fresh-border-this-month`, `--fresh-border-older`, `--radius-lg`. All are design system tokens defined by the spec. The border tokens are `transparent` (design intent). `--status-red-bg` and `--radius-lg` are available for future packets (Error States, Polish). Not drift.

### ALLOC_COLORS Palette (Packet 19)

The 10-color hardcoded palette `['#4c8dff', '#34d399', '#fbbf24', '#f97316', '#ef4444', '#a78bfa', '#ec4899', '#06b6d4', '#84cc16', '#f43f5e']` matches the spec §5.6 exactly. The first 5 values correspond to accent-blue, status-green, status-yellow, status-orange, status-red. The last 5 are spec-prescribed supplementary colors not in `:root`.

---

## Cross-Packet Boundary Check

| Check | Result |
|-------|--------|
| All 3 analytics components render in AnalyticsTab (packet 21 scope) | PASS |
| No error state UI (packet 22) | PASS |
| No polish/accessibility (packet 23) | PASS |
| No premature PATCH /api/repos/{id} endpoint (packet 22) | PASS |
| No scan_error or dep_check_error schema columns (packet 22) | PASS |
| "Dependencies — coming soon" placeholder intact at line 4692 | PASS (see observation) |

### Observation: Dependencies Tab Gap

The navigation includes a "Dependencies" tab that renders "Dependencies — coming soon" (line 4692). This tab was established in packet 04 (HTML Shell). No packet in the canonical ladder (22=Error States, 23=Polish) implements this tab's content. The spec defines a Dependencies cross-view tab as a separate concern from the analytics tab's Dependency Overlap section. This is a pre-existing gap between the spec and the packet ladder — not drift introduced by packets 19–21. Flagged for operator awareness; no action required within the current packet scope.

---

## Code Health

| Check | Result |
|-------|--------|
| Unused imports | NONE |
| Dead code | `is_valid_repo` defined/tested but not called in production (carryover since packet 01) |
| Unreferenced functions (beyond is_valid_repo) | NONE |
| TODO/FIXME/HACK markers | NONE |
| Logger usage | Active — properly used across all dep check and scan error paths |
| Hardcoded hex colors in React | 2 instances of `#fff` (lines 2720, 2834) + `rgba(255,255,255,0.02)` table striping (line 2640) — carryover |
| Total lines | 5,417 |

---

## Prior Audit Findings Review

| Prior Finding | Source | Current Status |
|---------------|--------|----------------|
| KPI aggregation gap (4 KPIs hardcoded 0) | Packet 08 | Fully resolved |
| Header Full Scan button scope bug | Packet 09 | Fixed, regression test in place |
| Untracked test files | Packet 05+ | **Carryover** — now 22 test files, at least 1 untracked per git status |
| `last_commit_hash` extra field | Packet 05 | Still present, still accepted (additive) |
| 2 transparent CSS border tokens unreferenced | Packet 10 | Design tokens by intent |
| `repositories.last_quick_scan_at` never written | Packet 00+ | Spec-defined slot, not drift |
| SSE step label "branches" stale | Packet 16 | Fixed in packet 16 repair |
| Redundant `import re` in check_ruby_outdated | Packet 16 | Fixed in packet 16 repair |
| Unused `import urllib.error` | Packet 17 | Fixed in packet 17 repair |
| 9 untracked test files | Packet 18 | **Carryover** (now 22 test files total) |

---

## Findings Summary

| # | Finding | Category | Severity | Action | Status |
|---|---------|----------|----------|--------|--------|
| 1 | Untracked test files (22 files) | VCS hygiene | Low | Operator: commit | Carryover |
| 2 | `is_valid_repo` defined/tested but not called in production | Code inventory | Trivial | None — available for packet 22 | Carryover |
| 3 | `#fff` hardcoded in 2 places (lines 2720, 2834) | Style consistency | Trivial | None — functional | Carryover |
| 4 | 4 unreferenced CSS design tokens (`--status-red-bg`, `--fresh-border-this-month`, `--fresh-border-older`, `--radius-lg`) | Design system | Trivial | None — spec-defined placeholders | Carryover |
| 5 | `full_suite_state.json` stale (says 18, actual 22) | Tracker hygiene | Low | Next full-suite verification will correct | New |
| 6 | Dependencies tab placeholder with no covering packet | Spec–ladder gap | Low | Operator awareness | Pre-existing |

No new architectural drift introduced by packets 19, 20, or 21. All findings are either carryover from prior audits or minor process observations.

---

## Verdict

| Field | Value |
|-------|-------|
| Status | **pass** |
| Severity | low |
| Effort | small |
| Fixes applied | No |
| Validation rerun | none |
| Notes | No architectural drift after packet 21. Schema (6 tables), all 17 API contracts, CSS design system (45 properties, 4 unreferenced design tokens), and analytics tab wiring (3 sections, 3 child components, 32px gap) all match the intended architecture. The AnalyticsTab correctly renders Heatmap, TimeAllocation, and DepOverlap with independent data fetching. All 402 tests pass. The only new observation is the stale `full_suite_state.json` tracker (records validated_count 18, actual is 22) — will self-correct at next formal full-suite verification. All other findings are carryover from prior audits. |
