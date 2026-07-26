# Multi-State Tax Design

Status: implemented. This document records the durable architecture, behavioral
invariants, and known limitations of Tax2's multi-state support.

## Goals and boundaries

Tax2 supports one or more states in a single calculation and QIF export. Federal
tax is calculated once; every state receives an independent allocation of the
entered earned and unearned income. New states and tax components should be
addable through YAML without jurisdiction-specific branches in the engine.

Tax2 intentionally does not automate residency timelines, estimated-payment
thresholds or due dates, return-of-capital basis, federal preferential rates for
qualified dividends or long-term capital gains, Pennsylvania Tax Forgiveness,
county property tax, or local services tax.

## Rules schema

The engine consumes a component-only model. `taxkit.rules_loader.load_rules`
normalizes legacy YAML containing top-level `standard_deduction` and `brackets`
into one enabled component that applies to earned and unearned income. A file
that combines top-level brackets with `components` is rejected as ambiguous.

Each v2 component contains:

- a generic `name` and optional display `label`;
- an `enabled` flag;
- one or both values in `applies_to`: `earned` and `unearned`;
- a standard deduction by filing status; and
- brackets by filing status.

The engine sums enabled components, then applies jurisdiction-level credits and
floors the result at zero. Component names are identifiers only: engine, API,
and QIF behavior must not branch on a component name or state code. Locality
names and rates remain YAML data.

Federal and Georgia files currently use the normalized legacy shape.
Pennsylvania 2026 uses components: a 3.07% state-income-tax component for both
income classes and a disabled earned-only local EIT component.

## Income and allocation model

`TaxInput` stores annual `earned_income` and `unearned_income`; its
`annual_income` property is their sum. The UI accepts monthly values and
annualizes them for rules computation.

Federal tax always uses the full entered income. For each state, rules mode
multiplies both income buckets by that state's allocation and computes tax on
the resulting income. This distinction matters for deductions and progressive
brackets: Tax2 does not compute a full-income state tax and then prorate it.

Allocation percentages:

- range from 0% through 100%;
- default to 100%;
- are independent across states; and
- are never normalized or required to sum to 100%.

Thus GA at 100% and PA at 100% deliberately computes full state tax for both.
The caller is responsible for choosing allocations appropriate to the tax
situation.

## State discovery and API

`GET /api/states` scans `rules/states/*/`, returning each directory's upper-case
code, latest rules display name, available years, and QIF defaults. Adding a
state directory therefore makes the state selectable without a frontend code
change.

`POST /api/compute` accepts monthly earned/unearned income, filing status, year,
mode, and a non-empty state selection list. State codes and allocation bounds
are validated. The response contains one federal result, an ordered state result
list, combined totals, and an effective rate.

The UI's year selector is based on federal rule years. Rules mode returns a
clear error when a selected state has no file for that year; it does not
silently substitute another state year.

## Lookup tables

Table generation treats the entire income amount as unearned so the output
remains a one-dimensional income grid. It writes:

```text
federal_YYYY.parquet
{state}_YYYY.parquet
combined_YYYY_STATE.csv
combined_YYYY.csv
```

Each state-specific combined CSV retains the three-column contract:
`MonthlyIncome`, `FederalMonthlyTax`, and `StateMonthlyTax`.
`combined_YYYY.csv` is a compatibility copy for `legacy_combined_alias` when
that state was part of the generation run.

Table lookup chooses the nearest `MonthlyIncome` row. Federal lookup uses total
monthly income. State lookup uses allocated total monthly income, but cannot
distinguish earned from unearned income. Rules mode is authoritative when an
earned-only component is enabled.

## QIF structure

One QIF bundle has a single `!Type:Bank` header followed by:

1. one federal expense transaction;
2. one matching federal transfer;
3. one state expense; and
4. one matching state transfer for each selected state, in selection order.

Federal appears exactly once. Single-state exports use the legacy generic state
memo, preserving the established Georgia output. Multi-state exports add the
state code to state memos. State expense and transfer defaults are stored in
rules YAML and may be overridden by UI/config data.

## Runtime preferences

`taxkit.config` stores preferences in `~/.tax2/config.yaml`, or
`$TAX2_HOME/config.yaml`. The default shape is:

```yaml
default_states:
  - GA
legacy_combined_alias: GA
qif_overrides: {}
```

Missing config is created with defaults. Corrupt or unreadable config produces
a warning and in-memory defaults without overwriting the bad file. Runtime
config never contains tax rates or locality rules.

## Compatibility invariants

- Legacy rules files continue to load through normalization.
- Federal results depend on total income, not the earned/unearned split.
- A single-state Georgia QIF remains byte-compatible with the captured golden
  baseline.
- State allocations remain independent, including two states at 100%.
- State-specific combined CSVs retain their three-column schema.
- Jurisdiction-specific behavior remains in YAML rather than engine branches.

These invariants are covered by the golden, engine-component, rules, QIF, API,
CLI, and config tests under `tests/`.

## Known data constraints

- Pennsylvania rules exist for 2026 only.
- Pennsylvania local EIT is disabled by default. Its locality label and rate
  must be verified before enabling it.
- Georgia 2025 is retained as a historical fixture. Its standard deduction
  values mirror the federal 2025 values rather than Georgia's 2025 deduction;
  it remains unchanged to preserve the stored regression baseline.
- Checked-in rules and generated estimates are inputs to a personal utility,
  not a substitute for official tax guidance.
