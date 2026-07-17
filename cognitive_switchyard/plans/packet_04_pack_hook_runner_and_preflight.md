# Packet 04: Pack Hook Runner and Preflight

## Why This Packet Exists

After packet `03`, the next runtime dependency is safe, deterministic pack-side execution. The orchestrator cannot dispatch any real work until pack hooks can be discovered, permission-checked, and invoked consistently. This packet isolates that contract before long-running worker subprocesses and timeout management arrive in packet `05`.

## Scope

- Extend pack runtime support from pure manifest parsing to executable hook resolution.
- Discover conventional hook executables under `scripts/` for short-lived pack hooks (`preflight`, `isolate_start`, `isolate_end`, `resolve`) and resolve manifest-declared script paths needed by later packets.
- Add the orchestrator-owned executable-bit preflight that scans every file in a pack's `scripts/` directory and reports deterministic `chmod +x` remediation hints using canonical `~/.cognitive_switchyard/packs/<pack-name>/...` paths.
- Run pack prerequisite checks declared in `pack.yaml` and collect structured pass/fail results with captured stdout/stderr.
- Run an optional pack `scripts/preflight` hook after the executable-bit scan and prerequisite checks succeed.
- Add reusable short-lived hook-invocation helpers that execute scripts directly with positional arguments, controlled working directories, and structured results/errors.

## Non-Goals

- No long-running worker `Popen` lifecycle, progress parsing, log streaming, kill handling, or timeout enforcement; packet `05` owns those behaviors.
- No planner/resolver runtime integration or execution-pipeline dispatch decisions; packet `08` decides when hooks are invoked in the live pipeline.
- No global verification loop or auto-fix behavior; packets `09` and `05` own those flows.
- No built-in pack syncing, bootstrap copying, or operator-facing CLI/API/UI preflight surfaces; packet `10` owns installation/bootstrap behavior.
- No changes to packet-`01` manifest schema semantics beyond consuming the already-parsed fields.

## Relevant Design Sections

- `4.1 Pack Directory Structure`
- `4.2 pack.yaml Schema`
- `4.3 Lifecycle Hook Contracts`
- `7.1 Module Structure`

## Allowed Files

- `cognitive_switchyard/pack_loader.py`
- `cognitive_switchyard/models.py`
- `cognitive_switchyard/config.py`
- `cognitive_switchyard/hook_runner.py`
- `tests/test_hook_runner.py`
- `tests/test_pack_loader.py`
- `tests/conftest.py`
- `tests/fixtures/packs/**`

## Tests To Write First

- `tests/test_hook_runner.py::test_script_scan_reports_all_non_executable_files_with_canonical_chmod_hints`
- `tests/test_hook_runner.py::test_prerequisite_checks_return_structured_results_in_declared_order`
- `tests/test_hook_runner.py::test_pack_preflight_hook_runs_only_after_permission_and_prerequisite_success`
- `tests/test_hook_runner.py::test_short_lived_hook_runs_with_positional_args_and_working_directory`
- `tests/test_pack_loader.py::test_packet_01_manifest_parsing_regressions_still_pass`

## Implementation Notes

- Keep manifest loading pure. `load_pack_manifest()` should stay a filesystem-and-YAML parser; runtime hook execution belongs in a separate module or separate runtime-facing entrypoints.
- Treat hook scripts as executables, not shell snippets. Invoke them with direct argument vectors (`subprocess.run([...])`) and never via `bash -c` / `sh -c`.
- `prerequisites[].check` is the exception: it is a shell command string from `pack.yaml`, so run it as a shell command with captured stdout/stderr and explicit environment control in tests.
- Use canonical runtime-pack paths in executable-bit diagnostics even when the checked pack lives under `tests/fixtures/packs/`.
- Missing optional hooks should report cleanly through structured results or typed exceptions so later packets can branch on capability instead of catching raw filesystem errors.
- Keep `execution.command` and `verification.command` launch semantics out of this packet beyond command/hook-path resolution. Packet `05` owns long-running execution, and packet `09` owns the verification loop.
- The reference `work/` artifacts confirm the script-driven pipeline shape, but this packet should stop at preflight and short-lived hook execution. Do not pull worker progress-marker or session-orchestration behavior forward.

## Acceptance Criteria

- Pack script scans report every non-executable file in deterministic order with actionable `chmod +x` guidance rooted at `~/.cognitive_switchyard/packs/<pack-name>/...`.
- Manifest prerequisite checks return structured pass/fail results and aggregate failure state without launching any worker process.
- An optional `scripts/preflight` hook can be run after permissions and prerequisites pass, with stdout/stderr/exit code captured for the caller.
- The hook runner can execute a short-lived script directly with positional args and a specified working directory, and returns structured output without shell wrapping.
- Existing packet-`01` manifest parsing behavior continues to pass unchanged.

## Validation Focus

- `.venv/bin/python -m pytest tests/test_hook_runner.py tests/test_pack_loader.py -v`
- `.venv/bin/python -m pytest tests/test_fixture_baseline.py tests/test_bootstrap_smoke.py -v`
