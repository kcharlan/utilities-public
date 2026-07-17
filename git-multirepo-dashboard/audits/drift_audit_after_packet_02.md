# Drift Audit — After Packet 02

**Auditor:** Claude Opus 4.6
**Date:** 2026-03-10
**Frontier:** Packet 02 (Repo Discovery & Registration API)
**Validated packets:** 00, 01, 02
**Result:** PASS — no meaningful drift detected

---

## Methodology

1. Read all validated packet docs (00, 01, 02) and their validation audits.
2. Read `docs/git_dashboard_final_spec.md` sections 1–4, 9, 11 (relevant to packets 00–02).
3. Read `git_dashboard.py` in full (911 lines).
4. Read all test files (`test_packet_00.py`, `test_git_quick_scan.py`, `test_repo_discovery.py`).
5. Ran the full test suite: **78/78 passed** (0.97s).
6. Compared `plans/packet_status.json` and `plans/packet_status.md` for consistency.
7. Verified each validated packet's acceptance criteria still hold against the current codebase.

---

## Tracker State Verification

| Check | Result |
|-------|--------|
| `packet_status.json` and `packet_status.md` agree on all statuses | PASS |
| `highest_validated_packet` = "02" matches both files | PASS |
| Dependency graph matches canonical ladder in playbook | PASS |
| All packets 03–23 are `planned` (no premature status advancement) | PASS |
| Packet doc paths in JSON match actual file paths in `plans/` | PASS |

---

## Schema vs Spec (Section 2)

All 6 tables in `_SCHEMA_SQL` (lines 272–339) match spec section 2 exactly:

| Table | Columns match | Constraints match | FKs match |
|-------|--------------|-------------------|-----------|
| repositories | YES | YES | N/A |
| daily_stats | YES | YES (PK, FK CASCADE) | YES |
| branches | YES | YES (PK, FK CASCADE) | YES |
| dependencies | YES | YES (PK, FK CASCADE) | YES |
| working_state | YES | YES (PK, FK CASCADE) | YES |
| scan_log | YES | YES (AUTOINCREMENT) | N/A |

WAL mode: enabled via `PRAGMA journal_mode=WAL` in schema script. ✓

---

## Bootstrap Constants vs Spec (Section 1)

| Constant | Spec Value | Code Value | Match |
|----------|-----------|------------|-------|
| VENV_DIR | `~/.git_dashboard_venv` | `Path.home() / ".git_dashboard_venv"` | YES |
| DATA_DIR | `~/.git_dashboard` | `Path.home() / ".git_dashboard"` | YES |
| DB_PATH | `DATA_DIR / "dashboard.db"` | `DATA_DIR / "dashboard.db"` | YES |
| DEFAULT_PORT | 8300 | 8300 | YES |
| DEPENDENCIES | `["fastapi", "uvicorn[standard]", "aiosqlite", "packaging"]` | Same | YES |

---

## API Contract Verification

### Implemented Endpoints

| Endpoint | Spec Shape | Code Shape | Match |
|----------|-----------|------------|-------|
| `GET /` | HTML 200 | HTMLResponse with HTML_TEMPLATE | YES |
| `GET /api/status` | `{tools, version}` | `{"tools": TOOLS, "version": VERSION}` | YES |
| `POST /api/repos` | `{registered: N, repos: [{id, name, path}]}` | Same | YES |
| `DELETE /api/repos/{id}` | 204 on success, 404 on not found | Same | YES |
| `GET /api/repos` | Not in spec section 4 | Returns `{repos: [...]}` | See note below |

**Note on `GET /api/repos`:** This endpoint is not explicitly listed in spec section 4, but is scoped by the packet 02 doc as "lists all registered repos (simple DB query, no scan)." It's needed for idempotency verification and the `--scan` flow. It does not conflict with `GET /api/fleet` (packet 03), which has a completely different response shape including working_state, KPIs, and sparklines. This is a valid additive endpoint, not drift.

---

## Git Operations Verification (Packet 01)

| Function | Spec Compliance | Notes |
|----------|----------------|-------|
| `run_git()` | YES | `asyncio.create_subprocess_exec`, `errors='replace'`, never `shell=True` |
| `is_valid_repo()` | YES | `git rev-parse --is-inside-work-tree` |
| `parse_porcelain_status()` | YES | All XY combinations correct (MM, AM, D, UU, ??) |
| `parse_last_commit()` | YES | NUL-delimited split, empty repo → all-None |
| `get_current_branch()` | YES | `rev-parse --abbrev-ref HEAD`, "HEAD" → None |
| `quick_scan_repo()` | YES | 3 commands (status, log, branch); 4th (is_valid_repo) is separate per validation note |
| `upsert_working_state()` | YES | INSERT OR REPLACE with all columns |

---

## Discovery & Registration Verification (Packet 02)

| Function | Spec Compliance | Notes |
|----------|----------------|-------|
| `generate_repo_id()` | YES | `sha256(path)[:16]` |
| `detect_runtime()` | YES | All priority 1–12 checks, mixed classification, docker exclusion |
| `discover_repos()` | YES | Walk + skip dirs + show-toplevel dedup |
| `get_default_branch()` | YES | `symbolic-ref --short HEAD` with fallback |
| `register_repo()` | YES | INSERT OR IGNORE for idempotency |
| `--scan` CLI flag | YES | Async startup scan with discover + register |

---

## Cross-Packet Boundary Check

| Check | Result |
|-------|--------|
| No API endpoints from future packets (03+) implemented | PASS |
| No UI code beyond placeholder | PASS |
| No dependency parsing or scanning logic | PASS |
| No SSE, scan orchestration, or parallel execution | PASS |
| No full history or branch scanning | PASS |

---

## Minor Observations (Not Drift)

These are cosmetic differences noted and accepted by validators. None affect correctness or forward compatibility:

1. **Extra skip directories:** `_DISCOVERY_SKIP_DIRS` includes `.pytest_cache`, `.mypy_cache`, `.tox`, `.eggs`, `dist`, `build` beyond the packet-specified minimum. Conservative addition — no false negatives.

2. **docker-compose.yaml variant:** `detect_runtime()` also checks `docker-compose.yaml` in addition to the spec's `.yml`. Correct extension for real-world repos.

3. **Test file naming:** Packet 00 uses `test_packet_00.py`, packets 01–02 use descriptive names (`test_git_quick_scan.py`, `test_repo_discovery.py`). Each follows its packet doc's specification.

4. **Preflight message detail:** The spec's example includes `-> Affects:` lines in the preflight summary. The implementation uses slightly shorter messages. The packet 00 doc doesn't mandate exact phrasing.

---

## Findings

**None.** No drift, no scope creep, no invalid tracker state, no missing cross-packet corrections. The implementation is aligned with the spec and packet boundaries.

---

## Verdict

| Field | Value |
|-------|-------|
| Status | **pass** |
| Severity | low |
| Effort | small |
| Fixes applied | No |
| Validation rerun | none |
