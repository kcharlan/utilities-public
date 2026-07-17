# RouterView Setup Guide

This guide covers the current CSV-only RouterView workflow.

## First Run

Start RouterView from the project directory or through a symlink:

```zsh
./routerview
```

On first launch RouterView will (via [uv](https://docs.astral.sh/uv/), `brew install uv`):

1. Create `~/.routerview/`
2. Resolve its dependencies into uv's shared cache (may briefly hit the network on the first run)
3. Start the local server, defaulting to `http://127.0.0.1:8100`
4. Open the dashboard in your browser

If port `8100` is busy, RouterView automatically picks the next free port and prints the change.

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

RouterView rebuilds daily summaries after each successful CSV import. The admin refresh controls remain available in Settings if you want to recompute summaries later.

## Purging Old Data

Use **Settings → Purge Data** to delete all generations and daily summaries before a chosen date.

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
