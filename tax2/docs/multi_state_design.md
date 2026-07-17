# Multi-State Expansion Design (GA + PA)

> **Superseded environment note:** The feature is implemented; references below to private venv/bootstrap state describe the pre-uv launcher and are historical.

Status: IMPLEMENTED 2026-07-04 (rev 3). Companion document: multi_state_implementation_plan.md.
Rev 3 changes: 2025 files and tables frozen per user decision; PA 2026 only; GA 2025 discrepancy documented but not fixed.
Date: 2026-07-04
Rev 2 changes: generic `local_eit` component name with display label; allocation percentages explicitly independent (both states at 100% is valid and tested); added Section 5 inventory of actual on-disk config vs proposed changes, including GA 2025 standard deduction discrepancy and ~/.tax2 migration items.

## 1. Goals

1. Support multiple states, initially GA and PA, selectable at runtime (checkboxes, one or more).
2. Handle the GA-to-PA relocation straddle: compute and export estimated taxes for both states in a single run, with per-state income allocation for split months.
3. Model PA correctly for the user's situation: flat 3.07% on all income classes (dividends qualified or not, option gains), no standard deduction, no local tax on unearned income.
4. Local tax (West York borough / West York Area SD EIT, applies to earned income only) must be addable or enable-able by configuration change only, never a code change.
5. Federal behavior unchanged: taxes total income as ordinary (deliberate overestimation, user preference).
6. Preserve backward compatibility where cheap: existing GA YAML files load unchanged; single-state GA QIF output stays byte-identical; per-state combined CSVs keep the existing 3-column format.

## 2. Non-Goals

- Federal preferential rates for qualified dividends / LTCG (explicitly declined; overestimation preferred).
- ROC basis tracking. The user excludes ROC from entered income until basis is exhausted, then includes it as gain. Document this in Usage.md.
- Residency timeline automation / date-based allocation. The user runs the tool monthly and enters income; per-state allocation percentages cover split months.
- PA Tax Forgiveness (Schedule SP), PA estimated-payment threshold logic, county property taxes, LST. Out of scope for the calculator; note in docs only.

## 3. Verified Tax Facts (sources at bottom)

| Fact | Value | Design consequence |
|---|---|---|
| PA PIT rate (2026) | Flat 3.07%, all 8 income classes | Single bracket, rate 0.0307 |
| PA standard deduction | None | standard_deduction: 0 |
| PA qualified vs ordinary dividends | No distinction | Unearned bucket needs no further split for state |
| PA local EIT | Earned income only; unearned exempt | `applies_to: [earned]` on the local component |
| West York EIT rate | ~1% combined borough + school district; EXACT RATE MUST BE VERIFIED at implementation via DCED PSD lookup or YATB | Ships disabled with placeholder rate and a comment |
| GA 2026 rate | Flat 5.09% (already in rules/states/GA/2026.yaml) | Unchanged |
| Part-year residency | Each state taxes income received while resident there | Per-state allocation % on inputs |

## 4. Design

### 4.1 Rules schema v2: components with income-class scoping

A jurisdiction YAML may now contain a `components` list. Each component is an independently computed tax layered under the same jurisdiction. Total state tax = sum of enabled components, minus jurisdiction-level credits (floor 0).

```yaml
# rules/states/PA/2026.yaml
year: 2026
jurisdiction: PA
display_name: Pennsylvania
filing_statuses: [single, married_joint]
components:
  - name: state_income_tax
    enabled: true
    applies_to: [earned, unearned]     # default if omitted
    standard_deduction: { single: 0, married_joint: 0 }
    brackets:
      single:        [ { up_to: null, rate: 0.0307 } ]
      married_joint: [ { up_to: null, rate: 0.0307 } ]
  - name: local_eit                    # generic name; NEVER encode a locality in the component name
    label: "Local EIT (West York Boro / West York Area SD)"   # display-only data; edit freely on any move
    enabled: false                     # config-only enable, per requirement
    applies_to: [earned]               # unearned income exempt at local level
    standard_deduction: { single: 0, married_joint: 0 }
    brackets:
      single:        [ { up_to: null, rate: 0.01 } ]   # PLACEHOLDER, verify via dced.pa.gov PSD/EIT lookup
      married_joint: [ { up_to: null, rate: 0.01 } ]
credits: []
qif:
  state_expense: "Tax:State Income Tax Estimated Paid"
  state_transfer: "[PA State Income Taxes]"
```

Backward compatibility: a YAML **without** `components` (current federal and GA files) is normalized at load time into a single implicit component `{name: default, enabled: true, applies_to: [earned, unearned]}` using its top-level standard_deduction/brackets. No edits to existing GA/federal files required. `display_name` and `qif` blocks are optional; GA gets a `qif` block added so its transfer default `[GA State Income Taxes]` moves out of code and into rules.

Component names are generic engine identifiers (`state_income_tax`, `local_eit`); locality specifics (which borough, which school district, the rate) live only in the `label` and bracket data. Moving to a different PA locality means editing the label and rate, nothing else. If the user's EIT understanding turns out wrong (for example locality taxes unearned income), the fix is editing `applies_to` in YAML. If a new tax appears, add a component. All are configuration changes only. Code must never reference component names other than for display.

### 4.2 Models (`taxkit/models.py`)

- `IncomeClass = Enum("earned", "unearned")`.
- `TaxComponent`: name, enabled, applies_to, standard_deduction, brackets.
- `TaxRules`: gains `components: List[TaxComponent]`, `display_name: Optional[str]`, `qif: Optional[QIFDefaults]`. Loader performs the v1-to-v2 normalization so the engine only ever sees components.
- `TaxInput`: replace `annual_income` with `earned_income` + `unearned_income` (both annual, ge=0). Keep an `annual_income` computed property returning the sum so existing call sites and federal computation read naturally. Loader/engine treat federal as an all-classes jurisdiction, so federal math on total income is unchanged.

### 4.3 Engine (`taxkit/engine.py`)

For each enabled component: applicable income = sum of the input buckets named in `applies_to`; taxable = max(0, applicable − standard_deduction[fs]); tax = apply_brackets(taxable, brackets[fs]). Sum components, apply jurisdiction credits, floor at 0. `apply_brackets` unchanged. Federal result for a given total income must be bit-identical to today (regression test).

### 4.4 API

- `GET /api/states` (new): scans `rules/states/*/`, returns `[{code, display_name, years}]`. UI builds checkboxes from this; adding a state directory adds a checkbox with zero code changes.
- `POST /api/compute` request: `monthly_earned`, `monthly_unearned`, `filing_status`, `year`, `mode`, and `states: [{code, allocation_pct}]` (allocation_pct defaults 100). Federal always computed once on 100% of total income.
- Response: `federal_monthly/annual`, `states: [{code, display_name, monthly, annual, allocation_pct}]`, `total_monthly/annual`, `effective_rate`. The old flat `state_monthly` fields are dropped; the SPA ships in the same file so API and UI change atomically.
- Semantics of allocation: state tax is computed on (allocated income), not prorated from full-income tax. With flat-rate states these are equal; with bracketed states computing on allocated income matches the "income received while resident" rule better.
- Allocation percentages are INDEPENDENT per state, range 0 to 100, default 100. They are deliberately NOT normalized and do not need to sum to 100. Setting GA=100 and PA=100 simultaneously is valid and is the user's stated safety posture during the relocation straddle (pay full estimated tax to both states, reconcile via refunds at filing). The UI must not link the sliders/inputs, must not warn on overlap beyond an informational note, and a regression test must assert that two states at 100% each produce full tax for both.

### 4.5 UI (embedded SPA in `tax2`)

- Income section: two fields, "Monthly unearned income" (primary for this user) and "Monthly earned income" (defaults 0). Total shown.
- States section: checkboxes from `/api/states` (GA, PA), at least one required. When 2+ are checked, an allocation % input appears next to each (default 100). Selecting/deselecting recalculates automatically (existing recompute-on-change behavior), which satisfies the "enter once, flip state, auto recalc" workflow.
- Results: federal card unchanged; one state card per selected state labeled with display_name (replaces hardcoded "State Tax (GA)"); totals sum federal + all selected states.
- Default selections persisted (see 4.8) so post-move the tool opens with PA only.

### 4.6 QIF (`taxkit/qif.py`)

- `build_qif_entries(tx_date, federal_tax, states: List[StateQIFItem], cfg)` where each item carries code, amount, expense category, transfer account (defaults from the state YAML `qif` block, overridable in UI).
- Output: one `!Type:Bank` block with 2 federal transactions + 2 per state, in state selection order. Federal appears exactly once regardless of state count, which resolves the duplicate-federal concern from per-state runs.
- Memo lines gain the state code for state entries ("Estimated PA State taxes - MM/DD/YYYY") ONLY for multi-state exports; a single-state GA export must remain byte-identical to current output (snapshot test enforces this). If byte-compat and clearer memos conflict, byte-compat wins for the single-GA case.

### 4.7 Tables and CLI

- `generate-combined --year 2026 --states GA,PA` (comma list; default from config). Outputs per state: `tables/{st}_{year}.parquet` and `tables/combined_{year}_{ST}.csv` with the existing columns `MonthlyIncome, FederalMonthlyTax, StateMonthlyTax`. `federal_{year}.parquet` written once.
- Legacy `tables/combined_{year}.csv` continues to be written as a copy for the configured default state, so existing consumers keep working. Removable later.
- Table generation sweeps assume all income is unearned (matches the user's situation and keeps tables 2-D). Documented limitation: tables ignore earned/unearned split and any earned-only local components; rules mode is authoritative when EIT is enabled.
- Table lookup mode in UI: per selected state, load `combined_{year}_{ST}.csv`, falling back to legacy `combined_{year}.csv` for the default state.

### 4.8 Config (runtime home, `~/.tax2/config.yaml`)

New small config file, created with defaults on first run: `default_states: [GA]` (user flips to `[PA]` after the move), `legacy_combined_alias: GA`, per-state QIF account overrides. UI writes back default state selection. Keeps all mutable preference state out of the repo, per the runtime-home pattern.

### 4.9 Testing (per repo test policy)

- Engine: component scoping (earned-only component ignores unearned income), v1 YAML normalization, federal regression (identical results pre/post change for same total income), GA regression, PA flat-tax cases including zero standard deduction.
- QIF: byte-compat snapshot for single-state GA; structural tests for fed+GA+PA bundle (6 transactions, single federal pair).
- Tablegen/CLI: per-state outputs exist, column names unchanged, legacy alias written.
- API: /api/states discovery, compute with 1 and 2 states, allocation math.
- Smoke-run `./tax2` after UI changes; run `python3 cli.py generate-combined --year 2026 --states GA,PA`.

## 5. Current System Inventory vs Proposed Changes

Verified on the user's machine 2026-07-04.

### 5.1 Runtime home `~/.tax2/`

Contains only `venv/` and `bootstrap_state.json` (`bootstrap_version: 2`, `python_version: 3.14.6`, requirements hash). No tax data, no user config exists there today. Consequences for implementation:

- `~/.tax2/config.yaml` is NEW; the implementation must create it with defaults on first run after upgrade (`default_states: [GA]`, `legacy_combined_alias: GA`) without disturbing venv or bootstrap state.
- No new Python dependencies are anticipated (pyyaml, pandas, fastapi already installed), so `BOOTSTRAP_VERSION` stays at 2 unless requirements.txt changes; if it does change, bump it per the repo bootstrap pattern.

### 5.2 Repo rules files (all tax data lives in the repo, none in ~/.tax2)

| File | Current content | Proposed change |
|---|---|---|
| rules/federal/2025.yaml | Std ded 15750/31500; 7 brackets 10-37% | None (numbers untouched; loader normalizes v1 format) |
| rules/federal/2026.yaml | Std ded 16100/32200; 7 brackets 10-37% | None |
| rules/states/GA/2025.yaml | Flat 5.19%; std ded 15750/31500 | NONE. User decision 2026-07-04: 2025 files are frozen (see discrepancy note below) |
| rules/states/GA/2026.yaml | Flat 5.09%; std ded 12000/24000 | Add `display_name` + `qif` block (transfer `[GA State Income Taxes]` moves from code to YAML); numbers untouched |
| rules/states/PA/2026.yaml | Does not exist | NEW: flat 3.07%, std ded 0, disabled `local_eit` component (see Section 4.1 example). No PA 2025 file; scope is 2026 onward |
| tables/*.parquet, combined_2026.csv | GA-only outputs | Regenerate 2026 only per Section 4.7 after rules changes; 2025 tables untouched |

**GA 2025 discrepancy (noted, deliberately NOT fixed):** GA/2025.yaml uses standard deduction 15750/31500, which are the FEDERAL 2025 values; Georgia's actual 2025 standard deduction was 12000/24000. User decision 2026-07-04: leave all 2025 files and tables exactly as they are. Scope of this project is tax year 2026 onward. Implementation must not modify any `2025.yaml` or regenerate any 2025 table. The v1-format 2025 files must still LOAD correctly through the new normalizing loader (regression test), they just stay byte-identical on disk.

### 5.3 Migration items to carry into the implementation plan

1. Add `display_name` and `qif` blocks to rules/states/GA/2026.yaml only. Do not touch 2025 files.
2. Create rules/states/PA/2026.yaml with generic `local_eit` component (disabled, placeholder rate pending DCED/YATB verification).
3. First-run creation of `~/.tax2/config.yaml`; never store tax rates there, only preferences.
4. Regenerate 2026 tables with `--states GA,PA` and verify the legacy alias `combined_2026.csv` matches prior GA values (GA 2026 numbers are unchanged, so it must be value-identical).
5. Update README.md and docs/Usage.md for the new schema, state selector, allocation semantics, and ROC handling note.

## 6. Decisions Taken as Defaults (flagging, not silently baked in)

1. West York EIT placeholder rate 1.00% and disabled by default. Exact combined rate and PSD code must be verified against dced.pa.gov / yatb.com during implementation and recorded in a YAML comment.
2. PA gets a 2026 rules file only. Year fallback logic (resolve_year) already handles a state having fewer years than federal; selecting year 2025 with PA checked must surface a clear "no PA rules for 2025" error rather than a crash.
3. Allocation is a percentage of entered income per state, not date-based. Split-month math (how much income was received while GA resident) stays the user's responsibility.
4. Credits remain jurisdiction-level (not per-component). No known GA/PA credit needs component scoping.
5. PA estimated-payment mechanics (REV-413I thresholds, due dates) are documented in Usage.md but not enforced by the tool, same as today for GA.

## 7. Sources

- PA flat 3.07% and income classes: https://www.pa.gov/agencies/revenue/resources/tax-types-and-information/personal-income-tax and https://www.pa.gov/agencies/revenue/resources/tax-rates
- PA dividends / ROC basis treatment: https://www.pa.gov/agencies/revenue/forms-and-publications/pa-personal-income-tax-guide/dividends
- Local EIT earned-income-only, rate lookup: https://dced.pa.gov/local-government/local-income-tax-information/psd-codes-and-eit-rates/ and https://www.yatb.com/for-individuals/earned-income-tax/
- Part-year residency (income received while resident): https://www.pa.gov/agencies/revenue/resources/tax-types-and-information/personal-income-tax/nonresidents-and-part-year-residents and https://dor.georgia.gov/filing-residents-nonresidents-and-part-year-residents-faq
