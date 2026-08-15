# Standalone Build Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Model Sentinel's scheduled runtime fully standalone while making stale zipapp deployments detectable, attributable, and safe to replace.

**Architecture:** Add a format-only build identity module whose checkout defaults can be overridden by a generated, staged-only metadata module inside the zipapp. Surface the identity through a configuration-free top-level `--version`, `healthcheck`, and scan startup logs. Extend the atomic standalone installer with deterministic content hashing, pre-replacement smoke verification, and a read-only `--check` mode, then rebuild and verify the existing scheduled artifact.

**Tech Stack:** Python 3.11+ standard library, argparse, zipapp, Bash, Git, macOS `shasum`, pytest.

---

## Scope and binding decisions

The approved design is in
`docs/superpowers/specs/2026-08-15-standalone-build-provenance-design.md`.
The executor must preserve these decisions:

- The scheduled job remains independent of the checkout and continues to run
  `~/Library/Scripts/model-sentinel`.
- The exact staged Python contents, not a version string or Git revision, are
  authoritative for freshness.
- Git revision and build time are diagnostic context only.
- `--version` must not load config, create runtime directories, access the
  database, read credentials, or contact a provider.
- `--check` is read-only with respect to the install target and runtime home.
- Candidate execution must succeed before the installer atomically replaces
  an existing target.
- No provider, report, storage, or ordering behavior changes belong in this
  work.

The generated constants are kept in a staged-only
`model_sentinel/_packaged_build.py`, imported opportunistically by the tracked
`model_sentinel/build_info.py`. This is the concrete implementation of the
design's “replace staged metadata constants” requirement: executable helper
logic remains tracked once, while only inert constants are generated. The
generated module must never be written into the checkout.

## File map

- Create `model_sentinel/build_info.py`
  - Own checkout defaults, packaged-constant fallback, identity formatting,
    and entrypoint resolution.
- Modify `model_sentinel/cli.py`
  - Add top-level `--version`, preserve it through default-scan normalization,
    add the healthcheck row, and log runtime identity before scan validation.
- Modify `install_standalone.sh`
  - Parse install/check modes, stage sources, compute deterministic source
    identity, generate `_packaged_build.py`, smoke-test candidates, compare
    installed artifacts, and preserve atomic replacement.
- Create `tests/test_build_info.py`
  - Unit coverage for formatting, hash abbreviation, checkout defaults, and
    entrypoint resolution.
- Modify `tests/test_cli.py`
  - CLI, healthcheck, and scan-log contracts.
- Create `tests/test_install_standalone.py`
  - End-to-end installer/check/preservation coverage using only temporary,
    conspicuously synthetic files.
- Modify `README.md`
  - Document point-in-time standalone semantics, version inspection, rebuild,
    and freshness check workflow.
- Modify `docs/LAUNCHD.md`
  - Document the standalone target's update responsibility and diagnostic
    commands.
- Modify
  `docs/superpowers/specs/2026-08-15-standalone-build-provenance-design.md`
  - Clarify that generated constants live in staged-only
    `_packaged_build.py`; do not alter approved behavior or scope.

## Task 1: Build identity and configuration-free `--version`

**Files:**

- Create: `model_sentinel/build_info.py`
- Modify: `model_sentinel/cli.py` (`main`, `build_parser`,
  `_normalize_argv_for_default_scan`)
- Create: `tests/test_build_info.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing build-info unit tests**

Create `tests/test_build_info.py` with focused tests for the public helper
contract:

- source-checkout defaults format as
  `build=source revision=unpackaged source_sha256=unpackaged built=unpackaged`;
- a synthetic 64-character lowercase hash is abbreviated to its first 12
  characters when `full_hash=False` and remains complete when
  `full_hash=True`;
- `runtime_entrypoint("./synthetic-model-sentinel")` returns the absolute,
  expanded path without requiring that the file exist;
- `runtime_entrypoint("")` returns the literal `unknown`, not the working
  directory.

The intended interfaces are:

```python
def format_build_info(*, full_hash: bool = False) -> str: ...

def runtime_entrypoint(argv0: str | None = None) -> str: ...
```

Use `monkeypatch` against module constants for packaged examples. Use only
synthetic revision and hash values.

- [ ] **Step 2: Run the new unit module and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_build_info.py -v
```

Expected: collection fails because `model_sentinel.build_info` does not exist.
Confirm this is the only failure cause before proceeding.

- [ ] **Step 3: Implement the build-info module minimally**

Create `model_sentinel/build_info.py` with these constants and resolution
rules:

```python
try:
    from ._packaged_build import (
        BUILD_KIND,
        BUILD_REVISION,
        BUILD_SOURCE_HASH,
        BUILD_TIME_UTC,
    )
except ImportError:
    BUILD_KIND = "source"
    BUILD_REVISION = "unpackaged"
    BUILD_SOURCE_HASH = "unpackaged"
    BUILD_TIME_UTC = "unpackaged"
```

`format_build_info` returns four space-separated `key=value` fields in the
fixed order `build`, `revision`, `source_sha256`, `built`. Only abbreviate
`BUILD_SOURCE_HASH` when it is a real 64-character digest and `full_hash` is
false; never abbreviate `unpackaged` or `unknown`.

`runtime_entrypoint` uses the supplied `argv0`, or `sys.argv[0]` when omitted.
Return `unknown` for an empty value; otherwise return
`str(Path(value).expanduser().resolve())`. Do not inspect `sys.executable`.

- [ ] **Step 4: Run the build-info tests and verify GREEN**

Run the command from Step 2.

Expected: every test in `tests/test_build_info.py` passes.

- [ ] **Step 5: Write failing CLI version tests**

In `tests/test_cli.py`, add tests that call `cli.main(["--version"])` and pin:

- argparse exits with code 0;
- stdout starts with `model_sentinel 0.1.0` and contains the complete
  `format_build_info(full_hash=True)` string;
- stderr is empty;
- a nonexistent `MODEL_SENTINEL_HOME` remains nonexistent, proving the command
  did not load configuration or initialize runtime state;
- `_normalize_argv_for_default_scan(["--version"])` returns `['--version']`,
  while an existing scan flag such as `--no-notify` is still rewritten as
  `['scan', '--no-notify']`.

- [ ] **Step 6: Run the CLI version tests and verify RED**

Run the exact new node IDs with `.venv/bin/python -m pytest ... -v`.

Expected: the normalization assertion fails and argparse reports
`unrecognized arguments: --version` under the scan parser.

- [ ] **Step 7: Add the top-level version action**

In `model_sentinel/cli.py`:

- import `__version__` from the package;
- import `format_build_info` from `build_info`;
- add a top-level parser argument using argparse's `action="version"` and the
  exact value
  `f"model_sentinel {__version__} {format_build_info(full_hash=True)}"`;
- special-case `--version` in `_normalize_argv_for_default_scan` so it remains
  a top-level option;
- leave current default-scan behavior for every other option unchanged.

Do not manually print or catch `SystemExit`; argparse must terminate before
`load_config` is reachable.

- [ ] **Step 8: Run focused and adjacent CLI tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_build_info.py tests/test_cli.py -v
```

Expected: all tests in both modules pass with no warnings or stderr noise.

- [ ] **Step 9: Review, stage, perform the sensitive-data audit, and commit**

Run `git diff --check`, inspect the complete diff, then stage only the Task 1
files. Inspect `git diff --cached --name-only` and the complete
`git diff --cached` for sensitive data before committing.

Suggested commit:

```text
Add Model Sentinel build identity
```

## Task 2: Surface runtime identity in healthcheck and scan logs

**Files:**

- Modify: `model_sentinel/cli.py` (`run_healthcheck`, `run_scan`)
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing healthcheck tests**

Extend the existing healthcheck coverage to assert:

- text output contains `OK      runtime_build:`;
- the detail contains `build=source`, `source_sha256=unpackaged`, and
  `executable=`;
- JSON healthcheck output contains exactly one object whose `check` is
  `runtime_build`, whose status is `ok`, and whose detail contains the same
  identity fields;
- the informational row does not change a successful healthcheck's exit code.

Reuse `_write_config_files` and synthetic credential values already used by
the test module. Do not assert the machine-specific absolute pytest path;
assert only that the resolved `executable=` field is present and nonempty.

- [ ] **Step 2: Run the new healthcheck nodes and verify RED**

Expected: both tests fail because no `runtime_build` check exists.

- [ ] **Step 3: Add the informational healthcheck row**

Import `runtime_entrypoint` alongside `format_build_info`. At the start of
`run_healthcheck`, append:

```python
{
    "check": "runtime_build",
    "status": "ok",
    "detail": (
        f"{format_build_info(full_hash=False)} "
        f"executable={runtime_entrypoint()}"
    ),
}
```

This row must be present even when later configuration loading fails. It must
not inspect a checkout or claim freshness.

- [ ] **Step 4: Run healthcheck tests and verify GREEN**

Run all healthcheck-related tests in `tests/test_cli.py` using `-k healthcheck`.

Expected: every selected test passes, including warning and error exit-status
tests.

- [ ] **Step 5: Write failing scan-log ordering tests**

Add one success-path or baseline-missing test and one missing-credential test
that capture stderr and assert:

- `Runtime build:` appears exactly once;
- it contains the short build identity plus `executable=`;
- it appears before `Scanning providers:` on the normal path;
- it appears before `Missing required credential environment variables:` on
  the credential-error path.

Use the existing temporary config helper. Never include or print an actual
credential.

- [ ] **Step 6: Run the new scan-log nodes and verify RED**

Expected: both fail because the runtime line is absent.

- [ ] **Step 7: Log identity at the start of `run_scan`**

Make the first operation in `run_scan`:

```python
logger.info(
    "Runtime build: %s executable=%s",
    format_build_info(full_hash=False),
    runtime_entrypoint(),
)
```

It must precede `validate_selected_providers`, credential validation, baseline
resolution, and provider access. Do not log environment variables or config
contents.

- [ ] **Step 8: Run the complete CLI test module**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli.py -v
```

Expected: all CLI tests pass.

- [ ] **Step 9: Review and commit Task 2**

Perform `git diff --check`, complete unstaged/staged reviews, and the mandatory
sensitive-data audit. Stage only `model_sentinel/cli.py` and
`tests/test_cli.py`.

Suggested commit:

```text
Report runtime build identity
```

## Task 3: Make the standalone installer self-identifying and checkable

**Files:**

- Modify: `install_standalone.sh`
- Create: `tests/test_install_standalone.py`

- [ ] **Step 1: Write the temporary-project integration-test helper**

In `tests/test_install_standalone.py`, write a helper that creates a synthetic
installer project beneath `tmp_path` by copying only:

- `install_standalone.sh`;
- root `__main__.py`;
- `providers.env.template`, `settings.env.template`, and
  `launchd.env.template`;
- the `model_sentinel/` Python package.

Set the copied installer executable. All subprocess environments must set
`MODEL_SENTINEL_HOME` to a temporary directory and prepend the active venv's
bin directory (`Path(sys.executable).parent`) to `PATH`, ensuring the script's
`python3` is the project virtual-environment interpreter rather than system or
Homebrew Python.

- [ ] **Step 2: Write failing install/version/check integration tests**

Add tests that:

1. install to a temporary target and assert exit 0;
2. invoke the target with `--version` and assert `build=standalone`,
   `revision=unknown` (the copied fixture is outside Git), a 64-character
   lowercase `source_sha256`, and a UTC `built=...Z` field;
3. run `install_standalone.sh --check <target>` and assert exit 0 plus a
   `current` message;
4. record the target bytes and modification time, append a synthetic comment
   to the copied `model_sentinel/reporting.py`, rerun `--check`, and assert exit
   1 plus `stale`, with target bytes and modification time unchanged;
5. call `--check` on a missing target and assert exit 1 without creating the
   target directory or runtime home;
6. pass excess or unknown options and assert exit 2 with usage text.

- [ ] **Step 3: Run the installer tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_install_standalone.py -v
```

Expected: failures show that `--check` is treated as a target path and that
the built zipapp does not recognize `--version`/contain packaged provenance.

- [ ] **Step 4: Refactor argument parsing without changing install behavior**

In `install_standalone.sh`, parse `install` as the default action and
`--check` as the only alternate action. Accept at most one target after the
action. `-h`/`--help` exits 0; invalid options or extra arguments exit 2.

Move `mkdir -p "$RUNTIME_HOME" "$TARGET_DIR"` and target-directory `mktemp`
inside install mode. Check mode may create and remove a temporary staging
directory under `${TMPDIR:-/tmp}`, but must not create the runtime home,
target, or target directory.

- [ ] **Step 5: Implement deterministic staged-source hashing**

After `stage_zipapp_source`, calculate `SOURCE_HASH` over every staged `*.py`
except the generated `model_sentinel/_packaged_build.py`. Use this exact
load-bearing pipeline so random staging paths are not part of the digest:

```bash
SOURCE_HASH="$({
  cd "$STAGING_DIR"
  find . -type f -name '*.py' \
    ! -path './model_sentinel/_packaged_build.py' \
    -exec shasum -a 256 {} \; \
    | LC_ALL=C sort \
    | shasum -a 256 \
    | awk '{print $1}'
})"
```

Validate the result against `^[0-9a-f]{64}$`; abort before touching the target
if validation fails.

Resolve Git context with `git -C "$SCRIPT_DIR" rev-parse --short=12 HEAD` when
available, otherwise `unknown`. Append `+modified` when
`git -C "$SCRIPT_DIR" status --porcelain -- .` is nonempty. Set build time
with `date -u '+%Y-%m-%dT%H:%M:%SZ'`.

- [ ] **Step 6: Generate staged-only packaged constants**

Write `$STAGING_DIR/model_sentinel/_packaged_build.py` with only four Python
string assignments:

```python
BUILD_KIND = "standalone"
BUILD_REVISION = "<resolved revision>"
BUILD_SOURCE_HASH = "<complete source hash>"
BUILD_TIME_UTC = "<UTC timestamp>"
```

The inputs are constrained to hex, `unknown`, `+modified`, and the fixed UTC
timestamp format before interpolation. Do not embed paths, usernames, Git
author data, environment values, or runtime configuration.

- [ ] **Step 7: Implement read-only freshness comparison**

For `--check`:

- return 1 with `stale: standalone target is missing` if the target is not an
  executable file;
- capture `<target> --version` stdout/stderr without allowing `set -e` to abort
  before an actionable message;
- require the exact token `source_sha256=$SOURCE_HASH` in successful output;
- return 0 and print `current` when it matches;
- otherwise return 1 and print `stale`, the expected hash, and the target's
  reported version output (if any).

Do not seed config files or call `mkdir` in this branch.

- [ ] **Step 8: Smoke-test before atomic replacement**

In install mode, build the candidate at the existing same-directory temporary
target, mark it executable, and run `<temp-target> --version`. Verify both exit
0 and the exact expected source-hash token before `mv`. On failure, exit
nonzero and let the cleanup trap remove the candidate and staging directory;
the old target must remain untouched.

Only after verification:

1. atomically `mv` the candidate to the target;
2. seed config templates with the existing `copy_if_missing` behavior;
3. print the installed version output;
4. print the exact follow-up check command and the reminder to run it after
   repository updates.

- [ ] **Step 9: Add the failed-candidate preservation test**

Create an executable sentinel target with conspicuously synthetic contents.
Corrupt the copied project's `model_sentinel/cli.py` with a deliberate import
failure, run install, and assert:

- nonzero exit;
- output explains candidate smoke verification failed;
- original target bytes and mode remain unchanged.

This test pins operation ordering rather than mocking `mv` or zipapp.

- [ ] **Step 10: Run installer tests until GREEN, then validate shell syntax**

Run:

```bash
.venv/bin/python -m pytest tests/test_install_standalone.py -v
bash -n install_standalone.sh
```

Expected: all installer tests pass and `bash -n` exits 0 with no output.

- [ ] **Step 11: Run adjacent CLI/build tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_build_info.py \
  tests/test_cli.py \
  tests/test_install_standalone.py \
  -v
```

Expected: every selected test passes.

- [ ] **Step 12: Review and commit Task 3**

Review shell quoting carefully, run `git diff --check`, and inspect both the
unstaged and staged diffs. The sensitive-data audit must confirm that generated
build metadata, local paths, runtime files, and temporary artifacts are not
tracked.

Suggested commit:

```text
Verify standalone deployment freshness
```

## Task 4: Document the standalone update contract

**Files:**

- Modify: `README.md` (`Standalone Install`, `Help`, `Validate Runtime Readiness`)
- Modify: `docs/LAUNCHD.md` (`Seed`, `Check Status`, `Notes`)
- Modify:
  `docs/superpowers/specs/2026-08-15-standalone-build-provenance-design.md`
  (`Build Metadata` implementation clarification)

- [ ] **Step 1: Update README operating instructions**

Document these commands and their expected intent:

```bash
./install_standalone.sh
./install_standalone.sh --check
~/Library/Scripts/model-sentinel --version
~/Library/Scripts/model-sentinel healthcheck
```

State explicitly that the zipapp is a point-in-time copy, repository pulls do
not update it, `--check` is read-only, and the installer must be rerun after
source updates. Explain that `--version` reports product version plus artifact
provenance and does not require config or credentials.

- [ ] **Step 2: Update launchd documentation**

In the standalone-target note, state that launchd needs no reload when the
same zipapp path is atomically replaced. Add a diagnostic sequence of
`--check`, installed `--version`, installed `healthcheck`, and the existing
launchd logs. Keep the repo-local default workflow distinct from the current
standalone customization.

- [ ] **Step 3: Clarify the design's generated-module detail**

Update only the implementation wording: tracked helpers/defaults live in
`build_info.py`; the installer adds `_packaged_build.py` to staging and the
source hash excludes that generated constants file. Do not change the approved
goals, failure semantics, or acceptance criteria.

- [ ] **Step 4: Review documentation and commit**

Run `git diff --check`. Check commands, file names, option spelling, exit codes,
and the no-checkout-at-runtime guarantee against the implementation. Perform
the staged sensitive-data audit.

Suggested commit:

```text
Document standalone deployment checks
```

Documentation-only edits do not require an additional test run at this task
boundary; the mandatory complete suite runs next.

## Task 5: Complete verification, deploy, and prove the installed fix

**Files:** No source edits expected. If verification reveals a defect, return
to the relevant TDD task, add or correct the failing test first, implement one
root-cause fix, and repeat all verification from this task.

- [ ] **Step 1: Run static repository checks**

Run:

```bash
git diff --check
bash -n install_standalone.sh setup.sh setup_launchd.sh install_launchd.template.sh
```

Expected: all commands exit 0 and `bash -n` emits no output.

- [ ] **Step 2: Run the complete test suite**

Run:

```bash
.venv/bin/python -m pytest
```

Expected: every collected test passes with zero failures. Repository policy
forbids proceeding to deployment if any test fails; investigate and fix every
failure before continuing.

- [ ] **Step 3: Re-run the pricing-order regression nodes explicitly**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_provider_profiles.py::test_profiles_define_provider_owned_pricing_field_order \
  tests/test_change_render.py::test_pricing_field_sort_key_uses_profile_order \
  tests/test_reporting.py::test_html_cards_use_profile_pricing_field_order_across_opposite_impacts \
  tests/test_reporting.py::test_human_scan_reports_use_profile_pricing_field_order \
  -v
```

Expected: all four pass. This confirms the checkout being packaged still owns
the intended `Input`, cache, `Output` contract.

- [ ] **Step 4: Inspect repository and staged state for sensitive data**

Require a clean working tree after all intended commits. Inspect the complete
commit range and tracked file list. Confirm that no generated
`_packaged_build.py`, zipapp, runtime config, reports, logs, database, absolute
personal paths, or secrets entered the repository.

- [ ] **Step 5: Check the existing target before replacement**

Run with the venv first in `PATH`:

```bash
PATH="$PWD/.venv/bin:$PATH" ./install_standalone.sh --check
```

Expected before deployment: exit 1 with `stale`, because the July 26 target
lacks the current source hash and provenance interface. Record the output as
the red deployment check; do not treat it as a test-suite failure.

- [ ] **Step 6: Atomically rebuild the scheduled standalone target**

Run:

```bash
PATH="$PWD/.venv/bin:$PATH" ./install_standalone.sh
```

Expected: candidate `--version` verification succeeds, the target is replaced,
existing runtime config files are retained, and the installer prints the new
standalone identity. Do not edit or reload the LaunchAgent: its runner already
executes this target path on each invocation.

- [ ] **Step 7: Verify installed freshness and identity**

Run:

```bash
PATH="$PWD/.venv/bin:$PATH" ./install_standalone.sh --check
~/Library/Scripts/model-sentinel --version
```

Expected: check exits 0 with `current`; version reports
`build=standalone`, the current commit revision, a 64-character source hash,
and UTC build time.

- [ ] **Step 8: Run installed healthcheck in the scheduled environment**

Use Bash exactly as the LaunchAgent runner does, without printing environment
values:

```bash
/bin/bash -c 'source "$HOME/.model_sentinel/launchd.env"; exec "$HOME/Library/Scripts/model-sentinel" healthcheck'
```

Expected: `runtime_build` identifies the standalone target, all required
readiness checks are visible, and exit status is 0. If a check fails, report
and resolve it before claiming deployment success; never expose credential
values.

- [ ] **Step 9: Prove the installed artifact contains semantic pricing order**

From a directory outside the checkout, run the venv interpreter with a
configuration-free synthetic assertion that prepends the zipapp to `sys.path`,
imports `OPENROUTER_PROFILE` and `pricing_field_sort_key`, sorts:

```text
pricing.completion
pricing.input_cache_read
pricing.prompt
```

and requires this result:

```text
pricing.prompt
pricing.input_cache_read
pricing.completion
```

Use `.venv/bin/python` by absolute path; do not run bare Python. Also inspect
the archive with `unzip -p` to confirm `_pricing_rows_by_impact` is absent from
embedded `reporting.py`. This verification is read-only and must not run or
save a provider scan.

- [ ] **Step 10: Confirm launchd still targets the rebuilt artifact**

Read `~/.model_sentinel/run_model_sentinel_launchd.sh` and confirm its final
exec target resolves to `~/Library/Scripts/model-sentinel`. Do not print or
source `launchd.env` during this check. No LaunchAgent mutation is expected.

- [ ] **Step 11: Final handoff evidence**

Report:

- commit IDs and the files changed;
- complete-suite test count and exit status from the fresh run;
- focused pricing regression results;
- pre-deploy stale and post-deploy current checks;
- installed `--version` provenance without local-sensitive values;
- installed healthcheck status;
- installed semantic-order smoke result;
- confirmation that runtime state and LaunchAgent configuration were not
  modified.

Do not claim completion if any test, check, healthcheck, or installed-artifact
assertion fails.
