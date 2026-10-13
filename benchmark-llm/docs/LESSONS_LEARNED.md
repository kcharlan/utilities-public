# Lessons learned

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
