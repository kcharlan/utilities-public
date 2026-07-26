# usage-monthly-csv

Standalone Zsh utility that runs the `ccusage claude daily` and `ccusage codex daily` JSON reports for the appropriate month, converts them to fixed-column CSV files, and writes `MMYY`-suffixed files to Downloads by default.

## What It Does

- Detects the current month and runs both upstream JSON commands with `--since YYYYMM01` and an automatically calculated month-end `--until YYYYMMDD`.
- Writes output files to `~/Downloads` by default as:
  - `ccusage-MMYY.csv` for Claude usage
  - `cusage-MMYY.csv` for Codex usage (the `cusage` prefix is retained for compatibility)
- Accepts both upstream JSON shapes used by the report generators: an object with a `daily` array or a top-level array.
- Accepts either `date` or `period` as the upstream date field.
- Normalizes the CSV `date` column to ISO `YYYY-MM-DD` when upstream tools emit display-formatted dates.
- Automatically includes both the current month and the prior month during the first 2 days of a new month.
- Supports an explicit prior-month mode for manual backfills after the boundary window.
- Accepts `--date` in either `YYYY-MM-DD` or `YYYYMMDD`, normalizes internally, and still passes `YYYYMMDD`-style values to the upstream commands.
- Replaces existing files for the same month only after the new report has been generated successfully.
- If the JSON-report path is unavailable, falls back to the legacy `ccusage_csv` and `cusage_csv` commands. It can load those commands through interactive Zsh when they are defined as functions or aliases in a startup file such as `~/.zshrc`.

## Requirements

- macOS with `zsh` and BSD `date`.
- One of these report sources:
  - Preferred: `npx` and `jq` on `PATH`. The script invokes `ccusage@latest`, so `npx` may need network access when the package is not cached.
  - Fallback: both `ccusage_csv` and `cusage_csv`, either on `PATH` or available to interactive Zsh through a startup file such as `~/.zshrc`.

## Installation

From this project directory, make the script executable and optionally symlink it into `~/Library/Scripts`:

```bash
chmod +x usage-monthly-csv
mkdir -p ~/Library/Scripts
ln -sf "$PWD/usage-monthly-csv" ~/Library/Scripts/usage-monthly-csv
```

If `~/Library/Scripts` is not already on your shell `PATH`, add it in `~/.zshrc`:

```bash
export PATH="$PATH:$HOME/Library/Scripts"
```

## Usage

```bash
usage-monthly-csv
usage-monthly-csv --prior-month
usage-monthly-csv --output-dir /tmp/usage-reports
usage-monthly-csv --date 2030-01-02
usage-monthly-csv --boundary-days 3
```

Run `usage-monthly-csv --help` for the full switch reference.

### Defaults

- Output directory: `~/Downloads`
- Boundary window: first `2` days of the month
- Standard run: current month only
- Boundary run: current month plus prior month
- Prior month override: `--prior-month` runs only the prior month

### CSV columns

Claude reports (`ccusage-MMYY.csv`) contain:

```text
date,inputTokens,outputTokens,cacheCreationTokens,cacheReadTokens,totalTokens,totalCost
```

Codex reports (`cusage-MMYY.csv`) contain:

```text
date,inputTokens,cachedInputTokens,outputTokens,reasoningOutputTokens,totalTokens,costUSD
```

## Validation

Repo-local regression harness:

```bash
zsh tests/test_usage_monthly_csv.zsh
```

Safe shell-utility validation:

```bash
./usage-monthly-csv --help
```
