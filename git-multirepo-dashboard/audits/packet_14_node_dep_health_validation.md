# Packet 14 Validation: Node Dep Health

**Validator:** Claude Opus 4.6
**Date:** 2026-03-10
**Result:** PASS (validated)

## Test Results

- **Packet tests:** 22/22 pass
- **Full suite:** 283/283 pass (no regressions)

## Repair During Validation

**Test 1 vacuous assertion (fixed):** `test_check_node_outdated_npm_not_available` had `assert ... or True` on line 81, which always evaluates to `True` — providing zero test value. Replaced with explicit assertions that `severity`, `advisory_id`, and `checked_at` keys are absent from the returned dict when npm is unavailable. Fix confirmed passing.

## Acceptance Criteria Verification

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | `check_node_outdated()` skips gracefully when npm unavailable | PASS | Code L1522-1524: returns `deps` unchanged. Test 1 confirms. |
| 2 | Correctly parses `npm outdated --json` and sets version fields | PASS | Code L1553-1557 maps current/wanted/latest. Tests 3, 4, 5 confirm. |
| 3 | Uses `classify_severity()` from packet 13 | PASS | Code L1561 calls `classify_severity(current, latest)`. Test 22 verifies reuse. |
| 4 | Handles `npm outdated` exit code 1 correctly | PASS | Code L1536-1540: only errors on empty stdout + non-zero rc. Tests 3, 4, 5, 8 all use rc=1. |
| 5 | Handles subprocess failures gracefully | PASS | Code L1542-1547 catches CalledProcessError and generic Exception. Test 6 confirms. |
| 6 | Handles invalid JSON gracefully | PASS | JSON parse error caught by generic Exception handler L1545. Test 7 confirms. |
| 7 | `check_node_vulns()` skips when npm unavailable | PASS | Code L1585-1587. Test 10 confirms. |
| 8 | Parses `npm audit --json` and sets severity + advisory_id | PASS | Code L1620-1623: sets `"vulnerable"` and `"npm:{name}"`. Test 12 confirms. |
| 9 | Handles npm audit failures gracefully | PASS | Code L1597-1606: empty stdout fallback + exception handlers. Tests 14, 15, 16 confirm. |
| 10 | Vulnerability overrides outdated/major severity | PASS | Code L1622 unconditionally sets `severity="vulnerable"`. Test 13 confirms (outdated→vulnerable). |
| 11 | `check_node_deps()` orchestrates both checks | PASS | Code L1647-1648 chains outdated→vulns. Test 17 confirms full pipeline. |
| 12 | Returns `[]` for empty input | PASS | Code L1638-1639. Test 19 confirms. |
| 13 | All enriched dicts contain 9 required fields | PASS | Code L1655-1661 stamps defaults. Test 20 asserts all 9 fields present. |
| 14 | `classify_severity()` reused, not reimplemented | PASS | Single definition at L1347. Node code calls it at L1561. Test 22 verifies `gd.classify_severity` is callable. |
| 15 | No regressions (all prior tests pass) | PASS | 283/283 pass. |

## Validation Focus Areas

- **Subprocess mocking:** All 22 tests mock `subprocess.run` via `unittest.mock.patch`. No real npm invocations.
- **Exit code handling:** Tests 3, 4, 5, 8 use `returncode=1` and verify output is still parsed. Implementation uses `subprocess.run` without `check=True`.
- **Severity escalation:** Test 13 verifies `outdated` → `vulnerable` override. Code unconditionally overrides at L1622.
- **classify_severity reuse:** Test 22 directly verifies `gd.classify_severity` is callable and produces correct results.
- **npm audit lockfile fallback:** Test 16 simulates empty stdout with rc=1 (no lockfile scenario). Deps returned unchanged.
- **No DB writes:** Confirmed — functions only return enriched dicts. No `aiosqlite` or SQL in any of the three functions.
- **TOOLS dict access:** All three functions use `TOOLS.get("npm")`, not hardcoded paths.
- **Non-npm deps unchanged:** Test 21 verifies pip and gomod deps pass through untouched.

## Files Modified

- `git_dashboard.py` — `check_node_outdated`, `check_node_vulns`, `check_node_deps` (L1515-1664)
- `tests/test_node_dep_health.py` — 22 tests (test 1 assertion strengthened during validation)

## Notes

- `CalledProcessError` catch in `check_node_outdated` (L1542) is technically dead code since `check=True` is not passed, but it's harmless defensive coding. The generic `Exception` handler at L1545 covers real failure modes (TimeoutExpired, OSError, etc.).
- `check_node_vulns` uses case-insensitive matching (`.lower()`) for package name comparison — extra defensive since npm packages are conventionally lowercase.
