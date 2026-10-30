# Retire Runtime Venvs for uv Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task by task, with each tool task in its own git worktree. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the 11 remaining standing Python tools to uv-managed PEP 723 launchers, remove the venvs they no longer need, and redeploy the installed copies.

**Architecture:** One guard change lands first so every launcher is registered before any tool moves. Tool work then runs in parallel worktrees that touch only their own directories. A single integration task owns all shared docs, and deployment is a separate gated task.

**Tech Stack:** uv, PEP 723 inline metadata, Python, pytest, Playwright, zsh and bash.

**Spec:** None. The owner's decisions are recorded under Global Constraints and Decisions.

## Global Constraints

- `transcription` is out of scope. `transcription/venv` and `~/transcription/venv` are its live runtime and must not be touched. See follow-up F2.
- Max **4 worktrees active at once**. A reviewer shares its implementer's slot. Max **1 Playwright suite at a time**.
- Tool tasks edit only their own project directory. They never edit a file in the Shared Files table.
- Canonical header. The guard requires this exact first line:

  ```python
  #!/usr/bin/env -S uv run --script
  # /// script
  # requires-python = ">=3.12"
  # dependencies = []
  # ///
  ```

- Tools with pinned dependencies (`reversible-skew`, `video-scenes`) use `requires-python = ">=3.12,<3.13"`. On this machine `>=3.12` selects Python 3.15, and those pins were verified only on 3.12.
- Run launchers with `UV_PYTHON_DOWNLOADS=never`. Run the guard with `uv run --no-python-downloads --script tools/check_uv_headers.py`.
- Run Python only as `agents.md` and `core.md` allow. Create any test venv **inside the worktree**, with `/opt/homebrew/bin/python3 -m venv .venv`, so it disappears with the worktree. Never recreate a venv in the main checkout.
- Put temporary files in `mktemp -d`, under `$TMPDIR`, and remove them. Never create `$HOME/.something.XXXXXX` directories.
- Delete with `/usr/bin/trash`, not `rm`, for anything outside a worktree. Space returns when the owner empties the Trash.
- This is a public repository. Use synthetic fixtures only, inspect the full staged diff for sensitive data before each commit, and never read private exports or the contents of `~/.apple-health-extract/project-dir`.
- Commits have an imperative subject and a body saying what changed and why.
- Deploy only from `main`, and only under Task 10 with the owner's separate go-ahead.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Six stdlib tools | One worktree (Task 3) | Each is a header and a README edit, so six reviews would catch nothing |
| `data_format_converter` requirements | Keep one file | The guard's manifest allowance already covers `pytest`, so no split is needed |
| `tomli` | Remove | The new `>=3.12` floor always has `tomllib`, so the fallback is dead code |
| `apple-health-extract/run.sh` | Keep, and call uv | It carries project-dir resolution, and a copy is installed in `~/Library/Scripts` |
| Deployment audit | No changes | Every deployed tool keeps its current deployment shape |
| Test venvs | Delete now, keep the test flow | Converting tests is a separate effort. See follow-up F1 |
| `dloc` | Add no options | `--help` is not added; the smoke test runs the tool itself |

## Shared Files and Conflict Control

Tool directories are disjoint, so all merge risk is in these files.

| File | Who edits it | How conflict is avoided |
|---|---|---|
| `tools/check_uv_headers.py` | Tasks 1 and 9 only | Task 1 registers all 13 launchers at once |
| `tools/tests/test_check_uv_headers.py` | Tasks 1 and 9 only | Same |
| `agents.md` | Task 9 only | Final integration |
| `docs/projects.md`, `docs/local_deployment_sync.md` | Task 9 only | Final integration |
| `README.md` | Nobody | Nothing in it names these tools |
| `.gitignore` | Nobody | Its entries for these tools protect private exports and stay |
| `tools/check_local_deployments.zsh` and its test | Nobody | Deployment shape does not change |

`CLAUDE.md` is a symlink to `agents.md`, so editing either edits both.

Why the guard must go first: `tools/check_uv_headers.py` fails on any uv launcher missing from `LAUNCHERS`, so the first tool to merge would break it. If each branch registered itself, all of them would edit the same two lists and collide.

## Schedule

| Phase | Tasks | Runs | Blocked by |
|---|---|---|---|
| 0 | Task 1 (guard), Task 2 (venv cleanup) | Parallel | Nothing |
| 1 | Tasks 3, 4, 5, 6 | Parallel, 4 slots | Task 1 merged |
| 2 | Tasks 7, 8 | As Phase 1 slots free up | Task 1 merged |
| 3 | Task 9 (integration) | Alone | Tasks 3 to 8 merged |
| 4 | Task 10 (deploy) | Alone | Task 9 merged, owner go-ahead |

- Two slots sit idle during Phase 0 by design. Everything else needs Task 1, and Task 2 is the only independent work.
- Task 2 touches ignored files in the main checkout. Worktrees never inherit `.venv`, so it cannot block or conflict with anyone.
- Task 6 holds the only browser suite in Phases 1 and 2. Tasks 1 and 9 also run browser suites, but neither overlaps Task 6.

### Merge protocol

Merge one branch at a time, in any order.

- [ ] Rebase the branch on `main`.
- [ ] Run the guard. Expected: `check_uv_headers: OK`.
- [ ] Inspect the staged file list and diff for sensitive data.
- [ ] Merge the PR, then remove the worktree and its branch. This also removes any test venv it created.

## Review Focus

1. **Working directory.** `dloc`, `migrate_skills.py` and `md_converter.py` depend on the caller's directory, and a launcher must not change it. Tested in Task 3.
2. **Paths with spaces.** `abacus usage/de-abacus.py` must run by its full quoted path through `env -S`. Tested in Task 3.
3. **Clean stdout.** uv writes install progress to stderr, and `dloc` output is meant for redirecting. Tested in Task 3.
4. **Wrong interpreter for pins.** Pinned tools must select 3.12 rather than the newest Python. Tested in Tasks 5 and 7.
5. **`uv` missing.** `run.sh` must fail with a clear message rather than a shell error. Tested in Task 8.

---

### Task 1: Prepare the guard for parallel migration

**Files:**
- Modify: `tools/check_uv_headers.py`
- Test: `tools/tests/test_check_uv_headers.py`

**Interfaces:**
- Produces: `PENDING_UV_MIGRATION: frozenset[str]`, and a `("stdlib", "", frozenset())` policy in `DEPENDENCY_MANIFESTS`.
- Task 9 removes `PENDING_UV_MIGRATION`.

- [ ] **Step 1: Write the failing tests** in `tools/tests/test_check_uv_headers.py`, using `tmp_path` and `monkeypatch` on `guard.REPO_ROOT` as `test_unregistered_uv_launcher_is_discovered_and_rejected` does:

  ```python
  def test_pending_launcher_without_shebang_is_skipped(...): ...
      # file exists, first line is a plain shebang, path in PENDING_UV_MIGRATION
      assert guard.check_launcher(rel_path) == []

  def test_pending_launcher_with_shebang_is_fully_checked(...): ...
      # canonical first line, no PEP 723 block
      assert "missing or invalid PEP 723 '# /// script' block" in guard.check_launcher(rel_path)

  def test_pending_missing_file_is_skipped(...): ...
      assert guard.check_launcher(rel_path) == []
      assert guard.check_dependency_manifest(rel_path) == []

  def test_registered_missing_file_still_fails(...): ...
      assert guard.check_launcher(rel_path) == [f"file not found: {rel_path}"]

  def test_stdlib_policy_accepts_empty_dependencies(...): ...
      assert guard.check_dependency_manifest(rel_path, {"dependencies": []}) == []

  def test_stdlib_policy_rejects_declared_dependencies(...): ...
      assert guard.check_dependency_manifest(rel_path, {"dependencies": ["pyyaml"]}) == [
          "stdlib-only launcher declares dependencies: pyyaml"
      ]
  ```

- [ ] **Step 2: Run them to verify they fail**

  Run: `uv run --no-project --no-python-downloads --with pytest pytest tools/tests/test_check_uv_headers.py -q -p no:cacheprovider`
  Expected: FAIL on the new tests. The 31 existing tests pass.

- [ ] **Step 3: Add `PENDING_UV_MIGRATION` and the `stdlib` policy to `tools/check_uv_headers.py`**

  - `check_launcher`: for a path in `PENDING_UV_MIGRATION`, return `[]` if the file is missing or its first line is not `CANONICAL_SHEBANG`. A pending file that has the shebang gets every normal check.
  - `check_dependency_manifest`: return `[]` for a pending path whose file is missing. Handle `"stdlib"` before any manifest path is resolved.
  - `main`: on success, print `check_uv_headers: OK (<verified> launchers verified, <pending> pending)`, where `pending` counts only the launchers skipped on this run. Omit the pending clause when it is 0.

- [ ] **Step 4: Register all 13 launchers** in `LAUNCHERS`, `DEPENDENCY_MANIFESTS` and `PENDING_UV_MIGRATION`:

  | Launcher | Format | Manifest | Allowed manifest-only |
  |---|---|---|---|
  | `abacus usage/de-abacus.py` | `stdlib` | | |
  | `anduril_steps/anduril_steps.py` | `stdlib` | | |
  | `dloc/dloc` | `stdlib` | | |
  | `worktree-helper/worktree` | `stdlib` | | |
  | `md-json/md_converter.py` | `stdlib` | | |
  | `Claude_plugin_converter/to_gemini_cli/migrate_skills.py` | `stdlib` | | |
  | `doc_linearizer/linearize.py` | `requirements` | `doc_linearizer/requirements.txt` | none |
  | `data_format_converter/src/data_convert.py` | `requirements` | `data_format_converter/requirements.txt` | `pytest` |
  | `reversible-skew/rs.py` | `requirements` | `reversible-skew/requirements.txt` | `numba` |
  | `reversible-skew/rs-big.py` | `requirements` | `reversible-skew/requirements.txt` | none |
  | `video-scenes/video-scenes` | `requirements` | `video-scenes/requirements.txt` | none |
  | `apple-health-extract/extract_workout_stats.py` | `requirements` | `apple-health-extract/requirements-dev.txt` | none |
  | `apple-health-extract/exercise_bouts.py` | `requirements` | `apple-health-extract/requirements-dev.txt` | none |

- [ ] **Step 5: Run the guard and its tests**

  Run: `uv run --no-python-downloads --script tools/check_uv_headers.py`
  Expected: `check_uv_headers: OK (19 launchers verified, 13 pending)`

  Run the Step 2 command. Expected: all pass.

- [ ] **Step 6: Run the guard's consumer suites in the worktree.** Each project gets its own `.venv`, created per its README, then:

  - `tax2`: `.venv/bin/python -m pytest`
  - `benchmark-llm`: `.venv/bin/python -m pytest`
  - `cognitive_switchyard`: `.venv/bin/python -m pytest`

  They may run in parallel. Report that `tax2`'s uv acceptance checks were not run, because they exercise its launcher rather than the guard.

- [ ] **Step 7: Commit and merge** through the merge protocol. Every tool task branches from this commit.

---

### Task 2: Remove stale venvs

This task changes no tracked files, so it needs no worktree, commit or review.

- [ ] **Step 1: List every venv.** Run `find . -name pyvenv.cfg -not -path '*/node_modules/*' -not -path './.claude/*'` from the repo root. Expected: 29.

- [ ] **Step 2: Confirm nothing holds them.** Check `ps -axo pid,command` and `lsof` for any process using a path under these venvs. Stop and report if one is in use.

- [ ] **Step 3: Trash these 25 with `/usr/bin/trash`**, about 3.3 GB:

  - All 24 `.venv` directories, including the one at the repo root
  - `vid-compiler/venv`

- [ ] **Step 4: Confirm the 4 kept venvs remain:** `transcription/venv`, `apple-health-extract/venv`, `reversible-skew/venv` and `video-scenes/venv`. The last three go in Task 10.

- [ ] **Step 5: Remove `~/vid-compiler/venv`** (232 MB). Its only reference is a stale untracked `~/vid-compiler/README.txt`. Then run `UV_PYTHON_DOWNLOADS=never ~/vid-compiler/video_compiler.py --help`. Expected: usage text.

---

### Task 3: Migrate the six stdlib tools

**Files:**
- Modify: `abacus usage/de-abacus.py`, `abacus usage/README.md`
- Modify: `anduril_steps/anduril_steps.py`, `anduril_steps/README.md`
- Modify: `dloc/dloc`, `dloc/README.md`
- Modify: `worktree-helper/worktree`, `worktree-helper/README.md`
- Modify: `md-json/md_converter.py`, `md-json/README.md`
- Delete: `md-json/setup.sh`
- Modify: `Claude_plugin_converter/to_gemini_cli/migrate_skills.py`, its `README.md` and `MIGRATION_GUIDE.md`

**Interfaces:**
- Consumes: the `stdlib` policy from Task 1.

- [ ] **Step 1: Replace the first line of `de-abacus.py`, `anduril_steps.py`, `dloc` and `worktree` with the canonical header.** Keep any docstring or `from __future__` import after it, unchanged in order.

- [ ] **Step 2: Add the header above line 1 of `md_converter.py` and `migrate_skills.py`, and make both executable** with `chmod +x`.

- [ ] **Step 3: Bump `VERSION` in `worktree-helper/worktree` from `"0.1.0"` to `"0.1.1"`.** It is the only versioned tool in this plan.

- [ ] **Step 4: Update the READMEs.** Remove every venv setup step, and state the requirement as uv (`brew install uv`).

  - `abacus usage/README.md`: remove the venv block in Quick start.
  - `anduril_steps/README.md`: remove the venv block and the `python3 anduril_steps.py --help` form.
  - `dloc/README.md`: remove the venv block and the "Python 3.9 or newer" line.
  - `worktree-helper/README.md`: add the uv requirement.
  - `md-json/README.md`: remove the setup section, delete `md-json/setup.sh`, and change usage to `./md_converter.py`.
  - `Claude_plugin_converter`: change usage to invoke the script directly. Change the test command to `~/.venvs/agent-tools/bin/python -m unittest discover -s tests -v`, because the current `uv run --python 3.12 python …` form needs approval under `agents.md`.

- [ ] **Step 5: Run the guard.** Expected: OK, with `pending` lower by 6.

- [ ] **Step 6: Smoke-test each tool.** Prefix each with `UV_PYTHON_DOWNLOADS=never`:

  | Command | Expected |
  |---|---|
  | `"$PWD/abacus usage/de-abacus.py" --help` | Usage text (Review Focus 2) |
  | `anduril_steps/anduril_steps.py --help` | Usage text |
  | From another git repo: `<worktree>/dloc/dloc 2>/dev/null \| head -1` | `\| Date       \| Added   \| Removed \| Net Change \|`, with that repo's rows (Review Focus 1, 3) |
  | `worktree-helper/worktree --version` | `0.1.1` |
  | `worktree-helper/worktree --list` | Lists this repo's worktrees (imports `curses`) |
  | `cd "$S" && <worktree>/md-json/md_converter.py --input synthetic.json --output out.csv`, with a synthetic `{"all_items": []}` | `out.csv` written in `$S` (Review Focus 1) |
  | In `Claude_plugin_converter/to_gemini_cli`: the new test command | All tests pass |

- [ ] **Step 7: Commit and merge** through the merge protocol.

---

### Task 4: Migrate doc_linearizer

**Files:**
- Modify: `doc_linearizer/linearize.py`, `doc_linearizer/README.md`

**Interfaces:**
- Consumes: its Task 1 registration. `doc_linearizer/requirements.txt` stays as the guard's manifest.

- [ ] **Step 1: Add the header** above line 1 with `dependencies = ["beautifulsoup4", "html2text"]`, and make the file executable.

- [ ] **Step 2: Update `doc_linearizer/README.md`.** Replace Setup with the uv requirement, and change usage to `./linearize.py`.

- [ ] **Step 3: Run the guard.** Expected: OK.

- [ ] **Step 4: Run a synthetic smoke test.** In a `mktemp -d` directory `$S`, write `$S/ig/site/index.html` containing `<h2>SYNTHETIC HEADING</h2>`, and create `$S/out`.

  Run: `UV_PYTHON_DOWNLOADS=never doc_linearizer/linearize.py "$S/ig" -o "$S/out/out.md"`
  Expected: `Successfully created`, and `$S/out/out.md` contains `SYNTHETIC HEADING`.

  The output's parent directory must already exist. This was verified with a prototype of this launcher.

- [ ] **Step 5: Commit and merge** through the merge protocol.

---

### Task 5: Migrate reversible-skew

**Files:**
- Modify: `reversible-skew/rs.py`, `reversible-skew/rs-big.py`, `reversible-skew/README.md`
- Delete: `reversible-skew/setup.sh`

**Interfaces:**
- Consumes: its Task 1 registration. `reversible-skew/requirements.txt` stays as the guard's manifest.

- [ ] **Step 1: Replace line 1 of both scripts with the header**, using `requires-python = ">=3.12,<3.13"`:

  - `rs.py`: `dependencies = ["pydivsufsort==0.0.20"]`
  - `rs-big.py`: `dependencies = ["pydivsufsort==0.0.20", "numba==0.68.0"]`

- [ ] **Step 2: Update `reversible-skew/README.md`.** Remove the Setup section and the `setup.sh` file entry, and change usage to `./rs.py` and `./rs-big.py`. Keep the note on `rs.py`'s slow fallback, but say the launcher installs `pydivsufsort`.

- [ ] **Step 3: Run the guard.** Expected: OK.

- [ ] **Step 4: Run each selftest.**

  Run: `UV_PYTHON_DOWNLOADS=never reversible-skew/rs.py selftest`, then the same for `rs-big.py`.
  Expected: each ends with `SELFTEST PASSED!`.

- [ ] **Step 5: Verify the pinned interpreter and cross-script format.** The header cap is what selects 3.12 (Review Focus 4). Run `rs.py transform` on a synthetic file in `mktemp -d`, run `rs-big.py inverse` on the result, and compare with `cmp`. Expected: identical.

- [ ] **Step 6: Commit and merge** through the merge protocol.

---

### Task 6: Migrate data_format_converter

**Files:**
- Modify: `data_format_converter/src/data_convert.py`, `data_format_converter/src/converters/toml_conv.py`, `data_format_converter/requirements.txt`, `data_format_converter/README.md`
- Modify: `data_format_converter/tests/test_cli_roundtrip.py`, `data_format_converter/tests/test_toml_conv.py`
- Create: `data_format_converter/tests/test_launcher.py`

**Interfaces:**
- Consumes: `extract_pep723` and `missing_declared_imports` from `tools/check_uv_headers.py`, and `assert_launcher_help` from `tools/testkit.py`.

- [ ] **Step 1: Write the failing test** in `data_format_converter/tests/test_launcher.py`. The guard scans only the launcher file, so this test covers the sibling `converters` package:

  ```python
  def test_header_declares_every_converter_import():
      text = LAUNCHER.read_text(encoding="utf-8")
      deps = extract_pep723(text)["dependencies"]
      for module in [LAUNCHER, *CONVERTERS.glob("*.py")]:
          assert missing_declared_imports(module, module.read_text(encoding="utf-8"), deps) == []

  def test_launcher_help_runs_through_uv():
      assert_launcher_help(LAUNCHER)
  ```

- [ ] **Step 2: Run it to verify it fails.** Create `.venv` in the worktree, install `requirements.txt`, then run `.venv/bin/python -m pytest tests/test_launcher.py`.
  Expected: FAIL, because `data_convert.py` has no header.

- [ ] **Step 3: Add the header to `src/data_convert.py`** with `dependencies = ["pyyaml", "tomli-w", "toon-format==1.1.0", "xmltodict"]`, and make it executable. `sys.path` includes the script's directory, so `from converters…` keeps working.

- [ ] **Step 4: Remove `tomli`.** Delete it from `requirements.txt`, replace the `try`/`except` at `src/converters/toml_conv.py:3-6` with `import tomllib`, and do the same for the fallbacks in `tests/test_cli_roundtrip.py` and `tests/test_toml_conv.py`.

- [ ] **Step 5: Update `data_format_converter/README.md`.** Change the requirement from Python 3.10 to uv, replace the venv block, and change usage to `./src/data_convert.py`. Keep the Testing section, which still uses a dev `.venv`.

- [ ] **Step 6: Run the full suite in the worktree.**

  Run: `uv run --no-python-downloads --script tools/check_uv_headers.py` from the worktree root. Expected: OK.
  Run: `.venv/bin/python -m pytest`. Expected: all pass.
  Run: `npm ci`, `npx playwright install chromium`, `npm run test:browser`. Expected: all pass.

- [ ] **Step 7: Commit and merge** through the merge protocol.

---

### Task 7: Add a video-scenes launcher

**Files:**
- Create: `video-scenes/video-scenes`
- Modify: `video-scenes/README.md`
- Delete: `video-scenes/setup.sh`

**Interfaces:**
- Consumes: its Task 1 registration. `video-scenes/requirements.txt` stays as the guard's manifest.

- [ ] **Step 1: Create the executable `video-scenes/video-scenes`.** Use `requires-python = ">=3.12,<3.13"`, and declare all six pins from `requirements.txt` in the header: `opencv-python==5.0.0.93`, `numpy==2.5.4`, `Click==8.5.0`, `tqdm==4.70.1`, `platformdirs==4.13.1`, `scenedetect==0.7.2`. The body imports `main` from `scenedetect.__main__` and calls `sys.exit(main())`. This is scenedetect's own console entry point, and a prototype of this launcher ran successfully.

- [ ] **Step 2: Update `video-scenes/README.md`.**

  - Replace Requirements and Setup with uv and `ffmpeg`.
  - Change `scenedetect` commands to `./video-scenes`.
  - Keep the Tips.
  - Change `venv/bin/scenedetect` in Validation to `./video-scenes`.

- [ ] **Step 3: Run the guard.** Expected: OK.

- [ ] **Step 4: Run the README's Validation check** with `./video-scenes`, in `mktemp -d`.
  Expected: exactly two 75-frame scenes, with the cut at `00:00:03.000`. Running on 3.12 is enforced by the header (Review Focus 4).

- [ ] **Step 5: Commit and merge** through the merge protocol.

---

### Task 8: Migrate apple-health-extract

**Files:**
- Modify: `apple-health-extract/extract_workout_stats.py`, `apple-health-extract/exercise_bouts.py`, `apple-health-extract/run.sh`, `apple-health-extract/README.md`
- Test: `apple-health-extract/tests/test_run_wrapper.sh`
- Delete: `apple-health-extract/setup.sh`

**Interfaces:**
- Consumes: its Task 1 registration. `requirements-dev.txt` stays as the guard's manifest.
- `run.sh` keeps its existing `--check`, `--help` and project-directory resolution order.

- [ ] **Step 1: Update `tests/test_run_wrapper.sh` first.** Replace the fake `venv/bin/python` with a fake `uv` on `PATH` that records its arguments. The wrapper's behaviour is changing, so this is a real requirement change rather than a test edited to pass. Assert that:

  - `run.sh` invokes `uv run --no-python-downloads --script <project>/extract_workout_stats.py`
  - extractor arguments pass through
  - the working directory is the project directory
  - with no `uv` on `PATH`, `run.sh` and `run.sh --check` exit non-zero with a message containing `brew install uv` (Review Focus 5)

- [ ] **Step 2: Run it to verify it fails.** Run: `bash tests/test_run_wrapper.sh`. Expected: FAIL.

- [ ] **Step 3: Update `run.sh`.** Replace the `venv/bin/python` check at lines 106-107 with a `command -v uv` check, and replace the final `exec` with `exec uv run --no-python-downloads --script "$PROJECT_DIR/$EXPECTED_SCRIPT" "$@"`. Update the usage text.

- [ ] **Step 4: Add the header to both Python scripts** with `dependencies = ["pandas>=3.0", "tqdm>=4.70"]`, and make them executable.

- [ ] **Step 5: Update `apple-health-extract/README.md`.** Remove `setup.sh` from the file list and setup steps, delete `setup.sh`, and change `venv/bin/python exercise_bouts.py` to `./exercise_bouts.py`. Update the private operational copy steps.

- [ ] **Step 6: Run the guard and the wrapper test.** Expected: both pass.

- [ ] **Step 7: Run a synthetic extraction** in `mktemp -d`, with an invented `export.xml` holding one `<Workout>` and one heart-rate `<Record>` inside its time window, dated 2030. Run `UV_PYTHON_DOWNLOADS=never <worktree>/apple-health-extract/extract_workout_stats.py` from that directory. Expected: `workout_summary.csv` has one row with `hr_samples` of 1. This was verified with a prototype of this launcher. Never use a real export.

- [ ] **Step 8: Commit and merge** through the merge protocol.

---

### Task 9: Integrate shared docs and finish the guard

**Files:**
- Modify: `tools/check_uv_headers.py`, `tools/tests/test_check_uv_headers.py`
- Modify: `agents.md`, `docs/projects.md`, `docs/local_deployment_sync.md`

**Interfaces:**
- Produces: `NON_UV_PYTHON_ALLOWLIST: tuple[str, ...]`, a constant of repo-relative paths and directory prefixes.

- [ ] **Step 1: Write the failing test.** `test_unlisted_python_shebang_is_rejected` follows the synthetic pattern of `test_unregistered_uv_launcher_is_discovered_and_rejected`, and asserts that `guard.main() == 1` with `not a uv launcher` in the output.

- [ ] **Step 2: Add the check.** In `main`, fail any file from `git_repository_files()` whose first line matches `^#!.*python` unless it matches `NON_UV_PYTHON_ALLOWLIST`, which holds:

  - `Calculation tools/backtest/data/compile_market_data.py`
  - `benchmark-llm/examples/shared/demo_prompt_executor.py`
  - `coding/design_orch/scripts/codex_json_progress.py`
  - `cognitive_switchyard/cognitive_switchyard/scripts/plan_commit_msg.py`
  - `cognitive_switchyard/scripts/codex_json_progress.py`
  - `cognitive_switchyard/tests/fixtures/workers/`
  - `docker/llm_collector/snapshots/rollup_snapshots.py`
  - `harscope/tests/verify_redaction.py`
  - `model_sentinel/__main__.py`
  - `model_sentinel/model-sentinel`

  This check sees shebangs only, so it can't catch a tool with no shebang. Follow-up F3 covers that.

- [ ] **Step 3: Remove `PENDING_UV_MIGRATION`** with its branches and the Task 1 tests that exercise it. Keep the `stdlib` policy and its tests.

- [ ] **Step 4: Update `agents.md`.**

  - Line 234: remove `reversible-skew`, `video-scenes`, `md-json` and `apple-health-extract` from the setup-script list.
  - Line 237: remove the `Claude_plugin_converter` example.
  - Validation Matrix: add the Task 3 to Task 8 smoke commands as entries for these tools. Keep `data_format_converter`'s `.venv` commands.

- [ ] **Step 5: Update `docs/projects.md`.** Change the `video-scenes` delivery type from "Setup helper and command reference" to CLI, and describe the launcher.

- [ ] **Step 6: Update `docs/local_deployment_sync.md`.** Line 710 ("Apple Health exports and its project venv") no longer applies to the venv. Note that `~/transcription` is the remaining home copy with a venv.

- [ ] **Step 7: Run everything.**

  Run the guard. Expected: `check_uv_headers: OK (32 launchers verified)`.
  Run the guard tests with the Task 1 command. Expected: all pass.
  Run `tax2`, `benchmark-llm` and `cognitive_switchyard` pytest suites in this worktree. Expected: all pass.

- [ ] **Step 8: Commit and merge** through the merge protocol.

---

### Task 10: Redeploy and remove the remaining venvs

**This task needs the owner's separate go-ahead.** Run it from `main` only, after Task 9. Follow `docs/local_deployment_sync.md`, which takes a backup first.

| Installed copy | Source | Action |
|---|---|---|
| `~/Library/Scripts/de-abacus.py` | `abacus usage/de-abacus.py` | Byte-identical copy |
| `~/Library/Scripts/dloc` | `dloc/dloc` | Byte-identical copy |
| `~/Library/Scripts/worktree` | `worktree-helper/worktree` | Byte-identical copy |
| `~/Library/Scripts/apple-health-extract` | `apple-health-extract/run.sh` | Copy. It is identical to `run.sh` today, but the audit does not track it |
| `~/apple-health-extract` | `apple-health-extract` | Home-project copy |
| `~/video-scenes` | `video-scenes` | Home-project copy |

- [ ] **Step 1: Copy the three `~/Library/Scripts` files and the wrapper.** Expected: `cmp` is clean, and `~/Library/Scripts/worktree --version` prints `0.1.1`.

- [ ] **Step 2: Copy the two home projects** with the documented pattern. Then trash `~/apple-health-extract/setup.sh` and `~/video-scenes/setup.sh`, because the copy pattern doesn't delete files removed from the repo.

- [ ] **Step 3: Verify each installed copy before removing anything.**

  - `~/Library/Scripts/apple-health-extract --check`. Expected: `configuration OK`.
  - `UV_PYTHON_DOWNLOADS=never ~/video-scenes/video-scenes version`. Expected: version output.

- [ ] **Step 4: Run the deployment audit** with `zsh tools/check_local_deployments.zsh`. Expected: no drift for any tool in this plan. Report any other drift rather than fixing it here.

- [ ] **Step 5: Trash the remaining venvs**, about 760 MB:

  - `~/apple-health-extract/venv`
  - `~/video-scenes/venv`
  - `apple-health-extract/venv`
  - `reversible-skew/venv`
  - `video-scenes/venv`

  Do not touch `~/transcription/venv` or `transcription/venv`.

- [ ] **Step 6: Confirm the end state.** The repo `find` from Task 2 lists only `transcription/venv`, plus any test venv recreated since. Report the released version: `worktree` 0.1.1.

---

## Home Residue Cleanup (Independent)

This work touches no repository files and no worktrees, so it can run at any time without using a worker slot. It uses `/usr/bin/trash`, and nothing is permanently gone until the owner empties the Trash.

The inventory below is from 2026-10-30 and must be rechecked before acting. Keep this section free of private content: list directory names only, never their contents.

### Tier A: trash after listing (45 directories, about 4.1 GB)

These are test, acceptance and agent-evidence directories from 2026-10-13 to 2026-10-17. No acceptance app is running.

| Pattern | Count | Size |
|---|---|---|
| `~/.brew-version-acceptance.*` | 9 | 2.2 GB |
| `~/.storage_monitor-acceptance.*` | 1 | 1.3 GB |
| `~/.colophon-cutover-*`, `~/.colophon-deploy-acceptance.*` | 7 | 451 MB |
| `~/.reversible-skew-task*` | 2 | 248 MB |
| `~/.llm-*` | 14 | 30 MB |
| `~/.brew-version-review-*`, `-settings-prototype.*`, `-final-validation.*`, `-task7-validation.*` | 6 | 1 MB |
| `~/.git-fleet-rescan-task13.*`, `~/.converter-temporal-task12.*`, `~/.market-atlas-cutover-validation.*`, `~/.storage_monitor-deploy.*` | 4 | 4 MB |
| `~/.model-sentinel-job-review-*`, `~/.model-sentinel-manual-run-*` | 2 | 1 MB |

### Tier B: ask the owner first, with a one-line description of each

- `~/.telltale-design-originals.*` (2 MB, 2 days old): may be originals the owner still wants.
- `~/.model-sentinel-recovery.*` (2 MB) and `~/.usage-monthly-csv-backup.*`: recovery data.
- `~/vid-compiler/working-venv-2025-06-02.7z` (23 MB), `~/vid-compiler/backup-video_compiler.py` and `~/vid-compiler/README.txt`: old local-only files.
- `~/.utilities-repair-snapshots` (48 MB) and `~/.prime-monitor-backups` (4 MB).
- `~/.codex/worktrees` (469 MB, 22 entries): Codex-managed. List each worktree's branch and merge state, and propose removing only merged ones through `git worktree remove`.

### Tier C: deploy backups, ask first (`~/.utilities-deploy-backups`, 1.7 GB in 36 entries)

These are rollback copies. The tools never prune them, and deletion is manual. They may hold private configuration, so never copy or print their contents.

- **Recommended:** `transcription-20261015.*` (1.2 GB) and `video-scenes-deps.*` (169 MB), which are old venv copies.
- **Keep:** the versioned deployers' `copy-*` backups (`colophon-native`, `brew-version`, `telltale`, `anker-charge-monitor`, `storage_monitor`, `backtest`, `model-sentinel`, `ai-model-timeline`, `drawdown`).
- **Keep:** anything from the last 7 days, including backups Task 10 creates.
- **For the rest:** the remaining dated one-off entries total about 16 MB, so leave them unless the owner wants them gone.

### Tier D: regenerable caches, ask first (about 7.5 GB)

Clearing these means re-downloading later. Use each tool's own command, not `trash`.

| Cache | Size | Command |
|---|---|---|
| `~/.bun/install/cache` | 2.8 GB | `bun pm cache rm` |
| `~/Library/Caches/Homebrew` | 2.2 GB | `brew cleanup` |
| `~/.cache/codex-runtimes` | 1.6 GB | Inspect first; it may be in use |
| `~/.npm` | 892 MB | `npm cache clean --force` |

### Never touch

- `~/.codex` sessions: Colophon reads them
- `~/.local`: holds opencode data, including credentials
- `~/.claude`, `~/.config`, `~/.docker`, `~/.gemini`, `~/.lmstudio`, `~/.venvs`, `~/.t3`
- Tool runtime homes: `~/.colophon`, `~/.model_sentinel`, `~/.storage_monitor`, `~/.tax2`, `~/.routerview`, `~/.benchmark_llm`, `~/.cognitive_switchyard`, `~/.apple-health-extract` and similar
- `~/transcription/venv`

### Procedure

1. Re-inventory with sizes and dates. Report anything that doesn't match the tables, and any new directory.
2. Confirm no process has files open in a Tier A directory.
3. Show the owner the final Tier A list, then trash it. Tier A was approved in principle, but the list must be shown first.
4. Ask the owner about Tiers B, C and D, item by item.
5. Report the space moved to Trash and remind the owner to empty it.

---

## Follow-ups (Discovery Briefs)

These are not ready to implement. Each is a starting point for an agent to investigate and produce its own implementation plan.

### F1: Retire test venvs

**Goal:** Stop test venvs from coming back after Task 2, without losing reproducible test runs or the safety of the Python rules.

**Why it's needed:** Task 2 frees about 3.3 GB only until each suite next runs, because the current rules and docs require a project `.venv`.

**Known facts:**

- Repo inventory on 2026-10-30: 24 `.venv` directories totalling 3.0 GB, with Python versions from 3.12 to 3.15. There are 21 tracked `requirements-dev` or `requirements-test` files.
- Verified working from the repo root, with no project venv, 31 tests passing:
  `uv run --no-project --no-python-downloads --with pytest pytest tools/tests/test_check_uv_headers.py -q -p no:cacheprovider`
- `~/.claude/shared/python-env.md` already allows `uv run --with-requirements <the project's own requirements file>` with `--no-project`, or outside any uv project.
- `benchmark-llm` and `docker/llm_proxy` are uv projects. `uv run` without `--script` or `--no-project` needs approval there, as do `uv sync` and `uv lock`.
- The Playwright browser cache is 572 MB at `~/Library/Caches/ms-playwright`, outside any venv, and it survives venv deletion.
- **Disk moves rather than disappears.** Prototyping just `video-scenes` and `reversible-skew` launchers grew `~/.cache/uv` from 137 MB to 754 MB. Script environments live in `~/.cache/uv/environments-v2/`.

**Where `.venv` is hard-coded or required:**

| Location | Type |
|---|---|
| `agents.md` Validation Matrix and "Python as an agent" section | Policy; most test commands |
| Project READMEs, Testing sections | Docs, about 20 projects |
| `colophon/tests/run-pytest.sh:23` | Runtime path |
| `colophon/tools/gen_unicode.py:100` | Raises unless `sys.prefix` is the project `.venv` |
| `git-multirepo-dashboard/tests/` (about 30 files) | Docstrings and `conftest.py:21`; confirm whether any is runtime |
| `cognitive_switchyard/tests/conftest.py:58` | Error-message hint |
| `cognitive_switchyard/.../builtin_packs/*/scripts/verify` | Run against target repos, so probably not in scope |
| `coding/task_orch/orchestrate.sh:502-569` | Agent instructions and a runtime `.venv/bin/pytest` call |
| `Calculation tools/backtest/tests/helpers/runner.cjs` | External venv via `MARKET_ATLAS_TEST_PYTHON` |
| `docker/llm_collector` | Uses its own `.venv` for tests; `migrate.sh` is never run by agents |

**Rules that would need changing, outside this repo:**

- `~/.claude/shared/core.md`: Python section
- `~/.claude/shared/python-env.md`
- `~/.claude/shared/python-venv-guard.sh`, `python-classifier.awk` and `audit-python-usage.sh`. Check that the guard's classifier permits the chosen form.
- PKM entries #3 (environment policy) and #249 (slim instructions)

**Questions to answer:**

1. What is the replacement: ephemeral `uv run --with-requirements`, one shared script per project, or a Make target? Does it work for projects that need editable installs (`pip install -e`)?
2. How long is a cold run and a warm run, compared with a `.venv`, on one small and one browser project?
3. What is the real disk result? Measure `~/.cache/uv` after running all suites, and compare with the 3.0 GB of venvs. If the cache holds the same bytes, is the benefit tidiness rather than space, and is that enough?
4. Does `pytest-playwright` behave in an ephemeral environment, and do tests that spawn `sys.executable` still find their packages?
5. Are versions reproducible? `requirements-dev` files are mostly unpinned. Does losing a stable venv make failures harder to reproduce?
6. How do concurrent runs across worktrees behave against the shared uv cache?
7. Which projects should stay exceptions? Colophon's `sys.prefix` check and Market Atlas's external venv are the likely candidates.

**Suggested pilots:** `div_conv` (pytest only), `jtree` (browser), `benchmark-llm` (uv project).

**Done when:** There is a written recommendation with measured numbers, a list of exceptions, and the rule changes needed, and the owner has chosen an approach. An implementation plan follows from that.

### F2: Migrate transcription

**Goal:** Decide how `transcription` moves to uv. It's the last runtime venv, at 1.2 GB in each of `transcription/venv` and `~/transcription/venv`.

**Known facts:**

- There are two Streamlit entry points, `app.py` and `transcribe.py`. `ui.sh` activates the venv and runs `streamlit run app.py`.
- `run.sh`, `m4a-run.sh` and `help.sh` are unsupported legacy wrappers, per `agents.md` and the README.
- `transcription_odometer.txt` and `session_backup.json` use paths relative to the working directory, not a runtime home. Treat them as sensitive state.
- `app.py` imports `openai`, and `transcribe.py` imports `librosa`. Both are optional in `requirements-optional.txt`.
- The guard requires every import at any scope to be declared, and forbids `os.execv`.
- The requirements pin `openai-whisper==20250625`, `streamlit==1.66.0` and `pandas==3.0.6`, and `setup.sh` uses `python3.12`.
- `~/transcription` is a tracked home-project deployment.

**Questions to answer:**

1. How should a launcher start `streamlit run`, given the `os.execv` ban? Can it call `streamlit.web.cli` or a child process, and does Ctrl-C still work?
2. Should the optional packages become required, or does the guard need an optional-dependency policy?
3. Should state move to `~/.transcription/`, and how is existing state migrated without an automatic import?
4. Is one launcher with two modes better than two launchers?
5. Should the legacy wrappers be deleted?
6. What is the torch and whisper footprint in the uv cache, and does a cold start stay acceptable? Are Whisper model downloads unaffected?

**Done when:** The owner has chosen answers to questions 1 to 3, and an implementation plan can be written.

### F3: Catch unmigrated tools with no shebang

**Goal:** Task 9's check sees only shebangs, so a new Python tool with no shebang, as `md-json` and `doc_linearizer` were, would pass.

**Questions to answer:** Can a tool be detected from `if __name__ == "__main__":` with `argparse`, a `docs/projects.md` entry, or a required registry row? Which detection gives few false positives on test helpers and library modules? Should the guard also scan sibling modules in general, as Task 6's test does for one project?

**Done when:** There is a chosen detection rule and a list of its exceptions.

### F4: Stop home residue from coming back

**Goal:** The Home Residue Cleanup removes the existing clutter, but nothing prevents new clutter.

**Known facts:**

- `agents.md:116` tells agents to create `~/.tax2-acceptance.XXXXXX` in `$HOME`, which directly contradicts the rule below.
- `docs/lessons_learned.md`, entry of 2026-10-17, says acceptance homes belong in private OS temporary space.
- Agents created about 45 acceptance and task-evidence directories in `$HOME` in five days of October (2026-10-13 to 2026-10-17).
- `tools/check_no_temp_leaks.sh` covers `$TMPDIR` and the Darwin temp dir, not `$HOME`.
- The deployment docs state that backups are never automatically pruned.

**Questions to answer:**

1. Why did agents choose `$HOME`? Possible reasons include sandbox limits on `$TMPDIR` and a need for evidence to survive across sessions.
2. Should there be one sanctioned evidence location, with a retention rule?
3. Should `core.md` or `agents.md` carry the rule, and should `tools/check_no_temp_leaks.sh` also watch `$HOME`?
4. What retention policy suits `~/.utilities-deploy-backups`, such as keeping the newest N per namespace, and should it stay manual?

**Done when:** The owner has agreed a rule, and `agents.md:116` no longer conflicts with it.
