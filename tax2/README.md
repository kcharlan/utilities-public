# Tax2

Tax2 is a rules-driven federal and state estimated-tax calculator with an
embedded React web UI, table generation, table lookup, and QIF export. The
executable is a uv-managed Python script that serves a local FastAPI app; the UI
does not require Node.js or a separate frontend build.

Tax2 currently includes federal rules for 2025 and 2026, Georgia rules for 2025
and 2026, and Pennsylvania rules for 2026. The checked-in rules are application
inputs, not tax advice; verify rates and eligibility rules before relying on the
results.

## Quick start

Install [uv](https://docs.astral.sh/uv/), then run:

```bash
./tax2
```

The launcher resolves its PEP 723 dependencies through uv, starts the server at
`http://127.0.0.1:8000`, and opens that address in the default browser. The first
run may access the network while uv fills its shared cache. Tax2 also creates a
preference file at `~/.tax2/config.yaml`, or at
`$TAX2_HOME/config.yaml` when `TAX2_HOME` is set.

Useful options:

```bash
./tax2 --port 9000
./tax2 --no-browser
./tax2 --help
```

The preferred port is not selected automatically. If it is occupied, choose a
different port with `--port`.

## Web UI

The UI:

- separates monthly earned and unearned income;
- computes federal tax once on the total income;
- discovers available states from `rules/states/`;
- supports one or more independently allocated states;
- calculates from YAML rules or generated lookup tables; and
- exports the displayed monthly estimates as one QIF bundle.

The selected year defaults to the current year when federal rules exist,
otherwise to the latest available federal year. A state still needs a rules
file, or a generated table in table mode, for the selected year. For example,
Pennsylvania has no 2025 rules and returns a clear error if selected for 2025.

State allocations range from 0% to 100% and are independent. GA at 100% and PA
at 100% is valid; Tax2 does not normalize the values or require them to total
100%. In rules mode, each state computes tax on its allocated share of earned
and unearned income. In table mode, the allocation is applied before the
nearest-income row is selected.

Generated tables treat all income as unearned. Use rules mode when an
earned-only component, such as Pennsylvania local EIT, is enabled.

## Generate lookup tables

The CLI uses `requirements.txt` because `typer` is not needed by the web
launcher:

```bash
uv run --with-requirements requirements.txt cli.py generate-combined --year 2026 --states GA,PA
```

`--states` accepts a comma-separated list. Without it, the command uses
`default_states` from the runtime config. The deprecated `--state` option still
accepts one state.

For each requested state with rules for the selected year, the command writes:

```text
tables/federal_YYYY.parquet
tables/{state}_YYYY.parquet
tables/combined_YYYY_STATE.csv
```

It also copies the configured `legacy_combined_alias` state's combined CSV to
`tables/combined_YYYY.csv` when that state was generated. Combined CSVs contain
`MonthlyIncome`, `FederalMonthlyTax`, and `StateMonthlyTax`. Generated table
files are ignored by Git.

For lower-level table generation from a single rules file or directory:

```bash
uv run --with-requirements requirements.txt cli.py tablegen \
  --rules rules/federal --year 2026 --out tables/federal_2026.parquet
```

## QIF export

Each exported payment bundle contains two federal transactions followed by two
transactions for every selected state:

1. an expense transaction with a negative amount; and
2. a transfer transaction with the corresponding positive amount.

The default expense categories and transfer accounts come from the state YAML
`qif` block and can be edited in the UI. Dates use `MM/DD/YY` on QIF date lines
and `MM/DD/YYYY` in memos. A single-state Georgia export retains compatibility
with the previous Tax2/`md-autotax` transaction text; multi-state memos include
the state code.

## Runtime configuration

The generated YAML config contains preferences only:

```yaml
default_states:
  - GA
legacy_combined_alias: GA
qif_overrides: {}
```

Selecting states in the UI updates `default_states`. `legacy_combined_alias`
controls the state represented by `combined_YYYY.csv`. Optional per-state
`qif_overrides` are read when populating QIF fields. Tax rates, brackets, and
local-tax details belong in repository rule files, never in this config.

## Rules model

Legacy federal and Georgia YAML files define top-level
`standard_deduction` and `brackets`; the loader normalizes them to one component.
A v2 rules file can instead define a `components` list. Each component supports:

- a generic `name` and optional display `label`;
- `enabled`;
- `applies_to` (`earned`, `unearned`, or both);
- per-filing-status `standard_deduction`; and
- per-filing-status `brackets`.

Do not combine top-level brackets with `components` in one file. Component names
are engine identifiers; locality names and rates belong in labels and bracket
data rather than Python code.

## Project layout

```text
tax2                  uv-managed FastAPI server and embedded React SPA
cli.py                Typer table-generation CLI
taxkit/               rules loader, engine, table generator, QIF, and config
rules/federal/        federal YAML rules
rules/states/         state YAML rules organized by state code
tables/               generated lookup tables (ignored except legacy fixtures)
tests/                unit, API, CLI, config, and regression tests
docs/Usage.md         detailed operating guide
docs/multi_state_design.md
                      durable multi-state design and invariants
docs/UI_Design_Reference.html
                      visual reference for the embedded UI
```

## Tests

Create an isolated development environment and run the complete project suite:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

When a launcher header changes, also run the repository-level uv header guard:

```bash
uv run --script ../tools/check_uv_headers.py
```

## Adding rules

Add a year by creating the corresponding federal and state YAML files. Add a
state by creating `rules/states/{STATE}/{YEAR}.yaml`; the UI discovers state
directories automatically. See [docs/Usage.md](docs/Usage.md) for the workflow
and Pennsylvania-specific limitations.
