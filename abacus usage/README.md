# Abacus.AI Usage Export

This utility captures ChatLLM credit-usage data from the signed-in Abacus.AI
Billing/Usage page and converts the downloaded JSON response to CSV.

The capture bookmarklets call an internal Abacus.AI endpoint, so they may need
to be updated if the dashboard changes.

## Privacy

Usage exports contain private account and activity data. Keep the downloaded
JSON and generated CSV files outside this public repository. The repository
ignores `abacus_usage_*.json` and `abacus_usage_*.csv` in this directory as a
backup safeguard, but `.gitignore` is not a substitute for storing exports
elsewhere.

## Quick start

1. Follow [`Operational_Guide.md`](./Operational_Guide.md) to create the two
   browser bookmarklets.
2. Use the bookmarklets on the signed-in Abacus.AI Billing/Usage page to
   download detail or summary JSON.
3. From this directory, convert a downloaded file:

```bash
./de-abacus.py \
  ~/Downloads/abacus_usage_detail_2030-01-02.json \
  ~/Downloads/abacus_usage_detail_2030-01-02.csv
```

When the output argument is omitted, the script writes a `.csv` beside the
input file. It requires Python 3 and has no third-party dependencies.

## Files

- [`Operational_Guide.md`](./Operational_Guide.md) explains how to install and
  use the capture bookmarklets.
- [`de-abacus.py`](./de-abacus.py) converts an Abacus.AI JSON response to CSV.

The converter reads the column order from `result.columns`; when that field is
missing, it infers columns from `result.log`. It places `date` first when
present, rounds numeric values to two decimal places, ignores row fields that
are not output columns, and fills missing values with `0` by default.

## Command-line options

```text
usage: de-abacus.py [-h] [--no-zeros] [-v] input [output]

positional arguments:
  input           Path to input JSON file
  output          Path to output CSV file (default: input_filename.csv)

options:
  -h, --help      show this help message and exit
  --no-zeros      Leave missing values empty instead of filling with 0
  -v, --verbose   Enable verbose debug logging
```

Use `--no-zeros` to leave missing values blank instead:

```bash
./de-abacus.py --no-zeros \
  ~/Downloads/abacus_usage_summary_2030-01-02.json \
  ~/Downloads/abacus_usage_summary_2030-01-02.csv
```
