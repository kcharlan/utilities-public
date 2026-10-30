# Transcription uv Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `transcription` off its private venv to one uv-managed launcher with state in its runtime home, then deploy it and retire the wrappers and venvs.

**Architecture:** `transcription/transcription` starts the scripts in process. They share `transcription_state.py` for state and uploads. The Launcher, State, Input and Release Tasks share a feature branch; the Retirement Task follows in a separate PR.

**Tech Stack:** Python 3.12, uv, Streamlit AppTest, openai-whisper, pytest, zsh.

**Spec:** [The delivery decision](transcription_uv_decision.md). Authorization is defined under Global Constraints and Owner gates.

## Global Constraints

- Header: `requires-python = ">=3.12,<3.13"`; use the exact requirement entries from `transcription/requirements.txt` and `transcription/requirements-optional.txt`. FFmpeg stays a machine prerequisite.
- Follow `agents.md` Public repository, Git, Testing Scope, Release Versions, and Quality and Consistency, including cleanup of owned temporary evidence. Never read real counters, audio or transcripts. Real-file metadata access is limited to the Release Task's deployment gate.
- Follow [the deployment guide](local_deployment_sync.md) from `main`. Use `/usr/bin/trash` for pre-existing removal targets; never empty the Trash.
- Implementation requires a separate request. Commit, publish, deployment and retirement actions require explicit authorization under the owner gates; requesting execution alone is not approval to commit.

**Terms.** *The scripts*: `transcription/app.py` and `transcription/transcribe.py`. *The counter files*: `session_backup.json` and `transcription_odometer.txt`. *The wrappers*: the Delete list in the Retirement Task.

**Named commands**, run from the repository root:

- *Guard scan*: `uv run --no-python-downloads --script tools/check_uv_headers.py`.
- *Guard tests*: `uv run --no-project --no-python-downloads --with pytest pytest tools/tests/test_check_uv_headers.py -q -p no:cacheprovider`.
- *Guard check*: run *Guard scan* and *Guard tests*.
- *Self-test*: `uv run --no-python-downloads --with pytest --with pip --with httpx --script transcription/transcription self-test`. It takes optional pytest paths and options.
- *Consumer suites*: every suite the `agents.md` Shared uv header guard entry requires after guard code changes.

**Owner gates** are marked **[OWNER]**. Stop at each one until the owner approves that named action in chat. An earlier approval does not cover a later gate.

## Source anchors and validation status

Inspect `transcription/app.py:controls_form`, `process_files` and `transcribe_audio`; `transcription/transcribe.py:get_file_names_from_uploads`, `get_audio_duration` and its transcription loop; and `tools/check_uv_headers.py:main`, `compare_dependency_sets` and `missing_declared_imports` before implementing their task changes.

Historical spike evidence is in [the decision record](transcription_uv_decision.md#recommendation-and-evidence). The launcher graph, overlay, pinned-package behavior and model acceptance remain implementation gates, exercised by the Environment and Release tests below. Prior probes do not satisfy them.

## Owner Decisions

1. **Migration:** approved.
2. **Authoritative legacy counters:** `~/transcription`.
3. **Test environment:** the *Self-test* overlay, with its test packages recorded in `requirements-dev.txt`. For this project it supersedes the local test-venv default in `agents.md` and the recommendation in [the test-venv decision](test_venv_retirement_decision.md). Existing environments stay until the Retirement Task.
4. **`librosa`:** keep it in the launcher graph.
5. **OpenAI fallback:** preserve `app.py:transcribe_audio`'s key-gated fallback and document it. Verify it with the Input Task's fallback tests.
6. **Other wrapper callers:** the owner expects none. Recheck that expectation at retirement; preserve the recovery path described there. See the decision record's wrapper investigation for the limits of its checks.

**Proposed behavior requiring acceptance with the implementation request:** the Launcher and Input Tasks' tests define launch settings, input handling and selected-model changes. State tests define shared-counter behavior. Upload names displayed by the UI acquire the prefix specified by `write_upload`. These proposals are not additional recorded owner decisions.

---

### Task 1: Launcher Task

**Files:**
- Create: `transcription/transcription` (mode `0755`), `transcription/requirements-dev.txt`, `transcription/tests/conftest.py`, `transcription/tests/test_launcher.py`, `transcription/tests/test_environment.py`
- Modify: `transcription/app.py`, `transcription/requirements-optional.txt`, `tools/check_uv_headers.py`, `tools/tests/test_check_uv_headers.py`, `transcription/README.md`, `docs/projects.md`, `agents.md`

**Interfaces:**
- Produces, in the launcher: `PROJECT_DIR: Path`; `MODES = {"app": "app.py", "divider": "transcribe.py"}`; `find_free_port(start_port, max_attempts=20)`, behaving as `jtree/jtree:find_free_port` does; `build_streamlit_argv(script: Path, port: int, headless: bool) -> list[str]`; `run_self_test(pytest_args: list[str]) -> int`; `main() -> int`.
- Produces, in the guard: `LAUNCHER_TARGETS: dict[str, tuple[str, ...]]`; `check_launcher_targets(rel_path: str, dependencies: list[str]) -> list[str]`.
- Produces, in `tests/conftest.py`: `PROJECT_DIR` and `UTILITIES_ROOT` on `sys.path`, as `tools/tests/test_check_uv_headers.py` does for the root; and a `server_cycle(argv, cwd, env)` fixture. It starts `argv` with `subprocess.Popen(..., stdin=subprocess.DEVNULL, start_new_session=True)`, requires 200 from `/` and `ok` from `/_stcore/health`, sends `SIGINT` to the group, then requires exit 0 and that `os.killpg(pgid, 0)` raises `ProcessLookupError`. Bound startup/shutdown waits and kill/reap only the owned group in `finally`, including failed health checks.
- Initial isolation fixture: before executing either existing script, create a synthetic working directory, change into it, remove `OPENAI_API_KEY`, and point `TRANSCRIPTION_HOME` plus the existing counter override variables at test-owned paths. Pass this isolation to server subprocesses. The State Task replaces the legacy override setup once the scripts share the state module. Tests of `HOME` resolution set synthetic `HOME` locally.
- CLI: `transcription [app|divider] [--port N] [--no-browser]`, default mode `app`, default port `8501`; `transcription self-test [pytest paths and options]`.

- [ ] **Step 1: Create an isolated feature worktree** following `agents.md` and the applicable worktree skill. Preserve unrelated uncommitted work.

- [ ] **Step 2: Write the guard tests in `tools/tests/test_check_uv_headers.py`,** in that file's `tmp_path` and `monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)` style.
  - `test_target_missing_import_is_reported`: a target with lazy `import librosa`, dependencies without it. The problem names the target and `librosa`.
  - `test_whisper_alias_satisfies_import`: `missing_declared_imports` accepts `import whisper` with its requirement from the header.
  - `test_missing_target_is_reported`: returns `["registered target not found: <target>"]`.
  - `test_target_syntax_error_is_reported`: a target that does not parse yields a problem.
  - `test_targets_belong_to_registered_launchers`: `set(guard.LAUNCHER_TARGETS) <= set(LAUNCHERS)`.
  - `test_transcription_app_is_not_entrypoint_allowlisted`: `"transcription/app.py" not in guard.NON_UV_ENTRYPOINT_ALLOWLIST`.
  - `test_transcription_policy_reconciles_manifests`: the policy is `("requirements", "transcription/requirements-dev.txt", frozenset({"httpx", "pip", "pytest"}))`, and `check_dependency_manifest("transcription/transcription") == []`.

- [ ] **Step 3: Run *Guard tests* and confirm** the new tests fail on the missing names and policy, and the existing tests pass.

- [ ] **Step 4: Change the guard to satisfy the guard tests.**
  - Add `"whisper": "openai-whisper"` to `IMPORT_DISTRIBUTION_ALIASES`.
  - Remove `"transcription/app.py"` from `NON_UV_ENTRYPOINT_ALLOWLIST`.
  - Append `"transcription/transcription"` to `LAUNCHERS`, and add its `DEPENDENCY_MANIFESTS` entry from the policy test.
  - Add `LAUNCHER_TARGETS = {"transcription/transcription": ("transcription/app.py", "transcription/transcribe.py")}` with a comment that this is an explicit per-launcher list, not sibling-module scanning.
  - Have `check_launcher` extend `problems` with `check_launcher_targets(rel_path, deps)` beside its existing import check. The function reports a missing, undecodable or unparsable target, and otherwise passes the target's own path and text to `missing_declared_imports`.

- [ ] **Step 5: Create `transcription/requirements-dev.txt`** by including the header's requirement manifests with `-r` and adding the test-only extras from `test_transcription_policy_reconciles_manifests`. The HTTP test imports `httpx` directly for a transport that cannot send real requests, so it needs an explicit test requirement despite also being a transitive runtime dependency. Reword `requirements-optional.txt` comments to point at the launcher header for installation.

- [ ] **Step 6: Write `transcription/tests/test_environment.py`.** No skips.
  - `test_python_is_312`: `sys.version_info[:2] == (3, 12)`.
  - `test_direct_pins_are_installed`: `importlib.metadata.version` equals every pin in the launcher header.
  - `test_header_pins_match_requirement_files`: `sorted(extract_pep723(text)["dependencies"])` equals the sorted `parse_requirements_file` results of `requirements.txt` and `requirements-optional.txt` combined.
  - `test_dev_requirements_name_the_overlay`: test requirements minus header requirements equal the policy's manifest-only extras, and each extra is importable.
  - `test_dependency_closure_is_consistent`: `[sys.executable, "-m", "pip", "check"]` exits 0.
  - `test_optional_packages_work_offline`: `librosa.load` reads a WAV written with the standard `wave` module, with positive duration.
  - `test_installed_openai_text_response`: construct the installed OpenAI client with a conspicuously synthetic key and `httpx.MockTransport`. Force local transcription failure and exercise `app.py:transcribe_audio` through that client; assert the synthetic text response is returned and the request uses the existing function's arguments. Close clients and ensure no request can leave the process. This verifies the installed SDK's response handling, beyond the Input Task's fake-client control-flow checks.

- [ ] **Step 7: Write `transcription/tests/test_launcher.py`,** using `load_launcher` and `assert_launcher_help` from `tools.testkit`.
  - `test_default_mode_selects_app` and `test_divider_mode_selects_transcribe`: with a fake `streamlit.web.cli` in `sys.modules`, `main()` calls its `main()` once. Captured `sys.argv[:3]` is `["streamlit", "run", str(PROJECT_DIR / script)]`, and `os.getcwd()` at that call equals the caller's directory.
  - `test_streamlit_argv_binds_loopback`: the argv contains `--server.address 127.0.0.1`, the port, `--server.headless`, `--server.showEmailPrompt false` and `--browser.gatherUsageStats false`.
  - `test_no_browser_sets_headless`.
  - `test_busy_port_moves_and_warns`: with the requested port bound, the next port is used and stderr names both.
  - `test_missing_ffmpeg_warns_and_continues`: `shutil.which` returns `None`; stderr names FFmpeg and Streamlit still starts.
  - `test_symlinked_launcher_finds_scripts`: run `server_cycle([sys.executable, link, "--no-browser", "--port", port], ...)`, where `link` is a symlink in a `tmp_path` directory containing a space. Do not use the `tools.testkit` helpers here; they resolve the path before running it.
  - `test_missing_script_exits_with_message`: exit 2 and no traceback.
  - `test_help_does_not_import_streamlit`: `assert_launcher_help`, and in a child process `streamlit` is absent from `sys.modules`.
  - `test_server_starts_and_stops[app|divider]`: `server_cycle([sys.executable, launcher, mode, "--no-browser", "--port", port], ...)`.

- [ ] **Step 8: Implement `transcription/transcription` to satisfy the launcher tests and CLI.** Use `tools/check_uv_headers.py:CANONICAL_SHEBANG` and the Global Constraints header. Set `PROJECT_DIR = Path(__file__).resolve().parent`. Parse arguments before importing Streamlit, and import `streamlit.web.cli` inside `main()`. Set `sys.argv` from `build_streamlit_argv`, then `return stcli.main()`. Do not spawn a child process or set environment variables. Accept unrecognized arguments only for `self-test`. `run_self_test` must:
  - return 2 with a message when `importlib.util.find_spec("pytest")` is `None`;
  - let pytest parse the supplied options and paths, and use `PROJECT_DIR / "tests"` when pytest received no explicit collection target, including option-only calls from any working directory;
  - load the optional pytest overlay only after checking its availability, and call `pytest.main` with a plugin that selects the default from pytest's parsed argument source. Preserve explicit paths and node IDs.

- [ ] **Step 9: Replace the `if __name__` block at the end of `app.py`** with a bare `main()` at column zero and a one-line comment that Streamlit always runs this file as a script.

- [ ] **Step 10: Update docs.**
  - In `transcription/README.md`, replace Requirements, Setup and the Run sections with the launcher CLI; point at the decision record for measured cache footprint. Document the header's machine prerequisites and Owner Decisions' OpenAI behavior. Update Troubleshooting and identify the wrappers as transitional until the Retirement Task.
  - In `agents.md`, rewrite `Streamlit apps (transcription)` to the launcher commands and *Self-test*, referring to Owner Decisions' Test environment. Update `docs/projects.md`'s Transcription entry to link to the revised setup instructions.

- [ ] **Step 11: Verify.** Run *Guard check* and *Self-test*. Expected: `check_uv_headers: OK` with the new launcher counted, all tests pass, none skipped. Record the active cache location from `uv cache dir` and its size; do not attribute a shared cache's total to this project.

- [ ] **Step 12: Run *Consumer suites*.** Expected: all pass, every failure named.

- [ ] **Step 13: Commit** on the feature branch, per Global Constraints, when execution is authorized.

### Task 2: State Task

**Files:**
- Create: `transcription/transcription_state.py`, `transcription/tests/test_state.py`, `transcription/tests/test_counters_ui.py`
- Modify: `transcription/tests/conftest.py`, the scripts, `tools/check_uv_headers.py`, `transcription/README.md`, `agents.md`

**Interfaces:**
- Consumes: *Self-test* and `conftest.py` from the Launcher Task.
- Produces, in `transcription_state.py`, standard library only, resolving paths at each call because the scripts re-execute on rerun:
  - `@dataclass(frozen=True) class Counters: cumulative_seconds: float; lifetime_seconds: float`
  - `@dataclass(frozen=True) class CounterRead: counters: Counters; warnings: tuple[str, ...]`
  - `runtime_home() -> Path`, `cumulative_path() -> Path`, `lifetime_path() -> Path`
  - `read_counters() -> CounterRead`, which reports `OSError` as a warning
  - `add_duration(seconds: float) -> Counters` and `reset_cumulative() -> Counters`, which raise `OSError`
- State path contract: `runtime_home()` defaults to `Path.home() / ".transcription"`, with nonempty `TRANSCRIPTION_HOME` taking precedence; expand `~`. Counter paths default beneath that home; nonempty `CUMULATIVE_JSON_PATH` and `LIFETIME_TXT_PATH` override their respective paths, with the same expansion. Relative overrides resolve from the caller's directory. Secure the runtime home and lock as tested by `test_private_modes`; do not chmod an override's existing outside parent.
- Produces, in `tests/conftest.py`: an autouse fixture that sets `TRANSCRIPTION_HOME` to `tmp_path / "home"`, removes `CUMULATIVE_JSON_PATH`, `LIFETIME_TXT_PATH` and `OPENAI_API_KEY`, and changes directory to `tmp_path / "cwd"`; and `stub_whisper(monkeypatch)`, which replaces `whisper.load_model`, `whisper.load_audio` and `whisper.audio.load_audio` so no model or audio is needed.

- [ ] **Step 1: Write `transcription/tests/test_state.py`.**
  - `test_default_home`, `test_home_override_and_empty_value`, and `test_file_overrides_win_for_each_counter`: exercise the State path contract with a synthetic `HOME`, including relative and tilde overrides. Published override files are `0o600`.
  - `test_private_modes`: after `add_duration`, home `0o700` and the counter files and `counters.lock` `0o600`, also when the home pre-existed at `0o755`.
  - `test_write_formats_are_legacy_compatible`: assert these exact synthetic outputs after adding duration:
    ```python
    assert json.loads(cumulative_path().read_text()) == {"cumulative_seconds": 3.5}
    assert lifetime_path().read_text() == "3.5\n"
    ```
  - `test_reads_each_legacy_lifetime_form[newline|no-newline]`: use synthetic fixtures in the formats of `app.py:save_counters_to_legacy` and `transcribe.py:save_lifetime_odometer`.
  - `test_cwd_legacy_counters_are_not_imported`: synthetic counter files in the working directory, and `read_counters().counters == Counters(0.0, 0.0)`.
  - `test_corrupt_counter_is_preserved[bad-json|list-json|text|nan|negative]`: the value reads as `0.0`, the original bytes survive in `<name>.unreadable-<UTC stamp>`, and a warning names that file.
  - `test_unreadable_home_is_a_warning`: with the home path being a file, `read_counters` warns and `add_duration` raises `OSError`.
  - `test_concurrent_additions_are_not_lost`: use `multiprocessing` workers; assert the resulting counters equal the sum of their contributions. Bound joins, surface child errors, and terminate workers in `finally` on failure.
  - `test_reset_keeps_lifetime`.
  - `test_readme_migration_block`: extract the `bash` block under README `## Manual counter migration` and run it with `bash` against synthetic `HOME/transcription` fixtures. Test populated, individually absent and entirely absent sources; existing destinations; repeat invocation; and the State path contract's override cases. Assert successful exit for absence, source bytes unchanged, destination values/modes, and unchanged permissions on existing outside parents. Existing destinations and dangling symlinks must never be overwritten.

- [ ] **Step 2: Run *Self-test* with `transcription/tests/test_state.py` and confirm** the tests fail.

- [ ] **Step 3: Implement `transcription_state.py`.**
  - Implement the State path contract, using `tax2/taxkit/config.py:ensure_runtime_home`, `_private_temp` and `atomic_write_bytes` as behavior references for directory creation and file publication. Keep Transcription runtime-standalone; do not import Tax2.
  - Hold `fcntl.flock` on `<home>/counters.lock` around every read and read-modify-write, including `read_counters`, so a racing writer's file cannot be moved aside. The lock is per home, so the README says one override file must not be shared by different homes.
  - A missing value reads as `0.0`. A value that does not parse, is not finite, is negative or has the wrong shape is moved aside with `os.replace` and reads as `0.0`.

- [ ] **Step 4: Write `transcription/tests/test_counters_ui.py`** using `AppTest.from_file(path, default_timeout=120)` and `stub_whisper`.
  - `test_interfaces_share_counters`: process a stubbed file in `app.py`. A fresh AppTest of `transcribe.py` shows the same cumulative total, and its reset writes `0.0` and keeps the lifetime value. A fresh `app.py` then shows the reset value.
  - `test_reset_from_each_interface[app|divider]`, with the confirm click for `app.py`.
  - `test_reset_failure_keeps_totals_and_transcripts[app|divider]`: inject `OSError` from `reset_cumulative` after seeding counters and a transcript. Click the reset (including confirmation where required); require `st.error`, no exception, no success message, unchanged totals/transcript and no automatic rerun loop. Restore persistence and retry successfully.
  - `test_counter_failure_keeps_transcript[app|divider]`: point the home at a file. An error shows, `at.exception` is empty and the transcript is present.
  - `test_read_warning_is_shown[app|divider]`: a corrupt synthetic counter shows a warning naming the preserved file, and it still shows after a second `at.run()`.

- [ ] **Step 5: Change `app.py`.**
  - Delete `CUMULATIVE_JSON_PATH`, `LIFETIME_TXT_PATH`, `atomic_write_text`, `atomic_write_json`, `load_counters_from_legacy` and `save_counters_to_legacy`.
  - In `ensure_session_state`, use `read_counters`, keep its warnings in session state and show them on every rerun.
  - In `process_files`, call `add_duration` in its own `try` and set the session totals from the returned `Counters`. On `OSError`, show `st.error`, add to the session totals locally, and still add the transcript.
  - In `render_metrics_and_resets`, implement `test_reset_from_each_interface` and `test_reset_failure_keeps_totals_and_transcripts`. Use `reset_cumulative`'s returned `Counters` only on success; catch `OSError` before changing totals or announcing success.
  - Update the header comment lines that describe `./` paths.

- [ ] **Step 6: Change `transcribe.py`.** Delete `load_lifetime_odometer`, `save_lifetime_odometer`, `load_cumulative_counter` and `save_cumulative_counter`. Display totals from `read_counters()` on each run, keeping warnings in session state. Use the shared APIs for additions and resets, satisfying the counter UI tests. Add `test_divider_failed_transcription_counts_detected_duration` to preserve the behavior of the current `transcribe.py` transcription loop; retain that behavior's description when rewriting the README.

- [ ] **Step 7: Add `"transcription/transcription_state.py"` to the `LAUNCHER_TARGETS` tuple.**

- [ ] **Step 8: Update docs.**
  - Rewrite README Counters and local state for the home, overrides, atomic writes, `.unreadable-*` recovery and the lock.
  - Add README `## Manual counter migration` with a `bash` block satisfying `test_readme_migration_block` and the State path contract, using Owner Decisions' authoritative legacy location. A reference alone cannot provide the directly runnable recipe. Require stopped interfaces and report skipped paths. Explain owner-run reconciliation between legacy and runtime totals for migration retries or rollback; never advise deleting accumulated totals to retry.
  - In `agents.md`, point Sensitive/Stateful Files at the home as well as the legacy paths.

- [ ] **Step 9: Verify** with *Guard check*, *Self-test* and *Consumer suites*, since this task changes the guard registry. Expected: all pass, none skipped.

- [ ] **Step 10: Commit** per Global Constraints, when execution is authorized.

### Task 3: Input Task

**Files:**
- Create: `transcription/tests/test_uploads.py`, `transcription/tests/test_input_ui.py`
- Modify: `transcription/transcription_state.py`, the scripts, `transcription/README.md`, `docs/lessons_learned.md`

**Interfaces:**
- Consumes: the `conftest.py` fixtures.
- Produces, in `transcription_state.py`:
  - `new_upload_batch() -> Path`: `tempfile.mkdtemp(prefix="transcription-upload-")`, in OS temporary space, mode `0700`.
  - `write_upload(batch: Path, index: int, name: str, data: bytes) -> Path`: writes `<index:04d>-<safe basename>` at `0600` inside `batch`.
  - `discard_upload_batch(batch: Path | None) -> None`: removes the batch and tolerates `None` and absence.
- Changes: `controls_form` returns `(selected_paths, model_name, did_submit, upload_batch)`. `process_files(filepaths, model_name)` loses `created_temp_files`.

- [ ] **Step 1: Write `transcription/tests/test_uploads.py`.**
  - `test_batch_is_private_and_outside_checkout`: mode `0o700`, and not under `PROJECT_DIR` or the working directory.
  - `test_write_upload_stays_in_batch[../escape.wav|a/b.m4a|..|empty]`: the result's parent is `batch`, mode `0o600`, bytes intact.
  - `test_equal_names_do_not_collide`: two uploads named `same.wav` keep separate content.
  - `test_discard_tolerates_none_and_absence`.

- [ ] **Step 2: Write `transcription/tests/test_input_ui.py`** with `stub_whisper`. Give each test its own temporary root and point `tempfile.tempdir` there (and `TMPDIR` in children). Record every `tempfile.mkdtemp` allocation, regardless of prefix, and assert allocated upload directories are absent afterward. The recorder must delegate to the real function so it can catch the current unprefixed divider leak. Restore globals and remove owned residue in teardown even when an assertion fails.
  - `test_path_mode_is_caller_relative[app|divider]`: `./audio/synthetic.wav` under the fixture's working directory is found and processed.
  - `test_path_mode_keeps_upload_prefixed_file`: `upload_notes.wav` selected in Path mode still exists afterward.
  - `test_upload_writes_nothing_to_cwd[app|divider]`: `at.file_uploader[0].upload("synthetic.wav", b"RIFF")`, then Start. The working directory stays empty and no batch remains.
  - `test_app_upload_cleanup_on_failure`: `load_model` raises, and no batch remains.
  - `test_divider_upload_cleanup_on_failure`: the stub model's `transcribe` raises, an `[ERROR]` result shows, and no batch remains.
  - `test_upload_write_failure_is_recoverable[app|divider]`: fail an upload write after an earlier upload has been saved. Require a visible error, no `at.exception`, retained previous results, and no upload directory or partial file. Also cover allocation failure. Restore writes and retry successfully.
  - `test_divider_rerun_makes_no_batch`: uploading and rerunning without Start creates no batch.
  - `test_app_uses_selected_model`: `tiny` in the selectbox reaches `whisper.load_model("tiny")`.
  - `test_divider_duration_falls_back_to_whisper`: `librosa.load` raises `RuntimeError`; the counter gains the duration of the synthetic array returned by `whisper.load_audio`, and the transcript has no `[ERROR]`.
  - `test_app_fallback_needs_key`: `load_model` raises and no key is set. A fake `openai.OpenAI` is never constructed, and the row shows the failure.
  - `test_app_fallback_uses_key`: with a synthetic key, the fake client is called once with `model="whisper-1"` and its text becomes the transcript.
  - `test_divider_never_calls_openai`: with a synthetic key and a failing model, the fake client is never constructed.

- [ ] **Step 3: Run *Self-test* with these files before changing the scripts.** Require observed failures for the upload leak, path-file deletion, selected-model and duration-fallback regression tests; ensure they fail at assertions about those behaviors rather than collection or unsupported harness APIs. Record already-passing preservation tests separately, including fallback tests. Tests of newly introduced helpers may fail because the helpers are not implemented yet; do not present those failures as reproduction of existing bugs.

- [ ] **Step 4: Change `app.py`.**
  - In `controls_form`, use the upload APIs and satisfy `test_upload_write_failure_is_recoverable`; discard partially allocated batches before returning no paths.
  - Return the local `model_name` from `controls_form`.
  - In `process_files`, remove the `finally` unlink, `safe_unlink`, and the `upload_` prefix test.
  - In `main`, wrap processing in `try/finally` with `discard_upload_batch(upload_batch)`, also when nothing was selected.
  - Replace the header line and the `process_files` docstring line that describe `upload_*` cleanup.

- [ ] **Step 5: Change `transcribe.py`.**
  - Delete `get_file_names_from_uploads`. Before Start, derive the status list and button state from `uploaded_files` names without writing anything.
  - Inside `if transcribe_btn:`, allocate/write uploads after the model loads. The `try/finally` must enclose allocation, every write and transcription, with `upload_batch = None` before entering it. Catch allocation/write `OSError` and report `st.error` without replacing prior results or announcing transcription success. Cleanup applies on write errors and Streamlit stop/rerun exits as well as processing failures. Satisfy `test_upload_write_failure_is_recoverable`.
  - Keep what `st.session_state['file_names']` displays.
  - In `get_audio_duration`, catch `Exception` around the `librosa` call and fall back to Whisper, and change the bare `except:` to `except Exception:`.

- [ ] **Step 6: Update docs.** Document the input behavior exercised by this task's tests and explain that a killed process can leave an upload directory behind. Add `docs/lessons_learned.md` entries pointing at `test_path_mode_keeps_upload_prefixed_file`, `test_divider_duration_falls_back_to_whisper`, `test_divider_rerun_makes_no_batch` and `test_app_uses_selected_model` rather than duplicating their fixtures.

- [ ] **Step 7: Verify.** Run *Guard check*, *Self-test* and *Consumer suites* on the combined branch. Expected: all pass, none skipped.

- [ ] **Step 8: Commit** per Global Constraints, when execution is authorized.

### Task 4: Release Task

**Release graph amendment:** the strict audit found 39 vulnerabilities in
Pillow 12.3.0, all fixed in 13.0.0. Streamlit 1.66.0 requires Pillow below
13. Update Streamlit to 1.66.1 and pin Pillow 13.0.0 in the launcher and
requirements: 1.66.1 permits Pillow 13, but upgrading Streamlit alone left
the vulnerable installed Pillow in the uv environment. The complete suite,
guard, consumer suites and strict audit remain required for the amended graph.

**Files:**
- Create: `transcription/tests/acceptance/release_checks.py`, `transcription/tests/acceptance/real_model.py`
- Modify: `transcription/README.md`, `docs/local_deployment_sync.md`

**Interfaces:**
- Consumes: `server_cycle` and the full branch. Real-model acceptance must not use `stub_whisper`.
- Deployment form: a maintained source copy in `~/transcription`; run its launcher in place.
- Produces, collected only when named explicitly because their filenames have no `test_` prefix:
  - `release_checks.py`: `test_shebang_launch_starts_and_stops[app|divider]` runs `server_cycle` on the launcher file itself with `UV_PYTHON_DOWNLOADS=never`. The path comes from `TRANSCRIPTION_LAUNCHER`, defaulting to `PROJECT_DIR / "transcription"`. `test_write_environment_freeze` writes `pip freeze --all` from the running environment to `$TRANSCRIPTION_ACCEPTANCE_DIR/freeze.txt`.
  - `real_model.py`: reads `TRANSCRIPTION_ACCEPTANCE_DIR`, and uses `monkeypatch.setenv("XDG_CACHE_HOME", <dir>/cache)`, so uv's cache stays where it is.

- [ ] **Step 1: Write the acceptance files and rewrite README Validation** around the launcher graph and the *Release invocation* recipe.
  - `test_tiny_model_word_timings`: `whisper.load_model("tiny")`, `transcribe(wav, word_timestamps=True, fp16=False)`, nonempty text, nonempty ordered nonnegative word timings, and `tiny.pt` exists under `<dir>/cache/whisper`.
  - `test_app_end_to_end_with_tiny`: AppTest, `tiny`, Path mode on the WAV. A transcript appears and the counters in the home are positive.
  - `test_divider_end_to_end_with_m4a`: AppTest, `tiny`, path to the `.m4a`. No `[ERROR]`, and the counters are positive.

- [ ] **Step 2: Run release checks and audit.** Name the following recipe *Release invocation* in README Validation. Its exact code establishes scratch lifetime across the checks; each use runs to completion before any owner gate:

  ```bash
  (
    set -eu
    S=$(mktemp -d "${TMPDIR:-/tmp}/transcription-acceptance.XXXXXX")
    trap 'rm -r -- "$S"' EXIT
    TRANSCRIPTION_ACCEPTANCE_DIR="$S" uv run --no-python-downloads --with pytest --with pip --with httpx --script transcription/transcription self-test transcription/tests/acceptance/release_checks.py
    uvx --no-python-downloads pip-audit --strict --no-deps --disable-pip -r "$S/freeze.txt"
  )
  ```

  Expected: the named acceptance tests and audit pass. Report results before the trap removes their files. A failed test, audit or withheld later gate must leave no owned scratch.

- [ ] **Step 3: Verify the full pinned graph's environment evidence.** Require `test_environment.py` and the freeze/audit from *Release invocation*. If the installed Streamlit uploader API differs from the Input Task's outline, adapt the harness against its installed source and retain the behavior assertions; report the discrepancy. Block release on unresolved graph, API-surface or audit failures.

- [ ] **Step 4: [OWNER] Authorize the Whisper `tiny` model download.** After approval, use *Release invocation*, inserting these commands and the `real_model.py` test run before its closing parenthesis:

  ```zsh
  say -o "$S/synthetic.aiff" 'This is a synthetic transcription acceptance test.'
  ffmpeg -nostdin -y -i "$S/synthetic.aiff" -ac 1 -ar 16000 "$S/synthetic.wav"
  afconvert -f m4af -d aac "$S/synthetic.aiff" "$S/synthetic.m4a"
  ```

  Invoke *Self-test* with `TRANSCRIPTION_ACCEPTANCE_DIR="$S"` and `transcription/tests/acceptance/real_model.py`. Expected: the named model tests pass. Use `real_model.py`'s cache setup. Record any gate not run; it remains required before release.

- [ ] **Step 5: Update `docs/local_deployment_sync.md`.** Update the local-only state list from the State path contract and Owner Decisions, document this task's Deployment form, and add Transcription to the copied-test `PYTHONPATH` guidance for `tools.testkit`.

- [ ] **Step 6: Commit** per Global Constraints, when execution is authorized.

- [ ] **Step 7: [OWNER] Push, open the PR and merge to `main`.** Check first that every commit on the branch has a body.

- [ ] **Step 8: [OWNER] Authorize real deployment and confirm no interface is running.** For each legacy counter path from Owner Decisions, record presence or absence; run `stat -f '%m %z'` only on present regular files. Report unexpected entry types and stop state-related actions without reading contents. Then use the deployment guide's Top-level home project copies pattern for `project="transcription"`.

- [ ] **Step 9: Verify the deployment.**
  - `zsh tools/check_local_deployments.zsh`. Expected: no `transcription` drift.
  - Run *Self-test* with `transcription/tests/acceptance/release_checks.py -k shebang` and `TRANSCRIPTION_LAUNCHER="$HOME/transcription/transcription"`. The test sets a scratch `TRANSCRIPTION_HOME`, so the real home is not touched.
  - Repeat the presence/type and metadata checks. Expected: the recorded legacy state is unchanged, including absent files remaining absent.

- [ ] **Step 10: [OWNER] Migrate counters** with README Manual counter migration, then confirm the totals in the deployed launcher. This step is owner-run under Global Constraints.

**Rollback before the Retirement Task:** restore replaced deployment files from this release's recorded backup and trash only files this deployment added. Follow [the deployment guide's backup-handling rules](local_deployment_sync.md#rollback); counter reconciliation follows the State Task's Manual counter migration guidance. Restoring the prior runtime produces audit drift against the merged migration on `main`; report it. An audit-clean rollback also needs an owner-authorized source revert, validation and redeployment. Do not revert source automatically. Retain backups under the Rollback retention decision in [the retirement plan](retire_venvs_for_uv_implementation_plan.md#home-residue-cleanup-record).

### Task 5: Retirement Task

**Files:**
- Delete: `transcription/ui.sh`, `transcription/setup.sh`, `transcription/run.sh`, `transcription/m4a-run.sh`, `transcription/help.sh`
- Modify: `transcription/README.md`, `agents.md`, `docs/transcription_uv_decision.md`, `docs/post_uv_retirement_implementation_plan.md`, `docs/retire_venvs_for_uv_implementation_plan.md`

**Interfaces:**
- Consumes: a verified Release Task deployment.
- Produces: the wrappers and the venvs named below are gone from the source and deployed copies, and the audit passes.

- [ ] **Step 1: [OWNER] Confirm the deployed launcher has served real use** and that the Other wrapper callers expectation in Owner Decisions still holds.

- [ ] **Step 2: In a new branch, delete the wrappers and update docs.**
  - Remove README Legacy wrappers and the remaining wrapper text.
  - In `agents.md`, remove the `transcription/setup.sh` example from Python as an agent.
  - Keep the Transcription `.gitignore` entries, since old counter files may remain in the source checkout.
  - Record the outcome with a link to this plan in the decision record, the Transcription row of `docs/post_uv_retirement_implementation_plan.md`'s execution record and `docs/retire_venvs_for_uv_implementation_plan.md`'s Transcription Migration section. In the latter file also update the actual exclusion under Global Constraints and search its other Transcription exclusions: retain historical actions as history, but make current permission point at this plan's Retirement gate, without marking removal complete before it happens.

- [ ] **Step 3: Verify.** Search `transcription/README.md` and `agents.md` for the Retirement Delete-list filenames and inspect matches in context: none may instruct users to run a deleted Transcription wrapper. Verify the updated Test environment entry still names *Self-test*. Run *Guard check* and *Self-test*; expect no failures or skips.

- [ ] **Step 4: Commit** only under Global Constraints' explicit authorization rule.

- [ ] **Step 5: [OWNER] Authorize the PR, merge and deployment.** After the Top-level home project copies pattern, trash each wrapper from `~/transcription`. Expected: `zsh tools/check_local_deployments.zsh` reports no drift, including its stale formerly tracked file count.

- [ ] **Step 6: [OWNER] Authorize venv removal and confirm no interface is running.** Review maintained launcher and wrapper callers against Owner Decisions' Other wrapper callers expectation. For a bounded text check, search tracked `.sh` and `.py` source and the extensionless launcher for `venv`, then their deployed counterparts; omit environment trees and runtime data, and report the paths searched. Resolve runtime dependencies found before removing anything. Then trash `~/transcription/venv` and the original source checkout's `transcription/venv`; do not mistake a feature worktree for that checkout. Report differently named environments instead of removing them.

- [ ] **Step 7: Final check.** Run `UV_PYTHON_DOWNLOADS=never ~/transcription/transcription --help` and the deployment audit, and report the removed paths.

**Recovery after the Retirement Task:** the Release Task's rollback source/audit distinction also applies. Restore wrappers from the pre-retirement revision and environments from the Trash only with owner authorization; do not run the retired setup script. For its destructive behavior, see `transcription/setup.sh` in the pre-retirement revision. Validate the restored runtime before use; a missing or broken environment requires a separately authorized recovery approach.
