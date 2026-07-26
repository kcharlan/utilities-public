# Tax2 Usage Guide

## Start the application

Tax2 requires [uv](https://docs.astral.sh/uv/) but no project-local installation:

```bash
./tax2
```

The launcher starts a local server at `http://127.0.0.1:8000` and opens the
browser. On first use, uv may access the network to resolve the dependencies in
the launcher's PEP 723 header.

```bash
# Choose another port if 8000 is occupied
./tax2 --port 9000

# Start without opening a browser
./tax2 --no-browser
```

Tax2 does not scan for a free port. If startup reports that the address is in
use, rerun it with another `--port` value.

## Calculate estimated tax

1. Select a tax year and filing status.
2. Choose **Rules Engine** or **Lookup Table**.
3. Enter monthly unearned and earned income separately.
4. Select at least one state.
5. When multiple states are selected, set each state's allocation percentage.

The UI recalculates automatically. Federal tax is computed once on 100% of the
combined income. Each state is computed separately from its allocated income.
Allocation percentages are independent: two selected states may both be 100%,
and Tax2 neither normalizes the percentages nor requires a total of 100%.

### Rules Engine

Rules mode computes directly from YAML files under `rules/`. It preserves the
earned/unearned split so components can apply to selected income classes. The
federal rules currently treat both buckets as ordinary income.

The year selector is based on available federal rules. Every selected state must
also have rules for that year. Pennsylvania currently has 2026 rules only, so
selecting Pennsylvania for 2025 reports that the state rules are unavailable.

### Lookup Table

Table mode reads generated `combined_YYYY_STATE.csv` files from `tables/`.
For the configured legacy alias state, it can fall back to
`combined_YYYY.csv`. It selects the row whose `MonthlyIncome` is nearest to the
entered amount rather than interpolating.

Generated tables assume all income is unearned, so table mode does not preserve
the entered earned/unearned split. State allocation is applied to the monthly
income before row lookup. Use rules mode when an earned-only component is
enabled.

## Generate lookup tables

Run the Typer CLI through uv with the tracked CLI requirements:

```bash
uv run --with-requirements requirements.txt cli.py generate-combined \
  --year 2026 --states GA,PA
```

The command writes:

- one `federal_YYYY.parquet`;
- one `{state}_YYYY.parquet` per successfully generated state;
- one `combined_YYYY_STATE.csv` per state; and
- `combined_YYYY.csv` when the configured legacy alias state was included.

Combined CSVs have exactly these columns:

```text
MonthlyIncome,FederalMonthlyTax,StateMonthlyTax
```

If federal rules for the requested year are unavailable, the CLI falls back to
the latest federal rules year. A requested state without rules for that resolved
year is reported and causes a nonzero exit. `--state` remains as a deprecated
single-state alias for `--states`.

Use `tablegen` for one rules file or rules directory:

```bash
uv run --with-requirements requirements.txt cli.py tablegen \
  --rules rules/states/PA --year 2026 \
  --filing-status single --inc-max 500000 --step 50 \
  --out tables/pa_2026.parquet
```

## Export QIF

The right panel lets you set:

- transaction date;
- payee;
- federal expense category and transfer account; and
- an expense category and transfer account for each selected state.

Select **Download QIF** after a successful calculation. The downloaded
`tax_transactions.qif` contains one federal expense/transfer pair and one
expense/transfer pair per selected state, using the displayed monthly tax
amounts. Multi-state memo lines include the state code.

State QIF defaults come from the selected state's YAML. Per-state
`qif_overrides` in the runtime config take precedence when the UI first loads;
fields remain editable in the UI.

## Runtime configuration

Tax2 stores preferences at `~/.tax2/config.yaml`, or
`$TAX2_HOME/config.yaml` when `TAX2_HOME` is set. It creates the file with
defaults when missing:

```yaml
default_states:
  - GA
legacy_combined_alias: GA
qif_overrides: {}
```

- `default_states` controls the initial state selection and is updated when the
  UI selection changes.
- `legacy_combined_alias` controls which generated state table is copied to
  `combined_YYYY.csv`.
- `qif_overrides` can supply `state_expense` and `state_transfer` by state code.

The config contains preferences only. Keep all rates, deductions, brackets, and
locality details in the rules YAML files.

## Add tax years and states

To add a year, create the applicable files:

```text
rules/federal/YYYY.yaml
rules/states/GA/YYYY.yaml
```

To add a state, create `rules/states/STATE/YYYY.yaml`. The UI discovers state
directories and their available years automatically. The rules file may use the
legacy top-level `standard_deduction`/`brackets` shape or the v2 `components`
shape, but not both.

A v2 component looks like:

```yaml
components:
  - name: state_income_tax
    enabled: true
    applies_to: [earned, unearned]
    standard_deduction:
      single: 0
      married_joint: 0
    brackets:
      single:
        - {up_to: null, rate: 0.0307}
      married_joint:
        - {up_to: null, rate: 0.0307}
```

Use generic component names. Put jurisdiction or locality wording in `label` and
put rates in bracket data so a locality change remains a data edit.

## Pennsylvania notes

- The checked-in 2026 Pennsylvania personal-income-tax component is a flat
  3.07% with no standard deduction.
- Tax2 does not distinguish qualified from ordinary dividends for Pennsylvania.
- Return of capital is excluded from entered income until basis is exhausted;
  after that, enter it as gain. Tax2 does not track basis.
- The local EIT component in `rules/states/PA/2026.yaml` is disabled by default
  and applies only to earned income. Before enabling it, verify that its label
  and rate match the applicable locality, then set `enabled: true`.
- Tax Forgiveness, estimated-payment thresholds and due dates, residency
  timelines, county property tax, and local services tax are not modeled.

## Troubleshooting

**The port is already in use**

```bash
./tax2 --port 9000
```

**The UI reports a missing table**

Generate tables for the selected year and every selected state, then retry.

**The UI reports missing state rules**

Choose a year listed for that state or add the missing state rules file. The tax
year selector reflects federal years, not the intersection of all state years.

**The calculation is unexpected**

Confirm the selected year, filing status, income bucket, state allocations, and
computation mode. Inspect the applicable YAML values. Generated lookup tables
may be stale after rule changes, so regenerate them or switch to rules mode.
