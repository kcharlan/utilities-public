# Model Sentinel Browser — UI/UX Design Proposals

Status: **proposal for review** (2026-08-23). Nothing here is implemented. Once an
approach is chosen this document becomes the input to a spec under
`docs/superpowers/specs/` and then an implementation plan.

## 1. What the browser is for

Model Sentinel already answers "what changed since the last scan?" very well
(scan reports, notifications, `changes`). What it cannot do today is let a
person *look back*: open the database, wander through five months of daily
snapshots, and form a picture. The browser is a read-only local SPA for that.

### Jobs the user shows up with

Ordered by how often I expect each to happen.

| # | Job | Example question | Primary object |
|---|-----|------------------|----------------|
| J1 | **Catch up** | "What happened across the fleet in the last 2 weeks?" | date range |
| J2 | **One model's story** | "How has `anthropic/claude-opus-5` pricing and context moved since March?" | model |
| J3 | **Compare a few models on one aspect** | "Input price of these 4 frontier models over time on one chart" | aspect × models |
| J4 | **Lifecycle** | "Which models appeared / disappeared this month? What is deprecated?" | added/removed events |
| J5 | **Explain an alert** | "That notification said the price rose — show me the raw old/new and the scrape it came from" | single change |
| J6 | **Catalog as of a date / diff two dates** | "What did the OpenRouter list look like on July 1st vs today?" | snapshot |
| J7 | **Market view of an aspect** | "Is median input price drifting down? How many models support vision now?" | aspect across all models |
| J8 | **Scrape health** | "Did scans run every day? Where are the error runs? Model count per run." | scrape |

J1, J2, J3 and J5 are the core. J6–J8 are real but secondary and can be
layered on later without changing the shell.

### Data realities that shape the UI

From the live database (read-only inspection, 2026-08-23):

- 189 scrapes since 2026-03-13; OpenRouter ~daily (161 saved, 6 error runs), Abacus 8 saved.
- 643 distinct provider/model pairs; 57,558 snapshot rows; `metadata_json` ≈ 1.4 KB each.
- 15,262 `field_changes` rows: 677 added, 189 removed, 14,396 field changes.
- **Noise dominates**: `benchmarks.design_arena` alone is 7,636 changes (50%).
  `supported_parameters`, `links`, `description`, `knowledge_cutoff` are the
  next tier. A browser that shows every change row is unusable; it must apply
  the same squelch patterns and categories the reports use.
- Every aspect has **two sources**: a *dense* series (one value per saved
  scrape, from `snapshot_models` canonical columns or `json_extract` on
  `metadata_json`) and a *sparse* event list (`field_changes`). Dense series
  make good charts; events make good feeds. The UI should use both and let
  the user hop between them.
- Prices are stored raw; display requires the provider profile's scale/unit
  rules (`/1M tokens`, `/1K searches`, `/request`). The browser must call the
  existing `model_sentinel` normalization and labeling code, not re-derive it.

## 2. Three approaches

Each is a complete, shippable product on its own. They differ in which
object the user grabs first.

### Approach A — Timeline Explorer (model-first)

The user picks one or more models; the canvas becomes a stack of small,
aligned time-series panels, one per aspect (input price, output price, cache
read, context window, max output, capability flags, benchmark index…). All
panels share one x-axis; hovering a date shows a vertical crosshair across
every panel. Change events (including added/removed) are tick marks on a rail
above the charts; clicking one opens the raw old → new record.

```
┌───────────────────────────────────────────────────────────────────────────┐
│ ⌕ models…      [openrouter ▾] [Mar 13 — Aug 23 ▾] [noise: default ▾]     │
├──────────────┬────────────────────────────────────────────────────────────┤
│ PINNED       │ events  ·   ·  ·   ·    ·  ▲added          ·  ·            │
│ ● opus-5     │────────────────────────────────────────────────────────────│
│ ● gpt-5.4    │ Input price   $/1M       ┌─────┐                            │
│ ○ gemini-3   │     ───────┘             │ 15.0│ ──────┐                    │
│              │ ·········┘                          ···└──────             │
│ ASPECTS      │────────────────────────────────────────────────────────────│
│ ☑ input      │ Output price  $/1M                                          │
│ ☑ output     │     ─────────────────────────┐                              │
│ ☑ context    │                              └────────────────              │
│ ☐ cache rd   │────────────────────────────────────────────────────────────│
│ ☐ reasoning  │ Context window  tokens         ┌────────────────────────    │
│ ☐ AA index   │   ─────────────────────────────┘                            │
├──────────────┴────────────────────────────────────────────────────────────┤
│ 2026-06-14  pricing.prompt   0.000015 → 0.00002   ($15.00 → $20.00, ↑33%) │
└───────────────────────────────────────────────────────────────────────────┘
```

- **Best for:** J2, J3, J7 (turn "all models" into a band chart).
- **Strengths:** the most *visual* answer; price "staircases" are immediately
  legible; multi-model overlay is natural. Dense series mean the chart is
  correct even when no `field_changes` row exists.
- **Weaknesses:** you have to know what to pin. Cold-start ("what happened?")
  is weak. Booleans and lists (capabilities, supported parameters) are awkward
  as line charts — they need a state-strip rendering.
- **Risk:** chart library and series extraction are the bulk of the work.

### Approach B — Catalog Ledger (snapshot-first)

The primary object is a *date*. A dense table lists every model as of that
date with a column chooser (price fields, limits, capability flags). A time
scrubber along the top moves the date; picking a second date turns the table
into a diff, with changed cells highlighted in the report's cost colors and
added/removed rows flagged. Clicking a cell opens a sparkline popover of that
field's history for that model; clicking the model name opens its full
timeline (Approach A's panel, as a drawer).

```
┌───────────────────────────────────────────────────────────────────────────┐
│ as of [2026-08-23 ▾]   compare to [2026-07-01 ▾]   ⌕ filter  ⚙ columns     │
│ ◄──────────────────●──────────────────────────────────────●──────────────► │
├──────────────────────┬─────────┬──────────┬─────────┬──────────┬──────────┤
│ model                │ input   │ output   │ context │ reason   │ vision   │
├──────────────────────┼─────────┼──────────┼─────────┼──────────┼──────────┤
│ anthropic/opus-5     │ $15→20 ▲│ $75      │ 200k    │ ✓        │ ✓        │
│ openai/gpt-5.4       │ $2.50   │ $10      │ 400k→1M │ ✓        │ ✓        │
│ + google/gemini-3.5  │ $1.25   │ $10      │ 1M      │ ✓        │ ✓   added│
│ − meta/llama-4-8b    │         │          │         │          │  removed │
│ … 640 more                                                                 │
└───────────────────────────────────────────────────────────────────────────┘
```

- **Best for:** J6, J4, J7 (sort any column; "how many ✓ in vision").
- **Strengths:** handles 643 models without choosing first; sort/filter
  gives market-wide answers for free; diff mode is exactly the mental model
  of `scan --baseline-date`. Cheap to build — it is mostly SQL over
  `snapshot_models`.
- **Weaknesses:** time is compressed to two points; trends are invisible
  until you open a popover. "What happened last week" still needs the feed.

### Approach C — Change Feed Investigator (event-first)

The primary object is the stream of `field_changes`. A faceted sidebar
(provider, model, category, field, kind, squelch level) filters the feed; a
calendar heatmap of change volume sits above it and doubles as the date
filter. Each row renders through the existing `classify_change` /
`RenderedChange` logic so it looks like the report. Clicking a row expands
the raw JSON old/new and links to the scrape; clicking the model opens a
timeline drawer.

```
┌───────────────────────────────────────────────────────────────────────────┐
│ Mar  ░▒▓▒░░▒  Apr ░░▒▒▓░░  May ▒░░░▒▒▓  Jun ░▒▓▓▒░  Jul ░░▒░  Aug ▒▒▓░    │
├──────────────┬────────────────────────────────────────────────────────────┤
│ PROVIDER     │ 2026-08-21  openrouter  anthropic/opus-5                    │
│ ☑ openrouter │   Pricing · Input   $15.00 → $20.00  ↑ 33.3%        [raw ▾] │
│ ☑ abacus     │ 2026-08-21  openrouter  +3 models added                     │
│ CATEGORY     │   google/gemini-3.5, …                                      │
│ ☑ pricing    │ 2026-08-19  openrouter  openai/gpt-5.4                      │
│ ☑ limits     │   Limits · Context   400,000 → 1,000,000                    │
│ ☐ parameters │ 2026-08-19  openrouter  14 models                           │
│ ☐ benchmarks │   Parameters · supported_parameters  +reasoning_effort      │
│ KIND         │ ░ 312 squelched changes hidden (benchmarks.design_arena …)  │
│ ☑ changed    │                                                             │
│ ☑ added      │                                                             │
└──────────────┴────────────────────────────────────────────────────────────┘
```

- **Best for:** J1, J5, J4, J8.
- **Strengths:** cold-start is perfect — open it and you see what happened;
  reuses the report rendering logic verbatim, so it is consistent with
  notifications; bulk consolidation (same list change on ≥3 models) already
  exists. Cheapest path to something useful.
- **Weaknesses:** events only — a field that never changed never appears;
  no trend picture without the timeline drawer.

## 3. Recommendation: one shell, three views, shared state

None of the three is sufficient alone, and they are not in tension: they are
the same data viewed by date, by model, or by event. Build **one SPA with
three top-level views** — **Activity** (C), **Models** (A), **Catalog** (B) —
that share a single global state (providers, date range, noise level,
pinned models) encoded in the URL hash so any view is bookmarkable and every
view can deep-link into any other:

- Activity row → model name → Models view with that model pinned and the
  date centered.
- Models chart → click a step → Activity filtered to that model/field/date.
- Catalog cell → sparkline popover → "open timeline" → Models view.
- Catalog diff → "show as feed" → Activity bounded to those two scrapes.

### Suggested build order (YAGNI applied)

1. **Shell + Activity view** (C). Heatmap, faceted feed, raw drawer. This
   alone replaces `changes` for interactive use and proves the backend.
2. **Models view** (A) for scalar aspects (prices, context, max output,
   numeric benchmark indexes) with an event rail. Boolean/list aspects as a
   state strip, not a line.
3. **Catalog view** (B): as-of table with column chooser, then two-date diff.
4. Later, if wanted: J7 market aggregates (median line, count-of-✓ over time),
   J8 scrape-health strip, CSV export.

### Architecture sketch

- **Location:** new sibling project `utilities-public/model_sentinel_browser/`
  (model_sentinel itself stays stdlib-only; the browser is a separate uv
  launcher with FastAPI/uvicorn, following the `editdb` embedded-SPA pattern).
- **Read-only:** open SQLite with `file:…?mode=ro` URI; no writes, ever.
  Respect `MODEL_SENTINEL_HOME` and `settings.env` for the DB path and squelch
  patterns.
- **Reuse, don't duplicate:** import `model_sentinel.provider_profiles`
  (categorize, price rules, labels), `model_sentinel.change_render`
  (`classify_change`, money/percent formatting), and `model_sentinel.config`
  (squelch patterns). The launcher adds the sibling package to `sys.path`
  when run from the checkout; the standalone question is open (see below).
- **API (JSON):** `/api/meta` (providers, date span, aspects catalog),
  `/api/activity?…` (paged, faceted, squelch-aware changes + bulk groups),
  `/api/series?model=…&aspect=…` (dense series from snapshots),
  `/api/catalog?as_of=…&compare=…` (snapshot table / diff), `/api/change/{id}`
  (raw record + scrape context).
- **Frontend:** single HTML string, React 18 + Babel + Tailwind from CDN as
  in `editdb`. Charts: **uPlot** (tiny, fast, native stepped lines and
  synchronized cursors — the right tool for price staircases) rather than
  Chart.js; or hand-rolled SVG if CDN-free is preferred.
- **Visual language:** inherit the report's rules — red/green mean cost
  direction and nothing else; amber for capacity, blue for capability/list
  membership, dim for informational. Dark industrial theme to match reports,
  with a light theme.
- **Port:** `find_free_port(8110)` per repo convention.

## 4. Open questions for review

1. **Does the three-view hybrid fit, or would you rather start with one
   approach alone?** My recommendation is the hybrid built in the order above.
2. **Chart library:** uPlot from CDN (recommended), Chart.js (more familiar,
   heavier, worse stepped lines), or zero-dependency SVG (most work, no CDN).
3. **CDN dependence:** `editdb` loads React/Tailwind from unpkg, so the UI
   needs network at page load. Acceptable, or should the browser be fully
   offline like the reports?
4. **Standalone install:** should the browser also get a zipapp under
   `~/Library/Scripts/` like `model-sentinel`? That affects how it imports
   the `model_sentinel` package (vendor it into the zipapp vs. require the
   checkout).
5. **Benchmarks:** treat as a first-class aspect family in the Models view
   (AA intelligence/agentic/coding indexes are genuinely interesting over
   time) while keeping them squelched in Activity by default?
6. **Multi-model cap:** overlaying more than ~8 models on a chart becomes
   spaghetti. Cap pins at 8, or allow unlimited with a "band" rendering?
