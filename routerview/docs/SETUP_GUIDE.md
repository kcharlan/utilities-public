# RouterView Setup Guide

This guide covers the current CSV-only RouterView workflow.

## First Run

Start RouterView from the project directory or through a symlink:

```zsh
./routerview
```

On first launch, assuming the default runtime location, RouterView will:

1. Use [uv](https://docs.astral.sh/uv/) (`brew install uv`) to resolve its Python dependencies into uv's shared cache (this may briefly hit the network)
2. Create `~/.routerview/`
3. Create or open `~/.routerview/routerview.db`
4. Start the local server, defaulting to `http://127.0.0.1:8100`
5. Open the dashboard in your browser

If port `8100` is busy, RouterView automatically picks the next free port and prints the change.

Set `ROUTERVIEW_HOME` before launch to use a runtime directory other than `~/.routerview/`. Use `--db` to select a different SQLite database path.

The dashboard loads its JavaScript and CSS libraries from public CDNs, so the browser needs network access unless those assets are already cached. RouterView has no authentication; keep the default `127.0.0.1` bind address unless you intentionally want to expose it to a trusted network.

## Importing OpenRouter Data

1. Export your OpenRouter Activity data as CSV.
2. In RouterView, open **Settings**.
3. Under **Import**, choose the CSV file.
4. Wait for the import result banner.

Successful imports report both inserted and skipped rows.

- New rows are inserted into `generations`
- Duplicate `generation_id` rows are skipped
- The dashboard refreshes immediately after the import completes

## Re-Import Behavior

Re-importing the same file is safe.

- Existing rows are not overwritten
- Duplicate rows count toward `skipped`
- The database row count stays stable

This is intended for repeated imports of overlapping OpenRouter exports.

## Daily Summary Refresh

RouterView rebuilds all daily summaries after each successful CSV import and refreshes its in-memory anomaly baselines. Settings also has a **Refresh Stats** action that recomputes the most recent two days.

## Repairing Imported Timestamps

Use **Settings → Rebuild Timestamps** only when previously imported rows have incorrect UTC timestamps. RouterView first writes a point-in-time database backup under `<runtime-home>/backups/`, then:

- derives timestamps from OpenRouter generation IDs that contain a recoverable Unix epoch
- leaves rows without a recoverable epoch unchanged
- rebuilds summaries and anomaly baselines if any rows changed

## Purging Old Data

Use **Settings → Purge Data** to delete all generations and daily summaries strictly before a chosen date. Rows on the chosen date are retained.

## Troubleshooting

### The dashboard opens empty after startup

That is expected until you import a CSV.

### I imported a CSV and the current view still looks stale

Current builds refresh the active dashboard and log view immediately after import. If you still suspect stale state, use the `R` keyboard shortcut to force a refresh and check the import banner for errors.

### Imported rows are all reported as inserted on re-import

Current builds treat duplicate `generation_id` rows as skipped. If you see otherwise, confirm the CSV actually contains the same generation IDs and not a different export window.

### I need the app on a fixed port

Start it with:

```zsh
./routerview --port 8110
```

RouterView will still fall forward if that port is already in use.

It checks up to 20 consecutive ports, starting with the requested port, and exits with an error if none is available.
