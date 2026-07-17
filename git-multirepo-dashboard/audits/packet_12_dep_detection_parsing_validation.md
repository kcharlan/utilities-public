# Packet 12 Validation: Dependency Detection & Parsing

**Validator:** Opus 4.6
**Date:** 2026-03-10
**Result:** PASS — validated

## Test Results

- **Packet tests:** 42/42 pass (39 original + 3 added during validation)
- **Full suite:** 235/235 pass (193 prior + 39 original packet + 3 strengthened)
- **Regressions:** None

## Tests Added During Validation

1. `test_parse_requirements_txt_missing_include` — `-r` pointing to nonexistent file returns other deps without crashing (validation focus area).
2. `test_parse_pyproject_toml_no_tomllib` — monkeypatches `tomllib=None`, verifies `[]` return without crash (AC 18).
3. `test_parse_cargo_toml_no_tomllib` — same for Cargo.toml (AC 18).

## Tests Strengthened During Validation

- `test_parse_pyproject_toml_poetry` — replaced weak assertion (`assert "flask" in names or len(result) >= 1`) with concrete checks: verifies `flask` and `requests` present with correct version strings (`^2.3`, `^2.31`). Fixed misleading comment about `python` key exclusion.

## Acceptance Criteria Verification

| # | Criterion | Status |
|---|---|---|
| 1 | detect_dep_files identifies all 7 manifest types | PASS — tests 1–7 |
| 2 | Highest-priority file per runtime only | PASS — test 10 |
| 3 | Mixed-ecosystem returns all runtimes | PASS — test 8 |
| 4 | Empty dir → [] | PASS — test 9 |
| 5 | requirements.txt extracts names + pinned versions | PASS — test 11 |
| 6 | Skips comments, blanks, -e, flags | PASS — tests 12, 14 |
| 7 | -r includes one level, circular-safe | PASS — tests 15, 16; missing file added |
| 8 | pyproject.toml PEP 621 | PASS — test 17 |
| 9 | pyproject.toml Poetry | PASS — test 18 (strengthened) |
| 10 | package.json deps + devDeps | PASS — test 20 |
| 11 | go.mod require blocks + single-line | PASS — tests 23, 24, 25 |
| 12 | Cargo.toml string + table versions | PASS — tests 26, 27 |
| 13 | Gemfile gem names + version constraints | PASS — tests 29, 30 |
| 14 | composer.json require + require-dev, skip php/ext-* | PASS — test 31 |
| 15 | All parsers return {name, version, manager} | PASS — parametrized test_standard_shape |
| 16 | parse_deps_for_repo orchestrates detection + parsing | PASS — tests 33, 34 |
| 17 | parse_deps_for_repo returns [] for no manifests | PASS — test 35 |
| 18 | No TOML crash if tomllib unavailable | PASS — 2 monkeypatch tests added |
| 19 | All prior tests pass (no regressions) | PASS — 235/235 |

## Validation Focus Area Notes

- **requirements.txt edge cases:** `-r` with relative paths, circular refs, and missing files all handled correctly. Missing include returns `[]` via `OSError` catch in recursive call.
- **TOML availability:** Both `parse_pyproject_toml` and `parse_cargo_toml` check `tomllib is None` up front and return `[]` with warning. Now tested via monkeypatch.
- **Version extraction:** `==` pins extract exact version. Range constraints (`>=`, `~=`, `^`, `~>`) correctly leave `version=None` for requirements.txt or preserve the raw string for package.json/Gemfile/Poetry.
- **Mixed-ecosystem:** Tested. `detect_dep_files` uses runtime de-dup set; cross-runtime files all returned.
- **Same-ecosystem de-dup:** Tested. `pyproject.toml` + `requirements.txt` → only `pyproject.toml` returned.
- **No side effects:** Pure functions — no DB, no network, no file writes. Confirmed by code review.

## Observations (not defects)

- Poetry `python = "^3.11"` is included as a dep (not filtered). The packet spec doesn't require filtering it (unlike `php`/`ext-*` in composer.json). If this becomes an issue in later packets, a one-line filter can be added.
- The `_DEP_FILE_PRIORITY` list uses case-insensitive matching (`filename.lower() in dir_files`) which handles case differences on case-insensitive filesystems.

## Scope Creep Check

- Only `git_dashboard.py` and `tests/test_dep_detection_parsing.py` modified — matches allowed files.
- No API endpoints, no UI, no DB writes, no network calls added.
- No features from later packets (13–17) included.

## Files Modified

- `git_dashboard.py` — 9 functions added (lines 1005–1340): `_DEP_FILE_PRIORITY`, `detect_dep_files`, `parse_requirements_txt`, `parse_pyproject_toml`, `parse_package_json`, `parse_go_mod`, `parse_cargo_toml`, `parse_gemfile`, `parse_composer_json`, `parse_deps_for_repo`
- `tests/test_dep_detection_parsing.py` — 42 tests (35 specified + 4 parametrize expansions + 3 validation additions)
