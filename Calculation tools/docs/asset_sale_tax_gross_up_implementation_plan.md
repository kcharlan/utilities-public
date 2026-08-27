# Asset-Sale Tax Gross-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a separately configurable 15%-default effective tax rate on asset sales and gross up each liquidation so its net proceeds fund the cash-buffer shortfall.

**Architecture:** Keep `drawdown.html` as the project’s self-contained browser application. Isolate the precision-sensitive sale calculation and CSV serialization behind small pure functions, then integrate their outputs into the existing monthly simulation, pin, aggregation, rendering, and export paths. Tests load the inline script through the project’s existing dependency-free `node:test`/`vm` pattern without adding production-only test hooks.

**Tech Stack:** HTML5, browser JavaScript, Node.js built-in `node:test`, `node:assert/strict`, and `node:vm`; no third-party packages or build step.

**Approved design:** `docs/superpowers/specs/2026-08-27-asset-sale-tax-gross-up-design.md`

---

## Execution Constraints

- Work only in `Calculation tools`; preserve the single-file architecture and do not add dependencies.
- Read `README.md` and the approved design before editing.
- Treat every test failure as blocking. Diagnose and fix it before continuing; never weaken an assertion or omit a test category.
- Run the complete project suite, `node --test tests/*.test.js`, before every implementation commit and at final handoff.
- Do not run Python for any step. The project needs only Node and direct browser loading.
- Use conspicuously synthetic values in tests, screenshots, downloads, logs, and documentation. Do not place private financial data or realistic account details in this public repository.
- Preserve unrelated working-tree changes. Stage only the files named by the current task.
- Before every commit, inspect `git diff --cached --name-only`, `git diff --cached --check`, and the full `git diff --cached`. Stop if any staged content could be sensitive.

## Current File Map

- `drawdown.html:951-1005` — base inputs, including the current recurring-income tax field.
- `drawdown.html:1088-1097` — on-page calculation methodology.
- `drawdown.html:1111-1137` — pin parameter definitions and default state.
- `drawdown.html:1149-1299` — monthly simulation and current dollar-for-dollar sale branch.
- `drawdown.html:1301-1326` — pre-state and effective-state snapshots used by pins.
- `drawdown.html:1374-1423` — deterministic pin ordering and yearly aggregation.
- `drawdown.html:1429-1474` — summary statistics.
- `drawdown.html:1566-1677` — table rendering and the current `Sold` column.
- `drawdown.html:1679-1848` — pin editor, bounds, dirty tracking, and override persistence.
- `drawdown.html:1986-2014` — base input parsing and recalculation.
- `drawdown.html:2020-2062` — CSV construction and browser download side effects.
- `drawdown.html:2068-2126` — input listeners and initialization.
- `tests/drawdown_dates.test.js` — existing inline-script extraction and `vm` test pattern.
- `README.md:1-22,66-75` — calculator behavior, usage, validation, and planning disclaimer.
- `docs/superpowers/specs/2026-08-27-asset-sale-tax-gross-up-design.md` — binding behavior, invariants, and non-goals.

## Planned File Changes

- **Modify:** `drawdown.html` — calculation helper, simulation integration, state and pins, tax inputs, rendering, validation, CSV builder, and methodology text.
- **Create:** `tests/drawdown_sales.test.js` — helper, simulation, pin, validation, aggregation, rendering, and CSV regressions.
- **Modify:** `README.md` — explain the two tax rates, gross-up behavior, CSV additions, and simplified-tax limitation.
- **Do not modify:** `tests/drawdown_dates.test.js` unless the shared inline-script test setup cannot remain duplicated cleanly. Prefer a small local harness in the new test file over an unrelated test refactor.

## Test Harness Contract

`tests/drawdown_sales.test.js` should read the first inline `<script>` exactly as `drawdown_dates.test.js` does. Each `loadDrawdownApi()` call must create a fresh `vm` context with `document.addEventListener()` stubbed so `init()` is registered but never invoked. Append a lexical export to the evaluated source rather than adding browser globals to production code.

Use conditional exports while developing incrementally so a missing future function produces a focused assertion failure instead of aborting module setup:

```js
globalThis.__drawdownApi = {
  state,
  PARAM_DEFS,
  simulate,
  aggregateForView,
  renderStats,
  calculateAssetSale: typeof calculateAssetSale === 'function' ? calculateAssetSale : undefined,
  normalizeTaxPercent: typeof normalizeTaxPercent === 'function' ? normalizeTaxPercent : undefined,
  readNormalizedTaxRate: typeof readNormalizedTaxRate === 'function' ? readNormalizedTaxRate : undefined,
  readPinFieldValue: typeof readPinFieldValue === 'function' ? readPinFieldValue : undefined,
  collectPinOverrides: typeof collectPinOverrides === 'function' ? collectPinOverrides : undefined,
  buildCsvText: typeof buildCsvText === 'function' ? buildCsvText : undefined,
};
```

Return the context as well as `__drawdownApi` when a test must replace a DOM stub for `renderStats()`. Never invoke the registered `DOMContentLoaded` handler from this test file.

Values created inside `vm` have different realm prototypes. Compare primitive fields individually or normalize result objects with `JSON.parse(JSON.stringify(value))` before `assert.deepEqual`; do not mistake a prototype mismatch for a calculation failure. Define one local `assertClose(actual, expected, tolerance = 1e-9)` helper for repeating-decimal amounts, while retaining exact assertions for deliberately exact net proceeds, zero unfunded deficit, and ending-floor equality.

Prefix test names by slice so every targeted red/green command is guaranteed to select tests:

```text
[helper] calculateAssetSale ...
[simulation] ...
[ui] tax control ... / [ui] normalization ... / [ui] pin field ...
[reporting] aggregate ... / [reporting] summary ... / [reporting] Gross sold ...
[csv] CSV ...
[docs] methodology ...
```

After every `--test-name-pattern` run, inspect the reported test count and confirm at least one matching test actually ran. A zero-match or all-skipped run does not establish either red or green status.

## Task 1: Implement the Pure Asset-Sale Calculation

**Files:**

- Create: `tests/drawdown_sales.test.js`
- Modify: `drawdown.html:1144-1149` — place the pure helper immediately before `simulate()`.

- [ ] **Step 1: Establish the clean baseline.**

  Run:

  ```bash
  git status --short
  node --test tests/*.test.js
  ```

  Expected: the working tree contains no unexpected changes; the current two date tests pass with zero failures. If any test fails, report every failure and diagnose it before editing.

- [ ] **Step 2: Create the isolated inline-script harness and failing helper tests.**

  Implement the harness contract above. Add named tests for:

  - `[helper] calculateAssetSale handles zero deficit and zero available investments`;
  - `[helper] calculateAssetSale applies zero tax to a $1,000 deficit`;
  - `[helper] calculateAssetSale grosses up a $1,000 deficit at 15%`;
  - `[helper] calculateAssetSale exhausts insufficient principal at 15%`;
  - `[helper] calculateAssetSale stays finite at 100%`;
  - `[helper] calculateAssetSale avoids overflow immediately below 100%`, using a rate and balance for which maximum net proceeds cannot cover the deficit.

  Assert the complete returned object and these invariants: gross equals tax plus net, gross never exceeds available investments, net never exceeds the deficit, and every result field is finite.

- [ ] **Step 3: Run the helper tests and confirm the red state.**

  Run:

  ```bash
  node --test --test-name-pattern="calculateAssetSale" tests/drawdown_sales.test.js
  ```

  Expected: FAIL because `calculateAssetSale` is not yet defined. Confirm the failure is the missing behavior, not a broken `vm` harness.

- [ ] **Step 4: Add `calculateAssetSale(deficit, availableInvestments, saleTaxRate)`.**

  The caller contract is finite, nonnegative `deficit` and `availableInvestments`, with `saleTaxRate` normalized to `0..1`. Implement the approved branches exactly:

  ```text
  no deficit or no investments -> no sale; unfunded deficit remains
  rate >= 1 -> sell all; sale tax equals gross; net is zero
  otherwise:
      net fraction = 1 - rate
      maximum net proceeds = available investments * net fraction
      if maximum net proceeds >= deficit:
          gross = deficit / net fraction
          net = deficit exactly
          tax = gross - net
          unfunded = 0 exactly
      else:
          gross = all available investments
          net = gross * net fraction
          tax = gross - net
          unfunded = max(0, deficit - net)
  ```

  Return `{ grossSold, saleTaxPaid, netSaleProceeds, unfundedDeficit }`. Do not round internal values. Test maximum net capacity before division so rates extremely close to 100% cannot overflow the gross-up.

- [ ] **Step 5: Verify helper behavior and the complete suite.**

  Run:

  ```bash
  node --test tests/drawdown_sales.test.js
  node --test tests/*.test.js
  ```

  Expected: all helper and date tests pass with zero failures, skips, cancellations, or todos.

- [ ] **Step 6: Perform the staged public-repository safety gate and commit.**

  Stage only `drawdown.html` and `tests/drawdown_sales.test.js`, inspect the staged file list and full diff, and run `git diff --cached --check`. Confirm all amounts are obviously synthetic and no sensitive data is present. Commit:

  ```bash
  git commit -m "Add asset-sale tax gross-up calculation"
  ```

## Task 2: Integrate Sale Tax into Monthly Simulation and Pins

**Files:**

- Modify: `tests/drawdown_sales.test.js`
- Modify: `drawdown.html:1111-1326`

- [ ] **Step 1: Add failing simulation tests using fresh state per test.**

  Add focused cases with explicit `Object.assign(state.params, ...)` setup and `state.pins = []` so no test relies on production defaults except the dedicated default test:

  - `state.params.sale_tax_rate` defaults to `0.15`.
  - A one-month scenario with starting buffer `$0`, floor `$100`, expense `$100`, no income, `$1,000` investments, and 15% sale tax has a pre-sale deficit of `$200`, sells about `$235.2941176471`, records about `$35.2941176471` sale tax, deposits exactly `$200`, ends at the `$100` floor, and leaves about `$764.7058823529` invested.
  - A combined-tax scenario with starting buffer `$0`, floor `$100`, external income `$100`, investment income `$0`, income tax 25%, expense `$175`, `$1,000` investments, and sale tax 15% produces `net_income = $75`, `delta = -$100`, a `$200` pre-sale deficit, `income_tax_paid = $25`, sale tax about `$35.2941176471`, and combined tax about `$60.2941176471`. The recurring `net_income` and `delta` exclude sale activity.
  - A no-shortfall scenario with starting buffer equal to floor and recurring net income equal to expense stores zero sale, zero sale tax, and zero net sale proceeds.
  - An insufficient-assets scenario with starting buffer `$0`, floor `$100`, expense `$100`, no income, `$100` investments, and 15% sale tax sells all `$100`, records `$15` tax and `$85` net proceeds, ends at `-$15`, sets `insolvency`, and terminates as `depleted`.
  - The same deficit scenario at 100% stores only finite numbers, sells all available principal, records sale tax equal to gross, deposits zero, and is insolvent.
  - For income decay, use starting buffer/floor `$100`, expense `$200`, investment income `$100`, no other income or tax, `$1,000` principal, 15% sale tax, and modifier `1`. Month one has a `$100` deficit and gross sale about `$117.6470588235`; month-two investment income is about `$88.2352941176`, reflecting gross-sale decay.
  - For pin timing, use starting buffer/floor `$100`, expense `$200`, investment income `$100`, income tax `0`, modifier `0`, `$5,000` principal, base sale tax `0`, three months, and a month-two `sale_tax_rate: 0.25` pin. Month one sells `$100`; months two and three each sell about `$133.3333333333`. At month two, `pre_state.sale_tax_rate` remains the pre-pin baseline `0`, `effective_state.sale_tax_rate` is `0.25`, and month-three `pre_state.sale_tax_rate` is `0.25`.

- [ ] **Step 2: Run only the simulation-oriented tests and confirm the red state.**

  Run:

  ```bash
  node --test --test-name-pattern="simulation|combined tax|income decay|pinned sale tax" tests/drawdown_sales.test.js
  ```

  Expected: FAIL because sale-tax state, row fields, and tax-aware simulation integration do not exist.

- [ ] **Step 3: Extend state and prospective pin application.**

  In `state.params`, add `sale_tax_rate: 0.15`. Initialize `sim.current_sale_tax` from it. When a pin contains `sale_tax_rate`, apply it before computing that month. Include the effective value in both `snapshotPreState()` and `snapshotEffectiveState()`.

  Preserve the current epoch-reset rules: changing sale tax alone must not reset `baseline_principal`, `baseline_income`, or `cumulative_reduction`.

- [ ] **Step 4: Replace the sale branch with the helper result.**

  Keep the established monthly ordering: recurring income tax, expense and `delta`, buffer update, then asset sale. Rename the recurring tax local to `income_tax_paid`. Initialize `sold`, `sale_tax_paid`, and `net_sale_proceeds` to zero before the sale branch.

  When `sim.buffer < sim.current_floor && sim.investments > 0`:

  - set `hitFloor = true`;
  - calculate `deficit = floor - buffer`;
  - call `calculateAssetSale(deficit, sim.investments, sim.current_sale_tax)`;
  - subtract `grossSold` from investments;
  - add only `netSaleProceeds` to the buffer;
  - use `grossSold / baseline_principal` for cumulative income reduction;
  - set insolvency from `unfundedDeficit > 0`.

  Preserve the no-investments branch: a below-floor buffer with no investments is insolvent but does not set `hitFloor` or record a sale.

- [ ] **Step 5: Store the expanded row contract.**

  Each monthly row must contain:

  ```text
  income_tax_paid    recurring investment + external income tax
  sale_tax_paid      tax withheld from gross liquidation
  tax_paid           income_tax_paid + sale_tax_paid
  sold               grossSold
  net_sale_proceeds  cash deposited from the sale
  ```

  Keep `net_income` and `delta` unchanged. Do not add sale tax to expenses and do not add net sale proceeds to recurring `net_income`.

- [ ] **Step 6: Verify targeted behavior and the complete suite.**

  Run:

  ```bash
  node --test tests/drawdown_sales.test.js
  node --test tests/*.test.js
  ```

  Expected: all helper, simulation, pin, decay, depletion, and date tests pass. Inspect failure output in full if any assertion fails.

- [ ] **Step 7: Perform the staged safety gate and commit.**

  Stage only the two task files, inspect the staged file list and full diff for sensitive data, and run the staged whitespace check. Commit:

  ```bash
  git commit -m "Apply tax-aware asset sales in drawdown simulation"
  ```

## Task 3: Add Tax Controls and Normalize Base and Pinned Rates

**Files:**

- Modify: `tests/drawdown_sales.test.js`
- Modify: `drawdown.html:999-1005,1111-1137,1679-1848,1986-1999,2068-2081`

- [ ] **Step 1: Add failing UI and normalization tests.**

  Cover:

  - the existing base field is labeled **Income effective rate**, defaults to 25, and says it applies to recurring income;
  - a new `sale-tax-rate` number input is labeled **Asset sale effective rate**, defaults to 15, has `step="0.5"`, `min="0"`, `max="100"`, and says it applies to gross sale proceeds;
  - `sale-tax-rate` appears in the debounced input list;
  - `PARAM_DEFS` includes `sale_tax_rate` directly after `tax_rate`, formatted as a percentage with stored bounds `0..1`;
  - `normalizeTaxPercent(rawValue, fallbackPercent)` returns a displayed percentage in `0..100`, clamping finite out-of-range values and using the fallback for blank or non-finite input;
  - `readNormalizedTaxRate(input, fallbackRate)` reflects the normalized displayed percentage into a fake `{ value }` input and returns the decimal rate;
  - `readPinFieldValue(input, key, fmt, baseline)` uses the pinned month’s baseline for blank/non-finite `tax_rate` or `sale_tax_rate`, while preserving existing parsing for inflation, money, and numeric fields.
  - `collectPinOverrides(fieldInputs, dirtyKeys)` returns only normalized dirty values that differ from their field baselines; a blank dirty sale-tax input normalizes to its baseline and produces no override.

  Model fake pin inputs with the same minimal interface production uses: `getAttribute('data-key')`, mutable `.value`, and `closest('.pin-editor-field').getAttribute('data-fmt' | 'data-baseline')`. Pass a real `Set` for `dirtyKeys`. Include one changed valid tax value that is retained and one blank dirty tax value that is pruned, proving the collector distinguishes normalization from untouched-field filtering.

- [ ] **Step 2: Run the new tests and verify the expected failures.**

  Run:

  ```bash
  node --test --test-name-pattern="tax control|normaliz|pin field" tests/drawdown_sales.test.js
  ```

  Expected: FAIL because the new HTML input and normalization helpers are absent.

- [ ] **Step 3: Add exact tax constants and base controls.**

  Define reusable decimal defaults before `state`:

  ```js
  const DEFAULT_INCOME_TAX_RATE = 0.25;
  const DEFAULT_SALE_TAX_RATE = 0.15;
  ```

  Use them in `state.params`. Update the Tax group labels/hints and add the new base input with the approved attributes. Do not change the existing income-tax default.

- [ ] **Step 4: Add bounded percentage metadata for pins.**

  Extend percentage parameter definitions with stored-unit bounds:

  - `inflation`: `min: -1`, `max: 10`, preserving the current displayed `-100..1000` range;
  - `tax_rate`: `min: 0`, `max: 1`;
  - `sale_tax_rate`: `min: 0`, `max: 1`, positioned immediately after `tax_rate`.

  Update `renderPinEditor()` to derive displayed percentage `min`/`max` attributes from parameter metadata. Leave money and modifier input behavior unchanged.

- [ ] **Step 5: Implement shared tax normalization.**

  Use these exact interfaces:

  ```text
  normalizeTaxPercent(rawValue, fallbackPercent) -> finite percent in [0, 100]
  readNormalizedTaxRate(input, fallbackRate) -> decimal rate in [0, 1]
  readPinFieldValue(input, key, fmt, baseline) -> stored-unit value
  collectPinOverrides(fieldInputs, dirtyKeys) -> override object
  ```

  `normalizeTaxPercent` must treat `null`, `undefined`, an empty/whitespace string, and non-finite numeric text as invalid. `readNormalizedTaxRate` passes `fallbackRate * 100`, writes the normalized percent back to `input.value`, and divides by 100. `readPinFieldValue` delegates the two tax keys to `readNormalizedTaxRate(input, baseline)` so blank pin fields revert to their effective baseline and are pruned by the existing `floatsEqual()` comparison.

  `collectPinOverrides` owns the current `data-key`, `data-fmt`, and `data-baseline` traversal, calls `readPinFieldValue`, compares with `floatsEqual`, and returns a plain override object without modifying `state` or rerendering. This lets tests prove that normalization is actually on the persistence path. Do not apply tax clamping to inflation.

- [ ] **Step 6: Wire normalization into base and pin saves.**

  In `readParams()`, read both tax inputs through `readNormalizedTaxRate()` with their documented constants. Add `sale-tax-rate` to the debounced input list.

  In `savePinFromEditor()`, replace the inline collection loop with `collectPinOverrides(document.querySelectorAll('.pin-field-input'), dirty)`. Persist the returned object using the existing remove-old-pin/add-nonempty-pin flow. Leave untouched-field, reset, close, and rerender behavior intact.

- [ ] **Step 7: Verify targeted behavior and the complete suite.**

  Run:

  ```bash
  node --test tests/drawdown_sales.test.js
  node --test tests/*.test.js
  ```

  Expected: all tax-control, normalization, pin, simulation, helper, and date tests pass with no skipped or deferred cases.

- [ ] **Step 8: Perform the staged safety gate and commit.**

  Stage only `drawdown.html` and `tests/drawdown_sales.test.js`, inspect the complete staged diff and file list, run `git diff --cached --check`, and commit:

  ```bash
  git commit -m "Add asset-sale tax controls and validation"
  ```

## Task 4: Aggregate and Render Gross Sales and Tax Breakdowns

**Files:**

- Modify: `tests/drawdown_sales.test.js`
- Modify: `drawdown.html:1066-1080,1384-1423,1429-1474,1580-1638`

- [ ] **Step 1: Add failing aggregation and rendering tests.**

  Add tests that:

  - aggregate 12 synthetic monthly rows and assert exact sums for `income_tax_paid`, `sale_tax_paid`, `tax_paid`, `sold`, and `net_sale_proceeds`;
  - call `renderStats()` with a fake `#stats` element and rows whose gross sales do not equal `investments_initial - ending investments`, proving **Total liquidated** uses the row sum;
  - assert the tax summary headline uses combined tax and its detail contains both income-tax and asset-sale-tax dollar components;
  - assert the total-liquidated detail says **gross sales across projection** and no longer emits the initial-principal percentage;
  - assert the table header is **Gross sold** while row rendering continues to use `r.sold`.

  For the render test, set `context.document.getElementById` to return a capture object only for `stats`; call `renderStats(rows, result)` without invoking full initialization.

- [ ] **Step 2: Run the reporting tests and verify the red state.**

  Run:

  ```bash
  node --test --test-name-pattern="aggregate|summary|Gross sold" tests/drawdown_sales.test.js
  ```

  Expected: FAIL because yearly aggregation and summary rendering do not yet know the component fields and the table still says `Sold`.

- [ ] **Step 3: Extend yearly aggregation.**

  In `aggregateForView()`, sum every flow field from its monthly slice:

  ```text
  income_tax_paid
  sale_tax_paid
  tax_paid
  sold
  net_sale_proceeds
  ```

  Continue using the last monthly row for balances/effective state and `some()` for sale/depletion flags. Do not recompute tax from a displayed rate because pins can create mixed-rate years.

- [ ] **Step 4: Correct summary calculations and labels.**

  In `renderStats()`:

  - calculate `totalSold` by summing `rows[].sold`;
  - sum income and sale tax separately and derive/display their combined total;
  - replace the old base-rate detail with a concise dollar breakdown using existing formatters;
  - replace the initial-principal percentage detail under **Total liquidated** with **gross sales across projection**.

  Keep the five-card layout and existing horizon/balance semantics.

- [ ] **Step 5: Rename the table header.**

  Change only the visible header from `Sold` to `Gross sold`. Continue displaying `r.sold` and preserve existing notes, CSS classes, and the 11-column table structure.

- [ ] **Step 6: Verify targeted behavior and the complete suite.**

  Run:

  ```bash
  node --test tests/drawdown_sales.test.js
  node --test tests/*.test.js
  ```

  Expected: all aggregation, rendering, helper, simulation, pin, normalization, and date tests pass.

- [ ] **Step 7: Perform the staged safety gate and commit.**

  Stage only the two task files, inspect the complete staged diff and file list, run `git diff --cached --check`, and commit:

  ```bash
  git commit -m "Report gross sales and sale-tax totals"
  ```

## Task 5: Extract and Test Reconciled CSV Serialization

**Files:**

- Modify: `tests/drawdown_sales.test.js`
- Modify: `drawdown.html:2020-2062`

- [ ] **Step 1: Add failing CSV contract tests.**

  Add tests for `buildCsvText(viewRows, unit, pins)` that assert:

  - the original 15 headers remain byte-for-byte in their original positions;
  - `income_tax_paid`, `sale_tax_paid`, and `net_sale_proceeds` are appended in that order;
  - `tax_paid` is serialized as combined income-tax cents plus sale-tax cents, not by independently rounding `r.tax_paid`;
  - `net_sale_proceeds` is serialized as gross-sale cents minus sale-tax cents, not by independently rounding `r.net_sale_proceeds`;
  - all currency values use exactly two decimals;
  - monthly and yearly date labels retain their current formats;
  - pin overrides retain deterministic `PARAM_DEFS` ordering and the existing quoted `key=value; ...` representation.

  Include an adversarial synthetic row whose independently rounded full-precision totals would differ by one cent from the sum of rounded components. Assert the exported identities exactly after parsing decimal strings as cents.

- [ ] **Step 2: Run the CSV tests and verify the red state.**

  Run:

  ```bash
  node --test --test-name-pattern="CSV" tests/drawdown_sales.test.js
  ```

  Expected: FAIL because CSV construction is still embedded in `exportCsv()` and does not append or reconcile the new fields.

- [ ] **Step 3: Add integer-cent serialization helpers.**

  Add small internal helpers with explicit contracts:

  ```text
  toRoundedCents(value) -> Math.round(value * 100)
  formatCents(cents) -> signed decimal string with exactly two fractional digits
  ```

  For each row, calculate:

  ```text
  grossSaleCents = toRoundedCents(r.sold)
  saleTaxCents = toRoundedCents(r.sale_tax_paid)
  netSaleCents = grossSaleCents - saleTaxCents
  incomeTaxCents = toRoundedCents(r.income_tax_paid)
  combinedTaxCents = incomeTaxCents + saleTaxCents
  ```

  This cent relationship is binding for exported values even though simulation rows retain full precision.

- [ ] **Step 4: Extract `buildCsvText(viewRows, unit, pins)`.**

  Move header construction, row serialization, date formatting, and pin-pair collection into the pure builder. Use the passed `unit` and `pins`; do not read `state.params.unit` or `state.pins` inside the builder. Keep existing columns in place, serialize reconciled `tax_paid` and `sold`, then append the three approved component columns at the end.

  Return the joined CSV string. Do not create a `Blob`, object URL, or DOM element in this function.

- [ ] **Step 5: Reduce `exportCsv()` to orchestration and download.**

  Keep its existing simulation, yearly/monthly aggregation, MIME type, filename, click, and URL revocation behavior. Pass `viewRows`, `state.params.unit`, and `state.pins` to `buildCsvText()`, then wrap the returned string in the existing browser download flow.

- [ ] **Step 6: Verify targeted behavior and the complete suite.**

  Run:

  ```bash
  node --test tests/drawdown_sales.test.js
  node --test tests/*.test.js
  ```

  Expected: the schema, rounding, pin-order, and all prior tests pass with zero failures.

- [ ] **Step 7: Perform the staged safety gate and commit.**

  Stage only the two task files, inspect the staged file list and full diff, run `git diff --cached --check`, and commit:

  ```bash
  git commit -m "Export asset-sale tax breakdowns"
  ```

## Task 6: Update Method Documentation and Complete Validation

**Files:**

- Modify: `drawdown.html:1088-1097`
- Modify: `README.md:9-21,66-75`
- Test: `tests/drawdown_sales.test.js`

- [ ] **Step 1: Add a failing terminology/documentation assertion.**

  Assert the on-page method text distinguishes recurring-income tax from asset-sale tax, states that the latter applies to gross proceeds, and says gross liquidation drives principal/income decay. Keep this source-level check narrow; do not snapshot the full page prose.

- [ ] **Step 2: Run the terminology test and verify the red state.**

  Run:

  ```bash
  node --test --test-name-pattern="methodology" tests/drawdown_sales.test.js
  ```

  Expected: FAIL because the current method text describes recurring-income tax only.

- [ ] **Step 3: Update on-page and README documentation.**

  Use the approved terms consistently:

  - **Income effective rate** applies to recurring investment and external income.
  - **Asset sale effective rate** applies to gross sale proceeds.
  - Gross sales are increased so their net proceeds refill the buffer when principal is sufficient.
  - Gross, not net, liquidation reduces principal and drives investment-income decay.
  - `tax_paid` in CSV is combined; component tax fields and `net_sale_proceeds` are appended.
  - The model is a planning simplification and does not represent cost basis, tax lots, account types, or jurisdiction-specific rules.

  Keep the README concise and preserve the existing statement that the tools are not financial, tax, or investment advice.

- [ ] **Step 4: Run the complete automated suite.**

  Run:

  ```bash
  node --test tests/*.test.js
  ```

  Expected: every date and asset-sale test passes with zero failures, skips, cancellations, or todos. Do not summarize the work as complete if any test fails.

- [ ] **Step 5: Perform direct-browser smoke validation with synthetic inputs.**

  Open the absolute local `drawdown.html` file directly in a modern browser; no server is required. Verify:

  1. Default load shows income tax 25% and asset-sale tax 15%, renders without console errors, and retains the current month anchor.
  2. Synthetic scenario: starting cash `$0`, floor `$100`, no income, principal `$1,000`, investment income `$0`, expense `$100`, inflation `0%`, one month. Confirm the buffer ends at `$100`, gross sold displays about `$235`, ending investments about `$765`, and total tax includes about `$35` of asset-sale tax.
  3. Change asset-sale tax to `0%`; confirm gross sold becomes `$200` for the same scenario.
  4. Change asset-sale tax to `100%`; confirm the page stays finite, sells the available principal, deposits no sale proceeds, and reports depletion.
  5. Reset to a non-depleting three-month pin scenario: starting cash/floor `$100`, external income `$0`, principal `$5,000`, investment income `$100`, modifier `0`, expense `$200`, inflation `0%`, income tax `0%`, and asset-sale tax `0%`. Pin month two to 25% asset-sale tax. Confirm month one remains a `$100` gross sale, months two and three become about `$133` gross sales, and the adjustment panel labels the override clearly.
  6. With a non-depleting synthetic scenario loaded, switch to yearly view and confirm gross-sale and tax totals aggregate without layout breakage.
  7. Export monthly and yearly CSV files using only synthetic scenarios. Confirm the three appended headers, two-decimal values, deterministic pin serialization, and both cent reconciliation identities.

  If a smoke check fails, capture the exact symptom, return to the responsible task, add or strengthen an automated regression where practical, and rerun the complete suite.

- [ ] **Step 6: Review the final diff against the approved design.**

  Confirm every goal and acceptance criterion in `docs/superpowers/specs/2026-08-27-asset-sale-tax-gross-up-design.md` maps to implemented code or a passing test. Confirm no non-goal—cost basis, account type, annual settlement, persistence, dependencies, or file splitting—was introduced.

  Run:

  ```bash
  git diff --check
  git status --short
  ```

  Expected: no whitespace errors; only the intended calculator, test, and README files are modified.

- [ ] **Step 7: Perform the final staged safety gate and commit.**

  Stage only `drawdown.html`, `README.md`, and `tests/drawdown_sales.test.js`. Inspect the complete staged file list and diff specifically for sensitive data, run `git diff --cached --check`, and commit:

  ```bash
  git commit -m "Document tax-aware drawdown behavior"
  ```

- [ ] **Step 8: Verify the committed result before handoff.**

  Run fresh:

  ```bash
  node --test tests/*.test.js
  DESIGN_BASE=$(git log -1 --format=%H -- docs/superpowers/specs/2026-08-27-asset-sale-tax-gross-up-design.md)
  git diff "$DESIGN_BASE"..HEAD --check
  git diff --stat "$DESIGN_BASE"..HEAD
  git status --short
  ```

  Expected: all tests pass, the complete series after the approved design has no whitespace errors, its file summary contains only this implementation plan plus the intended calculator/test/README changes, and the working tree is clean. Report the exact test counts and browser observations in the handoff.

## Final Acceptance Checklist

- [ ] Asset-sale tax defaults to 15%; recurring-income tax remains 25%.
- [ ] Sales are grossed up from the shortfall and limited by available investments.
- [ ] Full funding lands exactly on the floor; partial funding and 100% tax remain finite and insolvent.
- [ ] Only net sale proceeds enter cash; gross sales reduce principal and investment income.
- [ ] Pins carry `sale_tax_rate` prospectively without resetting the investment-income epoch.
- [ ] Base and pinned tax inputs normalize to `0..100%`, with documented fallback behavior.
- [ ] Monthly rows, yearly rows, summaries, and CSV export distinguish income tax, sale tax, combined tax, gross sold, and net sale proceeds.
- [ ] Total liquidated sums actual row sales and remains meaningful across investment-balance pins.
- [ ] CSV retains existing columns in place, appends the three new fields, and reconciles exactly at the cent level.
- [ ] UI terminology, README, table header, and methodology text match the approved design.
- [ ] Direct-browser monthly/yearly views, pins, default/0%/100% cases, and download controls work with synthetic inputs.
- [ ] The complete automated suite passes with no failures, skips, cancellations, or todos.
- [ ] The final staged diff contains no sensitive data and the committed working tree is clean.

## Stop Conditions

- Stop before implementation if the approved design and this plan disagree; update the plan rather than improvising behavior.
- Stop on any failing test, browser error, non-finite simulation output, cent-reconciliation mismatch, or unexpected file change. Diagnose and correct it before proceeding.
- Stop before committing if the staged file list contains anything beyond the task’s named files or if any staged content may be sensitive.
- Do not create a PR, merge, or deploy without separate user authorization.
