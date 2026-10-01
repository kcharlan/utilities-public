# Calculation Tools

Four financial calculators are self-contained HTML files with no build step or server component. Open those files directly in a modern browser or serve them with a static host. The independently maintained [Market Atlas](backtest/README.md) app lives in `backtest/` and uses external local historical data and a static packaging step. Its data-bearing builds are local runtime artifacts.

Calculations run entirely in the browser, and scenario inputs remain in page memory. The four HTML calculators do not save browser preferences; Market Atlas saves only its appearance preference. Reloading restores the built-in scenario defaults.

## Calculators

### `backtest/` — Market Atlas

Compares fixed-real, fixed-percent, Guyton–Klinger and configurable barbell withdrawal strategies across historical windows. Window, Sweep and Lifestyle views include pinned comparisons, spending floors and frontier exploration. Ordinary numerical defaults are synthetic examples.

Historical workbooks, compiled datasets, exports and local builds stay outside this public repository. Follow the [project README](backtest/README.md) for setup, offline use and the separate complete historical/browser validation gate. The parent test command covers the standalone calculators; it does not run this child project’s suite.

When installed through the existing localhost server, the canonical app link is [Market Atlas](http://127.0.0.1:7711/calculators/backtest/index.html). The folder URL may show the existing file browser. This port does not change shared proxy routing.

### `drawdown.html`

Projects monthly cash flow and investment principal until the requested horizon, a protected-reserve failure, or the 1,200-month safety cap.

- Models starting cash, a cash floor, external income, investment principal and income, expenses, annual inflation, and separate effective rates for recurring income and asset sales.
- Applies the income effective rate to recurring investment income plus external income before expenses. It applies the asset sale effective rate to gross asset-sale proceeds.
- Protects the cash floor while funding monthly expenses. A sale seeks enough net proceeds to cover expenses *and* restore the floor; when sufficient principal exists and the asset sale rate is below 100%, gross sale is `shortfall / (1 - rate)`. A 100% sale rate cannot fund a sale. The final row reports required expense, funded expense, unmet expense, and unmet reserve separately. The projection ends with `reserve_failure` when either amount remains unfunded; reaching zero principal or touching the floor alone does not end it.
- Reduces principal by gross liquidation, not net proceeds. The income ledger retains a raw income amount and yield; each sale or closing-principal valuation adjusts raw income by `modifier × yield × principal change`, using the modifier in force at that event. The change persists in the running ledger and can be reversed by later principal changes. Payable investment income is zero while principal is zero, even if the raw ledger remains positive. An explicit beginning or ending income edit resets the raw baseline and yield; ending income starts paying in the next month.
- Simulates monthly even in yearly view. Yearly rows group up to 12 actual months, sum flows, and show the exact closing balances of the last simulated month. A short final group can be a requested partial horizon or a group cut short by reserve failure; its planned last month and failure month are retained separately.
- Supports one identified adjustment per month. Beginning assumptions affect that month's flow; ending cash, principal valuation, and income baseline apply after expenses and sales. Closing cash is a separate cash adjustment, not recurring income. Only explicitly changed fields are stored. Pins can be moved to another unoccupied month, edited, reset, or removed. An unreachable pin remains visible with unapplied phase status for recovery; a failure-month ending phase does not apply.
- Expense and investment-income table cells edit the selected month's opening assumption; buffer and investment cells set its exact closing balance. In yearly view, flow cells set a target for the planned group by solving the first month's monthly assumption, while closing balance cells target the last simulated month. Annual targets are verified when saved and their target, resolved monthly value, and span are kept as provenance, not as a constraint automatically re-solved after later edits. Moving an annual pin preserves its monthly assumption but clears annual-target provenance.
- Lists adjustments in the **Adjustments** panel, where each can be opened at its exact month or removed. Changes compose chronologically and remain in page memory only.
- Offers Auto, Light, and Dark themes. Auto is selected on every load and follows the operating system's color setting; a Light or Dark override lasts only until reload. No theme choice is stored. Printing always uses the light theme.
- Leads the results with a verdict headline for the current projection. Hovering over the chart highlights the matching table row.
- Provides keyboard-accessible **+** and **✎** edit buttons, Enter or Space to open an editable table cell, and buttons for entries in **Adjustments**. Focus returns to a useful control after an editor closes.
- Stacks the sidebar above the results below 900px. Validation and updating status appear in an overlay near the top of the sidebar. Six money inputs have formatted readouts alongside their numeric controls, and **Clear pins** is disabled when no pins exist.
- Explains the projection's assumptions and boundaries in the structured **Method & scope** appendix.
- Shows summary statistics, a trajectory chart, a detailed table, and CSV export. Table money is rounded to whole dollars for display; hover or keyboard focus reveals cents and, on editable cells, the exact model value. CSV has readable cents columns and exact JavaScript Number `*_raw` columns. Its date, `first_month`, `last_month`, `planned_last_month`, `overrides`, and `adjustments_json` fields preserve row spans and applied/unapplied start/end provenance. Readable tax and sale columns reconcile at cents (`tax_paid = income_tax_paid + sale_tax_paid`; `sold = sale_tax_paid + net_sale_proceeds`), while raw columns retain the unrounded computation.
- Treats a period count of `0` as a run until reserve failure or the 1,200-month (100-year) safety cap. Invalid inputs show a recoverable status and keep the last valid projection visible; CSV export is disabled while it is stale and revalidates before download. Unreachable adjustments remain in the Adjustments panel for correction or removal.

Projection dates are anchored to the browser's current local month when the page loads. Month 1 is the following calendar month. Adjustments exist only in page memory and disappear on reload. Closing principal changes are valuations that affect subsequent investment income without creating a sale or sale tax. Closing cash changes are separate adjustments to cash, not recurring income. Google Fonts are loaded from the network when available; the calculator otherwise uses local fallback fonts.

In CSV exports, `tax_paid` combines recurring-income and asset-sale tax. The `overrides` column contains deterministic month and phase-qualified values with application status. The `income_tax_paid`, `sale_tax_paid`, and `net_sale_proceeds` columns provide readable tax and sale components.

The tax model is a planning simplification. It does not model cost basis, lot selection, account type, capital-gains character, deductions, or jurisdiction-specific rules.

### `early_loan_termination_calculator.html`

Compares the present value of vendor financing at each possible payoff month with paying the full vendor price at time zero.

- Accepts the vendor price, down payment, term, vendor rate, personal discount rate, and first-payment timing.
- Supports APR or APY input for both rates and converts them to monthly rates.
- Produces a standard vendor amortization table and an early-payoff savings table.
- Charts each month's savings as a percentage of the savings at the end of the term.
- Exports both tables as CSV and the chart as PNG.

"Savings" means `vendor price - present value of the financing scenario`; negative values are displayed as zero. The model assumes the remaining loan balance is paid as a lump sum after the selected number of payments. It does not include payoff penalties, transaction fees, taxes, or other financing charges. Chart.js 4.5.1 is loaded from jsDelivr, so chart rendering requires network access unless that dependency is cached.

### `lump_sum_calculator.html`

Finds the monthly internal rate of return (IRR) that makes a lump sum equivalent to a fixed monthly payment stream.

- Accepts a lump sum, periodic payment, term in months, and beginning- or end-of-month payment timing.
- Reports monthly IRR, nominal annualized IRR (`monthly IRR × 12`), and effective annual IRR.
- Builds an amortization table using the calculated rate.
- Accepts a custom monthly rate for a second comparison table.
- Exports either table as CSV.

For beginning-of-month timing, the first payment occurs at time zero and is deducted from the lump sum before Month 1. The page then models the remaining payments at the beginning of later months. The calculator does not model taxes, fees, inflation, or a variable payment stream.

### `money_sense_calculators.html`

Provides separate debt-payoff and savings-growth calculators on one page.

The debt calculator supports:

- A fixed monthly payment plus an optional extra payment.
- A payment calculated from a requested term plus an optional extra payment.
- A credit-card-style minimum payment based on a percentage of balance and a dollar floor.
- Payoff totals, a monthly amortization table, a principal/interest breakdown, and CSV export.

The savings calculator supports:

- A starting amount, annual rate, duration, and monthly contribution.
- Contributions at either the beginning or end of each month.
- Ending-balance, contribution, and interest totals; a monthly growth table; a sparkline; and CSV export.

Both calculators use `APR / 12` monthly compounding and round monthly amounts to cents. The debt loop is capped at 1,200 months. Its payment rules always increase an otherwise insufficient payment enough to cover interest plus at least one cent of principal. Actual credit-card interest commonly uses average daily balance calculations, so statement results can differ.

## Usage

1. Open the desired `.html` file in Chrome or Edge 123+, Firefox 120+, or Safari 17.5+. Older versions do not render `drawdown.html` correctly.
2. Enter a scenario.
3. Click **Calculate** where provided. `drawdown.html` also recalculates shortly after an input changes.
4. Use the page's export controls if you need CSV data or, for the early-loan calculator, a PNG chart.

Run the dependency-free Node regression suite with `node --test tests/*.test.js`. It covers drawdown dates, protected-reserve settlement, sales and income-ledger changes, adjustments, yearly aggregation and targets, and CSV schema and precision. A theme-token guard checks contrast, styling without color literals, absence of browser storage, and the single-script structure. No package installation is required for that suite.

The Playwright suite covers the drawdown editor, yearly target workflow, validation and stale-export recovery, CSV download, theme modes and print styling, responsive layout, chart interaction, keyboard editing, and focus recovery, as well as the Chart.js-backed financing calculator in Chromium:

```sh
npm ci
npx playwright install chromium
npm run test:browser
```

Run both full automated suites with `npm test`. To inspect the browser suite before running it, use `npx playwright test --list`. The other calculators still require browser checks when changing them; verify their default scenarios, representative edge cases such as zero interest, and download controls.

These tools provide planning estimates, not financial, tax, or investment advice.
