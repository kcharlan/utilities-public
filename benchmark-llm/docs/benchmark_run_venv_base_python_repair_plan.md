# Benchmark-run venv base-interpreter repair plan

Status: decisions locked 2026-10-12 (see "Decisions"); implemented 2026-10-12 and merged as kcharlan/utilities-public#33 (squash commit `dfdca32`); a follow-up review fix is on branch `fix/benchmark-llm-base-python-review`.

Terminology: outside the "Branch and checkout" section, "worktree" always
means a git worktree that
benchmark-llm itself creates for each benchmark run, under the runtime
home's `worktrees/` directory (`repo_task.py:580`; default
`~/.benchmark_llm/worktrees/`, overridable with `BENCH_RUNTIME_HOME`). It
never means the checkout used to implement
this plan; see "Branch and checkout".

## Branch and checkout

Implement on a local feature branch in the existing `utilities-public`
checkout (the repository root that contains `benchmark-llm/`). Do not create or use a git
worktree for this work. That is the repository's standing rule (PKM knowledge
#152, project utilities-public), and it overrides any skill or agent default
that recommends worktree isolation, such as `superpowers:using-git-worktrees`.

- Start from an up-to-date `main`. Create the branch and switch to it
  (`git switch -c <branch>`). Use a name such as
  `fix/benchmark-llm-base-python`, unless the owner names one. `codex/` is
  the default prefix only for Codex work.
- The repository has other local branches, such as `codex/tax2-built-page`.
  Leave them untouched.
- This plan file is untracked on `main` today. An untracked file follows
  `git switch -c`, so it carries onto the branch. Include it in the commit
  described under "Validation and exit criteria".
- Do not commit, push, open a PR or merge without the owner's instruction.

## Problem

When a benchmark step runs `python3 -m venv .venv`, the new venv is pinned to a
versioned Homebrew Cellar path. That venv breaks the next time Homebrew
replaces that Cellar directory, through a version upgrade or a bottle revision.

The fix must make the venvs that benchmark steps create point at a stable
interpreter path, such as `/opt/homebrew/opt/python@3.X/bin/python3.X`. It must
also keep the PATH behavior that `tests/test_repo_task.py` asserts.

## Root cause (verified 2026-10-12)

1. `benchmark_llm/cli.py:197-204` (`main`) sets
   `runtime_bin = str(Path(sys.executable).parent)` and puts it first on the
   `PATH` passed to every step. Repo-task steps (ordinary and model-visible),
   the prompt-batch judge and plugin runs all inherit it, through
   `merge_environ` / `build_model_command_env` in `benchmark_llm/util.py` and
   `run_command` in `benchmark_llm/execution.py`. A step's bare `python3`
   therefore resolves to the benchmark-llm runtime venv's interpreter.
2. The stdlib `venv` module (3.14:
   `.../lib/python3.14/venv/__init__.py`, `ensure_directories`, lines 160-173,
   and the `pyvenv.cfg` writer, line 231) uses `sys._base_executable`. It
   writes `home = dirname(sys._base_executable)` and links the new venv's
   `bin/python3.X` to that executable.
3. When the interpreter runs from a venv, `sys._base_executable` is the
   resolved Cellar path. Probe from `benchmark-llm/.venv/bin/python`:
   - `sys.executable` = `.../benchmark-llm/.venv/bin/python`
   - `sys._base_executable` =
     `/opt/homebrew/Cellar/python@3.14/3.14.8_2/Frameworks/Python.framework/Versions/3.14/bin/python3.14`
   - that venv's own `pyvenv.cfg` `home` = `/opt/homebrew/opt/python@3.14/bin`
     (stable).
   Any venv that a step creates with `python3 -m venv` therefore gets the
   versioned Cellar `home` and symlink.
4. The uv launcher (`./bench`) runs in a uv script environment, which is also a
   venv, so the defect applies there too. A uv environment on this machine
   (the `tax2` script environment under uv's `environments-v2` cache,
   uv 0.12.23) has
   `home = /opt/homebrew/opt/python@3.14/bin` and `bin/python ->
   /opt/homebrew/opt/python@3.14/bin/python3.14`, the same shape as
   `benchmark-llm/.venv`. No `bench` uv environment exists in the cache today,
   so this was not probed on the bench environment itself.
5. The only venv-creating commands in the project are
   `examples/policy-engine/scripts/run_checks.sh:6` (`python3 -m venv .venv`)
   and `examples/cron-eval/scripts/prepare.sh:9` (the same command, guarded by
   `if [ ! -d .venv ]`).

### Corrections to the original report

- The original report suggested, as a hypothesis to verify, that the
  2026-04-12 venvs came from the `runtime_bin` PATH prefix. They could not
  have: `git log -S` shows the prefix was introduced on 2026-09-17 by the
  squash commit `fdb165f` ("Modernize dependency surfaces across utilities
  (#23)"), whose body bullet "Preserve benchmark runtime Python for hooks"
  describes it. The
  public history starts on 2026-07-17 (`cb0dec7`, followed the same day by
  `368d4ec`, which published the sanitized source), and the private checkout
  named in those venvs' `command =` lines (an earlier private copy of
  `benchmark-llm`) no longer exists. The April mechanism therefore cannot be traced in code.
  Their `command =` line shows `python3 -m venv` running on the benchmark-llm
  venv interpreter, which is the same defect. The current code reproduces it
  on every run that reaches one of those two scripts.
- Bottle revisions also cause the breakage, not only version upgrades. Today
  `/opt/homebrew/Cellar/python@3.14/` contains only `3.14.8_2`. The 7
  hand-rebuilt worktree venvs have a stable `home`
  (`/opt/homebrew/opt/python@3.14/bin`) and still run. Their informational
  `executable =` line names `.../Cellar/python@3.14/3.14.8/...`, a directory
  that has since been removed. That line has no effect on whether the venv
  runs. Do not touch these venvs.

## Constraints

- Keep the `runtime_bin` PATH prefix. According to the `fdb165f` commit body,
  it exists "so documented repo-task Python commands work without shell
  activation". Bare `python`/`python3` in benchmark steps (for example a
  manifest step `python ./scripts/judge.py`, or
  `python "$SCRIPT_DIR/harness_metrics.py"` in `invoke_model.sh`) therefore
  run on the runtime interpreter even when `PATH` is hostile. These tests
  lock that in and must pass unchanged:
  `test_repo_task_seeds_absent_path_from_platform_default`,
  `test_repo_task_preserves_explicitly_empty_path`, and
  `test_repo_task_writes_run_artifacts_under_configured_output_dir`, which
  checks interpreter identity under a hostile `PATH`.
- Do not expose new `BENCH_*` variables to model-visible steps.
  `build_model_command_env` deliberately strips framework variables, and
  `test_policy_engine_model_visible_assets_do_not_signal_evaluation_context`
  guards against eval signaling.
- Never resolve symlinks (`os.path.realpath`, `Path.resolve()`) on the derived
  interpreter path. Resolving them is exactly what produces the Cellar pin.
- Do not delete, recreate or edit any venv under `~/.benchmark_llm`.
- Agent Python rules apply to the executor. Run tests only with
  `benchmark-llm/.venv/bin/python`. Never create a venv from another venv's
  interpreter, not even in a scratch directory to "reproduce" the bug.

## Approaches considered

| | Approach | Covers | Cost / risk |
|---|---|---|---|
| **A (chosen)** | The runtime derives a stable base interpreter and exports it to non-model steps as `BENCH_BASE_PYTHON`. Benchmark scripts create venvs with `"$BENCH_BASE_PYTHON" -m venv`, adding `--clear` wherever a model step may already have created that venv. | Every venv that benchmark-owned steps following the contract create or rebuild, including both bundled examples (Task 3). | Small and explicit; the PATH contract is unchanged. These are still pinned: a script that still runs bare `python3 -m venv`; a venv a model creates and nothing rebuilds; and a model-created venv that a script reuses without `--clear`. |
| B | Replace the `runtime_bin` PATH entry with a generated shim directory whose `python`/`python3` wrappers send `-m venv` to the base interpreter and everything else to the runtime interpreter. | Unmodified scripts and model-created venvs, but only for the exact `python3 -m venv` form. | Argument matching misses `-mvenv`, `-I -m venv`, `virtualenv` and similar forms. It adds generated files to the runtime home, changes the asserted PATH shape (so the tests above must be rewritten), and its red-phase test would create a venv from a venv. |
| C | Put the base interpreter's directory first on `PATH` instead of the runtime venv's `bin`. | Everything. | Breaks the hostile-PATH interpreter-identity tests and PyYAML availability for benchmark scripts. The Homebrew `opt/.../bin` directory has no `python` or `python3`, only `python3.14`. Rejected. |
| D | After each step, rewrite any workspace `pyvenv.cfg` whose `home` is under `/Cellar/`. | Everything, after the fact. | Rewrites artifacts, leaves the `bin/python3.X` symlinks pointing into Cellar, and adds hidden repair logic. Rejected. |

## Decisions (locked by the owner, 2026-10-12)

These are settled. The executor must not reopen them.

1. **Approach A.** B, C and D are not implemented.
2. **Model-visible steps do not receive `BENCH_BASE_PYTHON`.** This protects
   eval neutrality. A venv the model creates therefore stays pinned until a
   later step rebuilds it; in both bundled examples, validation rebuilds it
   (Task 3).
3. **No stable base found: warn and fall back.** The resolver returns the
   fallback interpreter, and the run continues with a one-line
   `[bench] warning:` on `stderr` (Task 1). The run is never refused for this
   reason. An invalid explicit override is a different case and still exits
   `1` (Task 2).
4. **Both examples' validate steps rebuild `.venv` with `--clear`.** This
   discards any `.venv` the model created (Task 3).

The plan below implements these decisions.

## Implementation tasks

Entry gate: `cd benchmark-llm && .venv/bin/python -m pytest -q` passes.
Baseline on 2026-10-12: 74 passed. Read `benchmark-llm/README.md` and the
`policy-engine` and `cron-eval` example READMEs first. There is no
benchmark-llm lessons-learned file yet (see Task 5).

### Task 1: resolver (`benchmark_llm/util.py`)

Add a pure, injectable resolver. Nothing like it exists in the package today
(`grep -rn "pyvenv\|_base_executable" benchmark_llm` finds nothing). Re-check
before writing and reuse anything found.

```python
def resolve_base_python(
    *,
    executable: str,
    prefix: str,
    base_prefix: str,
    version: tuple[int, int],
    base_executable: str | None,
) -> tuple[str, str | None]:
    """Return (interpreter_path, warning_or_None) for creating durable venvs."""
```

Required behavior. The logic is load-bearing; follow it exactly:

```text
exe_name = f"python{major}.{minor}"
if prefix != base_prefix:                      # running inside a venv
    home = value of the first `home` key in Path(prefix)/"pyvenv.cfg"
           (split each line on the first "=", strip, key match case-insensitive;
            missing file or key -> home = None)
    candidate = Path(home) / exe_name if home else None
else:
    candidate = Path(executable)               # as given; never resolved
if candidate is not None and "/Cellar/" in str(candidate):
    brew_root, rest = str(candidate).split("/Cellar/", 1)
    formula = rest.split("/", 1)[0]            # e.g. "python@3.14"
    opt = Path(brew_root) / "opt" / formula / "bin" / exe_name
    if opt is an executable file: candidate = opt
if candidate is an executable file (os.path.isfile and os.access X_OK):
    warning = None if "/Cellar/" not in str(candidate) else <cellar warning>
    return str(candidate), warning
fallback = base_executable or executable
return fallback, <fallback warning naming fallback>
```

Warnings are one line, start with `[bench] warning:`, and name the path that
venvs will be pinned to. When the fallback is a venv interpreter (inside a
venv with `base_executable` of `None`), the warning must say so, because venvs
created from it are venv-from-venv. Do not call `realpath`/`resolve` anywhere
in this function.

### Task 2: wire it into `cli.main`

In the `run` branch, before `detect_benchmark_mode` and before any runtime
directories are created:

- If `env` has a non-empty `BENCH_BASE_PYTHON`, the user supplied an override.
  Accept it only if it is an absolute path to an executable file. Otherwise
  write a one-line error to `stderr` and return `1`, following the existing
  config-error pattern (for example the `output_dir` failure path). If a
  valid override contains `/Cellar/` or lives in a venv (a `pyvenv.cfg` in
  its grandparent directory), write a one-line `[bench] warning:` to `stderr`
  and still use it.
- Otherwise call `resolve_base_python` with `sys.executable`, `sys.prefix`,
  `sys.base_prefix`, `sys.version_info[:2]` and
  `getattr(sys, "_base_executable", None)`. Set `env["BENCH_BASE_PYTHON"]`,
  and if there is a warning, write it to `stderr`.
- Leave the PATH code at lines 197-204 unchanged.

Because `env` is the environment passed to every runner, ordinary repo-task
steps, the final-summary step, the prompt-batch judge and plugins all get the
variable. `build_model_command_env` drops it from model-visible steps. That is
intended (Decision 2).

### Task 3: example scripts

**Why a rebuild is needed after the model step.** In both examples the
model-visible `execute` step runs with the runtime interpreter first on
`PATH`, in a worktree whose `visible/.gitignore` ignores `.venv/`. So the
model can create or recreate `.venv` with a pinned interpreter. Running
`venv` again on an existing venv without `--clear` rewrites `pyvenv.cfg`
`home`, but it keeps the existing `bin/python3.X` link, because stdlib
`symlink_or_copy` skips a `dst` that is already a link
(`venv/__init__.py:276`). Any later step that reuses `.venv` must therefore
rebuild it with `--clear`. Steps that reuse `.venv` today:

| Example | Step order (`bench.yaml`) | Creates `.venv` | Reuses `.venv` after the model |
|---|---|---|---|
| policy-engine | prepare, execute, validate, mutation_probe, adjudicate | `run_checks.sh:6` (validate) | `run_checks.sh:7`, `run_mutation_check.sh:6`, `adjudicate.sh:25` |
| cron-eval | prepare, execute, validate, adjudicate | `prepare.sh:9` (before the model) | `run_checks.sh:4`, `adjudicate.sh:29` |

Edits (the `:?` form makes an older runtime fail loudly instead of quietly
creating a pinned venv):

- `examples/policy-engine/scripts/run_checks.sh:6` →
  `"${BENCH_BASE_PYTHON:?BENCH_BASE_PYTHON is not set}" -m venv --clear .venv`.
  The script then reinstalls pytest, PyYAML and `requirements.txt`. Keep
  those lines unchanged, because
  `test_policy_engine_run_checks_allows_missing_requirements_txt` asserts
  them.
- `examples/cron-eval/scripts/prepare.sh:9` →
  `"${BENCH_BASE_PYTHON:?BENCH_BASE_PYTHON is not set}" -m venv .venv`,
  keeping the `if [ ! -d .venv ]` guard. It runs on a fresh worktree before
  the model, so it needs no `--clear`.
- `examples/cron-eval/scripts/run_checks.sh`: insert the same line as
  policy-engine's (`... -m venv --clear .venv`) after `cd "$BENCH_WORKSPACE"`
  and before `source .venv/bin/activate`. This is safe because cron-eval's
  validation and adjudication helpers (`scripts/run_checks.py`,
  `scripts/render_adjudication_prompt.py`) import only the standard library,
  and `prompt.txt` forbids third-party packages. After the edit,
  `test_cron_eval_run_checks_wrapper_uses_repo_task_environment` must still
  pass.

Behavior change (Decision 4): in both examples, validation now discards any
`.venv` the model created and grades in a freshly rebuilt one.

### Task 4: tests

General rules:

- Write each new test red-first where that is possible without creating any
  venv.
- Add a new `tests/conftest.py` (none exists today) with an autouse fixture
  that runs `monkeypatch.delenv("BENCH_BASE_PYTHON", raising=False)` for
  every test, existing and new. `main` merges `os.environ` (`cli.py:195`), so
  without it, an exported override (an expected use, documented in Task 5)
  would reach every test that calls `main`. An invalid value would make
  those tests exit `1` and the exit gate would depend on the shell. That
  includes `_capture_repo_task_environ`, which asserts exit `0`. Tests that
  need an override set it explicitly through `main`'s `environ` argument.
- No test may create a venv from a venv interpreter or from a Cellar path.

**4.1 Resolver unit tests.** Put these in a new `tests/test_base_python.py`.
Build fake trees under `tmp_path`, with mode-0755 files as executables, and
call `resolve_base_python` directly. In cases a, b, c and f, pass
`executable` and `base_executable` as two distinct sentinel paths, for
example `<tmp>/sentinel/exe/python3.99` and
`<tmp>/sentinel/base/python3.99`. Neither may equal the expected result, so
the fallback path can never satisfy those cases by accident; 4.5 depends on
this.

| Case | Setup | Expected |
|---|---|---|
| a | `prefix != base_prefix`; `pyvenv.cfg` `home` = a stable dir containing `python3.X` | that path, no warning |
| b | `home` = `<tmp>/Cellar/python@3.99/3.99.1_1/x/bin`; `<tmp>/opt/python@3.99/bin/python3.99` exists | the `opt` path, no warning |
| c | same `home` as b, with a mode-0755 `<home>/python3.99` created, and no `opt` file | the Cellar candidate `<home>/python3.99`, warning |
| d1 | `prefix != base_prefix` (inside a venv); no `pyvenv.cfg` under `prefix`; `executable` and `base_executable` are two distinct, nonexistent sentinel paths | `base_executable`, warning |
| d2 | `prefix != base_prefix` (inside a venv); `pyvenv.cfg` present without a `home` key; `executable` and `base_executable` are two distinct, nonexistent sentinel paths | `base_executable`, warning |
| d3 | `prefix != base_prefix` (inside a venv); no `pyvenv.cfg`; `executable` is a nonexistent sentinel path; `base_executable=None` | `executable`, warning that says it is a venv interpreter |
| e | `prefix == base_prefix`; `executable` is a symlink, not under `/Cellar/`, to an existing mode-0755 file; `base_executable` is a distinct non-`None` sentinel | `executable`, spelled through the symlink (not resolved), with warning `None` |
| f | `home` is a symlink (not under `/Cellar/`) to a real dir containing a mode-0755 `python3.99` | `<symlinked home>/python3.99`, spelled through the symlink (not resolved), no warning |

**4.2 CLI wiring tests.** Put these in `tests/test_repo_task.py`.

- `test_base_python_defaults_to_resolver`, using
  `_capture_repo_task_environ`: captured `BENCH_BASE_PYTHON` equals
  `resolve_base_python(...)` for the real `sys` values.
- `test_base_python_override_passes_through`, using
  `_capture_repo_task_environ`: a valid absolute executable override
  arrives unchanged.
- `test_base_python_invalid_override_rejected`: do not use
  `_capture_repo_task_environ`. It asserts `exit_code == 0` and discards
  `stderr`. Follow `test_repo_task_requires_output_dir_before_starting_any_model`
  instead: call `main` directly with its own `stderr` buffer, and
  monkeypatch `run_repo_task` with a fake that sets a `called` flag.
  Parametrize over a relative path and a nonexistent absolute path. Assert
  exit code `1`, a non-empty message naming `BENCH_BASE_PYTHON`, and
  `called is False`.
- The existing PATH tests stay unchanged and pass.

**4.3 End-to-end regression (the requested test).** Put this in
`tests/test_repo_task.py`, modelled on
`test_repo_task_writes_run_artifacts_under_configured_output_dir`: a real git
source repo in `tmp_path`, and a hostile `PATH` holding only a `python` that
exits 97. Steps run with `shell=True` under that `PATH`, so `cp`/`cat` are
unavailable. Write the `prepare` step as `python ./scripts/prepare.py`; it
reaches the runtime interpreter through `runtime_bin`. The helper must:

1. Read `BENCH_BASE_PYTHON`. Refuse unless the value fully matches
   `/opt/homebrew/(bin/python3|opt/python@3\.\d+/bin/python3\.\d+)` and
   `Path(value).parent.parent / "pyvenv.cfg"` does not exist. That rules
   out empty values, Cellar paths, venv interpreters and system
   interpreters such as `/usr/bin/python3`: the agent Python rules allow a
   venv to be created only from a Homebrew interpreter by absolute path. On
   refusal, write the reason to `tmp_path/refused.txt` and exit 3, without
   creating a venv.
2. Otherwise run `[value, "-m", "venv", "--without-pip", <workspace>/.venv]`
   with `subprocess`. `--without-pip` keeps the test offline and fast.
3. Write `.venv/pyvenv.cfg`, `os.readlink(<workspace>/.venv/bin/python3.X)`
   and the value to files under `tmp_path`. This has to happen inside the
   step, because successful worktrees are deleted after the run.

Assert, in this order:

- `refused.txt` does not exist (fail with its contents if it does);
- the run exits 0;
- `home` contains no `/Cellar/`;
- `home == str(Path(value).parent)`;
- the link target contains no `/Cellar/`.

The `home` equality holds because the resolver-derived interpreter is
invoked by its stable path. Do not document it as a guarantee for user
overrides. On this machine the expected `home` is
`/opt/homebrew/opt/python@3.14/bin`.

The bug and the regression are Homebrew-specific. At the top of the test,
call `pytest.skip` if `/opt/homebrew/bin` does not exist. The test then runs
on this machine and skips on non-Homebrew hosts. The exit gate's "no skips"
applies to this machine.

Against the current code the variable is unset, so the helper refuses at
step 1 and the test fails. That is the red state, and no venv is created.

**4.4 Static guard on example scripts.** Put this in
`tests/test_repo_task.py` or `tests/test_base_python.py`.

- Inputs: every file under `examples/` returned by
  `git ls-files examples`, run from the project root. This skips
  `__pycache__`, `*.pyc` and other ignored files, which exist on disk today.
  Read each file as UTF-8; a tracked file that fails to decode fails the
  test.
- Rule: any line matching
  `-m\s*venv|venv\.create|virtualenv|\buv\s+venv\b` must contain
  `BENCH_BASE_PYTHON`. This covers bare `python3`, `.venv/bin/python`,
  quoted, `-I`, tab-separated, `-mvenv`, `virtualenv` and `uv venv` forms.
- Exact lines:
  - both `run_checks.sh` files contain
    `"${BENCH_BASE_PYTHON:?BENCH_BASE_PYTHON is not set}" -m venv --clear .venv`;
  - cron-eval `prepare.sh` contains the same invocation without `--clear`;
  - in cron-eval `run_checks.sh`, the rebuild line comes before
    `source .venv/bin/activate`.
- Limits: the guard reads script text only. It cannot see a venv a model
  creates at run time, or one a tool creates indirectly (for example
  `uv sync` or `uv run` building a project `.venv`).

**4.5 Revert check.** After the tests pass, revert each task in turn using
only the reverts below, confirm the named tests fail, then restore. Record
the results.

| Revert | How | Must fail | May still pass |
|---|---|---|---|
| Tasks 1+2 | `cli.main` no longer sets `BENCH_BASE_PYTHON` and no longer validates overrides | 4.2 `test_base_python_defaults_to_resolver` and `test_base_python_invalid_override_rejected`; 4.3 (refused at step 1) | 4.2 `test_base_python_override_passes_through`, because `env` already carries the override |
| Task 1 parsing | the resolver's `pyvenv.cfg` reader returns no `home` | 4.1 a, b, c, f | 4.1 d1, d2, d3, e. Do not run 4.3 in this state |
| Task 3 | restore the old `python3 -m venv .venv` line, and remove the cron-eval rebuild line | 4.4 | everything else. Do not execute the scripts |

Never revert by pointing `BENCH_BASE_PYTHON` or the resolver at
`sys.executable`, `sys._base_executable` or any other Cellar or venv
interpreter. That would make 4.3 create a venv from a venv, which the agent
Python rules forbid.

### Task 5: documentation and records

- `benchmark-llm/README.md`, Repo-task section: document that steps run with
  the runtime interpreter first on `PATH`, that non-model steps receive
  `BENCH_BASE_PYTHON`, and that workspace venvs must be created with
  `"$BENCH_BASE_PYTHON" -m venv`, including why (the Cellar pin). Explain that
  `--clear` is needed when a model step may already have created that venv.
  Document the override, including the warning for Cellar or venv overrides,
  and the remaining limitations: venvs created by model-visible steps that no
  later step rebuilds, and scripts that ignore the contract, still pin.
- `examples/policy-engine/README.md` ("Prompt and validation contract") and
  `examples/cron-eval/README.md`: say that the validation step rebuilds the
  workspace `.venv` from scratch (`--clear`) with `BENCH_BASE_PYTHON`,
  replacing any `.venv` the model created. Describe this in prose, without
  quoting the command, so the READMEs do not add lines to the 4.4 guard or
  the exit grep.
- Root `agents.md` (Execution Guidance → "Do not run a project script that
  creates or recreates a venv with a bare interpreter"): the
  `scripts under benchmark-llm/examples` example becomes inaccurate after
  Task 3. Reword it so it stays true. Those scripts still need a bench run
  context and should not be run directly.
- Create `benchmark-llm/docs/LESSONS_LEARNED.md`, matching the format of
  `colophon/docs/LESSONS_LEARNED.md`. Record the lesson: never create a venv
  from a venv interpreter, `sys._base_executable` is the resolved Cellar path,
  and benchmark steps get `BENCH_BASE_PYTHON`.
- Add a PKM knowledge entry for project `utilities-public` (id 6) recording the
  fix and pointing to global knowledge #3.
- Update global PKM knowledge #3. It currently calls the benchmark-llm root
  cause "a separate pending task" and describes it only as worktree venvs
  being created from benchmark-llm's own venv's python. Replace that
  sentence: the mechanism is the `runtime_bin` PATH prefix plus
  `sys._base_executable` resolving to Cellar; the fix is `BENCH_BASE_PYTHON`;
  and it links the new project-6 entry.

## Validation and exit criteria

Run all commands from `benchmark-llm/`.

- `.venv/bin/python -m pytest -q` passes the complete suite: the 74 existing
  tests plus the new ones, with no skips on this (Homebrew) machine. Report
  every failure by name.
- The tests named under Constraints, and
  `test_cron_eval_run_checks_wrapper_uses_repo_task_environment`, pass
  without edits.
- The Task 4.5 revert table was run, and each "Must fail" result was observed
  and recorded.
- Syntax-check each edited script separately. `bash -n` checks only its first
  operand, so give it one file per call:
  `for f in examples/policy-engine/scripts/run_checks.sh examples/cron-eval/scripts/prepare.sh examples/cron-eval/scripts/run_checks.sh; do bash -n "$f" || echo "FAIL $f"; done`
  prints nothing.
- `git ls-files -z 'examples/*/scripts/*' | xargs -0 grep -nE -- '-m[[:space:]]*venv|venv\.create|virtualenv|uv[[:space:]]+venv'`
  prints exactly three lines, one each from
  `examples/policy-engine/scripts/run_checks.sh`,
  `examples/cron-eval/scripts/prepare.sh` and
  `examples/cron-eval/scripts/run_checks.sh`. All three contain
  `BENCH_BASE_PYTHON`. It reads tracked files only, so ignored `__pycache__`
  files cannot add lines.
- `./bench` is unchanged, so `tools/check_uv_headers.py` does not need to run.
  If the launcher is touched anyway, run
  `uv run --no-python-downloads --script tools/check_uv_headers.py` from the
  repository root.
- Optional, and only with the owner's approval, because it calls paid models:
  run one real `policy-engine` run. Successful worktrees are removed, so
  inspect the `.venv/pyvenv.cfg` and `bin/python3.X` link of a retained
  (failed) worktree, or capture them from a temporary extra step.
- Commit (only when the owner asks): one commit with an imperative subject and
  a body covering the root cause, the fix and the validation. Before
  committing, review the staged diff for sensitive data. This is a public
  repository, so use only synthetic paths in tests and docs; `/opt/homebrew/...`
  paths are generic.

## Out of scope

- The existing venvs under the benchmark-llm runtime home
  (`~/.benchmark_llm` by default), and the broken originals that were set
  aside when those venvs were rebuilt by hand.
- Venvs that models create during model-visible steps, except where a later
  benchmark step rebuilds them (Decision 2; Task 3 covers both bundled
  examples).
- Other monorepo projects.

## Follow-up: PR #33 review (2026-10-12)

A review of PR #33 (merged as `dfdca32`) found that the shipped tests did not
pin most of the new branches, and that `venv --clear` in the validation steps
is unsafe when the model leaves `.venv` as a symlink.

### Whole-part revert results (never recorded before)

Each part of the fix was reverted in turn at `dfdca32` and the suite run:

| Mutant | Part reverted | Failures |
|---|---|---|
| M01 | resolver | 10 failed |
| M11 | CLI | 7 failed |
| M19 | example scripts | 3 failed |
| M20 | example scripts | 2 failed |
| M21 | example scripts | 1 failed |
| M22 | `--clear` | 2 failed |
| M23 | `--clear` | 1 failed |

### Surviving mutants at `dfdca32`

16 of 31 targeted mutants survived the suite: M03, M06, M07, M10, M12, M13,
M14, M15, M16, M24, M25, X1, X2, X3, X4, X5. The M-1 hazard: `--clear` empties
the directory a model-created `.venv` symlink points to (the link target, not
just the link), and no test executed the example scripts, so nothing caught it.

### Owner decisions (all option A)

- D1: validation steps run `rm -rf -- .venv`, then create the venv without
  `--clear`. This replaces the `--clear` mechanism of locked Decision 4 and
  keeps its intent (a model-created `.venv` is rebuilt from the stable base).
- D2: document only the gap for venvs the model creates in a kept worktree;
  no code change.
- D3: an empty `BENCH_BASE_PYTHON=` counts as unset and the resolver is used.
- D4: interpreter paths under a full `X.Y.Z` versioned directory (uv, pyenv)
  produce a warning, never a refusal, through one shared helper.

### Deviations from the fix plan made during execution

1. The static guard in `tests/test_base_python.py` also splits commands on a
   bare `&` and on `|&` (without splitting redirections such as `2>&1`). Task
   review found that `"$BENCH_BASE_PYTHON" -c x & python3 -m venv .venv`
   bypassed the guard.
2. The README sentence saying a prompt-batch `llm_judge` command receives the
   full environment was not added: `benchmark_llm/prompt_batch.py` passes the
   judge the filtered `build_model_command_env` environment.

### Mutation results on the fix branch

The 24 mutants from the fix plan were swept when the suite had 151 tests,
and every one was killed, failing every test it was required to fail. Q1 and Q2
were added after the final review (suite then 157 tests) and were also killed.
Paths are relative to `benchmark-llm/`; test names omit the file prefix
(`tests/test_base_python.py`, `tests/test_repo_task.py`,
`tests/test_example_venv_scripts.py`).

| ID | File | Edit | Failures | Failing tests |
|---|---|---|---|---|
| M03 | benchmark_llm/util.py | Cellar check also requires the candidate not be executable | 2 | test_b_production_cellar_home_with_interpreter_maps_to_opt; test_cellar_executable_outside_venv_maps_to_opt |
| M06 | benchmark_llm/util.py | `partition("=")` becomes `rpartition("=")` in the `home` parser | 1 | test_home_value_may_contain_equals |
| M07 | benchmark_llm/util.py | drop `UnicodeDecodeError` from the `pyvenv.cfg` read handler | 1 | test_non_utf8_pyvenv_cfg_falls_back |
| M10 | benchmark_llm/util.py | `home` parser keeps the last match instead of the first | 1 | test_first_home_line_wins |
| X2 | benchmark_llm/util.py | resolver accepts a `home` candidate without checking it is executable | 2 | test_home_without_interpreter_falls_back; test_not_in_venv_without_base_executable_does_not_claim_venv |
| X3 | benchmark_llm/util.py | Cellar mapping also requires `prefix != base_prefix` | 1 | test_cellar_executable_outside_venv_maps_to_opt |
| X4 | benchmark_llm/util.py | drop the `prefix != base_prefix` condition on the missing-base-executable branch | 1 | test_not_in_venv_without_base_executable_does_not_claim_venv |
| N5 | benchmark_llm/util.py | versioned-directory warning helper returns `None` | 3 | test_versioned_non_homebrew_home_warns[uv]; test_versioned_non_homebrew_home_warns[pyenv]; test_base_python_risky_override_warns_and_passes_through[versioned] |
| M12 | benchmark_llm/cli.py | override check no longer rejects relative paths | 1 | test_base_python_override_rejects_each_invalid_shape[relative-existing] |
| M13 | benchmark_llm/cli.py | override check accepts any file, executable or not | 1 | test_base_python_override_rejects_each_invalid_shape[not-executable] |
| X5 | benchmark_llm/cli.py | override check accepts any path that passes `os.access` (directories too) | 1 | test_base_python_override_rejects_each_invalid_shape[directory] |
| M14 | benchmark_llm/cli.py | resolver-branch warning is no longer written | 1 | test_base_python_resolver_warning_is_reported_and_run_continues |
| M15 | benchmark_llm/cli.py | resolver-branch warning aborts the run (`return False`) | 1 | test_base_python_resolver_warning_is_reported_and_run_continues |
| M16 | benchmark_llm/cli.py | override branch writes an unconditional warning | 5 | test_base_python_override_passes_through[plain]; [symlink]; test_base_python_risky_override_warns_and_passes_through[cellar]; [versioned]; [venv] |
| X1 | benchmark_llm/cli.py | Cellar override skips the helper and the venv-override branch is widened | 1 | test_base_python_risky_override_warns_and_passes_through[cellar] |
| N8 | benchmark_llm/cli.py | `if override:` becomes `if "BENCH_BASE_PYTHON" in env:` | 1 | test_base_python_empty_override_uses_resolver |
| M24 | examples/cron-eval/scripts/prepare.sh | cron `prepare.sh` creation line gains `|| python3 -m venv .venv` | 1 | test_example_scripts_create_venvs_only_from_bench_base_python |
| M25 | examples/policy-engine/scripts/run_checks.sh | policy `run_checks.sh` gains a bare `python3 -m venv .venv` split over two lines | 8 | test_example_scripts_create_venvs_only_from_bench_base_python; test_validate_rebuild_never_touches_what_model_venv_points_to[dir-symlink-policy], [dangling-symlink-policy], [regular-file-policy], [dir-with-nested-symlink-policy]; test_validate_rebuild_replaces_model_created_venv[policy]; test_policy_validate_installs_tools_then_requirements_then_validates[no-reqs], [reqs] |
| N1 | examples/policy-engine/scripts/run_checks.sh | policy `run_checks.sh` goes back to `-m venv --clear .venv` with no `rm` | 8 | test_example_scripts_use_exact_base_python_venv_lines; the four test_validate_rebuild_never_touches_what_model_venv_points_to[...-policy] cases; test_validate_rebuild_replaces_model_created_venv[policy]; test_policy_validate_installs_tools_then_requirements_then_validates[no-reqs], [reqs] |
| N2 | examples/cron-eval/scripts/run_checks.sh | cron `run_checks.sh` goes back to `-m venv --clear .venv` with no `rm` | 6 | test_example_scripts_use_exact_base_python_venv_lines; the four test_validate_rebuild_never_touches_what_model_venv_points_to[...-cron] cases; test_validate_rebuild_replaces_model_created_venv[cron] |
| N3 | examples/policy-engine/scripts/run_checks.sh | policy `rm -rf -- .venv` moves above the `BENCH_BASE_PYTHON` check | 2 | test_example_scripts_use_exact_base_python_venv_lines; test_validate_without_base_python_keeps_workspace_venv[policy] |
| N4 | examples/cron-eval/scripts/run_checks.sh | cron `run_checks.sh` loses `rm -rf -- .venv` | 5 | test_example_scripts_use_exact_base_python_venv_lines; test_validate_rebuild_never_touches_what_model_venv_points_to[dir-symlink-cron], [dangling-symlink-cron], [regular-file-cron]; test_validate_rebuild_replaces_model_created_venv[cron] |
| N6 | tests/test_base_python.py | guard no longer joins backslash continuations | 1 | test_venv_creation_guard_flags_bypass_forms[continuation] |
| N7 | tests/test_base_python.py | guard no longer splits a line into commands | 3 | test_venv_creation_guard_flags_bypass_forms[same-line-or], [background-amp], [pipe-amp] |
| Q1 | examples/policy-engine/scripts/run_checks.sh | `"$BENCH_WORKSPACE"` unquoted in the `run_validation.py` call | 2 | test_policy_validate_installs_tools_then_requirements_then_validates[no-reqs], [reqs] |
| Q2 | examples/cron-eval/scripts/run_checks.sh | `"$BENCH_WORKSPACE"` unquoted in the `run_checks.py` call | 1 | test_cron_validate_runs_checks_with_each_path_as_one_argument |

Note: `test_validate_rebuild_never_touches_what_model_venv_points_to[dir-with-nested-symlink-cron]`
still passes under N4 (the `rm` deleted): that case guards the `rm`-versus-`--clear`
distinction (killed by N1 and N2), not the presence of `rm`.

Final suite on the fix branch: 157 passed, 0 skipped, 0 failed.
