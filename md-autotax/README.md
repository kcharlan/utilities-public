# MD AutoTax

MD AutoTax provides Streamlit and command-line interfaces for generating
Quicken Interchange Format (QIF) files that record estimated federal and state
tax payments. It looks up monthly tax amounts for an exact monthly-income value
in a private CSV tax table.

## Components

- `app.py` — Streamlit UI for selecting a tax-table row, choosing a date, and
  writing and downloading a QIF file.
- `md_autotax_core.py` — Shared private-config validation, CSV parsing, QIF
  generation, and atomic file-writing helpers.
- `tax_qif_generator_grouped.py` — Command-line interface for generating a QIF
  file for one income and date.
- `ui.sh` — Streamlit launcher that works in the project or as a standalone
  copied wrapper.
- `setup.sh` — Creates or updates `venv/` and installs pandas and Streamlit.
- `Tax-table.example.csv`, `config.example.json`, and `project-dir.example` —
  deliberately synthetic format examples, not operational data.

## Setup

```bash
bash setup.sh
source venv/bin/activate
```

The setup script uses the project-local `venv/` and does not install packages
into the system or Homebrew Python.

## Private configuration

Operational tax data and Moneydance/QIF labels must remain outside this public
repository. Create the runtime directory and copy the synthetic template:

```bash
mkdir -p "$HOME/.md-autotax"
chmod 700 "$HOME/.md-autotax"
cp config.example.json "$HOME/.md-autotax/config.json"
chmod 600 "$HOME/.md-autotax/config.json"
```

Edit `~/.md-autotax/config.json`, replace every `SYNTHETIC` value, and set
`tax_table` to the absolute path of your private CSV. The application requires
non-empty QIF values for both `federal` and `state`; account names must omit
square brackets because the generator adds them to transfer categories.

At load time, MD AutoTax requires the runtime directory to be a real directory
and the config to be a regular file rather than a symlink. It hardens their
permissions to `0700` and `0600`, respectively. Set `MD_AUTOTAX_HOME` to use a
different runtime directory.

The CSV must contain columns whose names include these phrases
case-insensitively:

- `Monthly Gross` and `Income`
- `Federal Monthly` and `Tax`
- `State Monthly` and `Tax`

Currency symbols, commas, parentheses for negative amounts, and percentages
are accepted. Rows with a monthly income less than or equal to zero are
discarded. See `Tax-table.example.csv` for the expected shape.

The current `tax2 generate-combined` CSV uses the compact headers
`MonthlyIncome`, `FederalMonthlyTax`, and `StateMonthlyTax`. Rename those headers
to the phrases above before using that output with MD AutoTax.

## Using the Streamlit UI

```bash
./ui.sh --check
./ui.sh
```

`--check` validates the project location and the Streamlit executable without
starting the UI. When `ui.sh` remains in this project directory, it finds the
project beside itself. To copy the wrapper elsewhere, including
`~/Library/Scripts`, create its private local path configuration while your
shell is in this project directory:

```bash
mkdir -p "$HOME/.md-autotax"
chmod 700 "$HOME/.md-autotax"
printf '%s\n' "$(pwd -P)" > "$HOME/.md-autotax/project-dir"
chmod 600 "$HOME/.md-autotax/project-dir"
cp ui.sh "$HOME/Library/Scripts/md-autotax-ui"
chmod 755 "$HOME/Library/Scripts/md-autotax-ui"
"$HOME/Library/Scripts/md-autotax-ui" --check
```

The `project-dir` file must contain exactly one absolute path. The wrapper reads
it as plain text and never sources or evaluates it. `MD_AUTOTAX_PROJECT_DIR`
overrides both the colocated-project check and the configured path.
`MD_AUTOTAX_HOME` changes the runtime directory used for `project-dir` and
`config.json`.

The wrapper binds Streamlit to `127.0.0.1`, so it does not intentionally expose
the UI on the LAN.

If a standalone copy has no path configuration, its first launch or `--check`
invocation creates an empty `~/.md-autotax/project-dir`, prints an error, and
stops. Fill that file locally and retry.

In the UI:

1. Confirm the configured private tax table path, or upload a CSV directly.
2. Select a monthly gross income; the app shows federal, state, and total tax.
3. Choose a transaction date and output directory.
4. Click **Generate QIF File** to write the file, preview its contents, and
   optionally download it.

The output directory must already exist. The UI offers shortcuts for the
current directory, Desktop, Documents, and Downloads when those directories
exist.

## Command-Line Generation

```bash
venv/bin/python tax_qif_generator_grouped.py \
  --income 111111.11 \
  --date 02/03/2031 \
  --output-dir ./exports
```

This writes `exports/tax_entries_2031-02-03.qif` containing four transactions
using the labels from the private config. The requested income must exactly
match a row in the table. The CLI creates the output directory when necessary.

Use `--config` to load a different private config or `--tax-table` to override
only its table path for one invocation. Run
`venv/bin/python tax_qif_generator_grouped.py --help` for all options.

## QIF Output Format

Each generated file is private (`0600`) and contains four bank transactions:

1. Federal tax expense (debit from checking)
2. Federal tax transfer (credit to the configured federal account)
3. State tax expense (debit from checking)
4. State tax transfer (credit to the configured state account)

## Troubleshooting

- If a CSV is rejected, verify the required header phrases described above and
  confirm its currency values are parseable.
- If `./ui.sh --check` reports a missing `venv/bin/streamlit`, run
  `bash setup.sh`.
- Streamlit needs a writable temporary directory because uploaded CSV files are
  staged before parsing.

## Tests

From this directory, after setup:

```bash
venv/bin/python -m unittest discover -s tests
bash tests/test_ui_wrapper.sh
```
