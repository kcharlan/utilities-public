# Packet 00: Bootstrap & Schema — Validation Audit

**Validator:** Claude Opus 4.6
**Date:** 2026-03-10
**Result:** PASS — status updated to `validated`

---

## Acceptance Criteria Verification

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | `--help` prints usage and exits cleanly | PASS | Exit code 0, prints argparse help with all 4 flags |
| 2 | `--yes --no-browser` starts server on port 8300 | PASS | Code path verified: `find_free_port(args.port)` → uvicorn.run |
| 3 | `GET /` returns HTML with status 200 | PASS | 3 tests: status code, content-type, HTML body |
| 4 | `GET /api/status` returns JSON with `tools` and `version` | PASS | 3 tests: shape, tools value, version string |
| 5 | `~/.git_dashboard` directory created with `dashboard.db` | PASS | `init_schema()` calls `db_path.parent.mkdir(parents=True, exist_ok=True)` |
| 6 | `dashboard.db` contains all 6 tables with correct schemas | PASS | 8 tests: table count, idempotency, columns for all 6 tables, FK verification |
| 7 | WAL mode enabled | PASS | Dedicated test asserts `PRAGMA journal_mode` returns `wal` |
| 8 | Missing git → exit code 1 with clear error | PASS | Test mocks `shutil.which("git")` → None, asserts SystemExit(1) |
| 9 | Python < 3.9 → exit code 1 with clear error | PASS | Test mocks version_info to (3,8,0), asserts SystemExit(1) and "3.9" in stderr |
| 10 | All tests pass | PASS | 38/38 pass (0.15s) |

## Validation Focus Areas

### Cross-platform path handling
- `VENV_DIR` and `DATA_DIR` use `Path.home()` — correct.
- Venv python path: `Scripts/python.exe` on win32, `bin/python` otherwise — correct.
- Re-exec: `subprocess.run` + `sys.exit` on Windows, `os.execv` on Unix — correct.
- Signal handling: SIGTERM skipped on win32 — correct.

### Schema correctness
- All 6 tables match spec section 2 exactly: column names, types, defaults, constraints.
- Foreign keys verified: `daily_stats`, `branches`, `dependencies`, `working_state` all reference `repositories(id) ON DELETE CASCADE`.
- Composite primary keys correct: `daily_stats(repo_id, date)`, `branches(repo_id, name)`, `dependencies(repo_id, manager, name)`.
- `scan_log.id` uses `AUTOINCREMENT` as specified.

### Preflight prompt logic
- `run_preflight()` calls `check_python_version()` → `check_git()` → `build_tools_dict()` → `check_ecosystem_tools()` → `_print_preflight_summary()` → prompt (if missing tools and not `--yes`).
- `--yes` bypasses the `input()` prompt — correct.
- Hard-fail when no ecosystem tools: `check_ecosystem_tools()` checks all 6 ecosystem keys — correct.
- Empty answer or "y" continues; "n" exits with code 0 — correct.
- EOFError/KeyboardInterrupt caught on prompt — correct.

### Port scanning
- `find_free_port()` follows the CLAUDE.md pattern exactly.
- Fallback tested: first bind fails → returns next port.
- Warning logged when port differs from requested — correct.

## Repairs Made

**Test strengthening only** (no code changes to `git_dashboard.py`):
- Added column-level schema tests for `daily_stats`, `branches`, `dependencies`, `working_state` (4 tests).
- Added foreign key verification test across all 4 FK tables (1 test).
- Test count: 33 → 38.

## Scope Creep Check
- No files outside `Allowed Files` were modified (only `git_dashboard.py`, `README.md`, and `tests/`).
- No features from later packets were introduced.
- No git operations, repo registration, or real UI beyond the placeholder.

## Regressions
- No prior tests existed. Full suite (38 tests) passes clean.
