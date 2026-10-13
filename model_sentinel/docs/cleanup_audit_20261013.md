# Credential loading and unattended execution audit

Date: 2026-10-13. Scope: credential configuration, extraction, scheduled scans,
and diagnostics. This is an assessment and proposed work, not an implementation.
Examples are synthetic. Private runtime files, secret values, environment IDs,
and operational logs are intentionally excluded.

## Assessment

Model Sentinel supports configurable credential variable names but only reads
credentials from its process environment. Scheduled execution depends on a
separate Bash bootstrap. A source statement targeting a removed bootstrap stops
that runner before the CLI can produce its own credential error report.

A mounted 1Password Environment is a named pipe, not a persistent credential
file. Reading it may require authorization, and simultaneous readers can
interfere. Loading that pipe during every scheduled scan cannot guarantee
unattended operation. See [1Password local environment files](https://www.1password.dev/environments/local-env-file).

The recommended approach is a configurable, persistent credential file plus a
separate, bounded refresh command. Scans read the persistent file; refresh reads
1Password while it is available. A failed refresh preserves the previous copy.

## Assumptions and standards

- Preserve the existing Python 3.11+, stdlib-only runtime and zipapp delivery.
- Preserve environment-only operation for existing users.
- Keep provider IDs, stored snapshots, and report semantics unchanged.
- Workload is one scheduled scan and occasional refreshes of a small credential
  set. Serialize refresh writers; read a mounted environment once per refresh.
- Scheduled scans must not launch the desktop app, request interactive login,
  or read a mounted secret pipe. Provider HTTP access remains necessary.
- Refresh enabled providers by default. An explicit `--provider` selection
  refreshes that configured provider even when disabled, matching existing scan
  selection. Persist only credentials referenced by configured providers, not
  the entire development environment. Preserve unselected configured providers'
  cached keys. New providers require another refresh.
- Secret files and temporary extraction output belong outside the checkout,
  under a private runtime directory. Diagnostics may expose presence and age,
  never values or raw source lines.
- A local copy deliberately persists plaintext credentials. Private directory
  and file permissions limit access; they do not provide encryption or prevent
  access by other processes running as the same user.
- A saved key may be revoked or rotated remotely. Refresh time proves extraction
  happened, not that the provider will accept the key indefinitely.

## Findings

### [Robustness] Finding #1: Shell bootstrap can prevent all application diagnostics

- **Severity:** High.
- **Category:** Robustness & Resilience.
- **Evidence:** `install_launchd.template.sh:57-75` generates a Bash runner with
  `set -euo pipefail`, sources `launchd.env`, and only then execs Model Sentinel.
  `launchd.env.template:7-10` permits arbitrary sourced shell commands.
  This establishes the failure path. Untimestamped stderr errors and a log's
  modification time alone do not establish which scheduled invocation failed.
- **Impact:** A removed bootstrap path, incompatible shell syntax, or login
  failure prevents the scheduled report and bypasses CLI error notifications.
- **Recommended fix:** Move credential loading into a shared application
  resolver. Scheduled file mode must consume a regular persistent file and
  have no dependency on an interactive secrets bootstrap. Preserve other
  operator-owned `launchd.env` exports during manual migration.
- **Effort:** M; **Risk:** Medium, with explicit runtime configuration migration.
- **Acceptance criteria:** A synthetic scheduled runner reaches the CLI without
  a secrets shell; missing credentials produce the existing actionable error
  flow; unrelated runtime exports survive migration.

### [Maintainability] Finding #2: Variable names are configurable; acquisition is not

- **Severity:** Medium.
- **Category:** Best Practices & Maintainability.
- **Evidence:** `model_sentinel/config.py:17-27` stores `credential_env_var`;
  `config.py:155-178` obtains it from `API_KEY_ENV`; `config.py:321-330` checks
  only the supplied environment. `model_sentinel/cli.py:355-374` checks
  `os.environ`, and `cli.py:408-411` reads the key from `os.environ` again.
  `cli.py:699-700` and `cli.py:831-843` independently inspect the same environment
  for provider listings and health checks. `config.py:305-318` permits explicit
  selection of a configured provider regardless of whether it is enabled.
- **Impact:** Changing a provider variable name already needs only a config
  edit, but changing the credential acquisition mechanism requires shell work
  and gives manual and scheduled runs different behavior.
- **Recommended fix:** Add explicit `environment` and `file` source modes.
  Preserve `environment` as the default. In `file` mode the configured file is
  authoritative; do not silently mix it with stale inherited credentials.
  Resolve a credential mapping once and pass its selected values to existing
  validation and fetch functions. Use the same resolver for diagnostics.
- **Effort:** M; **Risk:** Medium, backward compatible with opt-in file mode.
- **Acceptance criteria:** A changed `API_KEY_ENV` mapping works without code
  edits after refresh; file-mode scan and diagnostics agree; selecting one
  provider, including a disabled one, requires only its key. Explicit refresh
  of that provider preserves other configured providers' cached keys, so a
  later default scan retains its credentials. Offline history and browsing
  never acquire credentials.

### [Robustness] Finding #3: Existing env-file reads have no FIFO deadline

- **Severity:** High if reused to read a mounted environment.
- **Category:** Robustness & Resilience.
- **Evidence:** `model_sentinel/envfile.py:11-24` calls `Path.read_text()` with no
  deadline or size limit. Its callers currently use ordinary config files;
  this is an extension hazard, not evidence that present config reads hang.
  `model_sentinel/config.py:95-99` uses `is_file()`, which would exclude a FIFO
  if copied as the refresh-source guard.
- **Impact:** A naive credential-file implementation can hang while opening or
  reading a pipe, or reject a valid mount as missing. Direct redirection into
  the destination can also erase working credentials before extraction fails.
- **Recommended fix:** Keep regular-file scan loading separate from bounded
  refresh acquisition. Cover both FIFO open and read with a deadline; bound
  total bytes; finish parsing and validating every required key before writing.
  Factor text parsing out of `parse_env_file()` rather than duplicating it,
  and document the supported assignment grammar. Handle errors without quoting
  secret lines or values. Do not evaluate shell code or substitutions.
- **Effort:** M; **Risk:** Medium.
- **Acceptance criteria:** Synthetic FIFO cases cover delayed open, partial
  output, missing EOF, concurrent reads, malformed data, and oversize output.
  All failed refreshes leave existing credentials byte-for-byte unchanged.
  Reject unresolved `op://` references and empty or CR/LF-containing keys.

### [Safety] Finding #4: Persistent extraction needs a separate publication boundary

- **Severity:** High if plaintext caching is introduced without these controls.
- **Category:** Correctness & Safety.
- **Evidence:** `model_sentinel/config.py:64-68` creates directories using
  default permissions. `envfile.py` has no secret-specific persistence logic.
  No existing credential cache writer was found.
- **Impact:** A refresh could expose unrelated environment secrets, create
  broadly readable files, or publish an incomplete file to a concurrent scan.
- **Recommended fix:** Add a dedicated credential writer: private `0700`
  parent, `0600` file and temporary file, current-user ownership checks, regular
  non-symlink destination, restrictive umask, and atomic replacement on the
  same filesystem. Handle directory hardening narrowly; do not recursively
  change unrelated runtime content. Serialize refresh writers and clean up
  temporary output on failure. Never print secrets, include them in argv,
  retain secret backups, or write them inside the repository.
- **Effort:** M; **Risk:** Medium because this intentionally adds at-rest secrets.
- **Acceptance criteria:** Tests verify permissions, ownership/symlink
  rejection, interrupted refresh, concurrent scan versus refresh, preservation
  of the previous copy on failure, selected-key filtering, and no secret
  sentinel in reports, logs, stdout, stderr, or exceptions.

## Options

| Approach | Unattended behavior | Tradeoff |
| --- | --- | --- |
| Persistent local copy, refreshed while 1Password is available | Scans continue with 1Password closed | Keys persist on disk and need refresh after rotation |
| Service account retrieves secrets automatically, optionally maintaining the same local copy | No desktop login required | Requires a separately provisioned automation token, access grants, network access, and compatible tooling |
| Read the desktop-mounted environment on every scan | May prompt, block, or fail when unattended | No persistent copy, but does not meet the availability requirement |

Recommend the first option initially. Add service-account refresh only if fully
automatic rotation is required. A desktop login session is not a substitute for
an unattended service-account credential.

[1Password supports service-account authentication for Environments](https://www.1password.dev/environments/read-environment-variables).
Its Environment CLI support is documented as beta; inspect local command
capabilities rather than assuming a version number enables it. The installed
CLI examined during this assessment did not advertise `op environment` or
`op run --environment`. Do not base the first implementation on those commands
or install a replacement CLI as part of this analysis.

## Proposed configuration and extraction flow

The following settings and commands are proposals and do not exist yet:

```text
MODEL_SENTINEL_CREDENTIAL_SOURCE=file
MODEL_SENTINEL_CREDENTIAL_FILE=credentials.env
MODEL_SENTINEL_CREDENTIAL_REFRESH_FILE=~/.secrets/SYNTHETIC_ENVIRONMENT_PIPE
MODEL_SENTINEL_CREDENTIAL_REFRESH_TIMEOUT_SECONDS=5
```

Resolve relative paths under the runtime home and expand `~`. The persistent
file remains stable when the development environment is renamed; only the
refresh-source path changes. Credential variable renames use existing
`MODEL_SENTINEL_PROVIDER_<ID>_API_KEY_ENV` settings.

Proposed command: `model-sentinel credentials refresh`. It reads the configured
mount once, parses assignments in memory, and selects enabled providers by
default. `model-sentinel credentials refresh --provider <provider-id>` selects
that configured provider even when disabled. Validate every selected key before
changing the cache. Merge selected keys with existing unselected keys referenced
by the current provider configuration, discard unrelated variables, and write
the resulting complete file atomically. A failed refresh preserves the entire
previous file. An explicit
`--from-environment` mode could instead use keys already loaded by an interactive
secrets shell, avoiding a second pipe read. Refresh must report status without
printing values. It must not launch 1Password automatically.

Refresh initially and after changing a key, variable mapping, provider set, or
development environment. Optional automation can invoke refresh while the
mount is already authorized; failure must preserve the previous copy and must
not prevent a separate scheduled scan. Such opportunistic refresh does not
guarantee synchronization while 1Password is closed. Fully automatic updates
require an unattended authentication source such as a service account.

Scans use the saved credentials until replaced or until providers reject them.
Healthcheck should expose source, presence, permissions, and last refresh age.
Default to no forced expiration; any hard maximum age must be an explicit
operator choice. Do not silently erase cached keys after an HTTP auth failure.

## Ordered proposed work

1. Extend `Settings` and `load_settings()` in `model_sentinel/config.py` with
   validated optional source/path/deadline settings. Update
   `settings.env.template`; keep environment-only configurations working.
2. Extract shared text parsing from `model_sentinel/envfile.py`; add a small
   `model_sentinel/credentials.py` for selected-key resolution and secure
   persistence. Add synthetic credential and FIFO regression tests.
3. Update `run_scan()`, `run_healthcheck()`, and `run_providers()` in
   `model_sentinel/cli.py` to consume the resolver. Credential-free commands
   must retain their current behavior. Add the explicit refresh command.
4. Update `launchd.env.template`, README, and `docs/LAUNCHD.md` to distinguish
   persistent scan credentials from refresh inputs. Migrate existing private
   launchd config explicitly; setup scripts preserve existing files and cannot
   repair them merely by reseeding templates.
5. Run `.venv/bin/python -m pytest` from the project directory, including all
   unit, CLI/integration, installer, and Playwright browser tests. Expected:
   every category passes with no skips. Fix every failure before deployment.
6. Verify synthetic acceptance with a populated static file and an unavailable
   refresh mount: scans still reach mocked provider fetches without GUI or CLI
   authentication. Verify a disabled provider can be explicitly refreshed and
   scanned without erasing keys needed by the next default scan. Verify failed
   refresh preserves the file. Then validate standalone packaging in a private
   synthetic installation. A deployed zipapp must be rebuilt to include
   application changes.

Stop implementation if the chosen format cannot round-trip supported values,
timeouts cannot bound both open and read, or permission/atomicity tests fail.
Do not compensate with shell evaluation, unchecked copying, or discarded tests.
Rollback consists of choosing environment mode and restoring the previous
operator-owned bootstrap; existing snapshots and provider identities need no
data migration. Leave the persistent file intact until its owner removes it.

## Verification performed for this assessment

Read the root README, project README, launchd documentation, relevant deployment
documentation, implementation, and tests; consulted project PKM decisions and
official 1Password documentation. No project lessons-learned file was found.

Executed:

```bash
.venv/bin/python -m pytest -q tests/test_config.py tests/test_envfile.py tests/test_cli.py::test_scan_logs_runtime_identity_before_a_credential_error
```

Result: 13 passed. This validates the existing configuration/parser and
credential-error behavior; it does not validate the proposed feature. The full
suite was not run because this deliverable changes documentation only. No live
credential values were extracted, no provider requests were made, and no private
runtime configuration or scheduled job was modified.
