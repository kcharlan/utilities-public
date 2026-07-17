# Packet 23A: Test Hardening -- Important Gaps

## Why This Packet Exists

A test suite audit found 9 important test gaps -- common error paths and edge cases that are untested. These gaps mean real bugs could slip through validation undetected. This repair packet addresses them before the project is considered complete.

## Scope

Add tests for the following 9 gaps. Each test should verify real behavior, not just "no crash".

1. **Non-git directory as registered repo** (test_fleet_api.py) -- Register a repo, then delete its `.git/` dir. Call `GET /api/fleet` and verify the repo shows an error state rather than crashing the scan.

2. **Detached HEAD state** (test_git_quick_scan.py) -- Create a git repo, detach HEAD (`git checkout --detach`). Run `quick_scan_repo` and verify it returns valid data with branch as empty/None rather than failing.

3. **Merge commits in parse_git_log** (test_git_full_history.py) -- Create git log output with merge commits (no shortstat line). Verify `parse_git_log` handles them correctly (0 insertions/deletions) rather than dropping or miscounting.

4. **Subprocess timeout behavior** (test_git_quick_scan.py or new test) -- Verify that `run_git` and dep health check functions have timeout handling or document that they don't. If no timeout exists, add one and test it.

5. **find_free_port exhaustion** (test_packet_00.py) -- Mock all ports in range as occupied. Verify `RuntimeError` is raised with a clear message.

6. **Filenames with spaces in git porcelain output** (test_git_quick_scan.py) -- Create porcelain status output with quoted filenames containing spaces. Verify `parse_porcelain_status` counts them correctly.

7. **Negative/zero days parameter** (test_analytics_heatmap.py, test_analytics_time_allocation.py, test_project_detail.py) -- Call analytics and history endpoints with `days=0` and `days=-1`. Verify graceful behavior (empty results, not crashes).

8. **Pagination clamping** (test_commits_branches_subtabs.py) -- Call `GET /api/repos/{id}/commits` with `page=0`, `page=-1`, `per_page=0`, `per_page=200`. Verify values are clamped to valid ranges (page>=1, 1<=per_page<=100).

9. **Module-scoped client fixture safety** (conftest.py) -- Either add a docstring warning that `client` fixture must not be used for DB-backed endpoints, or add a DB override to the module-scoped fixture.

## Non-Goals

- No new application code changes (unless timeout handling is missing and needs adding)
- No UI/template changes
- No changes to the orchestrator or playbooks

## Relevant Design Doc Sections

- Not applicable -- this is a test-only repair packet

## Allowed Files

- `tests/conftest.py` (if fixture changes needed)
- `tests/test_*.py` (add tests to existing files)
- `git_dashboard.py` (only if timeout handling is missing and must be added)

## Tests to Write First

This packet IS the tests. Each item above is a test to write.

## Acceptance Criteria

1. Each of the 9 gaps has at least one test covering the specific scenario
2. All new tests pass
3. Full test suite still passes (no regressions)
4. Tests verify actual behavior, not just "no crash" -- assertions must check response content, error messages, or state changes

## Validation Focus Areas

- Are the new tests actually adversarial, or are they just happy-path variants?
- Do assertions prove correctness, or just prove "it returned something"?
- Are mocks realistic (e.g., actual git porcelain output format, not simplified)?
