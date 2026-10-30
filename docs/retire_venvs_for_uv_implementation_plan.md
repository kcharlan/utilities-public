# Retire Runtime Venvs for uv Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task by task, with each tool task in its own git worktree. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the standing Python tools in the Guard Prep launcher table to uv-managed PEP 723 launchers, remove the venvs they no longer need, and redeploy the installed copies.

**Architecture:** Follow Schedule for sequencing and Shared Files and Conflict Control for ownership.

**Tech Stack:** uv, PEP 723 inline metadata, Python, pytest, Playwright, zsh and bash.

**Spec:** Global Constraints and Decisions define the proposed implementation. Approval of this plan does not authorize implementation or deployment.

## Global Constraints

- **`transcription` is out of scope.** `transcription/venv` and `~/transcription/venv` are its live runtime and must not be touched. See the Transcription Migration follow-up.
- **Worker cap:** max 4 worktrees active at once, with a reviewer sharing its implementer's slot. Max 1 Playwright suite at a time, including Guard consumer suites.
- **Own directory only:** tool tasks edit only their own project directory, and never a file in the Shared Files table.
- **Worktree placement:** create task worktrees outside the main checkout, so Venv Cleanup's repository-root inventory cannot descend into their test environments.
- **Python:** run it only as `agents.md` and `~/.claude/shared/core.md` allow.
- **Test venvs:** create them inside the worktree, so they disappear with it, and never in the main checkout. Use the interpreter in the Test Interpreters table.
- **Temporary files:** use `mktemp -d` under `$TMPDIR`. Remove only this run's owned scratch directories with `rm -r -- "$scratch_dir"`, retaining the variable identifying each directory. For `tax2` acceptance, follow its `agents.md` Validation Matrix entry, including its location and cleanup command.
- **Existing cleanup targets:** use `/usr/bin/trash` for pre-existing venvs and obsolete deployed files. See Home Residue Cleanup Record before any further home cleanup.
- **Public repository:** follow `agents.md` Public repository: no sensitive data. Never read private exports or the contents of `~/.apple-health-extract/project-dir`. Commit-time inspection is in Merge protocol.
- **Commits:** imperative subject, with a body saying what changed and why.
- **Deployment gate:** run the Deployment task from `main` only, with the owner's separate go-ahead.

### Launcher header

Use this template, replacing dependencies as each tool task directs. Keep the first line equal to `tools/check_uv_headers.py:CANONICAL_SHEBANG`.

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
```

For `reversible-skew` and `video-scenes`, use `requires-python = ">=3.12,<3.13"`, preserving the interpreter choice in their `setup.sh` files. Keep dependency declarations tied to the manifests in the Guard Prep launcher table; an exact dependency pin alone does not imply an interpreter cap.

### Commands

| Name | Command |
|---|---|
| Guard check | `uv run --no-python-downloads --script tools/check_uv_headers.py` |
| Guard tests | `uv run --no-project --no-python-downloads --with pytest pytest tools/tests/test_check_uv_headers.py -q -p no:cacheprovider` |
| Launcher run | Prefix with `UV_PYTHON_DOWNLOADS=never` |
| Pinned-interpreter check | `uv python find --no-python-downloads --script <launcher>`, which must report a 3.12 interpreter |

### Test Interpreters

Use these interpreter choices for the Guard consumer suites. They preserve the baseline recorded in the supplied prior review; that review does not establish that the suites pass on these interpreters.

| Project | Interpreter |
|---|---|
| `tax2`, `data_format_converter` | `/opt/homebrew/opt/python@3.12/bin/python3.12` |
| `benchmark-llm`, `cognitive_switchyard` | `/opt/homebrew/opt/python@3.14/bin/python3.14` |

**Guard consumer suites:** `tax2`, `benchmark-llm`, `cognitive_switchyard`, and `data_format_converter` once its launcher test exists. Run each full suite as its `agents.md` and README entries describe, under Worker cap.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Stdlib tools | Share one worktree | Stdlib Tools owns the listed directories as one reviewable migration |
| `data_format_converter` requirements | Keep one file | Use the Guard Prep launcher table's manifest policy |
| `tomli` | Remove | The new Python floor always has `tomllib`, so the fallback is dead code |
| `apple-health-extract/run.sh` | Keep, and call uv | Preserve `run.sh:resolve_project_dir`; installed targets are in Deployment |
| Deployment audit | No changes | Deployed tools keep their current deployment shape |
| Test venvs | Delete now, keep the test flow | Converting tests is a separate effort. See the Test Venv Retirement follow-up |
| `dloc` | Add no options | Its smoke test runs the tool itself |
| `tax2` acceptance | Defer to Integration | Explicit exception for Guard Prep's shared-guard edit; run acceptance after the final guard change |
| Interim audit drift | Accept until Deployment | See Schedule |

## Shared Files and Conflict Control

Tool tasks follow Own directory only. Shared ownership is defined here.

| File | Who edits it | How conflict is avoided |
|---|---|---|
| `tools/check_uv_headers.py` | Guard Prep, Integration | Follow Schedule |
| `tools/tests/test_check_uv_headers.py` | Guard Prep, Integration | Same |
| `agents.md` (`CLAUDE.md` is a symlink to it) | Integration | Final integration |
| `docs/projects.md`, `docs/local_deployment_sync.md` | Integration | Final integration |
| `.gitignore` | Nobody | Its entries for these tools protect private exports and stay |
| `tools/check_local_deployments.zsh` and its test | Nobody | See Decisions: Deployment audit |

## Schedule

| Phase | Tasks | Runs | Blocked by |
|---|---|---|---|
| 0 | Guard Prep, Venv Cleanup | Parallel | Nothing |
| 1 | Stdlib Tools, doc_linearizer, reversible-skew, data_format_converter | Parallel | Guard Prep merged |
| 2 | video-scenes, apple-health-extract | As tool-work slots free up | Guard Prep merged |
| 3 | Integration | Alone | All tool tasks merged |
| 4 | Deployment | Alone | Integration merged, Deployment gate satisfied |

- Venv Cleanup owns only the main-checkout inventory and its named home target. Follow Worktree placement.
- **Expected interim drift:** once a deployed tool merges, `zsh tools/check_local_deployments.zsh` reports it as drifted until Deployment runs. That applies to `de-abacus.py`, `dloc`, `worktree`, `apple-health-extract` and `video-scenes`. It is not a failure in those tasks.

### Merge protocol

Merge one branch at a time, in any order.

- [ ] Before committing, inspect the staged file list and diff for sensitive data.
- [ ] Rebase the branch on `main`. Rerun the task's own validation if the rebase changed anything in its directory.
- [ ] Run the Guard check. Expected: `check_uv_headers: OK`.
- [ ] Push, open a PR, and squash merge it.
- [ ] Remove the worktree and its branch, following Test venvs.

## Review Focus

- **Working directory.** Preserve caller-directory behavior in the Stdlib Tools smoke tests.
- **Paths with spaces.** Validate the quoted `abacus usage/de-abacus.py` path in Stdlib Tools.
- **Sibling imports.** Validate through `data_format_converter/tests/test_launcher.py` as proposed below.
- **Pinned interpreter.** Apply Pinned-interpreter check in the capped tool tasks.
- **`uv` missing.** Validate through the apple-health-extract wrapper tests.

---

### Task 1: Guard Prep

**Files:**
- Modify: `tools/check_uv_headers.py`
- Test: `tools/tests/test_check_uv_headers.py`

**Interfaces:**
- Produces: `PENDING_UV_MIGRATION: frozenset[str]`, and a `("stdlib", "", frozenset())` policy in `DEPENDENCY_MANIFESTS`.
- Integration removes `PENDING_UV_MIGRATION`.

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

- [ ] **Step 2: Run the Guard tests to verify they fail.** Expected: the new tests fail and the existing tests pass.

- [ ] **Step 3: Add `PENDING_UV_MIGRATION` and the `stdlib` policy to `tools/check_uv_headers.py`.**

  - `check_launcher`: for a path in `PENDING_UV_MIGRATION`, return `[]` if the file is missing or its first line is not `CANONICAL_SHEBANG`. A pending file that has the shebang gets every normal check.
  - `check_dependency_manifest`: return `[]` for a pending path whose file is missing. Handle `"stdlib"` before any manifest path is resolved.
  - `main`: on success, print `check_uv_headers: OK (<verified> launchers verified, <pending> pending)`, where `pending` counts only the launchers skipped on this run. Omit the pending clause when none are skipped.

- [ ] **Step 4: Register every launcher below** in `LAUNCHERS`, `DEPENDENCY_MANIFESTS` and `PENDING_UV_MIGRATION`:

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

- [ ] **Step 5: Run the Guard check and Guard tests.** Expected: the check prints OK with a pending clause, and all tests pass.

- [ ] **Step 6: Run the Guard consumer suites** in the worktree. In the PR, say that `tax2` acceptance is deferred to Integration.

- [ ] **Step 7: Commit and merge** through the merge protocol.

---

### Task 2: Venv Cleanup

This task changes no tracked files, so it needs no worktree, commit or review.

- [ ] **Step 1: List every venv.** Run `find . -name pyvenv.cfg -not -path '*/node_modules/*' -not -path './.claude/*'` from the repo root.

- [ ] **Step 2: Confirm nothing uses them.** Check `ps -axo pid,command` and `lsof` for processes, and `~/Library/LaunchAgents`, `crontab -l` and `~/.claude/settings.json` for references to these paths. Stop and report if one is in use.

- [ ] **Step 3: Trash every `.venv` in the Venv Cleanup inventory**, including the one at the repo root, plus `vid-compiler/venv`. Report any differently named environment not explicitly assigned here instead of deleting it.

  Before any later recreation, follow `agents.md`'s `colophon` validation entry and `~/.claude/shared/python-env.md`'s uv approval rules. Recreation of Colophon's and `docker/llm_proxy`'s environments is outside this plan.

- [ ] **Step 4: Confirm `transcription/venv` and the Deferred Venv Removal list in Deployment remain.**

- [ ] **Step 5: Trash `~/vid-compiler/venv`.** Check first that no file in `~/vid-compiler` outside that directory uses it. Then run `~/vid-compiler/video_compiler.py --help` with the Launcher run prefix. Expected: usage text.

---

### Task 3: Stdlib Tools

**Files:**
- Modify: `abacus usage/de-abacus.py`, `abacus usage/README.md`, `abacus usage/Operational_Guide.md`
- Modify: `anduril_steps/anduril_steps.py`, `anduril_steps/README.md`
- Modify: `dloc/dloc`, `dloc/README.md`
- Modify: `worktree-helper/worktree`, `worktree-helper/README.md`
- Modify: `md-json/md_converter.py`, `md-json/README.md`
- Delete: `md-json/setup.sh`
- Modify: `Claude_plugin_converter/to_gemini_cli/migrate_skills.py`, its `README.md` and `MIGRATION_GUIDE.md`

**Interfaces:**
- Consumes: the `stdlib` policy from Guard Prep.

- [ ] **Step 1: Replace the first line of `de-abacus.py`, `anduril_steps.py`, `dloc` and `worktree` with the Launcher header.** Keep any docstring or `from __future__` import after it, unchanged in order.

- [ ] **Step 2: Add the Launcher header above the first line of `md_converter.py` and `migrate_skills.py`, and make each executable** with `chmod +x`.

- [ ] **Step 3: Bump `VERSION` in `worktree-helper/worktree`** to the next patch release, as `agents.md` Release Versions requires.

- [ ] **Step 4: Update the READMEs.** Remove the venv setup steps and state the requirement as uv (`brew install uv`).

  - `abacus usage/README.md`: remove the venv block in Quick start; update the activation reference in `Operational_Guide.md` to point to the README's uv prerequisite.
  - `anduril_steps/README.md`: remove the venv block and the form that invokes it through `python3`.
  - `dloc/README.md`: remove the venv block and the Python version requirement.
  - `worktree-helper/README.md`: add the uv requirement, and update the version named in the `--orphan` note.
  - `md-json/README.md`: remove the setup section, delete `md-json/setup.sh`, and change usage to `./md_converter.py`.
  - `Claude_plugin_converter/to_gemini_cli/README.md` and `MIGRATION_GUIDE.md`: change usage to invoke the script directly and update interpreter prerequisites to match its header. In the README, document the project-venv unit-test procedure in Run the converter's unit tests below, adapting only venv creation for portable developer instructions. Integration adds the agent-specific setup command to the Validation Matrix.

- [ ] **Step 5: Run the Guard check.** Expected: OK, with fewer pending.

- [ ] **Step 6: Smoke-test each tool** with the Launcher run prefix, in `mktemp -d` where a fixture is needed:

  | Run | Expected |
  |---|---|
  | `"$PWD/abacus usage/de-abacus.py" --help` | Usage text |
  | `anduril_steps/anduril_steps.py --help` | Usage text |
  | From a different git repo, `<worktree>/dloc/dloc` | Output matches `dloc/dloc:print_table` for that synthetic repo's commit statistics |
  | `worktree-helper/worktree --version` | The bumped `VERSION` |
  | `worktree-helper/worktree --list` | This repo's worktrees |
  | From the temp directory, `<worktree>/md-json/md_converter.py --input synthetic.json --output out.csv`, with an invented export in the shape `md-json/README.md` describes | `out.csv` written in the temp directory |
  | From an empty temp workspace, `<worktree>/Claude_plugin_converter/to_gemini_cli/migrate_skills.py <category>`, with a synthetic category shaped as `tests/test_migrate_skills.py` builds it | Output written under that workspace's `.gemini/` |

- [ ] **Step 7: Run the converter's unit tests.** In the worktree's `Claude_plugin_converter/to_gemini_cli`, create an absent `.venv` with `/opt/homebrew/bin/python3 -m venv .venv`, then run `.venv/bin/python -m unittest discover -s tests -v`. Expected: all pass.

- [ ] **Step 8: Commit and merge** through the merge protocol.

---

### Task 4: doc_linearizer

**Files:**
- Modify: `doc_linearizer/linearize.py`, `doc_linearizer/README.md`
- Create: `doc_linearizer/tests/test_launcher.sh`

**Interfaces:**
- Consumes: its Guard Prep registration. `doc_linearizer/requirements.txt` stays as the guard's manifest.

- [ ] **Step 1: Add the Launcher header** above the first line, declaring every entry in `requirements.txt`, and make the file executable.

- [ ] **Step 2: Update `doc_linearizer/README.md`.** Replace Setup with the uv requirement, and change usage to `./linearize.py`.

- [ ] **Step 3: Run the Guard check.** Expected: OK.

- [ ] **Step 4: Add and run `tests/test_launcher.sh`.** The test owns a fresh temporary directory, builds a synthetic site according to `linearize.py:main` and `linearize.py:process_page`, creates the output parent, invokes the executable through uv from another directory, and asserts the output preserves the fixture's heading marker. Keep the fixture and assertions in this test rather than prose; a named test is needed for repeatable validation without discarded scratch files. Use the Launcher run prefix and Temporary files cleanup. Run `bash tests/test_launcher.sh` from `doc_linearizer/`. Expected: exit 0 with the output assertion satisfied.

- [ ] **Step 5: Commit and merge** through the merge protocol.

---

### Task 5: reversible-skew

**Files:**
- Modify: `reversible-skew/rs.py`, `reversible-skew/rs-big.py`, `reversible-skew/README.md`
- Delete: `reversible-skew/setup.sh`

**Interfaces:**
- Consumes: its Guard Prep registration. `reversible-skew/requirements.txt` stays as the guard's manifest.

- [ ] **Step 1: Retain a pre-change stream and its original synthetic input.** Before editing anything, use the main checkout's `reversible-skew/venv/bin/python` to run `rs.py transform`. Keep the artifacts in owned temporary space until compatibility validation finishes, then apply Temporary files cleanup.

- [ ] **Step 2: Replace the first line of `rs.py` and `rs-big.py` with the capped Launcher header**, declaring the `pydivsufsort` pin in `rs.py` and every entry in `requirements.txt` in `rs-big.py`.

- [ ] **Step 3: Update `reversible-skew/README.md`.** Replace Setup with the uv prerequisite, delete `setup.sh` and its file entry, and change usage to `./rs.py` and `./rs-big.py`. Keep the note on `rs.py`'s slow fallback, but say the launcher installs `pydivsufsort`. Preserve the compatibility-validation requirements and update any interpreter invocation to use the launchers.

- [ ] **Step 4: Run the Guard check.** Expected: OK.

- [ ] **Step 5: Run the Pinned-interpreter check on `rs.py` and `rs-big.py`.**

- [ ] **Step 6: Run the complete compatibility validation** in the `reversible-skew/README.md` paragraph beginning "After code or dependency updates", through the launchers, using the retained pre-change stream and original input. Expected: every check it names passes.

- [ ] **Step 7: Commit and merge** through the merge protocol.

---

### Task 6: data_format_converter

**Files:**
- Modify: `data_format_converter/src/data_convert.py`, `data_format_converter/src/converters/toml_conv.py`, `data_format_converter/requirements.txt`, `data_format_converter/README.md`
- Modify: `data_format_converter/tests/test_cli.py`, `data_format_converter/tests/test_cli_roundtrip.py`, `data_format_converter/tests/test_toml_conv.py`
- Create: `data_format_converter/tests/test_launcher.py`

**Interfaces:**
- Consumes: `extract_pep723` and `missing_declared_imports` from `tools/check_uv_headers.py`.
- Produces: a new consumer of that guard, so it joins the Guard consumer suites.

- [ ] **Step 1: Write the failing tests** in `data_format_converter/tests/test_launcher.py`. Use `tools/check_uv_headers.py:missing_declared_imports` for the converter graph, and invoke uv explicitly for launcher acceptance. These proposed tests define the new coverage:

  ```python
  def test_header_declares_every_converter_import():
      text = LAUNCHER.read_text(encoding="utf-8")
      deps = extract_pep723(text)["dependencies"]
      for module in [LAUNCHER, *CONVERTERS.glob("*.py")]:
          assert missing_declared_imports(module, module.read_text(encoding="utf-8"), deps) == []

  def test_launcher_converts_through_uv_from_another_directory(tmp_path):
      source = tmp_path / "in.json"
      output = tmp_path / "out.toml"
      source.write_text('{"synthetic": 1}', encoding="utf-8")
      result = subprocess.run(
          ["uv", "run", "--no-python-downloads", "--script", str(LAUNCHER),
           "--input", str(source), "--to", "toml", "--output", str(output)],
          cwd=tmp_path, capture_output=True, text=True,
      )
      assert result.returncode == 0, result.stderr
      assert tomllib.loads(output.read_text(encoding="utf-8")) == {"synthetic": 1}
  ```

- [ ] **Step 2: Run them to verify they fail.** Create `.venv` in the worktree, install `requirements.txt`, then run `.venv/bin/python -m pytest tests/test_launcher.py`. Expected: FAIL, because `data_convert.py` has no header.

- [ ] **Step 3: Add the Launcher header to `src/data_convert.py`**, declaring every entry in `requirements.txt` except `pytest` and `tomli`, and make it executable.

- [ ] **Step 4: Remove `tomli`.** Delete it from `requirements.txt`. Replace its `try`/`except` fallback with `import tomllib` in `src/converters/toml_conv.py`, `tests/test_cli.py`, `tests/test_cli_roundtrip.py` and `tests/test_toml_conv.py`. Confirm with `rg tomli data_format_converter --glob '!node_modules'`. Expected: no matches beyond `tomli_w` and `tomli-w`.

- [ ] **Step 5: Update `data_format_converter/README.md`.** Replace CLI Setup with the uv prerequisite and change usage to `./src/data_convert.py`. Move the dev-venv setup into Testing, using the data_format_converter entry in Test Interpreters; retain its full suite commands.

- [ ] **Step 6: Run the Guard check and the full suite** as `agents.md` describes for this project. Expected: all pass.

- [ ] **Step 7: Commit and merge** through the merge protocol.

---

### Task 7: video-scenes

**Files:**
- Create: `video-scenes/video-scenes`
- Modify: `video-scenes/README.md`
- Delete: `video-scenes/setup.sh`

**Interfaces:**
- Consumes: its Guard Prep registration. `video-scenes/requirements.txt` stays as the guard's manifest.

- [ ] **Step 1: Create the executable `video-scenes/video-scenes`** with the capped Launcher header, declaring every entry in `requirements.txt`. The body imports `main` from `scenedetect.__main__` and calls `sys.exit(main())`.

- [ ] **Step 2: Update `video-scenes/README.md`.** Delete `setup.sh`, replace Requirements and Setup with uv and `ffmpeg`, and change every `scenedetect` and `venv/bin/scenedetect` command to `./video-scenes`, including Tips and Validation.

- [ ] **Step 3: Run the Guard check.** Expected: OK.

- [ ] **Step 4: Run the Pinned-interpreter check.**

- [ ] **Step 5: Run the README's Validation check** through the launcher, in `mktemp -d`. Expected: its stated acceptance result.

- [ ] **Step 6: Commit and merge** through the merge protocol.

---

### Task 8: apple-health-extract

**Files:**
- Modify: `apple-health-extract/extract_workout_stats.py`, `apple-health-extract/exercise_bouts.py`, `apple-health-extract/run.sh`, `apple-health-extract/README.md`
- Test: `apple-health-extract/tests/test_run_wrapper.sh`
- Create: `apple-health-extract/tests/test_extraction.sh`
- Delete: `apple-health-extract/setup.sh`

**Interfaces:**
- Consumes: its Guard Prep registration. `requirements-dev.txt` stays as the guard's manifest.
- `run.sh` keeps its existing options and project-directory resolution order.

- [ ] **Step 1: Update `tests/test_run_wrapper.sh` first.** Replace the fake `venv/bin/python` with a fake `uv` on `PATH` that records its arguments. The wrapper's behaviour is changing, so this is a real requirement change rather than a test edited to pass. Assert that:

  - `run.sh` invokes `uv run --no-python-downloads --script <project>/extract_workout_stats.py`
  - extractor arguments pass through
  - the working directory is the project directory
  - with no `uv` on `PATH`, `run.sh` and `run.sh --check` exit non-zero with a message containing `brew install uv`

- [ ] **Step 2: Run it to verify it fails.** Run `bash tests/test_run_wrapper.sh`. Expected: FAIL.

- [ ] **Step 3: Update `run.sh`.** In `resolve_project_dir`, replace the `venv/bin/python` check with a `command -v uv` check. Replace the final `exec` with `exec uv run --no-python-downloads --script "$PROJECT_DIR/$EXPECTED_SCRIPT" "$@"`. Update the usage text.

- [ ] **Step 4: Add the Launcher header to `extract_workout_stats.py` and `exercise_bouts.py`**, declaring every entry in `requirements.txt`, and make them executable.

- [ ] **Step 5: Update `apple-health-extract/README.md`.** Delete `setup.sh`, replace setup with uv, and change Python invocations to the executable launchers. Retain the private operational-copy procedure with its tracked-file list adjusted for the deletion. Document `bash tests/test_run_wrapper.sh` and `bash tests/test_extraction.sh`. Check `rg -n -i 'setup\.sh|venv|virtual env' apple-health-extract/README.md`. Expected: no matches.

- [ ] **Step 6: Run the Guard check and the wrapper test.** Expected: each passes.

- [ ] **Step 7: Add and run `tests/test_extraction.sh`.** Give it an optional absolute project-directory argument, defaulting to its source project, so Deployment can exercise installed scripts with the same test. It creates an unmistakably synthetic `export.xml` in a fresh owned temporary directory, invokes the project's extraction launchers there with the Launcher run prefix, asserts the expected workout and incidental-bout CSV rows and heart-rate detail, then applies Temporary files cleanup. Keep the complete fixture and exact assertions in this test; a reusable test is needed because task scratch files do not survive until Deployment. Run `bash tests/test_extraction.sh` from `apple-health-extract/`. Expected: exit 0 with every CSV assertion satisfied.

- [ ] **Step 8: Commit and merge** through the merge protocol.

---

### Task 9: Integration

**Files:**
- Modify: `tools/check_uv_headers.py`, `tools/tests/test_check_uv_headers.py`
- Modify: `agents.md`, `docs/projects.md`, `docs/local_deployment_sync.md`

**Interfaces:**
- Produces: `NON_UV_PYTHON_ALLOWLIST: tuple[str, ...]` of repo-relative paths and directory prefixes, and `read_first_line(path: Path) -> str | None`, which returns `None` on `OSError` or `UnicodeDecodeError`.

- [ ] **Step 1: Write the failing test.** `test_unlisted_python_shebang_is_rejected` follows the synthetic pattern of `test_unregistered_uv_launcher_is_discovered_and_rejected`, and asserts that `guard.main() == 1` with `not a uv launcher` in the output. Add a case proving a binary file is skipped.

- [ ] **Step 2: Add the check.** Extract `read_first_line` from `discover_launchers` and use it in discovery and the new check. In `main`, fail any regular file from `git_repository_files()` whose first line matches `^#!.*python` unless it matches this allowlist:

  ```python
  NON_UV_PYTHON_ALLOWLIST = (
      "Calculation tools/backtest/data/compile_market_data.py",
      "benchmark-llm/examples/shared/demo_prompt_executor.py",
      "coding/design_orch/scripts/codex_json_progress.py",
      "cognitive_switchyard/cognitive_switchyard/scripts/plan_commit_msg.py",
      "cognitive_switchyard/scripts/codex_json_progress.py",
      "cognitive_switchyard/tests/fixtures/workers/",
      "docker/llm_collector/snapshots/rollup_snapshots.py",
      "harscope/tests/verify_redaction.py",
      "model_sentinel/__main__.py",
      "model_sentinel/model-sentinel",
  )
  ```

  See No-Shebang Detection for the deferred detection scope.

- [ ] **Step 3: Remove `PENDING_UV_MIGRATION`** with its branches and the tests that exercise it. Keep the `stdlib` policy and its tests.

- [ ] **Step 4: Update `agents.md`.**

  - In the setup-script sentence under "Python as an agent", remove every tool that no longer has a `setup.sh`.
  - In the approval list, remove the `Claude_plugin_converter` example.
  - In the Validation Matrix, add entries from each tool task's validation steps, including the project-venv setup and unit test commands from Stdlib Tools and the new shell smoke tests. Keep `data_format_converter`'s `.venv` commands.
  - Add an explicit shared-header-guard entry to the Validation Matrix with the Commands table's Guard check and Guard tests, plus the Guard consumer suites list and Test Interpreters choices. Require the consumers when guard code changes; include `data_format_converter`'s full suite with its new launcher test.

- [ ] **Step 5: Update `docs/projects.md`.** Change the `video-scenes` delivery type to CLI, and describe the launcher.

- [ ] **Step 6: Update `docs/local_deployment_sync.md`.** In the local-only list, remove "and its project venv" from the Apple Health line.

- [ ] **Step 7: Run everything.** Follow Worker cap and the updated `agents.md` entries:

  - The Guard check. Expected: OK, with no pending clause.
  - The Guard tests. Expected: all pass.
  - The Guard consumer suites. Expected: all pass.
  - `tax2`'s launcher and acceptance checks in its `agents.md` entry. Expected: all pass.

- [ ] **Step 8: Commit and merge** through the merge protocol.

---

### Task 10: Deployment

Apply Deployment gate. Follow `docs/local_deployment_sync.md` Non-destructive rules and its direct-copy/home-project procedures.

| Installed copy | Source | Action |
|---|---|---|
| `~/Library/Scripts/de-abacus.py` | `abacus usage/de-abacus.py` | Byte-identical copy |
| `~/Library/Scripts/dloc` | `dloc/dloc` | Byte-identical copy |
| `~/Library/Scripts/worktree` | `worktree-helper/worktree` | Byte-identical copy |
| `~/Library/Scripts/apple-health-extract` | `apple-health-extract/run.sh` | Copy. The audit does not track this one |
| `~/apple-health-extract` | `apple-health-extract` | Home-project copy |
| `~/video-scenes` | `video-scenes` | Home-project copy |

- [ ] **Step 1: Establish the Apple Health wrapper's actual target before changing files.** Run `~/Library/Scripts/apple-health-extract --check` in the intended caller environment, without reading its private configuration. Compare the reported resolved directory with the canonical path of the home-project destination in the Deployment table. If they differ, stop this deployment before copying or removing environments and obtain the owner's choice: authorize deployment to the actual operational copy, or separately authorize correcting the configuration. Do not set an environment override merely to force this check to pass. Keep path evidence private, outside the repository.

- [ ] **Step 2: Copy the `~/Library/Scripts` rows.** Expected: `cmp` is clean, and `~/Library/Scripts/worktree --version` matches the source `VERSION`.

- [ ] **Step 3: Copy the home-project rows** with the documented pattern. Then trash the obsolete `setup.sh` in each installed home project.

- [ ] **Step 4: Verify each installed copy before removing environments.** Use the Launcher run prefix.

  - Re-run the Apple Health wrapper target check above in the same caller environment. Expected: the resolved path still equals the verified deployment destination.
  - From the source `apple-health-extract` directory, run `bash tests/test_extraction.sh "$resolved_project_dir"`, where `resolved_project_dir` is the absolute directory verified by that check. Follow the test contract in the apple-health-extract task. Expected: exit 0.
  - `~/video-scenes/video-scenes version`. Expected: version output.

- [ ] **Step 5: Run the deployment audit** with `zsh tools/check_local_deployments.zsh`. Expected: no drift for any tool in this plan. Report any other drift rather than fixing it here.

- [ ] **Step 6: Trash the Deferred Venv Removal list** after installed-copy verification:

  - `~/apple-health-extract/venv`
  - `~/video-scenes/venv`
  - `apple-health-extract/venv`
  - `reversible-skew/venv`
  - `video-scenes/venv`

- [ ] **Step 7: Re-run the Venv Cleanup inventory command.** Compare with that task's recorded inventory; report retained, removed and newly discovered environments by path, including any test venvs recreated since. Report the released `worktree` version.

---

## Home Residue Cleanup Record

The owner's supplied prior review reports a separate cleanup session on 2026-10-30. That session's itemized action record is not available here, so this plan does not certify which candidates were removed or retained. No task depends on that cleanup; do not repeat the old candidate deletions from this plan.

**Recovery before emptying Trash:** the supplied review reports that `~/.cache/codex-runtimes` was trashed while recently in use. If Codex misbehaves, restore that cache first. Do not treat this plan as clearance to empty Trash.

**Retained and deferred candidates:** recover the cleanup session's action record before deciding whether design originals, recovery directories, repair snapshots, legacy Video Compiler files, Codex worktrees or caches still need attention. Their disposition remains unverified here. Deployment owns the environments in Deferred Venv Removal; the transcription exclusion remains in Global Constraints.

**Protected paths for any later backup scan or cleanup:** exclude `~/.local` (credential-bearing application data), `~/.codex` sessions and managed state, `~/.claude`, `~/.config`, `~/.docker`, `~/.gemini`, `~/.lmstudio`, `~/.venvs`, `~/.t3`, and tool runtime homes such as `~/.colophon`, `~/.model_sentinel`, `~/.storage_monitor`, `~/.tax2`, `~/.routerview`, `~/.benchmark_llm`, `~/.cognitive_switchyard` and `~/.apple-health-extract`. Do not inspect their contents to classify backups. Worktree removal must use its owning manager and confirmed Git state, under separate authorization.

**Rollback retention decision:** keep the newest two rollback copies per tool in `~/.utilities-deploy-backups`. This is a manual policy; enforcement is deferred to Residue Prevention. Before pruning, use the cleanup action record and deployment recovery requirements to identify copies safe to remove, without printing backup contents.

---

## Follow-ups (Discovery Briefs)

These are not ready to implement. Each is a starting point for an agent to investigate and produce its own implementation plan.

### Test Venv Retirement

**Goal:** Stop test venvs from coming back after Venv Cleanup, without losing reproducible test runs or the safety of the Python rules.

**Policy sources:** `agents.md` Python as an agent and Validation Matrix; `~/.claude/shared/python-env.md` Which interpreter to use and Mechanics. Evaluate alternatives against those policies; no test-run or disk-saving claim is established by this brief.

**Where to look:** start with `rg -l '\.venv' --glob '!*.md'`, `git ls-files | rg 'requirements-(dev|test)'`, and `rg -l '\.venv/bin' -g 'README.md'`.

Inspect these sources rather than inferring runtime requirements from prose:

- Project README Testing sections
- `colophon/tests/run-pytest.sh` and `colophon/tools/gen_unicode.py`
- `git-multirepo-dashboard/tests/`
- `cognitive_switchyard/tests/conftest.py` and `cognitive_switchyard/cognitive_switchyard/builtin_packs/` verify scripts
- `coding/task_orch/orchestrate.sh`
- `Calculation tools/backtest/tests/helpers/runner.cjs`
- `docker/llm_collector/README.md` and its `agents.md` validation entry

**External policy sources to assess before proposing changes:**

- `~/.claude/shared/core.md`: Python section
- `~/.claude/shared/python-env.md`
- `~/.claude/shared/python-venv-guard.sh`, `python-classifier.awk` and `audit-python-usage.sh`. Check that the classifier permits the chosen form.
- PKM entries #3 (environment policy) and #249 (slim instructions)

**Questions to answer:**

1. What is the replacement: ephemeral `uv run --with-requirements`, one shared script per project, or a Make target? Does it work for projects that need editable installs (`pip install -e`)?
2. How long is a cold run and a warm run, compared with a `.venv`, on one small and one browser project?
3. What is the real disk result? Measure `~/.cache/uv` after running all suites, and compare with the deleted venvs. If the cache holds the same bytes, is the benefit tidiness rather than space, and is that enough?
4. Does `pytest-playwright` behave in an ephemeral environment, and do tests that spawn `sys.executable` still find their packages?
5. Are versions reproducible from each project's tracked dev requirements? Does losing a stable venv make failures harder to reproduce?
6. How do concurrent runs across worktrees behave against the shared uv cache?
7. Which projects should stay exceptions? Inspect the Colophon and Market Atlas sources listed above before recommending them.

**Suggested pilots:** `div_conv` (pytest only), `jtree` (browser), `benchmark-llm` (uv project).

**Done when:** There is a written recommendation with measured numbers, a list of exceptions, and the rule changes needed, and the owner has chosen an approach. An implementation plan follows from that.

### Transcription Migration

**Goal:** Decide how `transcription` moves to uv.

**Sources to inspect:** `transcription/README.md`, `app.py`, `transcribe.py`, `ui.sh`, `setup.sh`, `requirements.txt`, `requirements-optional.txt`; `agents.md` Streamlit apps; `tools/check_uv_headers.py:missing_declared_imports` and `FORBIDDEN_PATTERNS`; `docs/local_deployment_sync.md` transcription entry. Apply Public repository rules to state-file investigation.

**Questions to answer:**

1. How should a launcher start `streamlit run` under the guard's bootstrap restrictions? Can it call `streamlit.web.cli` or a child process, and does Ctrl-C still work?
2. Should the optional packages become required, or does the guard need an optional-dependency policy?
3. Should state move to `~/.transcription/`, and how is existing state migrated without an automatic import?
4. Is one launcher with two modes better than two launchers?
5. Should the legacy wrappers be deleted?
6. What is the torch and whisper footprint in the uv cache, and does a cold start stay acceptable? Are Whisper model downloads unaffected?

**Done when:** The owner has chosen answers to the launcher, dependency and state questions, and an implementation plan can be written.

### No-Shebang Detection

**Goal:** Integration's guard check sees only shebangs, so a new Python tool with no shebang would pass.

**Questions to answer:** Can a tool be detected from `if __name__ == "__main__":` with `argparse`, a `docs/projects.md` entry, or a required registry row? Which detection gives few false positives on test helpers and library modules? Should the guard also scan sibling modules in general, as the data_format_converter task's test does for one project?

**Done when:** There is a chosen detection rule and a list of its exceptions.

### Residue Prevention

**Goal:** Decide how to enforce temporary-evidence cleanup and the Rollback retention decision in Home Residue Cleanup Record.

**Sources to inspect:** `agents.md`'s `tax2` entry, `docs/lessons_learned.md` "Put acceptance homes in private OS temporary space", `tools/check_no_temp_leaks.sh`, and `docs/local_deployment_sync.md` backup/recovery procedures. Resolve location policy against these sources; this plan's implementation uses Temporary files.

**Questions to answer:**

1. Why did agents choose `$HOME`? Possible reasons include sandbox limits on `$TMPDIR` and a need for evidence to survive across sessions.
2. Should there be one sanctioned evidence location, with a retention rule?
3. Should `core.md` or `agents.md` carry the rule, and should `tools/check_no_temp_leaks.sh` also watch `$HOME`?
4. Should the deployers enforce the Rollback retention decision, or should enforcement stay manual?

**Done when:** The owner has agreed location and retention policies and the referenced instructions and enforcement tools implement them consistently.
