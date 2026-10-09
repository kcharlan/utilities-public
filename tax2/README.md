# Tax2

Tax2 3.0 builds a private, self-contained estimated-tax calculator from federal and
state YAML rules. Open the resulting HTML file in a browser to calculate tax
and download QIF payments, a Markdown rate schedule, or a CSV lookup table.
All rules, scripts, styles and license notices are embedded; the page uses local
system fonts. It works offline without a server or frontend build step.

Bundled rules cover federal and Georgia tax for 2025 and 2026, and Pennsylvania
for 2026. Verify rates and eligibility before relying on estimates. See
[Usage](docs/Usage.md) for tax and lookup limitations, and
[multi-state design](docs/multi_state_design.md) for interfaces and invariants.

## Quick start

Install [uv](https://docs.astral.sh/uv/), then run from this directory:

```bash
UV_PYTHON_DOWNLOADS=never ./tax2
```

The launcher validates local rules, writes `~/.tax2/tax2.html`, opens its
`file://` URL, and exits. First use may need network access to resolve/cache
dependencies. With compatible Python and dependencies cached, offline rebuilds
work; opening an already-built page needs neither uv nor a network connection.
The launcher depends on pydantic and pyyaml. Network access may be needed again
after clearing the uv cache or changing dependencies.

```bash
UV_PYTHON_DOWNLOADS=never ./tax2 --help
UV_PYTHON_DOWNLOADS=never ./tax2 --no-browser
UV_PYTHON_DOWNLOADS=never ./tax2 --output "$HOME/.tax2/example.html"
UV_PYTHON_DOWNLOADS=never ./tax2 --rules-dir "$HOME/.tax2/rules"
UV_PYTHON_DOWNLOADS=never UV_OFFLINE=1 ./tax2 --no-browser
```

`TAX2_HOME` overrides the runtime home, whose directory has mode `0700`.
New config and built pages have mode `0600`. Pages are replaced atomically,
including explicit outputs. Help writes no files. Build failure preserves the
previous page; browser-opening failure warns, leaving the printed file available
to open manually.

Exit codes are 0 for success (including a browser-opening warning after writing),
1 for a fatal build or destination-safety error, and 2 for a command-line usage
error.

An unreadable or malformed existing config is not a build error. A config entry
that cannot be read or parsed (including a dangling link, a symlink loop or a
link chain through an inaccessible directory) warns
`Unable to read config.yaml; using defaults`; an existing non-mapping config
(including an empty YAML document) warns
`config.yaml is not a mapping; using defaults`. The warning is printed to stderr
once per build, the build continues with default preferences (exit 0 when
nothing else fails), and nothing is created or modified at the config entry or
its link targets (the runtime home itself still gets its usual `0700` mode).

`--output` rejects destinations that replace the config entry, any entry
in its symlink chain (including directory links and a symlinked `TAX2_HOME`),
or its final target, even if missing. Existing entries are compared by file
identity, so hard links to config or its target are rejected even though
replacing such a link would leave the protected file's other name intact.
Distinct existing files on a
case-sensitive volume remain allowed; when either entry is missing, names use
NFC normalization and Unicode case folding and parents use identity when both
exist, otherwise folded physical paths. This rule is conservative on
case-sensitive volumes: missing `CONFIG.yaml` conflicts with `config.yaml`,
missing `STRASSE.yaml` conflicts with a protected `Straße.yaml`, and differently
cased missing parent paths also conflict. These name checks cover missing,
existing and dangling-link targets. Unrelated outputs still build when config
has a loop or unreadable chain, with a config warning and defaults.
Utilities-public source checkouts are rejected, and Git-marked ancestry that
cannot be classified fails closed. An unrelated output leaf symlink is replaced
as an entry, without writing through it to its target.

Rerun after changing rules or config: browser refresh only reloads the snapshot.
No server restart is involved.
The page shows its UTC build timestamp; its initial tax year and transaction
date use the browser's local date when opened.

## Calculator and downloads

Enter monthly earned and unearned income, select a year and filing status,
and choose one or more independently allocated states. Federal uses full income
once; state allocations apply to both buckets before computation. Allocations
need not sum to 100%.

Monthly tax rounds up to cents once per jurisdiction. Total sums those cents,
and net subtracts them from gross cents; net can be negative. QIF uses the same
displayed amounts and is disabled for invalid inputs or missing selected-state
rules.

- `tax_transactions.qif`: federal expense/transfer pair, then selected-state
  pairs in selection order.
- `tax2_rate_schedule_YEAR.md`: selected year, both filing statuses, federal
  and every state with rules for that year.
- `tax2_lookup_YEAR_STATUS.csv`: selected year/status, income-basis columns
  for all available jurisdictions, monthly rows 0–500,000 in steps of 50.

Reference exports ignore calculator income, state selection and allocations;
they remain available when selected-state rules are missing. They are downloads,
never calculator inputs. Read their caveats: component rounding and credits can
make manual totals approximate.

A single-state Georgia export keeps the transaction text of earlier versions;
multi-state memos include the state code.

## Manual lookup

For CSV lookup, apply each state's allocation to both monthly income buckets
first; federal uses unallocated income. Look up combined income in total-income
columns, earned income in earned-only columns, and unearned income in
unearned-only columns, then add the applicable columns.

The rate schedule uses these seven steps:

1. Multiply monthly income by 12.
2. For a state, multiply earned and unearned income by its allocation first.
   Federal uses unallocated total income.
3. Use each component's income basis. Subtract its standard deduction,
   flooring taxable income at 0.
4. Find the bracket and apply its formula.
5. For a jurisdiction with credits, subtract them once from the annual tax of
   its total-income components, flooring at zero (see Credits).
6. Divide each component's annual tax (or the credited total-income section's)
   by 12 and round up to the next cent.
7. Add the results.

The calculator rounds once per jurisdiction. Individually rounded schedule
components or lookup columns can overstate manual totals by a few cents.
Credits couple components: lookups subtract them only in the total-income
column and floor each column at zero, so credited jurisdictions are approximate.
When no enabled total-income component exists, the rate schedule discloses
omitted credits, which overestimate tax; the calculator still credits the
jurisdiction's total.

Interpolate linearly between CSV rows, then round up to cents. Within a straight
segment this is conservative, potentially adding about two cents per column.
The tax curve bends at deduction thresholds, bracket boundaries
`(standard deduction + up_to) / 12`, credit phaseouts and caps. Interpolating
across a bend where the marginal rate drops can underestimate. Use the schedule
for an exact rules calculation, or use the next row up to avoid underestimating
between rows: accepted nonnegative rates and valid credits make tax
nondecreasing. Above 500,000 monthly income, use the schedule. Nearest-row lookup
without interpolation can differ by $25 × the marginal rate per month per
column (about $9.25 at 37%); summed errors can be larger.

Federal treats both income buckets as ordinary income. Qualified-dividend and
long-term capital-gain rates, NIIT, FICA and self-employment tax are not modelled.

## Preferences and rules

`~/.tax2/config.yaml` (or `$TAX2_HOME/config.yaml`) holds hand-edited
`default_states` and nested `qif_overrides`. Tax2 creates defaults only when
missing and reads existing config without rewriting it. Optional `tax2:`
browser-storage keys save theme and state selection; a valid saved selection
wins over config. Browser interactions never write config or rules.
An existing non-mapping config (including an empty YAML document) warns
`config.yaml is not a mapping; using defaults`, uses defaults and remains untouched.

Add `rules/federal/YEAR.yaml` or `rules/states/STATE/YEAR.yaml`, or supply a
private `--rules-dir`, then rebuild. Use generic locality labels in this public
repo. Pennsylvania's earned-only local EIT is disabled by default; set the
applicable rate before enabling it and rerun.

## Project layout

```text
tax2                  uv-managed built-page launcher
taxkit/               rules normalization, payload, private publication/config
web/engine.js         browser calculation and export builders
web/app.js            Preact/htm UI, browser preferences and downloads
web/vendor/           exact-version assets, provenance and licenses
rules/                federal and state YAML inputs
tests/                rules, launcher, parity, config, export and browser tests
docs/Usage.md         operating guide and tax limitations
docs/multi_state_design.md
                      maintained interfaces and invariants
```

## Development validation

Use the existing project `.venv`, or create it only if absent. On Homebrew
macOS (do not recreate an existing environment):

```bash
/opt/homebrew/bin/python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest
```

The complete suite includes offline Chromium interaction and all three real
downloads, parity, bundled expectations, and publication safety. Other browsers
require manual verification. After launcher-header changes, run from repo root:

```bash
uv run --no-python-downloads --script tools/check_uv_headers.py
```

For executable changes, also follow the private build, permissions and warmed
offline acceptance steps in the repository's Tax2 validation matrix.
