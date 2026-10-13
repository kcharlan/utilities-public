# Persistent Credentials Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` when implementation is explicitly authorized, or
> `superpowers:subagent-driven-development` if the user chooses that method.
> Track the checkbox steps. This request authorizes the plan only, not execution,
> deployment, private configuration edits, commits, pushes, or PRs.

**Goal:** Let scheduled Model Sentinel scans use a persistent private credential
file, independently of whether 1Password is running, and refresh that file
explicitly without changing application code when the mount or key names change.

**Architecture:** Keep the existing environment-only source as the default and
add authoritative file mode. A shared credential resolver supplies scans and
diagnostics; a separate refresh transaction reads the configured mounted env
file or already-loaded process environment, validates selected credentials,
merges retained configured credentials, and atomically replaces the cache.
Scheduled scans never invoke refresh or 1Password.

**Tech stack:** Existing Python 3.11+ stdlib package and executable zipapp,
pytest and existing Playwright Chromium suite. File-mode security and refresh
locking target macOS/POSIX; environment mode retains its current platform scope.
No runtime dependency, SDK, beta CLI, browser UI, or new scheduled job.

**Spec:** [Credential assessment](cleanup_audit_20261013.md), including its two
approved cross-check corrections. This plan selects the first option only.

## Global constraints

- Keep provider IDs, SQLite schema, snapshots, pricing semantics, and report
  retention unchanged. Reuse existing selection, validation, notification,
  time-formatting, installer, and parsing patterns.
- Keep mutable state outside the public checkout. Use conspicuously synthetic
  fixtures and local mock provider endpoints; never extract live secrets in
  tests or record private mounts, identifiers, values, or logs in this plan.
- Preserve environment-only operation for existing users. Do not silently
  combine file credentials with inherited credentials in file mode.
- Refresh enabled providers by default. Explicit provider selection includes a
  configured disabled provider. Preserve unselected configured cached keys.
- No automatic desktop launch, login retry, GUI automation, or scan-time pipe
  access. An explicit refresh may encounter 1Password's own authorization prompt
  and its acquisition wait must time out. A failed refresh leaves the previous
  cache intact.
- Only referenced provider credentials enter the cache, never the complete
  development environment. Private parent/file modes are exactly `0700`/`0600`.
- No automatic expiry. Report cache age, but do not confuse age with provider
  validity or proof that every retained key was freshly extracted.
- Run Python through this project's `.venv/bin/python`. Existing installer and
  shebang subprocess tests must put that venv's bin directory first in PATH.
  Do not recreate its venv, install a Python, or download dependencies/browsers
  without any approval required by the standing environment rules.
- Work in the existing checkout on a local feature branch. No worktrees or
  commit steps unless requested. Full project tests are mandatory after code
  changes; a failure must be fixed or reported as a blocker.

## Review focus

1. A pipe exists but has no writer, authorizes slowly, or never closes: the
   configured timeout bounds reader communication after process creation. The
   reader is killed/reaped on timeout, with startup/cleanup overhead and no cache
   loss. This is not a deadline for the complete refresh transaction.
2. A disabled provider is refreshed explicitly: its subsequent scan works and
   the next default scan still has the other providers' credentials.
3. An inherited key is stale or is an unresolved `op://` reference: file mode
   uses only the cache; invalid selected values fail before provider requests.
4. A symlink, unsafe permissions, concurrent refresh, or interrupted write:
   refuse unsafe paths, prevent lost updates, and expose only a complete cache.
5. Offline commands and the installed zipapp: history/browse/help/version never
   acquire secrets; installed refresh needs no repo and touches no scan history.

Each condition has explicit tests in Tasks 2–5. These tests use synthetic data.

## Current code anchors

All paths below are relative to the Model Sentinel project directory.

| Existing code | Relevant contract |
| --- | --- |
| `model_sentinel/config.py:34`, `:231` | `Settings` and `load_settings(path, *, runtime_home)` |
| `model_sentinel/config.py:305` | `validate_selected_providers(providers, *, provider_id)` already includes disabled providers when explicitly selected |
| `model_sentinel/config.py:321` | `missing_credentials(providers, environ)` checks only supplied values |
| `model_sentinel/envfile.py:11` | `parse_env_file(path)` reads ordinary config files; parsing can be extracted |
| `model_sentinel/cli.py:56`, `:85`, `:130` | Command normalization, dispatch, and parser construction |
| `model_sentinel/cli.py:349`, `:408` | Credential validation and the key passed to `fetch_raw_models()` |
| `model_sentinel/cli.py:686`, `:777` | Provider inspection and healthcheck credential checks |
| `model_sentinel/reporting.py:3052`, `:3096` | Provider renderer and generic healthcheck renderer |
| `model_sentinel/providers.py:36–44` | Fetch errors currently include upstream HTTP bodies/reasons; replace that unsafe diagnostic boundary |
| `model_sentinel/cli.py:581`, `:977` | Scan-time report retention call and `_cleanup_old_reports()` |
| `install_launchd.template.sh:57–75` | Bash runner sources private `launchd.env` before execing the CLI |
| `install_standalone.sh:72–82` | Staging already copies all runtime package `*.py` files |
| `tests/test_install_standalone.py:22`, `:42` | `_copy_installer_project()` and `_installer_env()` isolate packaging and venv PATH |
| `tests/test_cli.py:296`, `tests/test_config.py:15` | Existing synthetic `_write_config_files()` helpers |

Recheck symbols before implementation; line numbers are navigation aids.

## Configuration and behavior decisions

Add these optional settings; old settings files require no edit:

| Setting | Default and validation |
| --- | --- |
| `MODEL_SENTINEL_CREDENTIAL_SOURCE` | `environment`; accept only `environment` or `file` |
| `MODEL_SENTINEL_CREDENTIAL_FILE` | `credentials.env`, relative to runtime home; blank is invalid |
| `MODEL_SENTINEL_CREDENTIAL_REFRESH_FILE` | blank/`None`; required only for a mount-based refresh |
| `MODEL_SENTINEL_CREDENTIAL_REFRESH_TIMEOUT_SECONDS` | `5`; positive finite number; reader communication timeout, not a total refresh deadline |

Expand `~` and resolve relative paths under `runtime_home`. Normalize `..`
lexically without dereferencing the final credential-file component, so later
no-symlink checks still work. Config loading does not stat or read these files.
Reject cache/refresh path equality during refresh, including inode equality when
both exist. Never create a secret file inside a Git checkout; check the
canonical parent and its ancestors for a `.git` file or directory before writes.

Continue using each provider's existing `API_KEY_ENV` as its credential name in
both environment and file mode. A name change requires a provider config edit
and refresh. A mount rename changes only
`MODEL_SENTINEL_CREDENTIAL_REFRESH_FILE`; it leaves the persistent destination
stable.

Add these commands, using `_invocation_name()` in all help/examples:

```text
model-sentinel credentials refresh
model-sentinel credentials refresh --provider synthetic_disabled
model-sentinel credentials refresh --from-environment
```

`--provider` accepts one configured provider, matching `scan`. Unknown providers
and an empty default enabled set fail before acquisition. Refresh can populate
the cache while source mode is still `environment`, allowing a staged cutover
before scheduled scans switch to file mode. `--from-environment` bypasses the
mount entirely and needs no configured refresh path; it does not launch a shell.
Success returns `0`; safe refresh errors return `2`; healthcheck retains `0`/`1`.

Cache age is the file modification time from the same opened descriptor used
to read it. Label it **cache last updated**, not per-key refresh or provider
validation time. Warn on a future modification time rather than printing a
negative age. Missing disabled-provider keys do not make healthcheck fail.

## File map and interfaces

Create `model_sentinel/credentials.py` for secret acquisition, validation,
resolution, locking, persistence, and safe error masking. Avoid a general secret
backend/plugin system. Extend existing modules for config, shared text parsing,
CLI dispatch, and reporting.

Create `tests/credential_fixtures.py`, `tests/test_credentials.py`,
`tests/test_credentials_cli.py`, `tests/test_providers.py`, and
`tests/test_launchd_credentials.py`.
The fixture helper `write_credential_config(root: Path, *, source: str = "file")
-> Path` creates an external synthetic runtime home, copies the settings
template, and writes two synthetic provider definitions: `synthetic_enabled`
(enabled) and `synthetic_disabled` (disabled), with `SYNTHETIC_ENABLED_KEY` and
`SYNTHETIC_DISABLED_KEY` and loopback/mock endpoints. Every test value includes
an unmistakable `SYNTHETIC_NOT_A_REAL_SECRET` marker. Reuse the helper across new
test files instead of copying config generation.

The credential module's shared contracts are:

```python
class CredentialError(ConfigError): ...  # safe operator-facing messages only

@dataclass(frozen=True)
class CredentialSnapshot:
    values: dict[str, str] = field(repr=False)
    source: str
    path: Path | None
    updated_at: datetime | None  # aware UTC; None for environment mode
    invalid_keys: tuple[str, ...] = ()  # configured names, never their values

def resolve_credentials(
    settings: Settings, providers: tuple[ProviderConfig, ...], *,
    runtime_paths: RuntimePaths,
    environ: Mapping[str, str],
) -> CredentialSnapshot: ...

def validate_credential_cache_location(
    settings: Settings, runtime_paths: RuntimePaths,
) -> None: ...

def read_refresh_values(path: Path, *, timeout_seconds: float) -> dict[str, str]: ...

def refresh_credentials(
    settings: Settings, providers: tuple[ProviderConfig, ...], *,
    runtime_paths: RuntimePaths,
    provider_id: str | None, from_environment: bool,
    environ: Mapping[str, str],
) -> CredentialSnapshot: ...

def redact_credential_values(message: str, values: Mapping[str, str]) -> str: ...
```

Use a `MAX_CREDENTIAL_BYTES = 65536` bound for input and cache output. Snapshot
values are never placed in report rows or serialized for diagnostics. The
resolver returns available valid values for the supplied providers; missing
keys remain absent and are checked with existing `missing_credentials()`.
Invalid present selected values are omitted and named in `invalid_keys`, so a
provider listing can diagnose one bad key without hiding the other rows.
Malformed storage or acquisition/permission failures raise `CredentialError`.
Successful refresh returns the newly published cache snapshot with source
`file`, its destination path, and the temporary file's final mtime captured
before replacement. The CLI labels the acquisition source separately from its
arguments (`--from-environment` versus the configured refresh mount).

## Task 1: Configuration and shared parsing

**Files:** Modify `model_sentinel/config.py`, `model_sentinel/envfile.py`,
`settings.env.template`, `tests/test_config.py`, `tests/test_envfile.py`.
Create `tests/credential_fixtures.py`.

**Interfaces:** Add defaulted `Settings` fields after existing required fields:
`credential_source: str = "environment"`, `credential_file: Path | None = None`,
`credential_refresh_file: Path | None = None`,
`credential_refresh_timeout_seconds: float = 5.0`. `load_settings()` always
resolves the configured/default cache path. Add
`parse_env_text(text: str, *, source: Path, strict: bool = False) -> dict[str, str]`;
make existing `parse_env_file(path)` delegate with `strict=False`.

- [ ] Before implementation edits, save the current delivery source inventory
  (`model-sentinel`, `__main__.py`, package `*.py`, and `browse` runtime resources)
  to a unique private recovery directory outside the checkout. Follow the
  installer's runtime-only inventory, excluding config/state, tests, docs,
  venvs, and bytecode. Preserve current working-tree bytes/modes, including any
  existing source edits rather than assuming HEAD captures them. Record copied
  paths and hashes for a package rollback; no commits are required. This is
  implementation-time preparation, not work authorized by writing this plan.
- [ ] Add `test_credential_settings_defaults_preserve_environment_mode`,
  `test_credential_paths_expand_home_without_following_final_symlink`, and
  parametrized rejection of unknown modes, blank cache paths, zero/negative,
  NaN/infinite deadlines. Assert config loading never opens the cache or mount.
- [ ] Add parser tests showing the old basic assignment behavior stays intact.
  Strict mode validates ASCII identifier names and rejects duplicate assignments,
  `export` prefixes, malformed quotes, and multiline assignments. Blank/comment
  lines and one-line unquoted/single/double quoted values remain supported.
  Unquoted `#`, `$`, backticks, and `$(...)` are literal data, never executed or
  expanded; quoted escapes follow the existing `_parse_value()` contract. This
  is an explicit subset, not a promise of full dotenv compatibility.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_config.py tests/test_envfile.py`.
  New tests must fail for the missing fields/text parser before implementation.
- [ ] Implement the defaults, lazy path normalization, finite acquisition-timeout check,
  and parser extraction. Strict errors include only source location/line number
  and a fixed reason; suppress exception chains containing secret source text.
  Extend `missing_credentials()`'s annotation to `Mapping[str, str]` for reuse.
- [ ] Rerun that command. Expected: all tests pass; existing env-file callers
  still have their previous grammar and duplicate-key behavior.

## Task 2: Safe cache resolution and bounded refresh acquisition

**Files:** Create `model_sentinel/credentials.py`, `tests/test_credentials.py`;
use the shared fixture from Task 1.

**Interfaces:** Produce `CredentialError`, `CredentialSnapshot`,
`resolve_credentials()`, `validate_credential_cache_location()`, `read_refresh_values()`, and
`redact_credential_values()` with the signatures above. Task 3 adds the writer.

- [ ] Add tests for environment resolution without file access, authoritative
  file mode despite a different inherited key, missing selected keys, and
  rejecting empty/whitespace-only, non-ASCII, NUL/control-character, and unresolved
  `op://` selected values. Preserve accepted key values exactly; do not trim credentials
  silently. Include `test_disabled_provider_needs_only_its_selected_key`.
- [ ] Add cache guard tests for a missing file, FIFO/directory/device instead of
  a regular file, final symlink, unsafe parent/file mode, and wrong ownership
  (mock the ownership check rather than require privileged tests). A FIFO cache
  must fail promptly without attempting to consume it.
- [ ] Add `test_resolution_rechecks_cache_location_after_report_dir_change`:
  seed a synthetic `credentials.txt` directly in test setup, with a `0700`
  parent and `0600` file outside the original report directory. Do not call
  `refresh_credentials()`; Task 3 introduces that writer. Change
  `MODEL_SENTINEL_REPORT_DIR` to its private parent, reload configuration, then
  resolve in file mode. Expect a safe placement error before opening the cache,
  with cache bytes/mtime unchanged. Include reserved config/database/launchd
  and log/debug collisions in the shared guard tests.
- [ ] Add real synthetic FIFO tests for success, no writer, partial payload
  without EOF, empty output, invalid UTF-8, invalid assignments, and data over
  65536 bytes. Use a short test deadline and generous scheduling tolerance, not
  sleeps as readiness synchronization. Test threads/processes must terminate.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_credentials.py` to establish
  failures, then implement acquisition and resolution.
- [ ] Implement `validate_credential_cache_location()` using `runtime_paths`:
  reject collisions with providers/settings/database and documented launchd
  files, locations under reports/logs/debug, root/home destinations, and Git
  checkouts. Use canonical parents while retaining the final component for
  no-follow checks. Reuse this guard on every file-mode resolution and refresh,
  before opening or acquiring secrets; it must not inspect the refresh mount.
- [ ] For cache reads, run that guard, then open the canonical private parent directory and operate
  relative to its descriptor. Use no-follow/nonblocking opens and `fstat()` to
  verify current-user ownership, regular-file type, exact `0600`, and parent
  `0700`. Read at most 65537 bytes and reject overflow; obtain mtime from that
  descriptor. Never chmod or create files during resolution.
- [ ] For refresh reads, accept a user-owned `0600` regular file or FIFO; reject
  other types and final symlinks. Read through a short-lived subprocess invoked
  as `[sys.executable, "-I", "-c", READER_SOURCE, source_path]`, with an empty
  child environment, captured binary output, and `subprocess.run(timeout=...)`.
  The immutable stdlib-only reader opens without following symlinks, validates
  the opened descriptor, reads at most 65537 bytes, and returns only bounded
  bytes or a fixed failure status. It imports no project modules, so zipapp
  refresh works. The communication timeout bounds the child's blocking open/read
  after process creation; the subprocess is killed/reaped on timeout. Process
  startup and termination add overhead, and parent parsing, publication, and
  filesystem `fsync()` have no strict end-to-end deadline. Measure FIFO timeout
  tests with scheduling tolerance; do not assert total refresh time equals the
  configured value. See [Python's timeout contract](https://docs.python.org/3/library/subprocess.html#subprocess.run).
  Never print captured stdout/stderr or embed values in argv. Do not use an
  uncancellable reader thread.
- [ ] Decode/strict-parse in the parent and emit only fixed acquisition/parse
  errors. Literal longest-first masking is defense in depth for known values,
  not a guarantee against escaped or encoded echoes. Hide values in snapshot
  repr. Task 4 must establish a fixed provider-error boundary instead of relying
  on masking arbitrary upstream text. Add sentinel tests for parser errors,
  decoder errors, timeout exceptions, repr, and echoed-key messages.
- [ ] Rerun the task command. Expected: reads are bounded and no synthetic
  secret appears in public exception strings or diagnostics. Cache reads never
  start the subprocess or consult the refresh path.

## Task 3: Refresh transaction and CLI command

**Files:** Modify `model_sentinel/credentials.py`, `model_sentinel/cli.py`;
extend `tests/test_credentials.py`; create `tests/test_credentials_cli.py`.

**Interfaces:** Produce `refresh_credentials()` and
`run_credentials_refresh(*, args: argparse.Namespace, loaded: LoadedConfig)
-> int`. Add nested `credentials refresh` parsing with optional `--provider`
and `--from-environment`, and register `credentials` in `COMMANDS`.

- [ ] Add transaction tests for initial population, rotation, filtering an
  unrelated secret, default enabled selection, and explicit disabled selection.
  Assert subsequent selected/default resolution succeeds. Test a provider key
  rename, provider removal, two providers sharing a key name, and `--from-environment`
  with a nonexistent mount. No acquisition occurs for an unknown provider.
- [ ] Add `test_refresh_then_report_dir_change_rejects_resolution` in
  `tests/test_credentials.py`: use `refresh_credentials()` to publish synthetic
  `credentials.txt` outside the original report directory. Change
  `MODEL_SENTINEL_REPORT_DIR` to that private parent and reload configuration so
  `runtime_paths` reflects the new location. Resolve in file mode; expect a safe
  placement error before cache acquisition and unchanged cache bytes/mtime.
  Task 3 owns this transaction regression and introduces its writer. Establish
  the expected failure before implementation; after the writer is implemented,
  the regression must pass in this task's rerun.
- [ ] Add failure/concurrency tests: absent source, timeout, missing selected
  key, unsafe existing cache, source=destination, oversized serialized result,
  write/fsync/replace failure, and interruption before replacement all preserve
  old bytes and mtime. Two refreshes cannot lose updates; concurrent scans see
  the complete old or new file, never partial output. Add
  `test_refresh_rejects_reserved_config_and_report_paths`: config/database,
  launchd files, and paths under reports/logs/debug are refused even when their
  parent permissions are private.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_credentials.py tests/test_credentials_cli.py`
  and confirm new refresh tests fail before implementation.
- [ ] Reuse `validate_credential_cache_location()` before extracting secrets.
  Create a missing
  default runtime parent at `0700`, or harden only that existing user-owned
  runtime directory to `0700`; reject root, home itself, Git checkouts, and
  unsafe ownership. An existing custom parent must already be private; never
  chmod an arbitrary shared parent. Reject symlink destinations and cache/source
  inode equality. The same location guard protects resolution after settings
  change; Task 4 also excludes the configured cache from cleanup in either
  source mode. Do not weaken permissions on unrelated descendants.
- [ ] Serialize writers with a private regular `0600` sibling lock file and
  nonblocking `fcntl.flock()`. Keep that lock file; do not unlink the locked
  inode. A second refresh fails with a safe “refresh already running” error.
  Acquire before acquisition and cache merge, release on every exit. Import
  POSIX-only primitives lazily so environment-only users are unaffected.
- [ ] Use `validate_selected_providers()` for selection. Strict-parse acquired
  data, filter to selected names, and validate every required selected value.
  Load any existing safe cache under the lock; a missing cache is an empty map,
  but a malformed/unsafe cache is an error. The merge rule is:

  ```python
  allowed = {p.credential_env_var for p in providers}
  selected_names = {p.credential_env_var for p in selected}
  merged = {k: v for k, v in existing.items() if k in allowed}
  merged.update({k: acquired[k] for k in selected_names})
  ```

  Retained entries must also be valid; unreferenced old names are dropped only
  on successful refresh. Serialize sorted `KEY={value!r}` assignments, which
  round-trip through the shared parser. Validate the resulting bounded text
  before publishing. Test quotes, backslashes, `=`, `#`, and `$` round trips.
- [ ] Create an exclusive random temporary file beside the destination with
  mode `0600` from creation. Write, flush, `fsync()`, and close it; publish with
  descriptor-relative `os.replace()`. Prepare the result before replacement.
  Replacement is the commit point: pre-commit errors preserve the previous
  file; after commit report completion, never claim the old file was retained.
  Clean temporary output on handled failure and release the lock. Abrupt
  process death may leave a private temp file, but never a partial active cache;
  document this without claiming durable recovery across a power failure.
- [ ] Dispatch refresh immediately after `load_config()` and before
  `ensure_directories()`, `_configure_logger()`, or `Store` initialization in
  `main()`, passing `loaded.runtime_paths` to the transaction. Catch safe
  credential errors, return `2`, and print only destination,
  source kind, selected provider IDs, and count on success. It makes no provider
  requests and creates no database, scan logs, reports, or notifications.
- [ ] Test all three help levels and renamed/module invocation, safe `0`/`2`
  exits, unchanged no-command scan normalization, and absence of unrelated
  runtime writes. Rerun the task command; expected: all cases pass.

## Task 4: Scan and diagnostic integration

**Files:** Modify `model_sentinel/cli.py`, `model_sentinel/reporting.py`,
`model_sentinel/providers.py`,
`tests/test_cli.py`, `tests/test_reporting.py`, `tests/test_credentials_cli.py`.
Create `tests/test_providers.py`.

**Interfaces:** Consume the snapshot resolver from Task 2. Add a private
`_emit_credential_error(*, message: str, args: argparse.Namespace,
loaded: LoadedConfig, logger: logging.Logger) -> int` by extracting the current
`run_scan()` credential-error block, preserving its output/notification behavior.
Extend `_cleanup_old_reports(report_dir: Path, retention_days: int,
logger: logging.Logger, *, protected_paths: tuple[Path, ...] = ()) -> None`.
Keep `fetch_raw_models()`'s current call signature; its operator-facing failures
will retain provider identity/HTTP status but omit upstream response text.

- [ ] Add `test_file_scan_survives_unavailable_refresh_source` using mocked
  `fetch_raw_models()` and synthetic keys; assert default and explicit disabled
  selection, exact key passed, no reader process, and no inherited fallback.
  Add missing/malformed/unreadable-cache tests asserting no provider fetch and
  the existing report/notification error path. Keep environment-mode missing-key
  text and the runtime-build-before-error regression unchanged.
- [ ] Add `test_provider_error_omits_escaped_credential_echoes` in
  `tests/test_providers.py`, parametrized over literal, JSON-escaped, and
  URL-encoded echoes of a synthetic key containing quotes/backslashes. Exercise
  the actual fetcher's HTTP error handling, including hostile reason strings;
  assert the body is not read for diagnostics and only a fixed message/provider/
  HTTP code survives. Add network-error and invalid-JSON exception-chain cases.
  Carry the HTTP failure through a scan and assert no raw or encoded secret
  sentinel in SQLite error rows, reports, logs, stdout, or stderr.
- [ ] Add `test_retention_preserves_cache_after_report_directory_change`:
  create an old synthetic `credentials.txt` in a private directory, then make
  that directory the report directory. File mode must report the placement
  error before fetching; environment mode may scan but cleanup must preserve
  the configured cache while removing an ordinary expired report. Neither
  case changes cache bytes or mtime. This covers staged cutover too.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_credentials_cli.py tests/test_cli.py tests/test_reporting.py tests/test_providers.py`
  to establish the new failures before wiring integration.
- [ ] Resolve once per scan after selection, supplying `loaded.runtime_paths`;
  pass `snapshot.values` to
  `missing_credentials()`, and use that same snapshot for every fetch. Treat
  nonempty `invalid_keys` as an actionable validation error before any fetch.
  Route resolver and missing-key failures through `_emit_credential_error()`. Do not
  re-read the file per provider or mutate `os.environ`.
- [ ] In `providers.py`, remove raw HTTP bodies and arbitrary HTTP/network reason
  strings from `ProviderFetchError`. Use fixed messages with configured provider
  identity and numeric HTTP status or a fixed network/JSON category; close HTTP
  error responses without exposing their content. Suppress unsafe exception
  chains with `from None`. This intentionally changes failure text in both source
  modes; it preserves actionable status/category without retaining upstream
  text that may echo credentials. Keep literal masking as an additional guard
  for known values before existing error persistence/reporting/logging, never
  as the primary secrecy boundary.
- [ ] Supply the configured `credential_file` as a protected path at the scan's
  cleanup call in both `environment` and `file` mode. Cleanup compares canonical
  parent plus filename, excluding that exact path before deletion regardless
  of its suffix. Default `protected_paths=()` preserves other callers' API.
  Reuse location validation for file-mode resolution; do not rely on an earlier
  successful refresh to validate current report settings.
- [ ] Resolve once for `providers`, supplying `loaded.runtime_paths`, over all configured providers, without
  requiring every key. Keep existing JSON fields and boolean
  `credential_present`; add `credential_source`, `credential_status`
  (`present`, `missing`, or `error`), and nullable safe `credential_error`.
  Use `invalid_keys` for per-row value errors; a disabled provider's invalid
  value must not hide an enabled provider's valid credential.
  On source failure return the provider listing with false presence and error
  status, still exit `0`; do not guess presence from inherited variables. Extend
  text/Markdown provider rendering to expose source/status and safe errors.
- [ ] In healthcheck keep the existing build/config/profile/database checks,
  validate enabled providers against the same resolver, and return `1` for
  unavailable, invalid, or missing required credentials. Add cache path/mode/source
  and last-updated/age details via existing `render_healthcheck_report()` and
  `time_utils.py`; supply `loaded.runtime_paths` for the current placement guard
  and do not probe the mount. Future mtime is a nonfatal warning.
- [ ] Assert diagnostics agree with scan, disabled missing keys are nonfatal,
  disabled invalid keys appear only on their own provider rows and do not fail
  the enabled-provider healthcheck, all formats contain no secret sentinel,
  and auth errors do not delete cached
  keys. Update existing ad-hoc fake Settings objects with explicit default
  credential fields where needed; do not remove their behavior assertions.
- [ ] Test help/version/history/changes/browse with resolver and refresh reader
  replaced by failing spies. They must never invoke either, even if file mode
  points at a missing cache and a mount with no writer. Preserve browse's
  no-runtime-writes contract and complete offline browser behavior.
- [ ] Rerun the task command. Expected: all new and retained cases pass.

## Task 5: Packaging, launchd guidance, and complete acceptance

**Files:** Modify `README.md`, `docs/LAUNCHD.md`, `launchd.env.template`, setup
guidance in `setup.sh`, next-step guidance in `install_standalone.sh`, and
`tests/test_install_standalone.py`. Create `tests/test_launchd_credentials.py`.
No behavior change to scheduling or existing-file preservation is needed.

**Interfaces:** Existing zipapp staging includes `credentials.py` automatically.
Extend `_copy_installer_project()` to copy setup/launchd templates when needed;
reuse `_installer_env()` for a venv-backed private installation.

- [ ] Add installed-artifact acceptance: install into an external synthetic
  home, refresh from a synthetic FIFO, stop/remove its writer, then run file-mode
  healthcheck and a scan against a loopback mock provider. Assert the mock saw
  the correct synthetic bearer key. Verify the package contains the credential
  module and no cache, keys, tests, or plans. Installed refresh must work without
  the source checkout; `--check`, version, and help remain configuration-free.
- [ ] Add a generated-runner acceptance with an external copied project and
  synthetic runtime config. Stub `launchctl`/`plutil` rather than install a real
  LaunchAgent. Its `launchd.env` contains only nonsecret exports and an explicit
  venv-first PATH. Run the generated runner against a loopback mock provider;
  no mounted source exists, and the saved scan still succeeds. Preserve those
  unrelated exports. Verify setup/standalone reseeding preserves existing
  operator config; it does not “repair” private bootstrap lines automatically.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_install_standalone.py tests/test_launchd_credentials.py`.
  Tasks 1–4 already provide feature support and staging includes the module, so
  the new acceptance cases may pass on their first run. Expected: installed and
  runner cases pass without real credentials. Investigate any failure; do not
  manufacture a red result by disabling previously implemented support.
- [ ] Document file mode, four settings, supported input grammar, bounded
  extraction, manual refresh after rotation, selected-provider merge behavior,
  `--from-environment`, private modes, cache age meaning, and plaintext at-rest
  tradeoff. Distinguish a private static file from 1Password's mount and from
  executable Bash `launchd.env`. Update old environment-only claims throughout
  README/setup/install help while retaining that supported option.
- [ ] Document optional human-run refresh after the existing secrets shell has
  loaded credentials. Do not edit global shell files or add automatic refresh
  hooks or jobs. Scans remain independent of refresh failure.
- [ ] Run the complete project suite from the Model Sentinel directory:

  ```bash
  .venv/bin/python -m pytest
  ```

  Expected: every unit, CLI/integration, installer, and Playwright browser case
  passes, with no skips. Stop on missing Chromium/dependencies and follow the
  standing approval/environment rules; never bypass browser tests. No other
  monorepo project or shared tool is changed by this plan.
- [ ] Run `.venv/bin/python -m model_sentinel --help`,
  `.venv/bin/python -m model_sentinel credentials --help`, and
  `.venv/bin/python -m model_sentinel credentials refresh --help` without live
  config. Expected: exit `0`, complete examples, and no credential acquisition.
  Run `git diff --check`; inspect the full changed-file list and diff for
  sensitive data and accidental unrelated changes. Report commands and results.

## Private cutover procedure — only after separate execution authorization

Application implementation and synthetic tests do not by themselves authorize
changing private configuration or deploying. Make this cutover concrete for the
owner after validation; never capture actual secret contents as evidence.

1. Identify the executable/package the runner actually uses. Before replacing
   any installed executable, copy the existing regular artifact to an owner-only
   backup directory outside the checkout, preserving its bytes and mode. Verify
   the backup matches and record its path plus configuration-free `--version`
   output. This implements the [deployment backup requirement](../../docs/local_deployment_sync.md).
   Back up delivery code, not credential-cache contents. Then rebuild the chosen
   standalone target with the project venv first in PATH, using
   `install_standalone.sh [chosen-target]`, its `--check`, and deployed `--version`.
   A repository update does not update a zipapp. If the runner targets the
   repository package instead, verify the Task 1 delivery-source recovery copy
   and its recorded hashes before cutover; backing up only the launcher cannot
   restore a multi-file app.
   Keep the current target/schedule unless the owner asks to change them.
2. Add the cache and refresh-source paths to private `settings.env`; initially
   retain `MODEL_SENTINEL_CREDENTIAL_SOURCE=environment`. Update provider `API_KEY_ENV` mappings
   to match actual names. Do not put values in either config file.
3. While the mounted environment is authorized, invoke the deployed
   `credentials refresh`; alternatively invoke `--from-environment` from the
   already-loaded secrets shell. Confirm exit `0`, correct private modes, and
   the safe count/status, never display the file. Refreshing does not prove the
   provider accepts a key.
4. Set `MODEL_SENTINEL_CREDENTIAL_SOURCE=file`. Remove only the obsolete secrets-bootstrap
   statement from private `launchd.env`; preserve PATH and other exports. Editing
   that file does not require reseeding/reloading because the runner sources it
   on each invocation. Reload only if runner/installer/plist settings change.
5. Run deployed healthcheck and, when live provider access is authorized, a
   compare-only scan before another scheduled `scan --save`. Confirm behavior
   with the refresh mount unavailable, without launching or closing 1Password
   on the user's behalf. Check sanitized status/outputs without claiming log
   mtime proves a specific scheduled invocation ran.
6. Rollback: atomically restore the saved executable bytes/mode to the same
   deployed path, then verify the restored artifact's `--version` against the
   recorded backup identity. For a repository target restore the Task 1 recorded
   delivery files/modes, preserving unrelated work; remove only runtime files
   introduced by this implementation and absent from that recovery inventory.
   Do not restore only its launcher. Set `MODEL_SENTINEL_CREDENTIAL_SOURCE=environment` and restore
   a compatible owner-approved credential bootstrap, including the mappings
   it requires. Keep cache and SQLite snapshots intact. Reload launchd only if
   runner/plist settings changed. Do not restore a known removed bootstrap path
   or create secret backups in the public checkout.

## Completion and plan verification

Acceptance requires persistent scans with an unavailable mount, bounded failed
refresh preserving the cache, selected disabled-provider compatibility,
consistent safe diagnostics, unchanged offline behavior, and a validated
standalone/runner. No real credential extraction is needed for automated proof.

This plan was checked against the current code and assessment for requirements,
signatures, task dependencies, and all five review-focus cases. It changes only
documentation; the feature and future tests have not been implemented or run.
Deliver the plan for review and stop. Approval of this plan is not authorization
to implement it under the standing project instructions.
