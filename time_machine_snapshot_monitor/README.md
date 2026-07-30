# Time Machine Snapshot Monitor

This user-level macOS monitor detects a specific Time Machine failure: a local
snapshot that remains mounted after Time Machine has stopped running.

Normal APFS snapshots listed by `tmutil listlocalsnapshots /` are not errors.
This tool alerts only for mounted paths beneath:

```text
/Volumes/com.apple.TimeMachine.localsnapshots/
```

## Safety contract

Scheduled operation is alert-only. Repair is possible only through the
**Attempt Repair** notification action or an explicit `--repair` command.

Repair:

- Rechecks Time Machine status immediately before acting.
- Refuses to run when Time Machine is active or its status is unknown.
- Re-enumerates current mounts rather than trusting saved paths.
- Uses only a normal `diskutil unmount`.
- Never forces an unmount, deletes a snapshot, kills a process, changes
  Time Machine settings, or invokes `sudo`.

## Requirements

- macOS
- [`alerter`](https://github.com/vjeantet/alerter) 26 or later

Install `alerter` with Homebrew if needed:

```bash
brew install vjeantet/tap/alerter
```

## Install or update

Run the installer from this repository:

```bash
./time_machine_snapshot_monitor/install.sh
```

The installer is safe to rerun. It validates and copies the project into:

```text
~/Library/Scripts/time_machine_snapshot_monitor
```

If that installed source tree changed, the installer first moves the previous
copy into a private directory beneath `~/.utilities-deploy-backups/`. It then
creates or refreshes:

- Public command: `~/Library/Scripts/tm-snapshot-monitor`
- LaunchAgent:
  `~/Library/LaunchAgents/local.time-machine-snapshot-monitor.plist`
- Runtime data:
  `~/Library/Application Support/TimeMachineSnapshotMonitor`

The final installation checks verify the loaded job and current monitor status,
then send a ten-second test notification.

## Schedule and alerts

The LaunchAgent runs at minute 45 of each hour.

- **Idle:** Check for mounted local snapshots immediately.
- **Running:** Skip this hourly check and increment a consecutive counter.
- **Unknown:** Skip the check and increment a separate monitor-health counter.

Four consecutive Running checks generate an alert. Checks five and later
refresh the alert hourly until an Idle check resets the counter. Unknown status
uses the same four-check threshold but generates a distinct monitor-health
alert.

A mounted local snapshot observed while Time Machine is idle alerts immediately
and offers **Attempt Repair**. The alert waits up to 3,300 seconds for a
response, ensuring the job exits before its next scheduled run.

## Commands

```bash
~/Library/Scripts/tm-snapshot-monitor --status
~/Library/Scripts/tm-snapshot-monitor --repair
~/Library/Scripts/tm-snapshot-monitor --test-notification
~/Library/Scripts/tm-snapshot-monitor --help
```

Exit statuses:

```text
0  success, including no mounted snapshots
2  command usage error
3  repair refused because Time Machine is running
4  repair refused because Time Machine status is unknown
5  one or more mounted snapshots remain after repair
6  dependency or runtime initialization failure
```

## Logs

The active log is:

```text
~/Library/Application Support/TimeMachineSnapshotMonitor/logs/monitor.log
```

At 1 MiB it is compressed to `monitor.log.1.gz`. A later rotation replaces
that archive, so the monitor retains exactly one active log and at most one
compressed log. LaunchAgent stdout and stderr go to `/dev/null`; the bounded
structured log is the authoritative record.

## Inspect the scheduled job

```bash
/bin/launchctl print \
  "gui/$(/usr/bin/id -u)/local.time-machine-snapshot-monitor"
```

## Uninstall

Remove the LaunchAgent and public command link while preserving logs and state:

```bash
~/Library/Scripts/time_machine_snapshot_monitor/uninstall.sh
```

Also remove the exact runtime log/state directory:

```bash
~/Library/Scripts/time_machine_snapshot_monitor/uninstall.sh --purge
```

The uninstaller preserves the installed source tree so it remains available for
review or reinstall. Delete that exact tree manually only after the scheduled
job has been uninstalled. The canonical repository source is never removed.

## Tests

The suite uses a temporary fake home and fake platform commands. It never
invokes real notification, `launchd`, or unmount operations.

From the repository root:

```bash
/bin/sh time_machine_snapshot_monitor/tests/run_tests.sh
```

The repository-wide deployment audit also checks the installed source tree and
stable command link:

```bash
/bin/zsh -f tools/check_local_deployments.zsh
```
