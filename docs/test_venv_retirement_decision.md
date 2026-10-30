# Test environment retirement: decision for review

**Superseded recommendation:** The approved registered isolated runner policy in
`~/.claude/shared/python-env.md` replaces the default recommendation below for
registered projects. Nonregistered projects and the exceptions below retain their
existing contracts. The historical measurements remain evidence only of those
pilots, not of fleet savings or runner correctness.

**Recommendation: retain project test venvs as the default for now.** Allow a
project-specific, explicitly documented `uv run --no-project --with-requirements`
test command after its complete suite and dependency closure have been verified.
Do not remove existing environments or change policy on the strength of these
pilots. The owner must decide whether to adopt the alternative. A script or Make
target is useful only where it captures additional setup or isolation; a wrapper
alone does not make dependencies reproducible.

## Measurements

On 2026-10-30, macOS ARM, uv 0.13.6, the two requirements-file pilots used the
same Homebrew Python 3.14 and fresh project venvs and fresh uv caches. Times are
single wall-clock observations, not benchmarks. Cold pip installation used a
fresh pip cache. Cold uv includes resolving,
downloading and executing tests; warm uv reuses that pilot's cache. Both browser
paths reused an already installed Chromium, whose storage and installation time
are excluded. `du -sk` reports allocated KiB, and hard links, filesystem cloning,
and package sharing make subtraction an estimate rather than reclaimed bytes.

| Project | pip install | venv cold / warm tests | uv cold / warm tests | Result per run | venv / pip cache / uv cache KiB |
| --- | ---: | ---: | ---: | --- | ---: |
| div_conv | 2.08 s | 2.47 / 2.47 s | 4.15 / 2.84 s | 115 passed | 28,688 / 2,028 / 17,992 |
| jtree | 8.37 s | 5.45 / 4.02 s | 8.49 / 4.56 s | 160 passed, one warning | 191,272 / 51,408 / 343,820 |

Fresh venv creation was measured separately at new project-local paths, using the
same Homebrew Python: 1.35 s for div_conv and 1.36 s for jtree. Adding creation,
install, and cold test components gives 5.90 s and 15.18 s respectively, versus
the 4.15 s and 8.49 s cold uv runs above. These sums are not timed end-to-end
runs: creation was measured later, and the two creation commands ran concurrently
with each other and the cross-worktree test below. System load and network
conditions may differ across observations.

Commands, from each project directory, used a new `.venv` created with
`/opt/homebrew/opt/python@3.14/bin/python3.14 -m venv .venv`, then
`.venv/bin/python -m pip install -r requirements-dev.txt`. The runs were
`.venv/bin/python -m pytest tests -v` and
`uv run --no-project --no-python-downloads --python /opt/homebrew/opt/python@3.14/bin/python3.14 --with-requirements requirements-dev.txt pytest tests -v`
for div_conv, and the same commands with `-q` replacing `tests -v` for jtree.
`/usr/bin/time -p` measured each command; `PIP_CACHE_DIR` and `UV_CACHE_DIR`
pointed to separate fresh temporary directories. The fresh uv caches were removed
after measuring. Jtree's warning was pytest's deprecation of session-scoped
instance-method fixtures; neither path skipped tests. The browser test launches
the app via `sys.executable`, as do div_conv CLI tests; these particular cases
worked in both environments. They do not prove all subprocess patterns work.
For the separate creation measurements, the same `-m venv` command targeted
the new `.venv/setup-measurement` path in each project; it did not recreate the
venvs used for the test timings.

For comparison, venv plus cold pip cache occupied 30,716 KiB for div_conv and
242,680 KiB for jtree; fresh uv cache alone occupied 17,992 and 343,820 KiB,
respectively. The apparent difference is approximately 12,724 KiB less and
101,140 KiB more, respectively, before filesystem-sharing effects. A shared uv
cache may amortize artifacts across projects and worktrees, but it retains bytes
outside the checkout (`uv cache dir` identifies its location). No fleet-wide
reclaimed-space claim follows from these single-project measurements.

Two simultaneous div_conv invocations in separate worktrees against one initially
empty temporary uv cache both passed 115 tests in 4.18 s each; the cache occupied
22,920 KiB afterward and was then removed. Both used the same Python 3.14 and
requirements-file uv command above, with `pytest tests -q -p no:cacheprovider`
and `PYTHONDONTWRITEBYTECODE=1` to avoid writes to the second checkout. The
worktrees were at commits `6cbdd29` and `4a0e22c`. This single trial does not
establish safety when projects sync a shared `.venv`, when caches are cleaned
concurrently, or across different dependency resolutions. Test output and
application state still need separate isolation.

The separately authorized `uv run --no-python-downloads --extra dev pytest -q`
in benchmark-llm built the editable project, created its `.venv` using Homebrew
Python 3.15.2, and passed 157 tests in 28.85 s. It is a working project-mode
editable install, not an ephemeral replacement: uv can sync `.venv` and the
lockfile. It is not a comparison with the matrix's Python 3.14 venv. Explicit
approval remains required for that form under current rules.

## Reproducibility and exceptions

Neither an existing venv nor an ephemeral environment guarantees reproducibility:
an existing venv may have unrecorded package history; a fresh resolution may
change because div_conv's `pytest` and jtree's requirements are unpinned. Record
the interpreter and resolved versions when investigating failures; for repeatable
fresh runs adopt reviewed, complete locks or constraints and a deliberate update
process, including browser versions. Verify no skipped tests and all runtime,
test, build and child-process dependencies. `--with-requirements` alone does not
install an editable project. A locked project-mode alternative may be viable, but
its `.venv` mutation and cross-worktree concurrency must be assessed separately.

Keep these as exceptions until their contracts are deliberately changed and
their full suites pass:

* Colophon's generator explicitly checks that `sys.prefix` is its `.venv`;
  `tests/run-pytest.sh` invokes it inside a sandbox with a fixed interpreter.
* Market Atlas's test runner requires a prepared external compiler venv and
  admission/data isolation; setup code manages that environment. Tests must not
  acquire data or silently bootstrap it.
* `docker/llm_collector/migrate.sh` creates and invokes its project venv as part
  of its guarded migration workflow. Agents must not run that script.
* Cognitive Switchyard's builtin verifiers select an existing target or source
  venv and can provision a session environment. Its orchestration defaults and
  regression tests also encode venv behavior. Git Fleet tests contain skip
  messages naming `.venv`; they are not path requirements, but skips must not be
  mistaken for coverage. `coding/task_orch` invokes `.venv/bin/pytest`, and
  `coding/design_orch` defaults to a venv command.
* Benchmark examples intentionally create isolated workspace venvs using
  `BENCH_BASE_PYTHON`; their tests verify that behavior. The benchmark test
  project itself remains a matrix exception until project-mode behavior and
  interpreter version are agreed. The `docker/llm_proxy` image copies and uses
  its application venv; it is not a disposable test venv.

## Inventory classification

The inventory was `git ls-files | rg 'requirements-(dev|test)'`,
`git grep -l '\.venv' -- ':!*.md'`, and
`rg -l '\.venv/bin' -g 'README.md'`. Tracked dev/test requirements occur in
apple-health-extract, cognitive_switchyard, colophon, div_conv, docker/llm_collector,
docpipe, editdb, etf_montecarlo, expense_dock, Git Fleet (`tests/requirements-test.txt`),
harscope, hysa-excel, jtree, launchmaster, mls-tracker, model_sentinel,
router-log-analyzer, routerview, storage_monitor, tax2 and vid-compiler. A
manifest's existence alone does not establish complete dependencies or pinning.
The README matches describe project setup or test commands; they must be reviewed
individually before changing a project's documented workflow.

Every non-Markdown `.venv` match falls into these classes (some files have more
than one):

* **Path/behavior dependency:** Market Atlas `tests/helpers/runner.cjs` and
  `tools/setup_data.mjs`; benchmark example `adjudicate.sh`, `prepare.sh`,
  `run_checks.sh`, and `run_mutation_check.sh`; `coding/design_orch/scripts/codex_packet_loop.zsh`,
  `coding/task_orch/orchestrate.sh`; the three Cognitive Switchyard builtin
  `scripts/verify` files and its `scripts/codex_packet_loop.zsh`;
  `colophon/tests/run-pytest.sh` and `colophon/tools/gen_unicode.py`;
  `docker/llm_collector/migrate.sh`; `docker/llm_proxy/Dockerfile`.
* **Tests, fixtures, or messages:** Market Atlas `tests/setup-data.test.js`;
  benchmark `tests/test_base_python.py`, `test_example_venv_scripts.py`, and
  `test_repo_task.py`; Cognitive Switchyard `tests/conftest.py` and
  `tests/test_builtin_verify_scripts.py`; all matching Git Fleet `tests/` files
  (dependency skip guidance and usage comments, except `test_repo_discovery.py`
  which tests exclusions). These assertions and fixture contracts are not
  evidence that every test must run from `.venv`.
* **Exclusions:** root, Market Atlas, benchmark example, Cognitive Switchyard,
  Colophon and Tax2 `.gitignore` files; Market Atlas `tools/check_admission.mjs`;
  benchmark `examples/policy-engine/scripts/run_mutation_check.py`;
  `docker/llm_collector/migrate.sh` rsync exclusions; `etf_montecarlo/etf_montecarlo`
  and its matching test; Git Fleet `git_dashboard.py` and its discovery test;
  `tools/tests/test_check_uv_headers.py`. Retain these even if test setup changes.

## Required policy work if adopted

The current `agents.md` Python-as-an-agent section and Validation Matrix specify
project venvs, including exact versions and project-specific commands; update
each affected instruction and README in the same reviewed change as its full
suite verification. The global `core.md` and `python-env.md` must explicitly
permit the chosen form without implying that a bare system Python is allowed;
preserve the Homebrew interpreter, no-Python-download, no-system-install and
no-recreate safeguards. Sync distributed instruction copies and update PKM
entries 3 and 249. The shared classifier and hook currently do not flag `uv
run`; that is a heuristic, not validation of safe flags or interpreter choice.
Add focused allowed/blocked regression cases if policy relies on enforcement,
and test the hook and transcript audit. Do not treat this record as authorization
to edit those files, remove venvs, change tests, or run migrations.
