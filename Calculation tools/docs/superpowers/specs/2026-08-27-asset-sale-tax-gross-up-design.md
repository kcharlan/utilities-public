# Asset-Sale Tax Gross-Up Design

**Status:** Approved for design documentation; implementation requires separate approval

**Date:** 2026-08-27

**Project:** `Calculation tools/drawdown.html`

## Summary

The drawdown calculator currently taxes recurring investment and external income, but it treats investment-sale proceeds as tax-free cash. When the cash buffer falls below its floor, the calculator sells exactly the shortfall, deposits the entire sale into the buffer, and reports no tax from the sale.

Add a separate **Asset sale effective rate** input, defaulted to **15%**, and gross up each sale so its after-tax proceeds—not its gross amount—cover the cash shortfall. Preserve separate income-tax and sale-tax amounts, while making the existing `tax_paid` concept the combined total. Keep the calculator as a self-contained HTML application with no new dependencies.

## Goals

- Add a distinct effective tax rate for asset sales without changing the meaning or default of the existing income-tax rate.
- Sell enough gross principal to restore the cash buffer to its floor after paying sale tax, subject to the available investment balance.
- Make gross sale, net sale proceeds, income tax, sale tax, and combined tax internally reconcilable and visible in exported data.
- Preserve the existing recurring-income, expense, inflation, pin, income-decay, monthly simulation, yearly aggregation, and depletion models except where sale taxation necessarily changes their results.
- Handle boundary inputs deterministically without `Infinity`, `NaN`, or floating-point false insolvency.
- Add focused regression coverage for the new calculation and all affected projections.

## Non-goals

- Do not model cost basis, tax lots, short- versus long-term gains, account types, deductions, loss harvesting, tax brackets, or tax-payment timing beyond the configured effective rate.
- Do not infer whether a particular account is taxable, tax-deferred, or tax-free.
- Do not add annual tax settlement, estimated-tax payments, or refunds.
- Do not persist settings or pins; they remain page-memory state.
- Do not split the intentionally self-contained `drawdown.html` into modules or add a build system.

## Current Behavior and Root Cause

In `simulate()` in `drawdown.html`:

1. `investment_income` and `external_income` form `total_pretax`.
2. The existing `tax_rate` is applied to that recurring income.
3. Expenses reduce the buffer.
4. If the buffer is below its floor, `deficit = floor - buffer`.
5. The calculator sets `sold = min(deficit, investments)` and deposits all of `sold` into the buffer.

Because the sale is outside `total_pretax`, the sale neither generates tax nor requires a gross-up. The existing `tax_paid` row value and “Total tax paid” statistic therefore include recurring-income tax only.

## Chosen Approach

Add a small pure calculation boundary inside the existing script:

```js
calculateAssetSale(deficit, availableInvestments, saleTaxRate)
```

It returns:

```js
{
  grossSold,
  saleTaxPaid,
  netSaleProceeds,
  unfundedDeficit,
}
```

This is preferred over placing the formula inline in `simulate()` because the boundary makes the gross-up rules and edge cases independently testable. A generalized tax-lot or account-type engine is intentionally out of scope.

### Function contract

Inputs are finite numbers. The caller normalizes `saleTaxRate` to the inclusive range `0..1`; `deficit` and `availableInvestments` are nonnegative.

The result must satisfy these invariants:

- `0 <= grossSold <= availableInvestments`
- `grossSold = saleTaxPaid + netSaleProceeds`
- `0 <= netSaleProceeds <= deficit`
- `unfundedDeficit = deficit - netSaleProceeds`, bounded below by zero
- A fully funded sale returns `netSaleProceeds === deficit` and `unfundedDeficit === 0`
- After applying a sale, `endingBuffer = floor - unfundedDeficit`
- A zero deficit or zero investment balance never creates a sale or sale tax
- No field is `Infinity` or `NaN`, including at a 100% rate

### Load-bearing calculation

The implementation should follow this branch structure so a fully funded sale lands exactly on the floor and does not become falsely insolvent through floating-point roundoff:

```text
if deficit <= 0 or available investments <= 0:
    gross sold = 0
    sale tax = 0
    net proceeds = 0
    unfunded deficit = max(0, deficit)

else if sale tax rate >= 1:
    gross sold = available investments
    sale tax = gross sold
    net proceeds = 0
    unfunded deficit = deficit

else:
    net fraction = 1 - sale tax rate
    maximum net proceeds = available investments * net fraction

    if maximum net proceeds >= deficit:
        gross sold = deficit / net fraction
        net proceeds = deficit
        sale tax = gross sold - net proceeds
        unfunded deficit = 0
    else:
        gross sold = available investments
        net proceeds = gross sold * (1 - sale tax rate)
        sale tax = gross sold - net proceeds
        unfunded deficit = max(0, deficit - net proceeds)
```

Testing the finite `maximum net proceeds` before dividing avoids overflow when the rate is extremely close to 100%. Using subtraction for `saleTaxPaid` preserves the conservation identity even when floating-point division is inexact.

At the default 15% asset-sale rate, a $1,000 shortfall requires a gross sale of approximately $1,176.47, produces approximately $176.47 of sale tax, and deposits exactly $1,000 into the buffer when sufficient principal is available.

The simulation retains full floating-point precision and does not round monthly sale calculations to cents. Existing money formatting continues to control on-screen rounding, while CSV amounts continue to use two decimal places. This preserves the calculator’s current precision model and prevents repeated monthly rounding drift.

## Simulation Data Flow

The monthly ordering remains explicit:

1. Apply pins scheduled for the month.
2. Calculate recurring investment income.
3. Add recurring external income.
4. Calculate income tax using `current_tax`.
5. Subtract expenses and update the buffer using after-income-tax recurring income.
6. If the buffer is below `current_floor`, calculate a tax-aware asset sale using the month’s `current_sale_tax`.
7. Reduce investments by `grossSold`.
8. Add only `netSaleProceeds` to the buffer.
9. Reduce future investment income using `grossSold / baseline_principal`, multiplied by the current income modifier.
10. Record income tax, sale tax, combined tax, gross sale, net sale proceeds, balances, and insolvency state.
11. Inflate the next month’s expense and apply the existing termination check.

Sale tax is modeled as being paid immediately from the gross proceeds in the same simulated month. It is not added to expenses or recurring-income `delta`.

Retain the existing meaning of `hitFloor`: it is true when the buffer falls below the floor while a positive investment balance is available for liquidation. A below-floor month with no investments is insolvent but does not report a sale attempt.

### Existing table semantics

- `Net` remains recurring income after income tax. It does not include asset-sale proceeds.
- `Δ` remains recurring net income minus expense. It does not include asset sales or sale tax.
- `Gross sold` is the gross amount removed from investments.
- The buffer receives only net sale proceeds.

Keeping financing activity outside `Net` and `Δ` avoids changing the meaning of those established columns.

## State and Pin Model

Add `sale_tax_rate: 0.15` to `state.params` and `current_sale_tax` to simulation state.

Add a `sale_tax_rate` entry to `PARAM_DEFS` so the existing adjustment editor, adjustment list, deterministic override ordering, and pin lifecycle support the new value. The label should be **Asset sale tax rate** and the stored value should be a decimal fraction.

Both `snapshotPreState()` and `snapshotEffectiveState()` must include `sale_tax_rate`. A pin containing that key updates `sim.current_sale_tax` before calculating the pinned month. It applies forward until another pin changes it. Past sale taxes remain governed by the rate effective in their respective months because every sale uses the current rate during simulation.

The parameter-definition metadata should support field-specific percentage bounds. Inflation retains its existing range; `tax_rate` and `sale_tax_rate` use `0..1` in state and `0..100` in displayed percent inputs. Pin saves normalize both tax-rate fields to that range so a pin cannot bypass the base form’s constraints.

## Input and Validation Design

In the Tax group:

- Rename **Effective rate** to **Income effective rate**, retaining the 25% default.
- Change its hint to **applied to recurring income**.
- Add **Asset sale effective rate**, defaulted to 15%, with the hint **applied to gross sale proceeds**.
- Use `id="sale-tax-rate"`, `step="0.5"`, `min="0"`, and `max="100"`.

`readParams()` must populate `p.sale_tax_rate`, and the new element must join the debounced recalculation input list.

Use one shared percentage-input normalization path for the base income-tax and asset-sale-tax fields:

- Convert displayed percentages to decimal fractions.
- Clamp finite values to `0..100` before conversion and reflect a clamped value back into the input so displayed and simulated values cannot diverge.
- Restore the field’s documented default when the value is blank or non-finite: 25% for recurring income tax and 15% for asset-sale tax.

For pin-editor tax fields, a blank or non-finite value reverts to that field’s effective baseline for the pinned month and therefore does not create an override. Finite values are clamped to `0..100`, reflected in the editor, converted to `0..1`, and compared with the baseline using the existing floating-point equality rule. This preserves the established meaning of resetting a pin field rather than unexpectedly inserting a global default.

This normalization is intentionally limited to the two tax inputs and their pin equivalents; broader form-validation changes are outside scope.

## Impacted Code Surfaces

The implementation remains localized to the maintained project files:

- `drawdown.html`
  - Tax-group labels and the new base input
  - `PARAM_DEFS`, `state.params`, and monthly simulation state
  - A pure `calculateAssetSale()` helper and the sale branch in `simulate()`
  - Pin application, `snapshotPreState()`, and `snapshotEffectiveState()`
  - `aggregateForView()`, `renderStats()`, and the amortization-table header
  - Tax-input and pin-input normalization
  - `readParams()`, the debounced input list, `buildCsvText()`, and `exportCsv()`
  - On-page method text
- `README.md`
  - Behavioral description, simplified-tax caveat, and expanded CSV semantics
- `tests/drawdown_sales.test.js`
  - Pure helper, simulation, pins, aggregation, summary, normalization, and CSV regressions

The trajectory chart requires no special code path: it already renders the resulting buffer and investment balances, which will naturally reflect larger gross liquidations. Existing date tests remain in `tests/drawdown_dates.test.js`.

## Row, Aggregation, and Summary Data

Each monthly row should contain:

- `income_tax_paid`: tax on recurring investment plus external income
- `sale_tax_paid`: tax retained from the gross asset sale
- `tax_paid`: `income_tax_paid + sale_tax_paid`
- `sold`: gross principal liquidated; this preserves the existing field name while clarifying its semantics
- `net_sale_proceeds`: cash deposited into the buffer from the sale

`aggregateForView()` must sum all five flow fields across each yearly slice. Ending balances and existing flags continue to come from the appropriate underlying monthly rows.

`renderStats()` should calculate:

- Total liquidated by summing row `sold` values, rather than subtracting ending investments from starting investments. This remains correct when an investment-balance pin resets principal.
- Total income tax by summing `income_tax_paid`.
- Total asset-sale tax by summing `sale_tax_paid`.
- Total tax paid by summing combined `tax_paid`.

The existing **Total tax paid** headline displays the combined total. Its detail text shows the income-tax and asset-sale-tax dollar breakdown instead of showing only the initial income-tax rate, which can be misleading when pins change either rate.

The **Total liquidated** detail should read **gross sales across projection** rather than expressing sales as a percentage of initial principal. An investment-balance pin can add or remove principal, so gross cumulative sales may legitimately exceed the original starting balance and the old percentage denominator would be misleading.

Rename the amortization-table header **Sold** to **Gross sold**. The row value remains `sold`. No additional table columns are required; the summary and CSV provide the tax breakdown without widening the already dense table.

## Insolvency and Termination

Replace the current `sold < deficit` insolvency test with the helper result:

```text
insolvency = unfundedDeficit > 0
```

The fully funded branch explicitly sets `unfundedDeficit` to zero, avoiding a tolerance-dependent result. When investments are insufficient, the calculator sells the entire available balance, deposits its after-tax proceeds, records the sale tax, marks the row insolvent, and then reaches the existing depletion termination condition when investments are zero and the buffer remains at or below its floor.

At a 100% asset-sale rate, the calculator deliberately liquidates the available balance, records the entire liquidation as sale tax, deposits zero net proceeds, and marks the shortfall unfunded. This is the finite limiting behavior of the configured effective-rate model; the UI and methodology text must make clear that the rate applies to gross proceeds.

## CSV Contract

Retain every existing CSV column in its current position. Keep `tax_paid` in place, but redefine it as combined income tax plus asset-sale tax. Keep `sold` in place and define it as gross liquidation.

Append these columns to the end of each exported row:

1. `income_tax_paid`
2. `sale_tax_paid`
3. `net_sale_proceeds`

Appending is an additive schema change that minimizes disruption for consumers relying on existing column positions. Consumers that require an exact column count will still need to adapt; the README must call out the expanded schema and the changed `tax_paid` semantics.

### CSV rounding contract

Internal simulation rows retain full precision, but related exported currency fields must reconcile exactly at two decimal places. `buildCsvText()` should convert the component amounts to integer cents before serializing:

```text
gross sale cents = round(sold * 100)
sale tax cents = round(sale_tax_paid * 100)
net sale proceeds cents = gross sale cents - sale tax cents

income tax cents = round(income_tax_paid * 100)
combined tax cents = income tax cents + sale tax cents
```

Serialize those integer-cent values with exactly two decimals. This makes exported `sold = sale_tax_paid + net_sale_proceeds` and `tax_paid = income_tax_paid + sale_tax_paid` hold exactly, rather than occasionally differing by one cent because three full-precision values were rounded independently. Other existing CSV money fields retain their current formatting.

For testability, separate CSV serialization from browser download side effects:

```js
buildCsvText(viewRows, unit, pins) -> string
```

`buildCsvText()` owns the header order, value formatting, pin serialization, and appended fields. `exportCsv()` continues to run the simulation and aggregation, then passes those rows to `buildCsvText()` before creating the `Blob`, object URL, and download link. This small extraction allows schema and reconciliation tests without emulating a browser download.

## Documentation Changes

Update `Calculation tools/README.md` and the on-page method footnote to state:

- Recurring investment and external income use the income effective rate.
- Asset sales use a separate effective rate on gross proceeds.
- Sales are grossed up so net proceeds refill the buffer when sufficient investments exist.
- Gross liquidation—not net cash—is used for principal depletion and investment-income decay.
- Tax treatment is a planning simplification and does not model basis, tax lots, account type, or jurisdiction-specific rules.

The table header, tax input hints, and summary breakdown should use the same terminology: **income tax**, **asset-sale tax**, **gross sold**, and **net sale proceeds**.

## Test Design

Add a dependency-free Node test file, following the existing `node:test` plus `vm` pattern, that loads the inline script and exposes only the calculation symbols needed by the test context. Production code does not need to publish a browser-global testing API.

Required regression cases:

1. **Default wiring:** HTML and `state.params` both default asset-sale tax to 15%.
2. **Zero rate:** A $1,000 deficit sells $1,000, records zero sale tax, and deposits $1,000.
3. **Default 15% rate:** A $1,000 deficit with sufficient investments sells approximately $1,176.47, records approximately $176.47 sale tax, deposits exactly $1,000, and lands exactly on the floor.
4. **Combined tax:** A month with recurring taxable income and an asset sale records correct `income_tax_paid`, `sale_tax_paid`, and their sum in `tax_paid`.
5. **Insufficient investments:** With $1,000 available at 15%, the helper reports the remaining deficit; the simulation sells all $1,000, deposits $850, records $150 sale tax, ends below the floor, and marks insolvency.
6. **100% rate:** The result contains only finite numbers, liquidates the available investments, records all proceeds as sale tax, deposits zero, and marks insolvency.
7. **No shortfall:** No sale and no sale tax occur when the post-expense buffer is at or above the floor.
8. **Gross-based income decay:** Future investment income declines according to gross principal sold, not net proceeds.
9. **Pinned rate:** A `sale_tax_rate` pin changes sales beginning in its pinned month and carries forward without changing earlier rows.
10. **Year aggregation:** Gross sales, net proceeds, income tax, sale tax, and combined tax equal the sums of their monthly rows.
11. **Input normalization:** Blank, non-finite, below-zero, above-100%, and exactly-100% base and pin values follow the documented normalization rules.
12. **CSV shape and rounding:** Existing columns retain their order and semantics except for the documented `tax_paid` and `sold` clarifications; the three new fields are appended, use two decimals, and satisfy both cent-level reconciliation identities for every exported row.
13. **Existing behavior:** Current date anchoring tests and a representative no-sale scenario remain unchanged.
14. **Pinned principal reporting:** Total liquidated is the sum of actual row sales and its detail remains meaningful when a pin changes the investment balance.

Use approximate assertions for repeating-decimal gross-ups, but exact assertions for the deliberately exact fully funded `netSaleProceeds`, zero `unfundedDeficit`, and ending buffer floor.

Run the complete project suite:

```bash
node --test tests/*.test.js
```

Expected result: every date and asset-sale test passes with zero failures, skips, cancellations, or todos.

## Acceptance Criteria

- The new base input is visible, defaults to 15%, and recalculates the projection after edits.
- The existing income-tax input remains defaulted to 25% and affects recurring income only.
- With sufficient principal and a sale-tax rate below 100%, every sale restores the buffer exactly to its floor after tax.
- Gross sale, sale tax, and net proceeds reconcile for every monthly and yearly row.
- Gross principal sold reduces both investments and the investment-income coefficient.
- Insufficient principal and a 100% rate produce finite, deterministic depletion results.
- Pins can change the asset-sale tax rate prospectively.
- “Total tax paid” equals income tax plus asset-sale tax and displays both components.
- “Total liquidated” sums actual gross sales and does not compare them with a stale initial-principal denominator after investment pins.
- CSV export retains existing columns in place and appends the three documented breakdown columns.
- README, UI labels, table header, and method text consistently describe the simplified effective-rate model.
- The complete test suite passes.

## Risks and Mitigations

- **Projection changes may be substantial:** This is the intended correction. Tests should compare tax-free and taxed scenarios and confirm the higher gross liquidation.
- **Users may interpret the rate as a capital-gains rate:** Label and documentation must say it is an effective rate on gross sale proceeds, not a tax-law calculation.
- **CSV consumers may assume `tax_paid` means recurring-income tax:** Document the semantic change and provide explicit component columns.
- **Floating-point division may create tiny floor gaps:** The fully funded branch assigns net proceeds directly from the deficit and derives tax by subtraction.
- **Pins can create mixed-rate periods:** Store tax components per monthly row and aggregate actual amounts rather than reconstructing totals from base rates.
- **Manual investment pins can distort starting-minus-ending liquidation totals:** Sum row-level gross sales for the statistic.

## Design Completion Boundary

This document authorizes and specifies the design only. It does not authorize implementation. After review and explicit implementation approval, create a separate implementation plan grounded in the then-current code before modifying `drawdown.html`, tests, or README behavior.
