# Memory Snapshot Helpers

Two macOS shell commands for manually capturing a point-in-time memory baseline.
The directory does not contain an executable script or automatic login/reboot
integration.

## Files

- `commands.txt` — Commands that write virtual-memory counters and a one-sample
  process snapshot to text files.

```bash
vm_stat > reboot_baseline.txt
top -l 1 > reboot_top.txt
```

## Usage

1. In Terminal, change to a private directory where you want to keep the
   snapshots.
2. Run the commands from `commands.txt` soon after a reboot.
3. Rename or move the two output files before the next capture if you want to
   compare multiple boots.

The commands write `reboot_baseline.txt` and `reboot_top.txt` in the current
working directory. Running them again overwrites those files. `vm_stat`
contains system-wide virtual-memory counters; `top -l 1` records a single
macOS `top` sample, including the process table.

## Privacy

Keep captured output out of this public repository. In particular, `top`
output can contain usernames, process command lines, and local paths. Review
and sanitize any snapshot before sharing it.

## Optional extensions

- Add timestamps to retained filenames so captures from different boots are
  not confused.
- Use an Automator workflow or LaunchAgent if automatic login-time capture is
  needed; no automation is included here.
- Run `memory_pressure` or `ps` separately when additional diagnostics are
  useful.
