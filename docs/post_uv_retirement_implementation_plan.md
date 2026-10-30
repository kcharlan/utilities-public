# Post-uv-Retirement Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement the Ready tasks, each in its own git worktree. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish what the uv runtime migration left open: clear the Apple Health warning and the dependency advisories, make the guard catch more unmanaged Python tools, detect home residue, and reach owner decisions on test venvs and `transcription`.

**Architecture:** Ready tasks merge within Schedule. Gated steps need the owner's approval for a named action. Decision Tasks defines the handoff for investigations.

**Tech Stack:** zsh and bash, Python with uv, pytest, Playwright, npm, Docker Compose.

**Spec:** The owner's request to pick up the remaining pieces, plus Follow-ups in `docs/retire_venvs_for_uv_implementation_plan.md`. This plan replaces that Follow-ups section. Approval of this plan does not authorize implementation, deployment or any Gated step.

## Execution record (2026-10-30)

The owner separately requested execution and approved the named deployment gates,
then approved additional gates while away. Work used independent managed
worktrees, serial integration, task reviews, and at most one Playwright suite.

| Task | Result |
| --- | --- |
| Apple Health warning | [PR 104](https://github.com/kcharlan/utilities-public/pull/104) merged; warning reproduced before the fix; both synthetic shell suites passed. Installed files matched merged source and the installed synthetic extraction passed. |
| Test lockfiles | [PR 105](https://github.com/kcharlan/utilities-public/pull/105) merged; all three audits clean; Playwright remained 1.64.1. Converter: 113 Python and 6 browser tests; calculators: 179 Node and 118 browser tests; multibody: 10 browser tests. |
| Entry-point detection | [PR 109](https://github.com/kcharlan/utilities-public/pull/109) merged; exact allowlist retained. Combined-tree validation: guard 56 tests and 32 launchers, Tax2 432 tests plus offline/download acceptance, converter 113 Python and 6 browser tests, benchmark 157 tests, Cognitive Switchyard 489 tests. |
| Home residue audit | [PR 107](https://github.com/kcharlan/utilities-public/pull/107) merged; synthetic cases, 124 installer lifecycle tests, 17 static audit tests and the fleet shell suite passed. Real-home name/age audit reported OK. [PR 108](https://github.com/kcharlan/utilities-public/pull/108) corrected a scratch-variable name without changing behavior; its covering suite and guard passed. |
| Webserver locks | [PR 106](https://github.com/kcharlan/utilities-public/pull/106) merged; Node and Python audits clean, three disposable builds passed, routing 5/5 and propagation 20/20 passed. Authorized deployment completed; all four services healthy. Installed Nginx syntax, API semantics, file browser, configuration UI, static-root bytes and calculator cache headers passed. |
| Test venv decision | [PR 110](https://github.com/kcharlan/utilities-public/pull/110) merged the [decision record](test_venv_retirement_decision.md). Both approaches passed 115 div_conv tests and 160 jtree tests; the approved project-mode benchmark pilot passed 157. Cross-worktree shared-cache runs passed 115 each. Recommendation: retain project venvs by default, with project-specific uv alternatives only after validation. Owner choice remains open. |
| Transcription decision | [PR 111](https://github.com/kcharlan/utilities-public/pull/111) merged the [decision record](transcription_uv_decision.md). Both dependency graphs passed HTTP/health startup and clean SIGINT teardown; separate AppTest runs executed both interfaces and synthetic resets. Known deployed wrappers were checked. Recommendation: one capped two-mode launcher and explicit runtime paths. No spike or migration merged; owner choice remains open. |

The Cognitive Switchyard warning is `PytestRemovedIn10Warning` from
pytest-playwright 0.10.0's session-scoped `_BaseUrlFallback.base_url` fixture
(`pytest_playwright/pytest_playwright.py:830`). Its separate investigation remains
outside this plan; no warning suppression was introduced.

The first installed fleet audit failed with `App source drift` for Anker Charge
Monitor. The admitted source inventory differed only in a documentation-link
comment. Its full native suite passed; reinstalling the existing 0.4.1 release
refreshed provenance, and source, installed metadata and receipt remained 0.4.1.
The direct native audit and subsequent whole-fleet audit passed. The running app
was not restarted; vault, cloud, GUI and physical-device checks were not performed.

Execution choices: the explicit parallel schedule took precedence over the
skill's serial-worker default; evidence stayed in private OS temporary space;
the request to execute authorized the plan's commit/PR/merge workflow while
separate deployment gates were preserved until approved. The costs if these
interpretations were wrong would be integration rework, unavailable deleted
scratch evidence, or published workflow changes, respectively.

## Global Constraints

- **Worker cap:** max 4 worktrees at once, with a reviewer sharing its implementer's slot. Max 1 Playwright suite at a time.
- **Worktrees:** create them outside the main checkout. Test venvs go inside the worktree and disappear with it.
- **Python and uv:** run them only as `agents.md` and `~/.claude/shared/python-env.md` allow.
- **Temporary files:** follow `agents.md` Quality and Consistency.
- **Public repository:** follow `agents.md` Public repository: no sensitive data. Use synthetic fixtures only. Never read private exports, Transcription's state files, or the contents of rollback backups.
- **Home scans:** report entry names and ages only. Never open what they find.
- **Existing files outside a worktree:** remove them with `/usr/bin/trash`, and never empty the Trash.
- **Deployment:** from `main` only, following `docs/local_deployment_sync.md`, as a Gated step.
- **Commits:** follow `agents.md` Git and Public repository requirements.

## Schedule

| Phase | Tasks | Runs | Blocked by |
|---|---|---|---|
| 0 | Commit this plan to `main` | Alone | Owner's go-ahead. Worktrees need it, and Home Residue Audit links to it |
| 1 | Apple Health Warning, Test Lockfile Refresh, Entry Point Detection, Home Residue Audit | Within Worker cap | Plan committed to `main`; Entry Point Detection starts after Test Lockfile Refresh finishes |
| 2 | Apple Health Warning's Gated step, Webserver Lockfile Refresh | One at a time | Plan committed to `main`; for Apple Health, its task merged |
| 3 | Test Venv Decision, Transcription Decision | Parallel | Plan committed to `main` and Ready tasks merged, to keep worker slots free |

## Shared Files

| File | Who edits it | How conflict is avoided |
|---|---|---|
| `tools/check_uv_headers.py` and its test | Entry Point Detection | Within this plan, no other task edits it |
| `agents.md` | Entry Point Detection, Home Residue Audit | Different lines. Merge one at a time and rebase |
| `docs/todo.md` | Home Residue Audit | `docs/implementation_plan_retirement_implementation_plan.md` also adds to it. Rebase on `main` first |

**Merge protocol:** rebase on `main`, rerun the task's validation if the rebase changed its directory, run the `agents.md` fleet drift guard, push, open a PR, squash merge, then remove the worktree and branch.

## Not in This Plan

- **`cognitive_switchyard` pytest warning:** when Entry Point Detection next runs that suite, capture the warning's source and report it. Warning remediation needs a separate investigation.
- **Further home scans:** follow Home Residue Cleanup Record in `docs/retire_venvs_for_uv_implementation_plan.md`, including its protected-paths and action-record requirements.

## Ready Tasks

### Task 1: Apple Health Warning

**Files:**
- Modify: `apple-health-extract/exercise_bouts.py`
- Test: `apple-health-extract/tests/test_extraction.sh`

- [x] **Step 1: Make the test fail on the warning.** Where `tests/test_extraction.sh` runs `exercise_bouts.py`, send its stderr to `bouts.stderr` in the scratch directory, print that file if the script fails, then fail if it contains `Warning`.

- [x] **Step 2: Run it to verify it fails.** Run `bash tests/test_extraction.sh` from `apple-health-extract/`. Expected: FAIL, naming `Pandas4Warning`.

- [x] **Step 3: Replace the `bouts_df.drop` call** with `bouts_df = bouts_df.drop(columns=['interval'])`.

- [x] **Step 4: Run every check in the `agents.md` Apple Health entry.** Expected: all pass, with CSV output unchanged.

- [x] **Step 5: Commit and merge** through the merge protocol.

- [x] **Step 6 (Gated): Deploy.** Follow `docs/local_deployment_sync.md` for `~/apple-health-extract`, and remove the stale `~/apple-health-extract/__pycache__`. Run `bash tests/test_extraction.sh "$HOME/apple-health-extract"` from the source directory, then `zsh tools/check_local_deployments.zsh`. Expected: each command passes.

---

### Task 2: Test Lockfile Refresh

Use each listed project's `package.json` and `npm audit --package-lock-only` as the dependency and advisory sources at execution time.

**Files:**
- Modify: `data_format_converter/package-lock.json`, `Calculation tools/package-lock.json`, `web_games/multibody_sim/package-lock.json`

- [x] **Step 1: Refresh each lock.** In each project directory, run `npm audit fix --package-lock-only --ignore-scripts`.

- [x] **Step 2: Confirm the scope.** `git diff --stat` lists only the Files entries. Confirm each project's resolved Playwright version is unchanged. In each project, `npm audit --package-lock-only` reports no vulnerabilities. If remediation requires changing a manifest or Playwright, report that scope decision before proceeding.

- [x] **Step 3: Run each project's complete suite**, after `npm ci`. Follow the full `agents.md` entries for `data_format_converter` (including Python tests) and `web_games/multibody_sim`, and run `npm test` from `Calculation tools`. Expected: all pass, and `http-server` still serves each browser suite.

- [x] **Step 4: Commit and merge** through the merge protocol.

---

### Task 3: Entry Point Detection

Extend the discovery in `tools/check_uv_headers.py:main` with the signal defined under Add the check to `main`, rather than introducing a tool registry.

**Files:**
- Modify: `tools/check_uv_headers.py`, `agents.md`
- Test: `tools/tests/test_check_uv_headers.py`

**Interfaces:**
- Produces: `NON_UV_ENTRYPOINT_ALLOWLIST: tuple[str, ...]`, `is_test_path(relative: str) -> bool`, and `is_allowlisted(relative: str, allowlist: tuple[str, ...]) -> bool`, extracted from the matching logic in `main`.

- [x] **Step 1: Write the failing tests** in the style of `test_unlisted_python_shebang_is_rejected`. These are outlines; each test builds the files its comment names:

  ```python
  # synthetic_tool.py: no shebang, `if __name__ == "__main__":` at column 0
  def test_unlisted_entrypoint_is_rejected(tmp_path, monkeypatch, capsys) -> None:
      assert guard.main() == 1
      assert "Python entry point is not a uv launcher" in capsys.readouterr().out

  # tests/helper.py, test_probe.py and conftest.py, each with a main guard
  def test_entrypoint_under_test_paths_is_skipped(tmp_path, monkeypatch) -> None:
      assert guard.main() == 0

  # a .py file with no main guard
  def test_module_without_main_guard_is_skipped(tmp_path, monkeypatch) -> None:
      assert guard.main() == 0

  # monkeypatch NON_UV_ENTRYPOINT_ALLOWLIST with one file and one "dir/" prefix
  def test_allowlisted_entrypoint_is_skipped(tmp_path, monkeypatch) -> None:
      assert guard.main() == 0

  # a .py file holding undecodable bytes
  def test_binary_python_file_is_skipped(tmp_path, monkeypatch) -> None:
      assert guard.main() == 0
  ```

- [x] **Step 2: Run the Guard tests** from the `agents.md` Shared uv header guard entry. Expected: the new tests fail.

- [x] **Step 3: Add the check to `main`**, in the existing `git_repository_files()` loop. Fail a regular `.py` file when it has no shebang, matches `(?m)^if __name__ == ["']__main__["']:`, is not a test path, and is not allowlisted. `is_test_path` is true when any directory part is `tests` or `test`, or the name is `conftest.py` or starts with `test_`. Skip unreadable and binary files as `read_first_line` does. Say in a comment that a script with no main guard goes unseen.

  ```python
  NON_UV_ENTRYPOINT_ALLOWLIST: tuple[str, ...] = (
      "benchmark-llm/benchmark_llm/__main__.py",
      "benchmark-llm/examples/",
      "cognitive_switchyard/cognitive_switchyard/__main__.py",
      "colophon/tools/gen_unicode.py",
      "docker/llm_collector/collector/collector.py",
      "docker/llm_proxy/src/llm_proxy/main.py",
      "model_sentinel/model_sentinel/__main__.py",
      "transcription/app.py",
  )
  ```

  If the guard flags a newer tracked file, report it rather than widening the allowlist unasked.

- [x] **Step 4: Update `agents.md`.** Document the detection boundary defined under Add the check to `main` in the uv-managed launcher section, and name the allowlist.

- [x] **Step 5: Run the whole `agents.md` Shared uv header guard entry**, including its consumer suites, under Worker cap. Expected: the guard prints OK and all suites pass.

- [x] **Step 6: Commit and merge** through the merge protocol.

---

### Task 4: Home Residue Audit

Use the table below as the audit's detection boundary. Preserve the broader Residue Prevention questions under Owner Items; a name heuristic does not settle them. For the existing build wrapper, refer to `tools/check_no_temp_leaks.sh`.

**Files:**
- Create: `tools/check_home_residue.zsh`
- Test: `tools/tests/test_check_home_residue.zsh`
- Modify: `agents.md`, `docs/todo.md`

- [x] **Step 1: Write the failing test**, in the style of `tools/tests/test_check_local_deployments.zsh`, running the audit with `HOME` set to a fresh fake home. Backdate entries with `touch -t`, using `-h` for the symlink. Old means older than 24 hours. Each row is a separate case. The Shape column defines what the audit matches.

  | Fixture entry | Shape | Expected |
  |---|---|---|
  | Old directory `.synthetic-task.aB3dEf` | **Dot suffix:** dot name ending in `.` plus exactly 6 alphanumerics, other than `backup` | Reported, exit 1 |
  | Old file `.synthetic-task.abcdef` | Dot suffix | Reported, exit 1 |
  | Old directory `.synthetic-review-aB3dEf9h` | **Hyphen suffix:** dot name ending in `-` plus exactly 8 alphanumerics with an uppercase letter or digit | Reported, exit 1 |
  | Old symlink `.synthetic-task.xY7zQ2` | Dot suffix, judged on the link itself | Reported, target not followed, exit 1 |
  | Old directory `.synthetic task.aB3dEf` | Dot suffix | Name printed intact, exit 1 |
  | Old directory `.synthetic-task.aB3dEf` holding a marker file | Dot suffix | Marker's name never appears, exit 1 |
  | The reported names, modified within 24 hours | Any | Not reported, exit 0 |
  | Old `.config`, `.synthetic-tool`, `.zshrc.backup`, `.synthetic-review-settings` | None | Not reported, exit 0 |
  | Empty home | None | `check_home_residue: OK`, exit 0 |

- [x] **Step 2: Run it to verify it fails.** Run `zsh tools/tests/test_check_home_residue.zsh`. Expected: FAIL, because the audit does not exist.

- [x] **Step 3: Write the audit under Home scans.** Match direct children of `$HOME` against the table using each entry's own timestamp. Express ages in days and append a count; exit 1 when anything is reported. Do not size entries or delete them.

- [x] **Step 4: Run it once against the real home under Home scans.** Expected: exit 0, or the report defined under Write the audit. If a false positive is identified, add it to the test as a new row and tighten the Shape.

- [x] **Step 5: Update the docs.** Add `zsh tools/tests/test_check_home_residue.zsh` to the Static deployment/fleet audit tooling entry in `agents.md`. Put the real audit beside the cleanup rule in Quality and Consistency, outside mandatory validation: another agent's leftover must not fail unrelated work. Add a `docs/todo.md` item linking this plan's Decision Tasks and Owner Items.

- [x] **Step 6: Commit and merge** through the merge protocol.

---

## Gated Tasks

### Task 5: Webserver Lockfile Refresh

Use `docker/propagate-updates.zsh` rather than hand-editing. The approval scope is the webserver entries in `REFRESH_TARGETS` and the operations in `refresh_stack`, `refresh_lock`, `check_build`, `pull_test_images` and `run_stack_tests`; review those symbols before requesting approval. This is a runtime lock refresh, not just advisory remediation.

**Files:**
- Modify: the lockfiles `refresh` changes under `docker/webserver/`

- [x] **Step 1: Prepare the owner's decision.** Run `docker/propagate-updates.zsh refresh --stack webserver --dry-run` and present its operation list. Copy each Node project's `package.json` and `package-lock.json` to temporary space, run the `npm update` command it prints, and report the lock diffs. Label the Python lock diff unmeasured until its compile operation is approved under Python and uv. Determine Docker availability and report each service's exposure from `docker/webserver/docker-compose.yml`. These observations require fresh output; a source reference alone cannot supply the approval packet.

- [x] **Step 2 (Gated): Run `docker/propagate-updates.zsh refresh --stack webserver`.** Request approval for this exact command and the operations shown by its dry run. Expected: its summary reports success, and the audits in `refresh_lock` pass.

- [x] **Step 3: Run the `agents.md` Docker update propagation suite.** Confirm the authorized refresh also completed the webserver README's Routing regression checks through `run_stack_tests`; rerun that validation if the lockfiles change afterward. Expected: all pass.

- [x] **Step 4: Commit and merge** through the merge protocol.

- [x] **Step 5 (Gated, approved separately): Run `docker/propagate-updates.zsh deploy --stack webserver`.** Require a successful command result and complete the installed acceptance under `docker/webserver/README.md`, Routing regression checks, including the paragraph beginning "After an authorized live update". Report each unmet check as an open release gate.

---

## Decision Tasks

Each task commits a decision record and stops for the owner's choice. Implementation requires a separately requested plan and authorization; these investigations do not migrate runtime state or retire existing venvs.

### Task 6: Test Venv Decision

**Goal:** Choose whether test runs stop recreating their own venvs, without losing reproducible runs.

**Deliverable:** `docs/test_venv_retirement_decision.md`, with measured numbers, a recommendation, an exceptions list, and the rule changes required.

**Sources:**
- Inventory: `git ls-files | rg 'requirements-(dev|test)'`, `git grep -l '\.venv' -- ':!*.md'` and `rg -l '\.venv/bin' -g 'README.md'`. Classify each code match as a hard dependency, a message, or an exclusion list.
- Start with `colophon/tools/gen_unicode.py`'s `if __name__` block, `colophon/tests/run-pytest.sh`, `git-multirepo-dashboard/tests/`, `cognitive_switchyard/cognitive_switchyard/builtin_packs/*/scripts/verify`, `Calculation tools/backtest/tests/helpers/runner.cjs`, `docker/llm_collector` and `benchmark-llm`.
- Policy: `agents.md` Python as an agent and Validation Matrix; `~/.claude/shared/core.md`; `~/.claude/shared/python-env.md`; `python-venv-guard.sh`, `python-classifier.awk` and `audit-python-usage.sh` beside them; the PKM entries "Python Environment Policy" and "Slim instructions".

- [x] **Step 1: Measure the pilots**, `div_conv` (pytest only) and `jtree` (browser), in a worktree. Compare `.venv` setup and run against `uv run --no-project --no-python-downloads --with-requirements requirements-dev.txt pytest …`. For cold runs, set `UV_CACHE_DIR` to a fresh `mktemp -d`, record its size, then remove it. Record cold time, warm time, disk and pass count.

- [x] **Step 2: Try `uv run --extra` in `benchmark-llm`.** Request approval for `uv run --no-python-downloads --extra dev pytest -q` under the `agents.md` Python as an agent entry before running it, or record this pilot as unmeasured.

- [x] **Step 3: Answer these in the record:**

  1. What replaces the venv: ephemeral `uv run`, a per-project script, or a Make target? Does it work for `pip install -e` projects?
  2. Do `pytest-playwright`, and tests that spawn `sys.executable`, work in an ephemeral environment?
  3. Is the disk result a real saving, or the same bytes moved to the cache reported by `uv cache dir`?
  4. Are failures as reproducible without a stable venv? Do tracked dev requirements pin enough?
  5. How do concurrent worktree runs behave against the shared cache?
  6. Which projects stay exceptions, judged from the Sources?
  7. Do the classifier and hook permit the chosen form?

- [x] **Step 4: Commit the record.**

### Task 7: Transcription Decision

**Goal:** Choose a uv delivery approach for `transcription` against its README's Setup and Run sections.

**Deliverable:** `docs/transcription_uv_decision.md`, with spike results and each question answered. Do not merge the spike.

**Sources:**
- `transcription/`: `README.md`, `setup.sh`, the requirements files, `app.py`, `transcribe.py`.
- `agents.md`: Public repository, the uv-managed launcher rules, and the Streamlit entry.
- `tools/check_uv_headers.py`: `FORBIDDEN_PATTERNS`, `check_launcher`, `missing_declared_imports`, `IMPORT_DISTRIBUTION_ALIASES`.
- `docs/local_deployment_sync.md`: the Transcription entries.

- [x] **Step 1: Spike in a worktree.** Build one launcher with a capped header matching `setup.sh`'s interpreter, declaring every pinned requirement. Test the question table's startup recommendation, then a child process if needed, without `os.execv`. Apply its state recommendation with `TRANSCRIPTION_HOME` pointing to synthetic scratch; isolate `transcribe.py`'s working directory before it starts.

- [x] **Step 2: Test the spike.** Through the launcher, start each script headless, request `/`, and confirm Ctrl-C ends it cleanly with no orphaned process. Do not load a Whisper model or use real audio. Launch from another directory and verify the state recommendation in the question table for each script; record additional changes needed. Keep these spike results distinct from acceptance requirements in the future implementation plan.

- [x] **Step 3: Measure the footprint.** Use a fresh `UV_CACHE_DIR` in temporary space, with and without the optional packages. Record cold start, warm start and disk, and say whether the cold start is acceptable.

- [x] **Step 4: Answer these in the record.** Each starting recommendation is there to confirm or overturn with the spike's evidence.

  | Question | Starting recommendation |
  |---|---|
  | How does a launcher start Streamlit? | In-process through `streamlit.web.cli`, if Ctrl-C works |
  | Are the optional packages required? | Declare them unless the footprint is large; otherwise add an optional-dependency policy to the guard |
  | How does the guard see imports in scripts a thin launcher starts? | Evaluate `tools/check_uv_headers.py:missing_declared_imports` and `check_launcher`; propose scanning named launcher targets and adding the `whisper` alias |
  | Does state move to `~/.transcription/`? | Use that default runtime home, honor `TRANSCRIPTION_HOME`, and migrate manually with documented steps and no automatic import, following Public repository |
  | One launcher with two modes, or two launchers? | One, with `app.py` as the default |
  | Do the old scripts go? | Use the legacy-wrapper list in `agents.md` Streamlit apps; propose deleting those wrappers, `ui.sh` and `setup.sh` after checking deployed callers |
  | Are Whisper model downloads unaffected? | Expected to be. Confirm where Whisper keeps its cache |

- [x] **Step 5: List what the implementation plan must cover:** `transcribe.py` as well as `app.py`, the verified question-table decisions, guard registration, removing `transcription/app.py` from `NON_UV_ENTRYPOINT_ALLOWLIST`, the `agents.md` Streamlit and setup-script entries, the README's Validation section, deployment, and removing the `transcription` venvs after verification.

- [x] **Step 6: Commit the record.**

---

## Owner Items

These need no agent unless the owner asks.

- **Trash:** apply Recovery before emptying Trash in the predecessor plan's Home Residue Cleanup Record before deciding whether to empty local or cloud Trash.
- **Codex worktree cleanup:** follow the owning-manager requirement in the predecessor plan's Protected paths paragraph.
- **Rollback pruning:** follow Rollback retention decision in `docs/retire_venvs_for_uv_implementation_plan.md`. Automated enforcement needs a separate owner choice.
- **Cleanup rule scope:** decide whether the cleanup instruction belongs in `~/.claude/shared/core.md` as well as `agents.md`.
- **Audit schedule:** decide whether to schedule Home Residue Audit after its on-demand behavior is reviewed.
- **Evidence location and retention:** resolve the Residue Prevention questions in `docs/retire_venvs_for_uv_implementation_plan.md` against that brief's sources. Home Residue Audit does not settle them.
- **General sibling-module scanning:** resolve the No-Shebang Detection sibling-module question in `docs/retire_venvs_for_uv_implementation_plan.md`. Transcription Decision does not decide the general policy.
- **`tax2` acceptance:** consult commit `3c0446a` and the `agents.md` Tax2 entry; request a fresh run if independent acceptance evidence is wanted.
