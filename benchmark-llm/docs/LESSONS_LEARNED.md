# Lessons learned

- Never create a venv from a venv interpreter. `sys._base_executable` inside a
  venv is the fully resolved versioned Homebrew Cellar path, so a venv built
  from it (or from the runtime venv's `python3`, which `bench run` puts first
  on `PATH`) is pinned to that Cellar version and breaks when Homebrew upgrades
  or removes it. Derive a stable interpreter without resolving symlinks and
  create venvs from that. Non-model benchmark steps now receive it as
  `BENCH_BASE_PYTHON`; scripts that create a workspace venv must use
  `"$BENCH_BASE_PYTHON" -m venv`, with `--clear` wherever a model step may have
  created the venv first. Model-visible steps do not receive the variable (eval
  neutrality), so a model that runs bare `python3 -m venv` (the runtime interpreter is
  first on `PATH` for model steps) creates a pinned venv that stays pinned until
  a later step rebuilds it. Regressions: `tests/test_base_python.py` (including
  `test_example_scripts_create_venvs_only_from_bench_base_python`) and
  `test_repo_task_venv_created_in_step_uses_stable_base_python` in
  `tests/test_repo_task.py`.
