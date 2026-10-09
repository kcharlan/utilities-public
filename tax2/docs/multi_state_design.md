# Multi-State Tax Design

Status: implemented. Tax2 publishes a schema-1 rules snapshot to an offline
HTML page; browser JavaScript owns all interaction-dependent arithmetic.

## Goals and boundaries

The page estimates ordinary-income federal and selected-state tax offline.
Qualified-dividend and long-term capital-gain rates, NIIT, FICA and
self-employment tax are not modelled. Credits use the one-child placeholder
and do not implement full dependent eligibility or refunds. Pennsylvania Tax
Forgiveness, residency timelines, estimated-payment thresholds/due dates,
county property tax, local services tax and return-of-capital basis tracking
are omitted; see [Usage](Usage.md#tax-limitations) for rule-specific caveats.

Runtime config contains preferences only, never tax rates or locality rules;
those belong in YAML rules. Allocations are the caller's independent choice
and are never normalized to sum to 100%. Bundled federal rules depend on total
income, regardless of its earned/unearned split. Custom component rules still
honor each declared income basis through the generic engine.

## Runtime boundary and interfaces

`tax2` validates its output destination before private config access, then
`taxkit.page.build_payload(rules_root, rules_source=...)` validates every
numeric-year YAML file and assembles federal years, ordered states with
per-year rules/QIF metadata, build time, and recognized config preferences.
`render_page(payload)` escapes embedded JSON and inlines vendored Preact/htm,
application JavaScript, CSS and licenses. Publication is private and atomic.

There are no HTTP APIs, table-input files, Python interactive tax engine or
browser config writes. `web/engine.js` exposes `window.Tax2Engine`:

- `computeAnnual(earned, unearned, filingStatus, year, states, rules)` accepts
  monthly dollar values and selections `{code, allocation_pct}`; returns
  unrounded `federal_annual` and ordered states containing `annual`.
- `computeMonthly({earnedCents, unearnedCents, filingStatus, year, states}, rules)`
  accepts safe integer cents; returns `federal_cents`, state `state_cents`,
  `total_monthly_cents`, `gross_cents`, `net_cents` and `effective_rate`.
- `buildQif(result, qifConfig, qifStates, rules)`,
  `buildRateSchedule(year, rules)` and
  `buildLookupCsv(year, filingStatus, rules)` return download text.

`web/app.js` owns input editing, DOM, optional browser storage and Blob
downloads. Year/date defaults use local opening time; payload build time is UTC.

## Rules schema

`taxkit.rules_loader.load_rules` normalizes legacy top-level deduction/brackets
to one enabled component for both earned and unearned income. Mixing that shape
with `components` fails. Components contain generic name/label, enabled flag,
income basis, per-status deductions and brackets.

Every numeric-year YAML/YML validates before YAML precedence is applied.
Both offered statuses, nonempty components, and explicit deductions/nonempty
brackets per status are required even for disabled components. Income bases
contain earned, unearned or both without repetition; either order is preserved,
and omission defaults to both. All normalized numbers are finite; thresholds
are nonnegative and strictly ascending, with null only last. Bracket rates,
phaseout rates and non-null refundable caps are nonnegative. Deductions have
no additional restrictions. Zero-rate/all-disabled rules remain valid.
Roots require federal rules and at least one state with valid rules.

Federal/Georgia currently normalize legacy files; Pennsylvania 2026 uses
components for 3.07% state tax and disabled earned-only local EIT. Names are
identifiers, never jurisdiction-specific engine branches. Generic labels and
rates stay in YAML; private locality names/codes never enter this public repo.

## Income, credits and allocations

Annual arithmetic sums enabled components, applies jurisdiction credits once,
then floors tax at zero. Federal uses full combined income once. States allocate
both buckets before component deductions/brackets; full-income tax is never
prorated. Allocations default to 100%, range 0–100, and remain independent,
including two states at 100%. Finite UI values clamp; invalid inputs error.

Credits preserve the one-child placeholder and max semantics: greater of fixed
amount/per-child amount with zero floor, phaseout reduction with zero floor,
then refundable cap. These are approximate eligibility/refund semantics.

Inputs parse as cents. Each jurisdiction's monthly amount rounds up once via
`ceilCents`; scaled values within `1e-6` of an integer count as exact.
Total is the sum of jurisdiction cents; net is gross cents minus that sum and
may be negative. Rates also round upward. See [Usage](Usage.md) for exact input
grammar, blur behavior, tax omissions and lookup caveats.

## Discovery and missing years

States are discovered at build time from `rules/states/*/`. Numeric years and
latest rule display/QIF metadata enter the payload; empty-year directories
remain selectable metadata but do not satisfy the required valid-state minimum.
The selector uses federal years. Missing selected-state rules error without
substituting a year and disable QIF; reference exports remain available.

## QIF and reference exports

QIF has one bank header, federal expense/transfer once, then selected-state
pairs in selection order. It uses displayed cents. Fixed-amount Georgia
single-state text remains golden-compatible; multi-state memos include codes.
Dates and zero-expense text retain their established formats.

The Markdown schedule covers selected year/both statuses; CSV covers selected
year/status with rows 0–500,000 by 50. Both include federal then all states
available for that year, independent of calculator selections/allocations.
CSV columns group enabled components by total/earned-only/unearned-only basis.
Reference exports are never calculator inputs.

Manual component/column rounding can overstate totals. Lookup credits attach
only to total-income groups; absent such a group they are omitted with a
warning, overestimating tax. Credited lookups remain approximate. Interpolation
is conservative within straight segments but can underestimate across
falling-rate bends; next-row-up lookup is conservative under accepted rates/
credits. Use the schedule above 500,000 or for exact boundary calculations.

## Config, storage and publication

Missing `~/.tax2/config.yaml` (or `$TAX2_HOME/config.yaml`) is created privately
with `default_states: [GA]` and `qif_overrides: {}`. Existing config is read-only.
Override mappings normalize state keys and retain only string `state_expense`
and `state_transfer`. Malformed parts warn/fall back while valid siblings remain:
this is the adopted compatibility assumption. Obsolete alias preferences are
ignored. Corrupt/unreadable config is not overwritten.

A valid saved `tax2:selected-states` selection precedes config defaults, then
the first discovered state. `tax2:theme` stores theme; unavailable storage is
nonfatal. QIF defaults use override, YAML then generic fallback, both for later
initialized states and empty edits. Other calculator/QIF fields are session-only.

Runtime home is `0700`, new config/page files `0600`; page replacement is
atomic. Before config reads/writes, the physical-parent-plus-leaf gate protects
config entries/targets and checks all Git-marked ancestors for verified source
identity. Source/worktree/nested-source output is rejected; unclassifiable
Git-marked ancestry fails closed. Git is conditional on markers, so standalone
unmarked deployment/default home output works without it. Source identity uses
tracked files, not directory names or hard-coded paths.

## Compatibility and verification

Tests cover legacy normalization, exact annual parity against an independent
test oracle, bundled rule expectations, fixed-amount Georgia QIF text, independent
allocations, generic YAML components, intentional zero tax and negative net,
config/storage fallbacks, publication safety and offline Chromium downloads.
Bundled rules remain unchanged. Georgia 2025's historical federal-like
deductions are preserved for its fixture, not corrected silently. Pennsylvania
has only 2026 rules and its local EIT stays disabled until its placeholder rate
is deliberately edited and the page rebuilt.
