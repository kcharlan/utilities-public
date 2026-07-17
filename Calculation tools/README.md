# Calculation Tools (Static HTML)
A handful of single-page calculators built in HTML/JavaScript for quick financial what-if scenarios. There is no build chain—just open the files directly in a browser. Some pages load presentation dependencies from public CDNs (`drawdown.html` uses Google Fonts; the early-loan calculator uses Chart.js), so those enhancements need network access unless cached.

## Files

- `early_loan_termination_calculator.html` – Analyze early loan payoff scenarios: compare remaining interest, penalties, and savings when terminating a loan ahead of schedule. Includes a savings-over-time chart.
- `drawdown.html` – Model retirement-account solvency year by year, including income, expenses, growth, inflation, taxes, and editable one-off adjustments pinned to individual years.
- `lump_sum_calculator.html` – Compare taking a lump sum payout versus an equivalent annuity stream, factoring in discount rates and time horizons.
- `money_sense_calculators.html` – Two calculators on one page: a Debt/Credit Card payoff calculator and a Savings/Investment growth calculator.

## Usage

1. Open the HTML file of interest in any modern browser (Chrome, Safari, Firefox).
2. Adjust inputs inline; JavaScript updates the results immediately.
3. Modify the inline calculator logic if you need to tweak formulas; each page remains a single HTML file even where it references a CDN asset.

## Tips

- For more complex scenarios you can duplicate a file, customize the logic, and keep it alongside the originals.
- When hosting on an intranet or sharing, the files do not require any server-side logic; static hosting is sufficient.
