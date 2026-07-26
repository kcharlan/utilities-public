# LLM Usage Collector

This project counts qualifying browser requests to selected LLM services. It
consists of a Chromium extension, a Flask collector, and a Docker runtime for
the collector.

## Purpose

The counters describe detected prompt/API requests per hostname. They are not
token counts, billing records, response captures, or exact cost measurements.
The collector receives only hostname/count deltas and client sequencing
metadata; it does not receive prompt or response content.

This can be useful for understanding relative request activity and usage
patterns across supported interfaces.

It currently supports tracking usage for **OpenAI (ChatGPT)**, **Perplexity**, **Google Gemini**, **Abacus.ai**, and **T3 Chat**.

## Folder Structure

- `INSTALLATION.md`: Full installation guide for macOS.
- `collector/`: Flask collection server and its tests.
- `extension/`: Manifest V3 extension, popup diagnostics, and dependency-free
  Node tests.
- `llm_collector_container/`: Docker build, Compose file, and lifecycle scripts.
- `snapshots/`: Rollup utility, tests, and snapshot format reference. Live
  Docker snapshots are stored in the external data directory.
- `setup.sh`: Creates or refreshes external local configuration and regenerates
  ignored `extension/config.local.js`.
- `migrate.sh`: Safely deploys this source tree to a separate
  `~/docker/llm_collector` operational copy.
- `reset_collector.sh`: Calls `/reset` with health checks, retries, and local
  reset-log rotation.
- `com.example.llmcollector.reset.plist.template`: Synthetic macOS `launchd`
  template. Replace its placeholders only in a private copy outside the
  repository.

## Guides

- **[Installation Guide](INSTALLATION.md)**: Set up the collector, browser
  extension, external state, and optional daily reset on macOS.

## Quick Start

For a complete setup guide, see [Installation Guide](INSTALLATION.md).

In brief:

1.  **Run local setup**: From this project directory, run `./setup.sh`. This creates or updates `~/.config/llm_collector/secret.env`, generates a random API key if one does not already exist, creates the external data directory, and regenerates `extension/config.local.js`.
2. **Start collector**: Run `llm_collector_container/up.sh`.
3. **Install extension**: Load the `extension` directory as an unpacked
   extension in a Chromium-based browser.

The secret file lives outside the project tree. Collector state, collector logs,
and generated snapshots live in the external directory named by
`LLM_COLLECTOR_DATA_DIR`. `reset_collector.sh` writes its small rotating
`reset_launchd.log` and `reset_launchd.err` files beside the script; they are
ignored by Git.

To explicitly refresh the moving Python 3.12 base and rebuild every dependency layer from scratch, run `llm_collector_container/update.sh`. The script recreates the collector, waits for Docker health, and verifies both `/health` and the authenticated `/counters` endpoint.

## Updating an Existing Local Install

Use `migrate.sh` when applying changes from this repo copy to the running local installation in `~/docker/llm_collector`.

From the repo project directory:

```bash
./migrate.sh
```

The script:

*   Runs the collector, snapshot, shell-config, and browser-extension tests.
*   Backs up the deployed tree, `~/.config/llm_collector/secret.env`, and the external data directory before making changes.
*   Checks live counters and, when they are non-empty, runs the deployed `reset_collector.sh` first so current totals are snapshotted and rolled into `snapshots.csv`.
*   Copies source with `rsync --delete` while preserving local-only secrets, generated extension config, logs, legacy state files, and snapshot data.
*   Regenerates `extension/config.local.js` from the external secret env.
*   Rebuilds/restarts the Docker container and validates Docker health, `/health`, `/counters`, mounts, and API-key preservation.

To preview the copy and validation plan without changing files or containers:

```bash
./migrate.sh --dry-run
```

After a successful migration, reload the unpacked browser extension so it picks up the regenerated `extension/config.local.js` and any updated extension code.

## Usage

Once the collector and extension are running, the extension will automatically track your LLM usage in the browser.

- Opening the extension popup performs an authenticated collector check. Green
  means it can reach and authenticate; red includes a specific failure reason.
  The check repeats only while the popup is open.
- The optional `reset_collector.sh` launch agent resets active counters and
  triggers a snapshot.
- The collector assigns accepted deltas to dates using the `/add` event
  timestamp and `BUCKET_TIMEZONE` (default `America/New_York`).
- `/reset` automatically rolls new snapshot JSON into `snapshots.csv` and
  renames processed JSON files with `.bak`.

To view the collected data, you can access the following endpoints on the collector server:

- **Counters:** `GET http://127.0.0.1:9000/counters` (requires `X-API-KEY`)
- **Reset:** `POST http://127.0.0.1:9000/reset` (requires `X-API-KEY`)

## Contributing

Contributions are welcome! Please feel free to open an issue or submit a pull request.

## License

This project is licensed under the MIT License.
