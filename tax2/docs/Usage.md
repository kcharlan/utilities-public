# Tax2 Usage Guide

## Build and open

Install [uv](https://docs.astral.sh/uv/), then run in the Tax2 directory:

```bash
UV_PYTHON_DOWNLOADS=never ./tax2
UV_PYTHON_DOWNLOADS=never ./tax2 --no-browser
UV_PYTHON_DOWNLOADS=never ./tax2 --output "$HOME/.tax2/example.html"
UV_PYTHON_DOWNLOADS=never ./tax2 --rules-dir "$HOME/.tax2/rules"
UV_PYTHON_DOWNLOADS=never ./tax2 --help
```

The launcher validates local rules, embeds them and all browser assets in one
HTML file, opens it from `file://`, and exits. `--no-browser` suppresses opening;
`--output` changes the destination; `--rules-dir` selects a root containing
`federal/` and `states/`. The default rules root is beside the launcher.
Help writes no files. Usage errors exit 2; fatal builds exit 1; success exits 0,
including when browser opening warns and fails. Open the printed path manually
if necessary.

First use may need the network for uv resolution/cache population. With
compatible Python and dependencies already cached, rebuild offline:

```bash
UV_PYTHON_DOWNLOADS=never UV_OFFLINE=1 ./tax2 --no-browser
```

This warmed-cache boundary concerns the launcher. The built page embeds scripts,
styles, rules and licenses and uses local system fonts. It makes no external
requests and needs no Python process, server, CDN or network connection.

The default page is `~/.tax2/tax2.html`. `TAX2_HOME` changes the runtime home
and config location. The runtime directory is `0700`; new config/page files
are `0600`. Pages publish via a private same-directory temporary file and
atomic replacement. Failed building/publication preserves the previous page.
Explicit outputs use `0600`, but their parent is not automatically made private.

The page shows its UTC build timestamp. Rerun after editing rules or config;
refresh only reloads the snapshot. At opening, the year defaults to the browser's
local current year if federal rules exist, otherwise the latest federal year.
The initial QIF date uses the browser's local date independently of build time.

### Safe output destinations

Keep runtime files outside the public source checkout. Before reading or
creating config, Tax2 checks the output's resolved physical parent plus leaf
name, without following an output leaf symlink. It protects the config entry,
all symlink entries along its resolution chain (including directory links and
a symlinked runtime home), and the final target even when missing. Identity
checks reject hard links; missing names use conservative Unicode case folding
even on case-sensitive volumes. See the [launcher contract](../README.md#quick-start)
for examples. An output symlink is replaced
as an entry rather than used to overwrite its target.

Every physical ancestor with a `.git` marker is classified by bounded,
read-only Git identity checks. Verified utilities source checkouts, including
worktrees and nested source ancestors, are rejected. Unclassifiable Git-marked
ancestry also fails closed before private state access. Classification uses
tracked source identity rather than names or hard-coded home paths. Git is
required only for Git-marked ancestry; default home output and standalone
deployment directories without markers work without Git.

## Calculate estimated tax

1. Choose year and **Single** or **Married Filing Jointly**.
2. Enter monthly unearned and earned income separately.
3. Select at least one state and set each allocation.
4. Read federal/state estimates, **Total Monthly Tax**, and **Net Monthly Income**.

The browser immediately calculates from embedded rules. Federal uses full
income once. Each state applies its allocation to both buckets before annual
computation, rather than prorating full-income tax. Allocations default to 100%,
are independent, and need not sum to 100%; two states at 100% are valid.
Finite allocation inputs clamp to 0–100. Empty or non-finite inputs show an error.

Money accepts surrounding whitespace, 1–12 ungrouped digits, or a leading group
of 1–3 digits followed by 1–3 comma groups of exactly three digits. An optional
decimal point may have zero, one or two fractional digits; `.5` and `.50` also
work. Empty input means zero. Signs, currency symbols, exponent notation,
malformed commas and more than two fractional digits are rejected. Parsing
produces whole cents. A lone `.` is an in-progress edit that retains the previous
cents and restores their formatted value on blur. Other invalid text stays
visible on blur with its error; results and QIF remain unavailable until fixed.

Monthly tax rounds up once per jurisdiction to cents. The shared helper treats
scaled values within `1e-6` of an integer as exact to avoid floating-point noise
at cent boundaries. Total sums integer cents; net subtracts them from gross
cents, so tax rounding never overstates net. Rates round up to one decimal on
jurisdiction cards and two on the combined rate. Net may be negative and is
never an additional QIF transaction.

Years reflect federal availability, not the intersection of state years.
A missing selected-state year reports available years and disables QIF.
Pennsylvania has only 2026 rules. A federal-only year still permits reference
exports; these do not depend on selected states or valid income.

## Download QIF

Set transaction date, payee, federal categories/accounts and each state's
categories/accounts. **Download QIF** writes `tax_transactions.qif` using the
displayed cents, with one `!Type:Bank` header, then:

1. a negative federal expense and matching positive transfer;
2. a negative expense and matching positive transfer per selected state, in
   selection order.

Dates use `MM/DD/YY` on date lines and `MM/DD/YYYY` in memos. A fixed-amount
single-state Georgia export preserves captured golden transaction text;
multi-state memos include state codes. Zero expenses retain `T-0.00`.
An invalid calendar date disables QIF independently of calculation validity.

State defaults use config overrides, then YAML `qif`, then generic fallback
strings. This applies whenever a state is first initialized, including states
checked later. Empty edits fall back through the same chain when exporting.

## Download reference tables

**Download rate schedule** writes `tax2_rate_schedule_YEAR.md` for the selected
year, both statuses, federal and every state with that year's rules. It lists
income bases, deductions, brackets, computed bracket bases, disabled components
and credits. Rule numbers retain full normalized precision; computed bases
round up to cents.

**Download lookup table** writes `tax2_lookup_YEAR_STATUS.csv` for the selected
year/status (`single` or `married_joint`). `MonthlyIncome` runs from 0 through
500,000 in steps of 50. Other columns group enabled components by jurisdiction
and basis: **total income**, **earned income only**, **unearned income only**.
Components sharing a basis sum within the column. Federal precedes states
ordered by code.

Both exports cover all available jurisdictions regardless of UI state selection,
income or allocation. No allocation is embedded. They remain available during
calculator errors when year/status are valid. They are reference downloads;
there is no table-input or table-calculation mode.

### Manual use and approximation boundaries

See [Manual lookup](../README.md#manual-lookup) for the procedure and approximation boundaries.

## Hand-edit preferences

Tax2 creates missing `$TAX2_HOME/config.yaml` (default `~/.tax2/config.yaml`):

```yaml
default_states:
  - GA
qif_overrides: {}
```

Overrides are nested mappings by state code, with only string `state_expense`
and `state_transfer` fields. Synthetic example:

```yaml
qif_overrides:
  GA:
    state_expense: "SYNTHETIC:Example Tax Category"
    state_transfer: "[SYNTHETIC Example Transfer]"
```

Override keys are stripped and uppercased. Unknown fields are omitted.
Malformed containers, entries or recognized leaves warn and fall back while
valid siblings survive. This warning/fallback policy is the adopted
compatibility assumption for malformed overrides. Corrupt or unreadable config
warns and uses in-memory defaults without overwriting the file. Existing config
is read-only to Tax2; obsolete alias preferences are ignored.
An existing non-mapping document, including empty YAML, warns
`config.yaml is not a mapping; using defaults`; it is not rewritten. Missing config
is created with defaults without this warning.

Optional storage saves `tax2:theme` and `tax2:selected-states`. A valid nonempty
saved selection wins over known config defaults, then the first discovered
state is the fallback. Clear the saved selection to apply edited defaults after
rebuilding. Blocked/malformed storage falls back gracefully. Income, allocation,
year, status, date and QIF edits are page-session state. The browser never updates
config.

## Add or change rules

Create `rules/federal/YEAR.yaml` or `rules/states/STATE/YEAR.yaml`, or matching
structure under a private `--rules-dir`, then rebuild. Legacy top-level
`standard_deduction`/`brackets` normalize to one enabled component for both
income classes. Alternatively use `components`; mixing shapes fails. Generic
labels and rates remain YAML data without jurisdiction-specific engine branches.

Every numeric-year `.yaml` and `.yml` validates, including older and shadowed
files; `.yaml` wins only after both validate. Both filing statuses are required,
with nonempty components and explicit deductions/nonempty brackets for each
status in every component, including disabled components. Basis must be earned,
unearned or both without repetition; omission defaults to both. All normalized
numbers must be finite. Non-null thresholds are nonnegative and strictly
ascending; null may appear only last. Bracket rates, phaseout rates and non-null
refundable caps must be nonnegative. Deductions have no additional restriction.
Intentional zero-rate and all-disabled rules remain valid. A root needs a
federal year and a state directory with valid rules; empty-year states remain
listed. Invalid files fail with their filename, preserving the old page.

Use generic locality labels such as `Local EIT` in this public repo, never
municipality/school-district names or tax-district codes. Keep private rules
and runtime outputs outside the checkout.

## Tax limitations

Federal treats both buckets as ordinary income. Preferential qualified-dividend
and long-term capital-gain rates, NIIT, FICA and self-employment tax are omitted.
Credits retain a one-child placeholder: take the greater of fixed and per-child
amount, floored at zero, reduce for phaseout, then apply the refundable cap.
Tax is floored at zero; this is not a full dependent-eligibility/refund model.

Pennsylvania 2026 uses flat 3.07% personal income tax without a standard
deduction and does not distinguish qualified from ordinary dividends. Local
EIT is earned-only, disabled by default and has a placeholder rate; set the
applicable resident rate before enabling and rerun. Exclude return of capital
until basis is exhausted, then enter it as gain; Tax2 does not track basis.
Tax Forgiveness, residency timelines, estimated-payment thresholds/due dates,
county property tax and local services tax are omitted.

Georgia 2025 retains federal-like deductions rather than Georgia's 2025
deductions to preserve its historical regression fixture. Verify rules before
use. For unexpected results, check build time, year/status, income basis,
allocations and applicable YAML, then rebuild.
