# History Browser Enhancements — Implementation Plan

Status: revised after adversarial review (two independent reviewers: code
grounding and UX). Nothing in this plan has been implemented. Section 9 lists
what the review changed.

## 0. Starting point: the history browser already exists

The request was "add a history browser function: run it with a parameter that
opens a different view in the browser that lets me explore the history." That
function is already shipped and working:

```bash
./model-sentinel browse            # opens http://127.0.0.1:8110/ in the default browser
./model-sentinel browse --no-open --port 8137
./model-sentinel browse --provider openrouter
```

Entry point: `run_browse_command` in `model_sentinel/cli.py:272`. Server:
`model_sentinel/browse/server.py`. JSON API: `model_sentinel/browse/api.py`
(`meta`, `activity`, `heatmap`, `series`, `events`, `catalog`, `change`,
`models`). Queries: `model_sentinel/browse/queries.py`. Front end: one Preact +
htm + uPlot single-page app in `model_sentinel/browse/assets/app.js` (1138
lines) with three views, Activity / Models / Catalog, state carried in the URL
hash. It was delivered in PRs #11, #12 and #13 and is covered by 203 tests in
`tests/test_browse_*.py`. The full suite (1322 tests) passes on `main` today.

So the real question is not "what does it take to add a history browser" but
"what does it take to make the existing one easy to use and powerful." This
plan answers that. Everything below was derived from reading the code and from
running the browser against a local database holding several months of daily
scans (hundreds of snapshots, hundreds of models, tens of thousands of stored
field changes). Measurements are stated as magnitudes only.

## 1. What is wrong today (evidence-based, ranked)

Each item names the code that causes it.

**P1. The default Activity feed is mostly empty cards.** In the default detail
mode a single recent day rendered well over a hundred entries, and the large
majority were a model header plus "1 additional details hidden by visibility
policy" with no change rows. Cause: `activity()` only drops an entry when it
has no visible changes *and* nothing hidden (`api.py:488`), so every model
whose only change is a squelched benchmark field still becomes a full card.
The scan report already solves this with `_is_squelched_only`
(`reporting.py:1380`), which the browse API does not use. The feed also sorts
entries within a day alphabetically by model id (`api.py:573`), so the three
price changes on a busy day sit wherever the alphabet puts them among forty
description changes.

**P2. Clicking a model in the feed dead-ends.** `openModel` in `App()`
(`app.js:1127`) writes `{view: "models", pins, from, to}` but never selects
aspects, so the Models view lands on "Select an aspect" unless the user had
already chosen some.

**P3. There is no single-model page.** The CLI `history` command answers "tell
me everything about model X" (first seen, last seen, every comparison edge,
with conditional-pricing interpretation). The browser does not: Models
requires pinning and hand-picking up to 12 aspects; Catalog shows one snapshot
row; Activity is date-first.

**P4. Activity is not paginated at the source.** `activity()` renders every
entry for the whole range, sorts, then slices (`api.py:575-580`). The default
30-day window is sub-second; the full span in "All" detail takes several
seconds and returns more than a megabyte, and "Load more" recomputes all of it.

**P5. Catalog friction.** The As-of and Compare pickers are native `<select>`
elements with one `<option>` per saved snapshot (well over a hundred), so
"jump to mid-July" means scrolling a list. Compare mode has no "changed rows
only" filter and no count of changed rows. Missing one-sided values render as
the literal text `null` (the browse API forwards `ABSENT_TEXT_DISPLAY` from
`change_render.py:835`; the HTML reports already close this with
`_html_side_display`, `reporting.py:6331`, but the browse JSON path does not).
Twelve default columns force horizontal scrolling with no sticky model column
(`app.css:1015` makes only the header sticky). Catalog `page` is component
state (`app.js:1034`), not URL state.

**P6. Date navigation is manual.** Two date inputs or a heatmap drag are the
only ways to set a range; there are no presets.

**P7. The event rail is unfiltered.** With three pinned models over the full
span the rail showed hundreds of marks in one strip, dominated by squelched
benchmark churn that the API already flags (`events()` sets `squelched`,
`api.py:786`) but the rail only dims (`app.js:864`).

**P8. "All" detail shows transitions that look like bugs.** Rows such as
`Design arena  10 → 10` appear when a list changed content but not length:
the list branch of `classify_change` renders lengths as the displays
(`change_render.py:1436-1439`), and `ChangeTable` renders these rows like any
other change.

**P9. No global search.** `/` only focuses the Models pin search. Nothing lets
the user type a model name from any view and go to it.

**P10. Two controls for one setting.** The bar's "Detail" segmented control
(`app.js:241`) and the Facets "Visibility" control (`app.js:300`) both write
`state.detail`.

Preserved, not problems: read-only/query-only SQLite access, fully offline
vendored assets with CSP enforcement, hash canonicalization via
`replaceState` (PKM note "Canonicalize URL state without polluting navigation
history"), the theme contract, the accessibility work on drawers, typeaheads
and tooltips, and the port-scan startup. The server is loopback-only
(`server.py:149-153, 255`), so "mobile" means a narrow desktop window; no
phone-specific work is planned.

## 2. Target experience

Design principle: **signal first, depth one click away, no dead ends, every
state a URL.** Easy means the default screen answers "what changed that I care
about" without configuration. Powerful means every element on that screen is
a door into a deeper view that already exists.

After this plan:

1. **Activity** (default, tab 1): a range-level summary strip (models added /
   removed / price / capacity / capability counts; its category chips are the
   global category filter) above a feed that contains only entries with
   visible changes, ordered by significance within each day (presence first,
   then Pricing, Context & Limits, Capabilities, Parameters, Benchmarks,
   Other). Models whose changes were all squelched are folded into one
   expandable line per day next to the existing squelched rollup line. Date
   presets sit beside the date inputs.
2. **Models** (tab 2): unchanged in shape. Pinning with no aspects selected
   gets Input / Output / Context by default. In default detail the event rail
   omits squelched events.
3. **Catalog** (tab 3): a date input that snaps to the nearest saved snapshot
   replaces the long `<select>`, with previous/next steppers and one-click
   "Compare with previous". Compare mode defaults to changed rows only with a
   count. Missing values render as `—`. Column presets and a sticky model
   column.
4. **Model dossier** (a detail route, not a tab): the full story of one
   provider/model pair, independent of the global date range. Identity and
   presence span; current facts grouped by category, each with "last changed
   <date> (old → new)" and a click-to-open sparkline; the complete changelog
   grouped by comparison edge, rendered with the same `ChangeTable` as the
   feed and interpreted with the same semantic cores as the CLI `history`
   report. Every model link in the app leads here. A "Find model" box in the
   bar (focused by `/`) reaches it from anywhere.

Keyboard: `1`–`3` views, `/` focus Find model, `Esc` close. Nothing else.

Explicit non-goals: cross-provider Catalog tables; any write endpoint; new
browser-local state beyond the theme key; new vendored libraries; SQLite
schema changes; a command palette; a copy-link button (the address bar holds
the URL); a collapsible mobile bar; keyboard window-shifting; splitting
`app.js` (about 15 tests read it by name and several pin function ordering,
see 3.4). The activity result cache is deferred (section 8).

## 3. Architecture of the change

### 3.1 Backend (Python, stdlib only)

| Area | File | Change |
|---|---|---|
| Activity folding, ordering, summaries | `browse/api.py` `activity()` | Fold squelched-only entries (default detail, no category filter), significance sort, per-day and range `summary`. Extract `_serialize_entry_group`. |
| Absent-side display | `change_render.py`, `reporting.py`, `browse/api.py` `rendered_change_to_json` | Move `_html_side_display` to `change_render.absent_side_display`; apply it in the browse JSON choke point. |
| Model dossier | `browse/api.py` new `model()`; `browse/queries.py` new `model_presence`, `snapshot_model_row` | New `/api/model`, built on the stored comparison-edge helpers in `storage.py`. |
| Catalog | `browse/api.py` `catalog()` | `changed_only`, `changed_total`, per-cell `changed` flag; extract `_aspect_cell` shared with the dossier. |
| Events | `browse/api.py` `events()` | Omit squelched events in default detail. |
| Routing | `browse/server.py` `_serve_api`, `run_browse` | Register `model`; initial-URL fragment for `--view` / `--model`. |
| CLI | `cli.py` | `--view`, `--model`, help epilog. |

### 3.2 Front end (`assets/app.js`, `assets/app.css`)

New components: `SummaryStrip`, `FoldedLine`, `RangePresets`, `ModelTypeahead`
(extracted from `Pins`), `FindModel`, `ModelView` (with `FactsList`,
`Changelog`), `SnapshotPicker`, `ColumnPresets`. New hook: `useFocusTrap`
(extracted from `RawDrawer` and `SparklinePopover`). Modified: `App` (route
dispatch, keys, canonicalization effect), `FilterBar`, `Feed`, `ChangeTable`,
`Facets` (Visibility control removed), `Models`, `EventRail`, `Catalog`,
`Pickers`, `CatalogTable`, `SparklinePopover`, `RawDrawer`.

Hash keys added to `HASH_KEYS`: `model` (string `provider/model_id`), `at`
(ISO date, optional, dossier scroll target), `changed` (`0` to turn the
compare-mode default off), `page` (catalog page number). `VIEWS` stays
`["activity", "models", "catalog"]`; `view=model` is accepted by `resolveState`
as a fourth value but is not a tab. Push-vs-replace rules apply unchanged:
user actions `write`, normalization `replaceState`.

### 3.3 Tests

Follow the three existing layers and add one new one, a browser smoke suite
(T0.0), which is the only new test dependency in this plan:

- API behaviour: `tests/test_browse_api.py` with `tests/browse_fixtures.py`
  (`build_fixture_db`, synthetic providers). Every backend rule below has an
  API test; these are the real behavioural checks.
- Server contract: `tests/test_browse_server.py` for the new route (405s,
  host check, caching headers, busy translation).
- Front-end source contract: `tests/test_browse_offline.py`. New assertions
  must check **wiring**, not existence: that a component is rendered inside
  its parent's template with the expected props (for example
  `<${FoldedLine}` appears inside the `Feed` function body and receives
  `openModel`), that a handler writes the expected keys, that a removed
  control is gone. "The file contains `function X(`" is not an acceptance
  criterion anywhere in this plan.
- Packaging: `tests/test_install_standalone.py::test_standalone_contains_every_browse_runtime_asset`
  enumerates asset files. No new asset files are planned.
- Browser smoke: `tests/test_browse_smoke.py` (T0.0) drives the fixture
  database through a headless Chromium with Python Playwright, in-process,
  as part of the ordinary `pytest` run. It is the behavioural gate for the
  front end; the source-contract layer checks wiring, the smoke layer checks
  that the wiring works. **Every task in Phases A–D adds or extends a smoke
  flow**, named in that task's acceptance under "Smoke:".
- Manual browser QA against a disposable synthetic runtime home
  (`MODEL_SENTINEL_HOME`, `config.py:371`), per the PKM technique "Validate
  public-repository browser behavior with an isolated synthetic runtime,"
  remains the final visual check (layout, colour, motion), which the smoke
  suite does not judge. Never screenshot or commit output from the real
  database.

### 3.4 `app.js` layout constraints

Several contract tests slice `app.js` between adjacent function definitions
and assert content inside the slice. These ranges are frozen; do not insert
new functions inside them:

- `useApi` → `activityEntryId` (`test_catalog_suppresses_stale_rows_and_replaces_debounced_search_hashes`)
- `Portal` → `TypeaheadOverlay` (`test_model_typeahead_portal_escapes_sidebar_and_cleans_up`; also freezes `Portal`'s two `useEffect`s and its `dataset.modelSentinelPortal = "typeahead"`)
- `TypeaheadOverlay` → `Pins` and `Pins` → `ambiguousAspectIds` (`test_model_typeahead_preserves_listbox_keyboard_contract`)
- `SparklinePopover` → `CatalogTable` (`test_catalog_sparkline_traps_focus_inerts_background_and_resizes`)

All new components and hooks are inserted immediately before
`function RawDrawer(`. Tasks that must move code out of a frozen slice
(`useFocusTrap`, `ModelTypeahead`) name the test they update.

## 4. Tasks

Order of delivery is the order below within each phase, and the phase order
is the recommended sequence: it front-loads the small fixes that remove the
worst friction (P2, P5-null, P8), then the feed, then the dossier. Each task
is independently reviewable and shippable.

### Phase 0 — Test gate and small trust fixes (ship first)

#### T0.0 Playwright smoke suite (before any behaviour change)

Purpose: a repeatable, headless, in-process check that the three existing
views render and their primary interactions work against the synthetic
fixture database, established **before** any task changes behaviour so that
every later task extends a passing baseline.

Dependencies and install:

- Add `requirements-dev.txt` in the project root, in the style of
  `editdb/requirements-dev.txt` and `storage_monitor/requirements-dev.txt`
  (the runtime is stdlib-only, so it lists only test dependencies):

  ```text
  # Test-only dependencies. Runtime is stdlib-only.
  pytest>=8.0
  playwright>=1.45
  ```

- Browser binaries are installed once per machine with
  `python -m playwright install chromium` from the project venv. They live
  under `~/Library/Caches/ms-playwright` (the path the fleet's
  `storage_monitor` already inventories), not in the repository.
- The suite does **not** skip when Playwright or Chromium is missing. A
  missing module fails collection loudly; a missing browser fails the first
  test with Playwright's own install instruction. This is deliberate: the
  project rules forbid silently skipped tests. `README.md` "Testing"
  documents the two install steps.
- Nothing is vendored and no runtime code changes. The offline/CSP contract
  tests are unaffected.

Harness (`tests/test_browse_smoke.py`):

- Move `_settings()` and `_context(db)` from `tests/test_browse_server.py:29-50`
  into `tests/browse_fixtures.py` as `browse_settings()` and
  `browse_context(db)`; both test modules import them (one implementation).
- Module-scoped fixture `smoke_server`: `build_fixture_db(tmp_path_factory…)`,
  `open_readonly`, `make_server(browse_context(db), port=0)` on a daemon
  thread, exactly as the `browse_server` fixture does. The server never
  opens a browser window (`run_browse` is not used; see the PKM note
  "Suppress browser auto-open during automated testing").
- Module-scoped fixture `browser`: `sync_playwright()` → `chromium.launch(headless=True)`.
  Function-scoped fixture `page`: a fresh context and page per test, with
  `page.on("pageerror", …)` and `page.on("console", …)` collectors; every
  test ends by asserting no page errors and no console messages of type
  `error` (the existing manual QA standard, "a clean browser console",
  becomes automated).
- Navigation helper `goto(page, server, hash)` that waits for
  `[data-view]` on the app shell (add `data-view=${resolved.view}` to
  `.app-shell` in `App`; it is the one attribute the suite keys on) and for
  `networkidle`.
- Selectors use roles and visible text (`get_by_role`, `get_by_text`), not
  CSS classes, so styling changes do not break flows; the only structural
  hooks are `data-view` and existing `aria-label`s.

Baseline flows (all must pass before T0.1 starts):

1. **Boot and tabs**: `/` loads Activity; `1`/`2`/`3` and clicking each tab
   switch views; the hash updates; browser Back returns to the previous view.
2. **Activity**: the heatmap renders 180 cells; the feed lists the fixture's
   price-step model on its date; clicking a change row opens the raw drawer
   with the change id in its heading; `Esc` closes it and focus returns.
3. **Models**: pin the price-step model through the pin search, select the
   Input aspect, a uPlot canvas appears, hovering the plot shows the
   tooltip with the model's value.
4. **Catalog**: the table lists the fixture's model count; sorting by Input
   reorders; the filter box narrows to one row; the sparkline button opens
   its popover.
5. **Theme**: Dark and Light stamp `data-theme` on the root; System removes
   it; the choice survives reload (localStorage) and no other key is set.
6. **Narrow viewport** (390 × 844): the shell has no horizontal overflow
   (`document.documentElement.scrollWidth <= innerWidth`).

Later tasks add: A1 folded line and summary chips; A2 presets; B2 dossier
open/Back/Timeline/`at=`; B3 model links from feed, catalog and pins; B4
Find model with `/`; C1 date snap and compare-with-previous; C2 changed-only
default and toggle; C3 presets and sticky column; D1 rail without squelched
marks; D2 theme inside the disclosure; T0.1 default aspects; T0.2 `—`
cells; T0.3 the `contents changed` chip; T0.4 the single Detail control.

Acceptance: `pytest tests/test_browse_smoke.py` passes with the six baseline
flows, runtime under 30 seconds on a laptop; `pytest` (whole suite) includes
it; `git ls-files` shows `requirements-dev.txt` and the new test module
tracked; `.gitignore` already excludes venvs and caches (verify no Playwright
artifacts such as `test-results/` are created; add a rule if the executor
sees any).

#### T0.1 Default timeline aspects (fixes P2 on its own)

- `defaultTimelineAspects(meta, providerId)` returns, in order, the ids among
  `${providerId}:input_price`, `${providerId}:output_price`,
  `${providerId}:context_window` that exist in `meta.aspects`; if none, the
  first two Pricing aspects for the provider; if none, the provider's first
  aspect.
- In `Models`, when `pins.length && !activeAspects.length`, canonicalize with
  `replaceState({aspects: defaultTimelineAspects(meta, <provider of last pin>)})`.
  This is normalization, not a user action.

Acceptance: contract test asserts the `Models` function body calls
`replaceState` with `defaultTimelineAspects(`. Smoke: pin a model with no
aspects selected; Input, Output and Context panels render without any
aspect click and the hash gains `aspects=`.

#### T0.2 Absent sides render as `—` everywhere in the browser

- Move `_html_side_display` (`reporting.py:6331`) to
  `change_render.absent_side_display(display, raw)` next to `ABSENT_DISPLAY`;
  `reporting.py` imports it (one implementation, three HTML call sites
  unchanged in behaviour).
- In `rendered_change_to_json` (`api.py:129`) apply it to `old_display` and
  `new_display` using `old_raw` / `new_raw`. This is the single choke point
  for `/api/activity`, `/api/catalog`, `/api/change` and the future
  `/api/model`.
- Executor: grep `tests/test_browse_api.py` for `"null"` and update every
  assertion that expected the literal, with a comment citing this task.

Acceptance: API tests: the fixture's `cache_read_price` / `cache_write_price`
catalog cells render `display == "—"` and still sort last (`value` stays
`null`); a one-sided price change in `/api/activity` renders `—` on the
absent side; no `display` string in any browse payload for the fixture equals
`"null"`. Smoke: the catalog cell for a fixture model without a cache write
price reads `—` and no cell text equals `null`.

#### T0.3 Honest rendering of equal-length list changes (P8)

- In `ChangeTable`, when `change.kind === "list"` and
  `change.old_display === change.new_display`, render the transition cell as
  the single count followed by a dim chip `contents changed` with
  `title` listing `list_added` / `list_removed` when present, otherwise
  "Nested values changed; open the raw record." The row stays actionable.
- No backend change. (`kind === "noop"` never reaches the browse API:
  `_drop_noop_changes` runs before every detail mode, `reporting.py:941`.)

Acceptance: contract test asserts the `ChangeTable` body contains the
`contents changed` chip inside the `kind === "list"` branch; fixture: the
bulk `supported_parameters` change renders its counts normally (guard against
over-application). Smoke: extend the fixture with one model whose list field
changes contents but not length on a known date
(`FixtureFacts.equal_length_list_step`); in All detail that row shows the
chip and the bulk row does not.

#### T0.4 One Detail control

- Remove the `Segmented` "Visibility" control from `Facets`; the bar's
  "Detail" control remains the only writer of `state.detail`.

Acceptance: contract test asserts `Facets` no longer references
`state.detail`; no test currently asserts the Visibility control exists
(verified by grep), so no test update is expected. Smoke: the facets column
has no "Visibility" group; the bar's All button changes the hash to
`detail=all` and the churn model's benchmark row appears in the feed.

### Phase A — Activity signal

#### A1. Fold squelched-only entries, add summaries, sort by significance

Backend, `activity()`:

- Extract the per-grouping serialization block (from `representative = entries[0]`
  through `serialized.append(item)`) into
  `_serialize_entry_group(entries, rows_by_model, profile, category_filter, kind_filter, presence_offsets, day, provider_id) -> dict | None`.
  The dossier (B1) reuses it. Acceptance grep:
  `rg -n "change_ids_by_change = \[\[\] for" model_sentinel/browse/api.py`
  returns exactly one line.
- Folding rule, applied per **entry** (not per grouping, so a bulk grouping
  folds every member, not only `entries[0]`): when `common.detail == "default"`
  **and** `category_filter` is empty **and** `entry.display is not None`
  (presence entries carry no display plan, `reporting.py:1563`, and are never
  folded) **and** `reporting._is_squelched_only(entry.display)` is true, the
  entry is not emitted. Export `_is_squelched_only` as `is_squelched_only` from
  `reporting` rather than re-deriving the predicate; it deliberately keeps
  entries whose hidden content is `hidden_unclassified` (the "add a
  show/squelch pattern" diagnostic) or `hidden_non_squelched` visible.
  With a category filter active, nothing is folded: that is how the user
  inspects squelched-category churn without switching to All
  (`test_activity_category_filter_keeps_matching_hidden_rows_and_ids` depends
  on it).
- Folded entries go to `rollups_by_date[day]["folded"] = {"models": <int>, "items": [{"provider_id", "model_id", "display_name", "hidden", "change_ids"}]}`.
  `items` is complete (not capped) and each item carries the entry's
  `change_ids` so every stored change stays reachable through the raw drawer.
  Do not add a per-field breakdown; `rollups_by_date[day]["squelched"]`
  already carries it (`_rollup_json`, `api.py:181`).
- `total` counts emitted entries. The invariant in
  `test_activity_and_heatmap_use_fixture_facts` (`tests/test_browse_api.py:196-207`,
  "every source `change_id` appears in `entries`") becomes "every source
  `change_id` appears in `entries` ∪ `folded.items`"; update that test with
  a comment citing this task.
- Significance sort within a day: key
  `(-date, presence_rank, category_rank, provider_id, model_id)` where
  `presence_rank` is 0 for `added`/`removed` entries and 1 otherwise, and
  `category_rank` is the index in `CATEGORIES` of the best category among the
  entry's visible changes (bulk entries included), 99 when none.
- Summaries: `summary = {"added": n, "removed": n, "changed": n, "by_category": {<category>: n}}`
  computed from emitted entries, where `by_category` counts visible change
  rows via `profile.categorize`, omitting zero categories. Emit one at the top
  level for the whole range and one per day in `rollups_by_date[day]`.

Front end:

- `SummaryStrip` above the feed renders the range summary. Its category chips
  toggle `state.categories` (the same write as the Facet checkbox) and read
  as filters (pressed state). Day-block headers show the per-day counts as
  plain text, not buttons.
- `Feed` keeps `rollupLine(group.date)` (squelched rollup for all models that
  day; `test_activity_frontend_preserves_list_semantics_and_date_local_rollups`
  asserts it) and adds `FoldedLine` beneath it: "N models changed only in
  squelched fields" with a `<details>` listing each folded model as a
  `model-link` (opens the dossier, B3) with a raw-record button for its
  first `change_id`, plus the existing "show all" button.

Fixture: `benchmark_churn_model` is also the `price_step` model. Add
`FixtureFacts.squelched_only_date`, a scrape date on which that model's only
change is the benchmark score (2026-08-11 in the current fixture), and assert
against it, not the price-step date.

Acceptance (API): on `squelched_only_date` with `detail=default` the churn
model is absent from `entries` and present in `folded.items` with a non-empty
`change_ids`; the same request with `detail=all` returns it as an entry; the
same request with `categories=Benchmarks` returns it as an entry (nothing
folded); on the fixture's bulk day every bulk member that is squelched-only is
listed in `folded.items`; the price-step day's `summary.by_category["Pricing"] == 1`;
entries on a day mixing an added model and a description change list the
added model first. Contract: `Feed` renders both `rollupLine(` and
`<${FoldedLine}` with `openModel`; `SummaryStrip` chips write `categories`.
Smoke: on `squelched_only_date` no card names the churn model; the folded
line reads "1 model"; expanding it lists the model and its raw button opens
the drawer; the summary strip's Pricing chip toggles `categories=Pricing` in
the hash and the feed narrows; on a mixed day the added model's card
precedes the description change.

#### A2. Date presets

- `RangePresets` in `FilterBar`: buttons `7d`, `30d`, `90d`, `180d`, `All`,
  computed from `meta.date_span.last` with `shiftDay` and `clamp`; `All`
  writes the full span. Active preset is derived by comparing the current
  `from`/`to` to what each preset would produce; none highlighted when none
  matches. Presets are user actions (`write`). No new hash keys, no new keys
  on the keyboard.

Acceptance: contract test asserts `FilterBar` renders `<${RangePresets}` and
that the preset handler calls `write({from`. Smoke: clicking `7d` sets both
date inputs and the hash; the `7d` button is pressed; Back restores the
previous range and no preset is pressed.

### Phase B — Model dossier

#### B1. `/api/model` endpoint

Params: `provider` and `model` (both required), `detail`. **No `from`/`to`**:
the dossier is the full history regardless of the global range. Parse the
pair exactly as `_pins` does (`api.py:624-648`): unknown provider → 400,
unknown model (no `snapshot_models` row) → 400 `unknown model: …`, consistent
with `_pins`. Model ids are bound SQL parameters; no identifier validation.

Response:

```json
{
  "provider_id": "…", "provider_label": "…", "model_id": "…", "display_name": "…",
  "first_seen": "<iso>", "last_seen": "<iso>", "observations": 42,
  "present_in_latest": true,
  "latest_scrape": {"scrape_id": 1, "date": "…", "completed_at": "…"},
  "facts": [
    {"aspect": "<id>", "category": "Pricing", "label": "Input", "qualifier": null,
     "kind": "price", "unit": "/1M tokens", "value": 2.0, "display": "$2.00",
     "last_changed": {"date": "…", "old_display": "$1.50", "new_display": "$2.00", "change_id": 7} | null}
  ],
  "changelog": [
    {"date": "…", "detected_at": "…", "kind": "initial|changed|added|removed",
     "from_scrape": {…} | null, "to_scrape": {…},
     "changes": [<rendered_change_to_json>…], "hidden": {…},
     "change_ids": […], "change_ids_by_change": [[…], …]}
  ]
}
```

Reuse (load-bearing; the CLI already composes this dossier at
`cli.py:614-647`, and the browser must not disagree with it):

- Presence: new `queries.model_presence(connection, *, provider_id, model_id)`
  returning `first_seen`, `last_seen`, `observations`, and the latest saved
  scrape containing the model, using the `snapshot_models ⋈ scrapes` pattern
  from `Store.history_events` (`storage.py:453`). `present_in_latest` is true
  when that scrape is the provider's latest successful saved scrape
  (`queries.list_scrapes`). Do not import `Store` into browse.
- Latest row: new `queries.snapshot_model_row(connection, *, scrape_id, provider_id, model_id, columns, paths)`
  returning one row shaped like `catalog_rows` output (`queries.py:271`).
  `catalog_rows` loads the whole snapshot and must not be used here.
- Facts: for each aspect in `ctx.aspects` with `aspect.provider_id == provider_id`,
  in `ctx.aspects` order (the same order `_catalog_aspects` preserves), build
  the cell with `_aspect_cell(row, aspect, profile)` extracted from
  `catalog()`; omit aspects whose raw value is missing. `last_changed` is
  derived from the changelog: the newest changelog change whose `field_path`
  maps to that aspect (`aspect.field_name`), or `null`.
- Changelog: build from the stored comparison edges, not from
  `recent_change_rows`. Use the module-level helpers
  `_comparison_event_envelopes(connection, provider_id=, model_id=, since=None, until=None, exclude_initial=False)`
  (`storage.py:714`), `_selected_comparison_change_rows` (`storage.py:886`)
  and `_build_comparison_events` (`storage.py:958`) — they take a connection
  and are usable from the read-only per-thread connection. For each edge,
  build `semantic_cores[event.identity] = build_model_event_semantic_core(pricing_event_from_stored(stored_event), profile)`
  exactly as `cli.py:621-631` does, then call
  `plan_changes_provider({model_id: rows}, ctx.policy_for(detail), profile, semantic_cores)`
  and serialize with `_serialize_entry_group` (A1). Edges are keyed on
  `(from_scrape_id, to_scrape_id)`; do not group by `detected_at`. The edge
  with `from_scrape_id IS NULL` becomes a `kind: "initial"` item with no
  change rows (it is the "first seen" evidence). Presence edges become
  `added` / `removed` items via `_render_presence_change`. Order newest
  first. `from_scrape` / `to_scrape` come from the envelope, not from
  per-row `change_by_id` lookups.
- Known divergence, accepted: `plan_changes_provider`'s unclassified budget
  (`unclassified_remaining`) is shared across all models in one call, so the
  dossier's per-edge single-model call can show fewer hidden unclassified
  fields than the feed shows for the same day. Document it in DESIGN.md.
- `ctx.aspects` is built once at server start (`server.py:307`); facts for a
  field first observed mid-session will not appear until restart. Pre-existing
  for Catalog and Models; inherited, documented, not fixed here.

Acceptance (API):

- Price-step model: a `facts` entry for Input whose `display` equals the
  catalog display for the same model at the latest scrape, with
  `last_changed.date` equal to the price-step date.
- `removed_model`: `present_in_latest` is false; changelog contains a
  `removed` item and an `initial` item.
- Conditional pricing: extend `browse_fixtures.py` with one model carrying a
  `pricing.overrides` payload from `tests/conditional_pricing_fixtures.py`;
  the changelog edge renders a Conditional pricing policy row (the semantic
  core path) rather than flattened selector leaves.
- Unknown provider and unknown model both return 400.
- `test_locked_database_returns_retryable_503_from_every_query_path` extended
  to cover `/api/model`; server route test extended for 405 and host checks.
- `rg -n "change_ids_by_change = \[\[\] for" model_sentinel/browse/api.py` → one line.

#### B2. Model view (detail route)

- Hash: `view=model&model=<provider>/<model_id>[&at=YYYY-MM-DD]`.
  `resolveState` accepts `view === "model"` only when `model` parses via
  `pinParts` against `meta.providers`; otherwise it resolves to the Activity
  default. `resolveState` is pure and cannot strip keys: extend the existing
  defaults effect in `App` (`app.js:1104-1108`) so that when the resolved
  view differs from `state.view` because of an invalid `model`, it
  `replaceState({view: null, model: null, at: null})`.
- Not a tab. `VIEWS` stays at three; the tab strip (`app.js:237`,
  `.view-tabs` `repeat(3, …)` at `app.css:250`) is unchanged. When
  `view === "model"`, no tab is pressed and a breadcrumb row renders under
  the tabs: "Model · <display name>" with a close control that returns to
  `view: "activity"` (a user action, `write`). The view dispatch in `App`
  (`app.js:1134`, a ternary chain ending in `Catalog`) becomes a lookup so a
  fourth branch is a one-line addition.
- No `4` key.
- Layout: `aside` identity card (display name, model id, provider label,
  first / last seen as local dates, observation count, presence badge, one
  action: **Timeline** → `write({view: "models", pins: [pin], aspects: defaultTimelineAspects(meta, provider), from: clamp(first_seen − 30d), to: clamp(last_seen)})`)
  and `main` with `FactsList` then `Changelog`.
- `FactsList`: grouped by category; each row shows label, current display,
  unit, and "last changed <date>: <old> → <new>" when `last_changed` exists
  (a button that opens the raw drawer on `change_id`). Numeric `price` /
  `count` / `numeric` facts get the same `spark-trigger` button as the
  catalog, opening the existing `SparklinePopover` (no extra series request
  on page load, no aspect cap).
- `Changelog`: one `date-block` per item using `ChangeTable` and `openRaw`;
  hidden counts use the same `entry-hidden` text as `Entry`; each item has a
  "That day in Activity" link →
  `write({view: "activity", providers: [provider], from: date, to: date})`
  (this is how a provider-wide change is told apart from a model-specific
  one). When `state.at` matches an item's date, that item is scrolled into
  view on mount and highlighted (animation suppressed under
  `prefers-reduced-motion`, as the HTML reports do).
- Empty state when the API returns 400 `unknown model`: "No saved history
  for <id>" with the Find model box focused. `ApiError` gains a `status`
  field (`app.js:71`) so the view can distinguish this from a server fault.
- Update the stale Models empty-state hint (`app.js:898`, "press `/` from
  anywhere") to describe the Find model box.

Acceptance (contract): `HASH_KEYS` contains `model` and `at`; `resolveState`
references `pinParts` for `model`; `App` dispatch renders `<${ModelView}`
for `view === "model"`; `ModelView` body renders `<${ChangeTable}` and
`<${SparklinePopover}`; `VIEWS.length === 3`. Smoke: navigate to the
price-step model's dossier hash; the breadcrumb shows its name and no tab is
pressed; the facts list shows Input with "last changed" on the price-step
date; the changelog has `initial` and `changed` items; Timeline lands on
populated panels; with `at=<price-step date>` the matching item's bounding
box is inside the viewport on load; an unknown model id shows the "No saved
history" empty state; Back returns to the feed.

#### B3. Every model link leads to the dossier

- `openModel(provider, model, date)` writes `{view: "model", model: pin, at: date || null}`.
  Callers: `Entry` model links and bulk lists (pass `entry.date`),
  `FoldedLine` items (pass the day), `CatalogTable` model names (no date),
  `Pins` names in the Models view (no date; `×` remains unpin).
- `EventRail` marks and `SparklinePopover` keep their current targets.

Acceptance (contract): `openModel` writes `view: "model"`; `Entry` passes
`entry.date`; `CatalogTable` model cell is a `model-link` button calling
`openModel`. Smoke: clicking the model name in a feed card opens its dossier
with `at=` equal to the card's date; clicking a catalog model name and a pin
name each open the dossier; none lands on an empty state.

#### B4. Find model box

- Extract `ModelTypeahead({providers, onPick, inputRef, placeholder, listboxId})`
  from `Pins` (the debounced `/api/models` query, `TypeaheadOverlay`,
  listbox keyboard contract). `Pins` uses it with `onPick = add`;
  `FilterBar` renders `FindModel`, which uses it with all known provider ids
  (`meta.providers`, not the selected ones) and `onPick = item => openModel(item.provider_id, item.model_id)`.
  `/` (unmodified, not editing) focuses the Find model input; `inputRef`
  moves from the Models pin search to it.
- `test_model_typeahead_preserves_listbox_keyboard_contract` slices
  `Pins → ambiguousAspectIds`; update it to slice `ModelTypeahead` instead
  and add an assertion that both `Pins` and `FindModel` render
  `<${ModelTypeahead}`. Cite this task in the comment.

Acceptance (contract): exactly one `function ModelTypeahead(`; two
`<${ModelTypeahead}` render sites; the `/` handler focuses `inputRef` and
no longer writes `view: "models"`. Smoke: from Catalog, press `/`, the Find
model input is focused; type part of a fixture model name, ArrowDown, Enter
opens its dossier; Esc with the list open closes the list and keeps focus in
the input; the Models pin search still adds a pin.

#### B5. `useFocusTrap` (dedup, independent of B4)

- Extract the Tab-cycling / Escape / focus-restore effect duplicated in
  `RawDrawer` (`app.js:1063-1079`) and `SparklinePopover` (`app.js:943-974`)
  into `useFocusTrap(panelRef, active, onClose)`; both use it.
- `test_catalog_sparkline_traps_focus_inerts_background_and_resizes` asserts
  the trap strings inside the `SparklinePopover` slice; rewrite it to assert
  `useFocusTrap(` is called inside that slice and that the strings exist
  exactly once in the file (inside the hook). Cite this task.

Acceptance: one definition, two call sites; the modal `inert` /
`aria-modal` behaviour of both components is unchanged (existing tests).
Smoke: baseline flows 2 and 4 already exercise Esc-to-close and focus
restoration for the drawer and the popover; add a Tab-cycling assertion to
each (Tab from the last focusable element lands on the first).

#### B6. CLI entry points

- `browse --view {activity,models,catalog}` (default `activity`) and
  `browse --model PROVIDER/MODEL_ID` (implies the dossier route). `--model`
  uses an argparse `type=` callable that requires exactly one `/` with
  non-empty sides and raises `ArgumentTypeError` otherwise (exit 2, usage
  message). The provider part is validated in `run_browse_command` after
  `open_readonly`, against configured providers ∪ `queries.db_providers`
  (the same union `parse_common` accepts); unknown → message on stderr and
  exit 2, like the missing-database path. The model id is not validated
  (the dossier's empty state handles it).
- `run_browse` gains `initial_view: str | None` and `initial_model: str | None`.
  Fragment construction, in this order and only for non-default values:
  `view=<view>` (omitted when `activity` and no model), `model=<quoted pin>`
  (implies `view=model`), `providers=<quoted provider>` (from `--provider`,
  unchanged). All values through `urllib.parse.quote(value, safe="")`.
  `--provider` and `--model` may both be given; `--model` controls the route
  and `--provider` still seeds `providers`.
- The printed "Model Sentinel browser:" line includes the fragment whenever
  one exists, so `--no-open` users can click it. This changes the assertion
  `line.endswith("/")` in `test_browse_server_lifecycle_and_browser_open`
  (`tests/test_cli.py:464`); update it to assert the fragment for the new
  parametrized cases and `/` for the existing ones, with a comment citing
  this task. The existing `--provider` case must still pass unchanged
  (`"#providers=openrouter" in opened[0]`), which is why `view=activity` is
  never emitted.
- Help: give `browse_parser` `formatter_class=argparse.RawDescriptionHelpFormatter`
  and an `epilog` with examples in the style of `providers` / `healthcheck`;
  add the two new examples to the top-level help next to the existing
  `browse --no-open` line (`cli.py:153`). `test_browse_help_lists_browser_options`
  gains the new flags.

Acceptance: parametrized `test_browse_server_lifecycle_and_browser_open`
cases for `--view catalog` (`#view=catalog`), `--model` (`#view=model&model=…`
with the pin percent-encoded), and `--provider` + `--model`; a parser test
for `--model nope` exiting 2; `browse --help` shows the examples.

### Phase C — Catalog

#### C1. Snapshot picker: date input that snaps to saved snapshots

- Replace each `<select>` in `Pickers` with `SnapshotPicker`: an
  `<input type="date">` with `min` / `max` from that provider's saved scrapes
  (`catalogScrapes`), a caption "snapped to <date> · <n> models", and `‹` `›`
  steppers moving to the adjacent saved scrape (disabled at the ends). On
  date change, choose the latest saved scrape on or before the chosen day
  (for Compare, additionally earlier than As-of); write `asof` / `compare`
  as today. Add a "Compare with previous" button that sets `compare` to the
  scrape immediately before As-of; hidden when none exists or already set.
- `catalogScrapes` already provides the sorted list; no API change.
- Update `test_catalog_frontend_uses_provider_scoped_saved_scrapes_and_canonical_defaults`
  if it asserts the `<select>` markup (executor: check).

Acceptance (contract): `Pickers` renders two `<${SnapshotPicker}` and the
"Compare with previous" button; no `<select` remains in `Pickers`. Smoke:
filling the As-of date input with a day that has no scrape snaps to the
previous saved date and the caption names it; `‹` moves to the earlier
scrape and `›` back; "Compare with previous" sets `compare=` in the hash to
the scrape before As-of and the button disappears.

#### C2. Changed-only compare mode

- Backend: `changed_only` (`"1"`) accepted only when `compare` is set (400
  otherwise). Each cell gains `"changed": <bool>` computed with `_same_value`
  when `compare` is set; a row is changed when `presence != "present"` or any
  cell is changed. Response gains `changed_total` (count before paging, always
  present under compare). `total` reflects the `changed_only` filter (it
  drives paging).
- Front end: delete `cellChanged` (`app.js:936`) and use `cell.changed`.
  When `compare` is set, changed-only is **on by default**; hash `changed=0`
  turns it off (toggle labelled "Changed only · <changed_total>"). Clearing
  `compare` clears `changed`. `page` moves into the hash (`replaceState` on
  page change; reset on any other catalog write).

Acceptance (API): with `compare=<price_step from>` and `as_of=<price_step to>`,
`changed_only=1` returns exactly the price-step model; the added-model edge
returns exactly the added model with `presence == "added"`; `changed_total`
equals those counts; `changed_only` without `compare` → 400; `total` under
`changed_only` equals `changed_total`. Contract: `cellChanged` no longer
exists; `HASH_KEYS` contains `changed` and `page`. Smoke: after "Compare with
previous" on the price-step edge the table has exactly one row, the toggle
reads "Changed only · 1", turning it off shows every model with the changed
cell tinted, and the hash carries `changed=0`; paging to page 2 (with a
fixture large enough, or `CATALOG_PAGE_SIZE` overridden through a test
hook) writes `page=2` and survives reload.

#### C3. Column presets and sticky model column

- `ColumnPresets` chips above `ColumnChooser`: `Pricing`, `Limits`,
  `Capabilities`, `Default`, `All` (cap 24 with a toast).
- CSS: `.catalog-table tbody th[scope="row"]` currently `position: relative`
  (`app.css:1019`) becomes `position: sticky; left: 0` with the panel
  background token; the header's first `th` gets `left: 0` in addition to
  `top: 0` and a `z-index` above the existing `4`. Colours must come from
  existing tokens; `tests/test_browse_theme.py` does not enforce this, so the
  reviewer checks the diff for hex literals.

Acceptance (contract): `Catalog` renders `<${ColumnPresets}`; the sticky
rules exist for both selectors. Smoke: clicking the Pricing preset sets
`cols=` to exactly the provider's Pricing aspects; with `All` selected,
scrolling the table container horizontally by 400 px leaves the first
model header cell's bounding-box `x` unchanged while a value cell's `x`
moves.

### Phase D — Models view

#### D1. Rail omits squelched events in default detail

- `events()`: when `common.detail == "default"`, drop rows whose
  `visibility_of(field_name, policy) == "squelched"`; `all` and `squelched`
  modes unchanged (`squelched` mode shows only them, mirroring the feed).
  Presence rows (`field_name is None`) are always kept. No new params.

Acceptance (API): the churn model's benchmark events are absent in
`detail=default`, present in `all`, and the only ones in `squelched`;
presence events appear in all three. Smoke: pin the churn model over the
full span; the rail's mark count in Default equals its API event count
(presence plus visible), and switching to All adds the benchmark marks.

#### D2. Theme control demotion

- Move the Theme segmented control out of the primary `FilterBar` row into a
  small trailing "Appearance" `<details>` at the end of the bar. No state
  change; `test_theme_is_validated_and_stamped_before_actual_stylesheet_tags`
  and the theme contract tests are unaffected (they read `index.html` and
  CSS).

Acceptance: contract test that `FilterBar` still renders the three theme
buttons and that they are inside the disclosure. Smoke: baseline flow 5
opens the disclosure first; the three buttons behave as before and the
disclosure state is not written to the hash or to localStorage.

## 5. Documentation and packaging updates (part of the work)

- `README.md` "Browse History": the dossier route, Find model box, presets,
  folding rule ("Default detail folds models whose only changes are squelched
  into one line per day; a category filter or All shows them"), changed-only
  default, `--view` / `--model`, the shortcut list (`1`–`3`, `/`, `Esc`).
- `docs/DESIGN.md` "History browser": the dossier route and `/api/model`,
  its reuse of the stored comparison-edge helpers and semantic cores, the
  accepted hidden-budget divergence, the frozen-at-start aspect catalog.
- `browse --help` epilog (B6).
- `README.md` "Testing": install test dependencies from
  `requirements-dev.txt` into the project venv, run
  `python -m playwright install chromium` once per machine, then `pytest`.
  State that the smoke suite is part of the ordinary run and is not skipped
  when the browser is missing.
- Standalone: `install_standalone.sh` copies the whole `browse` directory; no
  change unless an asset file is added. After merge run
  `./install_standalone.sh --check` and reinstall.

## 6. Verification

From `model_sentinel/` with the project virtual environment active:

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
pytest
```
Expected: every test passes, zero skips, count greater than 1322, and the
run includes `tests/test_browse_smoke.py` (check the `-v` output or
`pytest --collect-only -q | grep smoke`).

```bash
./model-sentinel browse --help
./model-sentinel browse --view catalog --no-open
./model-sentinel browse --model example-provider/fake-org/test-model-a --no-open
```
Expected: the printed URL carries `#view=catalog` and
`#view=model&model=example-provider%2Ffake-org%2Ftest-model-a` respectively.

Manual visual QA with a synthetic runtime home (never the real one), for
what the smoke suite does not judge (layout, colour, motion):

```bash
export MODEL_SENTINEL_HOME="$(mktemp -d)"
# seed providers.env / settings.env from the templates, build a fixture DB
# with tests/browse_fixtures.py, then:
./model-sentinel browse --no-open --port 8137
```
Walk: Activity default (no empty cards, summary strip, folded line expands,
significance order), click a model → dossier → Timeline, "That day in
Activity", Back after each step; Find model from every view; Catalog date
snap, compare with previous, changed-only; light and dark themes; a narrow
window. Remove the temporary directory afterwards.

## 7. Review checklist for the executor's final diff

- No second copy of: the entry-group serializer, the absent-side display
  rule, the cell-changed rule, the focus trap, the model typeahead, the
  squelched-only predicate.
- No literal `"null"` produced by the browse API for absent sides.
- No new `localStorage` key; no external URL; CSP unchanged.
- No real provider data, real model values or real-database output in tests,
  fixtures, docs or commit messages.
- Every test named in section 4 was updated with a comment citing its task;
  none deleted.

## 8. Deferred: the Activity result cache

### What it is

`/api/activity` answers "what changed between these dates, for these
providers, with these facets" as a paged list. The page is the last thing
computed: `activity()` loads every stored change row in the range
(`recent_change_rows`, one SQL query per provider), groups them by day and
model, runs each day's rows through the report planner
(`plan_changes_provider`, the same code that builds the scan report, which
applies the detail policy, squelch patterns, bulk consolidation and price
classification), serializes every resulting entry, sorts the whole list, and
only then slices out the requested page (`api.py:575-580`). The front end
asks for pages of 500 (`app.js:369`) and, on "Load more", asks for page 2
with identical filters, which repeats all of that work from the first row.

The cache would keep the fully rendered, unpaged result for the most recent
few filter combinations in memory, keyed by the filters, so that a page 2
request, a Back navigation, or a repeat of the same view is a list slice
instead of a full re-render.

### Why it was proposed

Measured on the local six-month database: the default 30-day window renders
in under half a second, the full span in Default detail in about one second,
and the full span in All detail in several seconds while returning more than
a megabyte of JSON. Every one of those numbers grows linearly with the number
of stored change rows in the range, and the database grows every day. The
heatmap, by contrast, is a single grouped SQL query (`change_counts_by_date`)
and stays at tens of milliseconds regardless of range.

The cost shows up as: a visible delay on "Load more" (the front end shows
"Loading more changes…"), a delay every time the user returns to Activity
from another view with the same filters (each view mount refetches), and a
long stall for the audit case "show me everything in All detail across the
whole history."

### Why it is deferred

Two things in this plan change the arithmetic before any cache is worth its
complexity:

1. **A1 folding removes most Default-mode entries.** In the sampled data
   more than half of all stored changes are squelched benchmark churn, and
   the entries that survive folding are far fewer than one page. "Load more"
   will rarely fire in Default detail, so the page-2 recompute mostly stops
   happening on its own.
2. **A1 also changes the response shape** (folded items, summaries,
   ordering). Building a cache first would mean caching a payload that is
   about to change; building it after means caching the final shape once.

What remains after A1 is the audit case, All detail over a long range, which
is a deliberate "show me everything" action and is not the default screen.
Whether that case still needs a cache is an empirical question, so the gate
is a measurement, not a guess.

### Trigger for un-deferring

After A1 ships, time these four requests against a database of the owner's
current size (use the synthetic fixture scaled up if the real database must
not be used in a test; `build_fixture_db` can be parameterised for scrape
count):

- Default detail, 30-day window, page 1
- Default detail, full span, page 1
- All detail, full span, page 1
- All detail, full span, page 2 (the "Load more" cost)

Un-defer if any Default request exceeds one second or any All request
exceeds three seconds. Otherwise leave it out; the code is simpler without
it.

### Design if it is built (corrected by review; do not implement the first draft)

- **Placement.** An `_ActivityCache` object on `ApiContext` (dataclass field
  with a default factory), one per server, so tests construct it naturally.
- **Key.** The parsed filters: `(providers, since, until, detail, models, categories, kinds)`
  as sorted tuples. `page` and `page_size` are not part of the key.
- **Value.** `(version, serialized_entries, rollups, rollups_by_date, summary)`.
- **Version stamp: the correctness core.** The server opens SQLite read-only
  while a scheduled scan may write concurrently, so a cached result must be
  invalidated when the database changes. Use one query, placed in
  `queries.py` so `_translate_busy` applies:
  `SELECT (SELECT MAX(scrape_id) FROM scrapes), (SELECT COUNT(*) FROM scrapes), (SELECT MAX(change_id) FROM field_changes), (SELECT COUNT(*) FROM field_changes)`.
  `MAX` on an autoincrement primary key is a rowid lookup; `COUNT(*)` on
  SQLite is a b-tree walk that stays fast at these sizes and catches deletes
  that `MAX` would miss. This stamp is sufficient only because the history
  tables are append-only today (there is no `DELETE` anywhere in
  `model_sentinel/`), and it is blind to `providers.label` changes, which
  `recent_change_rows` selects (`storage.py:1290`); a label edit followed by
  no new scan would serve the old label until the next scan. Both facts must
  be stated in a test so a future prune or label editor trips it.
- **Why not the obvious alternatives.** `PRAGMA data_version` changes only
  relative to the same connection's previous value, and this server uses one
  connection per request thread (`readonly.py:144`), so two threads cannot
  compare stamps. File mtime is unreliable under WAL: commits go to the WAL
  file and the main database file is untouched until checkpoint.
- **Locking.** A `threading.Lock` guards the dictionary only, never the
  render. Two threads can render the same key concurrently and the second
  store wins; that wastes one render but never blocks a request behind
  another's multi-second render or behind SQLite's five-second busy timeout.
  The "renders once for two pages" test is therefore valid only for
  sequential calls, and must say so.
- **Immutability.** Slicing returns the same entry dicts to the caller.
  Cached entries are treated as immutable; add the equivalent of the
  existing `test_change_does_not_mutate_query_result` for the cached path.
- **Bound.** Two entries. A full-span All result is millions of Python
  objects; two is the smallest number that covers "page 1 then page 2" plus
  "switch view and come back."
- **Tests.** Page 1 then page 2 with identical filters renders once; a new
  `field_changes` row inserted through a separate writable connection causes
  a re-render on the next request; the dictionary never exceeds two keys;
  the 503 busy-translation test covers the version query.

## 8a. Decision taken: Playwright smoke suite

Adopted as T0.0 on the owner's decision. It is a test-only dependency
(`requirements-dev.txt`), not a runtime or vendored one, so the offline and
CSP contracts are untouched. It replaces the manual walk as the behavioural
gate for the front end; the manual walk remains for visual judgement.

## 9. What the adversarial review changed

Cut as scope creep or wrong-shaped: command palette and `Cmd+K`, `[` / `]`
window shifting, copy-link button, collapsible mobile bar, event-rail
category chips and `rail` hash key, a fourth numbered "Model" tab and the `4`
key, sparkline-per-fact series request, Catalog and Activity exits on the
dossier, the folded per-field breakdown, the activity cache (deferred).

Corrected against the code: folding now uses the existing
`_is_squelched_only` predicate, is gated off under a category filter, folds
per entry (bulk members included) and keeps `change_ids`; the dossier is
built on the stored comparison-edge helpers with semantic cores so it matches
the CLI `history` report, is unbounded by the global range, keys edges on
scrape ids, includes the initial observation, and uses a per-model snapshot
query instead of loading the whole snapshot; the `null` fix moves to the
JSON choke point using the existing HTML rule; the P8 chip keys on
equal-length list changes, not the unreachable `noop` kind; unknown model is
400 like `_pins`; `Cmd+K` was unreachable behind the modifier guard; the CLI
fragment is emitted only for non-defaults and the printed URL contract test
is named; every contract test the plan changes is now named, and acceptance
criteria assert wiring rather than existence.

Added on review: significance ordering and the range summary strip, the
Find model box with `/`, the `at=` scroll target, the "That day in Activity"
exit, changed-only on by default, catalog `page` in the hash, the removal of
the duplicate Visibility control, and the recommended ordering (small trust
fixes first).

Added on the owner's decision after review: the Playwright smoke suite
(T0.0) as the first task, with a "Smoke:" line in every later task's
acceptance, and the expanded cache rationale with a measured un-defer
trigger (section 8).
