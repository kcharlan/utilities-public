# usage-monthly-csv

Standalone Zsh utility that runs the `ccusage claude daily` and `ccusage codex daily` JSON reports for the appropriate month, converts them to stable CSV, and writes `MMYY`-suffixed files to Downloads by default.

## What It Does

- Detects the current month and runs both upstream JSON commands with `--since YYYYMM01` and an automatically calculated month-end `--until YYYYMMDD`.
- Writes output files to `~/Downloads` by default as:
  - `ccusage-MMYY.csv`
  - `cusage-MMYY.csv`
- Accepts both upstream JSON shapes used by the report generators: an object with a `daily` array and a top-level array.
- Normalizes the CSV `date` column to ISO `YYYY-MM-DD` when upstream tools emit display-formatted dates.
- Automatically includes both the current month and the prior month during the first 2 days of a new month.
- Supports an explicit prior-month mode for manual backfills after the boundary window.
- Accepts `--date` in either `YYYY-MM-DD` or `YYYYMMDD`, normalizes internally, and still passes `YYYYMMDD`-style values to the upstream commands.
- Falls back to `zsh -ic` when the report generators are defined as shell functions in `~/.zshrc` instead of standalone executables.

## Requirements

- macOS with `zsh` and BSD `date`.
- `npx` and `jq` available on `PATH`.
- Optional fallback only: `ccusage_csv` and `cusage_csv` available either directly on `PATH` or as functions/aliases loaded by interactive Zsh startup files such as `~/.zshrc`.

## Installation

Copy or symlink the executable into `~/Library/Scripts` if you want to run it from your personal scripts directory:

```bash
chmod +x /Users/example/source/utilities/usage-monthly-csv/usage-monthly-csv
ln -sf /Users/example/source/utilities/usage-monthly-csv/usage-monthly-csv ~/Library/Scripts/usage-monthly-csv
```

If `~/Library/Scripts` is not already on your shell `PATH`, add it in `~/.zshrc`:

```bash
export PATH="$PATH:$HOME/Library/Scripts"
```

## Usage

```bash
usage-monthly-csv
usage-monthly-csv --prior-month
usage-monthly-csv --output-dir ~/Downloads
usage-monthly-csv --date 2026-01-02
usage-monthly-csv --boundary-days 3
```

Run `usage-monthly-csv --help` for the full switch reference.

### Defaults

- Output directory: `~/Downloads`
- Boundary window: first `2` days of the month
- Standard run: current month only
- Boundary run: current month plus prior month
- Prior month override: `--prior-month` runs only the prior month

## Validation

Repo-local regression harness:

```bash
zsh tests/test_usage_monthly_csv.zsh
```

Safe shell-utility validation:

```bash
./usage-monthly-csv --help
```
