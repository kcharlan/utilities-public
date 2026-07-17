# Memory Snapshot Helpers
Tiny shell snippets to capture baseline memory statistics on macOS immediately after a reboot.

## Files

- `commands.txt` – Reference commands and their intended output filenames.

```bash
vm_stat > reboot_baseline.txt
top -l 1 > reboot_top.txt
```

## Usage

1. Run the commands right after a reboot to capture kernel memory counters (`vm_stat`) and a one-shot process snapshot (`top -l 1`).
2. Commit the text files or store them with timestamps to compare against later boots.

## Tips

- Wrap the commands in an Automator script or LaunchAgent if you want them to trigger automatically on login.
- Pair with tools like `memory_pressure` or `ps` to gather additional diagnostics when chasing memory leaks.
