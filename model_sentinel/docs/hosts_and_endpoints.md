# Hosts and endpoint capture: developer reference

This reference records the identity and evidence boundaries behind the user-facing
[Endpoint capture](../README.md#endpoint-capture), [Browse History](../README.md#browse-history), and
[Alias Check and Provider Endpoints](../README.md#alias-check-and-provider-endpoints) descriptions.
The implementation and tests remain authoritative for the full schema and presentation.

## Capture and comparison

`providers.fetch_endpoint_lists` builds mappings from the accepted normalized catalog:
`listed` supplies a validated path, `alias` names an exact catalog target, and
`no_link` or `invalid_link` records unusable metadata. Alias chains resolve within
the same capture; missing targets and cycles remain unresolved. Distinct listed paths
are fetched once, even when models share them. A valid endpoint array is `ok` or
`empty`; an invalid envelope, invalid entry or transport failure is `error`. A
successful empty response is evidence; a failed or missing response is not.
`paths_requested` counts planned distinct paths, `paths_attempted` counts paths
actually sent (not retries), `paths_failed` counts errors, and `mapping_failures`
counts unusable or unresolved model mappings. No failure yields `complete`; a
failure alongside a successful path yields `partial`; failure without a successful
path yields `error`.

Endpoint URLs require an HTTPS origin and a validated absolute path beneath its
`/models/` prefix ending in `/endpoints`. Reject authorities, queries, fragments,
backslashes, controls, dot segments, repeated separators and escaped equivalents.
Requests are anonymous and redirects are rejected. At most four workers admit
requests for 180 seconds; one retry is allowed for 429 or 5xx after one second
if it can start within the budget. Each attempt uses at most 30 seconds or the
remaining admission time. Started workers drain: this is not a hard completion
deadline. Unsent paths are `budget_exceeded`. Catalog transport remains separate.
See [OpenRouter's endpoint reference](https://openrouter.ai/docs/api/api-reference/endpoints/list-all-endpoints-for-a-model).

`endpoints.endpoint_state` excludes profile-defined top-level telemetry and status;
status is stored separately. `endpoint_state_hash` hashes canonical JSON with
SHA-256. Keys use the first nonempty string of `tag`, `name`, `provider_name`, or
a reserved unnamed base, followed by `#` and the zero-based occurrence in response
order. Reordering duplicate bases can look like a change: the key is not a physical
endpoint identity. Diffs record additions, removals, field and status changes;
`pricing.overrides` remains one parent change.

Comparison uses the selected catalog baseline's capture, not a later or last-good
capture. Same-path successful observations take precedence. A moved path is paired
only when the old path disappears, the new path is new, and shared model mappings
produce a unique edge in both directions. Splits, merges and partial moves produce
`ambiguous_mapping`; failed observations and unpaired paths also produce gaps. A
complete current capture can therefore still have gaps. `first_capture` describes
provider history independently of `comparison_state`, which is `available`,
`no_selected_baseline`, `missing_baseline_capture`, or `unusable_baseline`.

## Storage and telemetry

`storage.SCHEMA` is the exact DDL authority. Its endpoint tables and keys are:

| Table | Identity and evidence |
| --- | --- |
| `endpoint_captures` | `capture_id`; unique `scrape_id`; provider, timestamps, status, counts, first-capture and selected-baseline state/reference, error summary |
| `endpoint_lists` | `(capture_id, list_path)`; response model ID, `ok`/`empty`/`error`, count and error evidence |
| `endpoint_capture_models` | `(capture_id, provider_model_id)`; mapping outcome, path, alias target and error code |
| `endpoint_states` | SHA-256 `state_hash` and canonical `state_json` |
| `endpoint_observations` | `(capture_id, list_path, endpoint_key)`; state hash and nullable status |
| `endpoint_changes` | `endpoint_change_id`; provider, both capture IDs and list paths, endpoint key, kind, field, old/new JSON and detection time |
| `endpoint_comparison_gaps` | `(capture_id, list_path, reason)`; optional `from_list_path` |
| `endpoint_capture_archives` | `capture_id`; gzip JSON of decoded successful bodies keyed by path |
| `endpoint_telemetry_captures` | `capture_id`; `scan`/`archive` source, recorded time, inserted and unmatched counts |
| `endpoint_telemetry` | `(capture_id, list_path, endpoint_key)`; nullable `uptime_5m`, `uptime_30m`, `uptime_1d`, canonical raw `telemetry_json` |

The schema enforces foreign keys and outcome/count constraints; capture writes enable
foreign keys and commit capture, mappings, lists, observations, archive, gaps and
changes together. A failed transaction attempts a minimal error capture separately;
if a capture already committed for the scrape, it is reused. Failure of that fallback
remains an in-memory persistence error. Archives are decoded JSON evidence, not
byte-for-byte HTTP recordings; headers, credentials and arbitrary error bodies are
not archived. Diagnostics are bounded and sanitized.

Telemetry markers distinguish processed empty captures from unprocessed archives.
Each archive backfill commits independently and only matches saved observation keys;
unmatched entries are counted. A failed archive remains pending. The README explains
sample validation, backfill timing and healthcheck behavior. Telemetry is excluded
from stable-state comparisons.

## Prices, aliases and reports

`resolved_price_leaves` collects direct scalar children of `pricing`, excluding
object/array subtrees. Arithmetic requires exact normalized values and compatible
unit and comparison-group identities. Unknown endpoint price rules render neutrally.
Alias comparisons use the fixed intersection of comparable alias and target leaves.
A candidate with a proven unequal leaf differs; it matches only if every required
leaf is available and equal; incomplete evidence is unknown. An empty intersection
or unavailable list cannot establish a match. Alias event identity comprises target,
sorted leaf paths, exact values and unit/group, not raw numeric spelling or endpoint
matching evidence. A divergence resolves only with present, comparable equal evidence.

`price_ladder` projects positive compatible values and reference marks onto a log10
axis, using the midpoint for a single distinct value. It retains coincident keys and
labels, and records zero, negative, missing, invalid or incompatible values as
unplaced evidence. The browser renders supplied positions rather than recalculating.
Concise report ordering ranks movements within compatible price groups, never across
units; the list cap is 25. Full detail retains raw evidence. Catalog artifact and
notification decisions do not count endpoint-only or alias changes.

Parameter-name fields use set membership only for valid string collections. Reorder
and duplicate-only changes have no primary human row, while raw source evidence and
record identities remain intact. Missing, null and malformed operands stay neutral;
known empty lists are sets. Supplied attribute objects expand to leaf transitions,
without inferring semantics from names. Capability selection is profile-owned and
its changed-list summary is computed before capping. See README Report Formatting
for user-visible detail and audit behavior.

## Read-only API identity

`GET /api/endpoints` requires provider and model identity and accepts an optional
`scrape_id` belonging to that model's saved observation. Without it, model-presence
selection applies. It returns `provider_id`, `model_id`, `scrape_id`, `captured`,
`reason`, `telemetry`, `backfill_eligible`, `capture`, `first_capture_date`,
`list_path`, `list_model_id`, `shared_with`, `alias`, `list_outcome`, `list_error`,
`endpoints` (`columns` and `rows`), `ladders`, `changes`, `limit`, and `truncated`.
Reasons are `no_tables`, `not_captured`, `alias_target_missing`, `alias_cycle`,
`no_link`, `invalid_link`, `fetch_error`, or `capture_error`; null means available.
Only resolved `ok` or `empty` lists are captured. Missing mappings in a non-error
capture are integrity errors. Alias evaluation uses the exact catalog observation
even without a capture. Changes are bounded by catalog completion order and scrape
ID, then change ID, not capture completion; 200 rows plus a probe determine truncation.
The dossier's request key includes the scrape so a resource switch cannot display
stale evidence.

`GET /api/hosts` requires `provider` and accepts a saved successful `scrape_id`;
otherwise it selects the newest usable capture by catalog order. It returns
`provider_id`, `scrape_id`, `reason`, `captures`, `capture`, `telemetry`,
`backfill_eligible`, `price_columns`, `lists`, `hosts`, `vocab`, and `endpoints`.
`reason` is null, `no_tables`, `not_captured`, or `capture_error`; a non-null
reason has empty lists, hosts and endpoints. Each price-column descriptor contains
`path`, `label`, `unit_label`, and `comparison_group`. `vocab` contains sorted
`parameters`, `native_tools`, `quantizations`, and `tiers` arrays; tiers contain
nullable strings, with null ordered first.
List records carry `path`, `display_id`, `models`, and `aliases`; host records carry
`name`, `endpoint_count`, `list_count`, and `uptime_1d_median`. Each endpoint has
`list` (index), `key`, `host`, `tag`, `status`, `quantization`, `precision_bits`,
`context_length`, `max_completion_tokens`, `max_prompt_tokens`, `service_tier`,
`parameters`, `native_tools`, `implicit_caching`, `prices`, and `uptime`. Parameter
and tool entries index their vocabulary arrays. Parameters are unique string members;
native-tool names are keys of an object, or empty if it is missing or not an object.
Missing or non-string quantization becomes `unknown`; unrecognized quantization has
null `precision_bits`. Missing or non-string service tier becomes null. Host name
falls back through `provider_name`, `name`, `tag`, then key; only literal true asserts
implicit caching. Uptime keys `1d`, `30m`, and `5m` are null unless telemetry is
available, and missing samples remain null.
Each price has `exact` (`numerator_hex`, `denominator_hex`), `display`, `display_own`,
and `raw`. Hexadecimal Fraction components avoid Python's decimal integer-string
limit while preserving precision beyond JavaScript Number. A negative numerator's
sign must be separated before constructing a hexadecimal BigInt and reapplied afterward;
`display` uses capture-wide formatting and `display_own` formats one value.
Telemetry is `available`, `pending`, or `no_tables`.

`GET /api/host_history` requires `provider` and `host`, with optional local-date
`from`/`to`; it returns `host`, `telemetry`, `series`, `changes`, `limit`, and
`truncated`. Series points contain `scrape_id`, `date`, `lists`, `endpoints`,
`uptime_1d_median`, `uptime_1d_min`, `not_normal`, and `capture`. Absence in a complete
capture yields zero counts; absence in an incomplete capture yields null counts.
Missing samples never carry forward and incomplete points break trend lines. Added
and changed endpoints are attributed to their target host; removals use the baseline
observation and path. Changes use target catalog order and the same 200-row limit.
All routes read saved state without backfill or upstream requests.

## Hosts state and interactions

The fragment keeps `hosts`, `hasof`, `rank`, `match`, `showx`, `hlist`, `hsort`,
`dsort`, and condition keys: `quant`, `quantset`, `upwin`, `upmin`, `upmiss`,
`healthy`, `ctxmin`, `outmin`, `params`, `ntools`, `caching`, `tiers`, `tierset`,
`plimit`, `xhosts`, `xmode`, and `hq`. List keys are comma-separated encoded values;
tiers encode native nullable strings as JSON so null and a string named `null` stay
distinct. Invalid capture-specific keys are canonicalized with replacement history;
deliberate selections use history entries. Switching provider clears the snapshot.

Qualification applies conditions in `HOST_CONDITIONS` order, which determines the
first failing reason. Removal counts evaluate each condition independently. Active
empty precision/tier sets match nothing. Missing uptime may be included, and its
condition pauses when telemetry is unavailable. `xmode=only` restricts hosts to
`xhosts`; an empty selection is inactive. Row admission uses qualifying endpoints
and selected-host any/all, or observed presence under Show excluded. An admitted
failing endpoint never wins a rank. Exact rational comparisons determine prices,
ties, limits and gaps; absent rank values stay unranked. Current default ranking is
output price when present, superseding the initial Hosts plan's prompt-price default.

The current toolbar, compact table and nonmodal drawer supersede the original roster,
question line and later modal drawer design. Menus own their state and cancel stale
editor drafts on unrelated navigation. The drawer respects overlay Escape priority,
URL history and focus restoration. Sort stacks cycle ascending, descending, removed;
missing values remain last, hidden valid keys survive, and active displayed keys
sort in priority order. Grouping uses adjacent comparator-equal runs of the first
visible sort key, within the current page and separately within passing/failing
drawer groups. Group headings do not count as data rows. README Browse History
contains the user-facing controls and current visual behavior.

## Validation and live evidence

The [Testing section](../README.md#testing) owns the full suite and isolated
synthetic Hosts visual procedure. Historical rollout instructions and old expected
results are not evidence that a live check passed. Live provider requests, real
saved scans and deployment require separate authorization; retain evidence privately.

The live acceptance, shadow period and telemetry review from the endpoint capture plan
were dropped on 2026-10-31. Capture runs on real scans, and problems get fixed when
they appear. The display cap stays at 25 until use shows it should change.
The legacy-schema fixture's source revision is
`d40cf3c063a2f7e13448eae412f0753371f6a68e`; `test_endpoint_legacy_schema_preservation`
protects existing data when the schema is initialized.
