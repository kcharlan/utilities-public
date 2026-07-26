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
file names.

## Overview

`moneydance_rotate_backups.sh` prunes old Moneydance backup exports on an
already-mounted SMB NAS share on macOS. Retention is expressed in distinct
local calendar days derived from file modification times, not file counts, so
every eligible export from a retained day is preserved. The mount point is
resolved from the macOS mount table.

## Requirements

- macOS with Zsh and the standard BSD command-line tools used by the script.
- The configured SMB share must already be mounted.
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

2. Edit the private copy. Set `BACKUP_FILENAME_SUFFIX` to the exact extension
   used by your backup exports. Do not edit `config.example` with real values.

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
| `NAS_SHARE_NAME` | Required mounted share name. No default is provided. |
| `BACKUP_DIRECTORY_NAME` | Required child directory containing backups. It must be one directory name, not a path. |
| `BACKUP_FILENAME_SUFFIX` | Required exact filename extension eligible for retention and deletion. It must begin with `.`. No operational default is provided. |
| `MAX_DAYS_TO_KEEP` | Positive number of newest distinct calendar days to retain (default `4`). |
| `DRY_RUN` | `1` prevents deletion; `0` permits deletion after all validation succeeds (safe default `1`). |
| `LOG_FILE` | Optional private absolute path for mirrored logs. Empty disables file logging. |
| `USE_SYSLOG` | `1` mirrors redacted status messages to macOS syslog (default `0`). |

The required location settings can instead be passed explicitly as
`MONEYDANCE_NAS_SERVER`, `MONEYDANCE_NAS_SHARE_NAME`, and
`MONEYDANCE_BACKUP_DIRECTORY_NAME`; the required suffix uses
`MONEYDANCE_BACKUP_FILENAME_SUFFIX`. Optional settings use the same prefix, for
example `MONEYDANCE_MAX_DAYS_TO_KEEP` and `MONEYDANCE_DRY_RUN`. Environment
variables with nonempty values override values loaded from the config file;
`--dry-run` always wins.

## Command-line options

```text
--config PATH  Use a specific private config file.
--dry-run      Inspect retention candidates without deleting files.
-h, --help     Print usage and exit without inspecting mounts or files.
```

Unknown options and a missing `--config` argument fail before any mount lookup.

## Retention behavior

1. Validate every setting before querying the mount table.
2. Locate the exact configured SMB host/share in the macOS mount table, whether
   macOS displays it as `//host/share` or `//username@host/share`.
3. Verify that the configured child backup directory exists, is accessible,
   and is not a symbolic link.
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
- On recent macOS versions, the invoking shell may need Full Disk Access for the
  private backup directory.
