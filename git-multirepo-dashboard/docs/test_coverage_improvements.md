# Test Coverage Improvements -- Nice-to-Have

These are lower-priority test gaps identified during a test suite audit (2026-03-10).
They improve confidence but are not blocking production correctness.

---

- [ ] **Schema constraint validation**
  - File: `tests/test_packet_00.py`
  - Area: DB schema setup (`ensure_schema` in `git_dashboard.py`)
  - Current tests verify column existence but not column types, NOT NULL constraints, DEFAULT values, or FOREIGN KEY relationships.

- [ ] **`parse_requirements_txt` with `-r` includes and extras syntax**
  - File: `tests/test_dep_detection_parsing.py`
  - Area: `parse_requirements_txt()` in `git_dashboard.py`
  - Edge cases like `-r other.txt` (recursive includes) and `requests[security]>=2.0` (extras syntax) are untested.

- [ ] **`parse_package_json` with malformed JSON**
  - File: `tests/test_dep_detection_parsing.py`
  - Area: `parse_package_json()` in `git_dashboard.py`
  - No test for truncated or invalid JSON input.

- [ ] **`parse_branches` with slash-containing branch names**
  - File: `tests/test_branch_scan.py`
  - Area: `parse_branches()` in `git_dashboard.py`
  - `feature/login` style branch names are common but untested.

- [ ] **HTML template validity**
  - File: `tests/test_html_shell.py`
  - Area: HTML template rendering in `git_dashboard.py`
  - No test that the template produces valid HTML (unclosed tags, matching quotes). Current tests only check string presence.

- [ ] **`compute_sparklines` edge cases**
  - File: `tests/test_sparklines_progress.py`
  - Area: `compute_sparklines()` in `git_dashboard.py`
  - No test for all-zero weeks or future-dated stats.

- [ ] **`upsert_branches` stale branch removal**
  - File: `tests/test_branch_scan.py`
  - Area: `upsert_branches()` in `git_dashboard.py`
  - Code deletes all branches before reinserting, but no test verifies that branches removed from git are removed from the DB.

- [ ] **`run_dep_scan_for_repo` TOCTOU**
  - File: `tests/test_dep_scan_orchestration.py`
  - Area: `run_dep_scan_for_repo()` in `git_dashboard.py`
  - No test for the race where a repo path is deleted between dep file detection and health check subprocess execution.

- [ ] **SSE client disconnect during scan**
  - File: `tests/test_full_scan_sse.py`
  - Area: `_scan_queues` management in `git_dashboard.py`
  - No test for orphaned queues in `_scan_queues` when an SSE client disconnects mid-stream.

- [ ] **`classify_severity` with non-semver versions**
  - File: `tests/test_python_dep_health.py`, `tests/test_node_dep_health.py`, `tests/test_remaining_dep_health.py`
  - Area: `classify_severity()` in `git_dashboard.py`
  - Version strings like `1.0.0rc1`, `2024.1.1`, or CalVer formats are untested.

- [ ] **Cross-test state isolation for module-level globals**
  - File: `tests/test_full_scan_sse.py`, `tests/test_dep_scan_orchestration.py`
  - Area: `_active_scan_id`, `_scan_queues`, `_scan_task` globals in `git_dashboard.py`
  - These are module-level mutable state not explicitly reset in teardown, risking cross-test contamination.
