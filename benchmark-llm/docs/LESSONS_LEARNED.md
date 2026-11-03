# Lessons learned

- Optional metrics sidecars can contain valid JSON with invalid numeric values.
  Treat normalization errors as recorded metrics errors so the benchmark result
  survives. Regression: `tests/test_prompt_batch.py`.

- Validate command-backed judge verdicts as JSON objects with an actual boolean
  `passed` field. Coercion can turn a string such as `"false"` into a passing
  result; malformed outputs should identify the case and fail the run instead.
  Regression: `tests/test_prompt_batch.py`.

- Validate a repo-task score before marking an attempt successful or indexing it;
  retain the failed run and name the score file when the output is missing or
  invalid so the final summary can include it. Regression: `tests/test_repo_task.py`.

- Validator output must satisfy the runtime's score contract on both successful
  evaluation and import failure. Exercise the example through a complete synthetic
  bench run as well as checking each score path. Regression: `tests/test_cron_eval_example.py`.

- A subprocess group leader can exit on SIGTERM while a descendant ignores it.
  Reap the leader and also terminate surviving members of its owned group on
  timeout or interruption. Regression: `tests/test_process_cleanup.py`.

- Never create a venv from a venv interpreter. `sys._base_executable` inside a
  venv is the fully resolved versioned Homebrew Cellar path, so a venv built
  from it (or from the runtime venv's `python3`, which `bench run` puts first
  on `PATH`) is pinned to that Cellar version and breaks when Homebrew upgrades
  or removes it. Derive a stable interpreter without resolving symlinks and
  create venvs from that. Non-model benchmark steps now receive it as
  `BENCH_BASE_PYTHON`; scripts that create a workspace venv must use
  `"$BENCH_BASE_PYTHON" -m venv`, after `rm -rf -- .venv` wherever a model step may have
  created the venv first. Model-visible steps do not receive the variable (eval
  neutrality), so a model that runs bare `python3 -m venv` (the runtime interpreter is
  first on `PATH` for model steps) creates a pinned venv that stays pinned until
  a later step rebuilds it. Regressions: `tests/test_base_python.py` (including
  `test_example_scripts_create_venvs_only_from_bench_base_python`) and
  `test_repo_task_venv_created_in_step_uses_stable_base_python` in
  `tests/test_repo_task.py`, and `tests/test_example_venv_scripts.py`.

- `python -m venv --clear DIR` follows DIR when it is a symlink: it empties the
  target directory, and only then fails because DIR is a link. Before rebuilding
  a venv at a path another process (such as a model step) controlled, check the
  interpreter variable, run `rm -rf -- DIR` (which removes a link without
  following it), and create the venv without `--clear`. Regressions:
  `tests/test_example_venv_scripts.py`.

- A test proves only the branch its setup forces. When several checks could
  produce the expected result (an override rejected by `is_file` as well as
  `is_absolute`, a Cellar path mapped whether or not the Cellar binary exists),
  the test passes with the named check deleted. Give each test a setup that
  only the named branch can satisfy, and confirm it by deleting that branch
  and watching the test fail. The PR #33 review found 16 of 31 targeted
  mutants surviving a suite that passed every whole-part revert.

- Failed and retried repo-task attempts keep their worktrees, so a venv a model
  created there is never rebuilt by validation and stays pinned.

- Persist command provenance and failure context when prompt-batch or plugin
  execution fails; completed executor calls may already have incurred cost.
  Validate plugin scores before summarization or writing successful artifacts.

- Remove temporary files in a `finally` block, not after the normal return
  path. `run_command` unlinked its `mkstemp` stdout/stderr logs only after a
  completed command, so a Ctrl-C, a raised progress callback or a cleanup
  `PermissionError` left `benchmark-llm-std*.log` files in `$TMPDIR` on every
  interrupted step (and on every run of the interrupt tests). Regression:
  `test_interrupted_command_removes_its_temporary_output_logs` in
  `tests/test_process_cleanup.py`.
