# launchd Setup

Model Sentinel includes a user-level `launchd` path for scheduled scans on macOS.

The setup is intentionally split into two steps:

1. seed runtime-home launchd files from the repo
2. edit and re-run the runtime-home installer whenever you want to change the job

This keeps the editable automation files in `~/.model_sentinel/` alongside the
rest of the tool's local state. Set `MODEL_SENTINEL_HOME` before running the
setup and installer commands to use a different runtime home.

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

The seeded installer captures the absolute repository path at this moment, and
the generated runner executes the repo-local `model-sentinel` launcher from
that path. Keep the checkout there. If it moves, edit `PROJECT_DIR` in the
runtime installer or remove the seeded installer and rerun
`./setup_launchd.sh` from the new checkout.

The standalone zipapp installer does not change this LaunchAgent target or
seed `install_launchd.sh`; using the standalone executable for scheduled runs
requires setting `PROJECT_DIR`/the runner command accordingly. A standalone
target is a point-in-time copy and must be rebuilt after repository updates.
Replacing the same target path with `install_standalone.sh` is atomic and does
not require reloading launchd; the generated runner resolves the path on every
invocation.

## 2. Edit `launchd.env`

`~/.model_sentinel/launchd.env` is sourced by the launchd runner with `bash`.

For persistent file mode, configure the credential source and paths in
`settings.env` and refresh manually before scheduled scans. See the
[credential settings and input grammar](../README.md#persistent-file-credentials).
The runner needs only nonsecret exports such as `PATH`; it reads the private
static cache and never opens a 1Password mount or refreshes credentials.

`launchd.env` is executable Bash, unlike the assignment-only credential cache
or refresh input. Do not use it as the refresh input. In the default environment
mode, use it for either:

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

When switching to file mode, manually remove only the obsolete credential
bootstrap/direct credential exports, preserving unrelated exports such as
`PATH`. Setup and standalone installation preserve existing file contents;
reseeding does not remove or repair bootstrap lines. Review the files yourself.
`launchd.env` is sourced on every run, so editing it needs no reload. Changing
the runtime installer's schedule or generated command requires rerunning it.

After credential rotation, run `model-sentinel credentials refresh` manually
from an authorized session, or optionally run
`model-sentinel credentials refresh --from-environment` after your existing
secrets shell loads the values. No shell-file edits or automatic refresh hooks
are needed. A failed refresh keeps the previous cache, and scheduled scans
remain independent of the refresh source. The cache has a `0700` immediate
parent and `0600` file mode but remains plaintext at rest. Cache last updated
describes the cache file's age, not provider validity or each retained key's age.

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

For a job customized to run the standalone target, diagnose deployment
freshness from the checkout before inspecting the logs:

```bash
./install_standalone.sh --check
~/Library/Scripts/model-sentinel --version
~/Library/Scripts/model-sentinel healthcheck
```

The freshness check is read-only. A `stale` result means the standalone must
be rebuilt; it does not imply that launchd itself needs to be reloaded.

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
- The generated runner depends on the repository path captured when
  `setup_launchd.sh` seeded the runtime installer, unless the runtime installer
  was explicitly customized to target a standalone directory.
- A customized standalone target remains independent of the checkout at run
  time, but repository updates do not update that target. Rebuild it with
  `install_standalone.sh` and verify it with `install_standalone.sh --check`.
- Missing or invalid selected credentials cause the run to fail just like a manual invocation, whether supplied by the environment or private cache.
- Notifications behave the same as manual runs.
- Click-to-open notifications require `terminal-notifier`.
- If `terminal-notifier` is installed in a nonstandard location, set `MODEL_SENTINEL_TERMINAL_NOTIFIER_PATH` in `~/.model_sentinel/settings.env`.
- Without `terminal-notifier`, notifications remain informational only because AppleScript notifications cannot open the report file on click.
