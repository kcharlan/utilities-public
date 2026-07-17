# Packet 15 Validation: Go / Rust / Ruby / PHP Dep Health

## Result: VALIDATED

## Test Results

- **Packet tests:** 46/46 passed (40 specified + 6 parametrize expansions)
- **Full suite:** 329/329 passed (0 regressions)

## Acceptance Criteria Verification

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | check_go_outdated skips when go unavailable | PASS | Test 1: TOOLS["go"]=None, deps unchanged |
| 2 | check_go_outdated parses NDJSON, sets version fields | PASS | Tests 2-3: _parse_go_ndjson via JSONDecoder.raw_decode |
| 3 | check_go_outdated uses classify_severity with v-prefix stripped | PASS | Code L1741: `classify_severity(_strip_v(current), _strip_v(update_ver))` |
| 4 | check_go_vulns skips when govulncheck unavailable | PASS | Test 7 |
| 5 | check_go_vulns parses JSON, sets vulnerable + advisory_id | PASS | Test 8: OSV ID extracted from Vulns[].OSV.id |
| 6 | check_rust_outdated skips when cargo-outdated unavailable | PASS | Test 12 |
| 7 | check_rust_outdated parses cargo outdated JSON | PASS | Tests 13-14: dependencies[].project/latest |
| 8 | check_rust_vulns skips when cargo-audit unavailable | PASS | Test 16 |
| 9 | check_rust_vulns parses cargo audit JSON, sets vulnerable + advisory_id | PASS | Test 17: RUSTSEC ID from vulnerabilities.list[].advisory.id |
| 10 | check_ruby_outdated skips when bundle unavailable | PASS | Test 21 |
| 11 | check_ruby_outdated parses bundle outdated --parseable | PASS | Tests 22-23: regex captures gem name, newest, installed |
| 12 | check_ruby_vulns skips when bundler-audit unavailable | PASS | Test 25 |
| 13 | check_ruby_vulns parses bundler-audit JSON | PASS | Test 26: results[].advisory.id extracted |
| 14 | check_php_outdated skips when composer unavailable | PASS | Test 30 |
| 15 | check_php_outdated parses composer outdated JSON | PASS | Tests 31-32: installed[].version/latest with latest-status filter |
| 16 | check_php_vulns skips when composer unavailable | PASS | Code L2188-2189: TOOLS.get("composer") check |
| 17 | check_php_vulns parses composer audit JSON | PASS | Test 34: advisories dict keyed by package name |
| 18 | Each orchestrator runs outdated then vulns | PASS | Tests 10, 19, 28, 36: side_effects order confirms sequence |
| 19 | Vuln overrides outdated/major for all ecosystems | PASS | Test 39 (parametrized x4): outdated→vulnerable override |
| 20 | All enriched dicts contain 9 required fields | PASS | Test 38 (parametrized x4): _REQUIRED_FIELDS set check |
| 21 | classify_severity from packet 13 reused | PASS | Test 40: inspect.getmembers confirms single classify_severity |
| 22 | All subprocess failures handled gracefully | PASS | Tests 5,9,15,18,24,27,33,35: Exception→deps unchanged |
| 23 | No DB writes | PASS | Grep for db/execute/INSERT/UPDATE in L1695-2264: zero matches |
| 24 | All 283 prior tests pass | PASS | 329 total = 283 prior + 46 packet 15, all green |

## Validation Focus Areas

- **Subprocess mocking**: All tests use `unittest.mock.patch("subprocess.run")`. No real tool invocations.
- **NDJSON parsing**: `_parse_go_ndjson` uses `json.JSONDecoder().raw_decode()` with position tracking. Test 10 verifies multi-object parsing (two objects separated by newline).
- **Version prefix stripping**: `_strip_v()` at L1670 strips leading `v`. Used at L1741 in check_go_outdated.
- **Parseable output format**: Ruby regex `r'^(\S+)\s+\(newest\s+([^,]+),\s+installed\s+([^,)]+)'` handles gem names with hyphens. Tests 22-23 confirm.
- **Tool availability cascading**: Each outdated/vuln function checks its own TOOLS key independently. Tests 16+12 verify cargo_audit and cargo_outdated checked separately.
- **Severity escalation**: Parametrized test 39 covers all 4 ecosystems: outdated→vulnerable.
- **TOOLS dict access**: All 12 functions read from TOOLS dict (verified in code review).

## Issues Found

None. Implementation is clean and matches packet spec exactly.

## Files Modified

- `git_dashboard.py` — 12 functions + 2 helpers (_strip_v, _parse_go_ndjson)
- `tests/test_remaining_dep_health.py` — 46 tests (40 base + 6 parametrize)
