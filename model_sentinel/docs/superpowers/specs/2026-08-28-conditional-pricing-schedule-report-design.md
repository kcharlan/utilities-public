# Conditional Pricing Schedule Report Design

- **Status:** Proposed design; no implementation is authorized by this document
- **Date:** 2026-08-28
- **Scope:** Human-readable Model Sentinel reports for provider-supplied conditional pricing

## Summary

Model Sentinel must treat `pricing.overrides` as a composite pricing policy,
not as an arbitrary list of monetary leaves. The first target is OpenRouter's
time-window pricing, but the design also preserves the existing prompt-token
threshold behavior and gives unknown future conditions a safe fallback.

The selected design introduces a provider-aware conditional-pricing
interpretation layer between canonical stored field changes and the existing scalar/list
rendering layer. It produces one semantic schedule or rule-set change per
model, keeps selectors such as `utc_start`, `utc_end`, and `utc_days` out of
monetary tallies, and renders the effective pricing policy as a compact table.
Canonical snapshots, stored field changes, JSON reports, and override-list
order remain unchanged.

The concise report will summarize a safely interpretable schedule by effective
rate bands. The full-detail report will retain the ordered rules and canonical
stored values.
When the conditions cannot be interpreted without guessing, the report will
say that conditional pricing changed, preserve the stored evidence in the audit
surface, and make no directional price claim.

## Trigger and Evidence

The 2026-08-28 OpenRouter snapshot for
`deepseek/deepseek-v4-pro-0813` introduced six `pricing.overrides` entries.
They use:

- `utc_days` to select weekends or weekdays;
- `utc_start` and `utc_end` as HHMM UTC clock boundaries; and
- `prompt`, `input_cache_read`, and `completion` as per-token prices.

OpenRouter documents override windows as half-open intervals: the start is
inclusive, the end is exclusive, and a start later than the end wraps past
midnight. Conditions on one entry are conjunctive. When multiple entries
apply, later entries win per price key; omitted price keys inherit the base
price. The top-level price keys represent the price under default conditions.

The current report flattens a one-sided structured list by index, producing
labels such as `Input (#2)`. It then treats numeric selectors under
`pricing.*` as money, producing claims such as `Utc end (#2): $400.00 /unit
unknown`. Those clock values also enter Price Movement tallies.

For this model, the report says "lower only" because the top-level advertised
rates fell 41.2%. The new scheduled peak rates are 17.6% above the prior
advertised rates, so the model's pricing became variable rather than simply
lower.

Repository history shows that time-window overrides are an evolving upstream
shape, not a single anomalous payload. A four-window form appeared for the same
model on August 17-18, disappeared on August 20, and returned on August 28 with
explicit weekday/weekend selectors. Current snapshots also contain time-window
overrides for other models. The report therefore needs a durable semantic
format rather than a model-specific exception.

## Goals

1. Render conditional pricing as a coherent policy whose conditions remain
   attached to their prices.
2. Never render condition selectors as monetary values or count them as price
   fields.
3. Distinguish base/default price movement from a newly variable price
   envelope.
4. Reuse one interpretation result across text, Markdown, concise HTML,
   full-detail HTML, `history`, and `changes` human reports.
5. Preserve canonical stored values, override-list order, and existing JSON
   schemas/values without claiming original wire-payload fidelity.
6. Match override entries by semantic condition identity so
   semantics-preserving reordering does not create human-report noise while
   non-commuting reorder remains visible.
7. Fail closed when a provider adds a condition or precedence relationship
   that the interpreter cannot represent safely.
8. Keep provider-specific vocabulary and schema rules in provider profiles,
   while keeping the schedule compiler and renderers provider-neutral.

## Non-Goals

- No SQLite schema migration or history rewrite.
- No change to JSON report structure or stored `FieldChange` paths.
- No attempt to predict the endpoint OpenRouter will route a request to or the
  user's actual billed cost.
- No conversion of a recurring UTC schedule into a permanently equivalent
  local-time schedule; daylight-saving transitions make that assertion false.
- No generalized rule engine for arbitrary boolean expressions, geographic
  pricing, account-specific discounts, or usage-based billing.
- No changes to the read-only Browse application's Activity, Models, or
  Catalog views in this feature. Browse continues to expose stored evidence;
  a dedicated composite-aspect design can follow if needed.
- No provider-specific hardcoding for one model ID or one observed set of
  prices.

## Existing Invariants to Preserve

- Provider identity is the provider ID, not its display label.
- Provider profiles own schema interpretation, field labels, units, and
  presentation order.
- Human presentation may interpret stored changes; storage and JSON projections
  remain unchanged.
- Pricing rows follow provider-defined semantic order: Input, cache variants,
  Output, then deterministic fallback.
- Red and green in change tables mean cost up and cost down only.
- Absolute comparisons occur only within the same provider-declared comparison
  group and unit.
- A bounded sentinel is preferable to a displayed false zero.
- Concise and `_full.html` reports use the same renderer; full detail is a
  policy mode, not a separate implementation.
- Composite provenance is matched by field, values, and occurrence where stored
  evidence links are constructed.

## Alternatives Considered

### A. Extend the existing leaf classifier

Add `utc_start`, `utc_end`, and `utc_days` exclusions, then keep rendering
`Input (#0)`, `Input (#1)`, and related rows.

This is the smallest change, but it fixes only the false-dollar symptom. Array
indices still separate rates from their conditions, repeated selector values
remain noisy, and Price Movement still cannot describe a variable envelope.
Every new selector would require another exclusion. This approach is rejected.

### B. Qualify every monetary leaf with its condition

Render rows such as `Input (Mon-Fri 01:00-04:00 UTC)` using the existing
`RenderedChange` table.

This preserves context and can reuse much of the scalar renderer, but repeats
the same condition once per price dimension. A schedule with six windows and
three prices becomes eighteen rows. It also overloads a scalar row abstraction
with precedence, inheritance, and schedule-level meaning. This remains the
fallback presentation for simple threshold changes only; it is not the primary
time-schedule design.

### C. Compile one composite conditional-pricing change

Recognize the parent `pricing.overrides` change, parse conditions and price
values through the provider profile, and render one schedule/rule-set block.

This approach adds a bounded semantic layer but solves the actual problem: it
keeps conditions and prices together, enables safe rate-band grouping, gives
Price Movement a model-level variable-pricing signal, and centralizes fallback
rules. This is the selected approach.

## Architecture

### 1. Preserve the canonical stored diff as the source of truth

`diffing._diff_values` continues to record one canonical parent change when an
override list changes:

```text
FieldChange("pricing.overrides", old_raw_list_or_null, new_raw_list_or_null)
```

Sibling base-price changes such as `pricing.prompt` remain ordinary stored
field changes. No condition-qualified synthetic paths are persisted. JSON
reports continue serializing the existing `FieldChange` values and public key
sets.

"Canonical stored value" is the audit promise. Model Sentinel retains the
normalized model object, override-list order, and the exact JSON values used by
the comparison. It does not retain original HTTP bytes, whitespace, numeric
spelling, or object-member order; canonical JSON sorts object keys. Existing UI
labels may continue to say "Raw details," but documentation and tests must not
expand that label into a wire-payload fidelity claim.

### 2. Add a conditional-pricing interpretation module

Create a focused module, conceptually `model_sentinel/conditional_pricing.py`,
instead of adding another composite subsystem to `reporting.py` or
`change_render.py`.

Its public boundary is format-neutral and event-scoped:

```text
interpret_conditional_pricing(
    event: PricingComparisonEvent,
    profile: ProviderProfile,
) -> ConditionalPricingInterpretation | None
```

`PricingComparisonEvent` contains:

```text
event_identity                 # live comparison token, or stored scrape edge
provider_id / provider_model_id
detected_at                    # display/filter metadata, never sole identity
field_changes                  # all rows for this exact model comparison
old_model_metadata             # exact baseline-side canonical metadata
new_model_metadata             # exact target-side canonical metadata
```

The complete event-side metadata is required because the diff contains only
unequal leaves. An override that omits `completion` may inherit an unchanged
base `pricing.completion`, which cannot be reconstructed from changed fields
alone. For a live scan, the comparison planner carries the baseline and current
`NormalizedModel` metadata already in memory. For a stored event, it loads the
model metadata at exactly the event's `from_scrape_id` and `to_scrape_id`. This
is not an arbitrary adjacent-snapshot lookup: those IDs define the recorded
comparison edge.

If either required side is unavailable, interpretation records
`missing_event_snapshot`. It may retain understood selectors, explicit rule
assignments, and independently provable direct `FieldChange` facts in an
ordered-rules presentation, but it cannot manufacture inherited vectors or
envelope directions. The interpreter consumes canonical values but never
mutates or replaces them.

Conceptual immutable result types:

```text
ConditionalPricingInterpretation
  source_change                 # canonical stored pricing.overrides change
  transition                    # added | removed | changed
  old_policy / new_policy       # parsed policies when safe
  absorbed_base_price_changes   # sibling price changes rendered in this block
  comparison                    # directional facts that are actually provable
  accounting                    # one format-neutral count/bucket record
  state                         # grouped-schedule | ordered-rules | raw-fallback
  fallback_reason               # unknown/unsafe semantics, if any
  grouping_inhibition_reasons   # understood but not safely collapsible
  comparison_inhibition_reasons # displayed but not directionally comparable

ConditionalPricingPolicy
  base_prices                   # provider-resolved price dimensions available
  rules                         # source-ordered ConditionalPricingRule values
  presentation                  # grouped-time-bands | ordered-rules

ConditionalPricingRule
  condition                     # canonical semantic condition
  explicit_prices               # only keys present in the source rule
  effective_prices              # only for a proven mutually exclusive region
  source_index                  # preserves later-rule precedence
  source_value                  # canonical stored rule for audit linking
```

`None` means only that the event has no `pricing.overrides` parent change. An
unrecognized or malformed parent change always returns a typed `raw-fallback`
result so selectors cannot fall through to scalar monetary rendering.

`change_render.RenderedChange` remains the scalar/list presentation type. A
composite pricing policy is not forced into it. `reporting.py` instead builds a
model-level presentation plan containing ordinary rendered rows plus zero or
one conditional-pricing block.

### 3. Make condition schemas provider-owned

Add an immutable registry of condition descriptors alongside the profile's
existing `pricing_override_condition_fields` tuple. A descriptor owns:

- raw field name;
- value validation;
- canonical identity representation;
- human label and formatting;
- condition family (`time`, `threshold`, or another registered family); and
- whether it participates in interval grouping.

The profile also owns policy-level evaluation semantics, separate from
individual descriptors:

```text
ConditionalPricingPolicySemantics
  condition_combination        # e.g. all fields must match
  rule_precedence              # e.g. later matching rule wins per key
  omitted_price_behavior       # e.g. retain prior assignment/base
  top_level_price_role         # e.g. default-condition base vector
```

The compiler never assumes these rules globally. OpenRouter registers
`all_conditions`, `later_per_key`, inherited omitted prices, and top-level
default prices from its documented contract. A provider without rich policy
semantics gets selector-safe stored-value fallback; it does not borrow
OpenRouter's precedence or inheritance.

Retain `pricing_override_condition_fields` for one compatibility period so
existing Python callers and synthetic profiles continue to construct
`ProviderProfile`. A legacy-only field becomes an identity-only descriptor: it
keeps the selector from being treated as money, but it cannot authorize time
grouping, an operator, ordered-rule semantics, or monetary interpretation. An
explicit rich descriptor with the same name takes precedence. This is a Python
construction API compatibility rule; environment-file provider configuration
is unchanged.

The OpenRouter profile registers rich descriptors grounded in the
[provider's generated model schema](https://github.com/OpenRouterTeam/terraform-provider-openrouter/blob/main/docs/data-sources/model.md):

| Field | Semantics | Canonical identity | Display |
|---|---|---|---|
| `min_prompt_tokens` | applies when prompt tokens are strictly greater | integer | `Prompt > 200,000 tokens` |
| `utc_days` | recurring UTC weekdays | calendar-ordered tuple | `Mon-Fri`, `Sat-Sun` |
| `utc_start` | inclusive HHMM UTC start | validated minutes since midnight | `01:00` |
| `utc_end` | exclusive HHMM UTC end | validated minutes since midnight | `04:00` |

The parser accepts JSON integers but not booleans. HHMM minutes must be below
60, hours below 24, and both time endpoints must be present together. OpenRouter
weekday values are the seven lowercase full English names observed in the
public schema payload; absent `utc_days` means every UTC day, while an empty
list is invalid. A rule with `utc_days` but no endpoints means all day on those
days. Duplicate or unknown weekday names, an empty rule, or an unsupported
condition causes a non-directional fallback rather than a guess. Duplicate
semantic rule conditions are understood overlap: they preserve source order
and use the ordered-rules state.

Weekday order in stored JSON is not semantically significant. The canonical
identity uses Monday-through-Sunday order, so list reordering does not create
a schedule change. The canonical stored JSON still records the source reorder.

Across event sides, rules match by `(canonical condition identity, occurrence)`
in source order, not array index alone. Unique identities match directly;
duplicate identities retain their first/second/etc. occurrence so provenance
and later-rule precedence remain auditable. Duplicate identities inhibit
grouped-band presentation unless the compiler independently proves a complete
equivalent partition.

### 4. Separate selectors from price dimensions

Within an override object, registered condition fields are selectors and can
never be price values. Remaining keys are price candidates only when the
provider profile resolves a price rule for that leaf. This is explicit schema
resolution, not the generic `pricing.*` monetary heuristic.

An unknown non-condition key forces stored-value fallback. It may be a price
assignment that affects inheritance or precedence, so a partial ordered-rules
table would overstate what is understood. Registered selectors remain
non-monetary even in that fallback.

### 5. Preserve inheritance and precedence

Under OpenRouter's registered policy contract, an override may omit price keys;
omitted keys retain the value supplied by an earlier matching assignment or the
base policy. Multiple applicable entries are source-ordered, and later entries
win per key. The interpreter therefore keeps explicit assignments separate
from compiled effective vectors and never sorts rules before applying
precedence. Other providers require their own registered policy semantics.

An ordered-rule row does not claim that an omitted cell inherits directly from
base. If multiple rules overlap, an earlier matching rule may supply that key.
The row says `not set by this rule`; the base/default vector is shown separately.
A complete effective vector is shown only for a proven mutually exclusive
region or a compiler-generated intersection whose full condition is visible.

The concise grouped-time-band format is permitted only when all these facts are
proven:

1. every rule is time-only (`utc_days`, `utc_start`, `utc_end`);
2. every condition is valid and canonical;
3. the weekly windows are non-overlapping after wrap handling;
4. a complete effective price vector can be derived from registered base and
   override price keys;
5. there are no unknown fields; and
6. grouping identical vectors does not change rule precedence or coverage.

Interpretation has exactly three presentation states:

1. `grouped-schedule`: complete, disjoint effective regions are proven;
2. `ordered-rules`: selectors and explicit price assignments are understood,
   but complete regions or final vectors are not proven; and
3. `raw-fallback`: at least one condition, price field, unit, value, or
   precedence relationship cannot be interpreted safely.

Valid overlap inhibits grouping but is not itself a raw fallback. The renderer
uses source-ordered rules with an explicit "later matching rules win per price
key" note and does not compute an unbounded set of intersections. Unknown
selectors or unresolved price semantics use `raw-fallback`.

Threshold-only rules remain ordered rules. Compound time-plus-threshold rules,
overlapping windows, and future understood condition families also remain
ordered rules unless a later design adds a provably correct compiler for them.

Rule-order equivalence is conservative. Reordering is semantic noise only when
the rules are disjoint or their per-key assignments commute for every possible
overlap. Reordering overlapping rules that assign different values to the same
price dimension is a semantic change.

### 6. Handle UTC windows precisely

Windows are half-open: `[start, end)`. Display uses `HH:MM-HH:MM UTC`.

- `utc_start=0` displays as `00:00`.
- `utc_end=0` after a positive start displays as `24:00` for the common
  end-of-day form.
- A general wrap such as `2200 -> 200` means the time-of-day predicate
  `time >= 22:00 or time < 02:00`.
- Equal non-null start and end values are not assumed to mean either empty or
  all day; they trigger stored-value fallback unless the provider profile
  explicitly defines that case.

OpenRouter evaluates `utc_days` at the request instant. Day membership is
therefore a predicate on the current UTC civil day, not an anchor that carries
a window into an unselected following day. For `utc_days=["friday"]` and
`2200 -> 200`, Friday 01:00 and Friday 23:00 match, while Saturday 01:00 does
not. If both Friday and Saturday are selected, Saturday's own predicate makes
Saturday 01:00 match. Canonical weekly coverage splits a wrapping time
predicate into `[00:00,end)` and `[start,24:00)` on each selected civil day;
Sunday-to-Monday rollover is not inferred.

All formats are UTC-only in this release. A recurring UTC schedule has no
single correct local representation across daylight-saving transitions, and a
clock-only conversion can also move the weekday. A future dated local preview
would require a separate design with a representative week, local dates,
numeric offsets, and DST tests; it must never drive semantic grouping.

## Change Semantics

### Policy transitions

The parent transition determines the leading language:

- no old policy, new policy: `Pricing schedule added relative to baseline`;
- old policy, no new policy: `Pricing schedule removed relative to baseline`;
- both policies: `Pricing schedule changed relative to baseline`;
- unparseable policy: `Conditional pricing changed (stored conditions retained)`.

A compact scan card may omit `relative to baseline` only when its enclosing
report header visibly identifies the selected baseline. Historical event blocks
always retain edge-relative language and source/target timestamps.

Source-order-only changes that preserve canonical conditions, effective
prices, and precedence produce no semantic schedule rows in concise human
reports. The canonical stored change remains in JSON and full-detail evidence.

### Directional comparisons

The interpreter distinguishes three kinds of facts:

1. **Base/default movement:** direct old-to-new sibling base-price changes.
2. **Region movement:** event-side effective prices compared per dimension and
   canonical region when an exact basis exists and units/groups match.
3. **Coverage:** a schedule or price dimension appeared or disappeared without
   a comparable prior value.

The report loads only the exact old/new metadata named by the comparison event.
It must not fetch an arbitrary adjacent snapshot or infer a missing price merely
to manufacture a percentage. Supported comparisons are deliberately bounded:

- a grouped policy versus a single default vector on the other event side;
- two grouped policies with the same canonical region partition; or
- directly matched dimensions/regions whose identity and basis are complete.

Different partitions, ordered-rule policies, missing event snapshots, and raw
fallbacks do not receive an aggregate envelope direction. Independently
provable direct base movements remain available as direct facts.

Movement is calculated per dimension first. A compiled band is `higher` only
when every comparable dimension is unchanged or higher and at least one is
higher; `lower` is symmetric; opposite directions are `mixed`; and no valid
basis is `not comparable`. One percentage may summarize a band only when every
included comparable dimension has the same percentage. Otherwise the report
shows per-dimension percentages or a direction-only statement. Mixed comparison
groups never share one dollar or percentage claim.

For the 2026-08-28 example, the recorded sibling base transitions provide a
valid basis. The report can truthfully say:

```text
Pricing schedule added
Advertised base rates: down 41.2%
Scheduled peak rates: up 17.6% versus the prior advertised rates
```

Here all three token-price dimensions have the same percentage on each band.
If they did not, the report would list their percentages separately. `Peak` or
`higher-rate band` is permitted only when that vector weakly dominates the
other relevant vectors in every included comparable dimension; otherwise use
neutral `Band 1`, `Band 2`, and so on.

This describes upstream catalog metadata, not guaranteed routed or billed
cost. Every report using `advertised`, `base`, or `scheduled` wording must keep
that distinction.

### Model buckets and verdicts

Add a fifth Price Movement model bucket: `Conditional / variable`.

A model enters this bucket whenever its conditional policy is added, removed,
or semantically changed. It does not simultaneously enter `Higher only` or
`Lower only`, even if its base prices moved in one direction. The schedule
block carries any provable directional subfacts.

The existing buckets remain:

- Higher only
- Lower only
- Both directions
- Added/removed only
- Conditional / variable

Verdict rules become:

- derive the ordinary `higher`, `lower`, `both`, or coverage verdict only from
  ordinary directional model buckets, using the existing rules;
- if no ordinary directional model exists and one or more conditional models
  changed, headline `conditional pricing changed`;
- if ordinary directional and conditional models both exist, keep the ordinary
  verdict and append `conditional pricing also changed` plus its model count;
- never turn `unknown/not comparable` into `mixed`; and
- keep conditional comparison status (`higher`, `lower`, `mixed`, `unchanged`,
  `coverage`, or `unknown`) inside the conditional tally and model block rather
  than merging it into the ordinary bucket verdict.

This deliberately avoids one synthetic global direction across flat and
scheduled price structures. The verdict is derived from the same pre-filter
semantic plan and accounting facts that populate the visible tallies. Default
and all-detail modes therefore agree. `--detail squelched` explicitly omits the
Price Movement and conditional schedule summary panels rather than recomputing
a different truth from the remaining rows. No renderer may recompute the
verdict independently.

### Tallies

Selector fields never enter monetary tallies. Conditional tier price values
are dimensions within a schedule, not independent global field changes.

Replace a misleading tally such as:

```text
49 price fields: 15 higher, 6 lower, 28 added
```

with two explicitly different aggregation levels:

```text
21 base price field changes: 15 higher, 6 lower
1 pricing schedule added: 6 rules, 3 price dimensions, 2 effective rate bands
```

One central accounting record defines:

- **base price field changes:** direct base `FieldChange` rows, including
  absorbed rows, counted exactly once;
- **conditional policies changed:** affected model-policy count;
- **source rules:** override objects on the displayed policy side;
- **schedule dimensions:** the union of registered price dimensions explicitly
  present in either old or new override rules;
- **effective rate bands:** distinct complete effective vectors after safe
  compilation; an uncovered default region counts only when it has nonempty
  coverage and a vector distinct from already counted bands; and
- **model bucket:** exactly one of higher, lower, both, coverage, or
  conditional/variable.

Rules that repeat the base vector can add condition coverage without adding a
distinct effective band. Two disjoint windows with the same complete vector are
one band. Ordinary one-sided non-schedule price fields continue to use
added/removed coverage tallies. Schedule counts are never counts of clock
selectors or repeated table cells, and field counts are never arithmetically
combined with policy or band counts.

## Presentation

### Concise HTML model card

When a schedule can be safely grouped, render one block in the Pricing section:

```text
PRICING SCHEDULE ADDED                                      UTC

Effective windows                   Input   Cache read   Output   vs prior
Weekends all day;
weekdays 00:00-01:00,
04:00-06:00, 10:00-24:00            $0.66   $0.022       $1.98    down 41.2%
Weekdays 01:00-04:00,
06:00-10:00                          $1.32   $0.044       $3.96    up 17.6%

Advertised base rate is the lower band. Actual routing and billing can vary.
```

Use provider-defined price-column order and unit labels. If columns have mixed
units, each header or value must carry its own unit; no shared `/1M tokens`
caption is allowed across unlike groups.

The absorbable dimension set is the union of registered price dimensions
explicitly present in either policy's override rules. A sibling base-price row
is consumed by the schedule block only when it belongs to the exact same event
edge, both event-side metadata objects are available, it resolves to a dimension
in that set, it has the same unit and comparison group as the displayed schedule
column, and the composite preserves its direct old/new value and movement fact.
The common presentation plan marks it consumed exactly once; accounting still
counts the base field change once.

Price siblings outside that set remain ordinary rows. For example, a
`pricing.request` change is not absorbed by a schedule containing only prompt
and completion token prices. `raw-fallback` never suppresses sibling rows;
independently provable base movements remain separately visible and counted.
Non-price changes for the model remain in the existing aligned table below the
schedule.

### Ordered-rules HTML fallback

When conditions are understood but cannot be safely collapsed, show rules in
source order:

```text
CONDITIONAL PRICING CHANGED
Base/default: Input $X | Cache read $Y | Output $Z

#  Applies when                         Input   Cache read   Output
1  Prompt > 200,000 tokens             ...     not set       ...
2  Mon-Fri 01:00-04:00 UTC             ...     ...          ...

Rules are evaluated in source order; later matching rules win per price key.
```

Explicit assignments and `not set by this rule` cells must be visually
distinguishable. `Inherited from base` is used only when mutual exclusivity
proves that statement. The full canonical stored rule remains available through
the existing raw-value disclosure.

### Raw fallback

If safe interpretation fails, the concise report shows:

```text
Conditional pricing changed
The provider supplied an unsupported or ambiguous condition. No schedule
direction was inferred. The canonical stored parent values are shown below.
```

The fallback reason is available in a tooltip or details disclosure for
diagnosis, but internal exception text is not exposed. Every fallback is
self-contained: text and Markdown print the parent old/new stored values in the
same artifact, and HTML places them in a disclosure in the same artifact.

### Full-detail HTML

The `_full.html` report uses the same composite renderer with detail mode
`all`. It:

- shows the semantic summary first;
- includes every source-ordered rule even when the concise view grouped it;
- marks explicit assignments and only proven inherited/effective prices;
- defaults canonical stored provider values to visible, consistent with
  existing behavior; and
- retains the canonical stored parent old/new JSON in one expandable audit
  block rather than manufacturing persisted synthetic paths.

### Text and Markdown

Text and Markdown use a compact block, not repeated scalar lines:

```text
[Pricing schedule added - UTC]
  Base/default: Input $0.66; Cache read $0.022; Output $1.98 /1M tokens
  Base-rate windows: Sat-Sun all day; Mon-Fri 00:00-01:00,
    04:00-06:00, 10:00-24:00
  Peak windows: Mon-Fri 01:00-04:00, 06:00-10:00
    Input $1.32; Cache read $0.044; Output $3.96 /1M tokens
  Movement: base down 41.2%; peak up 17.6% vs prior advertised rates
```

Text and Markdown continue to lead ordinary prices with provider-published
values. For an interpreted composite schedule, literal stored rule JSON belongs
in the all-detail audit subsection so the concise block remains readable. A
`raw-fallback` prints its stored parent values even at default detail because no
other semantic representation is safe and the artifact must be self-contained.

### Price Movement and Change Summary

Price Movement shows a `Conditional / variable` group and links each model to
its card. Its schedule tally uses policy, source-rule, dimension, and
effective-band counts from the central accounting record. Conditional status is
reported separately from the ordinary directional verdict; unknown is not
mixed. The Change Summary receives one schedule row per affected model, for
example:

```text
Pricing schedule added - 6 rules, 3 price dimensions, 2 UTC rate bands;
base down 41.2%, peak up 17.6%
```

It does not list eighteen tier leaves or any selector fields.

### `changes` and `history`

The shared compiler runs at a comparison-edge boundary. Storage already records
`from_scrape_id` and `to_scrape_id`, but the current historical query objects do
not carry them to presentation. Introduce a separate internal
`StoredComparisonEvent` envelope keyed by:

```text
(provider_id, provider_model_id, from_scrape_id, to_scrape_id)
```

It contains all source rows, both event-side model metadata objects, and the
detection timestamp. Timestamp is for display and date filtering, not identity.
This prevents two comparisons for one model on the same local day from merging.
The database schema and stored rows remain unchanged; queries select the
already-persisted scrape IDs and exact snapshot metadata.

Do not add internal IDs or metadata to dictionaries/dataclasses serialized by
the existing JSON branches. `changes` JSON remains the current row passthrough;
`history` JSON remains the current event key set. Human rendering consumes the
internal envelopes, while explicit legacy projection functions produce JSON.

Saved events are comparisons against a selected baseline, not necessarily the
chronologically adjacent saved scrape. Historical blocks therefore say
`Pricing schedule added relative to selected baseline` and show the source and
target scrape timestamps. They never claim a schedule first appeared at the
target unless immediate-predecessor identity is separately proven. The
retention contract is:

- compare-only scan: live comparison report plus scrape-attempt metadata; no
  stored snapshot or historical delta;
- saved scan: target snapshot plus the selected source-to-target comparison
  edge;
- `history`: all stored edges for one provider/model in the requested range;
- `changes`: stored non-initial edges in the requested range.

`history` and `changes` use the same format-neutral interpretation. There is no
report-specific copy of selector parsing, grouping, verdict, accounting, or
fallback policy.

### Command and format conformance

| Command | Text | Markdown | HTML | JSON |
|---|---|---|---|---|
| `scan` | semantic block | semantic block | semantic block; automatic reports produce concise and all-detail files | unchanged |
| `history` | grouped comparison edges | grouped comparison edges | unsupported | unchanged |
| `changes` | grouped comparison edges | unsupported | semantic block; `--detail all` is self-contained | unchanged |

Default and all-detail human formats share semantic verdicts and counts. All
detail additionally includes canonical stored parent values and source rules.
An explicit output request produces only the requested artifact; it may not
refer to an assumed HTML companion. Raw fallback remains self-contained even in
default detail.
Squelched scan/changes detail intentionally omits conditional schedule and Price
Movement summary panels rather than deriving a second answer from filtered
rows. Unsupported format cells remain unsupported; this feature does not add
history HTML or changes Markdown.

## Failure Handling

Interpretation returns typed reasons rather than raising for provider data.
Raw-fallback reasons include:

- parent value is not a list of objects;
- missing or invalid condition fields;
- unknown condition field;
- invalid HHMM value;
- unknown price field or unit;
- missing or unsupported provider policy-evaluation semantics.

Grouping inhibition is separate from raw-fallback failure. Valid overlap,
compound understood conditions, different old/new region partitions, and
non-commuting order are reasons to retain interpreted ordered rules, not reasons
to discard understood selectors and assignments.

Comparison inhibition is also separate. Missing event-side snapshot metadata,
missing base values required for inheritance, incompatible units/comparison
groups, different region partitions, or an absent prior basis prohibit the
affected effective vector or direction. They do not erase safely understood
conditions, explicit assignments, or direct base-field facts.

Provider-data failures degrade to an honest non-directional stored-value
report. Product invariant violations inside the interpreter remain programming
errors and are not swallowed.

No fallback may:

- format a selector as money;
- include a selector in price counts;
- claim higher or lower without a comparable basis;
- reorder rules whose precedence may matter; or
- discard canonical stored evidence.

## Data Flow

```text
provider payload
    -> canonical snapshot metadata (unchanged)
    -> recursive comparison diff (unchanged)
    -> stored FieldChange / public JSON projection (unchanged)
    -> exact comparison-edge envelope with old/new metadata
    -> model-event presentation planning
         -> conditional-pricing interpreter
              -> grouped time bands, ordered rules, or raw fallback
         -> ordinary change_render classification for remaining fields
    -> text / Markdown / HTML renderers
    -> Price Movement and Change Summary from the same plan
```

The interpreter is presentation-only. A successful grouped/ordered composite
plan may mark precisely qualified sibling rows consumed in one human
presentation, but it does not delete or rewrite them. Raw fallback consumes no
sibling rows.

## Testing Strategy

All fixtures must be conspicuously synthetic or copied only from public
provider documentation. Tests must never read the user's runtime database or
reports.

### Condition parsing and identity

- valid HHMM values including `0`, `30`, `100`, `1030`, and `2359`;
- invalid minutes, invalid hours, negative values, strings, floats, and booleans;
- paired start/end requirement;
- all-day `utc_days` without endpoints;
- omitted days mean all seven; empty days are invalid;
- calendar-order normalization and source weekday reordering;
- unknown and duplicate weekday values;
- normal, end-at-midnight, and current-civil-day wrap predicates;
- Friday-only `22:00-02:00` matches Friday 01:00 and 23:00 but not Saturday
  01:00; selecting Saturday makes its own 01:00 match;
- equal start/end fail-closed behavior;
- `min_prompt_tokens` strict-greater display and threshold-minus-one, exact,
  and threshold-plus-one contract fixtures;
- duplicate semantic rule identities preserve source order in ordered-rules
  state; and
- unknown condition fields.

### Policy semantics

- one-sided schedule addition and removal;
- safely grouped disjoint time windows;
- identical price vectors grouped without losing coverage;
- incomplete rule prices inheriting from unchanged event-side base metadata;
- addition and removal with a missing referenced snapshot use
  `missing_event_snapshot` rather than guessing;
- later-rule per-key precedence preserved;
- overlapping understood windows use ordered rules, while an unknown selector
  uses raw fallback;
- omitted ordered-rule cells say `not set by this rule` unless exclusivity
  proves base inheritance;
- time-plus-threshold compound rules use ordered rules;
- order-only changes are suppressed only for disjoint or commuting rules and
  remain visible in canonical stored evidence;
- reordered overlapping same-key assignments remain semantic changes;
- actual tier price mutation matched by canonical condition;
- schedule transition with exact comparable event state and with no valid
  comparison basis;
- same-unit per-dimension comparisons, mixed-direction vectors, and mixed-unit
  aggregate refusal;
- band names use `peak` only after dominance is proven; and
- malformed parent values using raw fallback.

### Report semantics

- selectors never produce currency, `free`, unit labels, cost colors, or price
  tallies;
- schedule models use the Conditional / variable bucket;
- unknown conditional movement never produces `mixed`;
- default and all-detail verdicts/counts agree, while squelched mode omits the
  semantic panels;
- only same-edge, same-dimension base movements are absorbed, with unrelated
  price groups left ordinary and every base field counted once;
- raw fallback absorbs no sibling row;
- schedule tallies reconcile policies, rules, dimensions, uncovered default
  coverage, and distinct effective bands;
- Change Summary has one composite row;
- `changes` and `history` JSON retain exactly their existing schemas and values;
- internal scrape IDs and snapshot metadata never enter public JSON;
- two comparison edges for one model on one local date remain two human event
  blocks with no cross-edge absorption;
- a selected baseline older than the chronological predecessor is labeled as a
  comparison edge and never as first appearance;
- compare-only changes do not appear in later history; the saved equivalent
  does;
- concise and full HTML use one renderer with policy-driven detail;
- every supported cell in the command/format matrix consumes the same
  interpretation;
- all-detail and every raw fallback artifact contains its canonical stored
  parent values without requiring an HTML companion;
- provenance links resolve to the correct parent change when repeated events
  exist; and
- a legacy `ProviderProfile(pricing_override_condition_fields=...)` fixture
  retains identity-only compatibility and never makes the field monetary.

### Characterization and visual validation

- Add a checked-in public six-rule trigger fixture and synthetic goldens for
  grouped schedule, ordered rules, and raw fallback in every supported format.
- Independently derive the fixture's 41.2% and 17.6% values rather than copying
  expected prose.
- Render concise and full HTML against an isolated synthetic runtime.
- Inspect desktop and narrow layouts for wrapping, overflow, readable price
  columns, and visible UTC labeling.
- Verify the raw-value toggle and self-contained parent evidence disclosure.
- Run the complete repository test suite with zero skips, as required by the
  project instructions.

## Documentation Updates Required During Implementation

- `README.md`: conditional-pricing semantics, new Price Movement bucket and
  tally vocabulary, UTC display, and raw fallback.
- `docs/DESIGN.md`: presentation compiler boundary and canonical-storage
  invariant.
- `docs/provider_schema_notes.md`: OpenRouter `utc_days`, half-open HHMM
  windows, inheritance, and precedence.
- `docs/report_readability_redesign_design.md`: amendment replacing indexed
  conditional leaves with composite schedules while preserving the shared
  renderer.

## Compatibility and Migration

- Database schema: unchanged.
- Existing snapshots and field changes: unchanged and immediately renderable
  through the new interpretation layer.
- Historical queries: select existing scrape-edge IDs and snapshot metadata
  into internal envelopes; no schema migration or backfill.
- JSON output: existing schemas and values unchanged; internal envelope fields
  are explicitly projected out.
- Environment-file provider configuration: unchanged.
- Python `ProviderProfile` construction: legacy
  `pricing_override_condition_fields` retained for one compatibility period as
  identity-only descriptors; rich descriptors are additive.
- Generic providers: no new semantic interpretation unless they register rich
  condition descriptors; legacy names remain non-monetary identity fields.
- Existing simple prompt-threshold overrides: rendered through the new ordered
  rules block using the documented OpenRouter strict-greater contract; stored
  paths remain unchanged.
- Deconfigured historical providers: generic profile and stored-value fallback,
  with no borrowed OpenRouter semantics.

## Acceptance Criteria

1. The synthetic equivalent of the August 28 schedule renders clock boundaries
   as times, never dollars or `free`.
2. Its concise card contains two grouped effective rate bands with conditions
   attached to the price tuple.
3. Its movement summary reports base rates down and scheduled peak rates up,
   per dimension (or once only when identical), and the model is Conditional /
   variable rather than Lower only.
4. Selector fields contribute zero monetary fields to tallies.
5. The full-detail report preserves all six source rules and both canonical
   stored parent values; it does not claim wire-payload fidelity.
6. Valid overlap produces source-ordered explicit assignments; an unknown
   selector or invalid clock produces a non-directional stored-value fallback.
7. Missing exact event-side metadata prohibits inherited vectors, consumes no
   sibling rows, and returns `missing_event_snapshot`.
8. Rule reordering produces no concise noise only when rules are disjoint or
   commute; overlapping same-key assignments remain a semantic change.
9. OpenRouter weekday, wrap, threshold, inheritance, and later-per-key
   precedence behavior matches its cited generated schema.
10. Only same-edge price dimensions participating in the schedule are
    absorbed; all base fields and policies reconcile exactly once.
11. Two events for one model on one date remain separate in `changes` and
    `history`, and saved historical wording is relative to the selected
    baseline.
12. Every supported human format in the conformance matrix agrees on semantic
    meaning/counts and is self-contained in all-detail or fallback mode.
13. Existing `changes` and `history` JSON schemas and values remain unchanged;
    persisted canonical values are untouched.
14. Existing Python profile constructors keep identity-only compatibility,
    while rich OpenRouter descriptors enable the new semantics.
15. The complete test suite passes with no skips, and synthetic HTML passes
    desktop and narrow visual inspection.

## Adversarial Review Record

An independent GPT-5.6 Sol Pro review examined this design together with the
current reporting, storage, diffing, CLI, profile, and characterization-test
paths. Each finding was checked against repository source; external condition
semantics were checked against OpenRouter's current generated schema. This
revision applies the following dispositions:

| # | Finding | Disposition and resolution |
|---|---|---|
| 1 | Historical paths lack event identity | Accepted. Added internal scrape-edge envelopes and explicit legacy JSON projections. |
| 2 | Changed fields cannot supply unchanged inherited base prices | Accepted. Interpreter now requires exact old/new event-side metadata, with `missing_event_snapshot` fallback. |
| 3 | Ordered-rule `inherited` cells can be false under overlap | Accepted. Ordered rows show explicit assignments and `not set by this rule`; effective vectors require proven regions. |
| 4 | Overlap was both ordered and raw fallback | Accepted. Defined grouped, ordered, and raw states; valid overlap is ordered. |
| 5 | Weekday/wrap semantics were incomplete | Accepted, but the proposed start-day correction was rejected. OpenRouter documents `utc_days` at the request instant, so wrap is split on each selected UTC civil day without inferred rollover. |
| 6 | Generic local-time preview can shift day/DST incorrectly | Accepted. Removed local preview from this release; every format is UTC-only. |
| 7 | Sibling absorption boundary was undefined | Accepted. Added exact-edge, participating-dimension, unit/group, preserved-fact, consume-once requirements; raw fallback absorbs none. |
| 8 | Mixed units/directions invalidate one band percentage and `peak` | Accepted. Movement is per dimension; aggregate percentages require equality and band naming requires dominance. |
| 9 | Unknown movement was incorrectly treated as mixed and could vary by detail filtering | Accepted. Unknown is separate; semantic planning precedes filtering; squelched mode omits panels. |
| 10 | Tally concepts did not reconcile | Accepted. Added one accounting record with disjoint field, policy, rule, dimension, band, and model-bucket meanings. |
| 11 | Historical edges are not necessarily adjacent transitions | Accepted. Added selected-baseline-relative wording and a retention matrix. |
| 12 | Audit language overstated wire fidelity and fallback reachability | Accepted. Promise is canonical stored values; fallback/all-detail artifacts are self-contained. |
| 13 | Strict-greater prompt threshold was unsupported | Rejected as a current factual claim. OpenRouter's generated schema explicitly specifies strictly greater. The review's underlying demand for an authoritative citation and boundary tests was accepted. |
| 14 | Replacing the profile tuple would break Python callers | Accepted. Rich descriptors are additive; the legacy tuple remains identity-only for one compatibility period. |
| 15 | Command/format and test scope were ambiguous | Accepted. Added an explicit conformance matrix and named cross-event, state, compatibility, audit, and public-fixture cases. |

The review also retracted suspected defects after source inspection: live scans
already have a natural per-model comparison boundary; presentation-only list
expansion does not rewrite persistence or JSON; `changes` groups providers by
provider ID; same-day presence rows remain distinct; and existing biggest-mover
selection already restricts unlike comparison groups. Those non-findings do not
require design changes.

## Implementation Boundary

This document resolves behavior and architecture but does not authorize
implementation. A separate implementation plan must map these decisions to
specific functions, tests, sequencing, and verification commands after the
design is approved.
