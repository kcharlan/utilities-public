# Test Environment Parity Implementation Plan

**Goal:** Migrate eligible uv-managed projects from project test venvs to tests using their launcher's interpreter constraint and runtime dependency declarations.

**Proposed design:** Add a shared stdlib runner and a TOML registry. Test-only requirements supplement launcher metadata. Validate the runner before migrating projects; decide script locking after the rollout.

**Authorization:** This document is a proposal. Approval of the document does not authorize implementation, commits, pushes, PRs, merges, deployment, rule changes or lock changes. Obtain execution authorization before starting. A **Gated** action also requires approval of its concrete proposed change. Drafting an approval packet is permitted before approval to apply it.

**Evidence:** Use [the decision record](test_venv_retirement_decision.md#measurements) for historical measurements. They do not establish the proposed runner's correctness. Produce fresh rollout evidence under the contracts below; do not infer fleet savings from those pilots.

## Execution contracts

### Policy and scope

Follow [agents.md](../agents.md), especially Testing Scope, Validation Matrix, Public repository, Release Versions and Quality and Consistency. Python execution follows `~/.claude/shared/python-env.md` until an approved Rule Change takes effect. Keep evidence and synthetic runtime homes in private OS temporary space and remove this run's artifacts before handoff, unless the owner requests retention.

When the Git workflow is authorized, commit and integrate the approved plan to `main` before creating implementation worktrees. Run tasks serially in an isolated worktree outside the main checkout. Run Playwright suites serially. Before each integration, rebase on `main`, rerun affected validation, and perform the Shared uv header guard matrix entry. Use the authorized Git workflow; this plan grants no Git authorization. Follow [local deployment sync](local_deployment_sync.md) for deployment from `main`.

The default exception authority is [Reproducibility and exceptions](test_venv_retirement_decision.md#reproducibility-and-exceptions). Rollout Inventory proposes migrating the project's own suite, not its product's venv behavior. Retain other exception contracts. Transcription's uv migration is complete; preserve its documented self-test overlay and do not repeat that migration. Registered launchers without tracked tests do not gain a registry entry; retain the shell workflows in the `apple-health-extract` and `doc_linearizer` matrix entries. Warning remediation, changes to `tools/testkit.py:run_launcher` and normal-cache pruning are outside this plan.

### Runner contract

`tools/run_project_tests.py` is a uv-managed stdlib launcher registered under the guard's `"stdlib"` policy. It reads `tools/project_tests.toml` relative to its own repository root, independent of the caller's cwd.

CLI: `UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py <key> [--smoke-only] [--install-browsers] [--print-command] [-- extra...]`.

Resolve the interpreter with `uv python find --no-python-downloads --script <absolute-launcher>`. Use the same controlled discovery environment for resolution and direct shebang smoke: remove inherited venv activation and Python import-path overrides, remove activated venv bin directories from `PATH`, and perform resolution from private scratch without a parent venv. Retain approved interpreter-selection settings consistently. Reject a result that violates Python policy or cannot satisfy launcher metadata. Record the resolved executable and actual executed Python version; do not assume a cached venv path identifies its underlying interpreter. A missing approved interpreter requires owner action, not a download.

Run suite commands from the registered project directory using this argv template:

```text
uv run --no-project --isolated --no-python-downloads --python <resolved>
  --with-requirements <absolute-launcher>
  [--with-requirements <absolute-test-requirements>]
  python -m <registered-module-and-args> <extra...>
```

Use `subprocess.run`, preserve command order, stop at failure and return its exit status. Pass application/test settings through, including `STORAGE_MONITOR_WALKER`, browser and cache paths. Set `UV_PYTHON_DOWNLOADS=never`; do not let inherited `PYTHONPATH`, `PYTHONHOME`, `VIRTUAL_ENV` or venv `PATH` entries contaminate execution. The isolation tests below must prove the result rather than relying on flags alone.

Direct smoke accepts `--help` only after source inspection proves it exits before runtime-home writes, server startup or browser launch. Otherwise print the registered skip reason. A failed smoke stops suite execution. `--smoke-only` runs the smoke choice without a suite. `--install-browsers` explicitly runs `python -m playwright install chromium` using the suite environment template; it requires any applicable download approval and is never automatic. `--print-command` renders templates with an unresolved-interpreter placeholder and performs no subprocess calls. Reject incompatible control options with usage guidance.

### Registry and guard contract

Create an initially empty registry. Proposed entry shape:

```toml
[projects.jtree]
project = "jtree"
launcher = "jtree/jtree"
test_requirements = "jtree/requirements-dev.txt" # optional
test_commands = [["pytest", "-q"]]
smoke_args = ["--help"] # alternatively, smoke_skip_reason = "reason"
```

Proposed runner interface:

```python
@dataclass(frozen=True)
class ProjectTests:
    project: str
    launcher: str
    test_requirements: str | None
    test_commands: tuple[tuple[str, ...], ...]
    smoke_args: tuple[str, ...] | None
    smoke_skip_reason: str | None

def load_project_tests(path: Path) -> dict[str, ProjectTests]: ...
def resolve_interpreter(launcher: Path) -> str: ...
def build_test_command(
    entry: ProjectTests, interpreter: str, command: tuple[str, ...], extra: list[str]
) -> list[str]: ...
def main(argv: list[str] | None = None) -> int: ...
```

Paths must resolve inside the repository to existing files/directories of the required kind. Reject malformed tables, empty commands, unknown launchers and missing or conflicting smoke choices. A skip reason must be nonempty. Invalid input produces an actionable diagnostic, not a traceback.

Extend `tools/check_uv_headers.py` with `check_test_requirements(key: str, entry: dict) -> list[str]`, invoked by `main`. Reuse `extract_pep723`, `normalize_distribution` and `parse_requirements_file`; share registry validation rather than duplicating it. Add `"header"` handling to `check_dependency_manifest` before its sidecar existence check. This policy removes the sidecar requirement while retaining import validation.

Test requirements must not declare runtime distributions from their launcher. Recursively check requirements includes. Extend `parse_requirements_file` to recognize attached `-rfile` and `--requirement=file` as well as its existing include forms; fail closed on unsupported directives that could introduce dependencies, unreadable includes and invalid entries. Add parser regressions for normalized names, extras and markers. Retain legitimate test constraints without treating them as installed runtime packages.

### Rollout procedure

Apply this procedure to each candidate in Rollout Inventory. Its acceptance evidence belongs with that project's migration.

- [ ] **Baseline:** On an unchanged revision, run the complete documented suite in the documented environment, translating setup as agents.md requires. Record revision, commands, interpreter path/version, pass/skip counts, skip reasons and warnings. Use the project's installed dev extra where its README specifies that form; do not invent a missing requirements file. Prepare approved browser dependencies before measuring. A dependency/browser-related skip invalidates coverage even if the command exits successfully.
- [ ] **Candidate:** Resolve the launcher under Runner contract, then run the same categories through the candidate environment. Record this interpreter separately from Baseline. Review legitimate version-dependent differences explicitly; do not silently redefine Baseline to the new interpreter.
- [ ] **Dependencies:** Add a registry entry covering each documented pytest/unittest invocation. Derive test-only requirements by inspecting actual imports and the existing `DEPENDENCY_MANIFESTS` policy. Fix missing production dependencies in the header. Use `"header"` policy unless Rollout Inventory retains a runtime manifest. Remove stale install/runtime comments from the changed test requirements.
- [ ] **Guidance and matrix:** Replace venv setup and Python suite commands in every migrated project's README, local guidance and agents.md matrix entry with the runner. Preserve non-Python categories, sanitizer commands, CLI smokes and acceptance gates. Search project `.venv` references with `git grep -n '\.venv' -- <project>`; update test docstrings, usage comments, skip/exit guidance and contributing docs. Retain ignore/exclusion behavior, product contracts and historical records; classify retained hits in review evidence.
- [ ] **Acceptance:** Run the full affected-project matrix and the Shared uv header guard entry, including its consumer suites. Compare coverage to Baseline. Do not weaken assertions, suppress warnings or accept dependency-related skips. Update assertions tied to deliberately changed manifests and explain why.
- [ ] **Failure:** Diagnose and fix failures within scope. If blocked, restore that project's migration changes and record its unchanged contract and failure output. Keep the task unmerged while a required suite has a known failure, as agents.md requires; report the blocker rather than treating the remaining candidates as a completed rollout. A deferred project must remain outside the cap/release set until its full validation succeeds.

### Disk measurement

Before any rollout, record the normal `uv cache dir` with no task-specific `UV_CACHE_DIR` override and measure its `environments-v2` separately. Create a fresh temporary rollout cache and retain its path across Pilot Projects, Non-Browser Rollout and Browser Rollout. Use it for candidate runs throughout those tasks. Baselines use a separate cache so they do not inflate the candidate figure.

After Browser Rollout, report the candidate cache's allocated size, its coverage by project and interpreter, browser-cache location/size separately, and normal script-environment cache size measured at the saved path. Label excluded/deferred projects. Do not add overlapping cache subdirectories or present allocated size as reclaimed disk. Clean up only measurement artifacts created for this rollout. Package versions, browser revisions and exact measurement commands belong in the evidence record.

## Rollout Inventory

Launcher identities and retained manifest formats are authoritative in `tools/check_uv_headers.py:LAUNCHERS` and `DEPENDENCY_MANIFESTS`; resolve those paths rather than duplicating them here. Project tests and auxiliary commands come from agents.md's matrix and the project's README/testing docs.

| Task | Candidate projects | Dependency disposition |
|---|---|---|
| Pilot Projects | `jtree`, `tax2`, `data_format_converter` | Create a test-only file for Data Format Converter; retain its runtime `requirements` policy. |
| Non-Browser Rollout | `Claude_plugin_converter/to_gemini_cli`, `div_conv`, `docpipe`, `etf_montecarlo`, `hysa-excel`, `router-log-analyzer`, `vid-compiler`, conditional `benchmark-llm` | The converter needs no test requirements file. Decide Benchmark's test dependency authority in its migration. |
| Browser Rollout | `cognitive_switchyard`, `editdb`, `expense_dock`, `git-multirepo-dashboard`, `harscope`, `launchmaster`, `mls-tracker`, `model_sentinel`, `routerview`, `storage_monitor` | Retain Cognitive Switchyard's runtime `requirements` policy; remove the runtime include from its test file. |

## Task: Shared Test Runner

**Files:** Create `tools/run_project_tests.py`, `tools/project_tests.toml`, `tools/tests/test_run_project_tests.py`; modify `tools/check_uv_headers.py`, `tools/tests/test_check_uv_headers.py`, `agents.md`.

- [ ] Obtain execution authorization, including the synthetic-launcher requirement-source experiments needed before Rule Change. Include narrow permission for real-uv tests' temporary synthetic environments; absent approval, stop those tests rather than bypassing policy.
- [ ] Write failing tests for Runner contract and Registry and guard contract. Cover command construction, absent optional requirements, unknown key diagnostics, smoke failure/order/skip-reason handling, control options, extra arguments, environment handling, exit status, missing uv, invalid registry data and parser directives. Use stubs for subprocess orchestration.
- [ ] Add real-uv tests named `test_extensionless_header_supplies_packages`, `test_empty_header_is_accepted`, `test_existing_venv_cannot_supply_undeclared_package`, `test_resolution_ignores_activated_and_parent_venvs`, and `test_cached_environment_interpreter_is_checked`. Use synthetic launchers and private scratch/cache paths. The header-supplies-packages test must prove its declared package imports and an undeclared sentinel cannot import, without borrowing pytest's dependencies. The cached-interpreter test must record actual execution and detect a mismatch instead of assuming `--python` preserves a cache's old base.
- [ ] Run the new tests using the Shared uv header guard pytest command form; confirm intended failures. Implement the contracts and run that entire matrix entry. Expected: registry/launcher checks and affected consumer suites succeed.
- [ ] Add runner tests to that matrix entry alongside guard tests, so future guard validation exercises uv behavior as well as stubs. Register the runner and verify registry consistency without a hard-coded launcher-count expectation.

## Task: Rule Change (Gated application)

**Files:** Propose changes to `~/.claude/shared/core.md`, `~/.claude/shared/python-env.md`, `~/.claude/shared/README.md`, `agents.md`, `docs/test_venv_retirement_decision.md`; regression files are `~/.claude/shared/python-venv-guard.sh`, `~/.claude/shared/audit-python-usage.sh` and, if necessary, their shared `python-classifier.awk`. Update the Python Environment Policy and Slim Instructions PKM records identified by the decision record's Required policy work section.

- [ ] After Shared Test Runner validation, draft and present the exact policy diff. Permit Runner contract for registered projects and synthetic-launcher regression fixtures. Include the deployed-test form to be documented in local deployment sync. Keep existing Python safeguards by reference to python-env.md; leave nonmigrated projects under current rules. Define explicitly whether no-project-venv enforcement is instructional or mechanical.
- [ ] Present proposed classifier changes with the diff if regression cases require them. Application to persistent rule/permission configuration remains gated. Do not stop merely because the classifier needs a change; obtain approval for that concrete diff.
- [ ] After approval, apply the diff and propagate it as `~/.claude/shared/README.md` directs. Add a superseded recommendation note to the decision record while retaining its measurements. Run the hook and audit `--self-test`, covering allowed runner/synthetic forms and blocked unsafe forms; check instruction synchronization. Expected: cases pass and distributed copies agree.
- [ ] Resume rollout in new sessions that load approved rules, following the shared README's session-reload requirement. Do not assume a running agent has acquired changed policy.

## Task: Pilot Projects

**Files:** Modify `tools/project_tests.toml`, `tools/check_uv_headers.py`, `agents.md`, `docs/local_deployment_sync.md`; each candidate's README/test guidance and test requirements; `data_format_converter/requirements.txt`, new `data_format_converter/requirements-dev.txt`, and `tax2/tests/test_launcher.py`.

- [ ] Start Disk measurement, then apply Rollout procedure to this task's inventory.
- [ ] Update `tax2/tests/test_launcher.py:test_runtime_manifest_and_fleet_policy_drop_retired_dependencies` to assert the proposed test-only and `"header"` policies. Preserve unrelated assertions.
- [ ] Move Data Format Converter's pytest declaration to its new test file and remove that allowed extra from its runtime-manifest guard policy. Check consumers with `git grep` before changing the manifest; resolve consumer requirements explicitly. Run its documented Node/browser category as well as the Python suite.
- [ ] Add a registry-based matrix entry and replace migrated project entries under Guidance and matrix. Change the deployed-test example in `docs/local_deployment_sync.md` to use Runner contract's isolation and header-plus-test-file environment, with absolute deployed paths and the existing shared-helper import arrangement. Test that arrangement deliberately; do not allow a general inherited `PYTHONPATH` bypass in the runner.
- [ ] Complete Acceptance, including Tax2's matrix acceptance commands.

## Task: Non-Browser Rollout

**Files:** Modify `tools/project_tests.toml`, `tools/check_uv_headers.py`, `tools/tests/test_check_uv_headers.py`, `agents.md`; candidate READMEs, developer/test guidance and test requirements. Benchmark changes may include `benchmark-llm/pyproject.toml`, `benchmark-llm/uv.lock` and a new test requirements file.

- [ ] After Pilot Projects validation, apply Rollout procedure using the saved candidate cache. Derive smoke behavior from each launcher, including the converter's `migrate_skills.py`, rather than presuming `--help` exists.
- [ ] Update `tools/tests/test_check_uv_headers.py:test_vid_compiler_has_stdlib_runtime_and_pytest_only_dev_policy` for the proposed policy.
- [ ] For Benchmark, obtain Baseline through the README's dev-extra installation under existing policy. Test a candidate requirements file derived from that extra. If it succeeds, make that file the test dependency authority, remove the duplicate extra and update its consumers, README and matrix entry. **Gated:** present the exact manifest change and proposed `uv lock` action for approval before refreshing the lock; review the resulting manifest/lock diff and rerun Acceptance before integration. If approval is declined or editable installation is required, restore Benchmark's migration as a unit, including manifest, lock, registry, requirements and guidance; record it as an exception with its tested interpreter and original dependency authority.
- [ ] Complete Acceptance and Guidance and matrix for this task's migrated projects.

## Task: Browser Rollout

**Files:** Modify `tools/project_tests.toml`, `tools/check_uv_headers.py`, `tools/tests/test_check_uv_headers.py`, `agents.md`; candidate READMEs, developer/test guidance and test requirements.

- [ ] After Non-Browser Rollout validation, apply Rollout procedure with the saved candidate cache. Browser downloads, if necessary, require concrete approval before installation; reuse the approved browser installation across suites.
- [ ] Derive separate module commands from `editdb/README.md` and `git-multirepo-dashboard/README.md` test sections. Update `tools/tests/test_check_uv_headers.py:test_git_fleet_browser_test_dependencies_are_manifest_only` for the proposed policy. Apply this inventory's retained-manifest disposition.
- [ ] Run storage_monitor's sanitizer and TSan matrix categories via the runner with the documented walker override.
- [ ] Assess Model Sentinel's runtime coverage against `model_sentinel/build_standalone.py:STANDALONE_INTERPRETER` and the README's Standalone Install/Testing sections. Report the installed runtime's interpreter only through an authorized diagnostic. If live inspection is unavailable, mark installed-runtime parity unverified. Do not equate builder-interpreter tests with installed-runtime coverage.
- [ ] Finish Guidance and matrix for this task's migrated projects, including guard consumer-suite commands, launcher-pattern dev/test guidance and Python-as-an-agent examples. Preserve exclusion rules rather than deleting references solely because they mention venvs.
- [ ] Complete Acceptance and Disk measurement.

## Task: Python Cap and Deployment

**Files:** Modify `tools/check_uv_headers.py`, `tools/tests/test_check_uv_headers.py`, `tax2/tests/test_launcher.py`, `agents.md`, eligible registered launcher headers, and Benchmark's pyproject/lock if admitted. Discover version declarations and assertions as specified below; include them in the proposed release diff.

**Fleet cap proposal:** Add `<3.16` to eligible headers lacking an upper bound; preserve existing floors and upper bounds. Add `UNCAPPED_LAUNCHERS: tuple[str, ...]` for explicitly recorded deferrals. No release or cap edit reaches a deferred project until its validation is unblocked.

- [ ] Before edits, record each candidate's resolved interpreter and actual version under Runner contract. Build the cap/release inventory from current `LAUNCHERS` and the rollout's deferred-project record. For out-of-registry candidates, identify and run their complete documented validation; defer any candidate lacking sufficient evidence.
- [ ] Write failing tests for a missing upper bound, a valid bound and an explicit exemption. Implement the check in `check_launcher`; test the guard's own metadata separately. Apply Fleet cap proposal, including the guard's own header and agents.md's canonical example. Update the Tax2 header assertion. Document cap raising as a branch validation exercise using every affected suite, including projects outside the registry.
- [ ] Discover versioned candidates from source and deployment inventories. Search every affected project's version declarations, golden payloads and exact-version assertions. Include `tax2/taxkit/page.py`, `tax2/tests/test_page_build.py` and `tax2/tests/fixtures/payload_bundled_baseline.json` in Tax2's release review; change version fields without regenerating unrelated expectations. Include worktree-helper's README declaration where applicable. Present proposed increments and ask the owner about release status where unclear, including Benchmark and Model Sentinel. Keep source, tests and installed/displayed version checks synchronized under Release Versions.
- [ ] **Gated:** Present Benchmark's bound/version/lock diff and request its `uv lock` action before retaining manifest changes. If declined, restore its header, pyproject, version declarations and lock as a unit; record its exemption and defer its release/deployment. Do not leave a new manifest version paired with the old lock.
- [ ] Validate the complete affected-project matrix, table suites, out-of-table suites and Migrated CLI tools entry. Compare executed interpreters with the saved pre-edit record. Report intentional differences for approval; failures follow Rollout procedure's Failure clause. A deferred project's cap cannot be declared validated.
- [ ] **Gated:** After authorized integration to `main`, present affected deployed copies and concrete deployment actions. Following deployment, run `zsh tools/check_local_deployments.zsh`, version checks under Release Versions, and the updated Tax2 deployed-test example. Resolve deployed launchers under Runner contract and compare to checkout evidence. Report drift or unverified live checks explicitly; a gated delay is not a successful deployment.

## Task: Script Lock Decision (Gated experiments)

**Deliverable:** `docs/script_lock_decision.md`, a recommendation for owner choice. Do not roll locks out as part of this task.

- [ ] After Python Cap and Deployment's admitted scope completes, request approval for pilot `uv lock --script` experiments for Tax2 and Jtree in an isolated worktree.
- [ ] Run safe synthetic production invocations under Runner contract's smoke restrictions and compare installed distributions to their locks. Determine whether a header requirement source honors a sidecar lock; if not, request approval for a temporary `uv export --script` requirement source. Run the pilots' complete suites in the working form.
- [ ] Record whether production and tests use identical versions; derive the proposed lock inventory and refresh process; inspect deployment-copy, fleet-audit and security-audit treatment; test header/lock disagreement; compare selective locking of runtime-dependent tools with fleet locking. Preserve unresolved limitations as owner decisions, not parity claims.
- [ ] Update `docs/todo.md`'s post-uv decision link with the resulting record through the authorized Git workflow. Stop for the owner's lock-policy choice.
