# launchmaster

launchmaster is a local macOS launchd control center served by a single uv-managed FastAPI launcher with an embedded React UI.

## Run

```zsh
./launchmaster
```

The launcher requires [uv](https://docs.astral.sh/uv/) and binds to localhost. Runtime configuration and backups live under `~/.launchmaster/` by default. Set `LAUNCHMASTER_HOME` to isolate that state:

```zsh
LAUNCHMASTER_HOME=/tmp/launchmaster-sandbox ./launchmaster --no-browser
```

## Tests

```zsh
cd /Users/example/source/utilities/launchmaster
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/playwright install chromium
.venv/bin/python -m pytest -q
```

The API and Playwright fixtures use separate temporary `LAUNCHMASTER_HOME` directories, so tests never read or modify the real user configuration.
