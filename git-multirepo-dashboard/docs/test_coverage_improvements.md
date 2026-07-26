# Test Coverage Improvements

**Status:** Active, non-blocking backlog
**Last reconciled with tests:** 2026-07-26

These are confirmed gaps in the current suite. Completed items from the original 2026-03-10 audit were removed: requirements-file includes, slash-containing branch names, branch snapshot replacement, schema foreign keys, prerelease severity handling, and scan-global fixture isolation now have coverage.

- [ ] **Schema constraints and defaults**
  - File: `tests/test_packet_00.py`
  - Current tests verify exact column names and the presence of repository foreign keys, but do not assert declared types, `NOT NULL`, default values, primary-key composition, or `ON DELETE CASCADE`.

- [ ] **Requirements extras syntax**
  - File: `tests/test_dep_detection_parsing.py`
  - Requirements includes are covered, but a line such as `requests[security]>=2.0` is not directly tested to prove that the normalized package name is `requests`.

- [ ] **Malformed `package.json`**
  - File: `tests/test_dep_detection_parsing.py`
  - Add a truncated/invalid JSON case that asserts an empty result and no exception.

- [ ] **HTML structural validity**
  - File: `tests/test_html_shell.py`
  - Existing tests verify required strings and components, not balanced/valid document structure.

- [ ] **Sparkline date boundaries**
  - File: `tests/test_sparklines_progress.py`
  - Add explicit all-zero and future-dated-stat cases. Empty input and data older than the 91-day window are already covered.

- [ ] **Dependency-scan path removal race**
  - File: `tests/test_dep_scan_orchestration.py`
  - Cover a repository or manifest disappearing between discovery and the ecosystem health subprocess.

- [ ] **SSE client disconnect cleanup**
  - File: `tests/test_full_scan_sse.py`
  - Queue production and scan cleanup are covered, but there is no direct streaming-client test proving `_scan_queues` is released when a client disconnects before the final event.

- [ ] **Additional non-standard version formats**
  - Files: `tests/test_python_dep_health.py`, `tests/test_node_dep_health.py`, `tests/test_remaining_dep_health.py`
  - Prerelease handling is covered. Add explicit CalVer and invalid/non-PEP-440 strings to document the intended fail-open classification behavior.
