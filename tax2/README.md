# Tax App (rules-based + QIF export)

A rules-driven tax calculator with optional pre-generated tables and **byte-compatible QIF export**. Uses a uv-managed FastAPI backend with an embedded React SPA (no Streamlit, no Node.js tooling). You can run the web UI, batch-generate tax tables via CLI, and export Quicken-ready transactions from the same codebase.

## Quick Start

```bash
# No setup required - just run
./tax2

# Or with custom port
./tax2 --port 9000

# Don't auto-open browser
./tax2 --no-browser

# Optional custom rules directory
./tax2 /path/to/rules

# CLI mode for table generation (uses uv with the pinned requirements)
uv run --with-requirements requirements.txt cli.py generate-combined --year 2026
```

The `tax2` launcher requires [uv](https://docs.astral.sh/uv/) (`brew install uv`) and declares its dependencies in a PEP 723 inline-metadata header. On first run:
- uv resolves the dependencies (FastAPI, uvicorn, pandas, pyyaml, etc.) into its shared cache — that invocation may briefly hit the network
- the web server starts on port 8000 and your browser opens

Subsequent runs start instantly. No virtual environment or state files are written to your home directory.

> `requirements.txt` is retained for the repo's dev venv (`.venv`) and the CLI examples above; the launcher no longer reads it — the PEP 723 header in `tax2` is authoritative for the web app's dependencies.

## Features

- **Rules Engine** – Parse YAML rules describing brackets, deductions, and credits for both federal and state systems. Supports tiered rates, phase outs, and standard deduction logic.
- **Dynamic Year Selection** – Automatically defaults to the current tax year. Allows manual selection of other available years and falls back to the latest rules if the current year's rules are missing.
- **Table Lookup** – Load precomputed CSV/Parquet tables to bypass runtime calculations or to cross-check the rules engine for regressions.
- **QIF Export** – Emit bundled transactions (federal expense/transfer plus one expense/transfer pair per selected state) that import cleanly into Quicken or Moneydance.
- **Consistency Check** – UI mode that compares live rule calculations to table lookup values and flags drift.

## Project Layout

```
tax2                # uv-managed entry point (FastAPI server + embedded React SPA)
cli.py              # Typer CLI for table generation (tablegen, generate-combined)
taxkit/             # Core library (engine, rules loader, table generation, QIF writer, utils)
rules/              # YAML rulesets
  federal/          #   Federal brackets (2025.yaml, 2026.yaml)
  states/GA/        #   Georgia state rules (2025.yaml, 2026.yaml)
  states/PA/        #   Pennsylvania state rules (2026.yaml)
tables/             # Output location for generated tables (Parquet + CSV)
tests/              # Unit, API, rules, table-generation, and QIF regression tests
docs/               # Design docs (Tech_migration.md, UI_Design_Reference.html, Usage.md)
archive/            # Previous Streamlit version (archive/streamlit_version/)
```

### Key Modules in `taxkit`

- `engine.py` – Evaluates income against rules to compute per-period tax owed.
- `rules_loader.py` – Validates and parses YAML into typed models (`models.py`).
- `tablegen.py` – Sweeps an income grid and records monthly/annual obligations.
- `qif.py` – Builds transaction text blocks with consistent memo/ledger structure.
- `utils.py` – Handles year selection and rule path resolution logic.

## Running the Web UI

```bash
./tax2
```

The embedded React SPA communicates with the FastAPI backend via `/api/*` JSON endpoints. Available modes:

1. **Rules Compute** – Select a tax year (defaults to current), filing status, earned/unearned monthly income, and one or more states to compute monthly obligations on the fly.
2. **Table Lookup** – Load a pre-generated combined CSV table and inspect values.
3. **Cross-Check** – Run both engines simultaneously and view deltas.
4. **QIF Export** – Choose income, number of months, and target ledger names to download QIF entries.

State allocation percentages are independent. GA at 100% and PA at 100% is valid and computes full tax for both states; percentages are never normalized or forced to sum to 100.

## Generating Tables from Rules

To generate both Federal and State tables and merge them into a single CSV (replaces the old `generate_tables.sh` script):

```bash
# Generate for the current year
uv run --with-requirements requirements.txt cli.py generate-combined

# Generate for a specific year and multiple states
uv run --with-requirements requirements.txt cli.py generate-combined --year 2026 --states GA,PA
```

This will produce:
- `tables/federal_YYYY.parquet`
- `tables/ga_YYYY.parquet`
- `tables/pa_YYYY.parquet`
- `tables/combined_YYYY_GA.csv`
- `tables/combined_YYYY_PA.csv`
- `tables/combined_YYYY.csv` (legacy alias for the configured default state)



## Table Format Expectations

- Per-state combined table: `MonthlyIncome`, `FederalMonthlyTax`, `StateMonthlyTax`.
- Individual tables: `MonthlyIncome`, `MonthlyTax` (federal) and the same for state.
- All amounts are monthly; annual values are derived in the UI when needed.
- Table generation treats all income as unearned. Rules mode is authoritative for earned-only components such as PA local EIT.

## QIF Output

- Each payment cycle generates two federal transactions plus two transactions per selected state:
  1. Expense: `Tax:Federal Income Tax Estimated Paid`
  2. Transfer: `[Federal Income Taxes]`
  3. State expense: defaults from the state YAML `qif.state_expense`
  4. State transfer: defaults from the state YAML `qif.state_transfer`
- Dates follow `MM/DD/YY` format inside QIF while memo lines keep `MM/DD/YYYY`.
- Output is byte-compatible with the earlier `md-autotax` tooling.

## Runtime Config

User preferences live at `~/.tax2/config.yaml` or `$TAX2_HOME/config.yaml` when `TAX2_HOME` is set. The config stores `default_states`, `legacy_combined_alias`, and optional per-state QIF account overrides. Tax rates, brackets, and local tax details stay in repo YAML rules only.

## Rules Components

Rules may use a v2 `components` list. Each component has a generic `name`, optional display `label`, `enabled`, `applies_to` (`earned`, `unearned`, or both), `standard_deduction`, and `brackets`. Component names are engine identifiers; locality names and rates belong in YAML labels and bracket data, not Python code.

## Testing

Create the tracked test environment and run the full suite:

```bash
cd /Users/example/source/utilities/tax2
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

## Extending

- Add new states by dropping YAML files under `rules/states/{STATE}/{YEAR}.yaml`.
- Introduce additional credit/phase-out models by expanding `taxkit.models` and updating the engine dispatcher.
- To support other export formats, create new writers alongside `taxkit.qif` and wire them into the UI download options.
