# Moneydance NAS Mount Validation and Config Repair Design

Date: 2026-08-24
Status: Approved

## Purpose

Strengthen `moneydance_rotate_backups.sh` against stale NAS addresses, partial mounts, split-share mistakes, and accidental matches to the wrong server. Normal backup rotation must remain fail-closed: it may diagnose a likely address change, but it must never modify configuration automatically. Configuration repair requires an explicit, interactive `--repair-config` invocation.

This public design uses synthetic examples. Real hosts, share names, directory names, and paths remain exclusively in private runtime configuration and terminal-only interactive output.

## Existing Behavior

The script loads `NAS_SERVER`, `NAS_SHARE_NAME`, and the backup directory from its config. It scans the macOS mount table for an exact `NAS_SERVER` and `NAS_SHARE_NAME` pair, then performs retention work only inside the configured backup directory. When that pair is not mounted, it logs a warning and exits successfully without deleting anything.

A legitimate NAS address change currently looks the same as an unmounted share. The script cannot distinguish a stale address from a missing or incorrect mount, and it does not validate companion shares required by the operator's normal workflow.

## Configuration Contract

Add this required config key, using synthetic values here:

```text
REQUIRED_NAS_SHARES=SYNTHETIC_PRIMARY,SYNTHETIC_COMPANION
```

The value is a comma-separated list of exact SMB share names. Leading and trailing whitespace around each item is ignored. Empty items and duplicate names are invalid. `NAS_SHARE_NAME` remains the share containing `BACKUP_DIRECTORY_NAME` and must appear exactly once in `REQUIRED_NAS_SHARES`.

Support `MONEYDANCE_REQUIRED_NAS_SHARES` as the environment-variable equivalent, following the script's existing config-override convention.

A missing or invalid `REQUIRED_NAS_SHARES` value is a configuration error. The script must exit before inspecting mounts or removing backup files. The private deployed config will receive the operator's real required-share list during deployment; real values must not be committed.

## Mount Inventory

Parse the mount table once into an internal inventory keyed by SMB source host. For each host, retain exact decoded share names and their mount points. Continue stripping an optional `user@` prefix from the SMB authority and decoding only the supported literal `\040` space sequence.

The configured host is valid only when:

1. Every exact name in `REQUIRED_NAS_SHARES` is mounted from `NAS_SERVER`.
2. `NAS_SHARE_NAME` is among those mounted shares.
3. The `NAS_SHARE_NAME` mount point is accessible.
4. `BACKUP_DIRECTORY_NAME` exists under that mount point and passes all existing directory, symlink, readability, and containment checks.

If the configured host is valid, normal retention proceeds exactly as it does today. Other mounted hosts are irrelevant in this case.

## Candidate Discovery

When the configured host is invalid, evaluate every other SMB source host as a possible replacement. A host is a valid candidate only when:

1. It provides every exact share in `REQUIRED_NAS_SHARES`.
2. Those shares all resolve to that same source host.
3. Its `NAS_SHARE_NAME` mount point is accessible.
4. The expected backup directory exists there and passes the existing safety checks.

Discovery outcomes:

- **Exactly one candidate:** emit a redacted persistent warning. When standard output is an interactive terminal, separately display the configured host, candidate host, validated share names, and validated backup directory, followed by instructions to rerun with `--repair-config`. No detailed values may pass through `log_message`, the configured log file, or syslog.
- **No candidate:** emit a redacted persistent warning and skip cleanup. An interactive terminal may additionally explain absent or split required shares when that can be stated unambiguously.
- **Multiple candidates:** emit a redacted ambiguity warning without choosing a host. An interactive terminal may show candidate details for manual investigation, but persistent logging remains redacted.

Normal mode preserves the current safe no-op behavior for mount mismatches: log a warning and exit successfully without removing files. It never changes the config.

## `--repair-config` Mode

`--repair-config` is a separate operation, not an option that enables cleanup. It performs discovery and, when safe, updates only `NAS_SERVER`; it never enumerates purge candidates or removes backup files.

Repair mode must:

1. Require both standard input and standard output to be attached to an interactive terminal.
2. Load and validate the selected config, including `--config PATH` when provided.
3. Refuse a missing config, a symlink, a non-regular file, or a config not readable and writable by the invoking user.
4. Refuse operation when `MONEYDANCE_NAS_SERVER` is set, because changing the file would not change the effective server value.
5. Refuse combination with `--dry-run`; repair mode already guarantees that cleanup cannot occur.
6. Rebuild the mount inventory and candidate decision independently rather than trusting output from a previous normal run.
7. Require exactly one valid candidate.
8. Display the config path, current server, proposed server, required shares, and validated backup directory directly on the terminal. Do not mirror these details to persistent logging.
9. Ask for explicit confirmation. Only an exact affirmative response accepted by the prompt proceeds; cancellation leaves all state unchanged and exits successfully with a cancellation message.
10. Replace only the single active `NAS_SERVER` assignment. Refuse configs containing zero or multiple active `NAS_SERVER` assignments.
11. Write a temporary file in the config directory, preserve the original file's mode, and atomically rename it over the original only after the complete replacement has been written successfully. Any failure removes the temporary file and leaves the original config intact.
12. Emit only a redacted persistent success message, display an interactive success message, and exit without running retention. The user must invoke a subsequent normal run.

Configuration and operational errors retain the script's existing exit-code conventions: configuration or usage errors exit `2`, operational failures exit `1`, and a successful update or explicit cancellation exits `0`.

## User-Facing Messages

Persistent output must remain safe for log files and syslog. A unique candidate found during normal execution should produce a persistent message substantially like:

```text
WARN: The configured NAS does not provide all required mounts. Cleanup was skipped. Run interactively with --repair-config to inspect a validated replacement candidate.
```

During an interactive normal run, terminal-only detail may additionally read:

```text
Configured NAS old-nas.invalid does not have all required shares.
Found one validated candidate at new-nas.invalid with shares SYNTHETIC_PRIMARY and SYNTHETIC_COMPANION.
Validated backup directory: /Volumes/SYNTHETIC_PRIMARY/SYNTHETIC_BACKUPS
No configuration or backup files were changed.
Re-run with --repair-config to review and approve updating NAS_SERVER.
```

Repair mode should show an explicit terminal-only proposal:

```text
Config: /synthetic/private/config
Required shares: SYNTHETIC_PRIMARY, SYNTHETIC_COMPANION
Validated backup directory: /Volumes/SYNTHETIC_PRIMARY/SYNTHETIC_BACKUPS
Proposed change: NAS_SERVER=old-nas.invalid -> NAS_SERVER=new-nas.invalid
Update this config? [y/N]
```

Messages must never print credentials or full unfiltered mount-table contents. Detailed runtime values are permitted only on an interactive terminal and must bypass persistent logging functions.

## Safety Invariants

- No cleanup unless all configured required shares are mounted from the configured host.
- No repair unless exactly one other host satisfies the complete required-share and backup-directory checks.
- No configuration mutation during normal or dry-run execution.
- No cleanup during repair execution, whether repair succeeds, fails, or is cancelled.
- No repair based on partial shares, split hosts, inaccessible paths, symlinks, or ambiguous candidates.
- No implicit fallback from exact share names to fuzzy or case-insensitive matching.
- No private host, share, directory, or path values in persistent logs or committed fixtures.
- Existing backup-directory containment and per-file revalidation remain unchanged.

## Test Strategy

Extend the existing Zsh test harness using injected fake command paths and isolated temporary configs and directories. Tests must not use live mounts or delete real backup files. All committed fixtures and assertions use conspicuously synthetic values.

Cover at least:

- Configured host has all required shares and normal retention continues.
- Either required share is missing.
- Required shares are split across different hosts.
- Configured host has all shares but the backup directory is invalid.
- Stale configured host and exactly one fully valid candidate.
- Multiple fully valid candidates are rejected as ambiguous.
- A host with only one matching share is not a candidate.
- Similar, differently cased, or partially matching share names do not qualify.
- Share names and mount points containing the supported encoded space sequence are parsed correctly.
- Normal and dry-run modes never rewrite config.
- Noninteractive diagnostics and all persistent logging redact private runtime values.
- Interactive normal mode displays detailed candidate information only on the terminal.
- Repair mode rejects noninteractive input or output, symlink configs, conflicting `--dry-run`, and a server environment override.
- Repair cancellation leaves config bytes unchanged.
- Successful repair changes only the active `NAS_SERVER` assignment, preserves mode, and performs no cleanup.
- Detailed repair values bypass persistent logging even when file logging and syslog are enabled.
- Write or rename failure leaves the original config intact and removes temporary files.
- Existing retention behavior and deletion safeguards continue to pass regression tests.
- The repository source and deployed standalone copy remain byte-for-byte identical after deployment.

## Documentation and Deployment

Update the public README and `config.example` using only synthetic values. Document `REQUIRED_NAS_SHARES`, `MONEYDANCE_REQUIRED_NAS_SHARES`, `--repair-config`, terminal-only diagnostics, and the no-cleanup repair contract.

Treat the tracked source and `~/Library/Scripts` copy as independently deployed artifacts. After source tests pass, copy the reviewed source to the deployed location, confirm byte-for-byte identity, update the private runtime config with its real required-share list, and perform a live dry run. Never copy the private config into the public repository.

## Scope

This feature discovers address changes only from currently mounted SMB shares. It does not scan the network, mount shares, resolve NAS names through external discovery services, change credentials, repair Finder favorites, or schedule the script. A future workflow change that no longer mounts every configured required share will require updating `REQUIRED_NAS_SHARES` and, if necessary, revisiting this safety contract.
