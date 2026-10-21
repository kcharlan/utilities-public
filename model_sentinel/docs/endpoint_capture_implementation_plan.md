# Provider Endpoint Capture: Implementation Plan

## Goal and scope

Add saved OpenRouter endpoint-list history, endpoint comparisons, alias price
checks, and navigation between scan HTML companions. Deliver endpoint information
in scan output and the model dossier under the contracts below.

Historical backfill, Abacus capture, endpoint Activity facets, Catalog columns,
and endpoint price sparklines are outside this change.

## Sources and evidence

Paths below are relative to `model_sentinel/`. Use these sources directly rather
than treating this plan as another description of current behavior:

| Area | Authority |
|---|---|
| Provider transport | `model_sentinel/providers.py`: `fetch_raw_models`, `ProviderFetchError` |
| Configuration | `model_sentinel/config.py`: `Settings`, `load_settings`, `_parse_bool`, `ProviderConfig.models_url` |
| Profiles and price units | `model_sentinel/provider_profiles.py`: `ProviderProfile`, `OPENROUTER_PROFILE`, `with_pricing` |
| Price resolution and formatting | `model_sentinel/change_render.py`: `resolve_price_value`, `format_price_values`, `pricing_field_sort_key`, `classify_change` |
| Scan, baseline, artifact and notification behavior | `model_sentinel/cli.py`: `run_scan`, `_resolve_baseline`, `_determine_report_path`, `_should_notify` |
| Storage and timestamps | `model_sentinel/storage.py`: `SCHEMA`, `Store`; `model_sentinel/time_utils.py` |
| Report structure and serialization | `model_sentinel/reporting.py`: `render_scan_report`, `_provider_result_json`, `_render_scan_html`, `_render_scan_disclosure`, `_render_html_card_row` |
| Dossier identity and reads | `model_sentinel/browse/api.py`: `model`; `model_sentinel/browse/queries.py`: `model_presence`; `model_sentinel/browse/readonly.py`: `_REQUIRED_SCHEMA` |
| Browser lifecycle and appearance | `model_sentinel/browse/assets/app.js`: `useApi`, `ModelView`, `FactsList`, `ErrorBanner`; `app.css` |
| User-visible report conventions | `README.md`: Report Formatting, Color Semantics, HTML Auto-Reports, Browse History |
| Tests and installation | `README.md`: Testing, Standalone Install; `docs/LAUNCHD.md`; repository `docs/local_deployment_sync.md` |
| Repository rules | [AGENTS.md](../../AGENTS.md): Testing Scope, Release Versions |
| Upstream route and response contract | [OpenRouter endpoint reference](https://openrouter.ai/docs/api/api-reference/endpoints/list-all-endpoints-for-a-model) |
| Redirect and timeout behavior | [Python urllib.request reference](https://docs.python.org/3/library/urllib.request.html) |

Migration-fixture source revision:
`d40cf3c063a2f7e13448eae412f0753371f6a68e`.

Establish payload edge cases with the named synthetic tests below and operational
measurements through approved live acceptance. New contracts are explicit here
because existing sources do not define this feature.

## Shared contracts

### Capture eligibility and isolation

Capture is eligible only for a saved scan whose resolved profile has
`endpoint_capture=True` and whose `Settings.endpoint_capture` is enabled. Run it
after the catalog snapshot and catalog field changes have been saved.

An endpoint exception must leave the catalog result, notification decision, and
scan exit status as they would be without endpoint work. Follow Storage and
typed records for failure summaries. Catch endpoint exceptions inside the
catalog success path; do not let them enter its provider-fetch exception handler.

### Output and artifact policy

Keep automatic artifact and notification decisions governed by the CLI authority
in Sources and evidence, using catalog changes and the existing error policy.
Endpoint changes and alias events do not contribute to `change_count` or become
new notification triggers. They do not enter catalog model counts or Price
Movement accounting.

Add endpoint and alias sections to the requested scan output independently of
whether automatic artifacts are created. Thus stdout and explicit `--output`
can contain endpoint-only changes. An automatically created HTML artifact
contains this run's endpoint information when available. Persisted endpoint
history remains available through the dossier even when no artifact was created.

### Mapping and fetch outcomes

Build mappings from the accepted `current_map` of `NormalizedModel` objects,
using each object's `metadata()`. This binds capture identity to the saved
catalog and avoids a separate interpretation of duplicate raw model IDs.

For each catalog model, record one mapping outcome:

| Outcome | Required data and meaning |
|---|---|
| `listed` | Validated `list_path` from `links.details` |
| `alias` | Nonempty `alias_target.slug` as `alias_target_model_id` |
| `no_link` | No usable link supplied |
| `invalid_link` | Supplied link or alias metadata has an invalid shape |

Resolve aliases by exact catalog model ID within the same capture. Follow alias
chains with a visited-ID set; missing targets and cycles are unresolved mappings.
Do not infer targets from names, prefixes, or version-like text. Fetch only the
distinct paths reached by `listed` mappings. Multiple catalog models can share a
path; alias mappings add no request of their own.

Each path has outcome `ok` for a valid nonempty endpoint array, `empty` for a valid
empty array, or `error`. Preserve a bounded, sanitized per-path error code and
message. Invalid envelopes or non-object endpoint entries fail that path. A
missing response `data.id` is allowed; use the path as its display fallback.

`paths_requested` means distinct validated paths planned, including paths never
attempted after the admission cutoff. `paths_attempted` counts distinct paths
actually sent, excluding retry attempts. `paths_failed` counts `error` paths.
`mapping_failures` counts `no_link`, `invalid_link`, and unresolved alias models.
Apply this status table, including when no path can be planned:

| Condition | Capture status |
|---|---|
| No path or mapping failure | `complete`, including an empty catalog |
| At least one successful path and a path or mapping failure | `partial` |
| A failure and no successful path, or a capture-level exception | `error` |

A successful `empty` path is evidence of no endpoints. Missing capture data,
unresolved mappings, and failed paths are not evidence of an empty list.

### Transport and admission deadline

Use anonymous endpoint requests as a deliberate local policy, without claiming
upstream guarantees anonymous access. Consult the upstream reference in Sources
and evidence; authentication failures remain visible path errors and must not
cause a credentialed retry. Live acceptance must establish whether this policy
works before enabling production capture.

Validate the configured origin as HTTPS with a hostname, an optional port, and
no user information, query, or fragment. Validate each payload link as an
absolute path beneath the configured base path's `/models/` prefix, with a
nonempty slug and `/endpoints` suffix. Reject schemes, authorities, backslashes,
control characters, dot segments, queries, fragments, repeated separators, and
percent escapes that decode to those forbidden path constructs. Normalize the
configured base path's trailing slash before checking the prefix boundary.

Construct the URL from that origin and the validated path. Disable redirects
for endpoint requests: every redirect response is a path error, including
same-origin redirects. This policy is endpoint-specific; preserve catalog
transport behavior. Send `Accept` and a `User-Agent` derived from
`model_sentinel/__init__.py::__version__`, use a default TLS context, and send no
authorization or cookie headers.

Keep at most `ENDPOINT_FETCH_WORKERS` requests in flight, with no pre-submission
of the remaining path queue. Before each initial attempt or retry, check a
monotonic admission deadline. Permit one retry for HTTP 429 or 5xx after
`ENDPOINT_RETRY_DELAY_SECONDS`, only if the delay and the next attempt can start
before that deadline. Never retry other failures. Record unsent paths as errors
with code `budget_exceeded`.

The deadline bounds request admission, not total capture duration. Each admitted
attempt uses the smaller of the remaining admission time and
`ENDPOINT_FETCH_TIMEOUT_SECONDS` for blocking operations. Drain started workers
before returning. A response delivered through repeated successful reads may
outlast these limits; do not describe this as a hard wall-clock bound. A hard
completion deadline would require a separately designed cancellable transport.

### Endpoint state and comparison identity

The profile owns `endpoint_telemetry_fields` and `endpoint_status_field`.
`endpoint_state` removes those top-level fields; status is stored separately.
Hash stable state with SHA-256 of `models.canonical_json`. Retain endpoint
response order for identity and audit evidence.

`endpoint_key(endpoint, occurrence)` uses a nonempty string `tag`, falling back
to `name`, then `provider_name`, then a reserved unnamed base. Append the
zero-based occurrence among entries with that base. Reordering entries sharing
a base can produce apparent changes; document this limitation rather than
claim stable physical endpoint identity.

`diff_endpoint_lists(old, new)` accepts maps from endpoint key to stable state
and status. Emit `endpoint_added`, `endpoint_removed`, `field_changed`, and
`status_changed`. Reuse the recursive dictionary diff from `diffing.py` after
exporting it as `diff_values`. Keep `pricing.overrides` as a parent-level change,
including when its parent object is added or removed; do not emit descendant
selector or rate changes for it.

Use the selected catalog baseline's capture, without substituting a last-good
capture. For shared paths, compare only `ok` or `empty` observations on each
side; suppress diffs involving an error and record the comparison gap.

For moved paths, form candidate edges from common catalog model IDs with
changed `listed` mappings. Compare an old path to a new path only when the old
path disappears, the new path is newly present, and the edge is unique in each
direction. Require successful observations on each side. Deduplicate common
model mappings to that edge before diffing. Store resulting changes under the
new path with `from_list_path` preserving the old identity. Shared-list splits,
merges, and partially moved lists start a new baseline for their unmatched
paths; record `ambiguous_mapping` instead of inventing a pairing. Same-path
comparison takes precedence. Newly appearing or disappearing paths otherwise
produce no endpoint presence diff. Record their coverage disposition.

`first_capture` means no earlier persisted capture exists for this provider,
independently of the selected baseline. `baseline_capture_id` and
`comparison_state` separately describe the selected edge: `available`,
`no_selected_baseline`, `missing_baseline_capture`, or `unusable_baseline`.
Keep per-list `comparison_gaps` for failed observations, unpaired paths, and
ambiguous mappings. A current complete fetch can still have comparison gaps.

### Price presentation

Add `endpoints.resolved_price_leaves(metadata, profile)` as the common scalar
price collector. Its namespace is direct scalar children of `pricing`;
exclude object/array subtrees, including `pricing.overrides`, before resolution.
Resolve eligible leaves through the strict `resolve_price_value` contract in
Sources and evidence. Endpoint tables, alias comparisons, endpoint matching,
and ladders use this collector rather than recursive price-leaf discovery.
Conditional policies remain governed by the dedicated parent-row contract below.
Compare `normalized_exact_value`, with matching unit and comparison-group
identities. Format normalized values through
`format_price_values`; choose precision using the values displayed together.
Leave unresolved fields out of price arithmetic and ladders; endpoint matching
follows Alias comparison contract.

Add a keyword `allow_unmatched_prices=True` to `change_render.classify_change`,
preserving existing callers. Endpoint classification passes `False`; unresolved
monetary-looking leaves then take the shared neutral scalar presentation rather
than permissive scalar price fallback. Extend the existing implementation rather
than copying its formatting logic. Conditional pricing changes use a dedicated
neutral parent row labelled `Conditional pricing changed`; full detail exposes
raw parent JSON, without schedule interpretation.

Use README Color Semantics as the authority and behave as its field-change
renderers do. Use a separate field-card table with `_render_html_card_row`'s
column structure for metadata changes; thread strict endpoint classification
through its input. Do not insert field-card rows into the endpoint-price table.

For concise ordering, assign each changed list to the comparison group of its
first changed resolved price leaf in `pricing_field_sort_key` order. Order groups
by that leaf's profile presentation order, then group identity. Rank lists
within a group by the largest absolute movement in that group, breaking ties
by path. Put lists without a comparable price movement afterward in path order.
Do not rank dollar magnitudes across groups. A list appears once in this order.

### Constants

Define these in `model_sentinel/endpoints.py`; import them where needed.

| Name | Value | Meaning |
|---|---|---|
| `ENDPOINT_FETCH_TIMEOUT_SECONDS` | 30.0 | Blocking-operation timeout ceiling |
| `ENDPOINT_FETCH_WORKERS` | 4 | In-flight request limit |
| `ENDPOINT_FETCH_BUDGET_SECONDS` | 180.0 | Request-admission interval |
| `ENDPOINT_RETRY_DELAY_SECONDS` | 1.0 | Retry delay |
| `CONCISE_ENDPOINT_LIST_CAP` | 25 | Provisional concise display limit |
| `DOSSIER_ENDPOINT_CHANGE_LIMIT` | 200 | Dossier change-row limit |

### Compatibility verification

Preserve existing characterization fixtures when optional endpoint/alias data
and companion links are absent. Apply this requirement through the maintained
`tests/test_render_*characterization.py` suites.

## Deliverable: HTML companion navigation

Add `companion_link: tuple[str, str] | None = None` to
`reporting.render_scan_report` and pass it through to the HTML renderer.
Other formats ignore it. When set, render an `a.companion-link` in the header
after the raw-value toggle. It carries a sibling filename and a label. Encode
the filename with `urllib.parse.quote(..., safe='')`, then HTML-escape the href
and label. Use the report navigation styling authority rather than a change
color.

In `cli.run_scan`, compute companion paths before rendering and provide
reciprocal links. Keep the existing artifact policy. Add navigation documentation
to README HTML Auto-Reports.

**Verification:** extend `tests/test_reporting.py` and
`tests/test_cli.py::test_scan_writes_full_html_companion_report` with named
companion navigation cases. They own filename, escaping, link-absence, reciprocal
target, and explicit-output expectations; use actual temporary file writes.
Apply Compatibility verification and run Implementation validation.

## Deliverable: Saved endpoint capture and comparison

### Configuration and transport changes

Add these `ProviderProfile` fields with disabled/empty defaults:
`endpoint_capture: bool`, `endpoint_telemetry_fields: frozenset[str]`, and
`endpoint_status_field: str | None`. Enable the capability on
`OPENROUTER_PROFILE`; initialize its telemetry set from the upstream reference
and synthetic telemetry fixture, and use `status` as its status field.
`with_pricing` must preserve them.

Add `Settings.endpoint_capture: bool = True`. Parse
`MODEL_SENTINEL_ENDPOINT_CAPTURE` in `config.load_settings` using `_parse_bool`
and the field default when the key is absent. Add it to `settings.env.template`
with a comment pointing to README configuration guidance. That guidance must
explain the anonymous-request policy, admission interval, and additional requests.

Extract reusable request/decoding work in `providers.py` without changing catalog
error messages or exception sanitization. Give `ProviderFetchError` an optional
HTTP status attribute. Apply Transport and admission deadline to the extracted
transport, including its version and catalog-compatibility requirements.

Add `fetch_endpoint_lists(provider, current_map) -> EndpointFetchResult` using
Mapping and fetch outcomes and Transport and admission deadline. Define its
typed mapping/path records under Storage and typed records. Keep network
operations in `providers.py` and normalization/comparison in new `endpoints.py`.

### Storage and typed records

Append each new DDL statement separately to `storage.SCHEMA`. Leave existing
schema elements unchanged. The following column inventory is normative DDL
input, not a description of existing tables:

| Table | Columns and constraints |
|---|---|
| `endpoint_captures` | `capture_id INTEGER PRIMARY KEY AUTOINCREMENT`; unique nonnull `scrape_id` referencing `scrapes`; nonnull `provider_id`, `started_at`, `completed_at`, `status`, `paths_requested`, `paths_attempted`, `paths_failed`, `mapping_failures`, `first_capture`, `comparison_state`; nullable `baseline_capture_id` referencing this table; nullable `error_summary` |
| `endpoint_lists` | Primary key `(capture_id, list_path)`; nullable `list_model_id`; nonnull `outcome`, `endpoint_count`; nullable `error_code`, `error_message` |
| `endpoint_capture_models` | Primary key `(capture_id, provider_model_id)`; nonnull `outcome`; nullable `list_path`, `alias_target_model_id`, `error_code` |
| `endpoint_states` | `state_hash TEXT PRIMARY KEY`; nonnull `state_json` |
| `endpoint_observations` | Primary key `(capture_id, list_path, endpoint_key)`; nonnull `state_hash`; nullable integer `status_code` |
| `endpoint_changes` | `endpoint_change_id INTEGER PRIMARY KEY AUTOINCREMENT`; nonnull `provider_id`, `from_capture_id`, `to_capture_id`, `from_list_path`, `list_path`, `endpoint_key`, `change_kind`, `detected_at`; nullable `field_name`, `old_value_json`, `new_value_json` |
| `endpoint_comparison_gaps` | Primary key `(capture_id, list_path, reason)`; nonnull `reason`; nullable `from_list_path` |
| `endpoint_capture_archives` | `capture_id INTEGER PRIMARY KEY`; nonnull `body_gzip BLOB` |

Use INTEGER for scrape/capture IDs, counts, and booleans; TEXT for timestamps,
JSON, paths, other identifiers, outcomes, and messages. Add foreign keys from
capture-owned rows to captures, from observations to their list and state, and
from changes to each capture.
Use CHECK constraints for the outcome/status enums and nonnegative counts.
Index changes on `(provider_id, list_path, to_capture_id)`.
On capture-write connections, enable and verify `PRAGMA foreign_keys = ON`
before starting the transaction. Validate that the referenced scrape is a saved
success for the same provider and that the baseline capture belongs to that
provider. Keep this connection policy local to capture writes rather than
changing unrelated `Store` methods.

The archive is gzip-compressed canonical JSON of successfully decoded response
bodies keyed by path. It preserves telemetry, but is not a byte-for-byte HTTP
archive. Do not retain request headers, credential values, or arbitrary HTTP
error bodies. Sanitize and bound diagnostic messages before persistence or
rendering. Keep archives and operational evidence in the runtime database,
outside the public checkout.

Define `EndpointCaptureSummary` before integrating consumers. Its fields are
the capture identity and status fields from `endpoint_captures`, plus
`persistence_error`, `changes`, `comparison_gaps`, and `lists`.
`capture_id` may be absent for an in-memory persistence failure. Each list
record carries its mapping IDs, path, response ID, outcome/error evidence,
stable observations, and status. Change records carry the comparison identity,
display ID, mapped catalog IDs, and decoded old/new values. Keep capture and
alias record types in `models.py` to avoid feature-module import cycles.

Add `Store.get_endpoint_capture_for_scrape`,
`Store.get_latest_endpoint_capture(provider_id)`, and
`Store.load_endpoint_lists(capture_id)`. Build normalized state, diffs, and the
candidate summary in memory before saving. Inside `BEGIN IMMEDIATE`, assign
`first_capture` using the provider's persisted captures, then write the
capture, mappings, lists, states, observations, archive, comparison gaps, and
changes through `Store.save_endpoint_capture` with one commit. Its change-writing
helper takes that connection and does not commit independently. Return the
persisted summary only after commit succeeds. Reuse storage timestamp helpers.

On capture failure, roll back that transaction and construct the in-memory
error summary. Attempt a minimal error capture in a new transaction. If a
capture for the scrape is already present, inspect and reuse that committed
record rather than attempting a conflicting insert or replacing its evidence.
If fallback persistence fails, retain the in-memory error with
`persistence_error` and log it. Guard this fallback too. A later scan uses the
stored observations and comparison contract, not an invented successful empty
baseline. Keep endpoint tables optional in the browse schema authority.

### CLI and healthcheck integration

Add `endpoint_capture: EndpointCaptureSummary | None = None` to
`ProviderScanResult`. Integrate the capture pipeline under Capture eligibility
and isolation. Pass a summary for success, partial success, and failure.
Sanitize exception messages using `credentials.redact_credential_values` with
the selected credential snapshot, without including raw exception tracebacks.

Log capture status and the summary's request, failure, mapping, comparison-gap,
and change counts. Add a non-fatal healthcheck item per enabled capable
provider, including setting state and latest capture date/status/counts.
Use `no capture yet` when absent; report query failure as an advisory and do
not let an endpoint-only healthcheck failure change the existing status code.

### Tests and acceptance

The following named test groups are to be added to the indicated modules. Their
contracts above are the authority for expected values; fixtures must be invented
and remain independent of live responses.

| Module | New verification groups |
|---|---|
| `tests/test_provider_profiles.py` | `endpoint_capability_preserved_by_with_pricing` |
| `tests/test_config.py` | `endpoint_capture_setting_defaults_and_boolean_grammar` |
| `tests/test_providers.py` | `endpoint_mapping_outcomes`, `endpoint_path_validation`, `endpoint_redirect_rejection`, `endpoint_anonymous_headers`, `endpoint_retry_admission`, `endpoint_bounded_inflight_queue`, `endpoint_response_validation`, `catalog_transport_compatibility` |
| `tests/test_endpoints.py` | `endpoint_key_fallback_and_duplicate_reordering`, `endpoint_telemetry_and_status_identity`, `endpoint_change_kinds`, `endpoint_override_parent_changes`, `endpoint_status_aggregation`, `endpoint_price_leaf_namespace` |
| `tests/test_storage.py` | `endpoint_legacy_schema_preservation`, `endpoint_transaction_rollback_including_changes`, `endpoint_state_deduplication`, `endpoint_selected_baseline_gaps`, `endpoint_shared_path_identity`, `endpoint_moves_splits_and_merges`, `endpoint_first_capture_independent_of_baseline`, `endpoint_sanitized_error_roundtrip`, `endpoint_foreign_key_enforcement_and_saved_scrape_identity` |
| `tests/test_cli.py` | `endpoint_capture_eligibility`, `endpoint_failure_isolation`, `endpoint_fallback_persistence_failure`, `endpoint_failure_after_commit`, `endpoint_healthcheck_status_and_counts` |
| `tests/test_diffing.py` | Existing coverage after the exported helper rename |
| `tests/test_browse_readonly.py` | `endpoint_tables_optional_for_legacy_database` |

The legacy-schema test must embed the literal `SCHEMA` extracted from the
Migration-fixture source revision with `git show`, not from the implementation
under test. Seed invented historical rows and compare them after initialization.
Failure-injection tests must assert catalog persistence, status, output, and
notification behavior as well as endpoint rollback. Transport tests use fake
clocks and controlled workers; they must not wait for production timeouts.

Run Implementation validation. Add a synthetic healthcheck acceptance test
that seeds templates in its own private temporary runtime home, forces
environment credential mode with invented credentials, and checks the new
healthcheck contract under Implementation validation, without provider requests.

## Deliverable: Alias events and endpoint report presentation

Deliver alias reporting and the endpoint disclosure together.

### Alias comparison contract

Add `alias_check.py`. Resolve aliases with Mapping and fetch outcomes against
each catalog snapshot independently. Use Price presentation's collector to form
a fixed comparison set from the intersection of compatible alias and target
leaves. Retain missing/unresolved catalog leaves as unavailable evidence.

For endpoint matching, evaluate each candidate against that fixed set; never
reduce it to the candidate's available leaves. A candidate with any proven
unequal leaf is a nonmatch. Otherwise it is a match only when every required
leaf is available, compatible, and equal; missing or unresolved required evidence
makes the candidate unknown. An empty comparison set makes matching unavailable
with reason `no_comparable_leaves`. Missing/failed lists make matching unavailable; a successful empty
list has no candidates.

`evaluate_aliases(models, profile, lists=None)` returns typed evaluations with
alias/target identity, unavailable catalog leaves, an optional divergence, and
endpoint-match evidence. That evidence contains `compared_leaves`, `matching_keys`,
`differing_keys`, `unknown_keys`, and an unavailability reason. Render matches as
claims about the named comparison leaves. Do not claim that no endpoint matches
when candidates remain unknown. An evaluation can retain unavailable evidence
without a divergence, for dossier use.

Define the semantic signature as target ID plus sorted leaf paths and exact
normalized alias/target values with their unit/group identities. Raw numeric
spelling and endpoint-match evidence do not participate in that signature.

`divergence_events(baseline_models, current_models, profile, lists=None)` compares
those signatures. A current-only divergence is `new`; a changed signature is
`changed`; an equal signature is `persisting`. A prior divergence is `resolved`
only when the alias and target are currently present and the previously
divergent leaves are comparable and equal. Missing aliases, targets, or comparable
leaves produce `unavailable` evidence, never a claim that prices match again.
Changed targets belong to the changed signature.

Add `alias_events: tuple[AliasEvent, ...] = ()` to `ProviderScanResult`. Run this
check on capable-profile catalog success paths for saved and compare-only scans,
after optional capture. Keep alias enrichment inside its own guarded block so
malformed alias metadata cannot turn catalog success into an error. Use the
catalog snapshots selected under Endpoint state and comparison identity; no
historical endpoint lookup is needed to classify an event.

For every differing leaf, render a labelled alias-versus-target sentence with
that leaf's actual values and unit. Do not substitute output prices for another
leaf's divergence. Place `new`, `changed`, and `resolved` events after the Price
Movement card. Follow Endpoint disclosure contract for persisting events. Present
`unavailable` as neutral evidence in full detail. Text and Markdown append an
Alias check section before the endpoint section, following the same event policy.
Use README Report Formatting as the formatting authority.

### Ladder contract

`price_ladder(endpoints, *, leaf, marks, profile) -> Ladder | None` is the shared
Python projection for report and API consumers. Accept only values compatible
with the selected leaf's resolved unit/group. Its domain includes strictly
positive endpoint values and reference marks; marks outside endpoint prices
expand the domain. Place values linearly in log10 space. A domain with one
distinct positive value has position `0.5`. Preserve exact-value equality for
grouping, and avoid overflow when computing the log span. Return zero,
negative, missing, invalid, and incompatible values separately with reasons.
Return `None` when no positive compatible value can be placed.

Preserve every endpoint key and mark label at coincident positions. Return the
domain, leaf, unit, positions, and unplaced evidence. JavaScript renders those
positions without recomputing the scale. Render a ladder for each displayed
divergent leaf when endpoint evidence is available.

Report SVG uses neutral endpoint dots and distinguishable labelled target/alias
marks with accessible titles and an equivalent text description. Size the SVG
for its labels, allow collision rows, and verify narrow viewports. Follow README
HTML Auto-Reports for report interactivity. Browser rendering follows the same
projection and its own CSS token authority.

### Endpoint disclosure contract

Add a closed `Provider endpoints` disclosure after the existing scan disclosure
when a capture summary or persisting alias event is present. Omit endpoint and
alias additions in `squelched` detail mode. Build summary clauses from uncapped
data for price-changed lists, endpoint additions/removals, conditional changes,
status changes, persisting divergences, capture failures, and comparison gaps;
drop zero-count clauses. Show the genuine first-capture message separately from
missing/unusable selected-baseline evidence. State no changes only for compared
lists, without implying that failed or unpaired lists were checked.

Show persisting aliases first. Then show changed lists in Price presentation
order. The endpoint-price table has provider tag, resolved price-leaf columns
in profile order, and change. Label units in headers; retain per-cell raw
evidence. Metadata rows use the separate table specified by Price presentation.
List headings show the response ID or path and mapped catalog IDs.

Default detail includes price, endpoint presence, and conditional changes, capped
by `CONCISE_ENDPOINT_LIST_CAP`. When truncated, show the omitted-list count and
use the companion navigation contract when a full companion exists. Full detail
includes metadata/status/unavailable evidence, remains inside the closed
disclosure, and has no display cap. Text/Markdown use the summary clauses and
include uncapped raw-first rows in full detail.

Add optional top-level JSON maps `alias_checks` and `endpoint_captures`, keyed by
provider ID, only when corresponding result data exists. Explicit serializers
must preserve `_provider_result_json` behavior. Endpoint serialization includes
the summary fields except `lists`, with uncapped changes/gaps. Serialize price
evidence using JSON-safe raw values and normalized display/unit metadata; do not
serialize Fraction objects or feed these extensions through catalog semantic
planning.

### Tests and acceptance

Add `tests/test_alias_check.py` groups `alias_leaf_comparison_and_matching`,
`alias_semantic_event_transitions`, `alias_missing_evidence`, and
`ladder_domain_and_unplaced_values`. They own concrete price inputs and
positions. Exercise Alias comparison contract, including its semantic signatures,
and differing-leaf presentation. Keep conditional-subtree, empty-comparison-set,
and incomplete-candidate cases in `alias_leaf_comparison_and_matching`.

Extend `tests/test_reporting.py` with `alias_leaf_presentation`,
`endpoint_disclosure_summary_and_detail`, `endpoint_comparison_gap_wording`,
`endpoint_strict_price_and_metadata_tables`, `endpoint_unit_group_ordering`,
`endpoint_companion_cap_navigation`, and `endpoint_json_extensions`.
Add CLI groups for compare-only aliases and Output and artifact policy.
Apply Compatibility verification.

Add temporary HTML artifact cases with browser assertions for semantic table
column alignment, accessible ladders, collision/narrow layouts, raw evidence,
disclosure default state, and reciprocal cap navigation. Inspect their synthetic
output visually. Update README Report Formatting and HTML Auto-Reports to
reference the implemented feature behavior. Run Implementation validation.

## Deliverable: Serving endpoints in the dossier

### Query and API contract

Add `endpoints` to `browse/server._API_ROUTES`. Extract/reuse model identity
validation from `browse/api.model`, and behave as `queries.model_presence` does
when selecting the dossier observation. Accept optional `scrape_id`, constrained
to a saved observation of that provider/model, so the UI can bind endpoint data
to the exact `latest_scrape.scrape_id` already displayed in its dossier. Without
it, use the same model-presence selection. Do not substitute the provider's
newest scrape or a capture from another observation.

Add read-only query helpers for optional-table detection, exact scrape capture,
model-to-list resolution, list changes, and first usable capture date. Behave
as `queries._translate_busy` does on SQLite lock errors. Query first usable date
per provider from persisted successful list observations; do not infer it from
the selected baseline or from an error-only capture.

Define `browse.api.endpoints(ctx, params)` with this response shape:

```text
{
  provider_id, model_id, scrape_id,
  captured: bool,
  reason: null | no_tables | not_captured | alias_target_missing |
          alias_cycle | no_link | invalid_link | fetch_error | capture_error,
  capture, first_capture_date,
  list_path, list_model_id, shared_with, alias,
  list_outcome, list_error,
  endpoints, ladders, changes, limit, truncated
}
```

`captured` is true only for a resolved `ok` or `empty` list at that observation.
A failed path returns `fetch_error` and its `list_error`; unresolved mappings
retain their reason. A persisted capture-wide error without mappings or lists,
including Storage and typed records' minimal fallback, returns `capture_error`
with its error evidence in `capture.error_summary`. An unexpected missing mapping
in a non-error capture is a data-integrity error, not `not_captured`.

Unavailable-list responses return empty endpoint, ladder, shared-model, and
change collections, with `truncated=false`. Unresolved list identity/outcome is
null. Preserve a capture summary whenever it exists; use nullable evidence for
absent tables/captures. Reads never open a writable connection. Build `alias`
from `evaluate_aliases` on the exact catalog snapshot independently of capture
availability. Price and ladder projections use the shared contracts.

`changes` queries use provider and resolved list path. Bound and order target
catalog observations using the ordering authority in `queries.model_presence`,
with descending change ID as the final tie-breaker. Capture completion order
must not admit a later catalog observation into an older dossier. Return
`DOSSIER_ENDPOINT_CHANGE_LIMIT` as `limit`;
fetch `limit + 1` rows to derive `truncated`, then remove the extra row. Preserve
each selected comparison's source/target capture and path identity in output.

### UI contract

Add `EndpointsSection` between `FactsList` and Changelog in `ModelView`, using
the existing section-heading pattern with title `Serving endpoints` and a
`serving providers` label. Adjust the neighboring label sequence in the same
change. Request endpoints only after the dossier response is fresh, including
its exact scrape ID. Use `useApi` and honor its request-key/freshness contract;
same-resource retries may retain data, but switching model/provider/scrape must
not display another resource's endpoints. Use `ErrorBanner` and the maintained
loading pattern.

Show the endpoint-price table and ladders under the shared presentation
contracts. An alias uses its actual differing-leaf evidence. A shared-list note
identifies the list and warns that the catalog row's price can differ; derive
sharing from mappings rather than a model-ID suffix. Changes use API order and
the API-supplied truncation fields.

Render Query and API contract's reason states distinctly. For absent capture
show `Provider endpoints weren't
captured for this snapshot.` Include the API's first usable capture date when
available; otherwise refer to the capture setting's README guidance. Failed
captures must show failure evidence and a recoverable API retry, without
suggesting the retry contacts the upstream provider.

Use the browse CSS authority for neutral endpoints/marks and field-change
semantics. Do not copy report token names into browse CSS. Keep provider-origin
requests in the CLI; browser requests go only to this local browse server.

### Tests and acceptance

Extend `tests/browse_fixtures.py::build_fixture_db` with
`with_endpoints: bool = False`. Endpoint-specific callers pass `True`; preserve
existing callers. Put fixture identities and expected capture evidence in its
returned facts, not in this document.

Add API/query test groups `endpoint_reason_states`, `endpoint_exact_observation`,
`endpoint_alias_and_shared_mapping`, `endpoint_change_truncation`,
`endpoint_no_future_changes`, `endpoint_minimal_error_capture_roundtrip`, and
`endpoint_busy_reads`. Exercise legacy schema,
failed captures, valid emptiness, and selected-baseline gaps through the shared
contracts rather than mocking every storage read.

Add a dedicated endpoint-enabled server fixture in
`tests/test_browse_smoke.py`; have it explicitly request endpoint fixture data.
Use the maintained page/console-error guards and add a runtime request guard
that fails any request outside the fixture server origin. Cover capture states,
alias leaf text, shared-list notes, light/dark appearance, label order,
truncation, and API retry. Hold requests to prove model/scrape switches suppress
stale endpoint data. Keep `tests/test_browse_offline.py` as an additional source
guard, not a replacement for runtime request observation.
Exercise `endpoint_minimal_error_capture_roundtrip` from the actual fallback
storage write through the API and browser. Put reversed capture-completion
ordering in the `endpoint_no_future_changes` fixture.

Add a named synthetic dossier acceptance test using the real browse server on
an ephemeral loopback port and fixture-defined dossiers. Inspect the synthetic
page in maintained themes. Update README Browse History and run Implementation
validation.

## Implementation validation

For each implemented deliverable, run the complete suite defined in README
Testing, including browser tests. From `model_sentinel/` with its prepared venv:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m model_sentinel --help
.venv/bin/python -m model_sentinel scan --help
```

Acceptance requires a passing full suite without skips and successful help
commands. Apply the Repository rules authority in Sources and evidence. Synthetic
runtime homes, artifacts, browser evidence, and payload fixtures must obey the
repository's public-data and Python-environment rules. Do not source real user
configuration in synthetic checks. Each acceptance test owns and cleans up its
fresh private directory and server lifecycle.

## Rollout and live acceptance

Deploy Saved endpoint capture and comparison first; companion navigation may
ship with it. Accumulate a two-week shadow period before releasing Alias events
and endpoint report presentation. Inspect private capture telemetry to adjust
the provisional display cap and profile telemetry fields before that release.
Serving endpoints in the dossier follows afterward. During shadow operation,
use the capture log and healthcheck contracts for visibility. Apply Transport
and admission deadline's production-enablement gate.

Follow the Repository rules and installation authorities in Sources and
evidence for release work. When an agent is authorized to install or check the
zipapp, prefix the installer command's PATH with the absolute project venv `bin`, and
run installed CLI checks through that venv's interpreter. Check installer
freshness before reporting a release.

Live acceptance requires separate approval for credentials, provider requests,
and real database writes. Keep its evidence private. On the exact approved
saved scrape, compare the persisted mapping/path records with Mapping and fetch
outcomes; inspect planned/attempted/failed counts and capture status under that
contract and the transport contract. Do not use a distinct-link SQL count or
alias-prefix subtraction as the acceptance
oracle. Verify saved capture and exact-edge changes through the API/report
contracts, and report unmet live gates rather than inferring success from unit
tests or a historical measurement.
