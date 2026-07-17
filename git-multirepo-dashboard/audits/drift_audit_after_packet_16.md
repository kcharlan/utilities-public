# Drift Audit — After Packet 16

**Auditor:** Claude Opus 4.6
**Date:** 2026-03-10
**Frontier:** Packet 16 (Dep Scan Orchestration)
**Validated packets:** 00, 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15, 16
**Validated count:** 17
**Result:** REPAIR_NOW — 2 small fixes applied

---

## Methodology

1. Read all validated packet docs (00–16) and their validation audits.
2. Read `docs/git_dashboard_final_spec.md` — all sections relevant to packets 00–16 (sections 1–4, 5.1–5.5, 6).
3. Read `git_dashboard.py` in full (4,612 lines on disk).
4. Read all 17 test files (345 tests total).
5. Ran the full test suite: **345/345 passed** (3.10s) — before and after fixes.
6. Compared `plans/packet_status.json` and `plans/packet_status.md` for consistency.
7. Reviewed all prior drift audits (after packets 02, 05, 08, 09, 10, 13).
8. Verified each validated packet's acceptance criteria still hold against the current codebase.
9. Verified CSS custom properties, API contracts, schema, and function inventory.

---

## Tracker State Verification

| Check | Result |
|-------|--------|
| `packet_status.json` and `packet_status.md` agree on all statuses | PASS |
| `highest_validated_packet` = "16" matches both files | PASS |
| Dependency graph matches canonical ladder in playbook | PASS |
| All packets 17–23 are `planned` (no premature status advancement) | PASS |
| Packet doc paths in JSON match actual file paths in `plans/` | PASS |
| `drift_audit_state.json` shows `next_due_validated_count: 17` (we are at 17) | PASS |

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
- `dependencies` table: All columns actively populated by packets 13–16 health check + orchestration pipeline.

---

## API Contract Verification

### All 12 Implemented Endpoints

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

### GET /api/fleet — dep_summary and KPIs

| Field | Spec | Code | Match |
|-------|------|------|-------|
| `dep_summary.total` | integer | COUNT(*) from dependencies | YES |
| `dep_summary.outdated` | integer | SUM(severity IN ('outdated','major')) | YES |
| `dep_summary.vulnerable` | integer | SUM(severity = 'vulnerable') | YES |
| `dep_summary` when no deps | null | null (total_deps > 0 guard) | YES |
| `kpis.vulnerable_deps` | integer | COALESCE from dependencies table | YES |
| `kpis.outdated_deps` | integer | COALESCE from dependencies table | YES |

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

## Packets 14–16 Acceptance Criteria Reverification

### Packet 14 — Node Dep Health (all criteria verified)

All 22 test cases pass. `check_node_outdated` (npm outdated --json), `check_node_vulns` (npm audit --json), `check_node_deps` orchestrator. Exit-code-1-safe for npm. 9 required fields stamped. No scope creep.

### Packet 15 — Go / Rust / Ruby / PHP Dep Health (all 24 criteria verified)

All 46 test cases pass. 12 functions + 2 helpers. NDJSON parser uses JSONDecoder.raw_decode. v-prefix stripped for Go. Ruby regex handles hyphens. Tool availability checked independently per key. Vuln overrides outdated for all 4 ecosystems. No scope creep.

### Packet 16 — Dep Scan Orchestration (all 16 criteria verified)

All 16 test cases pass. `run_dep_scan_for_repo()` routes through 6 ecosystem checkers. INSERT OR REPLACE upsert. Stale dep cleanup. type=deps real implementation. type=full includes deps. dep_summary from DB. KPI vulnerable_deps/outdated_deps from DB. No scope creep.

---

## CSS Design System vs Spec §5.2

All custom properties in `:root` match spec §5.2. CDN versions still pinned: React 18.2.0, ReactDOM 18.2.0, Babel 7.23.9, Recharts 2.12.7.

**Net unused CSS tokens:** 2 — `--fresh-border-this-month` (transparent) and `--fresh-border-older` (transparent). Design placeholders by intent. (Carryover from prior audits.)

---

## Cross-Packet Boundary Check

| Check | Result |
|-------|--------|
| No dependencies sub-tab content (packet 17) | PASS — PlaceholderTab for deps |
| No analytics features (packets 18–21) | PASS — placeholder text |
| No error state UI (packet 22) | PASS |
| No polish/accessibility (packet 23) | PASS |
| No `GET /api/repos/{id}/deps` endpoint (packet 17) | PASS |
| No `GET /api/analytics/*` endpoints (packets 18–20) | PASS |
| Placeholder values correct for unimplemented features | PASS |

---

## Code Health

| Check | Result |
|-------|--------|
| Unused imports | NONE after fix (redundant `import re` inside check_ruby_outdated removed) |
| Dead code | NONE |
| Unreferenced functions | NONE |
| TODO/FIXME/HACK markers | NONE |
| Logger usage | Active — properly used across all dep check and scan error paths |
| Scope issues | NONE — prior Full Scan button fix still in place with regression test |

---

## Findings

### Finding 1 — SSE Step Label Stale After Packet 16 (FIXED)

**Category:** API contract deviation
**Severity:** Low
**Action:** `repair_now` — applied

When packet 16 added `run_dep_scan_for_repo()` to the full scan path (line 997), the SSE progress event at line 1004 was not updated. It still emitted `"step": "branches"` when the last step completed is now `"deps"`.

**Root cause:** Packet 16 correctly added `run_dep_scan_for_repo` to the full scan loop but didn't update the SSE event's step label, which was set to "branches" back in packet 08 when only history+branches ran.

**Fix applied:** Changed `"step": "branches"` to `"step": "deps"` at line 1004 of `run_fleet_scan()` for the type="full" path. The type="deps" path already correctly used `"step": "deps"`.

**Impact:** No tests broke. The existing SSE test (`test_sse_progress_events_shape`) checks for the presence of the `step` key but does not assert its value.

### Finding 2 — Redundant `import re` in check_ruby_outdated (FIXED)

**Category:** Code hygiene
**Severity:** Trivial
**Action:** `repair_now` — applied

The function `check_ruby_outdated()` at line 2113 had `import re` inside the function body, despite `re` already being imported at module level (line 14). This was introduced in packet 15 and not caught during validation.

**Fix applied:** Removed the redundant `import re` line.

### Finding 3 — VCS Hygiene: 7 Untracked Test Files (Carryover)

**Category:** VCS hygiene
**Severity:** Low
**Action:** Note for operator

Same 7 test files remain untracked (not committed to git):

| File | Packet | Tests |
|------|--------|-------|
| `tests/test_fleet_api.py` | 03 | 9 |
| `tests/test_html_shell.py` | 04 | 10 |
| `tests/test_fleet_overview_ui.py` | 05 | 14 |
| `tests/test_git_full_history.py` | 06 | 15 |
| `tests/test_branch_scan.py` | 07 | 13 |
| `tests/test_full_scan_sse.py` | 08 | 17 |
| `tests/test_project_detail.py` | 10 | 14 |

92 tests not version-controlled. Flagged since the packet-05 audit. Not architectural drift.

**Recommendation:** Commit all untracked test files before proceeding further.

---

## Data Flow Verification (Packets 14–16)

### Packet 14: Node Health Enrichment Pipeline
- `check_node_deps()` filters npm deps, runs outdated + vulns, stamps 9 required fields.
- npm outdated exit-code-1 handled correctly (not CalledProcessError).
- `check_node_vulns()` uses `advisory_id = "npm:<name>"` format per spec.

### Packet 15: Go/Rust/Ruby/PHP Health Enrichment
- All 4 ecosystem checkers follow the same split/outdated/vulns/stamp pattern.
- `classify_severity` reused (no duplicates) — confirmed by test.
- `_strip_v()` strips Go version prefixes before comparison.
- `_parse_go_ndjson()` uses JSONDecoder.raw_decode for NDJSON.

### Packet 16: Dep Scan → DB Integration
- `run_dep_scan_for_repo()` calls `parse_deps_for_repo()` → routes through 6 ecosystem checkers (each in try/except) → INSERT OR REPLACE upsert → delete stale deps.
- `run_fleet_scan(type="deps")`: iterates repos sequentially, calls dep scan only.
- `run_fleet_scan(type="full")`: now calls history + branches + deps per repo.
- `GET /api/fleet`: dep_summary computed from DB, null when no rows. KPIs from DB via COALESCE.

---

## Prior Audit Findings Review

| Prior Finding | Source | Current Status |
|---------------|--------|----------------|
| KPI aggregation gap (4 KPIs hardcoded 0) | Packet 08 | Fully resolved — all 8 KPIs from real data |
| Header Full Scan button scope bug | Packet 09 | Fixed, regression test still in place |
| 7 test files untracked | Packet 05+ | **Carryover** — same 7 files still untracked |
| `last_commit_hash` extra field | Packet 05 | Still present, still accepted (additive) |
| 2 transparent CSS border tokens unreferenced | Packet 10 | Design tokens by intent |
| `repositories.last_quick_scan_at` never written | Packet 00+ | Spec-defined slot, not drift |

---

## Findings Summary

| # | Finding | Category | Severity | Action | Status |
|---|---------|----------|----------|--------|--------|
| 1 | SSE step label "branches" stale after packet 16 added deps to full scan | API contract | Low | `repair_now` | **Fixed** |
| 2 | Redundant `import re` inside check_ruby_outdated | Code hygiene | Trivial | `repair_now` | **Fixed** |
| 3 | 7 test files untracked (92 tests not version-controlled) | VCS hygiene | Low | Operator: commit | Carryover |

---

## Verdict

| Field | Value |
|-------|-------|
| Status | **repair_now** |
| Severity | low |
| Effort | small |
| Fixes applied | Yes (2 fixes: SSE step label, redundant import) |
| Validation rerun | targeted (78 tests in affected modules + full suite 345/345) |
| Notes | No architectural drift after packet 16. Schema, all 12 API contracts, CSS design system, full dependency pipeline (detection → parsing → 6 ecosystem health checks → DB orchestration → fleet API integration), and tracker state all match the intended architecture. All 345 tests pass before and after fixes. The SSE step label fix is a minor correction to a value introduced by packet 08 that became stale when packet 16 extended the full scan to include dep scanning. The redundant import is a code hygiene fix. The only carryover finding is 7 untracked test files (operator VCS hygiene). |
