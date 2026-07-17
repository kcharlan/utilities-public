# Packet 02 Validation: Repo Discovery & Registration API

**Validator:** Claude Opus 4.6
**Date:** 2026-03-10
**Result:** PASS — all 11 acceptance criteria verified

## Test Results

- **Packet 02 tests:** 17/17 pass
- **Full suite:** 78/78 pass (0 regressions)

## Acceptance Criteria Verification

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | `discover_repos()` correctly finds git repos | PASS | `test_discover_repos_finds_git_repos` — 2 repos + 1 plain dir → finds exactly 2 |
| 2 | Skips `.git`, `node_modules`, `.venv`, hidden dirs | PASS | `test_discover_repos_skips_hidden_and_exclude_dirs` — repos inside 5 skip dirs → 0 found |
| 3 | Deduplicates submodules via `rev-parse --show-toplevel` | PASS | `test_discover_repos_deduplicates_submodules` — outer+inner repos → only outer returned |
| 4 | `detect_runtime()` classifies repos correctly including "mixed" | PASS | 5 tests cover python (pyproject.toml, requirements.txt), node, mixed, unknown |
| 5 | `POST /api/repos` accepts path, discovers, returns list | PASS | `test_post_repos_registers_repos` — verifies `registered: 2`, response has `id`, `name`, `path` |
| 6 | `POST /api/repos` is idempotent | PASS | `test_post_repos_is_idempotent` — two POSTs then GET → 2 repos (not 4) |
| 7 | `DELETE /api/repos/{id}` removes repo + cascading data, returns 204 | PASS | `test_delete_repo_removes_it` (204 + gone from GET) + `test_delete_cascades_to_working_state` (working_state row removed) |
| 8 | `DELETE /api/repos/{nonexistent_id}` returns 404 | PASS | `test_delete_nonexistent_repo_returns_404` |
| 9 | `--scan` CLI flag registers repos on startup | PASS | Implemented at `git_dashboard.py:874-889`; arg parsing verified by `test_cli_scan`; exercises `discover_repos` + `register_repo` which are independently tested |
| 10 | Repo IDs are deterministic | PASS | `test_generate_repo_id_is_deterministic` (same path → same 16-char hex, matches independent sha256) + `test_generate_repo_id_different_paths_differ` |
| 11 | All tests pass | PASS | 78/78 |

## Validation Focus Areas

| Area | Finding |
|------|---------|
| **Submodule deduplication** | Correctly stops descending into found repos (`dirnames.clear()`). Belt-and-suspenders dedup via `rev-parse --show-toplevel` + `seen_toplevel` set. Test confirms inner repo is excluded. |
| **Runtime detection edge cases** | Case-insensitive matching via `{p.name.lower() for p in repo_path.iterdir()}`. Docker excluded from "mixed" classification. Shell/HTML fallback implemented. |
| **Path normalization** | `expanduser().resolve()` used in both POST handler and `--scan`. `discover_repos` resolves toplevel via `Path(stdout).resolve()` with OSError fallback. |
| **Idempotency** | `INSERT OR IGNORE` on the `path` UNIQUE constraint. Tested with back-to-back registrations. |
| **CASCADE delete** | Test inserts a `working_state` row, deletes the repo, confirms the row is gone. `PRAGMA foreign_keys = ON` set in both `get_db` and test fixture. |

## Allowed Files Check

- `git_dashboard.py` — modified (allowed)
- `tests/test_repo_discovery.py` — created (allowed)
- `plans/packet_status.json` — updated (tracker, expected)
- `plans/packet_status.md` — updated (tracker, expected)
- No other files modified by this packet.

## Notes

- `_DISCOVERY_SKIP_DIRS` includes additional dirs beyond the packet minimum (`.pytest_cache`, `.mypy_cache`, `.tox`, `.eggs`, `dist`, `build`). These are reasonable and don't affect correctness.
- `detect_runtime` also checks `docker-compose.yaml` (in addition to `.yml`). Minor but correct extension.
- `get_default_branch` not directly unit-tested, but exercised via POST `/api/repos` integration test. Simple function, adequate coverage.
- No scope creep: no quick scan during registration, no dependency parsing, no UI, no full scan.
