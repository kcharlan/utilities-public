# launchd Setup

Model Sentinel includes a user-level `launchd` path for scheduled scans on macOS.

The setup is intentionally split into two steps:

1. seed runtime-home launchd files from the repo
2. edit and re-run the runtime-home installer whenever you want to change the job

This keeps the editable automation files in `~/.model_sentinel/` alongside the rest of the tool's local state.

## Files

After running `./setup_launchd.sh`, these files live in the runtime home:

```text
~/.model_sentinel/launchd.env
~/.model_sentinel/install_launchd.sh
```

After installing the LaunchAgent, these additional files are generated:

```text
~/.model_sentinel/run_model_sentinel_launchd.sh
~/.model_sentinel/local.model_sentinel.scan.plist
~/Library/LaunchAgents/local.model_sentinel.scan.plist
```

## 1. Seed The launchd Files

From the project directory:

```bash
cd model_sentinel
./setup_launchd.sh
```

This does not overwrite existing runtime-home launchd files.

## 2. Edit `launchd.env`

`~/.model_sentinel/launchd.env` is sourced by the launchd runner with `bash`.

Use it for either:

- direct exports like `export OPENROUTER_AI_CREDS=...`
- a `source /path/to/your/secrets.sh` line that loads your existing secrets bootstrap

If your secrets bootstrap changes `PATH`, put your preferred Python path first before sourcing it. Example:

```bash
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
source "$HOME/.secrets/api_keys.zsh"
```

Recommended:

```bash
chmod 600 ~/.model_sentinel/launchd.env
```

The generated runner seeds a Homebrew-friendly default `PATH` before sourcing
`launchd.env`:

```text
/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
```

That makes Homebrew-installed `python3` and `terminal-notifier` visible under
`launchd` even when the GUI session has a minimal environment.

## 3. Edit The Runtime Installer

Edit:

```text
~/.model_sentinel/install_launchd.sh
```

The editable block includes:

- `JOB_LABEL`
- `START_HOUR`
- `START_MINUTE`
- `MODEL_SENTINEL_ARGS`
- launchd stdout/stderr log paths

Default scheduled command:

```bash
scan --save
```

Default scheduled time:

```text
09:05
```

## 4. Install Or Reload The Job

Install the LaunchAgent:

```bash
~/.model_sentinel/install_launchd.sh install
```

Reload after changes:

```bash
~/.model_sentinel/install_launchd.sh reload
```

## 5. Trigger It Manually

After installation:

```bash
launchctl kickstart -k gui/$(id -u)/local.model_sentinel.scan
```

If you changed `JOB_LABEL`, use your customized label instead.

## 6. Check Status

```bash
~/.model_sentinel/install_launchd.sh status
```

Useful files:

- `~/.model_sentinel/logs/launchd.stdout.log`
- `~/.model_sentinel/logs/launchd.stderr.log`
- `~/.model_sentinel/reports/`

Observed behavior:

- the human-readable Model Sentinel report goes to `launchd.stdout.log`
- Python logging output goes to `launchd.stderr.log`

## 7. Uninstall

```bash
~/.model_sentinel/install_launchd.sh uninstall
```

That removes the LaunchAgent from `~/Library/LaunchAgents/` but keeps the runtime-home files so you can reinstall later.

## Notes

- The scheduled job uses `MODEL_SENTINEL_HOME` pointing at `~/.model_sentinel/`.
- If credentials are missing in `launchd.env`, the run will fail just like a manual invocation.
- Notifications behave the same as manual runs.
- Click-to-open notifications require `terminal-notifier`.
- If `terminal-notifier` is installed in a nonstandard location, set `MODEL_SENTINEL_TERMINAL_NOTIFIER_PATH` in `~/.model_sentinel/settings.env`.
- Without `terminal-notifier`, notifications remain informational only because AppleScript notifications cannot open the report file on click.
