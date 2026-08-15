# Per-Field Pricing Units Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every price-classified provider field a provider-owned conversion rule and truthful display unit, beginning with OpenRouter token, web-search, request, image, and conservative unknown-unit behavior, while preserving raw data, JSON, storage, and all-unit movement visibility.

**Architecture:** Add frozen price-rule value objects to `ProviderProfile`, resolve one rule from the raw field path beside the existing label/order resolvers, and carry that resolved object on `RenderedChange`. Classification, normalization, text/Markdown/HTML rendering, tooltips, headline selection, and model-card impact ordering must consume that one contract. Field-local direction and percentage continue to cover every monetary unit; absolute-dollar comparison is restricted to the profile's declared primary group, and the existing global headline remains token-rate-only.

**Tech Stack:** Python 3.11+ standard library, frozen dataclasses, provider profiles, pytest, self-contained HTML/CSS, SQLite-compatible normalized models.

---

## Source of truth and scope

This plan implements the approved design in
[`docs/superpowers/specs/2026-08-15-per-field-pricing-units-design.md`](./superpowers/specs/2026-08-15-per-field-pricing-units-design.md).
If implementation reveals a conflict, stop and amend the design before changing
the contract described here.

The approved choices are binding:

1. Use provider-owned per-field rules (Approach 2), not renderer special cases.
2. Do not add runtime or user-authored rule overrides.
3. Do not estimate cost per search count, including one/three/ten-search examples.
4. Do not register an Abacus profile in this change.
5. Do not migrate or rewrite stored snapshots, field changes, JSON, or prior report files.
6. Do not rebuild or install the standalone zipapp without separate authorization.

The implementation is presentation and normalization-policy work. It must not
change fetching, diff generation, baseline selection, notification policy,
database schema, raw metadata persistence, or provider configuration parsing.

## Current code map

- `model_sentinel/provider_profiles.py`
  - `ProviderProfile` currently owns provider-wide `price_multiplier` and
    `price_divisor`, normalized candidate paths, labels, predicates, and Pricing
    order.
  - `GENERIC_PROFILE` and `OPENROUTER_PROFILE` are the two relevant instances;
    only OpenRouter is registered.
  - `ProviderProfile.with_pricing()` uses `dataclasses.replace`, so new fields
    must survive rebinding automatically.
- `model_sentinel/change_render.py`
  - `_split_field_path()` is the only parser for conditional/indexed field
    paths and must remain the only parser.
  - `resolve_field_label()` and `pricing_field_sort_key()` establish the
    existing exact-path/leaf/fallback pattern.
  - `RenderedChange` is the format-neutral value consumed by human renderers.
  - `_classify_price()` currently applies provider-wide factors and hardcodes
    `unit="/1M"`.
  - `_fmt_price_per_m()` is monetary formatting with a stale unit-specific name.
- `model_sentinel/normalize.py`
  - `_profile_field()` returns only a candidate value, losing the raw path.
  - `_normalize_price()` applies provider-wide factors to all four canonical
    token-price columns.
- `model_sentinel/reporting.py`
  - `_render_change_text()` and `_html_raw_and_normalized()` contain active
    `/1M` assumptions.
  - `_price_conversion_factor()` and `_card_raw_title()` use the profile-wide
    factors rather than the classified field's factors.
  - `_collect_price_movement_summary()` compares every `delta_abs` when choosing
    headline movers.
  - `_model_price_impact()` compares every monetary `delta_abs` for tier-one
    model ordering.
  - `_render_html_price_movement_summary()` labels the two panels “Biggest
    increase/decrease” without naming the comparable unit family.
- `tests/test_render_characterization.py`,
  `tests/test_render_changes_characterization.py`, and
  `tests/test_render_bulk_characterization.py` are exact-output regression
  gates. Intentional human-output diffs must be reviewed; JSON goldens must not
  change.

## Binding data contracts

### Rule value objects

Add these types in `model_sentinel/provider_profiles.py`:

```python
PriceNormalizedTarget = Literal["per_million_tokens"]
PriceRuleMatchSource = Literal["path", "leaf", "unmatched"]

@dataclass(frozen=True)
class PriceDisplayRule:
    unit_label: str
    multiplier: int | None = None
    divisor: int | None = None
    comparison_group: str | None = None
    normalized_target: PriceNormalizedTarget | None = None

@dataclass(frozen=True)
class ResolvedPriceRule:
    unit_label: str
    multiplier: int
    divisor: int
    comparison_group: str | None
    normalized_target: PriceNormalizedTarget | None
    match_source: PriceRuleMatchSource
```

`PriceDisplayRule.__post_init__()` must reject:

- a blank/whitespace-only `unit_label`;
- only one of `multiplier` and `divisor` being supplied;
- an explicit multiplier or divisor less than one;
- a blank/whitespace-only `comparison_group` when it is not `None`;
- any runtime `normalized_target` other than `None` or
  `"per_million_tokens"` (tests may deliberately bypass static typing).

Do not normalize user-supplied strings by stripping them silently. Reject
invalid declarations so the profile source remains the exact auditable
contract.

`ResolvedPriceRule` is not a second configurable rule. It is the result of
binding a `PriceDisplayRule` to one active `ProviderProfile`, so its factors are
always positive integers and never `None`.

Define shared semantic constants rather than repeating string literals:

```text
PER_MILLION_TOKENS_TARGET = "per_million_tokens"
USD_PER_MILLION_TOKENS_GROUP = "usd_per_million_tokens"
```

The target controls eligibility for canonical snapshot columns. The group
controls absolute comparison. They are intentionally independent.

### Provider profile fields

Extend `ProviderProfile` with:

```python
price_path_rules: Mapping[str, PriceDisplayRule]
price_leaf_rules: Mapping[str, PriceDisplayRule]
unmatched_price_rule: PriceDisplayRule
primary_price_comparison_group: str | None
```

Back both registries with `types.MappingProxyType`, including a shared empty
mapping used by defaults. The frozen profile prevents attribute rebinding;
mapping proxies prevent mutation through the retained mapping reference. Do
not expose mutable module dictionaries under a read-only `Mapping` annotation.

The generic unmatched default must:

- inherit `price_multiplier` and `price_divisor` (`None`/`None` in the rule);
- display `/1M` for compatibility;
- set `normalized_target="per_million_tokens"`;
- set `comparison_group=None` so unknown-provider deltas never enter a safe
  absolute headline/rank by implication.

`GENERIC_PROFILE.primary_price_comparison_group` remains `None`.

OpenRouter's unmatched rule must use explicit `1 / 1`, display
`/unit unknown`, and set both semantic fields to `None`. An uncontracted field
therefore keeps its raw USD magnitude and cost direction but acquires no
invented denominator, token-column eligibility, or absolute impact.

### Initial OpenRouter leaf registry

Populate `OPENROUTER_PROFILE.price_leaf_rules` with exactly these entries:

| Leaf | Multiplier / divisor | Unit | Comparison group | Normalized target |
|---|---:|---|---|---|
| `prompt` | `1_000_000 / 1` | `/1M tokens` | `usd_per_million_tokens` | `per_million_tokens` |
| `completion` | `1_000_000 / 1` | `/1M tokens` | `usd_per_million_tokens` | `per_million_tokens` |
| `internal_reasoning` | `1_000_000 / 1` | `/1M tokens` | `usd_per_million_tokens` | `per_million_tokens` |
| `input_cache_read` | `1_000_000 / 1` | `/1M tokens` | `usd_per_million_tokens` | `per_million_tokens` |
| `input_cache_write` | `1_000_000 / 1` | `/1M tokens` | `usd_per_million_tokens` | `per_million_tokens` |
| `web_search` | `1_000 / 1` | `/1K searches` | `usd_per_thousand_searches` | `None` |
| `request` | `1 / 1` | `/request` | `usd_per_request` | `None` |
| `image` | `1 / 1` | `/image` | `usd_per_image` | `None` |

Set OpenRouter's primary comparison group to
`USD_PER_MILLION_TOKENS_GROUP`. Keep `price_path_rules` empty initially; it is
part of the contract for narrow future exceptions and for precedence tests.

Do not add rules for `input_cache_write_1h`, `input_audio_cache`,
`audio_output`, or `image_output`. Their names are observed, but their source
units are not contracted. They must exercise the OpenRouter unmatched rule.

### Resolver contract

Add this function in `model_sentinel/change_render.py` beside
`resolve_field_label()` and `pricing_field_sort_key()`:

```python
def resolve_price_rule(
    field_path: str,
    profile: ProviderProfile,
) -> ResolvedPriceRule:
```

The resolver must:

1. call `_split_field_path(field_path)` once to obtain the bare path;
2. try `profile.price_path_rules[bare_path]`;
3. try `profile.price_leaf_rules[bare_leaf]`;
4. use `profile.unmatched_price_rule`;
5. replace inherited factors with the active profile's configured factors;
6. raise `ValueError` if either effective factor is less than one;
7. preserve `unit_label`, comparison group, normalized target, and the exact
   `path`/`leaf`/`unmatched` provenance in the result.

No other matching is allowed: no prefixes, substrings, regexes, labels,
numeric magnitudes, categories, or provider-name branches. The existing price
predicate remains the gate; the resolver does not decide whether a field is
monetary.

### Rendered change contract

Add one field to `RenderedChange`:

```python
price_rule: ResolvedPriceRule | None
```

This single object is the approved “sufficient resolved metadata”; do not copy
its multiplier, divisor, group, target, or provenance into parallel scalar
fields on `RenderedChange`. Price classifiers set it to the resolved rule.
Every non-price constructor sets it to `None`.

Extend `RenderedChange.__post_init__()` with both invariants:

- `kind == "price"` requires `price_rule is not None` and
  `unit == price_rule.unit_label`;
- every other kind requires `price_rule is None`.

The existing `unit` field remains because it is a general renderer-facing
column (counts also have units). For a price row it is derived from, and
checked against, `price_rule.unit_label`.

`delta_abs` remains the absolute-sort input in the rule's displayed
denomination. It is never safe to compare without also checking the non-`None`
comparison group.

## Unit-safe impact policy

Keep two questions separate:

- **Does this model have a monetary movement?** `_price_movement_kind()` still
  considers all price-classified fields and controls tier-one membership,
  direction buckets, affected-model lists, and field/model counts.
- **Does this movement have a comparable primary absolute magnitude?** Only a
  two-sided `RenderedChange` whose `price_rule.comparison_group` equals the
  active profile's non-`None` `primary_price_comparison_group` can contribute
  an absolute model-card score.

For the existing cross-provider headline, add the stricter current policy:
only `USD_PER_MILLION_TOKENS_GROUP` candidates are eligible. This makes the
panels truthfully labelable as “Biggest token-rate increase” and “Biggest
token-rate decrease” and prevents a future profile with a different primary
group from silently entering the same global maximum. Multiple per-unit
headline panels remain deferred.

Refactor `_ModelImpact` so absence of a primary magnitude is represented by
`primary_delta: float | None`, not fabricated `0.0`. Its sort key must be:

```text
primary candidate present:
    (0, -rounded_primary_delta, -paired_percent, -coverage, model_id.casefold())
primary candidate absent:
    (1, 0.0, 0.0, 0, model_id.casefold())
```

This preserves the existing cents rounding and percent/coverage tie-breaks for
comparable token-rate movers. Models with only search/request/image/unknown or
one-sided price coverage remain tier one, sort after scored models, and sort
among themselves by model ID. A non-primary percentage must not become a
surrogate cross-unit score.

## File map for implementation

- `model_sentinel/provider_profiles.py`
  - Add price-rule types, validation, constants, profile fields, generic
    fallback, OpenRouter rules, and primary group.
- `model_sentinel/change_render.py`
  - Add `resolve_price_rule()`.
  - Add `RenderedChange.price_rule` and invariants.
  - Resolve once in `_classify_price()` and use its factors/unit.
  - Rename `_fmt_price_per_m()` to `_fmt_money()` without changing formatting.
- `model_sentinel/normalize.py`
  - Retain the selected raw candidate path for monetary normalized fields.
  - Resolve the same rule and populate canonical token columns only for the
    token normalization target.
- `model_sentinel/reporting.py`
  - Remove hardcoded `/1M` presentation.
  - Use `RenderedChange.unit` and `RenderedChange.price_rule` for values and
    tooltips.
  - Filter absolute headlines and model impact by comparison policy.
  - Widen/wrap the unit column.
- `tests/test_provider_profiles.py`
  - Pin rule declarations, validation, defaults, and `with_pricing()` behavior.
- `tests/test_change_render.py`
  - Pin resolution, classification, metadata, formatter rename, and no
    heuristic matching.
- `tests/test_normalize.py`
  - Pin path-aware target eligibility and unchanged generic best effort.
- `tests/test_reporting.py`
  - Pin every human report surface, tooltip derivations, unit-safe headlines,
    all-unit counts/tiering, and deterministic impact ordering.
- `tests/test_render_characterization.py`
  - Review and update intentional scan text/Markdown/HTML unit and headline
    diffs; preserve JSON byte shape.
- `tests/test_render_changes_characterization.py`
  - Review and update intentional `changes` text/HTML unit diffs; preserve JSON.
- `tests/test_render_bulk_characterization.py`
  - Run as a regression gate; update only if a directly explained unit-bearing
    output is present.
- `README.md`, `docs/DESIGN.md`, `docs/provider_schema_notes.md`,
  `docs/report_readability_redesign_design.md`, `providers.env.template`
  - Document the shipped rule boundary and deferred Abacus/runtime work.

Files intentionally not changed:

- `model_sentinel/config.py`: existing factor keys remain required and valid.
- `model_sentinel/models.py`, `model_sentinel/storage.py`, and database schema:
  no persistent type or column changes.
- `model_sentinel/diffing.py`: raw paths, values, and ordering are unchanged.
- `install_standalone.sh` and installed artifacts: deployment is separately
  authorized.

## Task 0: Establish a clean baseline

**Files:** none

- [ ] **Step 1: Confirm the worktree and current commit**

Run:

```bash
git status --short
git log -1 --oneline
```

Expected: no unexpected edits. Preserve any user-owned changes and do not
overwrite them.

- [ ] **Step 2: Run the complete suite before implementation**

Run only through the project virtual environment:

```bash
./.venv/bin/python -m pytest
```

Expected: exit 0 with no failed, errored, or skipped tests. If anything fails,
diagnose and fix the baseline before beginning feature work; do not classify a
failure as ignorable.

## Task 1: Add the rule model, profile declarations, and resolver

**Files:**

- Modify: `model_sentinel/provider_profiles.py`
- Modify: `model_sentinel/change_render.py`
- Test: `tests/test_provider_profiles.py`
- Test: `tests/test_change_render.py`

- [ ] **Step 1: Write failing rule-validation tests**

In `tests/test_provider_profiles.py`, add focused tests that prove:

- a fully explicit rule and a fully inherited rule construct successfully;
- blank units and blank non-`None` groups fail;
- half-specified factors fail in both directions;
- zero/negative explicit factors fail;
- an invalid runtime normalized target fails;
- the dataclasses are frozen;
- attempts to mutate a profile's path or leaf registry raise `TypeError`;
- the generic fallback has the exact inherited `/1M`, token-target, no-group
  behavior;
- the OpenRouter registry is exactly the eight-entry table above;
- OpenRouter's unmatched rule and primary group are exact;
- `with_pricing()` preserves the mapping objects, unmatched rule, and primary
  group while rebinding only provider-wide factors.

Use conspicuously synthetic values and provider names.

- [ ] **Step 2: Run the profile tests and verify failure**

```bash
./.venv/bin/python -m pytest tests/test_provider_profiles.py -v
```

Expected: FAIL because the rule types and profile fields do not exist.

- [ ] **Step 3: Implement the frozen rule/profile contract**

Add the types, validation, constants, defaults, and OpenRouter declarations
exactly as specified above. Follow the module's existing pattern of named,
provider-local registries. Do not add a configuration parser or mutable
runtime registry.

- [ ] **Step 4: Run the profile tests**

Run the Step 2 command.

Expected: all `tests/test_provider_profiles.py` tests PASS.

- [ ] **Step 5: Write failing resolver tests**

In `tests/test_change_render.py`, add exact node-level coverage for:

- exact bare path winning over a conflicting leaf rule;
- a conditional `pricing.overrides[min_prompt_tokens=200000].prompt` using the
  `prompt` leaf rule and retaining `match_source="leaf"`;
- unmatched OpenRouter fields using `1 / 1`, `/unit unknown`, and no semantic
  metadata;
- generic unmatched fields binding configured factors and the token target;
- `pricing.prompt_surcharge` and `pricing.web_search_preview` staying
  unmatched;
- a profile with inherited factors resolving different effective values after
  `with_pricing()`;
- non-positive effective inherited factors failing at resolution even when a
  test constructs the profile directly.

The exact-path precedence fixture should use a synthetic `ProviderProfile`
with deliberately conflicting path and leaf rules. Do not alter OpenRouter's
production registry to manufacture the collision.

- [ ] **Step 6: Run the resolver nodes and verify failure**

Run the exact new test node IDs selected by the implementer, for example:

```bash
./.venv/bin/python -m pytest \
  tests/test_change_render.py::test_price_rule_exact_path_wins_over_leaf \
  tests/test_change_render.py::test_price_rule_resolves_conditional_leaf \
  tests/test_change_render.py::test_openrouter_unknown_price_rule_is_conservative \
  tests/test_change_render.py::test_price_rule_resolution_does_not_infer_similar_names \
  -v
```

Expected: FAIL because `resolve_price_rule()` does not exist.

- [ ] **Step 7: Implement `resolve_price_rule()`**

Use the binding algorithm in “Resolver contract.” Keep it independent of
`classify_change()`, values, and formatting. Return a new
`ResolvedPriceRule`; never mutate the profile's declaration.

- [ ] **Step 8: Run focused and module tests**

```bash
./.venv/bin/python -m pytest tests/test_provider_profiles.py tests/test_change_render.py -v
```

Expected: all tests PASS. Existing classification output should still be
unchanged at this checkpoint because `_classify_price()` has not switched to
the resolver yet.

- [ ] **Step 9: Run the complete suite and commit the foundation**

```bash
./.venv/bin/python -m pytest
```

Require a clean pass. Review `git diff`, stage only the four Task 1 files,
inspect `git diff --cached --name-only` and `git diff --cached` for sensitive
data, then commit with a message such as:

```text
Add provider price rule resolution
```

## Task 2: Make price classification rule-driven

**Files:**

- Modify: `model_sentinel/change_render.py`
- Modify: `model_sentinel/reporting.py` (private helper re-exports/imports only
  at this step if required)
- Test: `tests/test_change_render.py`
- Test: `tests/test_reporting.py` (test adapters only where required)

- [ ] **Step 1: Write failing classification and shape tests**

Add or update tests that pin:

- `RenderedChange`'s exact dataclass field set includes `price_rule` once;
- price/non-price `price_rule` invariants reject incoherent instances;
- `pricing.prompt: 0.000001 -> 0.000002` becomes `$1.00 -> $2.00`,
  `/1M tokens`, token group/target, explicit million factors, leaf source;
- `pricing.web_search: 0.010 -> 0.014` becomes `$10.00 -> $14.00`,
  `/1K searches`, search group, no normalized target;
- `pricing.request: 0.01 -> 0.02` stays `$0.01 -> $0.02`, `/request`;
- `pricing.image` stays unscaled and uses `/image`;
- `pricing.input_cache_write_1h` stays raw-scaled and uses `/unit unknown`;
- conditional prompt/completion paths carry their leaf rule;
- one-sided values use the same rule/unit but still have no delta/percent;
- zero basis, zero/free, bounded sentinels, shared operand precision, negative
  guards, and percentage semantics remain unchanged in at least token and
  operation-denominated families;
- explicit OpenRouter rules ignore deliberately different profile-wide factors
  (the unit and arithmetic cannot drift apart due to stale local config);
- a synthetic inherited unmatched rule still obeys profile-wide factors.

- [ ] **Step 2: Run the focused classification tests and verify failure**

Run the new nodes plus the existing price block in `tests/test_change_render.py`.

Expected: FAIL because the classifier still uses profile-wide factors,
hardcodes `/1M`, and does not populate `price_rule`.

- [ ] **Step 3: Add `RenderedChange.price_rule` safely**

Add the field and invariants. Update every constructor in
`change_render.py`: price branches pass the resolved object; count, numeric,
boolean, list, scalar, and no-op branches pass `None`. Do not make the field
optional through a default merely to avoid touching constructors—the explicit
constructor value is what keeps the classification contract reviewable.

- [ ] **Step 4: Resolve once in `_classify_price()`**

At the beginning of `_classify_price()`, resolve from the original raw
`field_path`. Use the returned multiplier/divisor for old, new, one-sided, and
delta normalization. Set `unit=rule.unit_label` and `price_rule=rule` in both
two-sided and one-sided returns.

Do not resolve separately for operands or delta. A recorded field change has
one raw field identity and therefore one rule.

- [ ] **Step 5: Rename the money formatter**

Rename `_fmt_price_per_m()` to `_fmt_money()` and update production imports,
re-exports, docstrings, and tests. Preserve its required `precision` signature
and all byte-level formatting behavior. Do not leave a compatibility alias:
the private old name encodes the assumption this feature removes, and an alias
would let new callers perpetuate it.

Keep `_normalize_price(raw_value, multiplier, divisor)` as a unit-neutral
arithmetic primitive if it remains useful; only the money formatter needs the
semantic rename.

- [ ] **Step 6: Repair test fixtures by intent, not by expectation rewriting**

Many current tests use `OPENROUTER_PROFILE.with_pricing(...)` as a convenient
generic conversion fixture. OpenRouter's new explicit rules intentionally make
those bound factors irrelevant for contracted leaves.

Split the fixtures:

- tests of actual OpenRouter behavior keep `OPENROUTER_PROFILE` and adopt the
  new fixed scales/units;
- tests of inherited/custom factors build a synthetic profile whose unmatched
  rule inherits factors and whose labels/predicates are only what the test
  needs.

In `tests/test_reporting.py`, update `_unscaled_price_report()` and the
shared-label provider-factor adapter to use such synthetic inherited profiles.
Those tests must continue proving “this field uses this provider instance's
factor,” not accidentally become tests that OpenRouter ignores configuration.

- [ ] **Step 7: Run classification tests**

```bash
./.venv/bin/python -m pytest tests/test_change_render.py -v
```

Expected: all tests PASS.

Do not commit yet: the behavior switch intentionally changes downstream human
output, which must be updated and fully verified in Tasks 3–5 before the next
commit.

## Task 3: Make canonical token normalization path-aware

**Files:**

- Modify: `model_sentinel/normalize.py`
- Test: `tests/test_normalize.py`

- [ ] **Step 1: Write failing normalization tests**

Cover all of these behaviors:

- current OpenRouter prompt/completion/cache leaves still normalize to the same
  per-million-token floats with standard config;
- those contracted token leaves still normalize correctly when the bound
  provider-wide factors are deliberately different, proving the explicit
  field rules control them;
- a synthetic normalized-field mapping that selects `pricing.web_search` does
  not populate a token snapshot column;
- synthetic request/image/unknown OpenRouter candidates also return `None` for
  a canonical token column;
- generic fallback `input_token_rate` / `output_token_rate` retains configured
  best-effort normalization and the current truthy-candidate semantics;
- when the first candidate is falsy, the selected later candidate's own raw
  path—not the first configured path—is the one resolved;
- model metadata JSON remains the complete canonicalized raw object.

- [ ] **Step 2: Run normalization tests and verify failure**

```bash
./.venv/bin/python -m pytest tests/test_normalize.py -v
```

Expected: at least the operation/unknown rejection and stale-config tests FAIL
because `_profile_field()` discards path identity and `_normalize_price()` uses
the profile-wide factors.

- [ ] **Step 3: Retain candidate identity without changing truthiness**

Add a private helper that returns the first truthy candidate as
`(value, dotted_raw_path)`, or `(None, None)`. Build the dotted path with
`".".join(path)` from the exact candidate tuple. Keep `_profile_field()` for
non-monetary callers by delegating to the new helper and returning only its
value.

Do not change the historical “first truthy candidate” behavior in this task;
zero/empty candidate semantics are separately covered and out of scope.

- [ ] **Step 4: Gate canonical columns by the resolved target**

For `input_price`, `output_price`, `cache_read_price`, and
`cache_write_price`, retain the selected path, coerce the value, resolve its
price rule, and return a normalized value only when
`resolved.normalized_target == PER_MILLION_TOKENS_TARGET`. Otherwise return
`None`.

Use the resolved effective factors for the arithmetic. Do not infer eligibility
from `unit_label`, comparison group, candidate key name, or profile kind.

Import `resolve_price_rule()` from `change_render.py`; the current dependency
graph has no reverse import from `change_render` to `normalize`. If inspection
reveals a new cycle at implementation time, move only the resolver to a small
provider-rule module and update the design first—do not duplicate it.

- [ ] **Step 5: Run normalization and classification modules**

```bash
./.venv/bin/python -m pytest \
  tests/test_normalize.py \
  tests/test_provider_profiles.py \
  tests/test_change_render.py \
  -v
```

Expected: all selected tests PASS.

## Task 4: Route every human renderer and tooltip through the resolved rule

**Files:**

- Modify: `model_sentinel/reporting.py`
- Test: `tests/test_reporting.py`
- Test: `tests/test_render_characterization.py`
- Test: `tests/test_render_changes_characterization.py`
- Test: `tests/test_render_bulk_characterization.py`

- [ ] **Step 1: Add a mixed-unit report fixture**

In `tests/test_reporting.py`, build one conspicuously synthetic OpenRouter
model containing token, web-search, request, image, and unknown monetary
changes. Include two-sided and one-sided rows. Use this shared fixture to pin
the same classified values and unit labels in:

- scan text;
- scan Markdown;
- concise scan HTML;
- full-detail scan HTML;
- `changes` text;
- `changes` HTML detail table;
- scan HTML Change Summary;
- `changes` HTML Change Summary;
- model-card unit/delta/percent cells;
- raw-value continuation rows and price-cell tooltips.

Assertions must inspect the relevant section/card rather than count a string
globally. The fixture must also assert that JSON retains raw values and raw
field paths with no resolved metadata.

- [ ] **Step 2: Add tooltip derivation tests**

Pin at least:

```text
0.000002 (2.0e-6) × 1,000,000 = $2.00
0.014 (1.4e-2) × 1,000 = $14.00
0.02 (2.0e-2) = $0.02
```

Continue asserting that `× 1` is omitted, the scientific notation equals the
raw operand, the derived result equals the visible cell, absent sides have no
tooltip, and no misleading middle-dot operator appears.

- [ ] **Step 3: Run focused report tests and verify failure**

Run the new mixed-unit and tooltip nodes.

Expected: FAIL because active renderers still append `/1M` and tooltip factors
come from the profile rather than the classified rule.

- [ ] **Step 4: Remove renderer-owned units**

Make these changes in `reporting.py`:

- `_render_change_text()` composes present price operands with
  `rendered.unit`; preserve existing text/Unicode structure apart from the
  intentional unit text.
- `_html_raw_and_normalized(raw, display, unit)` accepts the unit explicitly
  and never spells one internally.
- `_render_html_table_row()` passes `rendered.unit` to that helper.
- `_summary_change_detail()` continues to use `rendered.unit`; add regression
  coverage rather than another formatting path.
- model cards and headline values continue reading `rendered.unit`.

Search every production branch, including one-sided price branches. There must
be no active hardcoded `/1M` in `reporting.py` when this step is complete.

- [ ] **Step 5: Make tooltips rule-driven**

Change `_price_conversion_factor()` to accept the resolved effective
multiplier/divisor (or the `ResolvedPriceRule`) instead of `ProviderProfile`.
Change `_card_raw_title()` to read `rendered.price_rule`.

Because `_render_html_card_row()` needs the profile only for the old tooltip
calculation, remove its `profile` parameter after this change and update its
caller in `_render_html_card_table()`. Keep the profile at the table level for
classification.

Do not repeat the unit in the tooltip result; it remains in the adjacent unit
column.

- [ ] **Step 6: Adjust the unit column for explicit labels**

Update `_HTML_CSS` / `_CARD_TABLE_COLGROUP` so `/1K searches`, `/request`, and
`/unit unknown` are readable without overlapping the delta column. Prefer a
slightly wider unit column plus controlled wrapping/white-space behavior over
expanding the whole report excessively. Keep numeric columns aligned.

Add a structural CSS assertion for the chosen rule, but do not rely on CSS
string tests alone; visual verification is required in Task 7.

- [ ] **Step 7: Run reporting tests**

```bash
./.venv/bin/python -m pytest tests/test_reporting.py -v
```

Expected: all focused and existing reporting tests PASS after intent-specific
fixture repairs. Characterization expectations may still need their reviewed
updates in Task 6.

## Task 5: Make headlines and tier-one ordering unit-safe

**Files:**

- Modify: `model_sentinel/reporting.py`
- Test: `tests/test_reporting.py`

- [ ] **Step 1: Write failing headline tests**

Add tests proving:

- a numerically enormous `/1K searches` delta cannot displace a smaller token
  delta from either global headline;
- request, image, and unknown changes likewise cannot become headline movers;
- the panel labels are exactly “Biggest token-rate increase” and “Biggest
  token-rate decrease”;
- if a report has only non-token monetary changes, the Price Movement card,
  verdict, tallies, affected-model list, tier-one card, and Change Summary rows
  remain present, but both headline panels are omitted;
- higher/lower/mixed/coverage buckets and field/model counts still aggregate
  across all monetary unit families;
- additions/removals stay coverage-only and never become headline candidates.

- [ ] **Step 2: Write failing impact-order tests**

Add a deliberately adversarial order containing:

- a model with a small primary token delta;
- a model with a much larger displayed search delta and no token delta;
- request/image-only models whose alphabetical order conflicts with magnitude
  order;
- an unknown-unit-only model;
- a one-sided-only price model.

Assert that the token mover leads, every monetary model remains tier one, and
all models without a primary score follow in case-insensitive model-ID order.
Keep the existing tests for rounded-dollar, paired-percent, coverage, and ID
tie-breaks among primary token movers.

Update the existing one-sided-only ordering expectation where necessary: with
no primary magnitude, alphabetical model ID—not a fabricated zero-dollar score
or coverage count—controls ordering.

- [ ] **Step 3: Run the impact nodes and verify failure**

Run the new nodes plus:

```bash
./.venv/bin/python -m pytest \
  tests/test_reporting.py::test_price_movement_headline_names_the_biggest_dollar_mover \
  tests/test_reporting.py::test_impact_sort_leads_with_the_largest_absolute_dollar_move \
  tests/test_reporting.py::test_impact_sort_breaks_a_cents_rounded_tie_with_percent \
  tests/test_reporting.py::test_impact_sort_breaks_a_percent_tie_with_coverage_count \
  tests/test_reporting.py::test_impact_sort_falls_back_to_the_model_id \
  tests/test_reporting.py::test_a_one_sided_price_change_sorts_at_zero_dollars \
  -v
```

Expected: new mixed-unit tests FAIL because all deltas currently compete. Some
existing test names/comments will need semantic renaming, but their primary
token assertions must not be weakened.

- [ ] **Step 4: Filter headline candidates without filtering counts**

Keep `_price_movement_kind()` as the all-unit count/direction gate. In
`_collect_price_movement_summary()`, classify each qualifying change as today,
but allow it into `top_increase`/`top_decrease` only when all are true:

- it is two-sided and has `delta_abs`;
- `rendered.price_rule` is present;
- its group equals the profile's non-`None` primary group;
- its group equals `USD_PER_MILLION_TOKENS_GROUP`.

This explicit final condition is the safety boundary for the single global
token-rate panel. Do not compare two different groups and then choose a panel
label after the fact.

Rename stale “per-1M” comments/docstrings to “primary token-rate” where
appropriate. Render the two labels as “Biggest token-rate increase/decrease.”

- [ ] **Step 5: Separate tier membership from primary score**

Refactor `_ModelImpact` and `_model_price_impact()` to the nullable-primary
contract above:

- set `moved=True` for every movement returned by `_price_movement_kind()`;
- count one-sided coverage as today;
- classify two-sided changes, but consider `(delta, percent)` only when the
  resolved comparison group equals the profile's declared primary group;
- return `None` only when no monetary movement exists at all;
- return an impact object with `primary_delta=None` when the model moved only
  in non-primary or coverage-only ways;
- never use a non-primary percent in sorting.

Preserve the invariant that Price Movement membership and tier-one membership
share `_price_movement_kind()` as their gate.

- [ ] **Step 6: Run reporting and characterization regression tests**

```bash
./.venv/bin/python -m pytest \
  tests/test_reporting.py \
  tests/test_render_characterization.py \
  tests/test_render_changes_characterization.py \
  tests/test_render_bulk_characterization.py \
  -v
```

Expected: reporting behavior tests PASS. Characterization tests may fail only
on the intentional unit/headline strings enumerated in Task 6; JSON diffs are
not acceptable.

## Task 6: Review characterization output and update documentation

**Files:**

- Modify: `tests/test_render_characterization.py`
- Modify: `tests/test_render_changes_characterization.py`
- Modify only if justified: `tests/test_render_bulk_characterization.py`
- Modify: `README.md`
- Modify: `docs/DESIGN.md`
- Modify: `docs/provider_schema_notes.md`
- Modify: `docs/report_readability_redesign_design.md`
- Modify: `providers.env.template`

- [ ] **Step 1: Review golden diffs field by field**

For each failing characterization assertion, compare actual and expected
output. Accept only these intentional classes:

- OpenRouter contracted token units change from `/1M` (or spaced `/ 1M`) to
  `/1M tokens`;
- tooltip factors stay numerically identical for token fields but now come from
  the resolved rule;
- headline labels gain “token-rate”;
- any mixed-unit fixture added to a characterization module shows its declared
  scale/unit;
- unit-column CSS changes.

Add a dated “deliberate update” note near the characterization module's
existing audit history. Do not bulk-replace expected strings before reading the
diff.

JSON goldens, raw value strings, raw field paths, model order outside the
approved impact rule, Pricing row order, and stored/history shapes must remain
unchanged. Any such diff is a defect to investigate, not a golden update.

- [ ] **Step 2: Update README configuration/reporting guidance**

Document that `PRICE_MULTIPLIER`/`PRICE_DIVISOR` remain required but are now
fallback/inherited factors. Registered field rules may provide explicit
schema-defined scales. List the initial OpenRouter display families concisely
and state that unknown OpenRouter price leaves render `/unit unknown` without
entering token snapshot columns or absolute headlines.

Do not add an override syntax or search-count cost examples.

- [ ] **Step 3: Update architecture documentation**

In `docs/DESIGN.md`:

- extend the Provider Profiles section with rule declarations and resolution
  precedence;
- state that canonical price columns remain per-million-token and use the
  rule's normalized target;
- document `RenderedChange.price_rule` as presentation-only;
- document all-unit direction/count versus primary-group absolute comparison;
- remove per-field price rules from deferred work, while leaving a registered
  Abacus profile and runtime override layer deferred.

- [ ] **Step 4: Update provider schema notes**

In `docs/provider_schema_notes.md`:

- replace the OpenRouter provider-wide pricing claim with the verified initial
  field families and conservative unmatched behavior;
- remove `pricing.request` from deferred work because it is handled here;
- keep authenticated Abacus validation and its dedicated profile deferred;
- clarify that the mechanism now exists but does not justify guessing Abacus
  media units.

- [ ] **Step 5: Amend the historical readability design**

In `docs/report_readability_redesign_design.md`, append a dated amendment that
supersedes its fixed `/1M` assumptions. Explain that A1, D1, R1, summaries, and
the unit column now consume the resolved per-field rule; the global headline
is token-rate-only; all-unit direction/tiering remains.

Preserve the document as an implementation history rather than silently
rewriting old decisions.

- [ ] **Step 6: Update the configuration template**

In `providers.env.template`, clarify:

- canonical stored price columns are per million tokens;
- factors apply to inherited/fallback rules;
- OpenRouter's known price leaves use explicit registered rules;
- Abacus remains generic and `1 / 1` is still known incomplete.

Keep every example synthetic/general and add no secrets or local state.

- [ ] **Step 7: Run all characterization modules**

```bash
./.venv/bin/python -m pytest \
  tests/test_render_characterization.py \
  tests/test_render_changes_characterization.py \
  tests/test_render_bulk_characterization.py \
  -v
```

Expected: all PASS after reviewed intentional updates.

## Task 7: Complete verification, visual QA, and delivery

**Files:** all changed files

- [ ] **Step 1: Run static assumption searches**

```bash
rg -n '_fmt_price_per_m' model_sentinel tests
rg -n '/1M|/ 1M' model_sentinel/reporting.py model_sentinel/change_render.py
rg -n 'price_multiplier|price_divisor' model_sentinel/reporting.py model_sentinel/normalize.py
rg -n 'estimated cost|1/3/10|three searches|ten searches' README.md docs model_sentinel tests
```

Expected:

- the retired formatter name has no matches;
- render/classification modules contain no active hardcoded unit assumption
  (comments/docstrings should also use truthful terminology);
- reporting has no profile-wide conversion-factor reads, and normalization
  accesses factors only through the resolved rule;
- no deferred search-count estimate or override feature entered the change.

The literal `/1M` remains valid in the generic fallback declaration and in
historical documentation that is clearly marked as superseded.

- [ ] **Step 2: Run the CLI help smoke test**

```bash
./.venv/bin/python ./model-sentinel --help
```

Expected: exit 0 and normal command help.

- [ ] **Step 3: Generate and visually inspect a synthetic mixed-unit report**

Using `./.venv/bin/python`, render a report with conspicuously synthetic model
IDs and the mixed-unit fixture values to a temporary path outside the
repository (for example `/tmp/model_sentinel_mixed_units.html`). Do not use
live/provider/account data.

Open the file and verify:

- `/1M tokens`, `/1K searches`, `/request`, `/image`, and `/unit unknown` fit
  or wrap cleanly;
- unit text does not overlap delta/percent columns at desktop and narrow width;
- tooltips show the correct factor for each field;
- selectable raw rows preserve provider literals;
- Change Summary matches model-card units;
- only token-rate headline panels appear;
- non-primary-only models remain in the open tier-one section after scored
  token movers.

- [ ] **Step 4: Run the complete mandatory suite**

```bash
./.venv/bin/python -m pytest
```

Expected: exit 0 with no failed, errored, or skipped tests. Do not claim
completion, commit, or proceed with a known failure.

- [ ] **Step 5: Review the complete diff for scope and regressions**

Run:

```bash
git diff --check
git status --short
git diff --stat
git diff
```

Confirm specifically:

- no configuration override layer or search-count estimates were added;
- no Abacus profile was registered;
- no database/model/storage/diff schema changed;
- JSON expectations remain byte-shape compatible;
- raw paths and raw values remain unchanged;
- no logging, validation, or tests were removed/disabled;
- no secrets, personal data, realistic private values, generated reports, or
  mutable runtime state are present.

- [ ] **Step 6: Stage, inspect, and commit the feature**

Stage only the intended implementation, tests, and documentation. Then run:

```bash
git diff --cached --name-only
git diff --cached --check
git diff --cached
```

Inspect the complete staged list and diff for sensitive data as required by
this public repository. Commit only after the full suite and staged review are
clean, with a message such as:

```text
Support per-field pricing units
```

- [ ] **Step 7: Report deployment separation**

The repository implementation is complete after the clean commit. Explicitly
state that the installed standalone executable was not rebuilt. If the user
later authorizes deployment, follow the standalone provenance workflow and
run `install_standalone.sh` as a separate operation with its own verification.

## Acceptance criteria

The implementation is complete only when all of these are true:

1. One resolver maps an exact raw monetary path to one validated effective
   rule using exact path, leaf, then unmatched precedence.
2. `RenderedChange` carries that resolved rule once, and every price renderer
   derives factors/unit from it.
3. OpenRouter token, web-search, request, and image examples render with the
   exact approved scales and units; unknown monetary leaves render
   `/unit unknown` without inferred semantics.
4. OpenRouter contracted rules cannot be made numerically inconsistent with
   their labels by stale provider-wide factors.
5. Generic fallback behavior remains configurable, `/1M`, token-normalizable,
   and excluded from absolute headline comparison.
6. Canonical snapshot price columns accept only rules targeted to
   `per_million_tokens`; existing OpenRouter and generic token values remain
   unchanged.
7. Every required text/Markdown/HTML surface uses the same unit and retains raw
   provider values/paths; JSON and persistent schema do not acquire rule data.
8. Tooltips show the effective field conversion, omit `× 1`, and agree with
   visible values.
9. Direction, percentages, counts, affected-model lists, Change Summary rows,
   and tier-one inclusion cover all monetary unit families.
10. Absolute headlines are token-rate-only, and model impact compares only the
    active profile's declared primary group.
11. Non-primary-only and coverage-only monetary models remain tier one, follow
    scored primary movers, and sort by model ID without a fabricated magnitude.
12. The HTML unit column passes visual inspection for all five initial labels.
13. No runtime override syntax, search-count cost estimate, Abacus profile,
    storage migration, or standalone rebuild is included.
14. The CLI help smoke test and the complete pytest suite pass with no failures,
    errors, or skips.
15. The complete staged diff is free of sensitive data and only contains
    intended repository artifacts.
