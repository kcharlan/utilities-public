# benchmark-llm Cleanup Audit 20260411

> Status: Findings 1-5 in this audit were addressed in the current working tree on 2026-04-11. The body is preserved as the pre-remediation audit record.

## Assumptions

- **Language**: Python 3.10+ with stdlib-first conventions and small optional dependencies.
- **Public API**: The user-facing contract is the `bench` CLI plus the documented benchmark package formats in `README.md`.
- **Deployment Model**: Single-user local CLI running on one machine with filesystem persistence.
- **Scale**: Low to moderate benchmark volume; dozens to hundreds of runs, not a multi-tenant service.
- **Failure Handling**: Benchmark authors should be able to rely on manifest fields and documented environment variables without reading framework internals.
- **Architecture Expectation**: The framework should be general at the package-contract level, with benchmark-specific logic isolated to example packages and plugin code.

## Rules / Standards

### Correctness / Safety

- Manifest fields described in docs should either affect runtime behavior or be removed from the public contract.
- Example packages may be specific; framework code must not rely on example-specific directory names or step ordering unless documented as hard requirements.

### Robustness & Resilience

- Hidden/visible separation should be enforced from manifest configuration, not from fixed folder-name conventions.
- Runtime behavior should not silently depend on ambient shell state when the CLI exposes structured inputs.

### Best Practices & Maintainability

- Public abstractions such as `executor` and `visibility.hide` should have one clear implementation path.
- Test coverage should validate the general contract, not only the happy path for one example layout.

## Findings

### [Correctness] Finding #1: `visibility.hide` Is Documented but Runtime Hardcodes `hidden/`

- **Severity**: High
- **Category**: Correctness & Safety
- **Evidence**:
  - `benchmark-llm/benchmark_llm/repo_task.py:90-104`
  - `benchmark-llm/README.md:168-173`
- **Impact**:
  - Repo-task benchmarks that specify hidden assets anywhere except `benchmark_dir/hidden` will not behave as documented.
  - Authors can believe evaluator-only assets are protected by the manifest even though the runtime ignores `visibility.hide`.
  - Hidden-asset enforcement is coupled to one directory name instead of the benchmark contract.
- **Recommended Fix**:
  - Replace `hidden_dir = benchmark_dir / "hidden"` with manifest-driven hidden asset resolution.
  - Resolve `visibility.hide` globs into a concrete evaluator-only staging directory and pass that path through `BENCH_HIDDEN_DIR`.
  - Fail fast when `visibility.hide` is configured but resolves to nothing.
- **Effort**: M
- **Risk**: Medium
- **Acceptance Criteria**:
  - A repo-task benchmark with hidden assets outside `hidden/` passes.
  - A repo-task benchmark with invalid `visibility.hide` fails with a clear error.
  - Add tests covering at least two different hidden layouts.
- **Robustness Considerations**:
  - Failure mode should be explicit configuration error, not silent fallback to `benchmark_dir/hidden`.

### [Correctness] Finding #2: `executor.command` Is Declared Publicly but Ignored by the Runtime

- **Severity**: High
- **Category**: Correctness & Safety
- **Evidence**:
  - `benchmark-llm/README.md:175-182`
  - `benchmark-llm/benchmark_llm/repo_task.py:95-106`
  - `benchmark-llm/tests/test_repo_task.py:60-66`
  - `benchmark-llm/tests/test_repo_task.py:165-166`
- **Impact**:
  - Changing `executor.command` in `bench.yaml` has no effect unless the author also edits `steps`.
  - The documented executor abstraction is misleading; authors are really configuring only a positional step list.
  - Command provenance can diverge from the manifest because the framework never treats `executor.command` as authoritative.
- **Recommended Fix**:
  - Pick one contract and enforce it:
    - either remove `executor` from the public manifest for v1, or
    - make the runtime derive the execute phase from `executor.command` instead of duplicating it in `steps`.
  - If keeping both, validate that the execute step matches `executor.command` and fail otherwise.
- **Effort**: M
- **Risk**: Medium
- **Acceptance Criteria**:
  - Editing `executor.command` alone changes the executed command, or the manifest schema rejects unused executor fields.
  - Tests cover both a valid and invalid executor configuration.

### [Maintainability] Finding #3: Repo-Task Phase Semantics Are Hardcoded to Step Position

- **Severity**: Medium
- **Category**: Best Practices & Maintainability
- **Evidence**:
  - `benchmark-llm/benchmark_llm/repo_task.py:47-54`
  - `benchmark-llm/benchmark_llm/repo_task.py:95-106`
  - `benchmark-llm/examples/policy-engine/scripts/judge.py:20-30`
  - `benchmark-llm/tests/test_repo_task.py:165-166`
- **Impact**:
  - The framework only meaningfully understands the first three steps as `prepare`, `execute`, and `judge`.
  - Any benchmark with a different sequence or multiple execute-like steps gets misleading provenance labels.
  - Example judges and future reporting logic can break because they assume one fixed phase order.
- **Recommended Fix**:
  - Allow steps to be declared as structured items with explicit names, for example:
    ```yaml
    steps:
      - name: prepare
        run: ./scripts/prepare.sh
      - name: execute-main
        run: ./scripts/invoke_model.sh
      - name: judge-hidden
        run: python ./scripts/judge.py
    ```
  - Preserve the provided step name verbatim in `commands.jsonl`.
- **Effort**: M
- **Risk**: Medium
- **Acceptance Criteria**:
  - `commands.jsonl` preserves custom step names.
  - Example judge logic does not depend on positional phase naming.

### [Robustness] Finding #4: Manifest Env Expansion Uses Ambient Process State Instead of the CLI Environment

- **Severity**: Medium
- **Category**: Robustness & Resilience
- **Evidence**:
  - `benchmark-llm/benchmark_llm/util.py:32-38`
  - `benchmark-llm/benchmark_llm/repo_task.py:72-74`
- **Impact**:
  - Programmatic callers can pass `environ={...}` into `main()`, but manifest env expansion ignores those values and reads only `os.environ`.
  - This creates a hidden dependency on the parent shell and makes tests or embedded usage less deterministic.
  - Benchmarks that depend on env-backed manifest values are harder to run in controlled contexts.
- **Recommended Fix**:
  - Change env expansion to accept the merged runtime environment as an argument.
  - Expand strings against the CLI's effective environment, not only the process-global environment.
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**:
  - `main(environ={"BENCH_POLICY_ENGINE_SOURCE_REPO": ...})` resolves `${BENCH_POLICY_ENGINE_SOURCE_REPO}` correctly without mutating global env.
  - Add a regression test for env-backed `source_repo`.
- **Robustness Considerations**:
  - Missing env vars should yield a clear error identifying the unresolved variable name.

### [Maintainability] Finding #5: Plugin Runs Are Indexed Under Folder Names Even When the Plugin Declares Its Own Benchmark ID

- **Severity**: Medium
- **Category**: Best Practices & Maintainability
- **Evidence**:
  - `benchmark-llm/benchmark_llm/plugin_runner.py:31-40`
  - `benchmark-llm/benchmark_llm/plugin_runner.py:55-58`
  - `benchmark-llm/tests/test_plugin_mode.py:21-22`
- **Impact**:
  - The run directory slug is computed before `plugin.benchmark_id` overrides the benchmark identity.
  - Two copies of the same plugin benchmark can be indexed under different folder-derived run IDs while the manifest reports the same benchmark ID.
  - Comparison and aggregation logic will drift if folder naming changes.
- **Recommended Fix**:
  - Load the plugin class before constructing the run ID.
  - Use the resolved benchmark ID consistently for run naming, manifest writing, and SQLite indexing.
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**:
  - A plugin with `benchmark_id = "plugin-mini"` produces a run ID and SQLite row keyed to `plugin-mini`, not the directory name.
  - Add an assertion in the plugin test for the run directory name or recorded run ID.

## Implementation Plan

### Phase 1: Correctness Contract Fixes

**Step 1: Make hidden asset resolution manifest-driven**
- **Files to modify**:
  - `benchmark-llm/benchmark_llm/repo_task.py`
  - `benchmark-llm/tests/test_repo_task.py`
  - `benchmark-llm/README.md`
- **Changes**:
  - Parse and resolve `visibility.hide` globs.
  - Materialize a hidden staging directory or explicit file map.
  - Remove the fixed `benchmark_dir / "hidden"` assumption.
- **Commands**:
  ```bash
  source .venv/bin/activate
  pytest -q tests/test_repo_task.py
  ```
- **Expected result**: Repo-task tests cover more than one hidden layout.

**Step 2: Reconcile `executor.command` with `steps`**
- **Files to modify**:
  - `benchmark-llm/benchmark_llm/repo_task.py`
  - `benchmark-llm/tests/test_repo_task.py`
  - `benchmark-llm/README.md`
- **Changes**:
  - Either remove `executor.command` from the v1 contract or make it the source of truth for the execute phase.
- **Commands**:
  ```bash
  source .venv/bin/activate
  pytest -q tests/test_repo_task.py
  ```
- **Expected result**: The manifest has one unambiguous way to define model execution.

### Phase 2: Generalize Runtime Semantics

**Step 3: Replace positional phase naming with explicit step names**
- **Files to modify**:
  - `benchmark-llm/benchmark_llm/repo_task.py`
  - `benchmark-llm/examples/policy-engine/scripts/judge.py`
  - `benchmark-llm/tests/test_repo_task.py`
  - `benchmark-llm/README.md`
- **Changes**:
  - Support step objects with `name` and `run`.
  - Preserve exact step names in `commands.jsonl`.
- **Commands**:
  ```bash
  source .venv/bin/activate
  pytest -q tests/test_repo_task.py
  ```
- **Expected result**: Non-canonical workflows no longer depend on first/second/third step positions.

**Step 4: Use the effective CLI environment for manifest expansion**
- **Files to modify**:
  - `benchmark-llm/benchmark_llm/util.py`
  - `benchmark-llm/benchmark_llm/repo_task.py`
  - `benchmark-llm/tests/test_repo_task.py`
- **Changes**:
  - Add env-aware expansion helpers.
  - Cover env-backed `source_repo` through `main(environ=...)`.
- **Commands**:
  ```bash
  source .venv/bin/activate
  pytest -q tests/test_repo_task.py
  ```
- **Expected result**: Manifest env expansion is deterministic and testable.

### Phase 3: Identity Consistency

**Step 5: Make plugin run IDs use the resolved benchmark ID**
- **Files to modify**:
  - `benchmark-llm/benchmark_llm/plugin_runner.py`
  - `benchmark-llm/tests/test_plugin_mode.py`
- **Changes**:
  - Load plugin metadata before naming the run.
  - Use one benchmark identifier everywhere.
- **Commands**:
  ```bash
  source .venv/bin/activate
  pytest -q tests/test_plugin_mode.py
  ```
- **Expected result**: Plugin run directories, manifest IDs, and SQLite rows all agree.
