# Packet 10 Validation Audit

Assessed on 2026-03-10 against the live repository state.

## Outcome

Packet `10` is `validated`.

## Scope Check

- Packet implementation changes stayed inside the packet-10 allowed surface plus the expected tracker/audit updates.
- I did not find packet-scope code changes outside:
  - `switchyard`
  - `README.md`
  - `cognitive_switchyard/__main__.py`
  - `cognitive_switchyard/cli.py`
  - `cognitive_switchyard/config.py`
  - `cognitive_switchyard/pack_loader.py`
  - `cognitive_switchyard/bootstrap.py`
  - `cognitive_switchyard/builtin_packs/`
  - `tests/test_bootstrap_smoke.py`
  - `tests/test_cli.py`
- Unrelated worktree items were present (`audits/full_suite_verification_after_packet_08.*`, `tmp_packet08_probe/`, and older planning docs) and were ignored because they are outside packet `10` scope.

## Finding Repaired During Validation

### [Correctness] Finding #1: Root launcher dropped non-zero CLI exit codes

- **Severity**: Medium
- **Category**: Correctness & Safety
- **Evidence**:
  - [switchyard](/Users/example/source/utilities/cognitive_switchyard/switchyard#L14) called `main()` directly instead of exiting with its return code.
  - [cognitive_switchyard/cli.py](/Users/example/source/utilities/cognitive_switchyard/cognitive_switchyard/cli.py#L124) returns `1` from `start` when startup preflight fails, so the root launcher masked real packet-10 startup failures.
  - [tests/test_bootstrap_smoke.py](/Users/example/source/utilities/cognitive_switchyard/tests/test_bootstrap_smoke.py#L144) now covers the failing `./switchyard start ...` path with a non-executable built-in pack hook.
- **Impact**:
  - Operator-facing `./switchyard start` could report success to shells and scripts even when startup failed.
  - Packet-10's headless launcher surface was therefore unreliable for automation and smoke validation.
- **Recommended Fix**:
  - Exit the root launcher with `raise SystemExit(main())`.
  - Keep a launcher-level regression test that asserts a non-zero exit on startup failure.
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**:
  - `./switchyard` returns the same non-zero code as `python -m cognitive_switchyard` for packet-10 startup failures.
  - Help/path smoke commands still return `0`.

## Validation Evidence

- Packet-local tests passed:

```bash
.venv/bin/python -m pytest tests/test_cli.py tests/test_bootstrap_smoke.py -v
```

- Result: `12 passed`

- Adjacent regressions passed:

```bash
.venv/bin/python -m pytest tests/test_config.py -v
.venv/bin/python -m pytest tests/test_pack_loader.py -v
.venv/bin/python -m pytest tests/test_orchestrator.py -k 'start_session_runs_planning_resolution_then_hands_off_to_execution_when_no_review_items_exist' -v
```

- Results: `3 passed`, `8 passed`, and `1 passed`

- Direct launcher smoke confirmed the repaired behavior:

```bash
./switchyard --runtime-root <tmp> --builtin-packs-root <tmp>/builtin start --pack claude-code --session demo
```

- Result after repair: exit code `1` for a deterministic startup-preflight failure.

## Acceptance Summary

- Canonical help/path contracts still pass through both `python -m cognitive_switchyard` and `./switchyard`.
- First-run runtime bootstrap creates the runtime home, `packs/`, `sessions/`, `config.yaml`, and syncs bundled built-in packs.
- Built-in pack sync is non-destructive by default, while `reset-pack` and `reset-all-packs` restore factory copies.
- `start` creates or resumes a session and delegates into the existing orchestration runtime.
- No packet-11 HTTP/WebSocket/UI surface was added.
