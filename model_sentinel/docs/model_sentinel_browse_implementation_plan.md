# `model-sentinel browse` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [`docs/superpowers/specs/2026-08-23-model-sentinel-browse-design.md`](superpowers/specs/2026-08-23-model-sentinel-browse-design.md) — read it first; this plan does not restate every requirement, it tells you where each one lands and resolves the decisions that are easy to get wrong.

**Goal:** A read-only, fully offline history browser (`model-sentinel browse`) with Activity, Models and Catalog views over the existing SQLite database, packaged inside the existing zipapp.

**Architecture:** New `model_sentinel/browse/` subpackage: stdlib `http.server` serving package-data assets and a JSON API; SQL in `queries.py`; aspect catalog in `aspects.py`; all labeling, categorization, price units and change rendering delegated to the existing `provider_profiles`, `change_render` and `reporting` modules. Frontend is a single Preact + htm app with uPlot charts, no build step.

**Tech Stack:** Python ≥ 3.11 stdlib only (`http.server`, `sqlite3`, `json`, `importlib.resources`, `socket`, `webbrowser`, `threading`); vendored Preact 10, preact/hooks, htm 3, uPlot 1 (MIT).

## Global Constraints

- Runtime stays **stdlib-only**; no new PEP 723 dependencies, no pip.
- Python tests run inside the project venv: `source .venv/bin/activate && pytest` (never bare system python).
- The served page must reference **no external URL**; every asset is package data.
- The browser **never writes**: DB opened `?mode=ro` + `PRAGMA query_only = ON`; no files created under `~/.model_sentinel`.
- `browse` is dispatched in `cli.main()` **before** `store.initialize()` / `store.upsert_provider_configs(...)`.
- Pin cap **8** models; aspect cap **12** per series request.
- Color contract from README "Color Semantics": red/green = cost direction only (plus presence lists and run status); amber capacity; blue capability/list membership; dim informational.
- Theme: three states (system/light/dark), `localStorage` key `model_sentinel.browse.theme`, CSS token structure exactly as spec §6.6.
- Fixtures are conspicuously synthetic (`example-provider`, `fake-org/test-model-a`); never real provider values.
- **No duplicate logic**: before writing any formatting, categorizing, squelch, or price logic, call the existing function (named per task). Before finishing each task, grep for the distinctive strings you wrote and confirm they exist once.
- Every task ends with the **full** suite green (`pytest`), then a commit.
- The user's global rules on test accountability and skeptical reporting apply to every step.

## Verified code facts the plan relies on

| Fact | Where |
|---|---|
| `cli.main()` loads config, then `store.initialize()` + `store.upsert_provider_configs(...)` (writes) for every command except `healthcheck` | `model_sentinel/cli.py:46-75` |
| Subparsers registered in `build_parser()`; `--detail` choices `default/all/squelched`; `_parse_date` for `YYYY-MM-DD`; `_report_detail_policy(args=, loaded=)` builds `ReportDetailPolicy` from args/settings | `cli.py:117-215, 821-835` |
| `load_config(project_root) -> LoadedConfig` with `.runtime_paths.database_path`, `.settings.report_detail`, `.providers: tuple[ProviderConfig,...]` (`provider_id,label,kind,price_multiplier,price_divisor,enabled`) | `config.py:72-135` |
| `resolve_profile(kind, price_multiplier=, price_divisor=) -> ProviderProfile`; `profile.categorize(field_name) -> str`; `profile.default_squelch_fields` | `provider_profiles.py:476`, `:150`, `:159` |
| `change_render.resolve_field_label(field_path, profile) -> (label, qualifier)`; `resolve_price_rule(field_path, profile) -> ResolvedPriceRule(unit_label, multiplier, divisor, comparison_group, normalized_target, match_source)`; `classify_change(FieldChange, *, profile) -> RenderedChange` (fields listed at `change_render.py:264-290`) | `change_render.py:119, 142, 1207` |
| `reporting.make_report_detail_policy`, `classify_detail_visibility(field_name, policy) -> "shown"/"squelched"/"unclassified"`, `_plan_changes_report_provider(models, policy, profile) -> _ChangesProviderPlan(entries, rollups)`, `_PlannedChangeEntry(model_id, display_name, kind, display: _FieldDisplayPlan|None)`, `_FieldDisplayPlan(visible, squelched, hidden_unclassified, hidden_non_squelched, unclassified_used, noop)`, `_HiddenRollups(squelched, non_squelched, noop)` each a `list[tuple[str, tuple[FieldChange,...]]]` | `reporting.py:75-145, 285-335, 947-1000` |
| `Store.recent_changes(*, provider_id, since, until) -> tuple[dict,...]` rows with `provider_id, provider_model_id, change_kind, field_name, old_value, new_value, detected_at, provider_label, display_name` (JSON already parsed; `from_scrape_id IS NULL` rows excluded) | `storage.py:526-580` |
| `Store.list_known_models(*, provider_id, since, until)`; `Store.history_events(...)` | `storage.py:444, 395` |
| `time_utils.local_date_for(value) -> date` | `time_utils.py:53` |
| Canonical `snapshot_models` price columns are **already normalized** per the profile rule at save time (`normalize._normalize_price`); metadata-path prices in `metadata_json` are **raw** | `normalize.py:124-205` |
| Schema: `providers`, `scrapes(scrape_id, provider_id, started_at, completed_at, status, baseline_mode, baseline_scrape_id, saved_snapshot, model_count, error_message)`, `snapshot_models(scrape_id, provider_id, provider_model_id, display_name, …, metadata_json)`, `field_changes(change_id, provider_id, from_scrape_id, to_scrape_id, provider_model_id, change_kind, field_name, old_value_json, new_value_json, detected_at)` | `storage.py:16-84` |
| Installer stages `model_sentinel/*.py` only and hashes `*.py` only | `install_standalone.sh:72-90` |
| Installer tests copy the project to a temp dir and run the script with `MODEL_SENTINEL_HOME` overridden | `tests/test_install_standalone.py:15-56` |

## File structure

| File | Responsibility |
|---|---|
| `model_sentinel/browse/__init__.py` | empty marker |
| `model_sentinel/browse/readonly.py` | `open_readonly(database_path) -> sqlite3.Connection`; schema presence check; `MissingDatabaseError`, `SchemaError` |
| `model_sentinel/browse/aspects.py` | `Aspect` dataclass; `build_aspect_catalog(connection, profiles, policy) -> tuple[Aspect,...]`; canonical column ↔ profile field map |
| `model_sentinel/browse/queries.py` | every SQL statement: scrapes, heatmap, series, events, catalog, models typeahead, change by id |
| `model_sentinel/browse/api.py` | parameter parsing/validation (`BadRequest`), endpoint functions returning JSON-able dicts; `RenderedChange` serialization; activity planning via `reporting.plan_changes_provider` |
| `model_sentinel/browse/server.py` | `find_free_port`, `BrowseHandler(BaseHTTPRequestHandler)`, `serve(...)`, `run_browse(...)` |
| `model_sentinel/browse/assets/index.html`, `app.css`, `app.js`, `vendor/*` | frontend |
| `model_sentinel/reporting.py` | rename `_plan_changes_report_provider` → public `plan_changes_provider` (alias kept), no behavior change |
| `model_sentinel/cli.py` | `browse` subparser, dispatch before writes, help epilog example |
| `install_standalone.sh` | stage `browse/` recursively; hash all staged files |
| `tests/browse_fixtures.py` | `build_fixture_db(path) -> FixtureFacts` synthetic DB builder |
| `tests/test_browse_readonly.py`, `test_browse_aspects.py`, `test_browse_queries.py`, `test_browse_api.py`, `test_browse_server.py`, `test_browse_offline.py`, `test_browse_theme.py` | per-module tests |
| `tests/test_cli.py`, `tests/test_install_standalone.py`, `tests/test_reporting.py` | additions |
| `README.md`, `docs/DESIGN.md` | docs |

---

### Task 1: Synthetic fixture DB + read-only connection + `browse` CLI skeleton

**Files:**
- Create: `tests/browse_fixtures.py`, `model_sentinel/browse/__init__.py`, `model_sentinel/browse/readonly.py`, `tests/test_browse_readonly.py`
- Modify: `model_sentinel/cli.py` (`build_parser`, `main`), `tests/test_cli.py`

**Interfaces:**
- Produces `tests.browse_fixtures.build_fixture_db(path: Path) -> FixtureFacts`. Build the DB **through `Store`** (`Store.initialize`, `upsert_provider_configs`, `create_scrape`, `save_snapshot_models`, `record_field_changes` — read their signatures in `storage.py:98-268`) so fixture rows are shaped exactly as production writes them. `FixtureFacts` is a frozen dataclass recording what you wrote so tests can assert against it: `provider_ids`, `scrape_ids` (ordered), `scrape_dates`, `model_ids`, `added_model`, `removed_model`, `price_step: (model_id, scrape_id_before, scrape_id_after, old, new)`, `context_step`, `bool_flip`, `bulk_list_models: tuple[str,...]` (≥3), `benchmark_churn_model`.
  Content: one provider `example-provider` of kind `openrouter` (so the real OpenRouter profile and its `benchmarks*` squelch apply) with `price_multiplier=1_000_000, price_divisor=1`; a second provider `other-provider` of kind `generic` with one model and two scrapes (so multi-provider paths are exercised). Six saved successful scrapes for `example-provider` on six distinct local dates (use `started_at/completed_at` ISO UTC strings days apart), plus one `status="error"` unsaved scrape. Models `fake-org/test-model-a` … `-e`. Scripted changes: `-a` input price `0.000002 → 0.0000035` raw (canonical column `input_price` goes `2.0 → 3.5`) between scrapes 2→3; `-b` `context_length` `128000 → 256000` (canonical `context_window`) at 3→4; `-c` `reasoning_supported` false→true at 4→5; `-a,-b,-c` all gain `reasoning_effort` in `supported_parameters` at 5→6 (bulk); `-d` added at scrape 4; `-e` removed at scrape 5; `-a` `benchmarks.design_arena.score` changes every scrape (squelched churn). `metadata_json` must contain the raw values under the OpenRouter paths (`pricing.prompt`, `context_length`, `supported_parameters`, `benchmarks.design_arena.score`) because `/api/series` reads paths with `json_extract`. Record `field_changes` rows by diffing consecutive snapshots with the real `diffing` module (see `diffing.py` and how `cli.run_scan` calls `record_field_changes`) rather than hand-writing rows.
- Produces `model_sentinel.browse.readonly.open_readonly(database_path: Path) -> sqlite3.Connection`: raises `MissingDatabaseError(path)` if the file is absent (never creates it); connects with `f"{database_path.as_uri()}?mode=ro"`, `uri=True`, `check_same_thread=False`, `row_factory = sqlite3.Row`; executes `PRAGMA query_only = ON`; calls `ensure_schema(connection)` which raises `SchemaError(missing_name)` if any of the four tables or the columns listed in the spec's schema row are missing (`PRAGMA table_info`).
- Produces CLI: `browse` subparser with `--port` (int, default 8110), `--no-open` (store_true), `--provider` (str). In `main()`, add `if args.command == "browse": return run_browse_command(args=args, loaded=loaded)` immediately after `load_config` succeeds and **before** `loaded.runtime_paths.ensure_directories()`. `run_browse_command` lives in `cli.py`, validates `--provider` with the existing `validate_selected_providers`, calls `open_readonly` (mapping `MissingDatabaseError` → `SystemExit` code 2 with message `Model Sentinel database not found at <path>. Run 'model-sentinel scan --save' first.`; `SchemaError` → code 2 naming the missing object), then delegates to `model_sentinel.browse.server.run_browse(connection=, loaded=, port=, open_browser=, initial_provider=)`. For this task `run_browse` can be a stub that returns 0; Task 6 implements it.

- [ ] Write `tests/browse_fixtures.py` and a test in `test_browse_readonly.py` that builds the fixture and asserts row counts match `FixtureFacts` (6 saved scrapes, ≥1 added/removed/field_changed in `field_changes`, bulk change present on ≥3 models).
- [ ] Write failing tests: `open_readonly` on a missing path raises `MissingDatabaseError` and creates no file; on the fixture it returns a connection where `PRAGMA query_only` is 1 and `INSERT` raises `sqlite3.OperationalError`; `ensure_schema` on a DB missing `field_changes` raises `SchemaError("field_changes")`; SHA-256 of the fixture file is unchanged after a query sweep.
- [ ] Implement `readonly.py`; run tests; pass.
- [ ] Write failing CLI tests in `test_cli.py`: `browse --help` exits 0 and mentions `--no-open`; with a missing DB `browse --no-open` exits 2 and the message names the path; with the fixture DB as `MODEL_SENTINEL_HOME/model_sentinel.db` and `run_browse` monkeypatched to record its kwargs, `upsert_provider_configs` is **not** called (monkeypatch `Store.upsert_provider_configs` to raise) and `run_browse` received `open_browser=False`. Look at how existing `test_cli.py` tests set up `MODEL_SENTINEL_HOME` and env files and follow that.
- [ ] Implement parser + dispatch + `run_browse_command`; add the `browse` example to the epilog.
- [ ] Run full suite; commit `Add browse subcommand skeleton with read-only DB access`.

### Task 2: Aspect catalog

**Files:**
- Create: `model_sentinel/browse/aspects.py`, `tests/test_browse_aspects.py`

**Interfaces:**
- Produces `Aspect` (frozen dataclass): `id: str`, `provider_id: str`, `source: Literal["column","path"]`, `column: str|None`, `path: str|None`, `field_name: str` (the profile field path used for labels — for columns, the mapped profile path; for paths, the path itself), `label: str`, `qualifier: str|None`, `category: str`, `kind: Literal["price","count","numeric","boolean","list","scalar"]`, `unit: str|None`, `multiplier: int`, `divisor: int`, `squelched: bool`. `to_json() -> dict`.
- Produces `build_aspect_catalog(connection, *, profiles: dict[str, ProviderProfile], policy: ReportDetailPolicy) -> tuple[Aspect, ...]`.
- Aspect `id` format: `"{provider_id}:{column}"` for columns, `"{provider_id}:path:{path}"` for paths. Deterministic order: category order as the profile's pricing order then alphabetical within category.

**Load-bearing decisions:**
- Canonical column ↔ profile field map for OpenRouter-kind profiles: `input_price→pricing.prompt`, `output_price→pricing.completion`, `cache_read_price→pricing.input_cache_read`, `cache_write_price→pricing.input_cache_write`, `context_window→context_length`, `max_output_tokens→top_provider.max_completion_tokens`, booleans → their own names (label via `_prettify_leaf` behavior of `resolve_field_label`, category "Capabilities"). For the generic profile use the same map (labels fall back to prettified leaves). Put the map in `aspects.py` as one constant; do not duplicate it in `queries.py`.
- **Scale**: for `source == "column"` price aspects, `multiplier = divisor = 1` (already normalized — see verified facts) and `unit` from `resolve_price_rule(field_name, profile).unit_label`. For `source == "path"` price aspects, `multiplier/divisor` from `resolve_price_rule` so the series endpoint can normalize raw values. Test both explicitly.
- Path discovery: `SELECT DISTINCT provider_id, field_name FROM field_changes WHERE field_name IS NOT NULL`; keep a path only if its leaf is scalar in the latest snapshot that has it (`json_type(json_extract(metadata_json, '$.' || path))` in `('integer','real','true','false','text','null')` — arrays are `list` kind, objects are dropped). Kind: price if `profile`'s `is_price_amount_field`-style predicate says so (see `provider_profiles.py:110` and how `classify_change` decides `price`; reuse the same predicate, do not write a new `"pricing" in path` check), boolean for `json_type` true/false, count if `default_is_count_field`, numeric for integer/real, list for arrays, scalar otherwise.
- `squelched = classify_detail_visibility(field_name, policy) == "squelched"`.
- JSON path escaping: field names containing `"` or `.`-within-key are not expected, but guard: if a path segment contains a character outside `[A-Za-z0-9_\-]`, skip the aspect and log at debug level rather than building an injectable expression.

- [ ] Write failing tests on the fixture: the catalog contains `example-provider:input_price` with `unit == "/1M tokens"`, `multiplier == 1`, `category == "Pricing"`, `kind == "price"`; contains `example-provider:path:benchmarks.design_arena.score` with `squelched is True`, `kind == "numeric"`, `category == "Benchmarks"` (confirm the real category string from `default_categorize`); contains `example-provider:path:supported_parameters` with `kind == "list"`; path ordering deterministic across two calls; a path with an unsafe character is skipped.
- [ ] Implement; run; pass; full suite; commit `Add browse aspect catalog`.

### Task 3: Queries

**Files:**
- Create: `model_sentinel/browse/queries.py`, `tests/test_browse_queries.py`

**Interfaces (all take `connection: sqlite3.Connection` first):**
- `list_scrapes(connection) -> list[dict]`: `{scrape_id, provider_id, date (local, via local_date_for(completed_at)), completed_at, status, saved: bool, model_count}` ordered by `completed_at`.
- `date_span(connection) -> tuple[date, date] | None` over saved successful scrapes.
- `heatmap_counts(connection, *, provider_ids, since, until) -> dict[date, dict[str, int]]` — raw counts per local date keyed `changed/added/removed` plus a per-date `Counter[field_name]` so `api.py` can compute `squelched` with `classify_detail_visibility` (the policy is not a query concern). Only rows with `from_scrape_id IS NOT NULL` (match `recent_changes`).
- `saved_scrape_ids(connection, *, provider_id, since, until) -> list[dict]` (`scrape_id, date, completed_at`) — successful saved only.
- `series_rows(connection, *, provider_id, scrape_ids, model_ids, columns: tuple[str,...], paths: tuple[str,...]) -> list[sqlite3.Row]` — one SELECT with `json_extract` per path, `WHERE scrape_id IN (...) AND provider_model_id IN (...)`, parameters bound with `?` placeholders (build the placeholder list; never f-string values). `json_type` alongside each `json_extract` so the caller can distinguish list/object.
- `events_for_models(connection, *, provider_id, model_ids, since, until) -> list[dict]` — `change_id, date, provider_model_id, change_kind, field_name, old_value, new_value` parsed with `_load_json_value` semantics (import `storage._load_json_value` or lift it to a public helper; do not re-write it).
- `catalog_rows(connection, *, scrape_id, columns, paths) -> dict[model_id, dict]` — all models in the scrape with `display_name` and the requested values.
- `search_models(connection, *, provider_ids, query, limit) -> list[dict]` — latest display name per model via the same `MAX(display_name)`/`last_seen` shape as `Store.list_known_models`, case-insensitive substring on id or name.
- `change_by_id(connection, change_id) -> dict | None` — raw row plus both scrapes' `{scrape_id, date, completed_at, status}`.

- [ ] Write failing tests per function on the fixture: scrape list length/ordering and `saved`/`status` values; date span; heatmap has the right `added`/`removed` dates and `changed` count for the price-step date; `series_rows` returns `null`-free rows for present models and no row for `-d` before it was added (the pivot to `null` happens in api); `events_for_models` returns the price-step change with parsed floats; `catalog_rows` for the last scrape excludes the removed model; `search_models("model-a")` finds `-a` only; `change_by_id` of the price step returns both scrapes; an unknown id returns `None`.
- [ ] Implement; run; pass; full suite; commit `Add browse SQL queries`.

### Task 4: Public `plan_changes_provider` + JSON serialization + API layer

**Files:**
- Modify: `model_sentinel/reporting.py` (rename `_plan_changes_report_provider` → `plan_changes_provider`; keep `_plan_changes_report_provider = plan_changes_provider` alias; update internal callers), `tests/test_reporting.py` (one test that the public name exists and equals the alias)
- Create: `model_sentinel/browse/api.py`, `tests/test_browse_api.py`

**Interfaces:**
- `api.BadRequest(Exception)` with `.message`; `api.NotFound(Exception)`.
- `api.ApiContext` (dataclass): `connection`, `providers: tuple[ProviderConfig,...]`, `profiles: dict[str, ProviderProfile]`, `policy_for(detail: str|None) -> ReportDetailPolicy` (built with `make_report_detail_policy` and the settings' show/squelch/unclassified values exactly as `cli._report_detail_policy` does — lift that function's body into a shared helper in `reporting.py` or `config.py` called by both; do not copy it), `aspects: tuple[Aspect,...]`, `settings`.
- `api.parse_common(params: dict[str, list[str]]) -> Common(providers, since, until, detail)` with the 400 rules from spec §7 (`from > to`, bad date, unknown provider).
- Endpoint functions, each `(ctx, params) -> dict`: `meta`, `activity`, `heatmap`, `series`, `events`, `catalog`, `change`, `models`. Shapes exactly as spec §5.
- `api.rendered_change_to_json(rc: RenderedChange) -> dict`: `dataclasses.asdict` then replace `price_rule` with `{"unit": rule.unit_label, "multiplier": ..., "divisor": ...}` or `None`; drop nothing else (the client reads `kind`, `direction`, `semantic`, `label`, `qualifier`, `old_display`, `new_display`, `delta_display`, `pct_display`, `unit`, `list_added`, `list_removed`, `field_path`).

**Load-bearing guidance:**
- `activity`: for each selected provider call `Store.recent_changes` (construct a `Store(database_path)` only to reuse the method? **No** — `Store._connect` opens read-write. Instead lift the SQL of `recent_changes` into a function that accepts a connection: add `storage.recent_change_rows(connection, *, provider_id, since, until)` and have `Store.recent_changes` call it. One implementation.) Group rows by local date then by model like `_plan_changes_report_provider`'s caller does in `render_changes_report` (read `reporting.py` around `_plan_changes_report_provider` call sites to see the exact grouping) and call `plan_changes_provider(models, policy, profile)` per (provider, date). Convert each `_PlannedChangeEntry` to the spec entry dict; `changes` = `[rendered_change_to_json(classify_change(fc, profile=profile)) for fc in display.visible]`; `hidden` counts from `display.squelched/hidden_unclassified/noop` lengths; `change_ids` resolved by matching `(model_id, field_name)` back to the source rows (carry `change_id` through: add it to the `recent_change_rows` SELECT). Apply `models`, `categories` (via `profile.categorize(fc.field_name)` on the visible changes; an entry with no remaining visible change and no presence event is dropped), `kinds` filters after planning; then page. Sort entries newest date first, provider, model.
- `series`: validate ≤8 models (`provider_id/model_id` tokens; all must share… no — models may span providers; group by provider and issue one `series_rows` per provider) and ≤12 aspects, all aspect ids known. For each provider build `scrapes` from `saved_scrape_ids`; pivot rows into `values` aligned to that list with `null` for absent (model, scrape). Column price aspects: value as stored. Path price aspects: `value * multiplier / divisor`. Booleans → `0/1`. Lists → `len` and `list_hash` = `hashlib.sha1(json.dumps(sorted(members)).encode()).hexdigest()[:8]`. **Test the no-double-scaling rule**: `example-provider:input_price` series equals the stored `input_price` column exactly.
- `events`: squelched flag via `classify_detail_visibility(field_name, policy) == "squelched"`; `semantic/direction` via `classify_change` (presence rows: `direction` `added/removed`, `semantic` `"neutral"`).
- `catalog`: `as_of`/`compare` must be saved successful scrapes of `provider`; `compare` must have an earlier `completed_at`. Diff cells: `classify_change(FieldChange(aspect.field_name, old_raw, new_raw), profile=profile)` where for column price aspects you must pass **raw** values (`stored / (multiplier/divisor)` of the profile rule) so `classify_change` normalizes once — or, simpler and safer: pass the canonical values with a `FieldChange` whose `field_name` is the profile path and accept `classify_change`'s normalization by dividing first. Write the test `old_display == "$2.00"` and `new_display == "$3.50"` for the fixture price step and make it pass; whichever path you choose, the display must match the `changes` report's for the same change (assert equality with a `classify_change` call on the real `field_changes` row).
- Sorting for `catalog`: by any returned column, `null` last; default by `model_id`.
- `change`: 404 via `NotFound` when missing.

- [ ] Add the reporting rename + test; run; pass; commit `Expose plan_changes_provider for reuse`.
- [ ] Add `storage.recent_change_rows` refactor + test that `Store.recent_changes` output is unchanged on the fixture (compare before/after using a snapshot of the tuple taken in the test from the alias path — simplest: assert `Store.recent_changes(...)` equals `recent_change_rows(conn, ...)` minus the new `change_id` key); commit.
- [ ] Write failing tests for `parse_common` (each 400 case) and for each endpoint's shape on the fixture, including: activity entries equal to `plan_changes_provider` output for the same range (same entry count, same bulk model list, same hidden counts); heatmap `squelched` on a churn date ≥1; series no-double-scaling; catalog diff presence `added`/`removed` and price displays; change 404.
- [ ] Implement `api.py`; run; pass; full suite; commit `Add browse JSON API layer`.

### Task 5: Vendored assets, index.html shell, CSS tokens, theme

**Files:**
- Create: `model_sentinel/browse/assets/index.html`, `app.css`, `vendor/preact.min.js`, `vendor/hooks.min.js`, `vendor/htm.min.js`, `vendor/uplot.min.js`, `vendor/uplot.min.css`, `vendor/preact.LICENSE`, `vendor/htm.LICENSE`, `vendor/uplot.LICENSE`, `vendor/VERSIONS.md`; `tests/test_browse_offline.py`, `tests/test_browse_theme.py`

**Vendoring (one-time network; record exact versions in `VERSIONS.md`):**
- Preact 10.x UMD: `https://unpkg.com/preact@10/dist/preact.umd.js` (exposes global `preact`); hooks UMD: `https://unpkg.com/preact@10/hooks/dist/hooks.umd.js` (global `preactHooks`, requires `preact` loaded first); htm 3.x UMD: `https://unpkg.com/htm@3/dist/htm.umd.js` (global `htm`); uPlot 1.6.x: `https://unpkg.com/uplot@1/dist/uPlot.iife.min.js` (global `uPlot`) and `https://unpkg.com/uplot@1/dist/uPlot.min.css`. Fetch the matching `LICENSE` files from each package root. Resolve `@10`/`@3`/`@1` to the concrete version unpkg redirects to and write that in `VERSIONS.md` with the final URLs. Verify each file's first line contains the expected global before committing.
- Script order in `index.html`: theme stamp inline script (before any CSS link, reads `localStorage['model_sentinel.browse.theme']`, sets `document.documentElement.dataset.theme` for `light`/`dark`, removes for anything else), `<link rel=stylesheet href="vendor/uplot.min.css">`, `<link rel=stylesheet href="app.css">`, then `vendor/preact.umd.js`, `vendor/hooks.umd.js`, `vendor/htm.umd.js`, `vendor/uPlot.iife.min.js`, `app.js`. Keep the vendor filenames as downloaded (adjust the file list above to match) — `VERSIONS.md` is the map.
- `app.css`: tokens per spec §6.6. Dark industrial palette from the existing HTML report (open `reporting.py`'s HTML CSS and reuse its hex values for ground/panel/ink/cost colors so the browser and reports match); light palette chosen with the same hue bias. Semantic tokens: `--cost-up`, `--cost-down`, `--capacity`, `--capability`, `--dim`, `--presence-added`, `--presence-removed`, `--accent`. Layout tokens. Component classes for filter bar, sidebars, feed entries, tables, panels, drawer, banner, empty state, segmented control. `prefers-reduced-motion` block. Focus-visible outlines.

- [ ] Write `test_browse_offline.py`: read `index.html`, `app.css`, `app.js` (app.js may not exist yet — make the test iterate over whatever `assets/**` exists, excluding `vendor/*.LICENSE` and `VERSIONS.md`) and assert no `http://`, `https://`, or `//` URL tokens outside `/* … */` or `//` comment lines and license headers (strip comments before matching); assert every `src`/`href` in `index.html` resolves under `assets/` via `importlib.resources.files("model_sentinel.browse").joinpath("assets", …).is_file()`.
- [ ] Write `test_browse_theme.py`: parse `app.css` with a small regex pass — collect `--name` declarations per block; every name set inside a `@media (prefers-color-scheme: dark)` block or a `[data-theme=` block is also set on bare `:root`; the dark media block's selector contains `:root:not([data-theme="light"])`; `index.html` contains `model_sentinel.browse.theme` in an inline `<script>` before the first `<link`.
- [ ] Download vendor files, write `index.html` and `app.css`; run both tests; pass; full suite; commit `Vendor Preact, htm and uPlot; add offline shell and theme tokens`.

### Task 6: HTTP server

**Files:**
- Create: `model_sentinel/browse/server.py`, `tests/test_browse_server.py`
- Modify: `model_sentinel/cli.py` (`run_browse_command` now calls the real `run_browse`)

**Interfaces:**
- `find_free_port(start_port: int, max_attempts: int = 20) -> int` (repo convention pattern from `CLAUDE.md`, `127.0.0.1`); raises `RuntimeError` with the range.
- `make_server(ctx: ApiContext, *, host="127.0.0.1", port: int) -> ThreadingHTTPServer` — handler class closes over `ctx`; `daemon_threads = True`.
- `run_browse(*, connection, loaded, port, open_browser: bool, initial_provider: str|None) -> int`: builds profiles (`resolve_profile` per configured provider exactly as `run_changes` does — lift that dict comprehension into a shared `config`/`provider_profiles` helper `profiles_for(providers)` and use it from both `run_changes` and here), policy, aspect catalog, `ApiContext`; resolves port (warn on change via `logging`); starts server; if `open_browser`, `webbrowser.open(url)` after `server_bind` succeeds (append `#providers=<initial_provider>` when given); `serve_forever()` until `KeyboardInterrupt`, then `server.shutdown()`/`server_close()` and `connection.close()`; returns 0. Print the URL to stdout.
- Routing in `do_GET`: `/` and `/index.html` → `index.html`; `/app.js`, `/app.css`, `/vendor/<name>` → package data (reject any path containing `..` or not matching `^[A-Za-z0-9_.\-]+$` per segment with 404); `/api/<name>` → `api.<name>`; `/api/change/<int>` → `api.change`. Parse query with `urllib.parse.parse_qs(keep_blank_values=False)`. Map `BadRequest` → 400, `NotFound` → 404, any other exception → 500 with `{"error": "internal error: <type>"}` and a `logging.exception`. JSON responses: `Content-Type: application/json; charset=utf-8`, `Cache-Control: no-store`. Static: `Content-Type` by extension (`html/css/js/md/txt`), `Cache-Control: no-store`. Override `log_message` to route through `logging.debug` (no stderr spam).
- Content-type table lives once in `server.py`.

- [ ] Write failing tests: `find_free_port` returns the start port when free and the next one when a socket holds it; server on an ephemeral port (`port=0` then read `server.server_address[1]`) serves `/` with `text/html` containing `<script src="app.js"`, `/app.css` as `text/css`, `/vendor/<each file>` 200, `/vendor/../cli.py` 404, `/api/meta` JSON with `pin_limit == 8` and `aspects` non-empty, `/api/activity?from=bad` → 400 with `error`, `/api/change/999999` → 404, `/api/nope` → 404; a POST → 405 (implement `do_POST` returning 405). Fixture DB SHA-256 unchanged after the sweep (reuse the helper from Task 1's test module).
- [ ] Implement `server.py`; wire `cli.run_browse_command`; extend `test_cli.py`: with `--no-open` and a monkeypatched `serve_forever` that raises `KeyboardInterrupt` immediately, the command returns 0 and prints the URL; `webbrowser.open` is not called with `--no-open` and is called once without it (monkeypatch).
- [ ] Run; pass; full suite; commit `Add browse HTTP server and static/API routing`.

### Task 7: Frontend shell, hash state, Activity view

**Files:**
- Create: `model_sentinel/browse/assets/app.js`
- Modify: `app.css` as needed

**Structure (single IIFE; `const { h, render } = preact; const { useState, useEffect, useMemo, useRef, useCallback } = preactHooks; const html = htm.bind(h);`):**
- `hashState.read() -> state`, `hashState.write(partial)` — keys per spec §6.1; list values comma-joined with `encodeURIComponent` per item; `pins` as `provider/model` tokens. Defaults: `view=activity`, `providers` = all enabled from meta, `from` = max(last−30 days, first), `to` = last, `detail` = `meta.detail_default`. `useHashState()` hook subscribes to `hashchange`.
- `api.get(path, params) -> Promise<json>`; non-2xx → throws `ApiError(message)`; `useApi(path, params, deps)` returns `{data, error, loading}` and keeps the previous `data` on error (spec §7: never a blank page).
- `App`: `FilterBar` (view tabs `1/2/3`, provider chips, from/to date inputs clamped to `meta.date_span`, detail segmented control, **theme segmented control** System/Light/Dark writing `localStorage` and the `data-theme` attribute, plus a `matchMedia('(prefers-color-scheme: dark)')` listener that triggers a re-render when theme is `system` so charts re-read tokens), `ErrorBanner`, view switch, `RawDrawer` (fetches `/api/change/{id}`, shows `rendered` summary, raw old/new JSON in `<pre>`, both scrapes; `Esc` closes).
- Activity: `Heatmap` (180 cells ending at `to`, intensity quantized into 4 steps of `--heat-*` tokens; click sets `from=to=date`; mouse-drag sets a range; small presence dots), `Facets` (providers, categories from `meta` — collect distinct `aspect.category` values, kinds, detail), `Feed` (date blocks → entries; `changed` entries as a compact table: label+qualifier, `old_display → new_display`, `delta_display`, `pct_display`, `unit`; row class from `semantic`+`direction` — `cost/up`→`--cost-up`, `cost/down`→`--cost-down`, `capacity`→`--capacity`, `capability`/list added→`--capability`, list removed & neutral→`--dim`, presence entries `--presence-*`; bulk entries show the shared change once with an expandable model list when `entry.bulk_models` exists — add that key in `api.activity` for bulk groups if Task 4 did not; the hidden rollup line with `— show` flipping `detail=all`). Model name click → `hashState.write({view:'models', pins: addPin(...), from: date−30d, to: date+30d})` with the cap-8 oldest-drop + toast. Pager.
- Keyboard: `/` focus typeahead (Models view only — no-op elsewhere), `1/2/3` views, `Esc`.

**Manual verification (no JS test runner):** run `./model-sentinel browse --no-open` against a copy of the fixture DB (`MODEL_SENTINEL_HOME` pointing at a temp home seeded with the template env files and the fixture DB) and check in the in-app browser: heatmap renders, feed shows the price step with `$2.00 → $3.50` colored `--cost-up`, the bulk entry lists 3 models, hidden rollup toggles, RawDrawer opens, theme toggle switches all three states without unreadable text, hash round-trips on reload. Record what you observed in the commit body.

- [ ] Implement; update `test_browse_offline.py` expectations if new asset files were added; full suite; commit `Add browse frontend shell and Activity view`.

### Task 8: Models view

**Files:**
- Modify: `app.js`, `app.css`

- `Pins` (swatches from an 8-color categorical palette defined as tokens `--series-1..8` in both themes; remove ×; `Typeahead` backed by `/api/models?q=`, debounced 150 ms, Enter adds, cap 8 with toast).
- `AspectPicker`: groups by `category` in the order aspects arrive from `/api/meta` (already profile-ordered); squelched aspects under a collapsed `<details>` titled by their categories; checking writes `aspects=`.
- `PanelStack`: one `Panel` per selected aspect. For `kind in (price, count, numeric)`: uPlot with `scales.x.time=true`, x values = scrape `completed_at` epoch seconds, one series per pinned model with `paths: uPlot.paths.stepped({align: 1})`, `spanGaps: false`, stroke from the pin's token, y-axis label `unit`, `cursor.sync.key = "ms-browse"`, `setScale` hook on x that writes `from/to` after a drag-zoom (debounced) — all panels re-fetch from the hash. For `boolean`/`list`: `StateStrip` — a div-based strip per pinned model, one segment per scrape, colored `--capability` for true/`--dim` for false/transparent for null, list segments colored by `list_hash` changes (alternate two tints on each change), hover title shows the value. Height 56 px.
- `EventRail`: marks from `/api/events` positioned by date across the same x range (compute percent from from/to); color by `semantic/direction` using the Task 7 mapping; `squelched` at 40% opacity; click → RawDrawer; hover → `uPlot.setCursor` on all panels at that x (via the sync key) .
- Theme change: re-create uPlot instances (simplest correct approach) by keying panels on the theme value.
- Legend hover emphasizes the series in every panel (set other series' `width` to 1 and alpha via `u.setSeries(idx, {focus:true})`).

**Manual verification:** pin `-a` and `-b`, select Input price and Context window: `-a` shows a step at the price date; `-b` shows a context step; `-d` pinned shows a gap before its added date (no line from zero); the rail shows the squelched benchmark churn dim; dragging to zoom updates the hash and the feed when switching to Activity.

- [ ] Implement; full suite; commit `Add browse Models view with stepped timelines and event rail`.

### Task 9: Catalog view and cross-links

**Files:**
- Modify: `app.js`, `app.css`

- `Pickers`: provider select (single), `as_of` and `compare` selects listing saved successful scrapes (`date · N models`), `compare` options limited to earlier scrapes; "none" option clears compare.
- `ColumnChooser`: checkboxes over the provider's aspects; default set = canonical price/limit/capability columns.
- `Table`: sticky header, click header to sort (`sort`, `dir` in hash), `q` filter input, `tabular-nums`; diff cells show `old_display → new_display` colored by `change.semantic/direction`; presence rows with `--presence-added/-removed` left stripe; pager.
- `SparklinePopover`: on numeric cell click; tiny uPlot (height 80) from `/api/series` over `meta.date_span`; "Open timeline" → `{view:'models', pins:[model], aspects:[aspect]}`.
- "Show as feed" → `{view:'activity', from: compare.date, to: as_of.date, providers:[provider]}`.
- Cross-links from spec §6 verified in all directions.

**Manual verification:** as-of last scrape shows 5 models minus the removed one; compare to scrape 2 highlights the price, context and boolean changes, marks `-d` added and `-e` removed; sort by input price; sparkline opens; all three cross-links land with the expected hash.

- [ ] Implement; full suite; commit `Add browse Catalog view with diff and cross-links`.

### Task 10: Installer and standalone packaging

**Files:**
- Modify: `install_standalone.sh` (`stage_zipapp_source`, `SOURCE_HASH`), `tests/test_install_standalone.py`

- `stage_zipapp_source`: after copying `model_sentinel/*.py`, `cp -R "$SCRIPT_DIR/model_sentinel/browse" "$STAGING_DIR/model_sentinel/browse"` then `find "$STAGING_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} +` and delete `*.pyc`.
- `SOURCE_HASH`: remove `-name '*.py'`; keep the `_packaged_build.py` exclusion. Read the rest of the script to confirm nothing else assumes Python-only staging (the smoke check, the `--check` comparison).
- Tests: staged zipapp contains `model_sentinel/browse/assets/index.html`, `app.js`, `app.css`, every vendor file and LICENSE (`zipfile.ZipFile(target).namelist()`); modifying `app.css` in the copied project makes `--check` report `stale` (mirror the existing source-drift test); the built target run with `browse --no-open --port 0`… `--port 0` is not supported — instead run the target with `browse --no-open` in a subprocess with `MODEL_SENTINEL_HOME` set to a seeded temp home containing the fixture DB and template env files, read the printed URL from stdout, fetch `/` and `/api/meta` with `urllib.request`, assert 200 and `pin_limit == 8`, then terminate the process. This proves `importlib.resources` works inside the zipapp.

- [ ] Write failing tests; modify installer; run `tests/test_install_standalone.py`; pass; full suite; commit `Package browse assets in the standalone zipapp`.

### Task 11: Documentation and final verification

**Files:**
- Modify: `README.md` (Status bullet; new `### Browse History` section under Commands with the command, the three views, read-only/offline guarantees, keyboard shortcuts, theme; Help list), `docs/DESIGN.md` (short "History browser" subsection linking the spec), `model_sentinel/cli.py` epilog (already in Task 1 — verify), `model_sentinel/browse/assets/vendor/VERSIONS.md` (verify complete).

- [ ] Update docs.
- [ ] Duplicate-logic exit check: grep for `resolve_profile(`, `make_report_detail_policy(`, `json_extract`, `fnmatch`, `"/1M` , `Content-Type` and confirm each lives in one implementation site (plus tests).
- [ ] Run the complete suite: `source .venv/bin/activate && pytest -q`. Report every failure by name with output; fix before proceeding.
- [ ] Run `./install_standalone.sh --check` against the real target only if the user wants the installed standalone rebuilt — otherwise leave the installed target alone and say so.
- [ ] `git ls-files model_sentinel/browse tests | sort` — confirm every new file (including `vendor/*`) is tracked; `.gitignore` must not drop `*.min.js`/`*.min.css`.
- [ ] Commit `Document model-sentinel browse`.

## Self-review against the spec

- §1 decisions → Tasks 1 (read-only, dispatch), 5 (offline/vendored/theme), 7–9 (views, cap), 2 (benchmarks first-class + squelched flag).
- §3 CLI → Task 1, 6. §4 layout → all. §5 endpoints: meta/activity/heatmap/series/events/catalog/change/models → Tasks 3, 4, 6. §5.1 aspects → Task 2. §6.1–6.5 → Tasks 7–9. §6.6 → Tasks 5, 7, 8. §7 errors → Tasks 1, 4, 6, 7. §8 → Task 10. §9 tests → each task; `test_browse_readonly/aspects/queries/api/server/offline/theme`, cli and installer additions. §10 docs → Task 11.
- Names used consistently: `open_readonly`, `build_aspect_catalog`, `Aspect`, `ApiContext`, `BadRequest`, `NotFound`, `plan_changes_provider`, `recent_change_rows`, `profiles_for`, `rendered_change_to_json`, `find_free_port`, `make_server`, `run_browse`, `run_browse_command`, `build_fixture_db`, `FixtureFacts`.
- Spec amendment required (done alongside this plan): §5 `/api/series` — canonical price columns are already normalized; only path price aspects are scaled.
