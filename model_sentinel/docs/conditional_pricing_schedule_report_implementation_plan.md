# Conditional Pricing Schedule Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Interpret provider-supplied conditional pricing as one auditable schedule or ordered rule set per exact model-comparison edge, and present it consistently in every existing human report without changing stored data or public JSON.

**Architecture:** Add a provider-neutral conditional-pricing interpreter with provider-owned selector and policy semantics. Feed it complete old/new model metadata through a separate live edge map and typed stored scrape-edge envelopes, then build one pre-filter semantic presentation plan that all text, Markdown, HTML, summary, and tally renderers consume. Keep scalar rendering, SQLite rows, canonical snapshots, JSON keys, JSON values, and Browse behavior unchanged.

**Tech Stack:** Python 3.11+ standard library, frozen dataclasses, SQLite, existing `pytest` suite, self-contained HTML/CSS with no JavaScript.

**Approved design:** [`docs/superpowers/specs/2026-08-28-conditional-pricing-schedule-report-design.md`](superpowers/specs/2026-08-28-conditional-pricing-schedule-report-design.md)

---

## Delivery constraints

- This plan authorizes implementation only after the user separately asks to execute it.
- Work on a normal `codex/` feature branch in the existing checkout. Do not create a worktree unless the user explicitly requests one.
- Use only conspicuously synthetic public fixtures. Do not copy provider account data, real report payloads, runtime database contents, credentials, holdings, or personal details into this public repository.
- Do not migrate or rewrite SQLite. Do not modify the shapes or values of scan, history, or changes JSON.
- Do not add conditional-pricing behavior to Browse in this feature.
- Use the project virtual environment for every Python or pytest command: `source .venv/bin/activate` first. Never invoke Homebrew/system Python directly.
- Run the complete test suite with zero skips before delivery. No failing test may be dismissed.
- After every task's focused GREEN step, run `source .venv/bin/activate && pytest` and require the complete suite to pass with zero skips before making that task's commit. The focused command is diagnostic; the full suite is the commit gate.

## Repository map and file responsibilities

| File | Responsibility in this change |
|---|---|
| `model_sentinel/conditional_pricing.py` | New focused module containing event identities, parsed selectors/rules/policies, weekly UTC segments, interpretation states, comparison facts, absorption references, accounting, and `interpret_conditional_pricing(...)`. It must not format HTML or access SQLite. |
| `model_sentinel/provider_profiles.py` | Add immutable condition descriptors and policy-evaluation semantics; register OpenRouter's four rich selectors; preserve legacy selector construction for one compatibility period. |
| `model_sentinel/storage.py` | Load exact source/target scrape-edge records and exact snapshot metadata into internal typed envelopes; project those records back to the unchanged legacy history events and changes dictionaries. No schema change. |
| `model_sentinel/cli.py` | Preserve live baseline/current metadata, create live comparison events, request stored edge envelopes for human reports, and reuse one semantic report plan across primary and companion formats. |
| `model_sentinel/reporting.py` | Build the pre-filter model semantic plan; remove absorbed rows exactly once; integrate composite blocks with ordinary rows, Price Movement, Change Summary, text/Markdown/HTML, history, and changes. JSON branches remain legacy projections. |
| `model_sentinel/change_render.py` | Reuse existing scalar price resolution/formatting primitives where useful; add only narrowly reusable public helpers needed by the composite renderer. Do not force a schedule into `RenderedChange`. |
| `tests/conditional_pricing_fixtures.py` | New conspicuously synthetic six-rule OpenRouter-shaped policy and event builders used by pure and renderer tests. |
| `tests/test_conditional_pricing.py` | New pure interpreter tests for parsing, identity, UTC coverage, precedence, grouping, fallback, comparison, absorption, and accounting. |
| `tests/test_conditional_pricing_reporting.py` | New cross-format and cross-command semantic/report tests, including concise/all/squelched behavior and legacy JSON contracts. |
| `tests/test_provider_profiles.py` | Rich descriptor registration, policy semantics, immutability, and legacy-construction compatibility. |
| `tests/test_storage.py` | Exact-edge grouping, side metadata, same-day multi-edge isolation, missing-side behavior, date filtering, legacy projection, and bounded-query performance. |
| `tests/test_cli.py` | Live metadata plumbing, stored-report plumbing, companion-plan reuse, format matrix, and explicit-output behavior. |
| `tests/test_reporting.py` | Existing shared-plan, tally, summary, color, ordering, no-op, anchor, and visibility invariants affected by the fifth model bucket. |
| `tests/test_render_characterization.py` | Keep existing scan characterization outputs stable outside the new synthetic conditional fixture. |
| `tests/test_render_changes_characterization.py` | Keep current changes text/HTML behavior and JSON row passthrough stable outside conditional events. |
| `README.md` | Explain conditional schedule/rule/fallback presentation, UTC meaning, human-vs-JSON behavior, and command coverage. |
| `docs/DESIGN.md` | Record the event-scoped semantic layer, stored-edge input, no-migration rule, and conditional model bucket. |
| `docs/provider_schema_notes.md` | Record OpenRouter's documented strict threshold, conjunction, per-key later precedence, inherited omission, default base, weekday, and half-open/wrapping UTC semantics with the official source link. |
| `docs/report_readability_redesign_design.md` | Amend the implemented report contract from four to five Price Movement buckets and describe composite pricing blocks and central accounting. |

## Binding internal contracts

The executor may choose local helper names, but these public and cross-module contracts are binding.

### Provider semantics

Add frozen types in `model_sentinel/provider_profiles.py` equivalent to:

```python
ConditionFamily = Literal["time", "threshold"]
ConditionSemanticRole = Literal[
    "utc_weekdays",
    "utc_start_inclusive",
    "utc_end_exclusive",
    "integer_strictly_greater",
]

@dataclass(frozen=True)
class ConditionalPricingConditionDescriptor:
    field_name: str
    family: ConditionFamily
    semantic_role: ConditionSemanticRole
    parse_value: Callable[[Any], Any]
    canonical_identity: Callable[[Any], Hashable]
    format_value: Callable[[Any], str]
    participates_in_interval_grouping: bool

@dataclass(frozen=True)
class ConditionalPricingConditionSetSemantics:
    missing_weekdays: Literal["all_seven"]
    missing_endpoints: Literal["all_day"]
    endpoint_pairing: Literal["both_or_neither"]
    equal_endpoints: Literal["unsupported"]

@dataclass(frozen=True)
class ConditionalPricingPolicySemantics:
    condition_combination: Literal["all_conditions"]
    rule_precedence: Literal["later_per_key"]
    omitted_price_behavior: Literal["retain_prior_or_base"]
    top_level_price_role: Literal["default_base"]
```

Extend `ProviderProfile` with an immutable descriptor registry, optional condition-set/policy semantics, and an immutable `pricing_override_base_paths: Mapping[str, str]` from override dimension name to exact top-level base path. Append these new fields after every existing dataclass field so the old positional construction order is unchanged. Defensive-copy both new registries in `ProviderProfile.__post_init__` exactly as the pricing registries are copied today, and preserve every proxy identity in `with_pricing()` after validation. Rich descriptors override a legacy field of the same name.

The existing `pricing_override_condition_fields` tuple remains constructible for one compatibility period. A legacy-only name is selector identity only: it prevents monetary classification, but supplies no validation operator, interval grouping, ordering, inheritance, or comparison authority. A provider with no rich policy semantics can therefore produce a selector-safe `raw-fallback`, never borrowed OpenRouter semantics.

OpenRouter registers:

| Raw field | Parse and identity contract | Display/evaluation contract |
|---|---|---|
| `min_prompt_tokens` | JSON integer, never `bool`; canonical integer | `Prompt > N tokens`; strictly greater than, not greater-or-equal; threshold rules remain ordered rules |
| `utc_days` | list of unique lowercase full weekday names; canonical Monday-to-Sunday tuple; absent means all seven; empty/duplicate/unknown invalid | request-instant UTC civil-day membership; list order is semantic noise |
| `utc_start` | JSON integer HHMM, never `bool`; hours 0-23 and minutes 0-59; canonical minute-of-day | inclusive boundary; requires `utc_end` |
| `utc_end` | same HHMM validation and canonicalization | exclusive boundary; requires `utc_start`; a positive start with end `0` displays `24:00` |

The OpenRouter condition-set semantics are `all_seven`, `all_day`, `both_or_neither`, and `unsupported`; policy semantics are `all_conditions`, `later_per_key`, `retain_prior_or_base`, and `default_base`. The base-path registry maps every registered override price dimension to its exact `pricing.<dimension>` path. The provider-neutral compiler may branch on semantic roles and declared semantics, never on the raw names `min_prompt_tokens`, `utc_days`, `utc_start`, or `utc_end`. The official contract source is <https://github.com/OpenRouterTeam/terraform-provider-openrouter/blob/main/docs/data-sources/model.md>.

### Comparison event and result

Define the format-neutral boundary in `model_sentinel/conditional_pricing.py`:

```python
def interpret_conditional_pricing(
    event: PricingComparisonEvent,
    profile: ProviderProfile,
) -> ConditionalPricingInterpretation | None
```

Use separate frozen identity types so an event cannot be accidentally keyed by display time:

```python
@dataclass(frozen=True)
class LiveComparisonIdentity:
    provider_id: str
    provider_model_id: str
    baseline_scrape_id: int | None
    attempt_scrape_id: int

@dataclass(frozen=True)
class StoredComparisonIdentity:
    provider_id: str
    provider_model_id: str
    from_scrape_id: int | None
    to_scrape_id: int
```

`PricingComparisonEvent` carries one of those identities plus `provider_id`, `provider_model_id`, `display_name`, `detected_at`, source/target timestamps when known, every `FieldChange` for that exact edge, and exact old/new canonical model metadata dictionaries or `None`. `detected_at` is display/filter metadata only.

`interpret_conditional_pricing` returns `None` only when no exact `pricing.overrides` parent change exists. One malformed parent or multiple parent occurrences return a typed result with `state="raw-fallback"`; neither may fall into `_expand_pricing_override_changes` or scalar money classification.

The immutable result must keep these concerns distinct:

```text
state: grouped-schedule | ordered-rules | raw-fallback
semantic_change: bool               # distinct from canonical evidence changing
fallback_reason: unknown or unsafe semantics only
grouping_inhibition_reasons: understood policy that cannot be collapsed
comparison_inhibition_reasons: displayed policy without a valid directional basis
transition: added | removed | changed
old_policy / new_policy
absorbed_base_price_changes: occurrence-aware references
comparison: only provable direct, region, and coverage facts
accounting: the sole source for report counts and model bucket
source_changes: ordered tuple of occurrence-referenced canonical parent changes
```

Fallback reasons are stable internal codes, not exception strings. Renderers map them to safe prose and disclose the canonical stored parent values in the same artifact.

### Occurrence-aware provenance and consumption

Create an occurrence-aware reference from `(field_name, canonical_json(old_value), canonical_json(new_value), occurrence)` while walking the edge's source order. Use it for parent identity, sibling absorption, raw-evidence links, and consume-once enforcement. Never use field path alone; repeated equal rows and expanded structured children must not bind to the wrong source evidence.

A sibling base price change may be absorbed only when all are true:

1. it belongs to the exact same comparison identity;
2. both event-side metadata objects exist;
3. its path exactly equals the profile's base path for a dimension in the union of registered override dimensions explicitly present on either event side;
4. its resolved rule is not `match_source="unmatched"`, and its unit and comparison group equal the schedule column's unit/group;
5. its old/new values, including absence, equal the exact values read from old/new metadata at that registered base path;
6. the composite retains its exact old/new provider values and direct movement fact; and
7. its occurrence reference has not already been consumed.

`raw-fallback` and `missing_event_snapshot` absorb nothing. Unrelated price dimensions, including request/image/search prices not present in the policy dimensions, remain ordinary rows and are counted once.

### Stored envelopes and legacy projections

Add frozen internal records in `model_sentinel/storage.py` for a stored change row and `StoredComparisonEvent`. Key events by `(provider_id, provider_model_id, from_scrape_id, to_scrape_id)` and retain all source rows in `change_id` order, source/target scrape timestamps, and exact source/target `snapshot_models.metadata_json` values. `StoredComparisonEvent` has these fields:

```text
identity: StoredComparisonIdentity
provider_label / display_name
detected_at / from_completed_at / to_completed_at
source_rows: tuple[StoredChangeRecord, ...]
field_changes: tuple[FieldChange, ...]
old_model_metadata / new_model_metadata: dict[str, Any] | None
```

Define `StoredComparisonDataError(RuntimeError)` in `model_sentinel/storage.py` for malformed exact-side metadata or internally inconsistent rows on one persisted edge. Its message identifies the four-part edge and the failed invariant without echoing stored metadata values. The new rich methods raise this type; legacy methods retain their current exception behavior.

Keep the current legacy row paths independent from the new rich human-report path. `Store.history_events(...)` and `Store.recent_changes(...)` remain source-compatible and must not select or decode snapshot metadata. JSON-only CLI branches call only those legacy methods, so corrupt or absent `snapshot_models.metadata_json` cannot introduce a new JSON failure. Add exact rich methods and frozen return types for human rendering:

```text
Store.history_comparison_events(...) -> tuple[StoredComparisonEvent, ...]
Store.recent_comparison_events(...) -> tuple[StoredComparisonEvent, ...]

HistoryReportInputs
  first_seen / last_seen
  events: tuple[HistoryEvent, ...]
  comparison_events: tuple[StoredComparisonEvent, ...]

ChangesReportInputs
  changes: tuple[dict[str, Any], ...]
  comparison_events: tuple[StoredComparisonEvent, ...]
```

`cli.py` composes each `*ReportInputs` only for human formats. The new rich SQL selects the persisted `from_scrape_id` and `to_scrape_id`, left-joins the model row and scrape timestamp at each exact scrape, and obtains the edge-side display names separately from the legacy latest-name join. Human display uses target-side name, then source-side name, then model ID; legacy changes JSON keeps the current latest-snapshot `display_name` rule. A missing side join produces `None` metadata and `missing_event_snapshot`; it does not look elsewhere. Malformed exact-side metadata produces a deterministic human-path storage error, while the legacy methods and JSON remain unaffected because they never decode it.

Select candidate edge identities first, then load every row for each selected four-part identity in `change_id` order. Every row on one edge must agree on `detected_at`; disagreement is a deterministic storage invariant error, never a partially filtered event. Apply the command's existing local-date inclusion rule to the edge timestamp while retaining the whole edge.

Legacy projections are exact:

- history events retain only `detected_at`, `change_kind`, `field_name`, `old_value`, and `new_value`;
- changes dictionaries retain only the current keys and order/value population from `Store.recent_changes()`; and
- changes still excludes initial-baseline rows whose `from_scrape_id` is null.

### Shared semantic core, artifact projections, and stored aggregation

Keep three ownership layers separate:

1. `ModelEventSemanticCore` is built once per comparison event. It contains conditional interpretation, occurrence provenance, direct price facts, absorption decisions, semantic equality, and event accounting. It contains no `ReportDetailPolicy`, visibility, formatted prose, CSS class, tier, or anchor.
2. `ArtifactDetailProjection` is built per requested detail mode from the shared core. It owns visible ordinary rows, unclassified-budget consumption, hidden rollups, conditional-block visibility, and all-detail evidence. Default and all projections are distinct objects with identical semantic accounting. Squelched projections omit Price Movement and conditional blocks without recalculating them.
3. Renderer-local anchor tables are built after each artifact's final card set and document order are known. Semantic cores carry stable event/provenance identities, never HTML IDs.

Add explicit builders in `model_sentinel/reporting.py`:

```text
build_scan_semantic_core(provider_results, live_events) -> ScanSemanticCore
build_history_semantic_core(events, comparison_events, profile) -> HistorySemanticCore
build_changes_semantic_core(changes, comparison_events, provider_profiles) -> ChangesSemanticCore
project_*_detail(core, detail_policy) -> artifact-specific projection
```

Existing render entry points remain source-compatible. Add optional keyword-only `semantic_core`/`detail_projection` inputs; when absent, direct callers take the compatibility path. Every JSON branch returns before building or reading semantic cores.

Detail-budget ownership remains exactly current behavior: scan owns one unclassified budget per provider; changes owns one per local-date/provider block even when that block contains several exact edges; ordinary history rows retain their current byte-level behavior in default/all/squelched modes. This feature does not repair the existing `field_changed` versus `changed` history-filter mismatch. Conditional parents and safely absorbed siblings are removed before the applicable ordinary-row budget is consumed.

`changes` renders and summarizes exact edges but folds Price Movement by unique `(provider_id, provider_model_id)` over the selected range:

- Change Summary: one row per semantic model comparison edge.
- Model count/bucket: one per unique provider/model. If any edge has a semantic conditional change, the unique model is exclusively `conditional`; otherwise union all edge directions (`up` only, `down` only, both, or coverage only) into the existing four buckets.
- Field/policy/rule/dimension/band counts: sum event accounting, never deduplicate across edges.
- Conditional headline: state both unique model count and conditional comparison-event count when they differ.
- Affected-model entry: render once, include an ordered link for every semantic edge card, and label multiple links by local target timestamp.
- Edge-card anchor identity: `(provider_id, provider_model_id, from_scrape_id, to_scrape_id)`; never the provider/model pair alone.

For a same-model add-then-remove schedule fixture, the report therefore shows one conditional model, two conditional comparison events, two edge cards, two Change Summary rows, and two valid links from the one affected-model entry. This is the binding resolution of repeated-edge aggregation.

### Weekly UTC compilation

Represent time coverage internally as half-open `(weekday_index, start_minute, end_minute)` segments with `0 <= start < end <= 1440`. For each selected UTC civil day:

```text
no endpoints       -> [0, 1440)
start < end        -> [start, end)
start > end        -> [0, end) plus [start, 1440) on that same selected day
start == end       -> raw fallback unless a future provider explicitly defines it
```

Do not carry a wrapped interval into an unselected next day. Friday-only `22:00-02:00` matches Friday 01:00 and Friday 23:00, not Saturday 01:00. If Saturday is also selected, Saturday receives its own two same-day segments.

Grouped schedule is allowed only for valid time-only rules, complete event-side base vectors, registered price dimensions/units, no unknown keys, and non-overlapping weekly segments. For each disjoint rule region, start from the base vector and apply that rule's explicit assignments. The complement of all rule regions is the uncovered default region. Group display windows only after effective vectors and coverage are proven; two regions with the same complete vector count as one effective band. Count the uncovered default only if it has nonempty coverage and its vector is distinct from every counted rule vector.

Any valid overlap, duplicate semantic condition, threshold rule, or understood compound time-plus-threshold rule produces `ordered-rules` and keeps source order. In that state, show only explicit assignments and `not set by this rule`; do not claim direct base inheritance or enumerate intersections. Later matching rules win per key according to the registered provider policy.

An unknown selector, unknown non-condition key, invalid selector/value, unresolved price unit, malformed parent, or missing provider policy semantics produces `raw-fallback`. Registered selector fields remain nonmonetary even inside fallback.

Missing exact-side snapshot data is not unknown policy semantics. If selectors and explicit assignments parse, use `ordered-rules`, add `missing_event_snapshot` to comparison/grouping inhibition, infer no effective vectors or aggregate direction, and absorb nothing. Multiple parent occurrences use `raw-fallback`, retain every occurrence-referenced parent in source order, and consume every parent occurrence before scalar expansion so no selector can fall through.

Across event sides, match rules by `(canonical condition identity, occurrence)`. Task 2 performs parsing, identity, occurrence matching, and structural comparison only. Final `semantic_change` is decided in Task 3 after overlap and precedence analysis exists. A source reorder is semantic noise only if rules are disjoint or all possibly overlapping assignments commute per key. Reordering overlapping rules with different values for a shared key remains a semantic policy change. Evidence-only reorder remains in JSON and all-detail evidence, produces no concise schedule block, and contributes zero conditional policy/model counts.

### Direction, accounting, and display policy

Compare movement per price dimension and only within identical units and provider-declared comparison groups. Supported bases are deliberately bounded to:

- a grouped policy versus a single complete default vector;
- grouped policies with the same canonical region partition; or
- exact matched regions/dimensions with complete identity and basis.

Different partitions, ordered rules, fallback, or missing snapshots receive no aggregate envelope direction. A band is higher only when every comparable dimension is unchanged-or-higher and at least one is higher; lower is symmetric; opposite movement is mixed; incomplete basis is not comparable. Emit a band-level percentage only when every included comparable dimension has the same percentage. Use `peak` only if one complete vector weakly dominates every other relevant vector in all included dimensions; otherwise use neutral band labels. Never aggregate unlike units.

The report planner creates one `ModelPricingAccounting` record for every changed model event, including events for which `interpret_conditional_pricing(...)` returns `None`. It merges all direct ordinary price facts before detail filtering, absorbed facts exactly once, and the optional conditional contribution. All Price Movement counts, outcomes, tiering, Change Summary tallies, and affected-model lists consume this record; no consumer rediscovers movement by scanning `_FieldDisplayPlan.visible`.

Each accounting record contains:

- base price field changes, including absorbed rows, counted once;
- conditional policies changed;
- source-rule count from the displayed policy side;
- schedule-dimension union across old/new explicit override assignments;
- distinct complete effective-band count, using the uncovered-default rule above; and
- exactly one model bucket: `higher`, `lower`, `mixed`, `coverage`, or `conditional`.

Conditional policy addition/removal/semantic change puts the model only in `conditional`, even when absorbed or nonabsorbed direct prices moved. Evidence-only canonical parent changes do not. Added and changed transitions take rule/dimension/band counts from the new/displayed policy; removed transitions take them from the old/displayed policy. Ordinary verdicts are derived from the four existing buckets; if conditional is the only pricing bucket, say `conditional pricing changed`; if ordinary direction exists too, preserve it and append `conditional pricing also changed` with the model count. Unknown is never mixed.

Build semantic plans before detail filtering. Default and all-detail modes must therefore share verdicts and counts. In `squelched` mode, omit Price Movement and conditional schedule panels rather than recomputing a second truth from filtered rows. Raw fallback remains self-contained in default mode.

### Shared price-value contract

Task 4 must extract a narrow mandatory format-neutral contract from `model_sentinel/change_render.py`; it is not optional. Use types/functions equivalent to:

```text
ResolvedPriceValue
  field_path / raw_value / raw_display
  normalized_value: float
  price_rule: ResolvedPriceRule

resolve_price_value(field_path, raw_value, profile) -> ResolvedPriceValue | None
format_price_values(values, *, precision_basis) -> tuple[str, ...]
```

`resolve_price_value` rejects booleans, nonnumeric values, and unmatched rules when called for a conditional schedule. `format_price_values` reuses the existing shared precision and bounded-sentinel implementation. Refactor scalar `_classify_price` to consume the same primitives, so composite columns and scalar rows cannot diverge on provider factors, raw values, `free`, tiny positive values, units, or precision. Comparison arithmetic uses the same resolved normalized values; schedules are not represented as fake `FieldChange` or `RenderedChange` instances.

## Task 0: Characterize compatibility before production changes

**Files:**

- Modify: `tests/test_render_characterization.py`
- Modify: `tests/test_render_changes_characterization.py`
- Modify: `tests/test_reporting.py`
- Modify: `tests/test_storage.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Record the starting full-suite result.** Run `source .venv/bin/activate && pytest`. Expected: every current test passes with zero skips. Record the actual collected/pass count and duration in the implementation work log; stop and fix any failure before adding characterizations.
- [ ] **Step 2: Add exact legacy JSON characterizations.** Pin parsed key sets, values, and row order for scan/history/changes using existing synthetic fixtures. Add the later-snapshot rename case proving changes JSON uses the current latest display name. Add malformed snapshot metadata while valid field-change JSON still allows `Store.history_events(...)`, `Store.recent_changes(...)`, and both JSON reports to succeed unchanged.
- [ ] **Step 3: Characterize current ordinary history detail behavior.** Pin byte-identical nonconditional history text and Markdown for `default`, `all`, and `squelched`, including the existing `field_changed` behavior. This feature must not silently repair it.
- [ ] **Step 4: Characterize construction and call compatibility.** Construct `ProviderProfile` with the complete pre-feature positional argument order and assert every field. Call `render_scan_report`, `render_history_report`, and `render_changes_report` with their existing signatures and no semantic core. Pin managed companion generation and explicit-output-only behavior.
- [ ] **Step 5: Run focused and complete GREEN.** Run `source .venv/bin/activate && pytest tests/test_render_characterization.py tests/test_render_changes_characterization.py tests/test_reporting.py tests/test_storage.py tests/test_cli.py -q`, then `source .venv/bin/activate && pytest`. Expected: all focused and complete tests pass with zero skips and production files remain untouched.
- [ ] **Step 6: Commit.** Stage only characterization tests, inspect the full staged diff for sensitive data, and commit with `Characterize pricing report compatibility`.

## Task 1: Freeze the compatibility baseline and add the provider semantics

**Files:**

- Modify: `model_sentinel/provider_profiles.py` (`ProviderProfile`, `__post_init__`, `with_pricing`, `OPENROUTER_PROFILE`)
- Modify: `tests/test_provider_profiles.py`
- Create: `tests/conditional_pricing_fixtures.py`

- [ ] **Step 1: Add failing provider-profile contract tests.** Cover rich descriptor/semantic-role validation, condition-set semantics, both registry defensive copies, frozen behavior, `with_pricing()` preservation, append-only positional compatibility, OpenRouter's exact four descriptors/policy tuple/base-path registry, rich-over-legacy precedence, and construction of a legacy-only synthetic profile whose selector is identity-only. Register a fake provider using different raw selector names with the same semantic roles; it must later compile identically without raw-name branches.
- [ ] **Step 2: Run the focused tests and confirm RED.** Run `source .venv/bin/activate && pytest tests/test_provider_profiles.py -q`. Expected: failures for the missing descriptor/policy types and fields; existing tests remain collected.
- [ ] **Step 3: Implement the immutable profile contracts.** Keep generic defaults backward-compatible, validate nonempty unique descriptor names, defensive-copy registries, and register OpenRouter semantics exactly as specified under “Provider semantics.” Do not put UTC interval compilation in the profile.
- [ ] **Step 4: Build the shared six-rule synthetic fixture.** Use the obviously fake model `synthetic/scheduled-rate-demo`. The old base vector is `0.000001122`, `0.0000000374`, and `0.000003366`; the new base/lower vector is `0.00000066`, `0.000000022`, and `0.00000198`; the new higher vector is `0.00000132`, `0.000000044`, and `0.00000396`. Define six source-ordered rules: weekend all day at the lower vector; weekdays `00:00-01:00` lower; `01:00-04:00` higher; `04:00-06:00` lower; `06:00-10:00` higher; and `10:00-24:00` lower. At least one lower rule explicitly sets only `prompt` so the other complete dimensions come from the new base. A pure pre-render test derives identical per-dimension movements and rounds them to `-41.2%` and `+17.6%`. Expected accounting is one added policy, six source rules, three dimensions, and two distinct effective bands. It must contain no copied report/account values.
- [ ] **Step 5: Run focused and complete GREEN.** Run `source .venv/bin/activate && pytest tests/test_provider_profiles.py -q`, then `source .venv/bin/activate && pytest`. Expected: both runs pass with zero skips.
- [ ] **Step 6: Commit.** Stage only the profile, profile tests, and synthetic fixture. Inspect `git diff --cached` for sensitive data, then commit with `Add conditional pricing provider semantics`.

## Task 2: Parse and canonicalize conditional policies

**Files:**

- Create: `model_sentinel/conditional_pricing.py`
- Create: `tests/test_conditional_pricing.py`

- [ ] **Step 1: Add failing event-boundary and parsing tests.** Test `None` when the parent is absent; added/removed/changed transitions; malformed/multiple parents with every parent retained; JSON integer-but-not-bool enforcement; strict threshold evaluation at `N-1`, `N`, and `N+1`; absent/all-day weekdays; empty/duplicate/unknown weekdays; empty rules; missing paired endpoints; invalid HHMM; `00:00`, `24:00`, general wrap, and equal endpoints; condition conjunction; unknown selectors; unknown non-condition keys; selector-safe fallback; stable reason codes; and the fake alternate raw-name profile compiling through semantic roles.
- [ ] **Step 2: Add failing identity tests.** Pin Monday-to-Sunday weekday canonicalization, weekday source-order noise, `(condition identity, occurrence)` matching for duplicates, preservation of source indices, and occurrence-aware parent/source provenance using canonical old/new values.
- [ ] **Step 3: Run focused RED.** Run `source .venv/bin/activate && pytest tests/test_conditional_pricing.py -q`. Expected: import or contract failures because the new interpreter does not exist.
- [ ] **Step 4: Implement event/result types and safe policy parsing.** Use frozen dataclasses and immutable tuples/mappings. Catch provider-data validation failures and return typed results; programming invariant violations may raise. Preserve every occurrence-referenced parent, source rules, and canonical values without mutating input metadata. The generic module consumes provider-neutral semantic roles and condition-set semantics; add a source guard proving it does not branch on OpenRouter raw selector names.
- [ ] **Step 5: Implement canonical condition identity, occurrence matching, and structural comparison only.** Record canonical identities and explicit assignments while keeping duplicate occurrence and source precedence auditable. Do not decide final semantic equality, `semantic_change`, weekly grouping, or directional facts until Task 3 has overlap and commutativity information.
- [ ] **Step 6: Run focused and complete GREEN.** Run `source .venv/bin/activate && pytest tests/test_conditional_pricing.py -q`, then `source .venv/bin/activate && pytest`. Expected: both pass with zero skips.
- [ ] **Step 7: Commit.** Inspect the staged public fixture and module, then commit with `Parse conditional pricing policies`.

## Task 3: Compile UTC schedules and ordered-rule fallbacks

**Files:**

- Modify: `model_sentinel/conditional_pricing.py`
- Modify: `tests/test_conditional_pricing.py`

- [ ] **Step 1: Add failing weekly-coverage tests.** Cover half-open boundaries, Friday-only wrap (`Fri 01:00`/`Fri 23:00` true; `Sat 01:00` false), Friday-plus-Saturday wrap, Sunday behavior, absent days as all seven, all-day selected days, adjacent windows, disjoint windows, valid overlap, duplicate identity, complete complement coverage, and stable grouping of equal effective vectors.
- [ ] **Step 2: Add failing state-machine tests.** Prove exactly three states: disjoint complete time policies group; overlap/threshold/understood compound policies stay ordered; understood rules with a missing event side stay ordered with `missing_event_snapshot`, no vectors, and no absorption; unknown semantics fall back raw; multiple parents fall back raw while retaining all parent evidence. Verify `fallback_reason`, `grouping_inhibition_reasons`, and `comparison_inhibition_reasons` never substitute for one another.
- [ ] **Step 3: Add failing precedence/reorder tests.** Pin later-per-key assignment, omitted-key retention, explicit-vs-effective separation, source-ordered ordered tables, disjoint reorder as evidence-only noise, commuting overlap reorder as evidence-only noise, noncommuting overlap reorder as semantic change, and no unbounded intersection expansion. Evidence-only parents remain in JSON/all detail but contribute no concise block, conditional count, or conditional bucket.
- [ ] **Step 4: Run focused RED.** Run `source .venv/bin/activate && pytest tests/test_conditional_pricing.py -q`. Expected: new compilation/state assertions fail while Task 2 tests remain green.
- [ ] **Step 5: Implement weekly segments, overlap detection, complement, vectors, and state selection.** Follow the “Weekly UTC compilation” algorithm exactly. Keep segment calculation independent of human strings so formatting cannot change semantic identity.
- [ ] **Step 6: Implement final semantic equality and conservative rule-order equivalence.** Decide `semantic_change` only after proving coverage/overlap and per-key commutativity for every possible overlap. Preserve canonical parent evidence regardless.
- [ ] **Step 7: Run focused and complete GREEN.** Run `source .venv/bin/activate && pytest tests/test_conditional_pricing.py -q`, then `source .venv/bin/activate && pytest`. Expected: both pass with zero skips.
- [ ] **Step 8: Commit.** Commit as `Compile conditional UTC pricing schedules` after staged diff inspection.

## Task 4: Add comparison, absorption, and central accounting

**Files:**

- Modify: `model_sentinel/conditional_pricing.py`
- Modify: `model_sentinel/change_render.py` (mandatory `ResolvedPriceValue` resolution/formatting contract shared by scalar and composite paths)
- Modify: `tests/test_conditional_pricing.py`
- Modify: `tests/test_change_render.py`

- [ ] **Step 1: Add failing comparison tests.** Cover grouped-vs-default, equal-partition grouped-vs-grouped, exact matched regions, partition mismatch, ordered/raw/missing-side inhibition, per-dimension higher/lower/mixed/unchanged/coverage/unknown, equal-percentage aggregation, unequal percentages, mixed units, zero basis, and dominance-gated peak labeling.
- [ ] **Step 2: Add failing absorption tests.** Cover every required gate independently, exact provider-owned base paths, nested leaf homonyms, mismatch between sibling row values and exact metadata path values, unmatched price rules, value-plus-occurrence matching, consume-once behavior, retained exact direct values/movement, unrelated `request`/`image`/`web_search` rows, unit/group mismatch, raw fallback, and `missing_event_snapshot`. Each rejected absorption must leave the sibling ordinary and counted.
- [ ] **Step 3: Add failing accounting tests.** Reconcile base fields, one policy, displayed-side source rules, union dimensions, distinct effective vectors, uncovered default coverage, repeated-base vectors, and exactly one conditional model bucket. Pin selectors at zero monetary fields and prohibit arithmetic combination of fields/policies/rules/bands.
- [ ] **Step 4: Run focused RED.** Run `source .venv/bin/activate && pytest tests/test_conditional_pricing.py tests/test_change_render.py -q`. Expected: new comparison/accounting tests fail; existing scalar tests pass.
- [ ] **Step 5: Implement the mandatory shared price-value primitives, then bounded comparison/accounting.** Refactor `_classify_price` to consume the same resolution, normalization, precision, and sentinel path. Pin scalar/composite parity for zero/`free`, tiny positive values, bound provider factors, token/request/image/search units, and equal-ratio dimensions. Do not manufacture a percentage, direction, or inherited vector from incomplete metadata.
- [ ] **Step 6: Implement safe sibling absorption.** Return occurrence references to the report planner; never mutate or delete the input `FieldChange` tuple inside the interpreter.
- [ ] **Step 7: Run focused and complete GREEN.** Run the same two-file pytest command, then `source .venv/bin/activate && pytest`. Expected: both pass with zero skips.
- [ ] **Step 8: Commit.** Commit as `Account for conditional pricing movement` after staged diff inspection.

## Task 5: Load exact stored comparison edges without changing JSON

**Files:**

- Modify: `model_sentinel/storage.py`
- Modify: `tests/test_storage.py`

- [ ] **Step 1: Add failing storage-envelope tests.** Seed a synthetic database with two comparison edges for one model on one local day, an older selected baseline edge, exact source/target snapshot metadata, duplicate field rows, a missing source model row, an initial-baseline row, and a third later snapshot with a renamed display name. Assert four-part edge identity, whole-edge row order, exact local-date filtering, consistent timestamps, exact metadata/name selection, no cross-edge merge, no adjacent-snapshot substitution, and typed missing-side data.
- [ ] **Step 2: Add failing legacy-isolation tests.** Compare existing `history_events(...)` and `recent_changes(...)` outputs before/after the new independent rich path, including exact dictionary key sets, latest-snapshot display name, row order, local-date boundaries, null handling, and exclusion of initial changes. Corrupt side `metadata_json`; legacy methods/JSON-facing objects still succeed unchanged while the rich human method raises the documented storage error. Pin `HistoryEvent` to the current five fields.
- [ ] **Step 3: Add bounded-query and decode guards.** Use SQLite trace instrumentation or a wrapped connection to assert constant-bounded statement count as rows scale from hundreds to thousands. Instrument metadata decoding and assert at most once per event side/edge even with many duplicate field rows and a large metadata payload. Preserve the existing two-second elapsed smoke budget; time alone is not the query-shape proof.
- [ ] **Step 4: Run focused RED.** Run `source .venv/bin/activate && pytest tests/test_storage.py -q`. Expected: failures for the missing comparison-event methods, records, and `StoredComparisonDataError`.
- [ ] **Step 5: Implement typed source rows and independent exact-edge queries.** Implement `history_comparison_events(...)` and `recent_comparison_events(...)`. Select candidate four-part identities and then whole rows, both scrape timestamps, exact edge-side display names, and both exact `metadata_json` values in bounded SQL. Validate one `detected_at` per edge, group in `change_id` order, and decode each side once. Malformed stored metadata is a human rich-path storage error, not provider-data fallback.
- [ ] **Step 6: Preserve existing legacy methods and failure behavior.** Do not route `Store.history_events(...)` or `Store.recent_changes(...)` through rich envelope construction. Keep their SQL/projection semantics and JSON-facing values unchanged; CLI JSON branches must not call the rich methods.
- [ ] **Step 7: Run focused and complete GREEN.** Run the storage tests, then `source .venv/bin/activate && pytest`. Expected: both pass with zero skips, bounded statement/decode counts hold, and the elapsed smoke budget remains within two seconds.
- [ ] **Step 8: Commit.** Commit as `Load exact pricing comparison edges` after staged diff and schema inspection confirm `SCHEMA` is unchanged.

## Task 6: Build the live and stored semantic presentation plans

**Files:**

- Modify: `model_sentinel/cli.py` (`run_scan`, `run_history`, `run_changes`)
- Modify: `model_sentinel/reporting.py` (semantic-core builders, artifact projections, `_FieldDisplayPlan`, `_PlannedModelChange`, `_ProviderChangePlan`, `_renders_anything`, `_prune_empty_items`, `_bulk_change_signature`, `group_planned_entries_by_bulk`, stored changes planning)
- Modify: `tests/test_cli.py`
- Modify: `tests/test_reporting.py`
- Create: `tests/test_conditional_pricing_reporting.py`

- [ ] **Step 1: Add failing live-plumbing tests.** Mock one baseline/current synthetic model pair and prove `run_scan` creates one event with exact `NormalizedModel.metadata()` objects, all same-edge field changes, baseline/attempt identity, and no metadata on `ProviderScanResult` or scan JSON. Cover compare-only and saved scans.
- [ ] **Step 2: Add failing stored-plumbing and aggregation tests.** Prove `history` and `changes` human paths use exact stored envelopes, while JSON consumes only independent legacy paths. Two same-day edges remain two model-event blocks. An older selected baseline is labeled as a selected comparison edge, never “first appeared.” A same-model schedule add/remove range produces one conditional model, two conditional events, two Change Summary identities, and two edge anchor targets.
- [ ] **Step 3: Add failing semantic-layer and accounting tests.** Assert one `ModelEventSemanticCore` per edge and one `ModelPricingAccounting` per changed model event, including nonconditional events. Interpretation/accounting occur before `ReportDetailPolicy`; default/all projections are distinct objects over the same core and share semantics/counts; squelched omits panels; absorbed siblings disappear once from ordinary rows but remain once in accounting; raw/missing-side events absorb none; displayed policy side uses new for added/changed and old for removed; ordinary price ordering still operates only on final Pricing rows.
- [ ] **Step 4: Add lifecycle, budget, and plan-reuse probes.** Pin provider-owned scan budget and local-date/provider changes budget across exact edges; keep ordinary history output characterized. Prove a parent-only/all-absorbed composite keeps its card, a composite plus list diff cannot bulk-group, and evidence-only reorder does not keep/promote a card. Spy on interpreter, semantic equality, absorption, and accounting builders—not just the interpreter—and assert `run_scan` reuses one semantic core for requested output plus concise/full companions and `run_changes` reuses one core for primary plus HTML. Renderer-local anchors are built separately per HTML artifact.
- [ ] **Step 5: Run focused RED.** Run `source .venv/bin/activate && pytest tests/test_cli.py tests/test_reporting.py tests/test_conditional_pricing_reporting.py -q`. Expected: new event/plan contracts fail.
- [ ] **Step 6: Implement live event construction outside `ProviderScanResult`.** Retain `baseline_models`/`current_map` through semantic-core construction, build occurrence-preserving events after `attempt_scrape_id` is known, and pass them through a separate map keyed by typed live identity. Do not change `_provider_result_json`.
- [ ] **Step 7: Implement the three planning layers and universal accounting.** For each edge, interpret parents before structured expansion, mark consumed occurrences, create direct ordinary price facts and `ModelPricingAccounting` for every changed model, and pass only remaining fields into per-artifact detail projection. Semantic cores carry provenance/timestamps but no anchors. A semantic composite keeps the card alive and excludes it from bulk grouping; evidence-only parents do neither.
- [ ] **Step 8: Refactor stored changes grouping and folding.** Date/provider remain outer headings and budget owners; entries use four-part edge identity; unique-model Price Movement folding follows the binding stored aggregation rules; presence records remain independent/source ordered. History uses the same conditional semantic core but preserves existing ordinary-row rendering.
- [ ] **Step 9: Run focused and complete GREEN.** Run the same three-file command, then `source .venv/bin/activate && pytest`. Expected: both pass with zero skips.
- [ ] **Step 10: Commit.** Commit as `Plan conditional pricing report events` after confirming JSON helpers contain no new IDs or metadata.

## Task 7: Render text, Markdown, history, and changes blocks

**Files:**

- Modify: `model_sentinel/reporting.py` (`render_scan_report`, `_render_scan_text`, `_render_scan_markdown`, `render_history_report`, `render_changes_report` and their shared helpers)
- Modify: `tests/test_conditional_pricing_reporting.py`
- Modify: `tests/test_render_characterization.py`
- Modify: `tests/test_render_changes_characterization.py`

- [ ] **Step 1: Add failing scan text/Markdown tests.** Pin one compact composite block, provider price-column order, UTC-only windows, advertised/default wording, safe movement facts, ordered-rule explicit/not-set cells, and self-contained raw fallback. In all detail, include source-ordered rules and canonical parent old/new values once; default grouped output remains compact.
- [ ] **Step 2: Add failing history/changes non-HTML tests.** Pin edge-relative heading text and source/target timestamps, two same-day edge blocks, one text summary entry per edge/model, no “first appeared” claim, and the same grouped/ordered/raw interpretation in history text/Markdown and changes text. Confirm history has text/Markdown/JSON only and changes has text/HTML/JSON only; defer conditional changes HTML assertions to Task 8 so this task's GREEN boundary is satisfiable.
- [ ] **Step 3: Add failing JSON identity tests.** Compare parsed scan/history/changes JSON against pre-feature fixtures with exact key sets and values. Assert no `from_scrape_id`, `to_scrape_id`, metadata, synthetic schedule rows, formatted labels, or selector exclusions enter JSON.
- [ ] **Step 4: Run focused RED.** Run `source .venv/bin/activate && pytest tests/test_conditional_pricing_reporting.py tests/test_render_characterization.py tests/test_render_changes_characterization.py -q`. Expected: new human blocks fail; existing nonconditional goldens stay green.
- [ ] **Step 5: Implement shared non-HTML composite formatting.** Keep literal stored rule JSON out of concise grouped output, but always include it for raw fallback and all detail. Use `not set by this rule`, never an unproven `inherited from base`. Schedule predicates/weekdays remain UTC, but generated/detected/source/target audit timestamps keep the existing local-time helpers and changes local-date buckets. Do not add local-time schedule previews. Every artifact using advertised/base/scheduled pricing wording includes the catalog-versus-actual-routing/billing qualification.
- [ ] **Step 6: Route history/changes through event plans.** Keep chronological event order and edge provenance. Explicit `--output` artifacts must be self-contained and must not refer to a companion file.
- [ ] **Step 7: Run focused and complete GREEN.** Run the same characterization command, then `source .venv/bin/activate && pytest`. Expected: both pass with zero skips, existing goldens remain unchanged except deliberately added synthetic conditional expectations, and JSON is identical.
- [ ] **Step 8: Commit.** Commit as `Render conditional pricing in human reports` after staged output-fixture inspection.

## Task 8: Integrate HTML cards, summaries, and the fifth model bucket

**Files:**

- Modify: `model_sentinel/reporting.py` (`_PriceMovementModel`, `_PriceMovementSummary`, `_collect_price_movement_summary`, `_price_movement_outcome`, `_render_html_price_movement_summary`, `_SummaryEntry`, `_model_price_impact`, `_split_provider_tiers`, `_build_scan_change_tiers`, `_render_html_model_changes`, edge-aware changes HTML helpers/anchors, inline CSS)
- Modify: `tests/test_conditional_pricing_reporting.py`
- Modify: `tests/test_reporting.py`

- [ ] **Step 1: Add failing grouped-card tests.** Pin one schedule block in the Pricing category, UTC badge, provider-ordered columns, per-column units for mixed groups, window grouping, exact base values/movement, neutral band names unless dominance proves peak, and ordinary nonabsorbed rows below the block.
- [ ] **Step 2: Add failing ordered/raw/full-detail tests.** Pin source order, explicit/not-set visual distinction, later-per-key note, fallback reason disclosure without exception text, canonical parent values in the same artifact, all source rules in `_full.html`, and raw values visible by default in all detail.
- [ ] **Step 3: Add failing Price Movement and Change Summary tests.** Extend the bucket table to exactly five fixed entries; prove exclusive conditional membership, conditional-only verdict, ordinary-plus-conditional suffix, unknown-not-mixed, policy/rule/dimension/band tallies, zero selector tallies, one summary row per semantic edge, and no repeated tier leaves. Cover parent-only/all-siblings-absorbed card survival, conditional-plus-list bulk exclusion, conditional tier-1 placement, evidence-only reorder staying unpromoted, and renderer-local scan anchors.
- [ ] **Step 4: Add failing changes aggregation/anchor tests.** Pin unique-model folding for repeated stored edges: schedule add/remove means one conditional model and two conditional comparison events; affected-model rendering includes two timestamp-labeled links; two edge cards and two Change Summary rows have distinct four-part identities. For nonconditional repeated edges, union directions into higher/lower/mixed/coverage as specified. No provider/model-only lookup may silently select the first edge.
- [ ] **Step 5: Add failing detail-mode, timestamp, caveat, and color tests.** Default/all semantics and counts match; squelched omits both panels; schedule windows remain UTC while event/card dates remain on existing local-time paths; catalog-versus-billing qualification appears wherever advertised/base/scheduled wording appears; higher conditional dimensions use cost-up color and lower use cost-down color only; selectors, conditions, coverage, unknowns, and rule metadata never borrow red/green cost semantics.
- [ ] **Step 6: Run focused RED.** Run `source .venv/bin/activate && pytest tests/test_conditional_pricing_reporting.py tests/test_reporting.py -q`. Expected: new HTML/bucket assertions fail.
- [ ] **Step 7: Implement composite scan and changes HTML rendering from artifact projections.** Do not classify selector leaves with `classify_change`. Reuse mandatory shared price values, sentinel, tooltip, and renderer-local anchors; keep pages JavaScript-free and self-contained.
- [ ] **Step 8: Extend lifecycle, tier, aggregation, and Price Movement consumers.** Add `conditional` to the single fixed bucket definition; make card survival, bulk eligibility, tiering, model/event counts, verdicts, summaries, and links consume semantic accounting and the binding repeated-edge fold. Do not add a renderer-specific tally path.
- [ ] **Step 9: Run focused and complete GREEN.** Run the same two-file pytest command, then `source .venv/bin/activate && pytest`. Expected: both pass with zero skips.
- [ ] **Step 10: Commit.** Commit as `Display conditional pricing schedules in HTML` after inspecting generated markup tests for sensitive data.

## Task 9: Synchronize documentation and perform complete verification

**Files:**

- Modify: `README.md`
- Modify: `docs/DESIGN.md`
- Modify: `docs/provider_schema_notes.md`
- Modify: `docs/report_readability_redesign_design.md`
- Modify: any affected tests from Tasks 1-8 only when verification exposes a real defect

- [ ] **Step 1: Update operator documentation.** Explain grouped schedules, ordered rules, raw fallback, UTC request-instant weekdays, strict threshold wording, actual-routing/billing caveat, default/all/squelched behavior, and unchanged JSON/storage. Keep the command/format table accurate: no history HTML and no changes Markdown.
- [ ] **Step 2: Update architecture/provider documentation.** Record the event-scoped interpreter, provider-owned semantics, exact stored scrape edges, no schema migration, fifth exclusive bucket, central accounting, and official OpenRouter schema link. Amend prior readability decisions rather than creating contradictory rules.
- [ ] **Step 3: Run targeted static hygiene.** Run `rg -n 'TBD|TODO|first appeared|local time|pricing\.overrides\[[0-9]+\].*(Utc|utc)|\$[0-9]+.*utc_(start|end|days)' model_sentinel tests README.md docs`. Expected: no new placeholders, false first-appearance claims, local schedule previews, or selector-as-money output; legitimate design discussion lines must be manually classified.
- [ ] **Step 4: Run the complete suite.** Run `source .venv/bin/activate && pytest`. Expected: the entire project suite passes with zero failures and zero skips. Investigate and fix every failure before proceeding.
- [ ] **Step 5: Exercise CLI help and format boundaries.** Run `source .venv/bin/activate && ./model-sentinel --help`, `./model-sentinel scan --help`, `./model-sentinel history --help`, and `./model-sentinel changes --help`. Expected: exit 0; advertised formats remain scan text/JSON/Markdown, history text/JSON/Markdown, changes text/JSON, with HTML still an internal companion.
- [ ] **Step 6: Generate synthetic human artifacts without runtime data.** Use the test fixture or a dedicated test helper inside the activated venv to write scan concise HTML, scan all-detail HTML, changes HTML, scan text/Markdown, history text/Markdown, and raw-fallback examples to a temporary directory created with `mktemp -d`. Expected: artifacts are self-contained and use only the conspicuously synthetic fixture.
- [ ] **Step 7: Visually inspect HTML.** Open the generated concise, all-detail, and changes HTML in the in-app browser at desktop and narrow widths. Verify readable tables, no horizontal clipping, visible explicit/not-set distinction, UTC labels, raw disclosure, cost-only colors, anchors, and no JavaScript/network dependency. Record any defect as a failing test before fixing it.
- [ ] **Step 8: Inspect final scope and sensitive-data hygiene.** Run `git status --short`, `git diff --stat`, and review the complete diff. Confirm there is no SQLite schema change, Browse change, provider/runtime payload, secret, personal data, generated HTML, or temporary artifact staged.
- [ ] **Step 9: Commit documentation and final corrections.** Commit as `Document conditional pricing reports`, then rerun the complete suite on the committed tree and record its actual pass count and duration in the delivery handoff.

## Acceptance checklist

- [ ] Exactly one composite conditional-pricing interpretation is produced per exact model comparison edge.
- [ ] OpenRouter's documented selectors, conjunction, strict threshold, per-key precedence, omission, base, weekday, and UTC interval semantics are provider-owned and tested.
- [ ] Selectors are never monetary rows or price-field tallies, including fallback.
- [ ] Grouped, ordered, and raw states are mutually exclusive and use separate inhibition/fallback reasons.
- [ ] Weekly wrap uses the selected request-instant UTC civil day and never infers next-day anchoring.
- [ ] Rule matching is canonical-condition-plus-occurrence; only proven commuting/disjoint reorders are suppressed.
- [ ] Missing event snapshots, overlap, partition mismatch, unknown units, and unknown semantics never manufacture inherited vectors or aggregate direction.
- [ ] Sibling absorption is exact-edge, dimension/unit/group/value/occurrence safe, consume-once, and accounting-preserving.
- [ ] Only exact provider-owned top-level base paths can absorb; nested homonyms, unmatched rules, and row/metadata mismatches remain ordinary.
- [ ] Price Movement has five fixed exclusive buckets; conditional status does not corrupt ordinary verdicts, and unknown is not mixed.
- [ ] Policy/rule/dimension/band/base-field counts reconcile from one pre-filter accounting record in every human format.
- [ ] Every changed model event, conditional or ordinary, owns one `ModelPricingAccounting`; no tally or tier scans filtered display rows to rediscover movement.
- [ ] Semantic cores, detail projections, and renderer-local anchors have separate ownership; companion artifacts reuse only the core.
- [ ] Default and all detail share semantics; squelched omits conditional and Price Movement panels; raw fallback is self-contained.
- [ ] History and changes retain separate same-day edges, selected-baseline wording, and source/target timestamps.
- [ ] Repeated changes edges fold to unique affected models and exact edge links using the binding stored aggregation rule.
- [ ] Scan/history/changes JSON schemas, values, row order, canonical parent values, SQLite schema, and stored field paths are unchanged.
- [ ] Legacy JSON paths never decode rich snapshot metadata and retain current latest-display-name and failure behavior.
- [ ] No history HTML, changes Markdown, local-time schedule preview, Browse feature, database migration, or provider-specific model ID exception is introduced.
- [ ] Existing nonconditional characterization reports remain stable.
- [ ] All HTML variants pass desktop/narrow visual inspection and preserve the cost-only red/green vocabulary.
- [ ] Schedule clocks remain UTC while audit timestamps/local-date buckets preserve existing local-time behavior.
- [ ] SQL statement count is bounded by command, metadata decoding is bounded by edge count, and the elapsed smoke budget passes without schema/index changes.
- [ ] Old positional `ProviderProfile` construction and existing renderer call forms remain source-compatible.
- [ ] The complete project suite passes with zero failures and zero skips on the committed tree.

## Adversarial review record

A full, user-submitted Oracle GPT-5.6 Sol Pro review completed on 2026-08-28 against the approved design, this plan, and the current models/profile/diff/storage/CLI/reporting/change-render source plus focused tests. The run was allowed to finish naturally; its forty-minute watcher timeout reattached to the same submitted conversation and harvested the completed 10.89k-token review. Every finding was checked against repository source and the approved design before revision.

| # | Finding | Disposition and plan resolution |
|---|---|---|
| 1 | Synthetic rates derived 40%/20%, not the required 41.2%/17.6% | Accepted. Replaced them with a proportional raw fixture and required pre-render arithmetic assertions. |
| 2 | Field descriptors lacked provider-owned cross-field roles | Accepted. Added semantic roles, condition-set semantics, alternate raw-name provider coverage, and a raw-name source guard. |
| 3 | Semantic equality was scheduled before overlap/commutativity existed | Accepted. Task 2 now stops at structural matching; Task 3 owns final `semantic_change` and evidence-only reorder behavior. |
| 4 | Rich stored data could alter legacy JSON names/failure behavior | Accepted. Legacy storage/JSON paths remain independent and never decode snapshot metadata; rich human queries carry exact edge-side names separately. |
| 5 | Semantic truth, detail projection, and HTML anchors were conflated | Accepted. Defined three ownership layers, explicit core/projection builders, and renderer-local anchors. |
| 6 | Edge refactoring could reset detail budgets or change ordinary history | Accepted. Bound current budget scopes and froze existing nonconditional history behavior, including the known `field_changed` mismatch. |
| 7 | Scalar-only pruning/bulk/tiering gates could drop or misplace composites | Accepted. Added the exact lifecycle functions and parent-only, absorbed-only, bulk-exclusion, tier, link, and evidence-noise tests. |
| 8 | Accounting existed only when a conditional parent existed | Accepted. Added planner-owned `ModelPricingAccounting` for every changed model event and prohibited filtered-row tally reconstruction. |
| 9 | Repeated `changes` edges lacked model folding and link semantics | Accepted. Bound unique-model folding, event-summed facts, edge-specific anchors, multi-link affected entries, and the add/remove two-edge fixture. |
| 10 | Leaf resolution could absorb a nested homonym | Accepted. Added provider-owned exact base paths, exact metadata-value agreement, unmatched-rule rejection, and homonym tests. |
| 11 | Missing snapshots and multiple parents were under-specified | Accepted. Missing snapshots retain ordered explicit rules with inhibition/no absorption; multiple parents retain all evidence in raw fallback. |
| 12 | Shared price formatting was optional despite private scalar helpers | Accepted. Made a narrow value-resolution/formatting contract mandatory and routed scalar/composite behavior through it. |
| 13 | UTC schedule clocks could be confused with local audit timestamps | Accepted. Kept schedule predicates UTC, preserved existing local timestamp/date paths, and required billing caveats across applicable formats. |
| 14 | Compatibility/full-suite gates came too late; Task 7 had an impossible HTML GREEN | Accepted. Added Task 0, moved changes HTML assertions to Task 8, and made the full zero-skip suite a pre-commit gate for every task. |
| 15 | Elapsed time could not prove bounded SQL/decode behavior | Accepted. Added trace-based statement counts and per-edge decode instrumentation; retained elapsed time only as a smoke budget. |
| 16 | New profile fields/render parameters could break Python callers | Accepted. Required append-only profile fields, old positional characterization, optional keyword-only semantic inputs, and existing render wrappers. |

The reviewer also investigated and retracted six suspected defects after source inspection: compare-only scans do have an attempt scrape identity; changes already groups by provider ID; same-day presence rows remain independent; human structured expansion does not rewrite storage/JSON; weekly wraps correctly use current UTC civil days; and biggest-mover selection already restricts comparison groups. None was added as corrective work.

After these revisions, every formerly blocked requirement has an owning contract, task, test, and acceptance criterion. No adversarial finding remains open, and the plan is execution-ready subject to a separate user instruction to begin implementation.

## Implementation handoff

Execute Tasks 0-9 in order. Each task has its own RED/GREEN gate, complete-suite gate, and commit so compatibility, provider contracts, pure semantics, persistence inputs, shared planning, and rendering remain independently reviewable. Do not squash away the plan's compatibility gates while implementation is in progress; final integration strategy is a separate user decision after all verification passes.
