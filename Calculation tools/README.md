# Calculation Tools

Four browser-based financial calculators implemented as self-contained HTML files. They have no build step or server component: open a file directly in a modern browser or publish the directory with any static file host.

The calculations run entirely in the browser. The pages do not send inputs to a backend or save them in browser storage. Reloading a page restores its built-in defaults.

## Calculators

### `drawdown.html`

Projects how long a cash buffer and investment principal remain solvent under monthly income, expenses, inflation, and taxes.

- Models starting cash, a cash floor, external income, investment principal and income, expenses, annual inflation, and an effective tax rate.
- Applies tax to investment plus external income before expenses.
- Uses investment sales to restore the cash buffer to its floor. Each sale permanently reduces investment income according to the configured income modifier.
- Simulates monthly even when the yearly view is selected; yearly rows aggregate groups of 12 monthly results.
- Supports forward-looking overrides ("pins") from a selected month. Expense, investment income, buffer, and investment cells can also be edited directly to create an override.
- Shows summary statistics, a trajectory chart, a detailed table, and CSV export.
- Treats a period count of `0` as "run to depletion," subject to a 1,200-month (100-year) safety cap.

Projection dates are anchored to the hard-coded model date of May 14, 2026, not the browser's current date. Overrides exist only in page memory and disappear on reload. Google Fonts are loaded from the network when available; the calculator otherwise uses local fallback fonts.

### `early_loan_termination_calculator.html`

Compares the present value of vendor financing at each possible payoff month with paying the full vendor price at time zero.

- Accepts the vendor price, down payment, term, vendor rate, personal discount rate, and first-payment timing.
- Supports APR or APY input for both rates and converts them to monthly rates.
- Produces a standard vendor amortization table and an early-payoff savings table.
- Charts each month's savings as a percentage of the savings at the end of the term.
- Exports both tables as CSV and the chart as PNG.

"Savings" means `vendor price - present value of the financing scenario`; negative values are displayed as zero. The model assumes the remaining loan balance is paid as a lump sum after the selected number of payments. It does not include payoff penalties, transaction fees, taxes, or other financing charges. Chart.js is loaded from jsDelivr, so chart rendering requires network access unless that dependency is cached.

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

1. Open the desired `.html` file in Chrome, Safari, Firefox, or another modern browser.
2. Enter a scenario.
3. Click **Calculate** where provided. `drawdown.html` also recalculates shortly after an input changes.
4. Use the page's export controls if you need CSV data or, for the early-loan calculator, a PNG chart.

No automated test suite or package installation is provided for this directory. When modifying a calculator, verify its default scenario, representative edge cases such as zero interest, and its download controls in a browser.

These tools provide planning estimates, not financial, tax, or investment advice.
