# Tax2 Built-Page Migration — Design Spec

Status: approved direction; the decisions and contracts below are binding for the implementation plan · Date: 2026-10-08

This spec moves Tax2 from a FastAPI server with a CDN-loaded React UI to the
repository's default **built page** shape, and removes the retired
`md-autotax` project.

It is written for the agent that will write the implementation plan. The spec
fixes the decisions, contracts and load-bearing algorithms. The planner owns
the task breakdown, sequencing within §11, and routine implementation detail.

## 0. Read first

- **`agents.md` → UI Shapes.** The canonical rules for built pages, the
  front-end stack and tests. Where this spec is more specific, it wins for Tax2.
- **Tax2's own docs:** `tax2/README.md`, `tax2/docs/Usage.md`,
  `tax2/docs/multi_state_design.md`. The multi-state invariants remain in force
  except where §2 or §8 changes them.
- **The current UI in `tax2/tax2`:** the `HTML_TEMPLATE` string, lines
  475–1879. §6.1 lists the behaviours to keep; inspect the code for exact
  wording and styling.
- **`colophon/colophon`, the built-page reference.** Use these functions:
  - `runtime_home`, `ensure_runtime_home` and `atomic_write_bytes`;
  - `render_page`, which serializes JSON and then replaces each `<` with the
    six-character JSON escape (backslash followed by `u003c`);
  - `write_page`;
  - `webbrowser.open(output.resolve().as_uri())`, where `resolve()` is needed
    for relative `--output` paths.

  Follow Colophon for shape, not stack: it uses plain JavaScript, while Tax2
  uses Preact + htm (§5).
- **`model_sentinel/model_sentinel/browse/assets/vendor/`:** the vendored
  Preact, hooks and htm files and `VERSIONS.md`.
- **`tools/testkit.py`:** `guard_browser_errors`, `load_launcher`,
  `run_launcher` and `assert_launcher_help`.

## 1. Goals and non-goals

**Goals**
- `./tax2` validates the YAML rules, builds one self-contained HTML page, writes
  it to the runtime home, and opens it from `file://`. There is no server and no
  port.
- The page makes no network requests.
- Every calculation, the QIF export and both table exports run in the page,
  from one JavaScript engine.
- Annual tax values match the current Python engine exactly (§9). Monthly
  amounts round up to the next cent instead of to the nearest cent (D6).
- Remove table input (table mode). Add two exports for manual backup and
  lookup: rate schedules and income-step lookup tables (§7).
- Remove `md-autotax` from the repository and every live reference (§10).

**Offline boundary.** The built page opens and works offline at any time,
without the launcher. Rebuilding offline needs uv's cache to already hold an
environment for the launcher's dependencies: pydantic and pyyaml, unpinned. A
first run, or the first run after the cache is cleared or the dependencies
change, may need the network once. State this in the README.

**Non-goals**
- No new tax features, jurisdictions or rules. Rules files are unchanged.
- No change to the multi-state model: federal is computed once on total income,
  each state on its allocated share, and allocations are independent.
- Not modelled, unchanged from today:
  - preferential rates for qualified dividends and long-term capital gains;
  - the net investment income tax;
  - FICA and self-employment tax;
  - the items in `multi_state_design.md` "Goals and boundaries".

## 2. Decisions

**Settled with the user:**

| # | Decision | Reason |
|---|---|---|
| D1 | Built-page shape per `agents.md` UI Shapes. | Offline need. No outside side effects remain once table input and config writes go. |
| D2 | The tax engine lives only in JavaScript. Retire `taxkit/engine.py`, `taxkit/tablegen.py`, `taxkit/qif.py` and `cli.py`. | One home for logic. The page needs the engine for interactive results. |
| D3 | Python keeps four jobs: rules discovery, YAML loading, schema validation, and v1→component normalization (`taxkit/models.py`, `taxkit/rules_loader.py`, `taxkit/utils.py`), plus config loading (`taxkit/config.py`). The page receives normalized rules JSON and never parses YAML. | Validation is build-time gathering. Normalization has one home. |
| D4 | Remove table mode and all table input, listed below. | Tables were an input workaround that is no longer needed. Table mode also silently drops earned-only components. |
| D5 | Offer **both** exports: a rate schedule and an income-step lookup table (§7). | User decision. |
| D6 | **Round toward the safe side** (§6.4). Each displayed figure rounds in whichever direction makes its error harmless: tax amounts and tax rates round **up**; net income is never overstated; income inputs are whole cents, so they never need rounding. This applies in the calculator, QIF and both exports. Keep `T-0.00` on a zero-amount expense line. | User decision: overpaying tax is fine, underpaying is not; underestimating spendable income is fine, overestimating is not. Monthly tax amounts change from today's nearest-cent values by at most one cent per jurisdiction. |
| D7 | Remove `md-autotax`, including from `docs/privacy_scrub_design.md` (§10). | User decision; the project is retired. |

D4 removes:
- the **Lookup Table** radio;
- `_lookup_monthly_tax` and `legacy_combined_alias`;
- `/api/generate-tables`;
- the `tables/` directory and its `*.parquet` fixtures;
- the `combined_*.csv` contract.

**Made by this spec on the user's behalf** (the user can override any of them
before planning):

| # | Decision |
|---|---|
| S1 | Page source lives in separate tracked files under `tax2/web/` (§5.1). The builder inlines them into one output file. |
| S2 | System font stacks replace the three Google Fonts families. Lucide is dropped: its `Icon` component is defined but never rendered. |
| S3 | `--rules-dir PATH` replaces the positional `rules_dir` argument, which today is accepted but ignored by `/api/compute`. |
| S4 | An invalid rules file fails the build with exit 1 and a message naming the file. A file is invalid if it fails to load, if it does not declare both filing statuses the UI offers (`single`, `married_joint`), or if any component lacks a standard deduction or brackets for either status. A file is also invalid if any bracket `rate` or credit-phaseout `rate_per_dollar` is negative, which keeps tax non-decreasing in income, or if bracket `up_to` values are not strictly ascending (`null` allowed only last), which keeps the tax curve free of jumps. A rules root with no federal year, or with no state directories holding a valid rules file, also exits 1. Today `_discover_states` logs the error and lists the state with fallback values, and the compute later fails with a 500. |
| S5 | The in-page state selection persists in browser storage and takes precedence over `default_states` (§6.6). The page never writes `config.yaml`. |
| S6 | The schedule exports as Markdown and the lookup table as CSV. Scope: the selected year, all filing statuses (schedule) or the selected filing status (CSV), and every jurisdiction with rules for that year. |
| S7 | Keep the `--no-browser` flag name. Remove `--port`. The app version becomes `3.0`. |

**Fixes to today's behaviour** (each one also changes a test):

| # | Fix |
|---|---|
| F1 | The QIF default date is the **local** date. Today it is the UTC date (`new Date().toISOString()`), which is wrong in local evenings. |
| F2 | `qif_overrides` apply whenever a state's QIF fields are first initialized, including states checked after load. An empty field falls back through the same chain when the QIF is built. Today, states checked later get empty overrides, and an empty field falls back only to the hard-coded strings. |
| F3 | Allocation inputs are visible whenever a state is selected. Today they show only with two or more states, yet a hidden allocation still applies: set GA to 50, uncheck PA, and GA is still computed at 50% with no visible control. |
| F4 | The export panel stays reachable at every width; below 1200 px it stacks under the main panel. Today `.export-panel { display: none }` at 1200 px and below hides the QIF export entirely. |
| F5 | Result-card state names use the selected year's `display_name`, then the state's discovered display name, then the code. Today GA 2025 has no `display_name`, so its card says "GA" while the sidebar says "Georgia". |
| F6 | Input validation moves into the page (§6.2). The server's validation goes away with it. |

## 3. Launcher contract

`tax2/tax2` stays a uv-managed launcher. It still imports the `taxkit` package
from beside itself, so Tax2 remains a multi-file project deployed as a
directory copy (§12).

**Header dependencies:** `pydantic` and `pyyaml`. Remove `fastapi`,
`uvicorn`, `pandas`, `python-dateutil` and `pyarrow`.

**Flags**

| Flag | Contract |
|---|---|
| (none) | Build and open the page. |
| `--no-browser` | Build without opening. Also implied when `UTILITIES_TESTING` is truthy, as today. |
| `--output PATH` | Write the page to PATH instead of the runtime home. Same mode 0600 and atomic replace. |
| `--rules-dir PATH` | Rules root containing `federal/` and `states/`. Default: `rules/` beside the launcher. |
| `--help` | Usage, flags, `TAX2_HOME` and the runtime files. |

On success, print the written page path.

**Exit codes:**
- 0: success, including a failure to open the browser after the page is written.
- 1: fatal error: missing or invalid federal rules, invalid state rules, no
  valid state, or an unwritable output.
- 2: usage error (argparse).

**Runtime home:** `$TAX2_HOME` or `~/.tax2`.
- Create it with mode 0700 and reapply that mode on every run.
- Write `tax2.html` there by default, atomically with mode 0600.
- Create `config.yaml` only when it is missing, atomically with mode 0600.
  Never rewrite an existing config.
- Replace the general-purpose `save_config` with this create-if-missing
  behaviour.

**Config:** keeps `default_states` and `qif_overrides`.
- Drop `legacy_combined_alias` from the defaults. Ignore it when present so
  existing files still load.
- A corrupt config still warns, uses the defaults and is not overwritten.
- The config is edited by hand; the page never writes it.

## 4. Build pipeline and payload

**Pipeline:**
1. Resolve the rules root.
2. Discover the federal years and state directories, as `get_available_years`
   and `_discover_states` do today.
3. Load and validate every rules file with `load_rules`, plus the S4 checks.
4. Load the config.
5. Assemble the payload.
6. Render the page:
   - Serialize the payload as JSON with `ensure_ascii=True` and
     `allow_nan=False`.
   - Replace each `<` with the backslash-`u003c` escape, as Colophon's
     `render_page` does.
   - Inline the vendored scripts, app scripts, CSS, licence notices and the
     payload into the template.
7. Write the page.
8. Open it unless suppressed.

**Payload, schema 1:**

```json
{
  "schema": 1,
  "app": {"name": "Tax2", "version": "3.0"},
  "built_at": "<UTC ISO-8601>",
  "rules_source": "bundled | custom",
  "federal": {"<year>": <TaxRules>},
  "states": [
    {"code": "GA", "display_name": "Georgia", "years": [2025, 2026],
     "qif": {"state_expense": "...", "state_transfer": "..."} | null,
     "rules": {"<year>": <TaxRules>}}
  ],
  "config": {"default_states": ["GA"], "qif_overrides": {}}
}
```

- `<TaxRules>` is `TaxRules.model_dump(mode="json")` of the normalized rules.
  Enums become strings, and a v1 file arrives as one `default` component.
- A state's `display_name` and `qif` come from its latest year, as the sidebar
  does today.
- Never embed absolute paths or anything from the environment.

## 5. Page architecture

### 5.1 Source layout (S1)

```text
tax2/web/
  template.html   skeleton with placeholders for CSS, licence notices, vendor JS, app JS, payload
  styles.css      plain CSS with custom-property tokens for light and dark
  engine.js       engine, rounding, validation, QIF and export builders; no DOM access
  app.js          Preact + htm UI
  vendor/         preact.umd.js, hooks.umd.js, htm.umd.js, preact.LICENSE, htm.LICENSE, VERSIONS.md
```

**Vendor files.**
- Copy them byte-for-byte from model_sentinel (Preact 10.29.8, hooks 10.29.8,
  htm 3.1.1). Copy the same `VERSIONS.md` rows (version, exact source URL,
  SHA-256) for those files and their licences. `preact.LICENSE` covers hooks.
- Put the licence notices in the page, as UI Shapes requires.
- The builder fails if any inlined file contains `</script`; today's files do
  not.

**Scripts.**
- `engine.js` exposes its functions on one global, `window.Tax2Engine`, so
  browser tests can call them through `page.evaluate`.
- Load order: vendor scripts, then `engine.js`, then `app.js`, all classic
  inline scripts.
- `app.js` binds `const html = htm.bind(preact.h)`.

### 5.2 Stack constraints

- No CDN, JSX, Babel, Tailwind, React or network access.
- Keep today's visual design (the existing CSS variables and
  `docs/UI_Design_Reference.html`).
- Most of today's CSS is already plain. The few Tailwind utility classes need
  CSS equivalents: the error card, the old loading text, `font-display` and
  `inline-block`.
- Use system font stacks (S2).
- Show the build time in the page.

## 6. Page behaviour

### 6.1 What to keep
Inspect the template for exact wording.

**Header and sidebar**
- Title.
- Tax Year selector, newest first. The default is the current **local** year if
  federal rules exist for it, otherwise the latest federal year. Evaluate it
  when the page opens, not when it was built.
- Filing Status: Single or Married Filing Jointly.
- State checkboxes; at least one stays selected.
- Allocation % per state: 0–100, clamped and independent (F3 for visibility).
- `FY {year}` badge.
- Theme toggle, persisted.

**Income**
- Monthly Unearned Income and Monthly Earned Income, defaulting to 12,500 and 0.
- Today's money-input behaviour:
  - shows the raw number while focused;
  - formats to 2 decimals with grouping on blur;
  - an empty input means 0.
- The line `Total ${monthly} monthly = ${monthly×12} annually`.

**Results** (monthly figures only; no annual figures are shown today):
- Federal Tax card: `federal_cents`, formatted from cents (§6.4), with an
  `X.X% effective` sublabel.
- One card per state:
  - the name (F5), with the suffix ` (N%)` when the allocation is not 100;
  - its `state_cents`;
  - an `X.X% effective` sublabel.
- The card sublabels show `cents / gross_cents × 100` rounded **up** to one
  decimal place (§6.4 `ceilScaled`), or `0.0` when gross is 0.
- Total Monthly Tax card: `total_monthly_cents`, with the sublabel
  `{effective_rate}% combined` (§6.3 defines and formats the rate).
- Net Monthly Income card:
  - `net_cents = gross_cents − total_monthly_cents`, all integer cents.
    `gross_cents` is the exact sum of the two income inputs, parsed from their
    text as whole cents (F6), never through floats. Tax is rounded up, so net
    income is never overstated. `centsFromTwoDecimalDisplay` is no longer
    needed.
  - sublabel "Gross minus estimated taxes";
  - the summary note under it;
  - negative values shown with a leading `-`.

**Errors**
- The error card shows `Error: {message}`, replaces the result cards, and
  disables the QIF download.
- A state without rules for the selected year produces
  `State {CODE} has no rules for {year}. Available years: {years}`.
  - `{years}` uses Python list formatting: `[2026]`, `[2025, 2026]`, or
    `none` when the list is empty.

**QIF panel**
- Transaction Date, Payee Name, Federal Expense Category and Federal Transfer
  Account.
- For each selected state, Expense Category and Transfer Account.
- Default chain for a state's fields: `qif_overrides`, then the YAML `qif`
  block, then `Tax:State Income Tax Estimated Paid` / `[{CODE} State Income
  Taxes]`.
- A state's edited fields survive being unchecked and checked again.
- An empty state field falls back through that same chain when the QIF is built
  (F2).

### 6.2 Removed or changed
- **Computation mode** (rules versus table) is removed.
- **The "Calculating…" pending state** is removed; computation is synchronous
  on input change. The stale-result tests are replaced by tests showing that
  results always match the current inputs.
- **Validation (F6).**
  - Money inputs accept non-negative amounts in dollars and cents, matching
    exactly:

    ```text
    ^\s*(?:(?:\d{1,3}(?:,\d{3}){1,3}|\d{1,12})(?:\.\d{0,2})?|\.\d{1,2})\s*$
    ```

    - Commas must be proper thousands grouping, so a typo such as `12,34`
      cannot be read as $1,234 and overstate income.
    - At most 12 integer digits, which keeps integer cents exact.
  - **Special cases.**
    - Empty text means 0, as today.
    - Whitespace-only text also means 0. This is a change: today it keeps the
      last value.
    - A lone `.` is an entry in progress: it keeps the last valid value and
      shows no error, as today.
  - Anything else shows the inline message "Enter a dollar amount, up to 2
    decimal places". The field keeps the user's text.
  - **Accepted:** `1,234.56`, `12.`, `.5`, `0`, and `12` with leading and
    trailing spaces.
  - **Rejected:** `1.234`, `-5`, `1e5`, `Infinity`, `NaN`, `12.3.4`, `$12`,
    `12,34`, `1,2`, and a 13-digit dollar amount.
  - Parse valid input to integer cents from the text, after stripping commas
    and whitespace, never through `parseFloat` (`.5` is 50 cents, `12.` is
    1200).
  - These cases are F6 test vectors.
  - Allocation fields: clamp numbers outside 0–100, as today. Empty or
    non-numeric text shows "Enter 0–100" instead of silently becoming 0.
  - While any input is invalid, the results area shows the error card
    `Error: Fix the highlighted inputs.`, and the QIF download is disabled.
  - Both engine entry points (§6.3) also throw on non-finite or negative
    incomes, on allocations outside 0–100, and when a component lacks the
    selected filing status. The UI shows that as the error card. It never
    yields a silent 0.

### 6.3 Engine (`engine.js`): a faithful port

Port `taxkit/engine.py` exactly, keeping the order of operations.

**`applyBrackets(taxable, brackets)`**
1. `cap = up_to ?? taxable`.
2. If `taxable > prev_cap`:
   1. `slice = min(taxable, cap) − prev_cap`.
   2. Add `slice × rate` only if `slice > 0`.
   3. Set `prev_cap = cap`, still inside this branch.
3. Break when `up_to` is null or `taxable <= cap`.
4. Return `max(tax, 0)`.

**`computeTax(input, rules, filingStatus)`**
1. For each enabled component:
   1. Add up its `applies_to` income classes.
   2. Subtract its standard deduction, flooring at 0.
   3. Apply its brackets.
2. Credits: port the whole loop.
   - `amount` defaults to 0.0.
   - Keep the `amount_per_child` placeholder (one child).
   - The phaseout uses the input's own total income: earned plus unearned
     *as passed to this call*, which for a state is already allocated.
   - Keep `refundable_cap`.
3. Return `max(0, base − credits)`.

**Two entry points**
- **`computeAnnual(earned, unearned, filingStatus, year, states, rules)`**
  takes monthly incomes as dollar doubles: any finite, non-negative value,
  not necessarily whole cents. It returns each
  jurisdiction's raw annual tax. This is the Python-parity surface; the §9.1
  fixture calls it directly, including with incomes that are not whole cents,
  such as annualized bracket boundaries.
- **`computeMonthly(input, rules)`** is what the UI calls.
  - `input` is `{earnedCents, unearnedCents, filingStatus, year, states}`,
    with incomes as integer cents.
  - It calls `computeAnnual(earnedCents / 100, unearnedCents / 100, …)`. For a
    whole-cent input, `n / 100` is correctly rounded, so it equals the double
    Python parses from the same text.
  - It returns `federal_cents`, `state_cents`, `total_monthly_cents`,
    `gross_cents`, `net_cents` and `effective_rate`.
  - It never reconstructs cents from doubles.

**Composition** (port of `/api/compute`)
- Federal input: `earned×12`, `unearned×12`.
- State input: `earned×12×factor`, `unearned×12×factor`, evaluated left to
  right, where `factor = allocation_pct / 100`.
- `federal_annual` and each state's `annual` are the raw, unrounded
  `computeTax` results.
- Each jurisdiction's monthly amount is `ceilCents(annual / 12)` (§6.4): an
  integer number of cents, rounded **up** (D6).
- `total_monthly_cents = federal_cents + Σ state_cents`. Integer arithmetic is
  exact, so no further rounding applies.
- `gross_cents` is the exact integer sum of the two income inputs (F6).
- `effective_rate` is computed from what is actually charged,
  `total_monthly_cents / gross_cents × 100`, rounded **up** to two decimal
  places with `ceilScaled` when `gross_cents > 0`; otherwise 0. It is printed
  without trailing zeros, as today (`24.5`, not `24.50`). This replaces today's ratio of raw annual totals; neither
  `total_annual` nor Python's float `sum()` is needed any more.

### 6.4 Rounding toward the safe side (load-bearing, D6)

**The rule.** Ask what the consequence of each displayed figure being wrong
would be, and round so the error is harmless.

| Figure | Direction | Why |
|---|---|---|
| Tax amounts: each jurisdiction's monthly tax, the total, QIF amounts, export cells and schedule base amounts | **Up** to the next whole cent ($3.121 → $3.13) | Overpaying is fine; underpaying is not. |
| Tax rates shown: card sublabels and the combined rate | **Up** to the displayed precision | Never understate the burden. |
| Gross income | Not rounded | Inputs are whole cents (F6). |
| Net income | Never overstated | Exact gross cents minus rounded-up tax. |
| Rule data in the schedule: rates, deductions, thresholds | Printed exactly | They are inputs, not results (§7.1). |

Amounts that are already exact at the displayed precision stay unchanged. Tax
amounts are never negative.

**The float-noise problem.** `annual / 12 × 100` is a double. A value that is
mathematically a whole number of cents can land a hair above it, such as
`313.00000000000006`, and a naive `Math.ceil` would add a spurious cent.

**`ceilScaled(x, scale)`** returns `x × scale` rounded up to an integer.
There is one implementation, and every round-up uses it:
`ceilCents(x) = ceilScaled(x, 100)`, and the percentages use scale 10 or 100.
1. Throw if `x` is not finite or is negative. Validation (F6) makes both
   impossible in normal use. This never yields a silent 0.
2. Let `c = x × scale` and `r = Math.round(c)`.
3. If `|c − r| ≤ 1e-6`, return `r`. Within a millionth of a unit, the value is
   a whole unit plus float noise.
4. Otherwise return `Math.ceil(c)`.

**Tolerance tradeoff.**
- For monthly amounts under $1 million, double rounding error stays more than
  an order of magnitude below the 1e-6-cent tolerance.
- **Real fractions.** A true fraction of at most a millionth of a unit is
  treated as noise and dropped, which understates by at most $0.00000001.
  "Exact" in this spec means the computed double, so every result is at least
  that value minus 1e-6 of a unit.
- **Large incomes.** Above $1 million a month, noise may exceed the tolerance
  and add one spurious cent. That can only overstate tax.

**Test vectors** (`x` is a plain dollar input):

| `x` | cents | Note |
|---|---|---|
| `3.121` | `313` | Rounds up. |
| `3.13` | `313` | Already whole; `3.13 × 100` is exactly `313`. |
| `1.1` | `110` | `1.1 × 100` is `110.00000000000001`; naive `Math.ceil` gives `111`. |
| `0.07` | `7` | `0.07 × 100` is `7.000000000000001`; naive `Math.ceil` gives `8`. |
| `0.001` | `1` | A tenth of a cent still rounds up. |
| `1e-9` | `0` | Below the tolerance, so treated as noise. |
| `0` | `0` | |
| `1234.565` | `123457` | |

**Percentage vectors** (`ceilScaled` plus display formatting):

| Value | Scale | Result | Shown |
|---|---|---|---|
| `100/3` | 10 | `334` | `33.4` (card sublabel) |
| `100/3` | 100 | `3334` | `33.34` (combined rate) |
| `24.5` | 100 | `2450` | `24.5` (no trailing zero) |
| `24` | 100 | `2400` | `24` |
| `0.07 × 100` | 100 | `700` | `7` (float noise not bumped) |

**Formatting cents.** Display, CSV and QIF format integer cents as
`{dollars}.{two-digit cents}` (with grouping only where §6.1 shows it), never
through float division and `toFixed`.

**QIF amounts.**
- The expense line is the amount prefixed with `-`, and the transfer line is
  the amount unsigned.
- A zero amount therefore gives `T-0.00` and `T0.00`, as today's Python output
  does.

**Percentages** round up with `ceilScaled`, as defined in §6.1 and §6.3.

### 6.5 QIF builder (port of `taxkit/qif.py`)

**Layout**
- Lines are joined by `\n`, with no trailing newline.
- The file starts with `!Type:Bank`.
- Then one federal expense/transfer pair, then one pair per state in result
  order.
- Each transaction has these lines: `D` (`MM/DD/YY`), `T`, `P`, `M`, `L`, `^`.
- The memo is `{label} - MM/DD/YYYY`.
- State labels include the code only when there are two or more states:
  `Estimated {CODE} State taxes`, otherwise `Estimated State taxes`.

**Date**
- Parse the `<input type="date">` value as local date parts. Never construct it
  through UTC.
- The default is the local today (F1).
- An empty or invalid date disables the download. Today it downloads the
  server's 422 error JSON as the `.qif` file.

**Download:** `tax_transactions.qif`, MIME `application/qif`, via a Blob.

### 6.6 Persistence

- **Selected states.** The initial selection comes from the first valid source:
  1. browser storage key `tax2:selected-states`, filtered to known codes and
     non-empty;
  2. `config.default_states`, filtered the same way;
  3. the first discovered state.

  Every selection change writes `tax2:selected-states`.
- **Theme.** Stored under `tax2:theme`. The old `tax2-dark-mode` key belonged
  to the `http://127.0.0.1:8000` origin and cannot be read from `file://`, so
  there is no migration.
- **Robustness.** Wrap every storage access in try/catch. The page must work
  without storage.

## 7. Exports for manual backup and lookup

Both exports come from `engine.js`, using the same `applyBrackets` and
`computeTax` code as the calculator.

**Placement**
- Two buttons in the export panel: **Download rate schedule** and **Download
  lookup table**.
- They depend only on the selected year and filing status. They stay enabled
  while the income or state inputs are invalid or erroring.

**Why one dimension is enough.** Each component taxes only the sum of its
`applies_to` income classes. A jurisdiction's tax is therefore a sum of
one-variable pieces, keyed by total income, earned income only, or unearned
income only. No export needs an earned × unearned grid.

**Caveats.** The schedule prints these. The CSV stays machine-readable, so its
caveats and lookup procedure go in the README (§7.2, §8).
- **Rounding.** Every amount rounds **up** to the next cent. The calculator
  rounds each jurisdiction's monthly amount up once. Lookup columns and
  schedule components are rounded up individually, so a manual total can
  exceed the calculator's by a few cents. Followed as written, the procedures
  in §7.1 and §7.2 never give a lower figure, except for interpolation across
  a bend in the tax curve (§7.2).
- **Allocation.** Lookups apply no state allocation; multiply income by the
  allocation first.
- **Federal.** Federal tax is computed on total income, unallocated.
- **Not modelled:** preferential rates on qualified dividends and long-term
  capital gains, the net investment income tax, and FICA and self-employment
  tax.
- **Credits.** Credits subtract from a jurisdiction's total and floor at zero,
  which couples the pieces. No rules file has credits today.
  - When credits exist, apply them in the total-income column and section.
  - Apply the zero floor per column.
  - If the jurisdiction has no total-income component, omit its credits from
    the exports and say so in the schedule. Omitting a credit overestimates
    tax, which is the safe side.
  - Mark that jurisdiction's lookups as approximate.

### 7.1 Rate schedule (Markdown, S6)

File name: `tax2_rate_schedule_{year}.md`.

**Header and procedure**
- Title, build time, rules year, a "not tax advice" line, and the caveats.
- The manual procedure:
  1. Multiply monthly income by 12.
  2. For a state, multiply by its allocation.
  3. Subtract the component's standard deduction, flooring at 0.
  4. Find the bracket and apply its formula.
  5. Divide by 12 and round **up** to the next cent.
  6. Add the components.

**Sections**
- Order: federal first, then states with rules for the year, alphabetically.
- For each enabled component and each filing status:
  - the label, or the component `name` when there is no label;
  - the income it applies to;
  - the standard deduction;
  - a bracket table with the columns Over, But not over, and
    `Tax = base + rate × excess over`. A bracket's base is
    `applyBrackets(its lower bound, brackets)`, shown rounded up with
    `ceilCents`.
- List disabled components as "disabled — not included". List credits if
  present.

**Formatting**
- **Rates** print exactly as percentages. Take the rule value's shortest
  decimal string and move the decimal point two places, with no float
  multiplication (`0.0307` gives `3.07%`, never `3.0700000000000003%`).
- **Standard deductions and bracket thresholds** print exactly, at full
  precision from the rule value, with grouping.
- **Computed money** (bracket base amounts) is rounded up with `ceilCents`
  and shown with two decimals and grouping.

### 7.2 Income-step lookup table (CSV, S6)

File name: `tax2_lookup_{year}_{filing_status}.csv`.

**Rows and columns**
- Rows: `MonthlyIncome` from 0 to 500,000 in steps of 50, matching today's
  `generate_table` defaults.
- Columns: `MonthlyIncome`, then one column per jurisdiction and income basis
  that has enabled components.
  - Jurisdictions: federal first, then every state with rules for the year,
    alphabetically. Not only the selected states.
  - Within each jurisdiction, the bases in this order: total, earned-only,
    unearned-only.
- Headers name the basis, for example:
  - `Federal monthly tax (total income)`
  - `PA monthly tax (total income)`
  - `PA monthly tax (earned income only)`

**Cells**
- Each cell is `ceilCents(A / 12)`, formatted from cents. `A` is the summed
  annual tax of the group's components at an annual income of
  `MonthlyIncome × 12`, after the credit and zero-floor steps below. `A` is
  floored at zero **before** `ceilCents`.
  - In a total-income column, subtract the jurisdiction's credits, with the
    phaseout evaluated at that income.
  - Floor every column at zero (§7 Credits).
- This matches the calculator's monthly rounding (D6). It replaces today's
  nearest-cent `round(tax_annual / 12.0, 2)`. No allocation is applied.
- Numbers are plain: two decimals, no grouping.

**Manual lookup procedure** (for the README, with the §7 caveats):
1. For a state, multiply monthly income by its allocation.
2. Find the matching income in each of the jurisdiction's columns:
   - total income for "total income" columns;
   - earned income for "earned income only" columns;
   - unearned income for "unearned income only" columns.
3. Add the columns.

**Incomes between rows.**
- Interpolate linearly between the two surrounding rows and round the result
  **up** to the next cent.
  - Tax is piecewise linear in income. Within a straight segment, the result
    is never below the calculator's and at most about 2 cents above it per
    column: the cells are already rounded up, and the interpolated value
    rounds up again.
- **Bends.** The segment bends at each standard-deduction threshold, each
  bracket boundary (in gross monthly terms: `(standard deduction + up_to) / 12`),
  and any credit phaseout or cap point. When one of those falls inside the $50
  step, interpolation is approximate. Across a bend where the rate drops (such
  as the end of a credit phaseout), it can **underestimate**. Use the rate
  schedule for an exact figure there.
- **Next row up.** To skip interpolation and still never underestimate, use
  the next row up. This works because tax never falls as income rises, which
  S4 guarantees by rejecting negative rates. Above 500,000 there is no next
  row; use the schedule.
- Using the nearest row without interpolating can be off by up to
  $25 × the marginal rate per month in each column (about $9.25 at 37%). A
  total across several columns can be off by more.

**EIT.** The columns reflect exactly what the calculator includes. Enabling PA
local EIT in the YAML and rebuilding adds its earned-only column; today's
tables silently omit it.

## 8. Documentation changes

**tax2 project docs**
- **`tax2/README.md`:** rewrite.
  - Cover the launcher contract, the offline boundary (§1), runtime files, the
    page, QIF, both exports with the manual lookup procedure and caveats, the
    rules model, the layout and tests.
  - Reword the QIF compatibility sentence without naming md-autotax. The
    single-state Georgia text compatibility itself stays.
  - Remove the server, CDN, Tailwind, React, browser-floor and
    table-generation material.
- **`tax2/docs/Usage.md`:** same scope.
- **`tax2/docs/multi_state_design.md`:**
  - Update "State discovery and API", "Lookup tables" and "Runtime
    preferences" to describe the payload, the exports and persistence.
  - Update "Income and allocation model", which mentions `TaxInput` and rules
    mode.
  - In "Compatibility invariants", remove the invariant that state-specific
    combined CSVs keep their three-column schema, and update the closing
    sentence that names API and CLI tests. Keep the other invariants.
- **`tax2/docs/UI_Design_Reference.html`:** leave unchanged as the visual
  reference.

**Repository docs**
- **Root `README.md`:** update the `tax2` line in "Projects At A Glance" and
  the tax2 entry under "Notable Utilities".
- **`agents.md` Validation Matrix, `tax2` entry:** replace the server-start and
  `generate-combined` steps with:
  - `.venv/bin/python -m pytest`;
  - `UV_PYTHON_DOWNLOADS=never ./tax2 --help`;
  - `UV_PYTHON_DOWNLOADS=never TAX2_HOME=<tmp> ./tax2 --no-browser --output <tmp>/tax2.html`, then confirm the file exists with mode 0600;
  - after any rules change, the bundled-rules tests (§9.2).
- **`docs/local_deployment_sync.md`:** replace "Tax2 generated CSV/Parquet
  tables and `~/.tax2/config.json`" with today's local-only files:
  `~/.tax2/config.yaml` and `~/.tax2/tax2.html`.
- **Dated audit documents in `docs/`:** leave unchanged.

## 9. Testing and parity

### 9.1 Python oracle: capture before retiring anything

Before deleting the Python engine, capture a parity fixture from the current
code.

**Frozen rules**
- **Bundled copy.** Copy the bundled `rules/` tree as it stands at capture time
  into `tax2/tests/fixtures/parity/bundled/rules/`. Keep every number and
  structure unchanged.
- **Public-repo rule for both frozen roots.** Labels and comments must stay
  generic or conspicuously synthetic, and must never name a municipality,
  school district or tax-district code. The bundled PA `local_eit` label and
  comment were genericized on 2026-10-08. Labels and comments affect no
  computed value.
- **Synthetic root.** Create `tax2/tests/fixtures/parity/synthetic/rules/`, a
  separate root, with:
  - `federal/2026.yaml`, copied from the bundled rules;
  - `states/PA/2026.yaml`, a copy with local EIT **enabled**;
  - `states/XU/2026.yaml`, an invented state with an unearned-only component;
  - `states/XC/2026.yaml`, an invented state with a credit that has a phaseout
    and a `refundable_cap`.

  The two roots never share a state directory, so the EIT-disabled and
  EIT-enabled PA cases both survive.
- Parity always runs against these frozen copies. Later corrections to the
  bundled rules never invalidate the oracle.

**Fixture**
- `tax2/tests/fixtures/parity/python_parity.json`, built from synthetic,
  conspicuously round values.
- It records the generator's commit SHA and the exact CPython version used.

**Generator**
- Load the launcher with `load_launcher`.
- Point `_base_dir` at the directory that contains each `rules/`:
  `tax2/tests/fixtures/parity/bundled/` or `.../synthetic/`.
- Set `TAX2_HOME` to a temporary directory, because `/api/compute` calls
  `load_config`, which writes the config.
- Call the `/api/compute` handler and `build_qif_entries`.
- Compute each case's expected rounded-up monthly cents with a Python
  reference implementation of §6.4 (`c = (annual / 12.0) * 100.0`, using the
  same tolerance rule).
  - It performs the same double operations as the JavaScript. It therefore
    checks that the JavaScript matches the spec, not that the spec is right.
  - The generator also asserts these invariants for every case:
    - the cents are at least the nearest-cent cents;
    - `cents − c` lies in [−1e-6, 1).
- Build the expected QIF text with `build_qif_entries`, passing those cents
  divided by 100.
- Delete the generator in the same change that retires the engine.

**Cases**
- Every year in each frozen root, with both filing statuses.
- Bundled root: federal plus GA, PA, and GA+PA, with allocations 100/100,
  50/100, 33.33/100 and 0/100.
- Synthetic root: PA, XU and XC, each alone at 100% and all three together at
  100/100/100 and 50/33.33/100.
- The missing-state-year error, recording its `detail` text, for example PA in
  2025. That message is the only error-text parity target. Today's 422
  validation errors are replaced on purpose by F6 and are covered by F6 tests.
- Earned/unearned splits: all unearned, all earned, and mixed.
- Incomes:
  - zero;
  - below the standard deduction;
  - exactly on each federal bracket boundary (annualized), and one dollar
    either side;
  - large.
- Rounding coverage among the compute cases, each enforced by a generator
  assertion:
  - at least one annual tax that divides to a whole number of cents (GA
    2443.2/12 = 203.60 and PA 1842/12 = 153.50 are examples);
  - at least one monthly value that differs from Python's nearest-cent
    `round(annual / 12, 2)`, which proves the fixture catches a
    round-to-nearest port;
  - at least one value with `c ≠ round(c)` and `|c − round(c)| ≤ 1e-6`, which
    proves the fixture catches a port that uses plain `Math.ceil`.
  - If the enumerated cases do not satisfy an assertion, add cases until it
    holds.
- The §6.4 vectors are separate `ceilScaled` unit tests, not compute cases.
  They cover scale 100 and the percentage scales.
- QIF text for:
  - single-state GA computed from income, with rounded-up amounts;
  - GA+PA;
  - a zero-amount state;
  - custom labels.
- The existing goldens in `test_golden_baselines.py` and `test_api.py` must
  agree with the fixture on annual values.
- Every hard-coded monthly, total or net expectation in `test_api.py` and
  `test_browser_smoke.py` moves to the D6 values. During planning, enumerate
  them all and record each old → new value. Examples:
  - the GA golden federal monthly 418.33 (annual 5020 / 12) becomes 418.34,
    and its total 621.93 becomes 621.94;
  - `test_api.py`'s 775.43 becomes 775.44;
  - the browser test's totals and net figures (for example 698.68 and
    4,378.07) change too.
- `test_golden_baselines.py`'s QIF golden passes fixed amounts (2345.67,
  512.34) straight to the QIF builder, so it stays byte-identical.

**Comparison**
- JSON round-trips doubles exactly, and the JavaScript port keeps Python's
  order of operations. Compare these for exact equality:
  - annual values (Python's oracle, unchanged semantics);
  - rounded-up monthly cents and total cents (the Python reference);
  - error text;
  - QIF text.
- Exclude `display_name` (changed on purpose by F5), and today's nearest-cent
  monthly values and effective rate (replaced on purpose by D6).
- The ported golden tests keep their annual expectations. Their monthly and
  QIF expectations move to the rounded-up values; record each changed value in
  the change that moves it.

### 9.2 Test suite after the port

**Dispositions of the current tests**

| Current test | Disposition |
|---|---|
| `test_rules_v2.py` | Keep. Add the S4 build-failure cases. |
| `test_config.py` | Keep. Adjust for the dropped `legacy_combined_alias`, create-if-missing, and 0600/atomic writes. |
| `test_golden_baselines.py`, `test_engine_components.py`, `test_qif_multistate.py` | Port to browser tests that call `window.Tax2Engine` via `page.evaluate`, run against the frozen bundled root. Compare with the unrounded fixture values exactly rather than reproducing `round(x, 10)`. Add the whole §9.1 parity fixture. |
| `test_api.py` | Replace each test with a page or payload test of the same scenario (list below). |
| `test_cli_tables.py` | Replace with export tests (below). |
| `test_browser_smoke.py` | Rewrite (below). Drop the Tailwind, React and import-map contracts. |

The `test_api.py` replacements:
- the states listing with QIF data, as a payload test;
- the GA golden;
- GA+PA both at 100 are independent;
- PA at 50%;
- state validation;
- multistate QIF.

**Export tests**
- CSV: header and column order, row count, and sample cells against the engine.
- Schedule: content, bases and the caveats.
- Building from the frozen synthetic root adds PA's earned-income-only column
  and its EIT schedule section.

**Rewritten browser smoke test.** It opens the built page from `file://` and:
- uses `guard_browser_errors`;
- routes every non-`file:` request to a test failure;
- covers:
  - recomputation on input change;
  - input validation (F6);
  - state-persistence precedence;
  - theme persistence;
  - allocation visibility (F3);
  - `qif_overrides` for states checked later (F2);
  - the local QIF date (F1);
  - net-income reconciliation;
  - a card's effective-rate sublabel and the combined rate rounded **up**, for
    inputs where nearest rounding would show a lower figure;
  - the error card and disabled QIF;
  - the export panel at a narrow width (F4);
  - the summary layout in both themes.

**Bundled-rules tests**
- A small set of tests builds from the bundled `rules/` and checks values a
  human can verify by hand, such as federal tax at a few incomes for each year.
- When the bundled rules change, the person changing them updates these
  expected values on purpose.

**Launcher tests** (`load_launcher`, `run_launcher`, `assert_launcher_help`)
- `--help` lists the flags.
- `--no-browser --output` writes a 0600 file, and the runtime home is 0700.
- A relative `--output` works.
- The payload round-trips, and `<` appears in its JSON only as the
  backslash-`u003c` escape.
- The page has no `http://` or `https://` script, link or `src` references.
- `--rules-dir` is honoured.
- Invalid rules exit 1 and name the file.
- A config containing `legacy_combined_alias` loads.
- An existing config is never rewritten.

**Repository checks**
- In `tools/check_uv_headers.py`, set the `tax2/tax2` policy's extras to
  `playwright` and `pytest`. `requirements-dev.txt` must mirror the header in
  both directions.
- Restructure or remove `requirements.txt`, which today exists for the CLI.
- Run the guard and `tools/tests/test_check_uv_headers.py`.

**Code to retire**
- `taxkit/__init__.py` currently imports `engine`, `qif` and `tablegen`; reduce
  it to the modules that remain.
- `utils.resolve_year`.
- `models.TaxInput`, if nothing uses it after the engine is gone.
- The `tables/` directory.
- In `tax2/.gitignore`, the `tables/*.parquet`, `tables/*.csv` and
  `.tax2_venv/` lines. Before deleting the working-tree directory, list any
  generated, ignored files under `tables/`.

**Exit gate:** the full tax2 suite, the uv header guard and its tests, and the
Validation Matrix tax2 commands from §8.

## 10. md-autotax removal

1. **Inventory first.** List the untracked and ignored files under
   `md-autotax/` before deleting anything. Today they are `venv/`,
   `__pycache__/`, `tests/__pycache__/`, and an ignored `.zshrc` of unknown
   content.
   - Show `.zshrc` to the user and delete it only with their confirmation.
   - If a private data file appears (`config.json`, `Tax-table.csv`,
     `*.local.csv`, `tax_entries_*.qif`), stop and ask.
2. Run `git rm -r md-autotax`, then remove the untracked leftovers. This
   removes all 13 tracked files, including `md-autotax/.gitignore`.
   - **Commit the whole removal, with steps 3–7, in a single commit before
     running any deployment check.** `tools/check_local_deployments.zsh` audits
     every tracked `**/.gitignore`. It fails with "tracked repository
     .gitignore source state is incomplete" while the deletion is staged but
     uncommitted, or while the directory is gone from disk but still in the
     index.
   - After the commit the audit is clean: `md-autotax` is not one of its
     deployed projects.
3. Root `.gitignore`: remove the five `md-autotax/...` lines (currently lines
   276–280).
4. Root `README.md`: remove the `md-autotax` line from "Projects At A Glance".
5. `agents.md`:
   - remove `md-autotax` from the Repo Shape list;
   - make the Streamlit Validation Matrix entry cover `transcription` only;
   - remove `md-autotax` from the `setup.sh` example list in Execution
     Guidance.
6. `docs/privacy_scrub_design.md`: remove the bullet
   "`~/.md-autotax/config.json` and its private tax table" (D7).
7. `tax2/README.md`: in this same commit, reword the QIF compatibility sentence
   (currently line 137) so it no longer names md-autotax. The rest of the
   README rewrite stays in §8. This keeps step 10's check true even when §10
   lands first.
8. Leave the dated audits unchanged:
   `docs/dependency_modernization_audit_2026_09_16.md` and
   `docs/cleanup_audit_20260916.md`.
9. Tell the user that `~/.md-autotax/` is their private runtime folder, outside
   the repository, and theirs to delete.
10. Verify by running `rg -n "md-autotax|md_autotax"`. Only the two dated
    audits and this spec may match.

## 11. Ordering constraints for the plan

- **Precondition:** the PA label genericization and this spec are committed
  before any plan task starts. On 2026-10-08 they exist only as uncommitted
  changes to `tax2/rules/states/PA/2026.yaml`, `tax2/tests/test_rules_v2.py`,
  `tax2/README.md`, `tax2/docs/Usage.md` and `tax2/docs/multi_state_design.md`.
  Otherwise a clean checkout would copy the old locality label into the §9.1
  frozen fixtures, and §10's README edit would mix with unrelated pending
  changes.
- §10 is independent and can land first.
- Capture and commit the §9.1 frozen rules and fixture **before** removing any
  Python engine, QIF or table code.
- Start the page work with a probe: inline the three vendored UMD files into a
  page, open it from `file://` in Playwright Chromium, and render an htm
  component with hooks. No project inlines them yet, so confirm this before
  building on it.
- Port `engine.js` and pass the parity tests before building the UI on it.
- Remove the server, the table code, the retired Python modules and the
  dependencies only after the page reaches parity.

## 12. Deployment

Tax2 is deployed as a home-project copy at `~/tax2`
(`docs/local_deployment_sync.md`). That copy procedure adds and updates
tracked files but never deletes.

**Remove retired files.** After the merge, besides syncing, remove from
`~/tax2` every tracked file the migration deleted. Back each one up first, and
remove them only with the user's approval.
- Derive the list from git, for example
  `git diff --diff-filter=D --name-only <deployed-commit>..HEAD -- tax2`.
- The list includes `cli.py`, `taxkit/engine.py`, `taxkit/tablegen.py`,
  `taxkit/qif.py`, `tables/*.parquet`, `requirements.txt` if removed, and the
  retired or renamed tests (`tests/test_api.py`, `tests/test_cli_tables.py`,
  and any ported test files that changed names).
- Stale tests would import the removed modules and break the deployed suite.

Old generated `~/tax2/tables/*.csv` files are local-only; the user decides
whether to keep them.

**Verify, in this order:**
1. Run `tools/check_local_deployments.zsh`. It reports formerly tracked files
   that remain in a deployed copy, so remove anything it reports for tax2.
2. Run `./tax2 --help` and a `--no-browser --output` build from `~/tax2`.
3. Run the deployed suite as the deployment document describes.

## 13. Acceptance criteria

- **Build.** With a warm uv cache and no network, `./tax2` writes
  `~/.tax2/tax2.html` (mode 0600, runtime home 0700) and opens it.
- **Offline page.** The page makes zero network requests and logs no errors.
  A previously built page opens offline without the launcher.
- **Parity.** Every §9.1 fixture case matches exactly: annual values match
  Python, and monthly cents, totals and QIF text match the rounded-up
  reference.
- **Rounding.** Each jurisdiction's monthly tax, QIF amount and CSV cell is at
  least its computed value minus 1e-6 cent and less than that value plus one
  cent (§6.4; "computed value" means the double). The total is exactly the sum
  of the jurisdiction amounts. Displayed tax rates are never below their
  computed values minus 1e-6 of a display unit. Gross income is exact, and net
  income equals exact gross minus the rounded-up total, so it is never
  overstated.
- **Exports.** The rate schedule and lookup CSV download for the selected year
  and status and match the engine. Enabling PA local EIT in a rules root adds
  its earned-only column and schedule section.
- **Fixes.** F1–F6 behave as specified.
- **Dependencies.** FastAPI, uvicorn, pandas, pyarrow, python-dateutil and
  typer are gone, and the uv header guard passes.
- **No leftovers.**
  - No table-mode, `generate-combined` or `combined_*.csv` code or docs remain,
    except in this spec and the dated audits.
  - `legacy_combined_alias` appears only in the config loader's ignore path, its
    compatibility test and this spec.
  - `md-autotax` appears only where §10.10 allows.
- **Tests.** The full tax2 suite and the updated Validation Matrix commands
  pass.
