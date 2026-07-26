# LLM Usage Tracker — Full Installation Guide (macOS)

This guide sets up the current source tree. It does not require creating or
editing Dockerfiles, Compose files, or tracked source configuration.

## Prerequisites

- macOS
- Docker Desktop with Docker Compose
- a Chromium-based browser such as Chrome or Vivaldi
- `curl`
- Node.js 18 or newer only if you use `migrate.sh` or run extension tests

## 1. Create Private Configuration

From the `docker/llm_collector` directory:

```sh
./setup.sh
```

Setup creates or updates:

- `~/.config/llm_collector/secret.env`, mode `0600`
- `~/.local/state/llm_collector/` by default
- ignored `extension/config.local.js`

On first run, setup generates a random API key when OpenSSL is available and
prompts for the collector URL, data directory, and daily bucket timezone.
Existing values are retained on later runs. Do not put the secret environment
file, generated extension config, state, logs, or snapshots in this public
repository.

To recreate only generated configuration from an existing complete secret env:

```sh
./setup.sh --non-interactive
```

## 2. Start the Collector

```sh
./llm_collector_container/up.sh
```

The script loads the external secret env, builds the image, and starts
`llm-collector`. Compose publishes the service at `127.0.0.1:9000`, mounts the
source tree for collector code, and mounts the configured external data
directory at `/var/lib/llm_collector`.

Verify container health:

```sh
docker inspect llm-collector --format '{{.State.Health.Status}}'
curl -fsS http://127.0.0.1:9000/health
```

To verify the authenticated endpoint without printing the key:

```sh
set -a
. ~/.config/llm_collector/secret.env
set +a
curl -fsS -H "X-API-KEY: $API_KEY" "$COLLECTOR_URL/counters"
```

Use `llm_collector_container/down.sh` to stop the service and
`llm_collector_container/update.sh` for an explicit clean dependency/base-image
refresh followed by health checks.

## 3. Load the Browser Extension

1. Open `chrome://extensions` or the equivalent page in your browser.
2. Enable **Developer mode**.
3. Choose **Load unpacked**.
4. Select this project's `extension/` directory.
5. Open the extension popup and confirm **Collector connected**.

Reload the unpacked extension after every `setup.sh`, migration, or extension
code update so it picks up `config.local.js` and source changes.

The extension counts allowlisted outbound POST requests; it does not inspect
response bodies or calculate tokens. Generate a prompt on a supported service,
open the popup, and compare its server counters with authenticated `/counters`.

## 4. Optional Daily Reset

`reset_collector.sh` checks health and current counters, calls authenticated
`POST /reset` only when counts are non-empty, and retries transient failures.
The collector snapshots the totals and automatically rolls them into the
external `snapshots/snapshots.csv`.

To schedule it at midnight:

1. Copy `com.example.llmcollector.reset.plist.template` to a private file under
   `~/Library/LaunchAgents/`.
2. Replace `__SCRIPT_DIR__` with the absolute path to the operational
   `llm_collector` directory.
3. Replace `__LOG_DIR__` with a private writable log directory.
4. Validate and load the private plist with the current macOS `launchctl`
   workflow.

Do not edit or commit the tracked synthetic template with personal paths.
`reset_collector.sh` also maintains ignored `reset_launchd.log` and
`reset_launchd.err` files beside the script.

## 5. Updating a Separate Operational Copy

The recommended deployment model keeps the Git source and the running copy
separate. From the source project, preview:

```sh
./migrate.sh --dry-run
```

Then run:

```sh
./migrate.sh
```

By default this deploys to `~/docker/llm_collector`. It runs all project tests,
backs up deployed code plus external config/state, snapshots non-empty live
counters, copies source while preserving local-only files, regenerates
extension config, rebuilds the container, and validates health, authentication,
mounts, and API-key preservation.

Use `--deploy-dir` and `--backup-root` to override the external locations.
Reload the unpacked extension after a successful migration.

## Troubleshooting

| Symptom | Check |
|---|---|
| Popup reports configuration required | Run `./setup.sh`, then reload the unpacked extension. |
| Popup reports authentication failure | Regenerate extension config from the same external secret env used by the container, then reload it. |
| Collector is unreachable | Check `docker compose ps` and container logs from `llm_collector_container/`; verify `COLLECTOR_URL`. |
| A send is not counted | Inspect the popup debug records and service-worker console; the provider endpoint may not match the current allowlist. |
| Duplicate-looking counts | Check whether the application makes distinct allowlisted requests outside the 1.5-second per-tab/host/path debounce window. |
| Daily reset did not run | Run `reset_collector.sh` manually, inspect its ignored reset logs, and verify the private launch-agent paths. |
