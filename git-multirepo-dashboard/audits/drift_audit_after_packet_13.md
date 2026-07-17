# Drift Audit — After Packet 13

**Auditor:** Claude Opus 4.6
**Date:** 2026-03-10
**Frontier:** Packet 13 (Python Dep Health)
**Validated packets:** 00, 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13
**Validated count:** 14
**Result:** PASS — No meaningful drift detected

---

## Methodology

1. Read all validated packet docs (00–13) and their validation audits.
2. Read `docs/git_dashboard_final_spec.md` — all sections relevant to packets 00–13.
3. Read `git_dashboard.py` in full (3,726 lines on disk).
4. Read all 14 test files (261 tests total).
5. Ran the full test suite: **261/261 passed** (2.77s).
6. Compared `plans/packet_status.json` and `plans/packet_status.md` for consistency.
7. Reviewed all prior drift audits (after packets 02, 05, 08, 09, 10).
8. Verified each validated packet's acceptance criteria still hold against the current codebase.
9. Verified CSS custom properties, API contracts, schema, and function inventory.

---

## Tracker State Verification

| Check | Result |
|-------|--------|
| `packet_status.json` and `packet_status.md` agree on all statuses | PASS |
| `highest_validated_packet` = "13" matches both files | PASS |
| Dependency graph matches canonical ladder in playbook | PASS |
| All packets 14–23 are `planned` (no premature status advancement) | PASS |
| Packet doc paths in JSON match actual file paths in `plans/` | PASS |
| `drift_audit_state.json` shows `next_due_validated_count: 14` (we are at 14) | PASS |

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

All columns in all tables are actively used or are correctly deferred to future packets:

- `repositories.last_quick_scan_at`: Defined in both spec and code, never written. The quick scan timestamp is tracked via `working_state.checked_at`. This column was present since packet 00 and has been verified as spec-matching in every prior audit. Not drift — the column is a spec-defined slot for future use.
- `scan_log.finished_at` and `repos_scanned`: Both actively written during scan lifecycle (lines 865, 901, 913–916).
- `dependencies` table: All columns populated by packet 13's health check enrichment pipeline (`current_version`, `wanted_version`, `latest_version`, `severity`, `advisory_id`, `checked_at`).

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

### Packet 11 Endpoint Detail

- **GET /api/repos/{id}/commits**: Reuses `parse_git_log()` from packet 06 (line 3548). Maps `subject` → `message` per spec (line 3554). Pagination via `--skip`/`--max-count`. Total via `git rev-list --count --all`. Clamped params: page ≥ 1, per_page 1–100.
- **GET /api/repos/{id}/branches**: Reads from `branches` table. ORDER BY `is_default DESC, last_commit_date DESC`. Returns `is_default` and `is_stale` as booleans.

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

## Packets 11–13 Acceptance Criteria Reverification

### Packet 11 — Commits & Branches Sub-tabs (21 criteria)

| # | Criterion | Status |
|---|-----------|--------|
| 1 | GET /api/repos/{id}/commits returns 200 with commits, page, per_page, total | PASS |
| 2 | Each commit has hash, date, author, message, insertions, deletions, files_changed | PASS |
| 3 | Pagination works (--skip/--max-count) | PASS |
| 4 | total = git rev-list --count --all | PASS |
| 5 | 404 for unknown repo | PASS |
| 6 | GET /api/repos/{id}/branches returns 200 | PASS |
| 7 | Each branch has name, last_commit_date, is_default, is_stale | PASS |
| 8 | Branches sorted: default first, then by last_commit_date desc | PASS |
| 9 | 404 for unknown repo | PASS |
| 10 | CommitsTab renders table with Date, Message, +/-, Files columns | PASS |
| 11 | Pagination controls (Prev, page indicator, Next) | PASS |
| 12 | Insertions green, deletions red | PASS |
| 13 | BranchesTab renders table with Branch, Last Commit, Status | PASS |
| 14 | Default branch shows blue badge | PASS |
| 15 | Stale branches show orange badge with days | PASS |
| 16 | Active branches show muted text | PASS |
| 17 | PlaceholderTab no longer used for Commits/Branches | PASS |
| 18 | #/repo/{id}/commits direct nav works | PASS |
| 19 | #/repo/{id}/branches direct nav works | PASS |
| 20 | Sub-tab click updates hash | PASS |
| 21 | All 193+ tests pass | PASS (261/261) |

### Packet 12 — Dependency Detection & Parsing (19 criteria)

| # | Criterion | Status |
|---|-----------|--------|
| 1 | detect_dep_files() identifies all 7 manifest types | PASS |
| 2 | Returns highest-priority file per runtime | PASS |
| 3 | Returns files for all runtimes in mixed repos | PASS |
| 4 | Returns [] for no manifests | PASS |
| 5 | parse_requirements_txt() extracts names and pinned versions | PASS |
| 6 | Skips comments, blanks, -e, flags | PASS |
| 7 | Follows -r includes one level, no circular loops | PASS |
| 8 | parse_pyproject_toml() extracts PEP 621 deps | PASS |
| 9 | Extracts Poetry deps | PASS |
| 10 | parse_package_json() extracts deps + devDeps | PASS |
| 11 | parse_go_mod() extracts from require blocks | PASS |
| 12 | parse_cargo_toml() handles string and table formats | PASS |
| 13 | parse_gemfile() extracts gem names and versions | PASS |
| 14 | parse_composer_json() extracts require + require-dev, skips php/ext-* | PASS |
| 15 | Standard shape {name, version, manager} | PASS |
| 16 | parse_deps_for_repo() orchestrates detection + parsing | PASS |
| 17 | Returns [] for no manifests | PASS |
| 18 | No TOML crash (graceful degradation) | PASS |
| 19 | All 235+ tests pass | PASS (261/261) |

### Packet 13 — Python Dep Health (16 criteria)

| # | Criterion | Status |
|---|-----------|--------|
| 1 | classify_severity() returns "ok" for same versions | PASS |
| 2 | Returns "outdated" for same-major different-minor/patch | PASS |
| 3 | Returns "major" for different major versions | PASS |
| 4 | check_python_outdated() queries PyPI, sets latest_version | PASS |
| 5 | Skips deps with version=None | PASS |
| 6 | Handles PyPI network errors gracefully | PASS |
| 7 | Handles invalid PyPI JSON gracefully | PASS |
| 8 | check_python_vulns() skips when pip-audit not installed | PASS |
| 9 | Parses pip-audit JSON, sets severity=vulnerable + advisory_id | PASS |
| 10 | Handles pip-audit subprocess failures gracefully | PASS |
| 11 | Vuln severity overrides outdated/major | PASS |
| 12 | check_python_deps() orchestrates both checks | PASS |
| 13 | Works with only outdated check (no pip-audit) | PASS |
| 14 | Returns [] for empty input | PASS |
| 15 | All enriched dicts have 9 required fields | PASS |
| 16 | All 261+ tests pass | PASS (261/261) |

---

## CSS Design System vs Spec §5.2

All custom properties in `:root` match spec §5.2. CDN versions still pinned: React 18.2.0, ReactDOM 18.2.0, Babel 7.23.9, Recharts 2.12.7.

### CSS Usage Audit

All defined CSS custom properties are actively referenced or serve as design tokens used via string interpolation:

- **Status colors + bg variants**: All 8 used (status pills, badges, KPI conditional coloring).
- **Freshness tokens**: `--fresh-this-week`, `--fresh-this-month`, `--fresh-older`, `--fresh-stale` all referenced in `freshnessStyle()`. Border tokens `--fresh-border-this-month` and `--fresh-border-older` are defined as `transparent` (intentionally invisible) but not referenced in component code — the middle freshness tiers have no border by design.
- **Runtime colors**: All 9 used via string interpolation in `RuntimeBadge`: `` `var(--runtime-${type}, var(--text-muted))` ``.
- **Transition tokens**: `--transition-fast`, `--transition-normal` used directly; `--transition-slow` used for toast slide animations (lines 2149–2150).

**Net unused CSS tokens (defined but never referenced):** 2 — `--fresh-border-this-month` (transparent) and `--fresh-border-older` (transparent). Both are intentionally invisible design placeholders for tiers that have no border accent. No action needed.

---

## Cross-Packet Boundary Check

| Check | Result |
|-------|--------|
| No dep scan orchestration (packet 16) | PASS — type="deps" is a no-op in run_fleet_scan |
| No dependencies sub-tab content (packet 17) | PASS — PlaceholderTab |
| No Node/Go/Rust/Ruby/PHP health checks (packets 14–15) | PASS |
| No DB writes from dep health checks (packet 16) | PASS — check_python_deps returns dicts, no DB |
| No analytics features (packets 18–21) | PASS |
| No error state UI (packet 22) | PASS |
| No polish/accessibility (packet 23) | PASS |
| Placeholder values correct for unimplemented features | PASS |

---

## Code Health

| Check | Result |
|-------|--------|
| Unused imports | NONE — all imports actively used |
| Dead code | NONE |
| Unreferenced functions | NONE |
| TODO/FIXME/HACK markers | NONE |
| Logger usage | Active — 12 logger.warning/error calls across dep parsing and scan error paths |
| Scope issues | NONE — prior Full Scan button fix still in place with regression test |

---

## Data Flow Verification (Packets 11–13)

### Packet 11: Commits Endpoint → parse_git_log Reuse
- `get_repo_commits()` (line 3513) reuses `parse_git_log()` from packet 06 (line 3548).
- `subject` → `message` field mapping (line 3554) matches packet 11 spec.
- Pagination via `--skip`/`--max-count` git args with proper clamping.

### Packet 12: Dep Parsers → Standard Shape
- All 8 parsers return `[{name, version, manager}]` — consistent contract.
- `parse_deps_for_repo()` orchestrates detection + parsing correctly.
- No DB writes (data stays in memory for health checks).

### Packet 13: Health Enrichment Pipeline
- `check_python_deps()` receives `[{name, version, manager}]` from parsers.
- Maps `version` → `current_version` via `setdefault` (line 1501).
- Stamps all 9 required fields: `name, version, manager, current_version, wanted_version, latest_version, severity, advisory_id, checked_at`.
- No DB writes — correct per packet boundary (packet 16 handles DB integration).

---

## Prior Audit Findings Review

| Prior Finding | Source | Current Status |
|---------------|--------|----------------|
| KPI aggregation gap (4 KPIs hardcoded 0) | Packet 08 | Fixed, still correct |
| Header Full Scan button scope bug | Packet 09 | Fixed, regression test in place |
| 7 test files untracked | Packet 09+ | **Carryover** — same 7 files still untracked |
| `orch_launch.sh` untracked | Packet 05 | Resolved (now tracked) |
| Stale docstrings/comments | Packet 08 | Fixed, no new stale comments |
| `last_commit_hash` extra field | Packet 05 | Still present, still accepted (additive) |
| 2 transparent CSS border tokens unreferenced | Packet 10 | Not explicitly flagged before but present since packet 05 — design tokens by intent |

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
| `tests/test_project_detail.py` | 10 | 14 |

This represents 92 tests not version-controlled. Flagged since the packet-05 audit. Not architectural drift — operator VCS hygiene.

**Recommendation:** Commit all untracked test files before proceeding further.

---

## Findings Summary

| # | Finding | Category | Severity | Action |
|---|---------|----------|----------|--------|
| 1 | 7 test files untracked (92 tests not version-controlled) | VCS hygiene | Low | Operator: commit |

---

## Verdict

| Field | Value |
|-------|-------|
| Status | **pass** |
| Severity | low |
| Effort | N/A |
| Fixes applied | No |
| Validation rerun | none |
| Notes | No architectural drift after packet 13. Schema, all 12 API contracts, CSS design system, dependency parsing pipeline, Python health check enrichment, UI components, and tracker state all match the intended architecture. All 261 tests pass. Packets 11–13 acceptance criteria all reverified. Data flow from dep parsers → health enrichment is clean (standard shape, no premature DB writes). The only finding is a carryover VCS hygiene issue (7 untracked test files). Prior drift repair (Full Scan button scope) still in place with regression test. |
