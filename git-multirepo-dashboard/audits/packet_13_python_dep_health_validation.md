# Packet 13 Validation: Python Dep Health (Outdated + Vuln)

**Validator:** Claude Opus 4.6
**Date:** 2026-03-10
**Status:** VALIDATED

## Test Results

- **Packet tests:** 26/26 passed (25 original + 1 strengthening addition)
- **Full suite:** 261/261 passed (260 prior + 1 new)
- **Regressions:** None

## Acceptance Criteria Verification

| # | Criterion | Result |
|---|-----------|--------|
| 1 | classify_severity returns "ok" for same versions | PASS — test_classify_severity_same_version |
| 2 | classify_severity returns "outdated" for same-major different-minor/patch | PASS — test_classify_severity_minor_update, test_classify_severity_patch_update |
| 3 | classify_severity returns "major" for different major versions | PASS — test_classify_severity_major_update, test_classify_severity_prerelease_latest |
| 4 | check_python_outdated queries PyPI and sets latest_version | PASS — test_check_python_outdated_up_to_date, _outdated_minor, _major_update |
| 5 | check_python_outdated skips deps with version=None | PASS — test_check_python_outdated_no_pinned_version (asserts urlopen not called) |
| 6 | check_python_outdated handles network errors gracefully | PASS — test_check_python_outdated_network_error |
| 7 | check_python_outdated handles invalid PyPI JSON gracefully | PASS — test_check_python_outdated_invalid_json |
| 8 | check_python_vulns skips when pip-audit not installed | PASS — test_check_python_vulns_no_pip_audit |
| 9 | check_python_vulns parses pip-audit JSON, sets severity + advisory_id | PASS — test_check_python_vulns_finds_vulnerability |
| 10 | check_python_vulns handles subprocess failures gracefully | PASS — test_check_python_vulns_subprocess_fails |
| 11 | Vulnerability severity overrides outdated/major | PASS — test_check_python_vulns_overrides_outdated_severity + test_check_python_vulns_overrides_major_severity (added during validation) |
| 12 | check_python_deps orchestrates both checks | PASS — test_check_python_deps_full_pipeline |
| 13 | check_python_deps works when only outdated check available | PASS — test_check_python_deps_no_pip_audit |
| 14 | check_python_deps returns [] for empty input | PASS — test_check_python_deps_empty_list |
| 15 | All enriched dicts contain 9 required fields | PASS — test_check_python_deps_all_fields_present |
| 16 | All 260 prior tests still pass (no regressions) | PASS — 261/261 (235 prior + 25 packet 12 additions + 1 new) |

## Validation Focus Area Checks

- **PyPI API mocking:** All tests use `unittest.mock.patch("urllib.request.urlopen")`. No real network calls.
- **pip-audit mocking:** All tests mock `subprocess.run`. No real pip-audit execution.
- **Severity escalation:** Verified vuln > major > outdated > ok. Both "outdated→vulnerable" and "major→vulnerable" paths tested.
- **Version parsing:** Uses `packaging.version.parse()` — handles PEP 440 formats including pre-releases (rc1 tested).
- **No DB writes:** Verified — no INSERT/UPDATE/cursor operations in lines 1345–1509.
- **TOOLS dict:** Accessed via `TOOLS.get("pip_audit")` (line 1428), not hardcoded.
- **No scope creep:** Only `git_dashboard.py` and `tests/test_python_dep_health.py` modified. No API endpoints, no UI, no DB writes.

## Fixes Applied During Validation

1. **Strengthened weak non-pip assertion** (test_check_python_deps_non_pip_deps_unchanged): Changed `assert npm_result.get("severity") is None or "current_version" not in npm_result` to explicit per-field absence checks (`severity`, `current_version`, `latest_version`, `checked_at`).
2. **Added vuln-overrides-major test** (test_check_python_vulns_overrides_major_severity): Packet doc AC 11 says "vuln overrides outdated/major" but only outdated was tested. Added explicit test for major→vulnerable escalation.

## Files Modified

- `git_dashboard.py` — implementation (4 functions: classify_severity, check_python_outdated, check_python_vulns, check_python_deps)
- `tests/test_python_dep_health.py` — 26 tests (25 original + 1 validation addition)
