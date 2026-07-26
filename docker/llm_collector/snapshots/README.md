# Snapshots

This tracked directory contains the rollup utility, tests, and the snapshot
format reference. With the recommended Docker setup, live snapshot JSON,
`snapshots.csv`, and `.bak` files are stored in the external
`LLM_COLLECTOR_DATA_DIR/snapshots` directory, not in this public source tree.

## Rollup Script

The collector's `/reset` handler automatically applies the same rollup logic to
the configured external snapshot directory. The standalone
`rollup_snapshots.py` utility processes snapshot files located beside the
script; it is primarily for legacy/local-development data and tests.

### Usage

From the project root, run it with the project's virtual environment:

```sh
.venv/bin/python snapshots/rollup_snapshots.py
```

The script supports a command-line argument to control how dates are calculated for legacy snapshots that do not include `daily_totals`.

*   `--cutoff-hour <HOUR>`: Sets an hour in **UTC** before which snapshots are attributed to the previous day. This is useful for daily rollups that run after midnight but should include data for the prior day. For example, if you are in EST (UTC-5) and want to include all snapshots up to 2 AM local time, you would set the cutoff to `7` (2 + 5). The default value is `8`.

After a snapshot is successfully rolled up, it is renamed with a `.bak` suffix so it will not be processed again.

## Snapshots CSV Format

The `snapshots.csv` file will have the following format:

```csv
date,chat.openai.com,bard.google.com,...
YYYY-MM-DD,12345,67890,...
```

These values are request counts, not token counts.

Where:

*   `date`: The daily bucket date. For new snapshots this comes from the collector's `BUCKET_TIMEZONE`; for legacy snapshots it is derived from the snapshot filename timestamp and `--cutoff-hour`.
- `chat.openai.com`, `gemini.google.com`, etc.: Columns for each hostname,
  containing the request count for that day.

## Filename Convention

The snapshots are named using the following convention:

`snapshot_<timestamp>.json`

Where `<timestamp>` is a Unix timestamp in milliseconds representing the time the snapshot was created. For example, `snapshot_1760327682560.json` was created at the time represented by the timestamp `1760327682560`.

## Format

The snapshots are JSON files containing the collected usage data at the time of the reset. New snapshots include both the backwards-compatible `totals` object and the preferred `daily_totals` object.

```json
{
  "totals": {
    "chat.openai.com": 12345,
    "bard.google.com": 67890
  },
  "daily_totals": {
    "2026-04-25": {
      "chat.openai.com": 12345
    },
    "2026-04-26": {
      "bard.google.com": 67890
    }
  }
}
```
