# `model-sentinel browse` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [`docs/superpowers/specs/2026-08-23-model-sentinel-browse-design.md`](superpowers/specs/2026-08-23-model-sentinel-browse-design.md)

**Goal:** A read-only, fully offline history browser (`model-sentinel browse`) with Activity, Models and Catalog views over the existing SQLite database, packaged inside the existing zipapp.

**Architecture:** New `model_sentinel/browse/` subpackage: stdlib `http.server` serving package-data assets and a JSON API; SQL in `queries.py`; aspect catalog in `aspects.py`; all labeling, categorization, price units and change rendering delegated to the existing `provider_profiles`, `change_render`, `normalize` and `reporting` modules. Frontend is a single Preact + htm app with uPlot charts, no build step.

**Tech Stack:** Python ≥ 3.11 stdlib only (`http.server`, `sqlite3`, `json`, `importlib.resources`, `socket`, `webbrowser`, `threading`); vendored Preact 10.29.8, preact/hooks, htm 3.1.1, uPlot 1.6.32 (all MIT).

> **Revision note (adversarial review, 2026-08-23).** This plan replaces an earlier draft that contained four defects proven wrong against the code: (1) it claimed the `changes` planner bulk-consolidates — it does not; (2) it planned to call `Store.recent_changes` per request — that call is measured at 4m41s on the real database, and a narrowed date range does not help; (3) it planned to feed canonical price columns into `classify_change`, which inflates them by the provider factor (`$2.00` → `$2,000,000.00`); (4) it specified an offline test that the vendored libraries fail by construction. Each is corrected below and marked **[REVIEW]**. Evidence is in §"Measured facts".

## Global Constraints

- Runtime stays **stdlib-only**; no new PEP 723 dependencies, no pip, no build step.
- Python tests run inside the project venv: `source .venv/bin/activate && pytest` (never bare system python).
- The **page** must reference no external URL. Vendored library *contents* legitimately contain URL strings (XML namespaces, license banners) — see [REVIEW-4].
- The browser **never writes**: read-only connections, `PRAGMA query_only = ON`, and no directory creation under `~/.model_sentinel`.
- `browse` dispatches in `cli.main()` **before** `loaded.runtime_paths.ensure_directories()`, `store.initialize()` and `store.upsert_provider_configs(...)` — all three write.
- Pin cap **8** models; aspect cap **12** per series request.
- Color contract from README "Color Semantics": red/green = cost direction only (plus presence lists and run status); amber capacity; blue capability/list membership; dim informational.
- Theme: three states (system/light/dark), `localStorage` key `model_sentinel.browse.theme`, CSS token structure exactly as spec §6.6.
- Fixtures are conspicuously synthetic (`example-provider`, `fake-org/test-model-a`); never real provider values.
- **No duplicate logic.** Every formatting, categorizing, squelch, price and field-resolution rule already exists. Call it. Before finishing each task, grep for the distinctive strings you wrote and confirm each lives in exactly one implementation site.
- Every task ends with the **full** suite green (`pytest`), then a commit.
- The user's global rules on test accountability and skeptical reporting apply to every step. Report failures by name with output; never dismiss one as unrelated.

## Measured facts (verified 2026-08-23 against the real database and libraries)

Do not re-derive these; do not contradict them without new measurement.

| Fact | Evidence |
|---|---|
| `Store.recent_changes` is **measured at 280.7 s** for the full history (14,853 rows) and **309.7 s** for a one-month range — a narrow `--since` is *not* faster, because the range is filtered in Python after the full scan. Cause: a per-row correlated subquery over `snapshot_models` (57,558 rows), ~33 ms/row. | direct timing against a copy of `~/.model_sentinel/model_sentinel.db` |
| `recent_changes` has **no date predicate in SQL** (`storage.py:547`, `WHERE fc.from_scrape_id IS NOT NULL` only); `--since/--until` are applied in Python after `fetchall()`. Every call pays the full cost regardless of range — confirmed by the 280 s / 310 s pair above. Returned rows have exactly 9 keys and no `change_id`. | `storage.py:545-580` |
| **End-to-end proof on the shipped CLI:** `./model-sentinel changes --since 2026-08-20` — a **3-day** range — took **311.79 s real** (5 min 12 s) and produced a 2.1 MB artifact. This is current user-facing behaviour, not a browser-only concern. | `/usr/bin/time -p` against the real runtime home, `--output` to a scratch path |
| `BULK_CHANGE_MIN_MODELS = 3` (`reporting.py:68`); `pricing_field_sort_key(field_path, profile)` (`change_render.py:240`); `validate_selected_providers` lives in **`config.py:305`**, not `cli.py`. | grepped |
| A CTE rewrite (`ROW_NUMBER()` for latest display name + date predicate in SQL) returns **all 14,853 rows in 0.16 s**, and a one-month range in **0.116 s** — a ~3,000× improvement with identical columns. | measured |
| Other endpoint shapes are already fast: heatmap aggregate 0.007 s; `json_extract` series for one model 0.032 s; one scrape's catalog (422 rows) <0.001 s; distinct field paths (51 rows) 0.006 s. | measured |
| There are **no indexes** on `field_changes` (only two autoindexes exist). None are needed at this data size once the correlated subquery is gone — and the browser cannot create one anyway (read-only). | `sqlite_master` |
| `classify_change` on an **already-normalized** canonical value double-normalizes: `FieldChange("pricing.prompt", 2.0, 3.5)` renders `$2000000.00 → $3500000.00`, while the raw pair `0.000002 → 0.0000035` correctly renders `$2.00 → $3.50`. | executed |
| `dataclasses.asdict(RenderedChange)` **is** JSON-serializable as-is; `price_rule` becomes a nested dict with key `unit_label` (not `unit`); `PriceNormalizedTarget`/`PriceRuleMatchSource` are `Literal` strings, not enums. | executed |
| `classify_detail_visibility(None, policy)` raises `TypeError`. `field_changes.field_name` is **NULL for every added/removed row** (866 such rows in the real DB). | executed; `storage.record_field_changes:28` |
| Canonical columns are populated through `profile.normalized_fields`, an **ordered candidate list per column** — the winning path varies per model (`normalize._profile_field_candidate`, first truthy wins). There is no single static column→path map. | `normalize.py:96-135`, profile dump |
| Exact category strings: `Pricing`, `Context & Limits`, `Capabilities`, `Parameters`, `Benchmarks`, `Other`. `pricing_field_order` holds **leaf** names: `('prompt','input_cache_read','input_cache_write','input_cache_write_1h','input_audio_cache','completion')`. | executed |
| `resolve_price_rule` returns `unit_label='/unit unknown'` for non-price fields — never show it as a unit for a non-price aspect. | executed |
| Live DB `journal_mode = delete` (not WAL), so a read-only open needs no `-shm`; but a concurrent launchd scan takes an exclusive lock and readers get `SQLITE_BUSY`. | `PRAGMA journal_mode` |
| `detected_at` / `completed_at` are stored as ISO-8601 UTC with offset, e.g. `2026-03-13T18:10:45.984072+00:00` — lexicographic string comparison is valid for range predicates. | queried |
| The `changes` report buckets by `to_local_human(detected_at).split(" ")[0]` (format `%Y-%m-%d %H:%M:%S`), then `provider_id`, then model — equivalent to `local_date_for`. | `reporting.py:1463-1468`, `time_utils.py:47` |
| `_plan_changes_report_provider` (`reporting.py:947`) does **not** bulk-consolidate. Bulk grouping (`_BulkChangeGroup`, `_bulk_change_signature`, `BULK_CHANGE_MIN_MODELS`) lives in `_plan_provider_changes` (`reporting.py:629`), the **scan** path. | read |
| `python3 -m zipapp "$STAGING_DIR"` packages whatever is staged, so assets ship once staged; but `stage_zipapp_source` copies only `model_sentinel/*.py` and `SOURCE_HASH` hashes only `*.py`. | `install_standalone.sh:72-90, 160` |
| Vendored libraries, pinned and hashed: `preact@10.29.8/dist/preact.umd.js` sha256 `134b77bc803fa38661dc1b1e44e96eb0bb6a1a00edbb96d34dcde421b2e80b06` (global `preact`); `preact@10.29.8/hooks/dist/hooks.umd.js` sha256 `5c29238e5dc99df306d7f7fff038591a397cfcfabb59f81fbdef43d670aa0566` (global `preactHooks`); `htm@3.1.1/dist/htm.umd.js` sha256 `7a31776e04bd4afde0d4308177d26f377716fcf7e4bd70be590746d6aa594f08` (global `htm`); `uplot@1.6.32/dist/uPlot.iife.min.js` sha256 `19c8d4c6ad88929a79f4ae49d6f7161566dfd0ba3d15cc495e974f787eb78f1f` (global `uPlot`); `uplot@1.6.32/dist/uPlot.min.css` sha256 `df630c6a8d6f8eeaff264b50f73ce5b114f646ffd9a0bb74f049b0a00135fa04`. | downloaded from unpkg |
| Runtime-verified in a browser: `uPlot.paths` = `points, linear, stepped, bars, spline`; `uPlot.paths.stepped({align:1})` returns a function; `uPlot.sync` and `uPlot.tzDate` are functions; globals `preact.h`, `preactHooks.useState`, `htm.bind` all present. | loaded and evaluated |
| `preact.umd.js` contains `http://www.w3.org/{1999/xhtml,2000/svg,1998/Math/MathML}`; `uPlot.iife.min.js` contains a `https://github.com/leeoniya/uPlot` banner. A naive "no external URL in assets" test fails on both. | grepped |

## Other verified code facts

| Fact | Where |
|---|---|
| `cli.main()` order: `parse_args` → `healthcheck` early-return → `load_config` → `ensure_directories()` → `_configure_logger` → `Store(...)`, `initialize()`, `upsert_provider_configs()` → command dispatch | `cli.py:46-75` |
| `load_config(project_root) -> LoadedConfig` with `.runtime_paths.database_path`, `.settings`, `.providers: tuple[ProviderConfig,...]` (`provider_id,label,kind,base_url,models_path,credential_env_var,price_multiplier,price_divisor,enabled`) | `config.py:18-135` |
| `Settings` really has `report_detail`, `report_show_fields`, `report_squelch_fields`, `report_unclassified_limit` (the `getattr` defaults in `cli._report_detail_policy` are belt-and-braces) | `config.py:34-52` |
| `resolve_profile(kind, price_multiplier=, price_divisor=) -> ProviderProfile`; profile carries `normalized_fields`, `categorize`, `is_price_amount_field`, `is_count_field`, `known_boolean_fields`, `pricing_field_order`, `default_show_fields`, `default_squelch_fields`, `field_path_labels`, `field_leaf_labels` | `provider_profiles.py` |
| `change_render.resolve_field_label(path, profile) -> (label, qualifier)`; `resolve_price_rule(path, profile) -> ResolvedPriceRule(unit_label, multiplier, divisor, comparison_group, normalized_target, match_source)`; `classify_change(FieldChange, *, profile) -> RenderedChange` (fields at `change_render.py:264-292`) | `change_render.py:119,142,1207` |
| `reporting`: `make_report_detail_policy(...)`, `classify_detail_visibility(field_name, policy)`, `_plan_changes_report_provider(models, policy, profile) -> _ChangesProviderPlan(entries, rollups)`, `_PlannedChangeEntry(model_id, display_name, kind, display)`, `_FieldDisplayPlan(visible, squelched, hidden_unclassified, hidden_non_squelched, unclassified_used, noop)`, `_HiddenRollups(squelched, non_squelched, noop)` | `reporting.py:75-145,285-335,947-1000` |
| `Store` methods and signatures: `create_scrape(**10 kwargs) -> int`, `save_snapshot_models(*, scrape_id, provider_id, models)`, `record_field_changes(*, provider_id, from_scrape_id, to_scrape_id, deltas, detected_at)`, `list_known_models(*, provider_id, since, until)` | `storage.py:131-268,444` |
| `diffing.compare_models(...)` is the delta producer; `storage._load_json_value` parses stored JSON | `diffing.py:9`, `storage.py:599` |
| `providers` DB table stores `kind` — so a provider present in history but absent from config can still resolve a profile | schema + queried rows |
| `Store._connect()` opens **read-write** with no busy timeout — the browser must not use it | `storage.py:581` |

---

## Task 0: Fix `Store.recent_changes` performance  **[REVIEW-2]**

**Why this is first and not optional.** The browser's Activity view needs these rows on every request. At ~509 s per call it is unusable. Writing a second, fast query inside `browse/queries.py` would violate the no-duplicate-logic constraint, so the one implementation gets fixed and both callers use it. This also fixes the shipped `changes` command, which pays the same cost today.

**Files:**
- Modify: `model_sentinel/storage.py`
- Modify: `tests/test_storage.py`

**Interfaces:**
- Produces `storage.recent_change_rows(connection: sqlite3.Connection, *, provider_id: str | None, since: date | None, until: date | None) -> tuple[dict[str, Any], ...]` — a module-level function taking a caller-supplied connection so a read-only connection can be used.
- `Store.recent_changes(...)` keeps its exact signature and return value and becomes a thin wrapper: open `self._connect()`, delegate, return.
- Produces `storage.load_json_value(value: str | None) -> Any` as the public name for `_load_json_value` (keep `_load_json_value = load_json_value` alias so nothing breaks).
- **`change_id` is exposed only on `recent_change_rows`** (user decision, 2026-08-23). `Store.recent_changes` strips it, so its output stays byte-identical to today's — same 9 keys (`change_kind, detected_at, display_name, field_name, new_value, old_value, provider_id, provider_label, provider_model_id`), same types, same order. `changes --format json` dumps those rows verbatim (`reporting.py:1427`), so this keeps the shipped artifact unchanged. The browser's Activity endpoint calls `recent_change_rows` directly and gets `change_id`.

**Required query shape** (this is load-bearing; the correlated subquery is the defect):

```sql
WITH latest AS (
  SELECT sm.provider_id, sm.provider_model_id, sm.display_name,
         ROW_NUMBER() OVER (
           PARTITION BY sm.provider_id, sm.provider_model_id
           ORDER BY s.completed_at DESC, s.scrape_id DESC
         ) AS rn
  FROM snapshot_models sm
  JOIN scrapes s ON s.scrape_id = sm.scrape_id
)
SELECT fc.change_id, fc.provider_id, fc.provider_model_id, fc.change_kind,
       fc.field_name, fc.old_value_json, fc.new_value_json, fc.detected_at,
       p.label AS provider_label, l.display_name
FROM field_changes fc
JOIN providers p ON p.provider_id = fc.provider_id
LEFT JOIN latest l
       ON l.provider_id = fc.provider_id
      AND l.provider_model_id = fc.provider_model_id
      AND l.rn = 1
WHERE fc.from_scrape_id IS NOT NULL
  -- optional predicates appended here
ORDER BY fc.detected_at ASC, fc.provider_id, fc.provider_model_id, fc.change_id
```

Notes that must be honored:
- The original ordered by `datetime(fc.detected_at)`. Stored values are ISO-8601 UTC with a fixed format, so plain string ordering is equivalent **and** index-friendly; a test must prove the order is unchanged.
- `LEFT JOIN` (not inner): a model can have change rows and no surviving snapshot row. The original correlated subquery yielded `NULL` in that case; preserve it.
- `provider_id` predicate: `AND fc.provider_id = ?`.
- **Date predicates are a widened UTC pre-filter, not the authority.** `since`/`until` are *local* dates. Compute UTC bounds widened by one day on each side and push those into SQL, then keep the existing exact Python filter on `local_date_for(detected_at)`. This preserves today's exact semantics (including DST) while eliminating the full scan:
  ```python
  if since is not None:
      lo = (datetime.combine(since, time.min) - timedelta(days=1)).isoformat()
      # appended as: AND fc.detected_at >= ?
  if until is not None:
      hi = (datetime.combine(until, time.max) + timedelta(days=1)).isoformat()
      # appended as: AND fc.detected_at <= ?
  ```
  Do **not** delete the Python `local_date_for` filter — it remains the source of truth for boundary rows.

- [ ] **Step 1: Write the equivalence test first.** In `tests/test_storage.py`, build a store with several providers, models, scrapes and changes (including one model that appears in `field_changes` but has no `snapshot_models` row, and rows on local-date boundaries near midnight). Capture `Store.recent_changes(...)` output for several `(provider_id, since, until)` combinations **before** touching the implementation by copying the current method body into the test file as `_legacy_recent_changes(store, ...)`. Assert new output equals legacy output **exactly** — no key dropping, since `Store.recent_changes` must not gain a field — for every combination including `None/None/None`. Add a separate assertion that `recent_change_rows` *does* carry `change_id` and that `set(store_row) == set(raw_row) - {'change_id'}`.
- [ ] **Step 2: Run it — it passes against the unmodified implementation** (this proves the harness is sound). Run: `pytest tests/test_storage.py -k recent_changes -v`.
- [ ] **Step 3: Add a performance guard test.** Build a store with ~300 models × ~20 scrapes and ~2,000 change rows; assert `recent_change_rows` over the whole range completes in under 2 seconds (`time.perf_counter`). Verify this test **fails** against the old implementation before you change it.
- [ ] **Step 4: Implement `recent_change_rows`, rewire `Store.recent_changes`, publish `load_json_value`.**
- [ ] **Step 5: Run both tests plus the full suite.** Run: `pytest`.
- [ ] **Step 6: Verify against the real database, read-only.** `time ./model-sentinel changes --since 2026-08-20 --format json --output /tmp/ms_check.json` — record the before/after wall time in the commit body. Do not run it without `--output` (that writes report artifacts into the runtime home).
- [ ] **Step 7: Commit** `Fix quadratic recent_changes query`.

## Task 1: Fixture DB, read-only database access, `browse` CLI skeleton

**Files:**
- Create: `tests/browse_fixtures.py`, `model_sentinel/browse/__init__.py`, `model_sentinel/browse/readonly.py`, `tests/test_browse_readonly.py`
- Modify: `model_sentinel/cli.py`, `tests/test_cli.py`

**Interfaces — fixture:**
`tests.browse_fixtures.build_fixture_db(path: Path) -> FixtureFacts`. Build **through `Store`** (`initialize`, `upsert_provider_configs`, `create_scrape`, `save_snapshot_models`, `record_field_changes`) and produce the deltas with `diffing.compare_models` so rows are shaped exactly as production writes them. `FixtureFacts` is a frozen dataclass recording what was written, so tests assert against data rather than magic numbers: `provider_ids`, `scrape_ids` (ordered), `scrape_dates` (local `date`s), `model_ids`, `added_model`, `added_at_scrape`, `removed_model`, `removed_at_scrape`, `price_step: (model_id, from_scrape, to_scrape, raw_old, raw_new, canon_old, canon_new)`, `context_step`, `bool_flip`, `bulk_list_models: tuple[str, ...]` (exactly 3), `benchmark_churn_model`.

Content requirements:
- Provider `example-provider`, kind `openrouter` (so the real OpenRouter profile, its `pricing_field_order` and its `benchmarks*` squelch apply), `price_multiplier=1_000_000`, `price_divisor=1`. Second provider `other-provider`, kind `generic`, one model, two scrapes.
- Six saved successful scrapes for `example-provider` on six distinct local dates, plus one `status="error"`, `saved_snapshot=False` scrape. Timestamps ISO UTC, days apart, and **one pair deliberately 20 minutes apart on the same local date** so the "two scans in one day" bucket is exercised.
- Models `fake-org/test-model-a` … `-e`.
- `metadata_json` must carry raw values at the real OpenRouter paths (`pricing.prompt`, `pricing.completion`, `context_length`, `top_provider.max_completion_tokens`, `supported_parameters`, `benchmarks.design_arena.score`), because `/api/series` and catalog diffs read those paths. Canonical columns follow from `normalize`, so build `NormalizedModel`s via `normalize.normalize_models` rather than hand-filling both — that guarantees the raw/canonical relationship is the real one.
- Scripted changes: `-a` `pricing.prompt` `0.000002 → 0.0000035` (canonical `input_price` `2.0 → 3.5`) at scrape 2→3; `-b` `context_length` `128000 → 256000` at 3→4; `-c` `reasoning` false→true at 4→5; `-a`,`-b`,`-c` each gain `reasoning_effort` in `supported_parameters` at 5→6 (identical list delta on exactly 3 models — the bulk case); `-d` added at scrape 4; `-e` removed at scrape 5; `-a` `benchmarks.design_arena.score` changes at every scrape (squelched churn).

**Interfaces — read-only access:**
`model_sentinel.browse.readonly` provides:
- `MissingDatabaseError(path)`, `SchemaError(missing: str)`, `DatabaseBusyError`.
- `class ReadOnlyDatabase` — **one instance per process, one connection per thread.** `ThreadingHTTPServer` handles requests on many threads and a single `sqlite3.Connection` shared across them is not safe even read-only. Hold `threading.local()`; each thread lazily opens its own connection with `sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)`, `row_factory = sqlite3.Row`, then `PRAGMA query_only = ON` and `PRAGMA busy_timeout = 5000`. Expose `connection() -> sqlite3.Connection` and `close_all()`.
- `open_readonly(database_path: Path) -> ReadOnlyDatabase` — raises `MissingDatabaseError` if the file is absent (never creates it), then calls `ensure_schema` on a first connection.
- `ensure_schema(connection)` — verifies the four tables and the columns this project reads (`PRAGMA table_info`); raises `SchemaError(name)` naming the first missing object.
- Any `sqlite3.OperationalError` whose message contains `locked` or `busy` is translated to `DatabaseBusyError` by the query layer (a scan may hold an exclusive lock — journal mode is `delete`, so this is a real concurrent case, not theoretical).

**Interfaces — CLI:**
- `browse` subparser: `--port` (int, default 8110), `--no-open` (store_true), `--provider` (str).
- In `cli.main()`, insert dispatch immediately after `load_config` succeeds and **before** `loaded.runtime_paths.ensure_directories()`:
  ```python
  if args.command == "browse":
      return run_browse_command(args=args, loaded=loaded)
  ```
  `ensure_directories()` creates `logs/` and `reports/`; skipping it is what keeps the "never writes" guarantee true on a machine that has never scanned.
- Because the shared logger is configured after that point, `run_browse_command` configures its own: a `logging.StreamHandler(sys.stderr)` at `WARNING` on the `model_sentinel.browse` logger, `propagate = False`. Do not call `_configure_logger(loaded)` — it opens the rotating log file, which is a write.
- `run_browse_command` validates `--provider` with the existing `config.validate_selected_providers`, calls `open_readonly`, maps `MissingDatabaseError` → `SystemExit(2)` with `Model Sentinel database not found at <path>. Run 'model-sentinel scan --save' first.` and `SchemaError` → `SystemExit(2)` naming the missing object, then delegates to `browse.server.run_browse(...)`. For this task `run_browse` is a stub returning 0.

- [ ] **Step 1:** Write `tests/browse_fixtures.py`; add a test asserting the fixture matches `FixtureFacts` (6 saved + 1 error scrape; the added/removed/bulk/churn rows all present; `-a`'s canonical `input_price` is `2.0` before and `3.5` after, while its metadata `pricing.prompt` is `0.000002`/`0.0000035`).
- [ ] **Step 2:** Write failing tests in `test_browse_readonly.py`: missing path raises `MissingDatabaseError` and creates no file; `PRAGMA query_only` is 1 and `INSERT` raises; `ensure_schema` on a DB with `field_changes` dropped raises `SchemaError("field_changes")`; **two threads each get a distinct connection object** and can query concurrently; the fixture file's SHA-256 is unchanged after a query sweep.
- [ ] **Step 3:** Run them; confirm they fail for the right reason.
- [ ] **Step 4:** Implement `readonly.py`; run; pass.
- [ ] **Step 5:** Write failing CLI tests: `browse --help` exits 0 and mentions `--no-open`; missing DB exits 2 naming the path; with the fixture DB in `MODEL_SENTINEL_HOME` and `Store.upsert_provider_configs` monkeypatched to raise, `browse --no-open` still returns 0 (proving dispatch precedes the writes) and `run_browse` received `open_browser=False`; `ensure_directories` is not called (monkeypatch it to raise). Follow the existing `test_cli.py` env-file setup.
- [ ] **Step 6:** Implement parser, dispatch, `run_browse_command`, epilog example; run; pass.
- [ ] **Step 7:** Full suite; commit `Add browse subcommand skeleton with read-only DB access`.

## Task 2: Aspect catalog  **[REVIEW-3 partial]**

**Files:** Create `model_sentinel/browse/aspects.py`, `tests/test_browse_aspects.py`. Modify `model_sentinel/normalize.py` (publish one helper).

**Interfaces:**
- Publish `normalize.profile_field_candidate(raw_model: dict, profile: ProviderProfile, field_name: str) -> tuple[Any, str | None]` as the public name for `_profile_field_candidate` (keep the private alias). This is how a canonical column is traced back to the raw path **for a specific model**, and Task 4 depends on it.
- `Aspect` (frozen dataclass): `id`, `provider_id`, `source: Literal["column","path"]`, `column: str|None`, `path: str|None`, `field_name: str` (the profile field path used for labels/units), `label`, `qualifier`, `category`, `kind: Literal["price","count","numeric","boolean","list","scalar"]`, `unit: str|None`, `multiplier: int`, `divisor: int`, `squelched: bool`, plus `to_json() -> dict`.
- `build_aspect_catalog(db, *, profiles: dict[str, ProviderProfile], policy: ReportDetailPolicy) -> tuple[Aspect, ...]`.
- Aspect ids: `"{provider_id}:{column}"` and `"{provider_id}:path:{path}"`.

**Load-bearing decisions:**

1. **There is no static column→path map.** `profile.normalized_fields` maps each canonical column to an *ordered candidate list*, and the winner is per model. For the catalog (a per-provider concern) resolve a **representative path** from the data: parse `metadata_json` of the models in the provider's latest saved scrape and pick the first candidate path that any model actually populates; fall back to the first declared candidate when none is populated. Store it as `Aspect.field_name`. Never hardcode `input_price → pricing.prompt`.
2. **Scale.** `source == "column"` price aspects are **already normalized at save time** — set `multiplier = divisor = 1`. `source == "path"` price aspects are raw — take `multiplier`/`divisor` from `resolve_price_rule(field_name, profile)`. Test both; this is the same defect class as [REVIEW-3].
3. **Unit.** Only a price aspect takes `unit = resolve_price_rule(...).unit_label`; for anything else that call returns the misleading `'/unit unknown'`. Use `unit = "tokens"` for `context_window`/`max_output_tokens`, otherwise `None`.
4. **Kind.** Price iff `profile.is_price_amount_field(field_name)`. Boolean iff the path is in `profile.known_boolean_fields`, the column is one of the `*_supported`/`deprecated` columns, or the sampled `json_type` is `true`/`false`. `list` iff `json_type` is `array`. `count` iff `profile.is_count_field(...)`. Else `numeric` for `integer`/`real`, `scalar` for `text`.
5. **Path discovery.** `SELECT DISTINCT provider_id, field_name FROM field_changes WHERE field_name IS NOT NULL` (51 rows on the real DB, 0.006 s). Drop paths whose sampled leaf is an object. Determine `json_type` by sampling the latest snapshot that has a non-null extract.
6. **Path safety.** Reject any path whose segments are not all `^[A-Za-z0-9_\-]+$`; skip the aspect and log at debug. All `json_extract` expressions are built from this whitelisted set — never from user input.
7. **Squelched.** `squelched = classify_detail_visibility(field_name, policy) == "squelched"`. `field_name` is never `None` here (the query filters it), but the helper you write for other call sites must guard — see Task 3.
8. **Order.** Category order `Pricing`, `Context & Limits`, `Capabilities`, `Parameters`, `Benchmarks`, `Other`; within `Pricing`, honor `profile.pricing_field_order` (leaf names) via the existing `change_render.pricing_field_sort_key`; alphabetical otherwise. Deterministic across calls.

- [ ] **Step 1:** Write failing tests on the fixture — `example-provider:input_price` has `kind="price"`, `category="Pricing"`, `unit="/1M tokens"`, `multiplier == 1`, and `field_name == "pricing.prompt"` (resolved from data, not hardcoded); `example-provider:path:pricing.prompt` has `multiplier == 1_000_000`; `…:path:benchmarks.design_arena.score` has `squelched is True`, `category == "Benchmarks"`, `kind == "numeric"`; `…:path:supported_parameters` has `kind == "list"`, `category == "Parameters"`; `context_window` has `unit == "tokens"` and never `"/unit unknown"`; a path containing `$` is skipped; two calls return identical tuples.
- [ ] **Step 2:** Run; confirm failure. **Step 3:** Implement. **Step 4:** Run; pass.
- [ ] **Step 5:** Full suite; commit `Add browse aspect catalog`.

## Task 3: Queries

**Files:** Create `model_sentinel/browse/queries.py`, `tests/test_browse_queries.py`.

**Interfaces** (each takes `connection: sqlite3.Connection` first; each wraps `sqlite3.OperationalError` locked/busy into `DatabaseBusyError`):
- `list_scrapes(connection) -> list[dict]`: `{scrape_id, provider_id, date, completed_at, status, saved, model_count}`, `date` computed in **Python** with `local_date_for` — never SQL `date()`, which is UTC and would mis-bucket evening scans.
- `date_span(connection) -> tuple[date, date] | None` over saved successful scrapes.
- `change_counts_by_date(connection, *, provider_ids, since, until) -> list[dict]`: one row per `(detected_at, provider_id, change_kind, field_name)` group with a count — the raw material for the heatmap. Bucketing to local dates and squelch classification happen in `api.py`, because both need Python (`local_date_for`) and the policy. Use the same widened-UTC-prefilter pattern as Task 0.
- `saved_scrape_ids(connection, *, provider_id, since, until) -> list[dict]` — successful saved scrapes only.
- `series_rows(connection, *, provider_id, scrape_ids, model_ids, columns, paths) -> list[sqlite3.Row]` — one SELECT with a `json_extract` **and** a `json_type` per path; `WHERE scrape_id IN (…) AND provider_model_id IN (…)` with generated `?` placeholders. Column and path identifiers come only from the Task 2 whitelist; values are always bound.
- `events_for_models(connection, *, provider_id, model_ids, since, until) -> list[dict]` — `change_id, detected_at, provider_model_id, change_kind, field_name, old_value, new_value`, JSON parsed with `storage.load_json_value`.
- `catalog_rows(connection, *, scrape_id, columns, paths) -> dict[str, dict]` — every model in the scrape with `display_name`, the requested column values, **and the raw `metadata_json`** (needed by Task 4 to resolve raw price values).
- `search_models(connection, *, provider_ids, query, limit) -> list[dict]` — latest display name per model, case-insensitive substring on id or name.
- `change_by_id(connection, change_id) -> dict | None` — the row plus both scrapes' `{scrape_id, date, completed_at, status}`.
- `db_providers(connection) -> list[dict]` — `provider_id, label, kind, enabled` from the `providers` table, so providers present in history but absent from config are still browsable.

- [ ] **Step 1:** Write failing tests per function against the fixture: scrape list ordering and `saved`/`status`; a scrape whose UTC date differs from its local date buckets to the **local** date; date span; `change_counts_by_date` includes the added/removed dates; `series_rows` returns rows only for scrapes where the model existed; `events_for_models` parses the price step to floats; `catalog_rows` for the last scrape excludes `-e` and includes `metadata_json`; `search_models("model-a")` matches only `-a`; `change_by_id` returns both scrapes and `None` for an unknown id; `db_providers` lists both providers.
- [ ] **Step 2:** Run; fail. **Step 3:** Implement. **Step 4:** Run; pass.
- [ ] **Step 5:** Full suite; commit `Add browse SQL queries`.

## Task 4: Shared helpers, bulk grouping, and the API layer  **[REVIEW-1, REVIEW-3]**

**Files:**
- Modify: `model_sentinel/reporting.py`, `model_sentinel/provider_profiles.py`, `tests/test_reporting.py`
- Create: `model_sentinel/browse/api.py`, `tests/test_browse_api.py`

### 4a. Extract shared helpers (no behavior change)

- `reporting.plan_changes_provider` — public name for `_plan_changes_report_provider`; keep `_plan_changes_report_provider = plan_changes_provider`; update internal call sites at `reporting.py:1510` and `:4805`.
- `reporting.detail_policy_from_settings(settings, *, mode: str | None = None) -> ReportDetailPolicy` — the body of `cli._report_detail_policy`, which then calls it. One implementation.
- `provider_profiles.profiles_for(providers: Iterable[ProviderConfig]) -> dict[str, ProviderProfile]` — the dict comprehension currently inline in `cli.run_changes:509`; `run_changes` calls it afterwards.
- `reporting.visibility_of(field_name: str | None, policy) -> str` — returns `"presence"` when `field_name is None`, else `classify_detail_visibility(...)`. **[REVIEW]** `classify_detail_visibility(None, policy)` raises `TypeError`, and every added/removed row has `field_name = NULL`; every browser call site must go through this guard.

Tests: the public names exist and are identical objects to the private aliases; `detail_policy_from_settings` returns what `cli._report_detail_policy` returned for the same inputs; `visibility_of(None, policy) == "presence"` and does not raise.

### 4b. Bulk grouping for the changes path  **[REVIEW-1]**

The earlier draft claimed the Activity feed inherits bulk consolidation from the `changes` planner. **It does not** — `_plan_changes_report_provider` has no bulk step; bulk lives in the scan planner. The spec's Activity view promises bulk groups, so build it, reusing the existing signature logic rather than inventing a second rule:

- `reporting.group_planned_entries_by_bulk(entries: tuple[_PlannedChangeEntry, ...]) -> tuple[BulkGrouping, ...]` where `BulkGrouping` is a frozen dataclass `{signature, entries: tuple[_PlannedChangeEntry, ...]}`.
- Group only `kind == "changed"` entries whose `_bulk_change_signature(entry.display)` is not `None`; a signature shared by **at least `BULK_CHANGE_MIN_MODELS`** entries becomes one group; everything else stays a singleton group. Import `_bulk_change_signature` and `BULK_CHANGE_MIN_MODELS` — do not re-derive the signature.
- This is additive: no existing renderer calls it, so `changes` output is unchanged. Assert that with a characterization test (`tests/test_render_changes_characterization.py` output identical before/after).

Test on the fixture: at scrape 5→6 the three `supported_parameters` entries form one group of 3; the price step remains a singleton.

### 4c. The API layer

- `api.BadRequest(Exception)`, `api.NotFound(Exception)` (both carry `.message`).
- `api.ApiContext`: `db: ReadOnlyDatabase`, `providers: tuple[ProviderConfig, ...]`, `db_providers`, `profiles: dict[str, ProviderProfile]`, `settings`, `aspects`, `policy_for(detail: str | None) -> ReportDetailPolicy` (via `detail_policy_from_settings`).
  **Providers not in config** (present only in the `providers` table) are included in `meta.providers` with `configured: false`, and their profile resolves via `resolve_profile(db_row["kind"])` with the profile's own default factors. History must not disappear because a provider was removed from `providers.env`.
- `api.parse_common(params) -> Common(providers, since, until, detail)` enforcing spec §7's 400 rules.
- Endpoint functions `(ctx, params) -> dict`: `meta`, `activity`, `heatmap`, `series`, `events`, `catalog`, `change`, `models`.
- `api.rendered_change_to_json(rc) -> dict` = `dataclasses.asdict(rc)`. **[REVIEW]** Measured: this is already JSON-serializable and `price_rule` is already a nested dict; do **not** hand-flatten it. Note for the frontend: the unit key inside `price_rule` is `unit_label`, while the top-level field is `unit`.

**`meta`** additionally returns `categories` (the ordered category list) explicitly — the client must not have to infer facets from the aspect list — plus `date_span`, `scrapes`, `aspects`, `detail_default`, `pin_limit: 8`, `bulk_min_models`.

**`activity`** — the flow, precisely:
1. `recent_change_rows(conn, provider_id=…, since=…, until=…)` per selected provider (Task 0 made this fast).
2. Bucket by local date (`local_date_for(detected_at)`), then provider, then model — the same nesting `render_changes_report` builds at `reporting.py:1463`.
3. `plan_changes_provider(models, policy, profile)` per (provider, date) bucket.
4. `group_planned_entries_by_bulk(plan.entries)`.
5. Serialize: for a singleton, one entry with `changes = [rendered_change_to_json(classify_change(fc, profile=profile)) for fc in display.visible]`; for a bulk group, one entry with `kind: "bulk"`, the shared `changes`, and `bulk_models: [{model_id, display_name}, …]`.
6. `hidden` counts from `len(display.squelched)`, `len(display.hidden_unclassified)`, `len(display.noop)`; `rollups` from `plan.rollups`.
7. **`change_ids`**: build `{(model_id, field_name): [change_id, …]}` from the source rows of that bucket and attach every matching id (a model can have several rows for one field in one bucket when two scans ran the same day — the fixture has such a pair). Do not assume one id.
8. Apply `models`, `categories` (via `profile.categorize(fc.field_name)`), `kinds` filters **after** planning, drop entries left with nothing, then page. Sort newest date first, then provider, then model.

**`heatmap`** — bucket `change_counts_by_date` rows to local dates in Python; classify each distinct `field_name` once with `visibility_of` and sum; return `[{date, changed, added, removed, squelched}]`.

**`series`** — validate ≤8 models, ≤12 aspects, known ids. **[REVIEW]** The earlier draft returned a single `scrapes` list while grouping by provider — incoherent when pins span providers. Build a **union time axis**: collect the saved scrapes of every provider involved, sort by `completed_at`, and emit
```
{"axis": [{scrape_id, provider_id, date, completed_at, t}, …],
 "series": [{model, aspect, provider_id, kind, unit, values: [v|null…], list_hash: [h|null…]}]}
```
with each series aligned to the union axis and `null` at every index belonging to another provider or to a scrape where the model was absent. `null` means "not present", never zero; the chart breaks the line there (`spanGaps: false`).
Values: column price aspects as stored (already normalized); path price aspects `× multiplier / divisor`; booleans `0/1`; lists → length, with `list_hash[i] = sha1(json.dumps(sorted(members)))[:8]`.
**Test the no-double-scaling rule explicitly**: the `example-provider:input_price` series equals the stored `input_price` column values, and equals the `…:path:pricing.prompt` series — proving one scaling, not two.

**`catalog`** — `as_of`/`compare` must be saved successful scrapes of the provider, `compare` strictly earlier. **[REVIEW-3] Diff cells must be built from raw values, never canonical columns.** Measured: feeding the canonical `2.0 → 3.5` into `classify_change` yields `$2000000.00 → $3500000.00`. For each price aspect and each model, resolve the raw pair by calling `normalize.profile_field_candidate(json.loads(metadata_json), profile, column)` on both snapshots and pass those to `classify_change`. For non-price aspects the stored value is already raw. Assert `old_display == "$2.00"` and `new_display == "$3.50"` for the fixture step, and assert the cell's rendering is **identical** to `classify_change` on the real `field_changes` row for that same change.
Sorting: any returned column, nulls last, default `model_id`.

**`change`** — `NotFound` when missing.

- [ ] **Step 1:** Implement 4a; add its tests; run; pass; commit `Extract shared reporting and profile helpers`.
- [ ] **Step 2:** Write the bulk-grouping test (including the characterization test proving `changes` output is byte-identical); run; fail; implement 4b; run; pass; commit `Add bulk grouping for planned change entries`.
- [ ] **Step 3:** Write failing API tests: every `parse_common` 400 case; each endpoint's shape; activity entry counts and the bulk group asserted **against `FixtureFacts`**, not against another call to the planner (a test that compares the planner to itself proves nothing); heatmap squelched ≥1 on a churn date; series no-double-scaling and union-axis nulls; catalog price displays and presence marks; change 404; a provider present only in the DB still appears in `meta`.
- [ ] **Step 4:** Implement `api.py`; run; pass. **Step 5:** Full suite; commit `Add browse JSON API layer`.

## Task 5: Vendored assets, page shell, CSS tokens, theme  **[REVIEW-4]**

**Files:** Create `model_sentinel/browse/assets/{index.html,app.css}`, `assets/vendor/*`, `tests/test_browse_offline.py`, `tests/test_browse_theme.py`.

**Vendoring — pinned and hashed.** Download exactly these, verify each sha256 against the table in "Measured facts", and record version, URL and hash in `vendor/VERSIONS.md`. If a hash does not match, stop and report; do not proceed with an unverified file.

| File | Source | Global |
|---|---|---|
| `preact.umd.js` | `https://unpkg.com/preact@10.29.8/dist/preact.umd.js` | `preact` |
| `hooks.umd.js` | `https://unpkg.com/preact@10.29.8/hooks/dist/hooks.umd.js` | `preactHooks` |
| `htm.umd.js` | `https://unpkg.com/htm@3.1.1/dist/htm.umd.js` | `htm` |
| `uPlot.iife.min.js` | `https://unpkg.com/uplot@1.6.32/dist/uPlot.iife.min.js` | `uPlot` |
| `uPlot.min.css` | `https://unpkg.com/uplot@1.6.32/dist/uPlot.min.css` | — |

Also fetch each package's `LICENSE` into `vendor/` (`preact.LICENSE`, `htm.LICENSE`, `uplot.LICENSE`). Load order in `index.html`: theme stamp script → `uPlot.min.css` → `app.css` → `preact.umd.js` → `hooks.umd.js` → `htm.umd.js` → `uPlot.iife.min.js` → `app.js`. (`hooks.umd.js` requires `preact` to be loaded first.)

**[REVIEW-4] The offline test must not scan vendor file bodies.** Measured: `preact.umd.js` contains three `http://www.w3.org/…` XML namespace URIs and `uPlot.iife.min.js` carries a `https://github.com/leeoniya/uPlot` license banner. These are identifiers and attribution, not network fetches; a naive scan fails on correct files. The test therefore has two distinct parts:
1. **Our assets** (`index.html`, `app.css`, `app.js`): strip `/* … */` and `// …` comments, then assert no `http://`, `https://` or protocol-relative `//` URL remains, allowing only `http://www.w3.org/2000/svg` when used as an SVG namespace attribute.
2. **Vendor files**: verified by **sha256 against `VERSIONS.md`**, not by content scanning.
3. **References**: every `src`/`href` in `index.html` is a relative path that resolves under `assets/` through `importlib.resources`.

**`app.css`.** Tokens per spec §6.6. Reuse the existing HTML report's hex values for ground/panel/ink and the cost colors so the browser and the reports match — read them out of `reporting.py`'s inlined CSS rather than inventing new ones. Semantic tokens: `--cost-up`, `--cost-down`, `--capacity`, `--capability`, `--dim`, `--presence-added`, `--presence-removed`, `--accent`, `--heat-0…3`, `--series-1…8`. Every token defined on bare `:root` (complete light palette), redefined under `@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]) }` and again under `:root[data-theme="dark"]`. `prefers-reduced-motion` block; visible `:focus-visible`.

- [ ] **Step 1:** Write `test_browse_offline.py` and `test_browse_theme.py` per the rules above (theme test: every custom property set in a media/`[data-theme]` block is also on bare `:root`; the dark media block is guarded with `:root:not([data-theme="light"])`; `index.html` carries the pre-paint stamp script reading `model_sentinel.browse.theme` before the first `<link>`).
- [ ] **Step 2:** Download and hash-verify the vendor files; write `VERSIONS.md`, `index.html`, `app.css`.
- [ ] **Step 3:** Run both tests; pass. **Step 4:** Full suite; commit `Vendor Preact, htm and uPlot; add offline shell and theme tokens`.

## Task 6: HTTP server

**Files:** Create `model_sentinel/browse/server.py`, `tests/test_browse_server.py`. Modify `cli.py` to call the real `run_browse`.

**Interfaces:**
- `find_free_port(start_port: int, max_attempts: int = 20) -> int` — repo convention, binds `127.0.0.1`; raises `RuntimeError` naming the range. **`start_port == 0` is a special case**: return 0 and let the server bind an ephemeral port; the caller reads the real port from `server.server_address[1]`. Without this, `find_free_port(0)` "succeeds" on port 0 and the reported port is wrong.
- `make_server(ctx, *, host="127.0.0.1", port) -> ThreadingHTTPServer` with `daemon_threads = True`.
- `run_browse(*, db, loaded, port, open_browser, initial_provider) -> int` — builds profiles via `profiles_for`, the policy, the aspect catalog and the `ApiContext`; resolves the port (warn via the browse logger when it differs); starts the server; prints exactly one machine-readable line `Model Sentinel browser: http://127.0.0.1:<port>/` (tests parse it — do not change the shape casually); opens the browser inside `try/except Exception` (a headless box must not crash the server), appending `#providers=<initial_provider>` when given; `serve_forever()` until `KeyboardInterrupt`; then `shutdown()`, `server_close()`, `db.close_all()`; returns 0.

**Handler rules:**
- Parse with `urllib.parse.urlsplit(self.path)`; query via `parse_qs`.
- **Host header check**: reject with 403 unless `Host` is `127.0.0.1:<port>` or `localhost:<port>`. This blocks DNS-rebinding, where a public page in the user's browser scripts requests to their local server. Cheap and worth it.
- Static: `/` and `/index.html` → `index.html`; `/app.js`, `/app.css`, `/vendor/<name>`. Reject any segment not matching `^[A-Za-z0-9_.\-]+$` or containing `..` with 404. Read via `importlib.resources.files("model_sentinel.browse")` chaining single `joinpath` calls (`.joinpath("assets").joinpath(name)`) — multi-argument `joinpath` on `Traversable` is not reliable across 3.11/3.12.
- API: `/api/<name>` and `/api/change/<int>`.
- Error mapping: `BadRequest` → 400, `NotFound` → 404, `DatabaseBusyError` → 503 with `{"error": "The database is busy — a scan may be writing. Try again in a moment."}`, anything else → 500 `{"error": "internal error: <ExceptionType>"}` plus `logging.exception`. Never leak a traceback to the client.
- Headers: JSON `application/json; charset=utf-8`; static typed by extension; `Cache-Control: no-store` on everything; no CORS headers.
- `do_POST` (and any other verb) → 405.
- Override `log_message` to `logging.debug` so the terminal stays clean.

- [ ] **Step 1:** Write failing tests: `find_free_port` returns the start port when free, the next when held, and 0 for 0; a server on an ephemeral port serves `/` as `text/html` referencing `app.js`, `/app.css` as `text/css`, every `/vendor/<file>` 200, `/vendor/../cli.py` 404, `/api/meta` with `pin_limit == 8` and non-empty `aspects`, `/api/activity?from=bad` 400 with `error`, `/api/change/999999` 404, `/api/nope` 404, `POST /api/meta` 405, a request with `Host: evil.example` 403; concurrent requests from 4 threads all succeed (exercises the per-thread connections); fixture SHA-256 unchanged after the sweep.
- [ ] **Step 2:** Run; fail. **Step 3:** Implement `server.py`; wire `run_browse_command`.
- [ ] **Step 4:** Extend `test_cli.py`: with `serve_forever` monkeypatched to raise `KeyboardInterrupt`, the command returns 0 and prints the URL line; `webbrowser.open` is not called with `--no-open`, is called once without it, and a raising `webbrowser.open` still returns 0.
- [ ] **Step 5:** Run; pass; full suite; commit `Add browse HTTP server and static/API routing`.

## Task 7: Frontend shell, hash state, Activity view

**Files:** Create `model_sentinel/browse/assets/app.js`; extend `app.css`.

Single IIFE: `const {h, render} = preact; const {useState, useEffect, useMemo, useRef, useCallback} = preactHooks; const html = htm.bind(h);`

- `hashState.read()/write(partial)` — keys per spec §6.1; list values comma-joined with `encodeURIComponent` per item; `pins` as `provider/model`. Defaults from `/api/meta`: `view=activity`, all providers, `from = max(last − 30d, first)`, `to = last`, `detail = meta.detail_default`. `useHashState()` subscribes to `hashchange`. The hash is the single source of truth; theme is deliberately **not** in it.
- `api.get(path, params)` → throws `ApiError(message)` on non-2xx; `useApi()` keeps the previous `data` on error so the page never blanks (spec §7).
- `App` → `FilterBar` (view tabs, provider chips, date inputs clamped to `meta.date_span`, detail control, **theme control** System/Light/Dark writing `localStorage` + `data-theme`, with a `matchMedia` listener that forces a re-render while on System so charts re-read tokens), `ErrorBanner`, view switch, `RawDrawer` (`/api/change/{id}`; rendered summary + raw JSON in `<pre>`; both scrapes; `Esc` closes).
- Activity: `Heatmap` (cells ending at `to`, 4 intensity steps from `--heat-*`, click sets `from=to=date`, drag sets a range, presence dots), `Facets` (providers, `meta.categories`, kinds, detail), `Feed` (date blocks → entries; `changed` entries as a compact table of label+qualifier, `old_display → new_display`, `delta_display`, `pct_display`, `unit`).
- **Color mapping, from `RenderedChange`** — `semantic == "cost"` → `--cost-up`/`--cost-down` by `direction`; `"capacity"` → `--capacity`; `"capability"` and list additions → `--capability`; list removals, `"neutral"` and `"coverage"` → `--dim`; presence entries → `--presence-added`/`--presence-removed`. Never colour a non-cost change red or green.
- Bulk entries render the shared change once with an expandable `bulk_models` list. The per-block rollup line reads `N squelched changes hidden (field, field, …) — show` and flips `detail=all`.
- Model-name click → Models view with the pin added (cap 8, oldest dropped, toast naming it) and `from/to` centred ±30 days.
- Keyboard: `/` focuses the typeahead (Models view), `1/2/3` switch views, `Esc` closes overlays.

**Manual verification** (no JS test runner; record observations in the commit body): seed a temp `MODEL_SENTINEL_HOME` with the template env files and a copy of the fixture DB, run `./model-sentinel browse --no-open`, and confirm in a browser: heatmap renders; the feed shows the price step as `$2.00 → $3.50` in the cost-up colour; the bulk entry lists exactly 3 models; the rollup toggle works; `RawDrawer` opens; all three theme states are readable; the hash round-trips across reload.

- [ ] Implement; re-run `test_browse_offline.py` (it now covers `app.js`); full suite; commit `Add browse frontend shell and Activity view`.

## Task 8: Models view

**Files:** `app.js`, `app.css`.

- `Pins` with `--series-1…8` swatches and a debounced (150 ms) typeahead on `/api/models`; cap 8 with a toast.
- `AspectPicker` grouped by `meta.categories` in order, squelched aspects (benchmarks) inside a collapsed `<details>` — first-class but not shouting.
- `PanelStack`: one panel per selected aspect over the **union axis** from `/api/series`.
  - `price`/`count`/`numeric` → uPlot, `scales.x.time = true`, x = `completed_at` epoch seconds, one series per pin, `paths: uPlot.paths.stepped({align: 1})` (runtime-verified present in 1.6.32), `spanGaps: false`, stroke from the pin token, y-axis label = `unit`, `cursor.sync.key = "ms-browse"`, and a debounced `setScale` hook on x that writes `from/to` back to the hash.
  - `boolean`/`list` → `StateStrip`: one row per pin, one segment per axis point, `--capability` for true, `--dim` for false, transparent for null; list segments alternate two tints on each `list_hash` change; hover shows the value. Height 56 px.
- `EventRail` from `/api/events`, positioned by date across the same range, coloured by `semantic`/`direction`, squelched at 40% opacity, click → `RawDrawer`, hover → `setCursor` across panels via the sync key.
- Re-create uPlot instances on theme change (key the panels on the theme value) so token colours are re-read.
- Legend hover emphasises a series in every panel via `u.setSeries(idx, {focus: true})`.

**Manual verification:** pin `-a` and `-b` with Input price and Context window — `-a` steps at the price date, `-b` steps at the context date; pin `-d` and confirm a gap before its added date rather than a line from zero; the rail shows benchmark churn dimmed; drag-zoom updates the hash and carries into Activity.

- [ ] Implement; full suite; commit `Add browse Models view with stepped timelines and event rail`.

## Task 9: Catalog view and cross-links

**Files:** `app.js`, `app.css`.

- `Pickers`: provider select; `as_of` and `compare` listing saved successful scrapes (`date · N models`), `compare` limited to earlier ones, with a "none" option.
- `ColumnChooser` over the provider's aspects; default = canonical price/limit/capability set.
- `Table`: sticky header, sortable, `tabular-nums`, `q` filter; diff cells show `old_display → new_display` coloured from the cell's `RenderedChange`; presence rows carry a `--presence-*` left stripe; pager.
- `SparklinePopover` on a numeric cell: a small uPlot (height 80) from `/api/series` over the full span, with "Open timeline" → Models view pinned to that model and aspect.
- "Show as feed" → Activity bounded to the two scrapes' dates.

**Manual verification:** as-of the last scrape lists the models minus `-e`; comparing to scrape 2 highlights the price, context and boolean changes and marks `-d` added, `-e` removed; sorting by input price works; the sparkline opens; all three cross-links land on the expected hash.

- [ ] Implement; full suite; commit `Add browse Catalog view with diff and cross-links`.

## Task 10: Installer and standalone packaging

**Files:** `install_standalone.sh`, `tests/test_install_standalone.py`.

- `stage_zipapp_source`: after copying `model_sentinel/*.py`, `cp -R "$SCRIPT_DIR/model_sentinel/browse" "$STAGING_DIR/model_sentinel/browse"`, then prune `__pycache__` directories and `*.pyc` from the staging tree.
- `SOURCE_HASH`: drop the `-name '*.py'` filter so every staged file is hashed; keep the `_packaged_build.py` exclusion. Re-read the rest of the script and confirm nothing else assumes a Python-only tree.
- Tests: the built zipapp's `namelist()` contains `model_sentinel/browse/assets/index.html`, `app.js`, `app.css` and every vendor file and LICENSE; editing `app.css` in the copied project makes `--check` report `stale` (mirror the existing source-drift test); and an **end-to-end packaging test** — run the built target as a subprocess with `MODEL_SENTINEL_HOME` pointed at a seeded temp home containing the fixture DB and template env files plus `browse --no-open --port 0`, parse the printed `Model Sentinel browser: http://127.0.0.1:<port>/` line, fetch `/` and `/api/meta` with `urllib.request`, assert 200 and `pin_limit == 8`, then terminate. This is the only proof that `importlib.resources` reads assets from inside a zipapp.

- [ ] Write failing tests; modify the installer; run; pass; full suite; commit `Package browse assets in the standalone zipapp`.

## Task 11: Documentation and final verification

**Files:** `README.md`, `docs/DESIGN.md`, `vendor/VERSIONS.md`, `cli.py` epilog.

- README: Status bullet; a `### Browse History` section under Commands (command, three views, read-only/offline guarantees, keyboard shortcuts, theme); the Help list. Note that `browse` needs `providers.env`/`settings.env` and an existing database.
- `docs/DESIGN.md`: a short "History browser" subsection linking the spec.
- Also document the Task 0 fix in README (the `changes` command is now fast) — a user-visible behaviour change deserves a line.

- [ ] Update docs.
- [ ] **Duplicate-logic exit check:** grep for `resolve_profile(`, `make_report_detail_policy(`, `detail_policy_from_settings`, `profiles_for`, `json_extract`, `fnmatch`, `ROW_NUMBER`, `query_only`, `Content-Type` — each semantic pattern must exist in exactly one implementation site (plus tests).
- [ ] **Run the complete suite:** `source .venv/bin/activate && pytest`. Report every failure by name with its output; fix before proceeding. Do not summarise a run with failures as "mostly passing".
- [ ] **Verify tracking:** `git ls-files model_sentinel/browse tests | sort` — every new file including `vendor/*` is tracked; confirm no `.gitignore` rule drops `*.min.js`/`*.min.css`.
- [ ] Leave the installed standalone at `~/Library/Scripts/model-sentinel` alone unless the user asks for a rebuild; if you do not rebuild, say so explicitly in the final report.
- [ ] Commit `Document model-sentinel browse`.

## Decisions on record (2026-08-23, approved by the user)

- **Task 0 is in scope.** Fixing `Store.recent_changes` ships as part of this work. It is required: the browser needs the same rows per request, and a second query would duplicate logic.
- **`change_id` is exposed only on `recent_change_rows`.** `Store.recent_changes` and therefore `changes --format json` are unchanged.

## Open items the implementer must not silently decide

1. **Vendor download requires one-time network access.** If the executing environment is offline, Task 5 blocks. Stop and report; do not substitute different libraries or versions, and do not fall back to a CDN.

## Self-review against the spec

- §1 decisions → Tasks 1 (read-only, dispatch), 5 (offline, vendored, theme), 7–9 (views, pin cap), 2 (benchmarks first-class + squelched flag).
- §3 CLI → Tasks 1, 6. §4 layout → all. §5 endpoints → Tasks 3, 4, 6; §5.1 aspects → Task 2. §6.1–6.5 → Tasks 7–9; §6.6 → Tasks 5, 7, 8. §7 errors → Tasks 1, 4, 6, 7 (plus the 503 busy path, which the spec did not anticipate). §8 → Task 10. §9 tests → every task. §10 docs → Task 11.
- **Spec amendments are already applied** (2026-08-23), so spec and plan agree and the executor can trust either: §2 records the storage fix as an in-scope prerequisite; §3 names `ensure_directories`/`_configure_logger` as writes and specifies per-thread connections; §5 `/api/meta` returns `categories`, `bulk_min_models` and DB-only providers; `/api/activity` sources from `recent_change_rows` and gains `kind: "bulk"` with `bulk_models`; `/api/heatmap` uses `visibility_of` and Python-side local bucketing; `/api/series` returns a union `axis`; `/api/catalog` requires raw values; §7 gains the 503 busy response.
- Names used consistently throughout: `recent_change_rows`, `load_json_value`, `profile_field_candidate`, `open_readonly`, `ReadOnlyDatabase`, `DatabaseBusyError`, `build_aspect_catalog`, `Aspect`, `plan_changes_provider`, `detail_policy_from_settings`, `profiles_for`, `visibility_of`, `group_planned_entries_by_bulk`, `ApiContext`, `BadRequest`, `NotFound`, `rendered_change_to_json`, `find_free_port`, `make_server`, `run_browse`, `run_browse_command`, `build_fixture_db`, `FixtureFacts`.
