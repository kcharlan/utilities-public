# Multi-State Expansion: Implementation Plan

> **Superseded:** The multi-state work shipped, and its bootstrap instructions are historical. Runtime dependencies now live in the `tax2` launcher's PEP 723 header.

Audience: a coding agent implementing this feature in the `tax2` project.
Authoritative design: `docs/multi_state_design.md` (rev 3, APPROVED). Read it fully before writing any code. Where this plan and the design doc conflict, the design doc wins; stop and ask the user if the conflict is material.
Also read: `README.md`, `docs/Usage.md`, and the repo root `CLAUDE.md` (test accountability rules are mandatory).

## 0. Hard Invariants (violating any of these is a failed implementation)

- I1. No file named `2025.yaml` is modified, and no 2025 table is regenerated. 2025 stays byte-identical on disk yet must still load through the new code path.
- I2. Federal computation results are numerically identical to the current code for any (total income, filing status, year). Federal ignores the earned/unearned split; it taxes the sum.
- I3. A single-state GA QIF export with the same inputs produces byte-identical output to the current `build_qif_entries`. Capture a golden snapshot from current code BEFORE refactoring (Phase 0).
- I4. Per-state allocation percentages are independent: each state 0 to 100, default 100, never normalized, never forced to sum to 100. GA=100 and PA=100 together must yield full tax for both.
- I5. Code never branches on specific component names or state codes ("local_eit", "GA", "PA" must not appear in engine/QIF/API logic except as data defaults or display fallbacks). Behavior comes from YAML fields (`applies_to`, `enabled`, `qif`), not names.
- I6. Per-state combined CSVs keep exactly the existing 3 columns: `MonthlyIncome, FederalMonthlyTax, StateMonthlyTax`. Legacy `combined_{year}.csv` continues to exist (alias for the configured default state).
- I7. All tests run and pass; every failure investigated and fixed; no category skipped (repo CLAUDE.md policy).

## 1. Phase 0: Baseline Capture (do this before touching any code)

1. Run the existing suite: `pytest` from `tax2/` (fall back to `python3 -m pytest`). Record results.
2. Write `tests/test_golden_baselines.py` against the CURRENT code and commit mentally to these values:
   - Federal tax for monthly incomes [0, 1000, 5000, 8333.33, 20000, 41666.67] x [single, married_joint] x years [2025, 2026], computed via `compute_tax`. Store expected values as literals in the test (generate them by running current code, then paste).
   - GA state tax for the same grid.
   - Full QIF output string for `build_qif_entries(date(2026, 9, 15), 2345.67, 512.34)` with default `QIFConfig`, stored as an exact multi-line literal.
3. These tests must pass before AND after every subsequent phase. They are the enforcement mechanism for I2 and I3.

## 2. Phase 1: Models and Rules Loader (`taxkit/models.py`, `taxkit/rules_loader.py`)

Schema target is Section 4.1/4.2 of the design doc. Concretely:

- Add `IncomeClass(str, Enum)` with members `earned`, `unearned`.
- Add `TaxComponent(BaseModel)`: `name: str`, `label: Optional[str]`, `enabled: bool = True`, `applies_to: List[IncomeClass] = [earned, unearned]`, `standard_deduction: Dict[FilingStatus, float]`, `brackets: Dict[FilingStatus, List[Bracket]]`.
- Add `QIFDefaults(BaseModel)`: `state_expense: Optional[str]`, `state_transfer: Optional[str]`.
- Extend `TaxRules`: add `display_name: Optional[str]`, `qif: Optional[QIFDefaults]`, `components: List[TaxComponent]`. Keep existing top-level `standard_deduction`/`brackets` fields OUT of the final model if feasible; prefer that the loader consumes them and emits components, so the engine sees only components. Choose the cleaner of: (a) loader-level normalization producing a components-only `TaxRules`, or (b) model validator. Either is acceptable; document the choice in a code comment.
- Loader normalization rule: if YAML has no `components` key, synthesize one component `{name: "default", enabled: true, applies_to: [earned, unearned]}` from top-level `standard_deduction` + `brackets`. If YAML has BOTH `components` and top-level bracket fields, raise a clear validation error (ambiguous file).
- `TaxInput`: fields become `earned_income: float = 0` and `unearned_income: float = 0` (both `ge=0`), plus a computed/derived `annual_income` property returning the sum. Search the codebase for every constructor call `TaxInput(annual_income=...)` and update call sites (tablegen, server compute, tests) to pass `unearned_income=` instead.

Tests (new `tests/test_rules_v2.py`):
- v1 GA 2025 and federal 2026 files load and normalize to exactly one enabled all-classes component with the original numbers.
- A v2 file (write a fixture inline via tmp_path) with two components, one disabled, parses correctly.
- Ambiguous file (both formats) raises.
- Golden baseline tests still pass.

## 3. Phase 2: Engine (`taxkit/engine.py`)

- `compute_tax(tax_in, rules)` becomes: for each component where `enabled`: applicable = sum of tax_in buckets named in `applies_to`; taxable = max(0, applicable - component.standard_deduction[fs]); tax += apply_brackets(taxable, component.brackets[fs]). Then apply existing jurisdiction-level credits logic to the summed tax, floor at 0. `apply_brackets` is unchanged.
- Signature stays `(TaxInput, TaxRules) -> float`.

Tests (new `tests/test_engine_components.py`):
- Earned-only component with earned=0, unearned=100000 yields 0 for that component.
- Two-component sum equals manual expectation (flat rates make this easy to hand-compute; use exact literals).
- Disabled component contributes nothing.
- Golden baselines still pass (federal and GA identical to Phase 0 values).

## 4. Phase 3: Rules Data (YAML files only)

- Create `rules/states/PA/2026.yaml` exactly per the design doc Section 4.1 example: flat 0.0307 both filing statuses, standard deduction 0, `display_name: Pennsylvania`, `qif` block with transfer `[PA State Income Taxes]`, and a `local_eit` component that is `enabled: false`, `applies_to: [earned]`, placeholder rate 0.01, with label "Local EIT (West York Boro / West York Area SD)".
- EIT rate verification: attempt to verify the 2026 resident EIT rate for West York Borough / West York Area School District via https://munstats.pa.gov/public/ or https://dced.pa.gov/local-government/local-income-tax-information/psd-codes-and-eit-rates/ or https://yatb.com. If verified, set the real rate and record the source and date in a YAML comment. If not verifiable, keep 0.01 and add a YAML comment: "PLACEHOLDER, verify before enabling". Do not enable the component either way.
- Edit `rules/states/GA/2026.yaml` only: add `display_name: Georgia` and a `qif` block (`state_expense: "Tax:State Income Tax Estimated Paid"`, `state_transfer: "[GA State Income Taxes]"`). Do not change any number. Do not touch `rules/states/GA/2025.yaml`.

Tests: loader loads PA 2026 (one enabled component, one disabled); GA 2026 exposes qif defaults; `get_available_years` on `rules/states/PA` returns `[2026]`.

## 5. Phase 4: QIF (`taxkit/qif.py`)

- New data shape: `StateQIFItem` dataclass: `code: str`, `amount: float`, `expense: str`, `transfer: str`, `label: Optional[str]` (display name for memos).
- `build_qif_entries(tx_date, federal_tax, states: list[StateQIFItem], cfg)` where `cfg` retains `payee`, `federal_expense`, `federal_transfer`. Emits one `!Type:Bank` header, then federal expense + federal transfer, then per state (in list order) expense + transfer.
- Byte-compat rule (I3): when `len(states) == 1`, memo lines use the current wording exactly ("Estimated State taxes - MM/DD/YYYY"). When `len(states) >= 2`, state memos become "Estimated {code} State taxes - MM/DD/YYYY". Keep the existing helper functions.
- Keep a thin backward-compatible wrapper or update all call sites; either way the golden QIF snapshot test must pass unchanged.

Tests (new `tests/test_qif_multistate.py`):
- Golden single-GA snapshot (from Phase 0) byte-identical.
- Fed + GA + PA export: exactly 6 transactions (36 lines after the single `!Type:Bank` header, each transaction being D/T/P/M/L/^), federal pair appears exactly once and first, state order preserved, expense amounts negative and transfer amounts positive, multi-state memo wording includes the state code.

## 6. Phase 5: Tables and CLI (`taxkit/tablegen.py`, `cli.py`)

- `generate_table`: update its internal `TaxInput` construction to `unearned_income=annual` (tables assume all income unearned, per design Section 4.7). Signature otherwise unchanged.
- `cli.py generate-combined`: replace `--state GA` with `--states "GA,PA"` (comma-separated, default read from config, fallback "GA"). Keep `--state` as a deprecated alias that maps to a single-item list and prints a deprecation warning. For each state: write `tables/{st.lower()}_{year}.parquet` and `tables/combined_{year}_{ST}.csv` (3-column format, I6). Write `tables/federal_{year}.parquet` once. After all states, copy the default state's combined CSV to `tables/combined_{year}.csv` (legacy alias; default state from config, see Phase 7).
- Year resolution: resolve against federal years as today, but if a requested state lacks that year's file, fail that state with a clear message listing available years for it (design doc Section 6 item 2) and continue with other states; nonzero exit if any state failed.

Tests (new `tests/test_cli_tables.py`, use `typer.testing.CliRunner` and tmp output dir):
- `--states GA,PA --year 2026` produces 5 files (federal parquet, 2 state parquets, 2 combined CSVs) plus legacy alias; column names exact.
- Legacy alias content equals the GA combined CSV (default state GA).
- `--states PA --year 2025` exits nonzero with a message naming PA and 2025.
- Value spot-check: PA combined CSV at MonthlyIncome=10000 has StateMonthlyTax == round(10000*12*0.0307/12, 2) == 307.00.

## 7. Phase 6: Config (`~/.tax2/config.yaml`)

- Add a small config module (suggest `taxkit/config.py`): `load_config()` returns dict with defaults `{default_states: ["GA"], legacy_combined_alias: "GA", qif_overrides: {}}`; `save_config(cfg)` writes YAML to `~/.tax2/config.yaml`. Create with defaults if missing. Never store tax rates here. Corrupt/unreadable file: log a warning, use defaults, do not crash, do not overwrite the corrupt file.
- Wire into: CLI default for `--states` and legacy alias choice; server default state selection; UI persistence (`POST /api/config` to update `default_states` when the user changes selection, plus `GET /api/config`).
- `requirements.txt` should not need changes (pyyaml present). If you do add a dependency, follow the bootstrap pattern in the `tax2` launcher: bump `BOOTSTRAP_VERSION` and verify the venv rebuild triggers.

Tests: config round-trip in tmp dir (monkeypatch home), defaults on missing file, warning + defaults on corrupt file.

## 8. Phase 7: API (in `tax2` launcher file)

Per design Section 4.4:

- `GET /api/states`: scan `rules/states/*/`, return `{"states": [{"code", "display_name", "years": [...]}]}`. display_name falls back to code. Sorted by code.
- `GET /api/config` / `POST /api/config`: expose `default_states` (validate against discovered states).
- `POST /api/compute` request model: `monthly_earned: float = 0`, `monthly_unearned: float = 0`, `filing_status`, `year`, `mode`, `states: List[StateSelection]` where `StateSelection = {code: str, allocation_pct: float = 100}` (validate 0 <= pct <= 100, at least one state, codes must exist). Remove `monthly_income`, `federal_rules`, `state_rules` request fields (SPA ships in the same file; no external API consumers).
- Compute: federal once on total (earned+unearned) annualized. Per state: build `TaxInput(earned_income=earned*12*pct/100, unearned_income=unearned*12*pct/100)`, compute with that state's rules. Table mode: per state, read `tables/combined_{year}_{ST}.csv`, falling back to `tables/combined_{year}.csv` only for the configured default state; nearest-income lookup as today (note: table mode ignores earned/unearned split; apply allocation_pct by scaling looked-up state tax, and document this approximation in a code comment).
- Response model: `federal_monthly`, `federal_annual`, `states: [{code, display_name, monthly, annual, allocation_pct}]`, `total_monthly`, `total_annual`, `effective_rate` (total tax / total entered income, guard div-by-zero as current code does).
- `POST /api/export/qif` request: `tx_date`, `federal_tax`, `payee`, `federal_expense`, `federal_transfer`, `states: [{code, amount, expense, transfer}]` (expense/transfer prefilled by UI from `/api/states` + rules qif defaults + config overrides). Calls the new `build_qif_entries`.

Tests (new `tests/test_api.py`, `fastapi.testclient.TestClient`; import the app from the launcher — check how `tests/test_bootstrap.py` imports it today and follow that pattern):
- `/api/states` lists GA and PA with years.
- Compute single GA: matches golden baseline numbers.
- Compute GA+PA both 100%: each state equals its single-state value (I4 enforcement test), total = fed + GA + PA.
- Compute GA 100% + PA 50%: PA equals half-income computation.
- Validation errors: empty states list, unknown code, pct out of range.

## 9. Phase 8: UI (embedded SPA inside the `tax2` launcher file)

Follow existing SPA conventions (React 18 + Babel standalone, embedded HTML string). Changes:

- Income inputs: replace single income field with "Monthly unearned income" (first/primary) and "Monthly earned income" (default 0); show computed total.
- State selection: checkbox list from `/api/states` (auto-discovered; no hardcoded GA/PA). At least one required (disable unchecking the last one, or show inline error). When 2+ checked, show an allocation % numeric input (0-100, default 100) beside each state. Inputs are independent (I4): changing one never modifies another, no sum warnings beyond an optional informational note.
- Recompute on any change (existing debounce/auto-recalc behavior).
- Results: keep federal card; render one state card per selected state titled with display_name and showing allocation pct when != 100; totals aggregate all.
- QIF panel: per selected state, editable expense/transfer fields prefilled from rules qif defaults (fetch via `/api/states` payload; include qif defaults in that response) merged with config overrides; single "Download QIF" button producing the bundled file.
- Persist selection: on state checkbox change, `POST /api/config` with the new `default_states`.
- Remove the hardcoded "State Tax (GA)" label and `[GA State Income Taxes]` literal from the JSX (defaults now flow from data).

Verification: Playwright is not set up in this project; do manual/scripted smoke: start `./tax2 --no-browser --port <free>`, then curl `/`, `/api/states`, `/api/compute` (1 and 2 states), `/api/export/qif`, assert 200s and expected JSON. Automate this as `tests/test_smoke_server.py` if the bootstrap import pattern allows launching the app in-process; otherwise provide a `scripts/smoke.sh` and run it.

## 10. Phase 9: Documentation

- README.md: project layout (PA dir), new CLI flag `--states`, per-state table naming + legacy alias, earned/unearned inputs, state checkboxes, allocation semantics (independent, both-at-100 valid), QIF bundle shape (2 + 2N), config file location and keys, component schema with `applies_to`/`enabled`/`label` and the "generic names, locality in data" rule.
- docs/Usage.md: update workflows; add PA notes: flat 3.07%, no standard deduction, qualified vs ordinary dividends identical for PA, ROC excluded until basis exhausted then entered as gain, local EIT disabled by default and how to enable it (edit `enabled` + rate in `rules/states/PA/2026.yaml`), and that table mode ignores the earned/unearned split.
- docs/multi_state_design.md: update Status line to IMPLEMENTED with date when done.

## 11. Phase 10: Final Verification (mandatory, in order)

1. Full test suite: `pytest` (or `python3 -m pytest`) from `tax2/`. Every test listed in this plan plus pre-existing tests. Report every result; fix every failure (repo CLAUDE.md rules apply verbatim).
2. `python3 cli.py generate-combined --year 2026 --states GA,PA` (via `~/.tax2/venv/bin/python` if system python lacks deps). Confirm outputs and that `combined_2026.csv` values for GA are identical to the pre-change file (git diff should show no value changes for the GA columns; row set identical).
3. `git diff --stat` review: confirm NO diff under any `2025.yaml`, no diff to `rules/states/GA/2025.yaml`, and no 2025 table files changed (I1).
4. Smoke-run `./tax2 --no-browser` and exercise the endpoints per Phase 8 verification.
5. Grep check for I5: `rg -n "local_eit|\"GA\"|'GA'|\"PA\"|'PA'" taxkit/` and justify every hit (data defaults, tests, and display fallbacks are fine; logic branches are not).

## 12. Explicit Don'ts

- Don't modify anything under `archive/`, `.tax2_venv/`, or `tables/*2025*`.
- Don't rename existing public functions without keeping call sites working; the launcher imports from `taxkit` lazily inside endpoints.
- Don't introduce Node tooling, build steps, or split the SPA into separate files (single-file launcher is intentional).
- Don't normalize, cap-sum, or link allocation percentages (I4).
- Don't put tax rates, brackets, or locality names into Python code or `~/.tax2/config.yaml`.
- Don't enable the `local_eit` component, regardless of what rate verification finds.
- Don't skip, defer, or hand-wave any failing test (repo CLAUDE.md, non-negotiable).

## 13. Suggested Commit/Phase Order

Phases 0 through 10 in order; each phase ends with the full test suite green, not just the new tests. Phases 1+2 may be one commit (schema + engine are coupled through TaxInput). Phase 8 (UI) is the largest single edit because the SPA is an embedded string; make targeted edits rather than regenerating the whole HTML template, and re-run the smoke check after.
