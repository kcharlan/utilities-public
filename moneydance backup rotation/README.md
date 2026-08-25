# Moneydance Backup Rotation

## Privacy and safety

This is a public-facing utility. Never put a real NAS host, share name, backup
directory, username, file name, or local path in this repository. Runtime
settings belong in a private config file outside the repository or in explicit
`MONEYDANCE_*` environment variables. The script does not discover or migrate
legacy configuration.

The tracked [`config.example`](config.example) contains conspicuously synthetic
values and defaults to dry-run mode. Missing or invalid required settings stop
the script before it inspects mounts or files. Operational logs report counts
and outcomes without printing the configured host, share, directory, or backup
file names. Detailed host, share, directory, and private-config values are
shown only on an interactive terminal; non-terminal stdout and stderr, the
configured log file, syslog, and captured child-command diagnostics remain
redacted.

## Overview

`moneydance_rotate_backups.sh` prunes old Moneydance backup exports on an
already-mounted SMB NAS share on macOS. Retention is expressed in distinct
local calendar days derived from file modification times, not file counts, so
every eligible export from a retained day is preserved. The mount point is
resolved from the macOS mount table. Cleanup is allowed only when every exact
share listed in `REQUIRED_NAS_SHARES` is mounted from the configured host.

## Requirements

- macOS with Zsh and the standard BSD command-line tools used by the script.
- Every configured required SMB share must already be mounted from the same
  host. The script does not scan the network or mount shares.
- Read and search access to the backup directory; deletion also requires write
  access when dry-run mode is disabled.

## Setup

1. Copy the synthetic example to the default private configuration directory:

   ```bash
   config_root="${XDG_CONFIG_HOME:-$HOME/.config}"
   mkdir -p "$config_root/moneydance-backup-rotation"
   cp config.example "$config_root/moneydance-backup-rotation/config"
   chmod 600 "$config_root/moneydance-backup-rotation/config"
   ```

2. Edit the private copy. Set the NAS host, primary share, required-share list,
   backup directory name, and exact backup filename suffix. Include the primary
   `NAS_SHARE_NAME` exactly once in `REQUIRED_NAS_SHARES`. Do not edit
   `config.example` with real values.

3. Review behavior without deletion:

   ```bash
   ./moneydance_rotate_backups.sh --dry-run
   ```

4. After confirming the retention result, set `DRY_RUN=0` in the private config
   and invoke the script without `--dry-run` to enable pruning.

Use a different private file with `--config`:

```bash
./moneydance_rotate_backups.sh --config /path/to/private/config --dry-run
```

The path shown above is a placeholder. Do not commit your actual path.

## Configuration

The file format is a deliberately small `KEY=VALUE` format. It is parsed as
data and is never sourced as shell code. Blank lines and lines beginning with
`#` are allowed; quoting and inline comments are not supported.

Unless `--config` is supplied, the script looks for
`$XDG_CONFIG_HOME/moneydance-backup-rotation/config` when `XDG_CONFIG_HOME` is
set, or `$HOME/.config/moneydance-backup-rotation/config` otherwise. A config
file is optional only when all required values are supplied through environment
variables.

| Key | Purpose |
| --- | --- |
| `NAS_SERVER` | Required NAS host name or IP address. No default is provided. |
| `NAS_SHARE_NAME` | Required primary mounted share containing `BACKUP_DIRECTORY_NAME`. No default is provided. |
| `REQUIRED_NAS_SHARES` | Required comma-delimited list of exact SMB share names. Surrounding whitespace is ignored; empty or duplicate entries are invalid, and `NAS_SHARE_NAME` must appear exactly once. Every listed share must be mounted from the same host. |
| `BACKUP_DIRECTORY_NAME` | Required child directory containing backups. It must be one directory name, not a path. |
| `BACKUP_FILENAME_SUFFIX` | Required exact filename extension eligible for retention and deletion. It must begin with `.`. No operational default is provided. |
| `MAX_DAYS_TO_KEEP` | Positive number of newest distinct calendar days to retain (default `4`). |
| `DRY_RUN` | `1` prevents deletion; `0` permits deletion after all validation succeeds (safe default `1`). |
| `LOG_FILE` | Optional private absolute path for mirrored logs. Empty disables file logging. |
| `USE_SYSLOG` | `1` mirrors redacted status messages to macOS syslog (default `0`). |

The required location settings can instead be passed explicitly as
`MONEYDANCE_NAS_SERVER`, `MONEYDANCE_NAS_SHARE_NAME`,
`MONEYDANCE_REQUIRED_NAS_SHARES`, and
`MONEYDANCE_BACKUP_DIRECTORY_NAME`; the required suffix uses
`MONEYDANCE_BACKUP_FILENAME_SUFFIX`. Optional settings use the same prefix, for
example `MONEYDANCE_MAX_DAYS_TO_KEEP` and `MONEYDANCE_DRY_RUN`. Environment
variables with nonempty values override values loaded from the config file;
`--dry-run` always wins.

## Command-line options

```text
--config PATH    Use a specific private config file.
--dry-run        Inspect retention candidates without deleting files.
--repair-config  Interactively replace NAS_SERVER with one validated host.
-h, --help       Print usage and exit without inspecting mounts or files.
```

Unknown options and a missing `--config` argument fail before any mount lookup.
`--repair-config` cannot be combined with `--dry-run`.

## Mount mismatch diagnostics and config repair

Normal execution is diagnostic-only when the configured host does not satisfy
the full mount contract. The script considers only hosts already present in the
SMB mount table. A replacement candidate must provide every exact required
share from one host, have exactly one mount for each required host/share pair,
and expose the configured backup directory beneath the exact primary
`NAS_SHARE_NAME`. Similar, partial, differently cased, split-host, duplicate,
inaccessible, or symlinked matches do not qualify.

When exactly one candidate qualifies, normal mode skips cleanup and emits a
redacted instruction to run the script manually with `--repair-config`.
Interactive normal execution may also show the configured host, candidate,
validated shares, and backup directory directly on the terminal. No candidate
or multiple candidates also fail closed: cleanup is skipped and no host is
selected. Normal mode and `--dry-run` never rewrite the config.

Run repair mode explicitly with the private config you intend to change:

```bash
./moneydance_rotate_backups.sh --config /synthetic/private/config --repair-config
```

Repair mode requires both stdin and stdout to be attached to a terminal. It
also requires a readable, writable, regular, non-symlink config owned by the
invoking user, exactly one active `NAS_SERVER` assignment, and no set
`MONEYDANCE_NAS_SERVER` environment override. It independently rebuilds the
mount inventory and proceeds only when there is exactly one fully validated
replacement candidate.

The terminal displays the private config path, current and proposed hosts,
required shares, and validated backup directory, then asks once for explicit
confirmation. Only `y` or `yes`, case-insensitively, approves the change. On
approval, the script atomically replaces only the active `NAS_SERVER` value
while preserving the rest of the config and its permissions. Cancellation
leaves the config unchanged.

Repair mode never enumerates retention candidates or deletes backups. Whether
no repair is needed, the user cancels, or an update succeeds, it exits without
cleanup. After a successful update, run the script again normally (preferably
first with `--dry-run`) to validate the repaired configuration and review
retention behavior.

Usage, repair-precondition, and config-validation errors—including missing,
malformed, or binary config—exit `2`. Operational repair failures—including
candidate discovery; locking or snapshotting; temporary-file creation, writing,
or revalidation; live-config revalidation; or atomic activation—exit `1`. A
valid config that needs no repair, an explicit cancellation, and a successful
update exit `0`. A normal-mode mount mismatch also exits `0` after safely
skipping cleanup.

## Retention behavior

1. Validate every setting before querying the mount table.
2. Require every exact name in `REQUIRED_NAS_SHARES` to be mounted from the
   configured host, whether macOS displays a source as `//host/share` or
   `//username@host/share`. Duplicate exact host/share mounts are ambiguous and
   fail closed.
3. Resolve the primary `NAS_SHARE_NAME` mount and verify that its configured
   child backup directory exists, is accessible, and is not a symbolic link.
4. Scan regular files without crossing a nested filesystem. Only files whose
   names end in the exact configured `BACKUP_FILENAME_SUFFIX` are eligible;
   every other file is ignored and can never be deleted by this utility.
5. Group eligible files recursively by modification day and fail without
   deletion if any eligible file cannot be classified.
6. Retain every eligible file from the newest `MAX_DAYS_TO_KEEP` distinct days.
7. Report the candidate count in dry-run mode, or remove those files only when
   a private config or explicit `MONEYDANCE_DRY_RUN=0` environment setting
   permits deletion. The `--dry-run` option always overrides either setting.
8. Immediately before each removal, verify again that the candidate is a
   regular, non-symlink file beneath the backup directory, still has the exact
   configured suffix, and still belongs to a purge day. Changed candidates are
   skipped.

If reading the mount table fails, the share is not mounted, the directory is
inaccessible, enumeration or classification fails, or validation fails,
cleanup does not proceed.

Once deletion begins, an individual removal failure can leave an intentionally
partial result: successfully removed candidates stay removed, the script
reports the number of failures, and it exits nonzero.

## Tests

The test suite uses only temporary synthetic fixtures and mocked command paths;
it never queries a real share or depends on the repository location:

```bash
./tests/run_tests.zsh
```

## Notes

- Running frequently is safe because retention is based on distinct days.
- Address-change discovery is limited to already-mounted SMB shares. The script
  never scans for NAS devices, resolves them through an external discovery
  service, mounts shares, or changes credentials.
- Deploy a compatible reviewed script before adding `REQUIRED_NAS_SHARES` to a
  private runtime config. Keep operational host, share, directory, username,
  filename, and path values out of this public repository; never copy a private
  config into Git.
- On recent macOS versions, the invoking shell may need Full Disk Access for the
  private backup directory.
