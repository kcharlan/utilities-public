# Packet 10 - CLI, Bootstrap, and Built-In Pack Sync

## Why This Packet Exists

The engine internals are useful now, but the validated user-facing surface is still a packet-`00` scaffold that only prints canonical paths. Before packet `11` adds a server, the project needs a real local entrypoint that can bootstrap dependencies, materialize runtime defaults, sync built-in packs, and invoke the already-validated orchestration runtime without requiring manual repository plumbing.

This packet turns the current thin launcher into the first real operator surface while keeping network services and UI work out of scope.

## Scope

- Add the self-bootstrapping entrypoint that creates the private runtime venv and re-execs into it when third-party dependencies are missing.
- Create the canonical runtime home, packs directory, and default `config.yaml` on first bootstrap using the playbook's `~/.cognitive_switchyard*` contract rather than the design doc's legacy `~/.switchyard*` paths.
- Ship at least one minimal built-in pack inside the repository and sync built-in packs into the runtime packs directory without overwriting customized local copies by default.
- Add explicit pack reset flows:
  - reset one built-in pack
  - reset all built-in packs
- Expand the CLI from `paths` into a headless operator surface that can:
  - list runtime packs
  - sync/reset built-in packs
  - create or resume a session and hand it to the existing packet-`08` start path
- Keep the root `switchyard` launcher as a thin shim that delegates to the package entrypoint.

## Non-Goals

- No FastAPI server, `serve` command, REST endpoints, WebSocket handling, or SPA assets.
- No packet `11` transport contracts or packet `12` UI behavior.
- No comprehensive built-in pack catalog; this packet only needs the minimum built-in pack set required to prove sync and headless startup.
- No settings API or UI editing flow for `config.yaml`.
- No pack-author tooling or operator documentation beyond the minimal README/help updates required for the validated CLI surface.

## Relevant Design Sections

- `4.5 Pack Distribution`
- `6.4 Global Settings`
- `7.1 Module Structure`
- `7.2 Self-Bootstrapping`
- `7.4 Main Orchestration Loop` only as needed to wire the CLI into the existing runtime
- `9. Implementation Stages` notes about the operator-facing startup path
- `docs/implementation_packet_playbook.md` canonical contract decisions for package name and runtime paths

## Allowed Files

- `switchyard`
- `README.md`
- `cognitive_switchyard/__main__.py`
- `cognitive_switchyard/cli.py`
- `cognitive_switchyard/config.py`
- `cognitive_switchyard/orchestrator.py`
- `cognitive_switchyard/pack_loader.py`
- `cognitive_switchyard/state.py`
- `cognitive_switchyard/bootstrap.py`
- `cognitive_switchyard/builtin_packs/`
- `tests/test_bootstrap_smoke.py`
- `tests/test_cli.py`
- `tests/fixtures/builtin_packs/`

## Tests To Write First

- `tests/test_cli.py::test_bootstrap_creates_runtime_home_default_config_and_builtin_packs_when_dependencies_are_available`
- `tests/test_cli.py::test_sync_builtin_packs_is_non_destructive_for_existing_runtime_customizations`
- `tests/test_cli.py::test_reset_pack_restores_factory_copy_for_one_builtin_pack`
- `tests/test_cli.py::test_reset_all_packs_restores_all_builtin_packs_but_keeps_custom_only_runtime_packs`
- `tests/test_cli.py::test_start_command_creates_or_resumes_session_and_invokes_existing_orchestrator_pipeline`
- `tests/test_bootstrap_smoke.py::test_help_and_paths_continue_to_report_canonical_cognitive_switchyard_contracts`

## Implementation Notes

- Put bootstrap logic in a dedicated module so `cli.py` can call it before importing optional third-party dependencies. Packet `10` should follow the repo's self-bootstrapping pattern and use `os.execv()` for re-exec.
- Make bootstrap and pack-sync helpers directly unit-testable. Tests should be able to override the runtime home, built-in-pack source root, and dependency-install command path without hitting the network.
- The first-pass default settings file should use the canonical runtime path and the design's default keys: `retention_days`, `default_planners`, `default_workers`, and `default_pack`.
- Keep built-in pack sync source-of-truth inside the repository or package tree so runtime pack installation does not depend on external downloads.
- Runtime pack discovery must read from `~/.cognitive_switchyard/packs` only. The bundled built-in directory is a source for sync/reset, not a second live search path.
- The headless `start` command should delegate to existing `StateStore`, pack loading, and `start_session()` helpers. Do not duplicate orchestration logic inside CLI handlers.
- Do not introduce `serve` placeholders that import nonexistent packet-`11` modules. This packet should validate the CLI surface that already has real backing behavior today.

## Acceptance Criteria

- Running `./switchyard --help` and `./switchyard paths` still works and reflects the canonical `cognitive_switchyard` package/runtime contracts.
- On first bootstrap in a clean home directory, the CLI creates the runtime home, `packs/`, `sessions/`, and default `config.yaml`, then syncs bundled built-in packs into the runtime packs directory.
- A subsequent bootstrap or pack sync does not overwrite an existing runtime copy of a built-in pack unless the user explicitly requests `reset-pack` or `reset-all-packs`.
- `reset-pack <name>` restores one built-in pack to its bundled contents, and `reset-all-packs` restores all bundled packs while leaving custom non-built-in runtime pack directories intact.
- The CLI can list packs from the runtime packs directory and can create or resume a session using a synced built-in pack plus the packet-`08` orchestration runtime.
- Bootstrap behavior is covered by unit tests that mock the install/re-exec path rather than requiring a real pip install during validation.
- No HTTP server, WebSocket handler, or embedded SPA module is added in this packet.

## Validation Focus

- Bootstrap correctness with canonical path names and no legacy `~/.switchyard*` regressions.
- Non-destructive pack sync behavior versus explicit reset behavior.
- Headless CLI startup wiring into existing packet `08` orchestration without duplicating logic.
- Smoke coverage for the root launcher plus package entrypoint.
- Regression checks that packet `00` path-contract tests and packet `08` orchestration tests still pass.
