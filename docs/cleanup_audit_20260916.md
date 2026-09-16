# Test Infrastructure Cleanup Audit

Date: 2026-09-16

## Assumptions

- Each directory documented as a project in the repository README is an independently maintained boundary unless its README identifies it as a grouping or reference directory.
- The audit removes infrastructure only when it has no distinct present-day failure mode: placeholders, historical proof-of-removal assertions, exact/subset duplicates, disconnected copied implementations, unused helpers/fixtures/dependencies, or orphaned runners.
- Supported compatibility paths, privacy and security boundaries, error handling, concurrency, process cleanup, persistence, browser runtime behavior, and distinct API-versus-unit integration layers remain durable contracts.
- The repository is public. All reviewed fixtures and added text must remain conspicuously synthetic and contain no operational or personal data.
- Test-suite runtime is not itself a reason to delete coverage. Runtime savings are accepted only when the retained suite proves the same contract more directly.

## Rules and Standards Applied

### Correctness and Safety

- Retain negative tests that enforce a documented attack-surface, privacy, filesystem, authorization, process-lifecycle, or data-integrity boundary.
- Do not replace behavioral coverage with source-text inspection.
- Do not remove a compatibility test while the compatibility path remains supported.

### Robustness and Resilience

- Retain distinct timeout, retry, rollback, partial-failure, malformed-input, recovery, and cleanup cases.
- Browser tests must wait on observable UI conditions rather than sampling during an asynchronous re-render.

### Scalability and Capacity

- No test was removed solely for being expensive. This collection is predominantly local, single-user tooling, so there was no justified capacity-oriented test removal.

### Best Practices and Maintainability

- Prefer one owning-layer test plus integration coverage over repeated shape/smoke assertions with the same failure mode.
- Delete tests that execute copied production logic; they can stay green while production regresses.
- Remove dependencies and configuration allowances with no consumer.

### Readability

- Remove unused imports, helpers, fixtures, and historical finding-number names when durable behavior names are clearer.

### Performance and Efficiency

- Remove redundant browser page loads and duplicate converter round trips only where stronger retained scenarios cover the same path.

## Completed Findings

### [Maintainability] Finding #1: Placeholder and transition-only tests

- **Severity**: Low
- **Category**: Best Practices and Maintainability
- **Evidence**: Deleted `tax2/tests/test_placeholder.py`; legacy-removal assertions in Harscope, RouterView, Storage Monitor, Launchmaster, and Model Sentinel tests. The durable RouterView boundary remains at `routerview/tests/test_startup.py:84-90`.
- **Impact**: These tests either proved Python arithmetic or froze the absence of an old implementation without validating current behavior.
- **Recommended Fix**: Delete them while retaining positive/current behavior and documented boundary tests.
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**: Each affected full suite passes; RouterView continues to assert the documented absence of live backend routes.
- **Status**: Completed.

### [Correctness] Finding #2: Tests executed copied shell fragments instead of production

- **Severity**: Medium
- **Category**: Correctness and Safety
- **Evidence**: Deleted `cognitive_switchyard/tests/test_execute_sampler_heartbeat.py` and `test_execute_script_code_detection.py` embedded standalone copies with no reference to a built-in pack execute script. The maintained production-linked test map now points to `test_builtin_verify_scripts.py` at `cognitive_switchyard/docs/cognitive_switchyard_design.md:1458-1465`.
- **Impact**: Production heartbeat or test-detection logic could change or disappear while all copied-fragment tests stayed green.
- **Recommended Fix**: Remove the disconnected tests and stale design-doc reference. Future coverage must invoke production pack scripts.
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**: No references remain; the complete Cognitive Switchyard suite passes.
- **Status**: Completed.

### [Maintainability] Finding #3: Duplicate and subset coverage

- **Severity**: Low
- **Category**: Best Practices and Maintainability
- **Evidence**: Cognitive Switchyard packet bootstrap checks; Git Fleet endpoint/cascade/status/root/port smokes; Jtree insensitive clamp/copy tests; Launchmaster browser smokes; Data Format Converter round trips; one LLM Proxy parser case. The retained RouterView health behavior is explicit at `routerview/tests/test_startup.py:93-105`.
- **Impact**: Repeated assertions added maintenance and runtime without a distinct failure mode.
- **Recommended Fix**: Keep the strongest owning-layer or end-to-end scenario and remove exact or insensitive subsets.
- **Effort**: M
- **Risk**: Low
- **Acceptance Criteria**: Retained tests cover the same public contract and every affected suite passes.
- **Status**: Completed.

### [Maintainability] Finding #4: Orphaned runners and scaffolds

- **Severity**: Low
- **Category**: Best Practices and Maintainability
- **Evidence**: Git Fleet packet-loop scripts and their local ignore file; `media-dater/cli_harness.sh`; Gorilla's intentionally failing placeholder `npm test` package.
- **Impact**: The files had no current consumer or maintained documentation; one was unfinished boilerplate containing a failing literal command.
- **Recommended Fix**: Remove the orphaned files and their stale README reference.
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**: Repository-wide reference scans are empty and current project smoke checks pass.
- **Status**: Completed.

### [Efficiency] Finding #5: Unused test and runtime dependencies

- **Severity**: Low
- **Category**: Performance and Efficiency
- **Evidence**: Unused `pytest-cov` in Harscope, Jtree, and MLS Tracker; unused `requests` and `tiktoken` in Data Format Converter; duplicate direct `playwright` and `playwright-core` declarations in Multibody Simulator. Current policy and manifests are visible at `tools/check_uv_headers.py:81-94`, `data_format_converter/requirements.txt:1-6`, and `web_games/multibody_sim/package.json:16-19`.
- **Impact**: Fresh environments installed packages that no documented command, configuration, import, or test used.
- **Recommended Fix**: Remove the dependencies, synchronize manifests/lockfiles/docs, and tighten `tools/check_uv_headers.py` allowances.
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**: Clean or isolated installs pass complete suites; the fleet guard verifies all launchers.
- **Status**: Completed.

### [Readability] Finding #6: Dead helpers, fixtures, and imports

- **Severity**: Low
- **Category**: Readability
- **Evidence**: Unused helpers/imports across Cognitive Switchyard, Git Fleet, Jtree, Launchmaster, Data Format Converter, and repository deployment tests; three unreferenced packet-bootstrap fixtures.
- **Impact**: Dead support code obscured the active contract and implied coverage that did not exist.
- **Recommended Fix**: Remove definitions and fixtures after repository-wide reference scans.
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**: No removed-name references remain; collection and full suites pass.
- **Status**: Completed.

### [Robustness] Finding #7: Sticky-column browser test sampled during re-render

- **Severity**: Low
- **Category**: Robustness and Resilience
- **Evidence**: `model_sentinel/tests/test_browse_smoke.py:355-367` measured cell geometry immediately after changing catalog presets; one full-suite run returned no bounding box while ten isolated runs passed.
- **Impact**: The test could fail under suite load before replacement cells became visible.
- **Recommended Fix**: Wait for both target cells to become visible before measuring, without weakening the sticky-versus-scrolling geometry assertions.
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**: Ten focused repetitions and the complete Model Sentinel suite pass.
- **Status**: Completed.

## Project Coverage

Projects with cleanup changes: `cognitive_switchyard`, `data_format_converter`, `docker/llm_proxy`, `git-multirepo-dashboard`, `harscope`, `jtree`, `launchmaster`, `media-dater`, `mls-tracker`, `model_sentinel`, `routerview`, `storage_monitor`, `tax2`, `web_games/gorilla`, `web_games/multibody_sim`, and shared `tools`.

Projects whose current test infrastructure was retained after review: `Calculation tools`, `apple-health-extract`, `benchmark-llm`, `div_conv`, `docker/llm_collector`, `docpipe`, `editdb`, `etf_montecarlo`, `expense_dock`, `hysa-excel`, `md-autotax`, `mls-tracker` beyond its unused dependency, `moneydance backup rotation`, `router-log-analyzer`, `time_machine_snapshot_monitor`, and `usage-monthly-csv`.

Projects inspected and confirmed to have no removable test infrastructure: `Claude_plugin_converter`, `abacus usage`, `anduril_steps`, `coding`, `dloc`, `doc_linearizer`, the grouping-only `docker` root, `docker/actual-data`, `docker/docker-disk-compact`, `docker/excalidraw`, `docker/mermaid`, `docker/n8n-poc`, `docker/webserver`, `md-json`, `mem_snapshots`, `pdf-split`, `reversible-skew`, `toggle_wifi`, `transcription`, `trim_last`, `vid-compiler`, `video-scenes`, `web_games/rps_screen`, and `worktree-helper`. Runtime self-tests, deployment smoke checks, sprites, sample inputs, and operator verification commands were retained when they are part of the current product rather than test cruft.

## Implementation Plan

### Phase 1: Inventory and contract mapping

1. Read the repository and project READMEs plus linked behavior/design documents.
2. Inventory test files, helpers, fixtures, runners, manifests, configs, documented commands, and tracked generated artifacts.
3. Map borderline negative and compatibility tests to current behavior before deciding whether to remove them.

**Result**: Completed for every project listed in the root README.

### Phase 2: High-confidence cleanup

1. Remove placeholders, transition-only assertions, copied-fragment tests, exact/subset duplicates, and orphaned runners.
2. Remove unused helpers, fixtures, imports, and dependencies.
3. Update only the documentation, lockfiles, and dependency-policy entries directly made stale by those removals.

**Result**: Completed. No production application behavior or public API was changed.

### Phase 3: Adversarial review

1. Review every deletion against current docs, production behavior, retained coverage, and history.
2. Restore any removed test with a distinct durable contract.
3. Scan again for missed obsolete infrastructure and stale references.

**Result**: Completed. The review restored RouterView's documented live-route exclusion test, found the disconnected Cognitive Switchyard tests, and identified unused Harscope/Jtree coverage dependencies. The final adversarial verdict was approved with no remaining actionable findings.

### Phase 4: Verification and delivery

1. Run complete documented suites for every changed project boundary.
2. Run dependency/header guards, shell syntax/safe smoke checks, diff hygiene, reference scans, and sensitive-data review.
3. Stage the exact diff, re-inspect it, commit on the feature branch, push, and open a pull request.

**Stop condition**: Do not commit or open the pull request while any test is failing or an adversarial finding remains unresolved.

## Validation Summary

- Cognitive Switchyard: 476 passed.
- Data Format Converter: 62 passed in an isolated dependency environment.
- Git Fleet: 469 unit/API and 64 Playwright tests passed.
- Harscope: 162 passed in an isolated dependency environment.
- Jtree: 156 passed in an isolated dependency environment.
- Launchmaster: 88 passed, including Playwright.
- Model Sentinel: 1,352 passed; sticky-column check also passed ten focused repetitions.
- RouterView: 20 passed.
- Storage Monitor: 24 passed.
- Tax2: 24 passed.
- LLM Proxy: 74 passed; Ruff passed.
- MLS Tracker: 74 passed without `pytest-cov` installed.
- Multibody Simulator: JavaScript syntax check and 10 Playwright tests passed.
- Shared tooling: 8 header-checker tests, deployment shell suite, and the 17-launcher fleet guard passed.
- Other audited suites retained without cleanup also passed during the audit: Benchmark LLM 55; Div Conv 70; Docpipe 4; EditDB 3; ETF Monte Carlo 45; Expense Dock 6; HYSA Excel 20; Router Log Analyzer 451; Calculation Tools 32; Moneydance Backup Rotation 720; Time Machine Snapshot Monitor 80; plus the documented Apple Health, MD Autotax, and usage-monthly-csv shell harnesses.

The first Benchmark LLM attempt used a non-documented, non-activated invocation; generated shell steps could not find `python`, causing these seven failures:

- `test_repo_task_writes_run_artifacts_under_configured_output_dir`
- `test_repo_task_run_cleans_up_successful_worktree_and_records_branch_provenance`
- `test_repo_task_string_steps_still_honor_executor_command`
- `test_repo_task_retries_execute_in_fresh_workspace_and_preserves_attempts`
- `test_repo_task_does_not_retry_successful_non_model_step_on_provider_like_output`
- `test_repo_task_retries_execute_after_inactivity_timeout`
- `test_run_continues_past_failed_repo_task_model_and_returns_nonzero`

Activating the project environment as the README requires resolved all seven, and the complete 55-test suite passed. A Model Sentinel full run failed `test_catalog_snapshot_compare_changed_only_presets_and_sticky_column` because its first model cell temporarily had no bounding box during a React re-render. After the condition-based visibility wait described in Finding #7, ten focused repetitions and the complete suite passed.

A Tax2 collection probe was also first launched from the monorepo root instead of the project directory. Collection errored in `test_cli_tables.py` (`No module named 'cli'`) and in `test_config.py`, `test_engine_components.py`, `test_golden_baselines.py`, `test_qif_multistate.py`, and `test_rules_v2.py` (`No module named 'taxkit'`). Running from `tax2/`, as documented, collected and passed all 24 tests.

One moderate npm advisory and a Node `module.register()` deprecation warning remain in Multibody Simulator's existing dependency graph. They are not test failures and dependency upgrades were outside this removal-focused audit.
