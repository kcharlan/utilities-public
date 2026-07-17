# Snapshots

This directory contains snapshots of the collected LLM usage data. Snapshots are created automatically by the data collection server whenever the `/reset` endpoint is called.

## Rollup Script

The `rollup_snapshots.py` script is designed to process the individual JSON snapshot files and aggregate them into a single `snapshots.csv` file. This CSV file provides a daily summary of LLM usage. New snapshots include explicit `daily_totals` buckets from the collector, so usage is attributed by the original `/add` timestamp date instead of the reset time.

### Usage

To run the script, execute the following command in your terminal:

```sh
python3 rollup_snapshots.py
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

Where:

*   `date`: The daily bucket date. For new snapshots this comes from the collector's `BUCKET_TIMEZONE`; for legacy snapshots it is derived from the snapshot filename timestamp and `--cutoff-hour`.
*   `chat.openai.com`, `bard.google.com`, etc.: Columns for each hostname, containing the total token counts for that day.

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
