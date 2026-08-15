# Per-Field Pricing Units Design

Status: approved approach; implementation pending written-spec review.

## Problem

Model Sentinel currently assumes that every monetary field returned by one
provider uses the same source unit. A provider configuration supplies one
`PRICE_MULTIPLIER` and `PRICE_DIVISOR`, and every numeric field classified as a
price is converted with that pair and displayed with the unit `/1M`.

That assumption is false for OpenRouter's pricing object. Token prices such as
`pricing.prompt` and `pricing.completion` are costs per token, while
`pricing.web_search` is a cost per web-search operation,
`pricing.request` is a fixed cost per API request, and `pricing.image` is a
cost per image input. With OpenRouter's provider-wide multiplier of 1,000,000,
a raw web-search price of `0.014` is therefore rendered as `$14,000 /1M`
instead of a search-denominated rate.

The same architectural limitation prevents a correct registered Abacus
profile: its model catalog contains token, image, audio, video, duration, and
other monetary rates that cannot share one conversion or unit label.

## Goals

1. Resolve monetary conversion and unit metadata per raw provider field.
2. Render OpenRouter token, search, request, and image prices in truthful,
   explicit units across every human-readable report surface.
3. Preserve raw provider values, raw field paths, JSON output, stored metadata,
   and historical change records.
4. Preserve the existing provider-profile boundary: provider vocabulary and
   interpretation belong in `ProviderProfile`, not generic renderers.
5. Reuse one resolved rule through classification, formatting, tooltips, and
   impact calculations so report surfaces cannot disagree.
6. Prevent absolute-dollar comparisons between rates with unlike denominators.
7. Leave a safe path for a future registered Abacus profile after its
   authenticated schema and field units are validated.

## Non-goals

- No runtime or user-authored pricing-rule override layer.
- No estimated researched-response costs for one, three, ten, or any other
  assumed number of searches.
- No usage metering, inference calls, or attempt to estimate actual spend from
  catalog rates.
- No currency conversion; provider monetary fields remain USD.
- No database migration or rewrite of saved snapshots and change history.
- No change to JSON field names, JSON values, diff generation, baseline
  selection, provider fetching, or notification policy.
- No registered Abacus profile in this change. The mechanism is designed to
  support one later, but its rules require separate authenticated validation.

## Chosen Approach

Add immutable, provider-owned price display rules keyed by raw field identity.
A rule supplies the arithmetic needed to convert the provider's raw value to a
human display rate, the display unit, and an optional comparison group for
absolute-impact calculations.

This is preferred over a `web_search` special case because `request`, `image`,
and mixed-unit providers have the same underlying need. It is preferred over
runtime configuration because OpenRouter's schema is provider behavior rather
than an operator preference, and exact profile rules can be reviewed and
tested with the code that consumes them.

Two alternatives are rejected for the initial implementation:

- **Targeted renderer exceptions:** smaller, but would duplicate provider
  vocabulary across classification, text, HTML, tooltips, and impact sorting.
- **User-configurable rules:** flexible, but introduces rule syntax,
  precedence, validation, typo handling, and healthcheck behavior before a
  demonstrated need. It may be layered on top of this design later.

## Rule Model

Add a frozen `PriceDisplayRule` dataclass in `provider_profiles.py` with this
conceptual contract:

```text
PriceDisplayRule
  unit_label: non-empty human display text
  multiplier: positive integer or None
  divisor: positive integer or None
  comparison_group: stable semantic key or None
  normalized_target: "per_million_tokens" or None
```

`multiplier` and `divisor` are a pair:

- when both are integers, the rule uses those explicit factors;
- when both are `None`, the rule inherits the multiplier and divisor bound to
  the active `ProviderProfile` from `providers.env`;
- one set without the other is invalid.

The display calculation remains:

```text
display_price = raw_provider_price * multiplier / divisor
```

`comparison_group` identifies rates whose converted absolute dollar deltas
share the same denominator and can therefore be compared. It is not inferred
from `unit_label`. `None` means direction and percentage remain meaningful,
but the absolute delta must not compete for a headline or impact rank.

`normalized_target` is independent of comparison. It explicitly states
whether a value may populate the existing per-million-token snapshot columns.
The generic fallback retains `per_million_tokens` as the operator's declared
best-effort target, while still using no comparison group because an
unregistered mixed-unit provider is not safe for global impact ranking.

Add two immutable rule registries to `ProviderProfile`:

- `price_path_rules`, keyed by an exact bare dotted path;
- `price_leaf_rules`, keyed by a final leaf identity only when a dynamic
  parent, such as `pricing.overrides[...].prompt`, requires inheritance.

Keep the two registries separate, following the existing field-label design.
An exact path makes a narrow claim. A leaf rule deliberately applies to every
price-classified dynamic path ending in that leaf.

The profile also owns an unmatched-field rule. Registered profiles may choose
a conservative unmatched rule; the generic profile retains the existing
configured-factor behavior because its multiplier/divisor is the operator's
only declared unit knowledge.

Add `primary_price_comparison_group: str | None` to `ProviderProfile`. This is
the one group, if any, eligible for the existing absolute-movement headlines
and model-card impact score. OpenRouter selects its token group. The generic
profile selects none.

## Rule Resolution

Add one resolver beside `resolve_field_label` and
`pricing_field_sort_key` in `change_render.py`:

```text
resolve_price_rule(field_path, profile) -> ResolvedPriceRule
```

It must reuse `_split_field_path`; no second parser for conditional or indexed
paths is allowed. Resolution order is:

1. Strip bracketed qualifiers to obtain the bare path.
2. Match `price_path_rules` by exact bare path.
3. Match `price_leaf_rules` by exact final leaf.
4. Use the profile's unmatched-field rule.
5. Bind inherited factors from the active profile and validate that both are
   positive.

No substring, prefix, regular-expression, display-label, or numeric-value
inference is permitted. A similarly named future field must remain unmatched
until a profile explicitly claims it.

The resolver is called only after the existing price predicate has classified
the field as monetary. Field categorization, label resolution, pricing order,
and rule resolution remain separate provider-profile concerns.

## Initial OpenRouter Rules

The initial registered rules cover units stated by OpenRouter's Models API
contract:

| Raw pricing leaf | Scale | Unit label | Comparison group | Normalized target |
|---|---:|---|---|---|
| `prompt` | `1,000,000 / 1` | `/1M tokens` | `usd_per_million_tokens` | `per_million_tokens` |
| `completion` | `1,000,000 / 1` | `/1M tokens` | `usd_per_million_tokens` | `per_million_tokens` |
| `internal_reasoning` | `1,000,000 / 1` | `/1M tokens` | `usd_per_million_tokens` | `per_million_tokens` |
| `input_cache_read` | `1,000,000 / 1` | `/1M tokens` | `usd_per_million_tokens` | `per_million_tokens` |
| `input_cache_write` | `1,000,000 / 1` | `/1M tokens` | `usd_per_million_tokens` | `per_million_tokens` |
| `web_search` | `1,000 / 1` | `/1K searches` | `usd_per_thousand_searches` | none |
| `request` | `1 / 1` | `/request` | `usd_per_request` | none |
| `image` | `1 / 1` | `/image` | `usd_per_image` | none |

These are leaf rules where conditional pricing overrides must inherit the same
unit as their base pricing leaf. The price resolver is already gated by the
profile's price predicate, so the leaf identity is not applied to unrelated
non-pricing metadata.

Existing observed-but-not-currently-contracted names such as
`input_cache_write_1h`, `input_audio_cache`, `audio_output`, and
`image_output` are not assigned a unit by naming convention alone. They use
OpenRouter's conservative unmatched rule until their source units are
validated. This avoids replacing the current false `/1M` assertion with a new
guess.

OpenRouter's unmatched monetary rule uses `1 / 1`, displays `/unit unknown`,
and has no comparison group or normalized target. The raw value is therefore
still presented as a USD amount and still receives cost direction/color
semantics, but the report does not invent a denominator, use it in
absolute-impact comparisons, or place it in a token-price snapshot column.

The generic profile retains its current bound multiplier/divisor, `/1M`
label, `per_million_tokens` normalized target, and best-effort warning. It has
no cross-provider comparison group, so generic-provider absolute deltas do not
compete with registered, unit-safe rates in global headlines.

## Classification and Rendered Data

`change_render.py::_classify_price` resolves the rule once before converting
either side. The same resolved rule applies to old, new, and delta values; a
field cannot change units between sides of one recorded change.

Extend `RenderedChange` with resolved price metadata sufficient for every
downstream consumer:

- the effective multiplier and divisor;
- the existing `unit` field populated from the rule;
- the comparison group, or `None`;
- the normalized target, or `None`;
- whether the rule was exact/leaf matched or the unmatched fallback, for
  diagnostics and focused tests.

The resolved metadata is presentation-only and is never serialized into scan
JSON or persisted to SQLite. `delta_abs` remains the absolute delta in the
display denomination. Consumers may compare it only after confirming matching,
non-`None` comparison groups.

Rename the private `_fmt_price_per_m` helper to a unit-neutral money formatter.
Its precision, bounded-sentinel, sign, and `free` behavior do not change; only
the assumption encoded in its name is removed.

## Human Report Behavior

Every human renderer consumes `RenderedChange.unit`; no renderer spells `/1M`
independently.

Examples:

```text
Input: 0.000001 -> 0.000002 ($1.00 -> $2.00 /1M tokens, up 100.0%)
Web search: 0.010 -> 0.014 ($10.00 -> $14.00 /1K searches, up 40.0%)
Per request: 0.01 -> 0.02 ($0.01 -> $0.02 /request, up 100.0%)
```

The actual reports retain their Unicode arrows and existing direction glyphs;
the examples above describe content rather than byte-exact output.

Required surfaces are:

- scan text;
- scan Markdown;
- concise scan HTML;
- full-detail scan HTML;
- `changes` text;
- `changes` HTML body;
- scan and `changes` HTML Change Summary;
- HTML Price Movement card and headline;
- HTML raw-value tooltip and selectable raw-value continuation row.

`_html_raw_and_normalized` accepts the resolved unit instead of appending
`/1M`. `_card_raw_title` derives its multiplication/division clause from the
resolved rule rather than the provider-wide profile. A web-search tooltip must
therefore read like:

```text
0.014 (1.4e-2) × 1,000 = $14.00
```

The unit remains in the report's unit column rather than being repeated in the
tooltip result. The card unit column must be widened or allowed to wrap so
`/1K searches`, `/request`, and `/unit unknown` remain readable without
overlapping adjacent columns.

Raw provider values and raw dotted paths remain available exactly as today.
JSON continues to bypass `RenderedChange` and therefore remains byte-shape
compatible apart from unrelated timestamp variability in live output.

## Unit-Safe Price Movement and Card Ranking

Direction and percentage are field-local and remain valid for every monetary
unit. A search rate increasing is still a cost increase, and a 40 percent
increase can still be stated. Counts of models and changed cost fields may
therefore continue to aggregate across unit families.

Absolute dollar deltas are different: `$1 /1M tokens`, `$1 /1K searches`, and
`$1 /request` are not comparable measures of spend. Model Sentinel has no
usage quantities with which to translate them into a common workload cost.

For this initial implementation:

1. OpenRouter's primary absolute-impact group is
   `usd_per_million_tokens`, preserving the established token-price triage.
2. Biggest-increase/decrease headlines consider only changes in that primary
   group. Their labels explicitly name the unit, for example
   `Biggest token-rate increase`.
3. Search, request, image, and unknown-unit changes remain in directional
   verdicts, model/field tallies, affected-model lists, tier-one model cards,
   and Change Summary rows.
4. A model with only non-primary monetary changes still qualifies for tier
   one, but receives no fabricated absolute-impact score. Such models sort
   after models with a primary-group absolute movement and then by model ID.
5. One-sided additions/removals remain coverage changes. They do not acquire
   an absolute delta merely because a unit rule exists.
6. No `delta_abs` values from different comparison groups are compared.

This deliberately defers multiple per-unit headline panels. They can be added
later without changing rule resolution if real reports show that search or
media movements need their own summary prominence. The field rows themselves
are corrected in this change and remain the authoritative view.

## Normalized Snapshot Columns

`NormalizedModel.input_price`, `output_price`, `cache_read_price`, and
`cache_write_price` remain canonical per-million-token columns. Their SQLite
schema and public meaning do not change.

Normalization must use the same resolved price rule as field-change
presentation rather than independently applying the provider-wide factors.
The configured normalized-field candidate lookup therefore needs to retain
the candidate raw path along with its value for monetary fields. A candidate
may populate one of these four columns only when its resolved rule has
`normalized_target="per_million_tokens"`; an operation-, image-, or
unknown-unit price must never enter a token-price column. This explicit target
is used instead of inferring storage eligibility from display text or headline
comparison policy.

For the current OpenRouter profile this produces the same stored values as
today. Existing rows require no migration. A future Abacus profile can safely
map only validated token fields into these columns while leaving its media
rates in canonical metadata for field-level reporting.

## Configuration and Compatibility

`MODEL_SENTINEL_PROVIDER_<ID>_PRICE_MULTIPLIER` and
`PRICE_DIVISOR` remain required in `providers.env`. They become the bound
factors used only by rules that explicitly inherit the provider scale and by
the generic fallback. Contracted OpenRouter rules use explicit schema-defined
factors and therefore cannot drift away from their unit labels if an old local
configuration contains a different multiplier. The template's existing
OpenRouter values already match those explicit factors, so standard
installations retain the same token-price results.

No new runtime file or configuration key is introduced. `setup.sh`, existing
live configuration, and standalone installation paths remain compatible.

Because stored field changes retain raw paths and raw values, rerendering
historical `changes` data with the new code applies the corrected units without
a backfill. Previously generated report files are immutable artifacts and are
not rewritten.

The standalone zipapp is a copied deployment artifact. After implementation
and complete verification, updating the scheduled executable requires a
separately authorized `install_standalone.sh` rebuild; repository changes alone
do not update it.

## Validation and Failure Behavior

Static profile construction and focused tests enforce:

- non-empty unit labels;
- positive explicit multiplier/divisor values;
- both factors explicit or both inherited;
- non-empty comparison-group strings when a group is present;
- a recognized normalized-target value when a target is present;
- exact rule resolution with no heuristic matching.

A numeric monetary field without a registered rule does not fail a scan. It
uses the profile's explicit unmatched rule, which is conservative for
OpenRouter and best-effort for the generic profile. A nonnumeric value keeps
the existing scalar fallback behavior.

Classification errors remain local deterministic programming/configuration
errors; there is no network fallback and no attempt to query provider pricing
documentation at runtime.

## Testing

Implementation follows red-green TDD and preserves the repository's complete
suite requirement.

### Provider-profile and resolver tests

- Pin every initial OpenRouter rule, unit, scale source, comparison group, and
  normalized target.
- Prove exact path wins over leaf and unmatched fallback.
- Prove conditional `pricing.overrides[...]` paths inherit leaf rules.
- Prove similarly named fields do not match by substring or prefix.
- Prove invalid factor pairs and empty units/groups are rejected.
- Prove `with_pricing` preserves all rule registries while rebinding inherited
  factors.
- Prove generic and OpenRouter unmatched behavior differ intentionally.

### Classification tests

- `pricing.prompt: 0.000001 -> 0.000002` renders `$1.00 -> $2.00`
  with `/1M tokens`.
- `pricing.web_search: 0.010 -> 0.014` renders `$10.00 -> $14.00`
  with `/1K searches`.
- `pricing.request: 0.01 -> 0.02` renders `$0.01 -> $0.02` with
  `/request`.
- `pricing.image` renders with `/image` and no fabricated scale.
- Unknown OpenRouter monetary fields render with `/unit unknown`, retain cost
  direction, and expose no comparison group.
- One-sided, zero, sub-resolution, negative-guard, percentage, and tooltip
  precision behavior remain covered for more than one unit family.

### Cross-renderer tests

- Pin the same values and units in scan text, Markdown, concise/full HTML,
  `changes` text/HTML, both Change Summaries, model cards, and tooltips.
- Prove no production renderer still contains an active hardcoded `/1M`
  assumption.
- Prove raw-value lines and JSON retain the provider literals.
- Review characterization-golden changes field by field rather than accepting
  wholesale output rewrites.

### Impact and normalization tests

- Prove a large `/1K searches` delta cannot beat or replace a token-rate
  headline merely because its displayed number is larger.
- Prove a non-primary-only monetary model remains in tier one and sorts after
  primary-group movers.
- Prove directional verdicts and counts include all monetary unit families.
- Prove additions/removals remain coverage-only.
- Prove normalized snapshot token columns use the resolved token rule and
  reject operation/image/unknown-unit candidates.
- Prove generic fallback normalization preserves the configured best-effort
  per-million-token behavior without making its deltas headline-comparable.
- Prove JSON, stored raw paths, diff order, pricing presentation order, and
  chronological history remain unchanged.

Run the complete pytest suite with no skipped, failed, or errored tests before
claiming completion. Also run the CLI help smoke test and render a synthetic
mixed-unit HTML report for visual inspection of unit-column width, wrapping,
tooltips, raw-value rows, summaries, and tier ordering.

## Documentation

Update:

- `README.md` configuration and report-formatting sections;
- `docs/DESIGN.md` provider profiles, normalization, reporting, and deferred
  work;
- `docs/provider_schema_notes.md` OpenRouter unit handling and the remaining
  Abacus validation boundary;
- `docs/report_readability_redesign_design.md` A1, D1, F2, tooltip, and unit
  assumptions, clearly marking the previous all-`/1M` behavior as superseded;
- `providers.env.template` comments so the multiplier/divisor are described as
  inherited/default factors rather than a universal provider-wide unit claim.

Documentation must distinguish catalog rates from actual workload spend and
must not add researched-response scenario estimates.

## Security and Repository Safety

- Use conspicuously synthetic provider values and model IDs in every test and
  document example.
- Do not inspect, copy, log, or commit authenticated provider payloads,
  credentials, runtime databases, or generated personal reports.
- Do not add account-specific pricing observations to fixtures.
- Inspect the complete staged file list and staged diff for sensitive data
  before every commit.

## Acceptance Criteria

- OpenRouter `pricing.web_search = 0.014` displays as `$14.00 /1K searches`,
  never `$14,000 /1M`.
- Contracted OpenRouter token fields continue to display per million tokens.
- `request` and `image` display in their native operation units.
- Unknown registered-profile monetary fields make their unknown unit explicit
  instead of silently borrowing the token unit.
- Conditional pricing paths inherit the correct base-leaf rule.
- All human report surfaces agree on converted values, units, deltas,
  percentages, and tooltip arithmetic.
- Absolute-impact headlines and card sorting never compare unlike unit groups.
- Non-token monetary changes remain visible, directional, and above the fold.
- Normalized token columns cannot contain operation- or media-denominated
  prices.
- JSON, raw metadata, stored field paths, history, and existing database schema
  remain unchanged.
- No runtime override layer or assumed-search-count estimate is introduced.
- The complete test suite passes and a synthetic mixed-unit HTML report passes
  visual inspection.
