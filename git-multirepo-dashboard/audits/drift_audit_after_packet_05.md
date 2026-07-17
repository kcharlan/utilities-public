# Drift Audit — After Packet 05

**Auditor:** Claude Opus 4.6
**Date:** 2026-03-10
**Frontier:** Packet 05 (Fleet Overview UI)
**Validated packets:** 00, 01, 02, 03, 04, 05
**Result:** PASS — no architectural drift detected

---

## Methodology

1. Read all validated packet docs (00–05) and their validation audits.
2. Read `docs/git_dashboard_final_spec.md` sections 1–5, 9, 11 (all sections relevant to packets 00–05).
3. Read `git_dashboard.py` in full (1825 lines on disk).
4. Read all test files (test_packet_00.py, test_git_quick_scan.py, test_repo_discovery.py, test_fleet_api.py, test_html_shell.py, test_fleet_overview_ui.py).
5. Ran the full test suite: **110/110 passed** (1.43s).
6. Compared `plans/packet_status.json` and `plans/packet_status.md` for consistency.
7. Reviewed the prior drift audit (`drift_audit_after_packet_02.md`) and its findings.
8. Verified each validated packet's acceptance criteria still hold against the current codebase.

---

## Tracker State Verification

| Check | Result |
|-------|--------|
| `packet_status.json` and `packet_status.md` agree on all statuses | PASS |
| `highest_validated_packet` = "05" matches both files | PASS |
| Dependency graph matches canonical ladder in playbook | PASS |
| All packets 06–23 are `planned` (no premature status advancement) | PASS |
| Packet doc paths in JSON match actual file paths in `plans/` | PASS |
| `drift_audit_state.json` shows `next_due_validated_count: 6` (we are at 6) | PASS |

---

## Schema vs Spec (Section 2)

All 6 tables in `_SCHEMA_SQL` (lines 272–339) match spec section 2 exactly. No schema changes since the prior drift audit:

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

## Bootstrap Constants vs Spec (Section 1)

No changes since prior audit. All constants match spec exactly.

---

## API Contract Verification

### Implemented Endpoints

| Endpoint | Spec Shape | Code Shape | Match |
|----------|-----------|------------|-------|
| `GET /` | HTML 200 | HTMLResponse with full SPA template | YES |
| `GET /api/status` | `{tools, version}` | `{"tools": TOOLS, "version": VERSION}` | YES |
| `POST /api/repos` | `{registered: N, repos: [{id, name, path}]}` | Same | YES |
| `DELETE /api/repos/{id}` | 204 / 404 | Same | YES |
| `GET /api/repos` | Not in spec §4 (additive, per packet 02) | `{repos: [...]}` | Accepted |
| `GET /api/fleet` | `{repos: [...], kpis: {...}, scanned_at}` | Same | YES |

### GET /api/fleet Response Shape (Packet 03)

Per-repo fields verified against spec §4.1:

| Field | Present | Correct type/default |
|-------|---------|---------------------|
| id | YES | string |
| name | YES | string |
| path | YES | string |
| runtime | YES | string |
| default_branch | YES | string |
| current_branch | YES | string |
| last_commit_date | YES | ISO 8601 or null |
| last_commit_message | YES | string or null |
| has_uncommitted | YES | boolean |
| modified_count | YES | integer |
| untracked_count | YES | integer |
| staged_count | YES | integer |
| branch_count | YES | 0 (placeholder) |
| stale_branch_count | YES | 0 (placeholder) |
| dep_summary | YES | null (placeholder) |
| sparkline | YES | [] (placeholder) |

**Note:** `last_commit_hash` is also present in the response (via `**data` spread in `scan_fleet_quick`). This field is not listed in spec §4.1 but is additive — it does not break any contract and will be useful for packet 10 (Project Detail View). Not drift.

KPI fields verified: all 8 fields present (`total_repos`, `repos_with_changes`, `commits_this_week`, `commits_this_month`, `net_lines_this_week`, `stale_branches`, `vulnerable_deps`, `outdated_deps`). Placeholder values (0) correct for unimplemented packets.

---

## CSS Design System vs Spec §5.2 (Packet 04)

All 46 CSS custom properties in `:root` (lines 786–854) match spec §5.2 verbatim:

| Category | Count | Match |
|----------|-------|-------|
| Base backgrounds | 5 | YES (exact hex values) |
| Borders | 2 | YES |
| Text | 3 | YES |
| Accent | 2 | YES |
| Status colors + backgrounds | 8 | YES |
| Freshness backgrounds | 4 | YES |
| Freshness borders | 4 | YES |
| Runtime colors | 9 | YES |
| Typography | 3 | YES (with system fallbacks) |
| Sizing | 3 | YES |
| Transitions | 3 | YES |

CDN versions pinned correctly: React 18.2.0, ReactDOM 18.2.0, Babel Standalone 7.23.9, Recharts 2.12.7.

---

## Fleet Overview UI vs Spec §5.4 (Packet 05)

### Component Hierarchy

| Component | Present | Matches spec |
|-----------|---------|-------------|
| FleetOverview | YES | Fetches `/api/fleet`, renders KPI + grid |
| KpiRow | YES | 6 cards with correct labels/mappings |
| KpiCard | YES | 28px heading, 12px label, flex layout |
| GridControls | YES | SortDropdown + FilterInput |
| SortDropdown | YES | Custom (not native select), 4 options |
| FilterInput | YES | "Filter projects..." placeholder |
| ProjectCard | YES | 3-row compact layout |
| RuntimeBadge | YES | All 11 labels (PY, JS, GO, RS, RB, PHP, SH, DK, HTML, MIX, ??) |
| StatusPills | YES | Clean/mod/new/staged variants |
| DepBadge | YES | Null-safe, vuln/outdated/total modes |
| SparklineOverlay | YES | translateY animation, AreaChart |
| EmptyState | YES | "No repositories registered" message |
| timeAgo | YES | Relative time with "never" for null |
| freshnessStyle | YES | 7/30/90 day thresholds |
| sortRepos | YES | Filter-then-sort, 4 sort modes |

### KPI Conditional Coloring

| KPI | Condition | Color | Code |
|-----|-----------|-------|------|
| Dirty | > 0 | `--status-yellow` | Line 1360 |
| Stale Br | > 0 | `--status-orange` | Line 1361 |
| Vuln/Out | > 0 | `--status-red` | Line 1362 |

### Card Freshness

| Age | Background | Left Border | Code |
|-----|-----------|-------------|------|
| ≤7d | `--fresh-this-week` | `--fresh-border-this-week` (blue) | Lines 1105–1109 |
| ≤30d | `--fresh-this-month` | none | Line 1111 |
| ≤90d | `--fresh-older` | none | Line 1112 |
| >90d/null | `--fresh-stale` | `--fresh-border-stale` (orange) | Lines 1098–1102, 1113–1116 |

---

## Hash Routing vs Spec §5.8 (Packet 04)

| Route | Expected | Implemented |
|-------|----------|-------------|
| `#/` or `#/fleet` | Fleet Overview | YES |
| `#/analytics` | Analytics placeholder | YES |
| `#/deps` | Dependencies placeholder | YES |
| `#/repo/{id}` | Detail placeholder | YES |
| Unknown hash | Default to fleet | YES |

View transitions: `opacity 0, translateY(8px)` → `opacity 1, translateY(0)` on tab/route change. The spec distinguishes between Fleet→Detail (translateY) and main tab switches (crossfade only), but the implementation applies translateY to all transitions. This was accepted by the packet 04 validator and doesn't affect correctness. Will be refined in packet 23 (Polish & Accessibility) if needed.

---

## Cross-Packet Boundary Check

| Check | Result |
|-------|--------|
| No features from packet 06+ (full history, branch scan, SSE) | PASS |
| No dependency parsing beyond runtime classification | PASS |
| Header buttons (Scan Dir, Full Scan) have no-op handlers | PASS |
| Placeholder values correct for unimplemented packets | PASS |
| No loading skeletons (packet 23) | PASS |
| No error state UI (packet 22) | PASS |

---

## Version Control Observations

**This section covers file tracking concerns. These are not architectural drift but are flagged per the global CLAUDE.md instruction to verify files are tracked after commits.**

### Untracked test files

Three test files exist on disk but are NOT committed to git:

| File | Packet | Tests | Status |
|------|--------|-------|--------|
| `tests/test_fleet_api.py` | 03 | 8 tests | Untracked |
| `tests/test_html_shell.py` | 04 | 10 tests | Untracked |
| `tests/test_fleet_overview_ui.py` | 05 | 14 tests | Untracked |

These 32 tests (of the 110 total) would be lost if the working tree is reset or cloned fresh.

### Uncommitted code changes

`git_dashboard.py` has ~500 uncommitted lines of changes. Inspection of the commit history shows:

- **Packet 03 commit** (`02f32be`): Committed 74 lines of fleet scan code to `git_dashboard.py`.
- **Packet 04 commit** (`72be631`): Committed 402 lines of HTML/CSS/React shell to `git_dashboard.py`.
- **Packet 05 commit** (`6bb73f3`): Committed only the validation audit and tracker updates — **did NOT commit the Fleet Overview UI code** (~500 lines of React components).

The packet 05 code exists on disk and passes all tests, but is not version-controlled. The tracker says packet 05 is "validated" based on code that isn't committed.

### Untracked orchestrator artifact

`orch_launch.sh` (orchestrator launcher script) exists in the project root but is not part of any packet's deliverables. It's a dev/CI artifact.

### Recommendation

Commit the outstanding work before proceeding to packet 06:
1. Stage and commit `git_dashboard.py` (packet 05 code)
2. Stage and commit `tests/test_fleet_api.py`, `tests/test_html_shell.py`, `tests/test_fleet_overview_ui.py`
3. Decide whether `orch_launch.sh` should be committed or gitignored

---

## Stale Comments (Cosmetic)

Two stale comments remain from the packet development process:

1. **Line 1659** — `get_ui()` docstring: `"Serve the SPA shell (placeholder until packet 04)."` Packet 04 is validated; this should just say "Serve the SPA shell."
2. **Line 749** — `--scan` CLI help text: `"(wired in packet 02/03)"` — this implementation note is visible in `--help` output. Should be removed.

These are cosmetic and do not affect architecture or correctness.

---

## Prior Audit Findings Review

The prior audit (`drift_audit_after_packet_02.md`) found no drift and noted four minor cosmetic observations (extra skip dirs, docker-compose.yaml variant, test file naming, preflight message phrasing). All remain unchanged and are still accepted.

---

## Findings Summary

| # | Finding | Category | Severity | Action |
|---|---------|----------|----------|--------|
| 1 | 3 test files untracked (32 tests) | VCS hygiene | Low | Operator: commit before next packet |
| 2 | Packet 05 code (~500 lines) uncommitted | VCS hygiene | Low | Operator: commit before next packet |
| 3 | Stale docstring on `get_ui()` | Cosmetic | Trivial | Fix when convenient |
| 4 | Stale help text on `--scan` flag | Cosmetic | Trivial | Fix when convenient |
| 5 | `orch_launch.sh` untracked artifact | Housekeeping | Trivial | Operator: commit or gitignore |
| 6 | `last_commit_hash` extra field in fleet response | Informational | None | Accepted (additive, forward-compatible) |

**No architectural drift.** All findings are VCS hygiene or cosmetic.

---

## Verdict

| Field | Value |
|-------|-------|
| Status | **pass** |
| Severity | low |
| Effort | small |
| Fixes applied | No |
| Validation rerun | none |
