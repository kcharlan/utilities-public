# `model-sentinel browse` — History Browser Design

Date: 2026-08-23
Status: approved design; implementation plan at `docs/model_sentinel_browse_implementation_plan.md`
Precursor: [`docs/model_sentinel_browser_design_proposals.md`](../../model_sentinel_browser_design_proposals.md)
(three approaches, recommendation, decisions)

## 1. Decisions already made

| Question | Decision |
|---|---|
| Shape | One SPA, three views — **Activity** (event-first), **Models** (model-first timelines), **Catalog** (snapshot-first table/diff) — over shared URL-hash state with cross-links. Build order: Activity → Models → Catalog. |
| Packaging | A **`browse` subcommand of `model-sentinel`**, not a separate project. Ships inside the existing zipapp; one installer, one version, one `--check`. |
| Runtime deps | **None.** Backend is stdlib `http.server`; the package stays stdlib-only. |
| Offline | **Fully offline.** Every byte the page needs is served from package data. The served HTML must reference no external URL. |
| Frontend libs | **Preact + htm + uPlot**, vendored as minified files with their MIT LICENSE texts under `model_sentinel/browse/assets/vendor/`. Hand-written CSS; no Tailwind. |
| Benchmarks | First-class aspect family in Models; squelched in Activity by default (existing squelch patterns). |
| Multi-model cap | Models view pins at most **8** models. |
| Writes | The browser **never writes**: DB opened `mode=ro` with `PRAGMA query_only = ON`, no cache, no config of its own; view state lives only in the URL hash. This explicitly excludes `runtime_paths.ensure_directories()`, which creates `logs/` and `reports/` — `browse` dispatches before it, and configures its own stderr logger rather than opening the rotating log file. |

## 2. Scope

**Prerequisite (in scope).** `Store.recent_changes` is quadratic: a per-row
correlated subquery over `snapshot_models` with no date predicate in SQL. It
is measured at 280 s for the full history and 310 s for a one-month range, and
the shipped `changes --since <3 days ago>` takes 5 m 12 s. The Activity view
needs those rows on every request, and a second query would duplicate logic,
so the fix ships with this work as Task 0 of the plan. `Store.recent_changes`
keeps its exact output; the new `recent_change_rows` carries `change_id` for
the browser.

In scope for this spec (one implementation plan):

- `browse` subcommand and stdlib HTTP server
- JSON API (§5)
- the three views with shared state and cross-links (§6)
- installer/`--check` extension for non-Python package data (§8)
- tests (§9) and README/help updates

Out of scope (explicitly deferred): market aggregates across all models
(median lines, counts-of-✓ over time), scrape-health view, CSV export,
unlimited pins / band charts.

## 3. Runtime requirements and CLI

```
model-sentinel browse [--port 8110] [--no-open] [--provider ID]
```

- `--port`: preferred port; the server uses the first free port from it,
  scanning up to 20, and logs a warning when it differs (repo
  `find_free_port` convention, implemented in `browse/server.py` with stdlib
  `socket`).
- `--no-open`: do not launch the system browser. Default opens
  `http://127.0.0.1:<port>/` via `webbrowser` after the server is listening.
- `--provider`: initial provider filter (validated against configured
  providers like `changes --provider`); purely a default for the hash state.
- Binds `127.0.0.1` only. Ctrl-C shuts down cleanly (no traceback).

Configuration it needs, identical to what `changes` needs today:
`~/.model_sentinel/providers.env` (provider kind + price factors → profile),
`~/.model_sentinel/settings.env` (report detail mode and squelch/show
patterns), and the database at `runtime_paths.database_path`.
`MODEL_SENTINEL_HOME` is honored through the existing `load_config`.

**Dispatch (load-bearing).** `cli.main()` calls
`loaded.runtime_paths.ensure_directories()`, `_configure_logger(loaded)`,
`store.initialize()` and `store.upsert_provider_configs(...)` for every
command except `healthcheck`; all of those write (the first creates
directories, the second opens the rotating log). `browse` must be dispatched
*before* that block, immediately after `load_config` succeeds, and must
configure its own stderr logger. It constructs read-only connections:

```python
sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True)
```

(`Path.as_uri()` yields `file:///…`, which SQLite accepts with `?mode=ro`.)
**One connection per thread**, held in a `threading.local()` — the server is a
`ThreadingHTTPServer` and a single connection shared across request threads is
unsafe even read-only. Each connection sets `PRAGMA query_only = ON` and
`PRAGMA busy_timeout = 5000`.
If the database file does not exist, exit 2 with a message naming the path
and suggesting `model-sentinel scan --save`; do not create it.

Read-only is also enforced in code: the connection runs
`PRAGMA query_only = ON` and the handler layer exposes no mutating path.

## 4. Package layout

```
model_sentinel/
  cli.py                     # + browse subparser and dispatch
  browse/
    __init__.py
    server.py                # ThreadingHTTPServer, routing, static + JSON, port scan, open browser
    api.py                   # endpoint handlers: parse query → queries/reporting → JSON-able dicts
    queries.py               # every SQL statement for the browser; read-only connection helper
    aspects.py               # aspect catalog: canonical columns + metadata paths, units, categories
    assets/
      index.html             # shell; inlines nothing, references ./app.css ./vendor/*.js ./app.js
      app.css
      app.js                 # Preact + htm application (no build step, plain ES modules or a single IIFE)
      vendor/
        preact.min.js  preact.LICENSE
        htm.min.js     htm.LICENSE
        hooks.min.js   (preact/hooks)
        uplot.min.js   uplot.min.css  uplot.LICENSE
        VERSIONS.md    # exact upstream versions and download URLs
```

Assets are read with `importlib.resources.files("model_sentinel.browse") / "assets"`
so they resolve identically from a checkout and from inside the zipapp.
Static responses carry `Content-Type` by extension and
`Cache-Control: no-store` (the app is local; stale caches cost more than
bandwidth).

## 5. JSON API

All endpoints are `GET`, return `application/json; charset=utf-8`, and on
error return `{"error": "<human message>"}` with 400 (bad parameter), 404
(unknown route/id) or 500. Query parameters:

- `providers` — comma-separated provider IDs; default all configured.
- `from`, `to` — inclusive local dates `YYYY-MM-DD`, interpreted with the
  existing `time_utils.local_date_for` convention, same as `changes --since/--until`.
- `detail` — `default | all | squelched`, same vocabulary and semantics as
  the CLI; default comes from `settings.env`.

### `GET /api/meta`
One call on page load. Returns:
- `providers`: `[{id, label, kind, enabled}]` from config (not the DB table)
- `date_span`: `{first, last}` local dates of saved scrapes
- `scrapes`: `[{scrape_id, provider_id, date, completed_at, status, saved, model_count}]`
  (all scrapes; ~200 rows is fine, and Catalog needs the exact list)
- `aspects`: the aspect catalog (§5.1)
- `categories`: the ordered category list (`Pricing`, `Context & Limits`, `Capabilities`,
  `Parameters`, `Benchmarks`, `Other`) — the client must not infer facets from `aspects`
- `detail_default`: the configured detail mode
- `pin_limit`: 8
- `bulk_min_models`: 3

`providers` lists configured providers **and** any provider present only in the `providers`
DB table, flagged `configured: false`; history must not vanish when a provider is removed
from `providers.env`.

### 5.1 Aspect catalog (`browse/aspects.py`)

An *aspect* is one time-series-able field. Two sources:

1. **Canonical columns** of `snapshot_models`: `input_price`, `output_price`,
   `cache_read_price`, `cache_write_price`, `context_window`,
   `max_output_tokens`, the seven `*_supported` booleans, `deprecated`,
   `status`.
2. **Metadata paths** discovered from `field_changes.field_name` values
   (distinct, non-null, per provider) whose leaf is scalar — e.g.
   `benchmarks.artificial_analysis.intelligence_index`, `pricing.web_search`,
   `top_provider.is_moderated`. Read via `json_extract(metadata_json, '$.a.b.c')`.

Each aspect entry: `{id, source: "column"|"path", column|path, provider_id,
label, qualifier, category, kind: "price"|"count"|"numeric"|"boolean"|"list"|"scalar",
unit, scale}`. **Label, category, unit and scale come from the provider
profile** via `change_render.resolve_field_label`, `profile.categorize`, and
`change_render.resolve_price_rule` — never re-derived. Canonical price
columns map to their profile price field (OpenRouter: `input_price` ↔
`pricing.prompt`, etc.) so they display with the same unit the reports use.

Aspects whose `field_name` matches the squelch patterns are still listed
(benchmarks are first-class here) but carry `squelched: true` so the Models
view can group them under a collapsed "Benchmarks / other squelched" heading.

### `GET /api/activity`
Params: `providers, from, to, detail, models` (comma list, optional),
`categories` (comma list of profile category names, optional), `kinds`
(`added,removed,changed`), `page`, `page_size` (default 100, max 500).

Source rows come from `storage.recent_change_rows(connection, ...)` — the
connection-taking function introduced by the storage performance fix, which
also carries `change_id`. Rendering **reuses the `changes` report planner**:
`reporting._plan_changes_report_provider` becomes public
(`plan_changes_provider`) with no behavior change, so the feed shows exactly
the entries and hidden rollups the HTML `changes` report shows.

**Bulk groups are not free.** The changes planner does *not* consolidate
repetitive list changes — that logic lives in the scan planner
(`_plan_provider_changes`). Activity therefore applies a new
`reporting.group_planned_entries_by_bulk`, which reuses the existing
`_bulk_change_signature` and `BULK_CHANGE_MIN_MODELS` rather than inventing a
second rule, and is additive (no existing renderer calls it, so `changes`
output is unchanged).

Each visible `FieldChange` is serialized through
`change_render.classify_change` → `dataclasses.asdict(RenderedChange)`
verbatim — that output is already JSON-serializable and `price_rule` is
already a nested dict (its unit key is `unit_label`). `kind/direction/semantic`
drive color in the client and the client does no formatting of its own.

Response:
```
{ "total": N, "page": p, "page_size": s,
  "entries": [
    {"date": "2026-08-21", "provider_id": ..., "model_id": ..., "display_name": ...,
     "kind": "added"|"removed"|"changed"|"bulk",
     "bulk_models": [{model_id, display_name}…],   # bulk only
     "changes": [RenderedChange…],          # changed only, visible rows
     "hidden": {"squelched": n, "unclassified": n, "noop": n},
     "change_ids": [...] }                    # for /api/change drill-in
  ],
  "rollups": {"squelched": [[field, count]…], "non_squelched": [...], "noop": [...]} }
```
Paging is over entries after planning (planning needs the whole date
bucket to build bulk groups; the result set for five months is ~1.5K
entries after squelching, well within memory). Category and model filters
apply after planning too, so counts stay consistent with the report.

### `GET /api/heatmap`
Params: `providers, from, to, detail`. Returns `[{date, changed, added,
removed, squelched}]` per local date. Counts come from one SQL `GROUP BY`
on `field_changes` joined to nothing; `squelched` is computed by applying
`reporting.visibility_of` to each distinct `field_name` once and summing by
date (51 distinct field names in practice). **`visibility_of`, not
`classify_detail_visibility`**: added/removed rows store `field_name = NULL`
and the raw helper raises `TypeError` on `None`. Local-date bucketing happens
in Python via `local_date_for` — never SQL `date()`, which is UTC and
mis-buckets evening scans.

### `GET /api/series`
Params: `models` (comma list of `provider_id/model_id`, ≤ 8), `aspects`
(comma list of aspect ids, ≤ 12), `from, to`.

Returns the **dense** series over saved successful scrapes in range, aligned
to a single **union time axis** across every provider involved — pins may span
providers, so a per-provider x-axis cannot be expressed in one response:
```
{ "axis": [{scrape_id, provider_id, date, completed_at, t}…],
  "series": [{model, aspect, provider_id, kind, unit,
              values: [v|null…], list_hash: [h|null…]}] }
```
Each series is `null` at every axis index belonging to another provider or to
a scrape where that model was absent.
Values are **display-ready** in the profile's unit (`$ / 1M tokens`).
Canonical price columns of `snapshot_models` are **already normalized**
at save time (`normalize._normalize_price`) and are returned as stored;
only metadata-path price aspects are raw and are scaled server-side by
their `resolve_price_rule` factors. Scaling a canonical column again
would inflate it by the provider factor and is a correctness defect.
Booleans as 0/1/null, lists as their length
with the member list available via `/api/catalog` — list aspects are drawn
as a state strip that changes color on membership change, so the series
also carries `list_hash: [...]` (a stable hash per point) for that purpose.
`null` where the model is absent from a scrape (the chart breaks the line
there; an absent model is a fact, not zero).

SQL: one statement per provider, `SELECT scrape_id, provider_model_id,
<columns…>, json_extract(metadata_json, …) … FROM snapshot_models WHERE
scrape_id IN (saved successful scrapes in range) AND provider_model_id IN
(…)`, pivoted onto the union axis in Python. Fewer than 8 × 170 rows; measured
at 0.032 s for one model, no index needed. Column and path identifiers come
only from the aspect catalog's whitelist; all values are bound parameters.

### `GET /api/events`
Params: `models` (≤ 8), `from, to, detail`. The sparse companion to
`/api/series` for the event rail: `[{change_id, date, model, kind, field,
semantic, direction, squelched}]`. Squelched events are returned with the
flag (the rail dims them) rather than dropped, so the rail matches the chart
even for benchmark aspects.

### `GET /api/catalog`
Params: `provider` (one), `as_of` (scrape_id), `compare` (scrape_id,
optional, must be earlier), `columns` (comma list of aspect ids; default the
canonical price/limit/capability set), `q` (substring filter on model id or
display name), `sort`, `dir`, `page`, `page_size` (default 200).

Returns rows for every model in `as_of` (plus models only in `compare`,
marked removed):
```
{ "as_of": {...scrape}, "compare": {...}|null, "total": N,
  "rows": [{model_id, display_name, presence: "present"|"added"|"removed",
            cells: {aspect_id: {value, display, unit,
                                old_value?, old_display?, change?: RenderedChange}}}] }
```
Diff cells reuse `classify_change` on the **raw** pair, so the table colors
with the same semantics as the feed. The raw pair is mandatory: canonical
price columns are already normalized at save time, and feeding one back into
`classify_change` re-applies the provider factor — `2.0 → 3.5` renders as
`$2000000.00 → $3500000.00`. Resolve the raw values from each snapshot's
`metadata_json` with `normalize.profile_field_candidate`, which reproduces the
same per-model candidate path the normalizer chose; there is no static
column→path map, because `profile.normalized_fields` is an ordered candidate
list whose winner varies by model.

### `GET /api/change/{change_id}`
Raw record: `{change_id, provider_id, model_id, field, kind, old_value,
new_value (parsed JSON), detected_at, from_scrape: {…}, to_scrape: {…},
rendered: RenderedChange}`. Used by the raw drawer everywhere.

### `GET /api/models`
Params: `providers, q, limit` (default 50). Typeahead for the pin picker,
backed by `Store.list_known_models` semantics (latest display name per
model, case-insensitive substring on id or name). Returns
`[{provider_id, model_id, display_name, last_seen}]`.

## 6. Frontend

Single Preact app in `app.js` using `htm` tagged templates (no JSX, no
build). Components are small and single-purpose: `App` (router + global
state), `FilterBar`, `Activity{Heatmap,Facets,Feed,Entry}`, `Models{Pins,
AspectPicker,PanelStack,Panel,EventRail,StateStrip}`, `Catalog{Pickers,
ColumnChooser,Table,SparklinePopover}`, `RawDrawer`, `EmptyState`,
`ErrorBanner`.

### 6.1 Shared state in the URL hash

```
#view=activity&providers=openrouter,abacus&from=2026-06-01&to=2026-08-23
 &detail=default&pins=openrouter/anthropic~opus-5,openrouter/openai~gpt-5.4
 &aspects=input_price,output_price,context_window
 &asof=188&compare=160&cols=…
```
`/` in a model id is part of the id; the pin token is `provider_id/model_id`
URL-encoded. The hash is the single source of truth: every control writes
it, every view reads it, back/forward work, and a pasted URL reproduces the
screen. Defaults: `view=activity`, `providers=all enabled`, `from`=last 30
days (clamped to the data span), `detail`=configured default.

### 6.2 Activity view

Top: 180-day calendar heatmap (one cell per local date, intensity = visible
change count; added/removed shown as a small mark on the cell). Click a
cell to set `from=to=date`; drag across cells to set a range. Left:
facets — providers, categories (from the profile's category names), kinds,
detail mode. Main: the feed, newest first, one block per date with entries
as in §5 `/api/activity`; a `changed` entry is a compact table of its
visible changes (label, old → new, delta, %, unit) using the report's
color contract; bulk groups show the shared change once with an expandable
model list; the hidden rollup line sits at the bottom of each date block
(`N squelched changes hidden (field, field, …) — show` which flips `detail`).
Clicking a model name → Models view with that model added to pins (respecting
the cap; oldest pin is dropped with a toast naming it) and `from/to` centered
±30 days on the entry date. Clicking a change row opens the `RawDrawer`.

### 6.3 Models view

Left: pins (color swatch, remove ×, typeahead add via `/api/models`) and the
aspect picker grouped by category in the profile's order (Pricing first,
with the profile's pricing field order), squelched aspects under a collapsed
group. Main: one uPlot panel per selected aspect, stacked, same x-axis,
cursor synced with uPlot's `sync` key; price/count/numeric aspects are
stepped lines (`paths: uPlot.paths.stepped({align: 1})`); boolean and list
aspects render as a `StateStrip` (one row per pinned model, colored segments,
hover shows value/members) instead of a chart. Above the stack, the
`EventRail` marks every event from `/api/events` (cost colors for price
direction, blue for capability/list, amber capacity, dim informational,
green/red for added/removed presence); clicking a mark opens the
`RawDrawer`; hovering highlights the x position across all panels. Y-axis
labels carry the unit (`$ / 1M tokens`, `tokens`). Legend entries name the
model; hovering a legend entry emphasizes that series in every panel.
Zoom by drag in any panel applies to all and writes `from/to`.

### 6.4 Catalog view

Pickers for `as_of` and `compare` list real saved scrapes (date + model
count), provider-scoped. Column chooser from the aspect catalog. Table
with sticky header, sortable columns, tabular numerals, `q` filter. In
compare mode a cell that changed shows `old → new` colored by
`RenderedChange.semantic/direction`; added rows get a green presence mark,
removed rows red (the report's presence colors). Clicking a numeric cell
opens a `SparklinePopover` (a single small uPlot from `/api/series` for
that model/aspect over the full span) with an "Open timeline" link → Models
view with that model pinned and that aspect selected. A "Show as feed"
button → Activity with `from/to` set to the two scrapes' dates.

### 6.5 Visual language

Inherits the report's rules exactly: red/green mean cost direction and
nothing else, except the presence list and run status; amber capacity; blue
capability/list membership; dim informational. Dark industrial palette to
match the HTML reports, plus a light palette; both are complete token sets
defined as CSS custom properties (see §6.6). Monospace for
values, tabular numerals everywhere digits align. `prefers-reduced-motion`
disables highlight animations. Keyboard: `/` focuses the model typeahead,
`1/2/3` switch views, `Esc` closes drawers/popovers.

### 6.6 Theme: system, light, dark

Three states, supported from day one. A segmented control in the filter
bar offers **System / Light / Dark**; `System` follows
`prefers-color-scheme` live (a `matchMedia` change listener re-applies
without reload). The choice persists in `localStorage` under
`model_sentinel.browse.theme` (`"system" | "light" | "dark"`, default
`"system"` when absent or unparseable). This is page-side browser storage,
not a file the tool writes, so the read-only and no-config guarantees in §1
are unaffected; it is deliberately **not** part of the URL hash, because a
theme is a viewer preference and must not travel with a shared link.

CSS structure (load-bearing, the classic unreadable-page bug otherwise):
the bare `:root` block defines the **complete** light palette; `@media
(prefers-color-scheme: dark)` redefines only the tokens, guarded as
`:root:not([data-theme="light"])`; `:root[data-theme="dark"]` redefines
them again so an explicit choice wins in both directions. The app stamps
`data-theme="light"|"dark"` on `<html>` for an explicit choice and removes
the attribute for `System`. Components take every color from the tokens;
no color may be declared only inside a media or `[data-theme]` block. uPlot
series and axis colors are read from the tokens at render time and the
charts re-render on theme change. The cost/capacity/capability semantic
colors keep their meaning in both palettes with contrast checked on each
ground. A stamp is applied before first paint (inline script in
`index.html` reading `localStorage`) to avoid a flash of the wrong theme.

## 7. Error handling

- Missing `providers.env`/`settings.env`: same `ConfigError` path and exit
  code 2 as other commands.
- Missing DB: exit 2, message names the path and `scan --save`.
- DB present but no saved scrapes: server starts; every view shows an
  `EmptyState` explaining that nothing has been saved yet.
- Schema mismatch (a required table/column missing): exit 2 naming the
  missing object; never render partial data.
- **Database busy**: a scheduled scan holds an exclusive lock (journal mode is
  `delete`, so this is a real concurrent case, not theoretical). Connections set
  `PRAGMA busy_timeout = 5000`; a still-locked query returns **503** with
  `{"error": "The database is busy — a scan may be writing. Try again in a moment."}`.
- API errors: JSON `{error}` with status; the client shows an `ErrorBanner`
  with the message and keeps the last good state — never a blank page.
- Bad query parameters (unparseable date, `from > to`, unknown provider,
  too many pins/aspects, unknown aspect id, `compare` not earlier than
  `as_of`): 400 with a specific message.
- Port range exhausted: exit 1 with the range in the message.

## 8. Installer and standalone

`install_standalone.sh` today stages only `model_sentinel/*.py` and hashes
only `*.py`. Both must change:

- `stage_zipapp_source` copies `model_sentinel/browse/` recursively
  (Python, `assets/**`, license and version files), excluding `__pycache__`.
- `SOURCE_HASH` covers every staged file except `_packaged_build.py` (drop
  the `-name '*.py'` filter). `--check` therefore detects a changed asset.
- `tests/test_install_standalone.py` gains assertions that the staged tree
  contains `browse/assets/index.html`, `app.js`, `app.css`, the vendor
  files and licenses, and that the hash changes when an asset changes.
- `zipapp` serves package data via `importlib.resources` with no extraction.
  Verify by running the built target's `browse --no-open` and fetching `/`
  and `/api/meta` in the installer test (ephemeral port).
- `--version` output is unchanged in shape.

## 9. Testing

Synthetic fixture DB built in `tests/conftest.py` (or a new
`tests/browse_fixtures.py`) with conspicuously fake providers/models
(`example-provider`, `fake-org/test-model-a`), ~6 scrapes spanning several
dates, price steps, a context change, an added and a removed model, a
boolean flip, a list change on ≥3 models (bulk), and squelched benchmark
churn. Must not reproduce any real provider values.

- `test_browse_queries.py`: each query function against the fixture —
  series pivot (null for absent model), heatmap counts per date, catalog
  rows and diff presence, models typeahead, aspect discovery (paths found,
  labels/categories/units match the profile, squelched flag).
- `test_browse_api.py`: start `ThreadingHTTPServer` on an ephemeral port
  in a thread; use `http.client`; cover every endpoint's success shape, each
  400 condition listed in §7, 404 on unknown route/id, that `/api/activity`
  entries equal the `changes` planner's entries for the same range (same
  bulk grouping, same hidden counts), and that price values in
  `/api/series` equal `resolve_price_rule` scaling of the raw column.
- `test_browse_offline.py`: parse the served `index.html`, `app.js`,
  `app.css` and assert no `http://`, `https://`, `//` URL references
  outside comments/license headers; assert every referenced local asset
  path resolves through `importlib.resources`.
- `test_browse_readonly.py`: after a full request sweep the fixture DB's
  bytes are unchanged (compare SHA-256 before/after); the connection reports
  `PRAGMA query_only` = 1; opening a nonexistent DB path exits 2 and creates
  no file.
- `test_cli.py`: `browse --help`, port scan fallback, `--no-open`,
  `--provider` validation, dispatch occurs before `store.initialize()`
  (assert via a mock that `upsert_provider_configs` is not called).
- `test_install_standalone.py`: §8 additions.
- `test_browse_theme.py`: static check of `app.css` — every custom property
  set inside a `prefers-color-scheme` or `[data-theme]` block is also set on
  bare `:root`; the dark media block is guarded with
  `:root:not([data-theme="light"])`; `index.html` contains the pre-paint
  theme stamp script and no external URL.
- Front end: no JS test runner is added. Behavior that matters is in the
  API contract above; the offline test and a smoke test that the served
  HTML references exactly the vendored scripts are the guard.

Full suite (`pytest` in the project venv) must pass before completion.

## 10. Documentation

README gains a `browse` section (command, what it shows, offline/read-only
guarantees, keyboard shortcuts) and the `Commands`/`Help` lists; `--help`
epilog gains a `browse` example; `docs/DESIGN.md` gets a short
"History browser" subsection pointing here. `VERSIONS.md` in `vendor/`
records the upstream versions and URLs so the files can be re-fetched and
diffed.
