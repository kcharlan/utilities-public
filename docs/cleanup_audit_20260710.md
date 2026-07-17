# uv Bootstrap Remediation Audit — 2026-07-10

This audit validates and summarizes the findings implemented from `docs/uv_bootstrap_remediation_plan.md`. The remediation plan remains the detailed source of truth for task-level instructions and verification counts.

## Assumptions

- **Language:** Python 3.12+ and PEP 723 launcher conventions are authoritative for the 16 registered launchers.
- **API stability:** Existing CLI flags, HTTP routes, runtime-home locations, and default behavior are public contracts.
- **Deployment:** Tools run locally as single-user processes; selected launchers are copied to `~/Library/Scripts`.
- **Test environments:** Project test interpreters use repo-local venvs or isolated uv environments and never install dependencies during collection.
- **Scale:** This remediation changes bootstrap/test infrastructure, not application workload capacity or SLOs.
- **Failure handling:** Informational commands must not create runtime state; missing test dependencies must fail with an actionable setup command.

## Rules and Standards

- **Correctness/Safety:** Parse informational flags before runtime mutation and preserve subprocess exit codes.
- **Robustness & Resilience:** Declare every directly imported third-party package and keep genuine external-tool degradation paths.
- **Scalability & Capacity:** No material capacity findings; launcher discovery remains bounded to repository files and skips generated/vendor trees.
- **Best Practices & Maintainability:** Centralize extensionless launcher loading and keep dev dependency files complete.
- **Readability:** Remove dead imports, globals, bootstrap-era comments, and obsolete import staging.
- **Performance/Efficiency:** Read only candidate-file first lines during launcher discovery; AST-parse only the 16 registered launchers.

## Findings

### [Correctness/Safety] Finding #1: Informational commands mutated or misreported runtime state

- **Severity:** High
- **Category:** Correctness/Safety
- **Evidence:** `expense_dock/expense_dock:1984`, `storage_monitor/storage_monitor:3932`, and `cognitive_switchyard/cognitive_switchyard/cli.py:89`.
- **Impact:** `--help` could create state, and `switchyard paths` could accept an override while reporting the default home.
- **Recommended Fix:** Parse before mutation and compute `paths` output with pure resolved settings.
- **Effort:** S
- **Risk:** Low
- **Acceptance Criteria:** Help/paths exit zero, reflect overrides, and leave the probed runtime home absent.

### [Robustness] Finding #2: Test environments were incomplete or self-mutating

- **Severity:** High
- **Category:** Robustness & Resilience
- **Evidence:** `launchmaster/requirements-dev.txt` omitted runtime dependencies; `cognitive_switchyard/tests/conftest.py:55` previously pip-installed missing packages.
- **Impact:** Launchmaster produced 60 setup errors, while Cognitive Switchyard could mutate Homebrew/system interpreters during collection.
- **Recommended Fix:** Make tracked dev requirements complete and replace installation with an actionable dependency check.
- **Effort:** S
- **Risk:** Low
- **Acceptance Criteria:** Launchmaster passes all 60 tests; a dependency-poor interpreter exits with the exact venv setup command and performs no installation.
- **Robustness Considerations:** Missing dependencies now fail deterministically before collection instead of modifying the active interpreter.

### [Best Practices] Finding #3: Live behavior lost regression coverage

- **Severity:** High
- **Category:** Best Practices & Maintainability
- **Evidence:** Restored suites under `expense_dock/tests/`, `editdb/tests/`, `storage_monitor/tests/`, and `cognitive_switchyard/tests/test_launcher.py`.
- **Impact:** Help-state, launcher wiring, runtime config seeding, and core smoke behavior could regress without a red test.
- **Recommended Fix:** Restore still-live tests and add minimum viable suites for zero-test projects.
- **Effort:** M
- **Risk:** Low
- **Acceptance Criteria:** Each affected project collects real tests and all restored contracts pass.

### [Best Practices] Finding #4: Dependency declarations drifted from direct imports

- **Severity:** Medium
- **Category:** Best Practices & Maintainability
- **Evidence:** PEP 723 headers in `editdb/editdb`, `jtree/jtree`, `harscope/harscope`, and `git-multirepo-dashboard/git_dashboard.py`; metadata tests in `benchmark-llm/tests/test_launcher_metadata.py` and `cognitive_switchyard/tests/test_launcher_metadata.py`.
- **Impact:** A copied launcher or in-process test could fail because its declared environment did not supply a directly imported package.
- **Recommended Fix:** Align headers/requirements, remove unused dependencies, and test header-to-project metadata.
- **Effort:** M
- **Risk:** Low
- **Acceptance Criteria:** All launchers execute `--help`; metadata cross-checks and the fleet guard pass.

### [Maintainability] Finding #5: Launcher-loading and bootstrap-era cleanup were duplicated

- **Severity:** Medium
- **Category:** Best Practices & Maintainability
- **Evidence:** Shared loader at `tools/testkit.py:101`; converted tests across the launcher fleet, including mls-tracker and router-log-analyzer.
- **Impact:** Differing import behavior caused missing `__file__`, module collisions, and repeated maintenance.
- **Recommended Fix:** Use one `SourceFileLoader` helper that registers modules and preserves location metadata.
- **Effort:** M
- **Risk:** Low
- **Acceptance Criteria:** All converted suites pass and extensionless launchers expose a valid `__file__` without running `__main__`.

### [Robustness] Finding #6: docpipe guarded dependencies that PEP 723 guarantees

- **Severity:** Medium
- **Category:** Robustness & Resilience
- **Evidence:** Direct package imports in `docpipe/docpipe:29`; genuine external-tool checks retained at `docpipe/docpipe:48` and `docpipe/docpipe:221`.
- **Impact:** Unreachable package-degradation branches obscured real failures and complicated conversions.
- **Recommended Fix:** Import declared Python packages normally while retaining Pandoc/Poppler detection and fallback behavior.
- **Effort:** M
- **Risk:** Low
- **Acceptance Criteria:** Four docpipe tests and an XLSX conversion smoke-run pass; missing external binaries still produce warnings/fallbacks.
- **Robustness Considerations:** Python dependency failures now surface at launcher startup; optional executable failures still degrade per conversion path.

### [Maintainability] Finding #7: Fleet guard missed unregistered launchers

- **Severity:** Medium
- **Category:** Best Practices & Maintainability
- **Evidence:** Discovery at `tools/check_uv_headers.py:338` and all-scope import checks at `tools/check_uv_headers.py:294`.
- **Impact:** A new uv launcher could bypass canonical-header and dependency validation indefinitely.
- **Recommended Fix:** Discover canonical shebangs from tracked/non-ignored files, reject unregistered hits, inspect imports at every AST scope, and compare normalized dependency manifests in both directions.
- **Effort:** M
- **Risk:** Low
- **Acceptance Criteria:** The 16-launcher fleet passes; a temporary unregistered probe fails with a registration message.

### [Robustness] Finding #8: Restored suites depended on untracked local environments

- **Severity:** High
- **Category:** Robustness & Resilience
- **Evidence:** Tracked setup commands now appear in `docpipe/README.md:206`, `editdb/README.md:90`, `expense_dock/README.md:112`, `routerview/README.md:79`, and `storage_monitor/README.md:72`; each references a project `requirements-dev.txt`.
- **Impact:** A fresh clone could not reproduce passing tests, and docpipe's eager imports made its formerly dependency-light test command fail immediately.
- **Recommended Fix:** Track complete per-project test manifests, document fresh-venv commands, and validate every suite from an environment built only from those manifests.
- **Effort:** M
- **Risk:** Low
- **Acceptance Criteria:** Every project suite installs and passes from its tracked manifest; no test setup installs packages during collection.
- **Robustness Considerations:** Missing dependencies fail during explicit environment setup or with an actionable collection error, never through an untracked interpreter history.

### [Correctness/Safety] Finding #9: Restored tests used contradictory or vacuous premises

- **Severity:** Medium
- **Category:** Correctness/Safety
- **Evidence:** RouterView now imports real multipart support and uses the shared ASGI client in `routerview/tests/test_csv_import.py:8`; editdb's help test asserts an empty temporary working directory in `editdb/tests/test_smoke.py:17`.
- **Impact:** Multipart stubs could disagree with subprocess behavior, while an unused `EDITDB_HOME` assertion could pass without exercising any state boundary.
- **Recommended Fix:** Provision the real runtime dependency and assert observable filesystem behavior rather than an environment variable the launcher does not consume.
- **Effort:** S
- **Risk:** Low
- **Acceptance Criteria:** RouterView's 19 tests pass without multipart stubs; editdb's help probe leaves its temporary working directory empty.

### [Performance/Efficiency] Finding #10: docpipe carried a deliberately touched but unused pandas dependency

- **Severity:** Medium
- **Category:** Performance/Efficiency
- **Evidence:** `docpipe/docpipe:5` now starts its dependency list with `python-docx`; neither the launcher nor `docpipe/requirements-dev.txt:2` declares pandas.
- **Impact:** Every invocation paid pandas resolution/import cost even though no conversion path used it.
- **Recommended Fix:** Remove the header entry and the `import pandas; del pd` sentinel.
- **Effort:** S
- **Risk:** Low
- **Acceptance Criteria:** The guard, four unit tests, and a strict real-file conversion pass without pandas installed.

### [Best Practices] Finding #11: Fleet validation was costly and incomplete

- **Severity:** High
- **Category:** Best Practices & Maintainability
- **Evidence:** Manifest policies are centralized at `tools/check_uv_headers.py:74`, lazy imports are inspected at `tools/check_uv_headers.py:294`, and discovery uses Git's tracked/non-ignored file set at `tools/check_uv_headers.py:320`.
- **Impact:** Function-local imports escaped validation, ignored environment trees made discovery expensive and noisy, and one-way checks allowed stale packages such as `httpx2` to return unnoticed.
- **Recommended Fix:** Walk the full AST, use `git ls-files --cached --others --exclude-standard`, normalize requirement names once, and compare every tracked manifest in both directions.
- **Effort:** M
- **Risk:** Low
- **Acceptance Criteria:** Eight guard regression tests pass, including lazy-import, reverse-extra, and manifest-error cases; ignored venv probes remain invisible and unregistered launcher probes fail.

### [Maintainability] Finding #12: Two extensionless-launcher loader copies survived consolidation

- **Severity:** Medium
- **Category:** Best Practices & Maintainability
- **Evidence:** `mls-tracker/conftest.py:15` and `router-log-analyzer/test_router_log_analyze.py:18` both call `tools.testkit.load_launcher`.
- **Impact:** Hand-built import specs could diverge on `sys.modules`, `__file__`, and failure cleanup.
- **Recommended Fix:** Route the remaining call sites through the shared loader.
- **Effort:** S
- **Risk:** Low
- **Acceptance Criteria:** Repository search finds no executable `SourceFileLoader` copy outside `tools/testkit.py`; both suites pass.

### [Correctness/Safety] Finding #13: launchmaster tests shared state and could mutate the real runtime home

- **Severity:** High
- **Category:** Correctness/Safety
- **Evidence:** `launchmaster/launchmaster:30` honors `LAUNCHMASTER_HOME`; API and browser servers receive separate temporary homes in `launchmaster/tests/conftest.py:59`, `:90`, and `:97`.
- **Impact:** Test ordering could couple API and browser state, and configuration writes could reach `~/.launchmaster/config.json`.
- **Recommended Fix:** Add a runtime-home override, isolate both servers, and retain one shared lifecycle implementation without sharing server instances.
- **Effort:** M
- **Risk:** Low
- **Acceptance Criteria:** The full 62-test suite passes; help creates no override directory; the real user configuration is never read or written.
- **Robustness Considerations:** Startup failure captures output after terminating the child; teardown sends SIGTERM and escalates to SIGKILL only on timeout.

## Verification Record

- Fresh tracked environments: all 16 projects were rebuilt and installed only from their documented manifests or test extras.
- Project suites: editdb 3, jtree 168, harscope 163, mls-tracker 74, docpipe 4, storage_monitor 3, tax2 25, routerview 19, expense_dock 3, Git Fleet 482 unit + 65 E2E, launchmaster 62, router-log-analyzer 33, fid_div_conv 5, van_div_conv 3, benchmark-llm 55, and Cognitive Switchyard 491 passed.
- Cognitive Switchyard's WebSocket tests retain one visible upstream `StarletteDeprecationWarning` for FastAPI's current TestClient transport; launcher assertions no longer require empty stderr, so dependency diagnostics cannot create false regressions.
- Fleet checks: 16 direct launcher help invocations, ten deployed-copy byte comparisons/help invocations, four help-no-state probes, Cognitive Switchyard default/override path probes, eight guard tests, the 16-launcher guard, and pyflakes all passed.
- Operational checks: tax2 generated its 2026 combined tables and docpipe completed a strict conversion of a tracked HTML application.

## Implementation Plan

### Phase 1: Correctness and Coverage

1. Reorder help parsing and make Cognitive Switchyard path resolution pure.
2. Repair project dev dependencies and prohibit collection-time installation.
3. Restore launcher/app contracts and add smoke suites.
4. Run every affected project suite; stop and fix any failure.

### Phase 2: Dependency and Code Hygiene

1. Align PEP 723 headers, requirements files, and Python floors.
2. Centralize extensionless launcher loading.
3. Remove pyflakes findings and obsolete import staging.
4. Simplify docpipe package imports while retaining external-tool fallbacks.

### Phase 3: Tooling, Documentation, and Deployment

1. Add launcher discovery/direct-import checks to the fleet guard.
2. Repair documented fresh-venv test setup and mark historical bootstrap plans superseded.
3. Refresh deployed launcher copies and verify them directly.
4. Run all suites, all launcher help probes, pyflakes, the fleet guard, and repository cleanliness checks before committing.
