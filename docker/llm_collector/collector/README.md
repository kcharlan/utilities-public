# Collector

This directory contains the Flask collection server. It receives and stores
hostname/count deltas from the browser extension.

## Functionality

The collector stores request counters, per-day counters, and the last accepted
sequence for each extension client. It is the source of truth for accepted
counts. It does not receive prompt text, response text, or token usage.

## API Endpoints

The collector exposes the following endpoints:

*   `GET /health`: A health check endpoint that returns `{"ok": true}` if the server is running.
*   `GET /counters`: Returns the current usage counters. Requires a valid API key in the `X-API-KEY` header.
*   `GET /client_status?client_id=<client_id>`: Returns the status of a specific client, including the last sequence number received. Requires a valid API key in the `X-API-KEY` header.
*   `POST /add`: The main endpoint for submitting usage data. This endpoint is idempotent and uses a sequence number to prevent duplicate submissions. Requires a valid API key in the `X-API-KEY` header.
*   `POST /reset`: Resets all usage counters to zero and creates a snapshot of the current totals. Requires a valid API key in the `X-API-KEY` header.
*   `POST /flush`: Manually triggers a save of the current in-memory state to the `state.json` file. Requires a valid API key in the `X-API-KEY` header.

## API Data Format

The `/add` endpoint expects a JSON payload with the following structure:

```json
{
  "client_id": "<unique_client_id>",
  "seq": <sequence_number>,
  "deltas": {
    "<hostname>": <request_count_delta>,
    ...
  },
  "ts": <timestamp_ms_epoch>
}
```

*   `client_id`: A unique identifier for the browser extension instance.
*   `seq`: A monotonically increasing sequence number for each request from a given client. This is used to ensure that requests are processed in order and to prevent duplicate processing of retried requests.
- `deltas`: Positive request-count increments keyed by hostname.
- `ts`: Optional event timestamp in milliseconds since the Unix epoch. Invalid
  or missing values are bucketed using the collector's current time.

## State Management

The collector stores state at `STATE_PATH` (default: `state.json` in the process working directory). The recommended Docker setup sets this to `/var/lib/llm_collector/state.json`, which is bind-mounted from the external `LLM_COLLECTOR_DATA_DIR`; the in-tree `state.json` is legacy/local-development state, not the live Docker source of truth.

Snapshots are saved under `SNAP_DIR` (default: `snapshots/` in the working
directory) whenever `/reset` is called. The Docker setup maps that path to the
external data directory. The reset handler immediately rolls successfully read
snapshot JSON into `snapshots.csv` and renames it with a `.bak` suffix.

The collector preserves the extension's idempotency contract:

- `seq <= last_seq` is an acknowledged duplicate and does not reapply deltas.
- `seq == last_seq + 1` is accepted and persisted.
- a sequence gap returns HTTP 409 with `expected_next`.
- `/reset` clears totals, date buckets, and client sequences after snapshotting,
  so clients realign through `/client_status`.

## Configuration

### API Key

The collector server authenticates requests using an API key. This key must be provided by clients in the `X-API-KEY` header.

When running the collector, the API key is passed to the application via the `API_KEY` environment variable.

If you are running the server directly for development, you can set the environment variable in your shell:
```bash
    export API_KEY="SYNTHETIC_DEVELOPMENT_KEY" # pragma: allowlist secret
```

When running with Docker (the recommended method), `../setup.sh` writes the local secret environment file and `llm_collector_container/up.sh` exports those values for Compose interpolation. Do not put the secret directly in the tracked Compose file.

The `reset_collector.sh` script and the browser extension are also clients of this server. Ensure the API key is consistent across all components.

### Daily Bucket Timezone

Accepted `/add` batches are assigned to a `daily_totals` bucket using their `ts` payload and the `BUCKET_TIMEZONE` environment variable. The default is `America/New_York`. Set `BUCKET_TIMEZONE` in `~/.config/llm_collector/secret.env` if you want daily usage to follow a different IANA timezone.

## Installation

1.  For direct development, create an isolated environment and install the required packages:
    ```
    python3 -m venv ../.venv
    ../.venv/bin/pip install -r requirements.txt
    ```
2.  Set the `API_KEY` environment variable to your desired API key.
3.  Run the collector:
    ```
    ../.venv/bin/python collector.py
    ```

## Running with Docker

For easier deployment, it is recommended to run the collector using the provided Docker configuration in the `llm_collector_container` directory.
