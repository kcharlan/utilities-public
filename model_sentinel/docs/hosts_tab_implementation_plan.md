# Hosts Tab: Design and Implementation Plan

## Goal and scope

Add a browse view, **Hosts**, for comparing the companies serving models
through OpenRouter endpoint lists. The owner can combine conditions, compare
hosts across models, and inspect a host's saved history.

Hosts means serving companies. Preserve the existing Providers filter and its
hash key for catalog providers.

Out of scope: Activity facets for endpoint changes, Catalog host columns,
Abacus endpoint capture, interpreting latency or throughput, authenticated
endpoint fetches, and deployment. The dossier enhancement is optional.

## Sources

Paths are relative to `model_sentinel/`. Python symbols omit the
`model_sentinel` package prefix. Use these authorities directly for existing
behavior. The contracts below define new behavior because existing sources
cannot specify the new view, its state, or its telemetry storage.

| Concern | Authority |
|---|---|
| Endpoint identity and parsing | `endpoints.endpoint_key`, `key_endpoint_list`, `_endpoint_base`, `parse_endpoint_list`, `endpoint_list_records` |
| Stable state, telemetry and status | `endpoints.endpoint_state`, `endpoint_status`; `provider_profiles.ProviderProfile`, `_OPENROUTER_ENDPOINT_TELEMETRY_FIELDS` |
| Archive contents and capture persistence | `models.EndpointFetchResult`, `EndpointCaptureCandidate`; `storage._capture_archive_blob`, `Store.save_endpoint_capture`, `Store.save_endpoint_error_capture` |
| Scan isolation and healthcheck | `cli._capture_provider_endpoints` and its `run_scan` call site; `cli._endpoint_capture_check` |
| Price resolution and presentation | `endpoints.resolved_price_leaves`, `PriceLeaf`; `endpoint_report._state_leaves`, `_label`, `endpoint_label_profile`; `change_render.resolve_price_rule`, `format_price_values` |
| Capture status line | `browse.endpoints_api.endpoint_response`: the `capture["status_line"]` assignment |
| Change serialization and rendering | `browse.endpoints_api._change_json`; `browse.queries.endpoint_list_changes`; `browse/assets/app.js`: `endpointChangeCells`, `EndpointChanges` |
| Saved-scrape validation | `browse.api._scrape_for_catalog` |
| Change limit | `endpoints.DOSSIER_ENDPOINT_CHANGE_LIMIT` |
| Legacy and read-only database behavior | `browse/readonly.py`: `_REQUIRED_SCHEMA` and its preceding comment; `browse.queries`: `_ENDPOINT_TABLES`, `endpoint_tables_present`, `_translate_busy`, `first_usable_endpoint_capture_date`, `list_scrapes` |
| API errors and common parameters | `browse.api.BadRequest`, `NotFound`, `parse_common`; `browse.server._serve_api` |
| Routing and CLI | `browse.server._API_ROUTES`, `run_browse`; `cli.build_parser`: browse `--view` argument |
| Front end | `browse/assets/app.js`: `VIEWS`, `HASH_KEYS`, `LIST_KEYS`, `hashState`, `useHashState`, `useApi`, `resolveState`, `defaults`, `FilterBar`, `Catalog`, `SnapshotPicker`, `scrapeLabel`, `EndpointTable`, `Portal`, `typeaheadPlacement`, `useFocusTrap`, `App` |
| Visual conventions | `browse/assets/app.css`; `README.md`, Color Semantics |
| Browser fixtures and guards | `tests/browse_fixtures.py`; `tests/test_browse_smoke.py`: `_serve`, `endpoint_server`, `_guarded_page` |
| Synthetic runtime isolation | `tests/model_view_validation_fixture.py`: `_prepare_empty_runtime_home`, `_is_within_repository`; `tests/test_model_view_validation_fixture.py` |
| Recorded lessons | PKM project `utilities-public`, knowledge entries 158, 159, 164 |
| Release precedent | commit `7e38ae6`, `model_sentinel/__init__.py` |
| Repository requirements | `../AGENTS.md`: public data, testing, versions and Git rules |

No real archive extraction or operational frequency claim is needed for this
plan. Use the synthetic scenarios under Fixture cases as input evidence.

## View contracts

### Presentation

Use the browse app's body and monospace stacks. The primary control is a
sentence-shaped question line whose phrases open condition editors. It is
larger than surrounding controls; the remaining UI follows the app's scale.
Reuse the Sources visual conventions without introducing color tokens.

| New role | Existing token or treatment |
|---|---|
| Question phrases and selected hosts | `--accent`, `--focus-ring` |
| Capacity values | `--capacity` |
| Capability chips | `--capability` |
| Excluded values | `--dim` |
| Host history series | `--series-1` |
| Best rankable value | bold, solid left notch, accessible label "best in row"; ties share this treatment |

The best marker must not use `--cost-down`: ranking does not report a price
movement. Condition editors state the count of endpoints with missing values.

### Layout

Keep the roster, question line and snapshot picker visible in each mode.
Show the selected capture's shared `status_line` beside the picker; label
counts as observed coverage of that capture.

| Selected hosts | Main area |
|---|---|
| none | Matrix containing the best-across-hosts column |
| one | Host profile |
| more than one | Matrix with selected-host columns and the best-across-hosts column; selection bound is defined in Hash state |

The roster contains hosts from the selected capture. Show qualifying-list and
served-list counts, a host-name search, and sorting by name, lists served or
median 1-day uptime.

A matrix row represents an endpoint list and uses
`models.EndpointListRecord.display_id`. Show its mapped catalog models and
aliases below the title; shared lists do not create duplicate rows. A host
cell shows the endpoint chosen by Ranking, its precision, and a count of
additional qualifying endpoints. Expanding the cell lists those endpoints.
The best-across-hosts column considers hosts independently of roster selection
and shows the count of hosts with a qualifying endpoint. The model title
opens a dossier for a mapped model; when several models map to the list, each
mapped model has its own dossier link. A list with no mapped model has a plain
title.

The profile shows served-list, endpoint and tag counts, median 1-day uptime,
the count of status values outside the Status condition, a precision
distribution, and endpoint details grouped by model list. Show each host's
rank, difference from the winning host, and endpoint facts from Hosts response.
Host history uses Host history response.

On narrow viewports, collapse the roster into a disclosure above the main
area. Keep matrix horizontal scrolling inside a container with a sticky model
column. The document itself must not overflow horizontally.

### Ranking

| Dimension | Direction |
|---|---|
| A column from `price_columns` | lowest |
| Uptime window | highest |
| Context length or max output | highest |

Default to `pricing.prompt` when present, otherwise the first price column,
otherwise context length. A requested dimension absent from a new snapshot
normalizes to this default through `replaceState`. Disable uptime ranking
when telemetry is unavailable or the chosen window has no numeric samples.

Passing conditions and having a ranking value are separate properties.
Missing or nonfinite ranking values are unranked; retain qualifying endpoints
in counts and expanded details, display a dash for an unrankable cell, and
award it no best marker. With no rankable values, keep admitted rows and show
"No values for this ranking" instead of choosing a winner.

For each list, reduce each host to its best rankable qualifying endpoint,
then rank those host values. Ties share a competition rank, and the
denominator counts hosts with a rankable value. Extra tags cannot add ranks.
Difference from the winner is `(host - winner) / abs(winner) * 100`, labeled as a
percentage above or below the best; when the winner is zero, show a dash.
Sort matrix rows by the best-across-hosts value in the dimension's direction,
unranked rows last, then by list display ID and path for deterministic ties.

Price comparisons use the exact representation in Hosts response. Share
BigInt rational comparison helpers across price ranking, ties, row ordering,
price limits and winner differences. Parse price-limit decimal text directly
into a rational without a Number intermediate, preserving that text in Hash
state. Convert a final percentage for display only after the exact arithmetic.
These browser helpers are new: the Sources price resolver owns provider-unit
normalization, while this view needs exact comparisons during interaction.

### Conditions

The table order defines the first failing reason. Conditions are inactive
until added, except that entering model search or excluding a host activates
that condition. An endpoint qualifies when it passes each active condition.

| Condition | Editor and matching | Missing values |
|---|---|---|
| Exclude hosts | host chips; reject selected names | — |
| Status | "normal only" switch; this view defines normal as code 0 and labels other codes `status <code>` without interpreting their cause | missing fails |
| Precision | observed quantization chips; shortcuts use Precision ladder | use Hosts response normalization; unrecognized strings have their own chips |
| Uptime | window and minimum percent; presets 99, 99.5, 99.9, 99.99 | include-missing switch; suspend the condition when telemetry is not `available` and show Missing uptime copy |
| Context length, max output | minimum; presets 32K, 128K, 200K, 1M; accept K and M suffixes | missing fails |
| Supports | required supported-parameter chips, native-tool chips, implicit-caching switch; require each selected capability | missing fails |
| Service tier | allowed observed tiers; display string tiers with JSON quoting | null has the display label `standard` |
| Price limit | column and maximum in that column's unit | missing fails |
| Model search | case-insensitive substring over list display ID and mapped model IDs | — |

Precision ladder is Python-owned normalization:

| Bit width | Quantization values |
|---|---|
| 32 | `fp32` |
| 16 | `bf16`, `fp16` |
| 8 | `fp8`, `int8` |
| 6 | `fp6` |
| 4 | `fp4`, `mxfp4`, `nvfp4`, `int4` |
| null | `unknown` or an unrecognized value |

The "16-bit or better" and "8-bit or better" shortcuts select recognized
chips at or above their threshold, deselect recognized chips below it, and
leave null-width chips unchanged. "Any" selects each chip.

Opening a chip condition initially selects its observed values. An active
empty Precision or Service tier selection matches nothing. Removing the
condition restores unrestricted matching. See Hash state for persistence.

A removal count is the number of capture endpoints failing that condition
alone, ignoring other conditions. Break equal largest-removal counts by
condition order when choosing condition-removal text under Copy.

### Row admission and Reset

Row match defaults to `any`: a list is admitted if a selected host has a
qualifying endpoint. In `all` mode, each selected host must have one. With no
host selected, admit lists where a host qualifies.

With "Show excluded" enabled, evaluate row admission against endpoint
presence instead of qualification, retaining the chosen any/all host rule.
Fill failing endpoints in admitted rows, dimmed, with their first failing
reason. Presence does not make a failing endpoint rankable or qualifying.
With no selected hosts this exposes lists even when their endpoints all fail.
Empty lists remain absent from the matrix.

Initial state has no conditions, the default Ranking and row match, and
"Show excluded" off. Reset restores that state, keeping provider, selected
hosts and snapshot.

### Copy

Choose result-state copy in this order: empty capture, no qualifying
endpoints, then no admitted matrix rows. Ranking's unavailable-value message
applies to admitted rows rather than replacing these states.

| State | Copy |
|---|---|
| Provider without captures | `<provider label> has no saved endpoint capture yet. Saved scans record hosts while endpoint capture is on.` |
| Missing uptime | `Uptime isn't stored for this snapshot yet.` Add `The next saved scan can backfill it from its archive.` only when an archive is eligible for backfill. |
| Empty capture: no endpoint records | `No endpoints were recorded in this capture.` |
| No qualifying endpoints, with active conditions | `No endpoint meets every condition. [condition] removes the most ([removal count] endpoints).` Focus that condition's phrase. |
| No admitted matrix rows despite qualifying endpoints | `No qualifying list matches the selected hosts and row rule.` |
| Host history with a single point | `History starts <date>. Later usable captures add points.` |

## Storage and API contracts

### Telemetry storage

Append these statements to `storage.SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS endpoint_telemetry_captures (
    capture_id INTEGER PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('scan', 'archive')),
    recorded_at TEXT NOT NULL,
    endpoint_count INTEGER NOT NULL CHECK (endpoint_count >= 0),
    unmatched_count INTEGER NOT NULL CHECK (unmatched_count >= 0),
    FOREIGN KEY (capture_id) REFERENCES endpoint_captures(capture_id)
);
CREATE TABLE IF NOT EXISTS endpoint_telemetry (
    capture_id INTEGER NOT NULL,
    list_path TEXT NOT NULL,
    endpoint_key TEXT NOT NULL,
    uptime_5m REAL CHECK (uptime_5m IS NULL OR (uptime_5m >= 0 AND uptime_5m <= 100)),
    uptime_30m REAL CHECK (uptime_30m IS NULL OR (uptime_30m >= 0 AND uptime_30m <= 100)),
    uptime_1d REAL CHECK (uptime_1d IS NULL OR (uptime_1d >= 0 AND uptime_1d <= 100)),
    telemetry_json TEXT NOT NULL,
    PRIMARY KEY (capture_id, list_path, endpoint_key),
    FOREIGN KEY (capture_id, list_path, endpoint_key)
        REFERENCES endpoint_observations(capture_id, list_path, endpoint_key)
);
```

A telemetry-capture marker means processing completed, even if no endpoint
rows were produced. `endpoint_count` counts inserted rows; `unmatched_count`
counts archive endpoints with no matching saved observation. Missing markers
on archived captures are pending backfill. Minimal error captures without
archives are ineligible and excluded from pending counts.

Save a `scan` marker and telemetry rows in the existing
`Store.save_endpoint_capture` transaction. Leave stable-state comparison
governed by the Sources authorities. An uptime column accepts only finite
`int` or `float` values, excluding booleans, satisfying its SQL constraints;
otherwise store NULL. Preserve present raw telemetry fields, including nulls
and rejected uptime values, in canonical `telemetry_json` using the archive's
JSON serialization conventions.

Backfill archived captures lacking a marker for the provider, oldest first.
Process each in its own `BEGIN IMMEDIATE` transaction on
`_connect_capture_writer`: decode the archive, extract telemetry with the same
keying as new captures, insert matching observations, count unmatched
endpoints, and write an `archive` marker. Rerunning skips completed markers.
A failed archive leaves its transaction rolled back and marker absent.

Run backfill before endpoint capture for a saved scan of a capture-capable
provider, independently of the capture setting. It needs no network request.
Wrap it in its own exception handler preserving the scan-isolation authority
in Sources; log a redacted warning on failure and result counts on progress.
Healthcheck adds pending and unmatched counts without changing its status.

### Hosts response

`GET /api/hosts` takes required `provider` known to `ApiContext` and optional
`scrape_id`. Validate explicit scrapes through the saved-scrape authority in
Sources; never substitute another capture. Omitted `scrape_id` chooses the
newest usable saved scrape by catalog completion time and scrape ID. Use
`first_usable_endpoint_capture_date`'s usability predicate for capture lists
and `meta.host_providers`, preserving the provider order in `meta.providers`.
Reuse API error handling from Sources.

Specify response fields with types rather than maintaining example payloads:

| Field | Contract |
|---|---|
| `provider_id`, `scrape_id` | selected provider string and selected scrape integer, or null scrape when none exists |
| `reason` | null, `no_tables`, `not_captured`, or `capture_error`; non-null reasons have empty `lists`, `hosts`, `endpoints` |
| `captures` | usable saved scrapes, newest first; `json_scrape` projection plus `capture_id` and `capture_status`, suitable for `SnapshotPicker` |
| `capture` | selected capture or null; use the shared dossier capture-status projection |
| `telemetry` | `available` when the selected capture has a marker, `pending` when telemetry tables exist but its marker is absent, otherwise `no_tables` |
| `backfill_eligible` | boolean: selected capture has an archive and lacks a marker |
| `price_columns` | column descriptors: `path`, `label`, `unit_label`, `comparison_group`, using the dossier's price-resolution authorities |
| `lists` | list records containing `path`, `display_id`, mapped listed `models`, and `aliases` |
| `hosts` | host records: `name`, `endpoint_count`, distinct `list_count`, `uptime_1d_median` |
| `vocab` | sorted `parameters`, `native_tools`, `quantizations`, and observed normalized `tiers` (nullable strings) |
| `endpoints` | endpoint records as defined below |

An endpoint record contains `list` (index into `lists`), `key`, `host`, `tag`,
`status`, `quantization`, `precision_bits`, `context_length`,
`max_completion_tokens`, `max_prompt_tokens`, `service_tier`, `parameters`,
`native_tools`, `implicit_caching`, `prices`, and `uptime`.

Compute `host` through a shared Python helper that behaves as the dossier's
`EndpointTable` display-name expression does. Normalize missing or non-string
quantization to `unknown`; derive `precision_bits` through Precision ladder.
Normalize missing or non-string `service_tier` to null.
`parameters` and `native_tools` index their vocabulary arrays; native-tool
values are the sorted keys of an object, with missing/non-object inputs
treated as empty. Derive implicit caching only from a literal true
`supports_implicit_caching`; absent or malformed capability values do not
assert support.

`prices` maps column paths to `{exact, display, raw}`. Serialize each resolved
leaf's `normalized_exact_value` as `exact`, an object containing
`numerator_hex` and `denominator_hex` strings produced by `format(integer, "x")`
from the Fraction components. Decode the numerator's sign separately
before constructing a BigInt from its hexadecimal magnitude. This encoding
avoids Python's decimal integer-string limit without changing interpreter
settings. Format a column with a capture-wide
`format_price_values(..., precision_basis=())` call.
This is a new matrix formatting scope; comparison with dossier display text
must not require identical decimal places. `uptime` has nullable numeric
`1d`, `30m`, `5m` fields, null unless telemetry is `available`.

### Host history response

`GET /api/host_history` takes required `provider` and `host`, and optional
`from` and `to` parsed through the common-parameter authority in Sources.
It returns `host`, `telemetry`, `series`, `changes`, `limit`, `truncated`.
For absent telemetry tables, `telemetry` is `no_tables`; otherwise it is
`pending` if a selected usable capture lacks a marker, else `available`.
The series still includes capture-level counts when uptime is unavailable.

`series` contains one point per usable saved capture in range, in catalog
order: `scrape_id`, `date`, distinct `lists`, `endpoints`, nullable
`uptime_1d_median`, nullable `uptime_1d_min`, `not_normal`, and `capture` using
the Hosts response capture projection. Counts measure observed records.
For a host absent from a complete capture, counts are zero; for a host absent
from an incomplete capture, `lists`, `endpoints` and `not_normal` are null.
Absent hosts have null uptime. A missing marker also contributes null uptime,
never a carried-forward value. In history, mark incomplete points explicitly,
show their capture status line, and break trend lines at them; any observed
values remain available in their tooltips. This coverage contract is new for
host-level aggregation, where a failed list cannot establish a host's absence.

Attribute changes using the host helper on the target observation for added,
field-changed and status-changed endpoints; use the baseline observation at
`from_list_path` for removals. Filter by the target scrape's local date, and
order changes by target catalog completion time, scrape ID, then change ID,
descending.

The history query supplies the row shape of
`queries.endpoint_list_changes`, including decoded values and
`from_scrape`/`to_scrape` summaries. Load each change's target
`EndpointListRecord` by `to_capture_id` and `list_path`, then pass it and
`endpoint_label_profile(profile)` to the shared dossier serializer. Baseline
observation attribution does not replace the target-list metadata needed for
serialization. Handle missing required lists as dossier integrity errors.
Add `list_path` and `display_id` to the serialized output. Use the dossier's
change-limit and truncation authorities from Sources.

### Hash state

| Key | Meaning | Kind |
|---|---|---|
| `view=hosts` | Hosts view | existing scalar |
| `hosts` | selected hosts, bounded by `meta.pin_limit` | list |
| `hasof` | snapshot scrape ID | scalar |
| `rank` | `price:<column path>`, `uptime:1d`, `uptime:30m`, `uptime:5m`, `context`, `output` | scalar |
| `match` | `any` or `all` | scalar |
| `hq` | model search | scalar |
| `xhosts` | excluded hosts | list |
| `showx` | `1` enables Show excluded | scalar |
| `quant`, `quantset` | allowed quantizations; `quantset=1` activates even an empty selection | list, scalar |
| `upwin`, `upmin`, `upmiss` | uptime window, minimum, include-missing (`1`) | scalar |
| `healthy` | `1` enables Status condition | scalar |
| `ctxmin`, `outmin` | capacity minima | scalar |
| `params`, `ntools` | required parameters and native tools | list |
| `caching` | `1` requires implicit caching | scalar |
| `tiers`, `tierset` | JSON-encoded native tier values; `tierset=1` activates even an empty selection | list, scalar |
| `plimit` | `<column path>:<max>` | scalar |

Validate against the current capture's vocabulary and dimensions. Normalize
invalid values with `replaceState`; follow PKM 158 for navigation and typing,
and PKM 159 for retained API data. Register list keys in `LIST_KEYS` and keys
in `HASH_KEYS` and `resolveState`. Encode each native tier with `JSON.stringify`
before placing it in the hash list; decode with `JSON.parse`, requiring a
nullable string present in `vocab.tiers`. Display labels from Conditions are
not machine identities. Removing a chip condition clears its list and flag.

## Fixture cases

Add `build_hosts_fixture_db(path) -> HostsFixtureFacts` separately from
`build_fixture_db`. Keep existing endpoint fixture state unchanged. Name
tests for the following cases and record their expected values and identities
in `HostsFixtureFacts`; the fixture must supply the cases those tests need.
Use conspicuously synthetic data and fixed timestamps.

| Case | Required fixture coverage |
|---|---|
| `host_history_attribution` | compared usable captures with added, removed, field-changed and status-changed endpoints, including a moved list path |
| `host_history_truncation` | more changes than `DOSSIER_ENDPOINT_CHANGE_LIMIT` |
| `host_single_capture` | another capture-capable provider with a single archived capture and missing telemetry marker |
| `host_grouping_and_ties` | shared lists and aliases, multiple tags for a host on a list, ties between hosts, and values that change winners and matrix row order between ranking dimensions |
| `host_precision_conditions` | each Precision ladder value, an unrecognized string, and Hosts response precision-normalization cases |
| `host_missing_ranking` | resolved zero price, missing individual ranking values, a capture without price columns, a window without numeric uptime, and a list with no rankable values |
| `host_exact_prices` | distinct resolved prices with the same Number projection, a price at the Sources resolver's negative decimal-exponent bound, negative prices, and price limits separating exact values; assert serialization, ranking, tie markers, winner differences and thresholds |
| `host_partial_coverage` | compared complete and partial captures where a host's list fails while another succeeds, plus a complete capture confirming no host observations; exercise Host history response coverage |
| `host_empty_results` | an empty-only usable capture and disjoint selected-host list coverage; exercise Copy precedence |
| `host_tier_identity` | Hosts response tier-normalization cases and literal strings matching the null display label or null's serialized spelling; assert distinct chips and reversible hash selections |
| `host_condition_counts` | present/missing uptime and capacity, status 0 and other codes including missing, differing parameter sets, native-tool objects, literal/malformed implicit caching, null and non-null tiers, price limits, host exclusion and model-search matches |
| `host_row_admission` | any/all differences and lists whose endpoints all fail active conditions |
| `host_list_identity` | missing response ID and mapped/unmapped list titles |
| `host_legacy_and_reasons` | missing endpoint tables, missing telemetry tables, uncaptured scrape, and capture-wide failure |

## Implementation tasks

For completion criteria, see Final validation.

### Store endpoint uptime and backfill archives

Deliver Telemetry storage through the following changes:

- `provider_profiles.py`: add `endpoint_uptime_fields: Mapping[str, str]` to
  `ProviderProfile`, default empty. Validate it in `__post_init__` as window
  keys `5m`, `30m`, `1d` mapped to members of `endpoint_telemetry_fields`.
  Configure OpenRouter's corresponding uptime fields.
- `models.py`: add frozen `EndpointTelemetryRecord(list_path, endpoint_key,
  uptime_5m, uptime_30m, uptime_1d, telemetry)` and defaulted
  `telemetry: tuple[EndpointTelemetryRecord, ...] = ()` on
  `EndpointCaptureCandidate`.
- `endpoints.py`: add pure `endpoint_telemetry_records(bodies, profile) ->
  tuple[EndpointTelemetryRecord, ...]`, using the Sources parsing and keying
  authorities in sorted path order. Skip bodies raising `EndpointListError`.
  Call it from `build_endpoint_capture` and archive backfill.
- `storage.py`: implement the Telemetry storage statements and transaction
  behavior. Expose `Store.backfill_endpoint_telemetry(provider_id, profile) ->
  TelemetryBackfillResult(captures, rows, unmatched)` and
  `Store.endpoint_telemetry_status(provider_id) -> (pending_captures,
  unmatched_total)`.
- `cli.py`: integrate the scan and healthcheck behavior from Telemetry storage.
- `README.md`, Endpoint capture: document rolling-window samples, storage,
  backfill and healthcheck. Subsequent Browse History documentation links to
  this section for those facts.

Tests: extend `test_endpoints.py`, `test_storage.py` and `test_cli.py` for
Telemetry storage, extraction key parity, invalid bodies, transaction rollback,
idempotence, unmatched observations, archive-free error captures, isolated
backfill failure and healthcheck output. In `test_storage.py`, add the
Telemetry storage tables to `_ENDPOINT_TABLES`; retain
`test_endpoint_legacy_schema_preservation` and its legacy-prefix assertions.
The additional schema statements require updating this table inventory, not
weakening the preservation check.

Acceptance from `model_sentinel/`:

```bash
.venv/bin/python -m pytest tests/test_endpoints.py tests/test_storage.py tests/test_cli.py
```

### Serve Hosts and host history

Deliver Hosts response and Host history response through:

- `endpoint_report.py`: expose `_state_leaves` as `state_price_leaves`,
  updating callers rather than copying price logic.
- `provider_profiles.py`: add `QUANTIZATION_BITS` and
  `quantization_bits(value) -> int | None` implementing Precision ladder.
- `browse/api.py`: expose `_scrape_for_catalog` as `_saved_scrape`, updating
  Catalog; add `hosts(ctx, params)` and `host_history(ctx, params)`. Extend
  `meta` with `host_providers` as defined in Hosts response.
- `browse/endpoints_api.py`: extract the capture status-line projection and
  `_change_json` into shared functions used by the dossier and new API.
- `browse/queries.py`: add `_translate_busy`-wrapped
  `endpoint_telemetry_present`, `host_captures(provider_id)`,
  `capture_endpoint_rows(capture_id)`, `capture_list_models(capture_id)`,
  `host_series` and `host_changes`. Join telemetry only when its tables exist,
  using `LEFT JOIN` to preserve observations without samples. Use SQLite
  `json_extract` and the shared host-name fallback for history attribution.
- `browse/hosts_api.py`: add `hosts_response`, `host_history_response` and the
  shared host-name helper.
- `browse/server.py`: register `hosts` and `host_history` in `_API_ROUTES`.
- `tests/browse_fixtures.py`: implement Fixture cases.

Tests in `test_browse_queries.py` and `test_browse_api.py` cover the response
contracts and Fixture cases, including exact serialization from the Sources
price resolver and capture-wide display scope. Update
`test_meta_includes_configured_and_db_only_providers`' exact response-key
assertion for `host_providers`, preserving its other assertions. Compare the
dossier `/api/endpoints` output before and after shared-function extraction
for byte-identical responses. Extend `test_browse_readonly.py` and
`test_browse_server.py` for legacy database reads, no writes, routes and errors.

Acceptance:

```bash
.venv/bin/python -m pytest tests/test_browse_queries.py tests/test_browse_api.py tests/test_browse_readonly.py tests/test_browse_server.py tests/test_endpoints.py
```

### Build the roster, matrix and profile

Deliver Presentation, Layout, Ranking, and the view-selection portion of Hash
state. In `app.js`:

- Add `hosts` to `VIEWS`, extend the number-key handler from `VIEWS`, and add
  an explicit Hosts branch to `App`'s render chain.
- Add `Hosts({meta, state, write, replaceState, openModel, themeKey})`. Select
  the first selected provider in `meta.host_providers`, else its first entry,
  else show the provider-without-captures copy. Normalize through an effect
  with `replaceState`, following `Catalog`.
- Use `SnapshotPicker` for captures. Add `HostRoster`, `HostMatrix`,
  `HostProfile` and `HostHistory`; the latter fetches `/api/host_history`
  using filter-bar dates. Add shared pure `rankValue` and `bestEndpoints`
  helpers implementing Ranking for the matrix and profile.
- Register `hosts`, `hasof`, `rank`, `match`, `hq`, `xhosts` from Hash state.

Implement Presentation and Layout styles in `app.css`. Add `hosts` to CLI
`--view` choices and help. Document this task's view behavior and number key
under README Browse History.

In `test_browse_offline.py`, rename
`test_model_dossier_route_wires_changelog_and_sparklines_without_a_fourth_tab`
to end in `_without_a_dossier_tab`; replace its literal tab-list assertion
with assertions that `model` is absent and `hosts` present in `VIEWS`, keeping
its dossier wiring checks. Record why if a commit is later requested.

Add `hosts_server` to `test_browse_smoke.py`, using the fixture authority in
Sources. Add `hosts_page` following `endpoint_page`, explicitly passing
`_origin(hosts_server)` to `_guarded_page`; use `hosts_page` for the Hosts
browser cases. Browser cases exercise the view contracts using
Fixture cases, plus tab/number-key navigation, Back, reload, dossier links,
cell expansion, loading/error resource changes and narrow viewport behavior.
Test `browse --view hosts` and its fragment in `test_cli.py` and
`test_browse_server.py`. Run `test_browse_theme.py` unchanged.

Acceptance:

```bash
.venv/bin/python -m pytest tests/test_browse_smoke.py tests/test_browse_offline.py tests/test_browse_theme.py tests/test_cli.py tests/test_browse_server.py
```

### Build the question line and prepare the release

Deliver Conditions, Row admission and Reset, Copy, and remaining Hash state.
Add `QuestionLine` and `ConditionPopover` using `Portal`,
`typeaheadPlacement` and `useFocusTrap`. Editors open by keyboard, close with
Esc, and restore focus to their phrases. A pure
`evaluateEndpoint(endpoint, conditions) -> {pass, reasons}` supplies roster,
matrix, profile, removal-count and excluded-cell decisions.

Extend `test_browse_smoke.py` against `hosts_page` and Fixture cases to
exercise the condition contracts, first-reason order, empty chip selections,
all-excluded rows, Reset and hash round trips. Test numeric typing history
against PKM 158 and popover keyboard/focus behavior.

Add `tests/hosts_validation_fixture.py`, a module CLI accepting a runtime
directory. Extract the Sources runtime-isolation helpers to a shared test
helper and keep the existing model-view builder/tests using it. Validate the
target before writing, create synthetic provider/settings files matching the
Hosts fixture, disable notifications, and build the fixture database at
`config.RuntimePaths.database_path`. Print the resolved runtime directory.
`tests/test_hosts_validation_fixture.py` checks loadability and the rejection
cases established by the existing isolation tests, including filesystem aliases.
This builder is needed because the model-view builder supplies different
history and cannot exercise the Hosts contracts.

Document conditions in README Browse History, referencing Endpoint capture
for telemetry facts. Increment `model_sentinel/__init__.py`'s `__version__`
by a minor version, following the Sources release precedent; confirm the
increment with the owner before release. Complete Final validation before
claiming implementation complete.

### Optional: expose endpoint facts in the dossier

Add `quantization` and `context_length` to
`endpoint_report.EndpointTableRow`, telemetry to `endpoint_response`, and
corresponding columns in `app.js` `EndpointTable`. Use the Status condition's
label convention. Document the columns in the README dossier paragraph.
Extend `test_browse_api.py` and `test_browse_smoke.py` for columns and unavailable
telemetry. Run Final validation; if released separately, give this change its
own version bump.

## Final validation

From `model_sentinel/`, run the full documented suite:

```bash
.venv/bin/python -m pytest
.venv/bin/python model-sentinel --version
.venv/bin/python model-sentinel browse --help
```

Expected: tests pass without skips, the bumped version is printed, and help
includes `hosts`. Follow README Testing for dependencies; use the project
venv and `.venv/bin/python -m playwright install chromium` if needed. Do not
treat task-level checks as substitutes for the full suite.

Use the new synthetic runtime builder for visual validation after it exists:

```bash
hosts_acceptance_home=$(mktemp -d /private/tmp/model-sentinel-hosts.XXXXXX)
hosts_acceptance_home=$(.venv/bin/python -m tests.hosts_validation_fixture "$hosts_acceptance_home") &&
MODEL_SENTINEL_HOME="$hosts_acceptance_home" .venv/bin/python model-sentinel browse --no-open --view hosts --port 0
```

Only a successful builder run may start browse. Open its printed URL and
inspect Layout and Presentation in light and dark themes and at narrow width.
After stopping the server, remove the exact validated directory with
`rm -r -- "$hosts_acceptance_home"`.

A real saved scan writes to the runtime database and requires separate owner
authorization. After an authorized scan, inspect marker aggregates read-only:

```bash
sqlite3 -readonly ~/.model_sentinel/model_sentinel.db \
  "select source, count(*), sum(endpoint_count), sum(unmatched_count) from endpoint_telemetry_captures group by source"
```

Reconcile aggregates against Telemetry storage eligibility and marker rules;
investigate unmatched observations.
Standalone deployment is a separate authorized action under README Standalone
Install and `docs/LAUNCHD.md`.
