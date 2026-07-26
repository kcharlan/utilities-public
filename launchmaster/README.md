# launchmaster

launchmaster is a local macOS control center for inspecting and managing
`launchd` jobs. A single executable Python file serves a FastAPI backend and an
embedded React interface; there is no frontend build step.

## Requirements

- macOS with `launchctl`
- [uv](https://docs.astral.sh/uv/)
- A browser with internet access to load the React, Babel, Lucide, and font
  assets referenced by the embedded interface

launchmaster runs with the permissions of the user who started it. Reading or
changing jobs under `/Library` or `/System/Library` may fail unless that user
already has the required permissions; the application does not elevate
privileges.

## Run

```zsh
cd launchmaster
./launchmaster
```

By default, launchmaster binds to `127.0.0.1`, prefers port `8200`, and opens
the interface in the default browser. If port `8200` is occupied, it tries the
next 19 ports in sequence.

```text
usage: launchmaster [-h] [-p PORT] [--host HOST] [--no-browser] [--debug]
```

- `-p`, `--port`: preferred starting port
- `--host`: address to bind (default: `127.0.0.1`)
- `--no-browser`: do not open a browser automatically
- `--debug`: enable debug logging

The server has no authentication. Keep the default loopback binding unless
every device that can reach the chosen address should be allowed to inspect
and operate this Mac's launchd jobs.

## Features

- Discovers user, global, and Apple launch agents and daemons, plus loaded jobs
  that have no matching plist on disk
- Combines plist configuration with live PID, exit-status, loaded, and enabled
  state from `launchctl`
- Shows human-readable interval, calendar, `WatchPaths`, `KeepAlive`, and
  run-at-load schedules
- Searches, filters, sorts, paginates, and bulk-selects jobs; Apple jobs are
  hidden in the interface by default
- Pushes status changes to the browser over a WebSocket
- Starts, stops, runs, reloads, enables, disables, loads, and unloads jobs
- Creates or imports jobs, exports plist files, and validates plist XML before
  saving edits
- Reads configured stdout/stderr files and recent macOS unified-log entries
- Creates a timestamped backup before deleting a plist or saving plist edits

The generated FastAPI API reference is available at `/docs` while the server
is running.

## Runtime data

Runtime configuration and backups live under `~/.launchmaster/`:

```text
~/.launchmaster/
├── config.json
└── backups/
```

Set `LAUNCHMASTER_HOME` to use a different location, which is useful for
isolated runs:

```zsh
LAUNCHMASTER_HOME=/tmp/launchmaster-sandbox ./launchmaster --no-browser
```

This changes launchmaster's configuration and backup location only. It does
not sandbox `launchctl` or change which system plist directories are scanned.

The application creates backups before plist edits and deletes, but a backup
does not make launchd operations risk-free. Review the target domain and plist
path before modifying or deleting a job.

## Development

The executable uses PEP 723 metadata, so normal runs require only `uv`. The
separate development requirements reproduce the environment needed by the
complete test suite.

## Tests

From this directory:

```zsh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/playwright install chromium
.venv/bin/python -m pytest -q
```

The suite includes startup checks, live API integration checks, schedule
checks, and Playwright browser tests. It runs against the current Mac's real
`launchctl` state, while the API and browser fixtures use separate temporary
`LAUNCHMASTER_HOME` directories and therefore do not read or modify the real
launchmaster configuration or backups.

The browser tests also need network access for the interface's CDN-hosted
dependencies.
