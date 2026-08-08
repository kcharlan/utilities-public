# Consistent Pricing Field Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every human-readable Model Sentinel report a stable, provider-defined Pricing-field order, with OpenRouter rendering Input first, cache variants next, and Output after them regardless of each field's price movement.

**Architecture:** Add declarative Pricing-field ordering metadata to `ProviderProfile` and resolve it through one format-neutral sort-key helper beside the existing field-label resolver. Apply that key at the shared category-grouping boundary and carry the already-computed key into HTML summary entries, eliminating the scan HTML card's private impact sort without changing page-level model ranking, price-movement calculations, history chronology, stored data, or JSON output.

**Tech Stack:** Python 3.11+ standard library, frozen dataclasses, pytest, self-contained HTML.

---

## Context and resolved decisions

The current behavior is deterministic but has three independent policies:

- `model_sentinel/diffing.py::_diff_values` emits raw provider paths in lexicographic key order.
- `model_sentinel/reporting.py::_group_field_changes_for_detail` preserves that arrival order for most human report bodies.
- `model_sentinel/reporting.py::_pricing_rows_by_impact` reorders only scan HTML card Pricing rows by descending absolute price delta.
- `model_sentinel/reporting.py::_summary_entry_sort_key` independently alphabetizes summary rows by display label.

The implementation must replace those competing *human presentation* policies with one provider-owned order. The approved scope is intentionally narrower than a global field-order redesign:

1. Pricing fields get a shared fixed order across models and human report surfaces.
2. Category order remains `Pricing`, `Context & Limits`, `Parameters`, `Capabilities`, `Benchmarks`, `Other`, then `Unclassified` where applicable.
3. Non-Pricing field order remains unchanged in report bodies; HTML summaries retain their current alphabetical fallback for non-Pricing rows.
4. Model cards across the page remain ranked by overall price impact (`_model_price_impact` / F2). The Price Movement card, headline movers, tallies, and direction buckets also remain impact-based.
5. `history` remains chronological. Reordering events by field would break its time-series meaning.
6. JSON remains full-fidelity and preserves `ModelDelta.field_changes`; SQLite records and diff generation are untouched.
7. The concise and `_full.html` scan reports use the same renderer and therefore must receive the same Pricing order.
8. The provider order is keyed by raw field identity, never by a user-facing label, numeric delta, substring heuristic, or dictionary insertion order.

### OpenRouter's initial Pricing order

Add one explicit tuple to `provider_profiles.py`:

1. `prompt` — Input
2. `input_cache_read` — Cache read
3. `input_cache_write` — Cache write
4. `input_cache_write_1h` — Cache write (1h)
5. `input_audio_cache` — Audio cache
6. `completion` — Output

These are leaf identities deliberately: conditional paths such as `pricing.overrides[min_prompt_tokens=200000].prompt` and `.completion` must inherit the same rank as their base fields. Within one rank, the base field sorts before qualified variants through the deterministic display-label/raw-path tie-breakers.

Do not speculate about semantic placement for media, web-search, request, internal-reasoning, or future provider fields. Ranked fields come first; all unranked Pricing fields follow in case-insensitive display-label order, with raw path as the final deterministic tie-breaker. Future registered profiles can opt into their own tuple without changing shared reporting code. `GENERIC_PROFILE` has an empty tuple and therefore uses the deterministic unranked fallback for every Pricing field.

### Required sort-key contract

Add `pricing_field_order: tuple[str, ...] = ()` to `ProviderProfile`. Add the type alias `PricingFieldSortKey = tuple[int, int, str, str]` and the function signature `pricing_field_sort_key(field_path: str, profile: ProviderProfile) -> PricingFieldSortKey` in `change_render.py`.

The helper must reuse `_split_field_path`; do not introduce a second bracket parser. Resolve configured keys exact bare path first, then bare leaf, matching the existing field-label precedence. Return a key with these semantics:

```text
(
    0 for configured / 1 for unranked,
    configured tuple index (0 for unranked),
    qualified display label, case-folded,
    original raw field path, case-folded,
)
```

This exact configured/unranked discriminator is load-bearing: using only `len(profile.pricing_field_order)` as an unranked rank would collide with a future explicitly ranked item if the representation changes, while matching substrings such as `"cache"` would silently claim unrelated future fields.

## File map

- `model_sentinel/provider_profiles.py`
  - Extend `ProviderProfile` with immutable Pricing-order metadata.
  - Define OpenRouter's six-key tuple and bind it in `OPENROUTER_PROFILE`.
  - Leave `GENERIC_PROFILE` empty.
- `model_sentinel/change_render.py`
  - Add the single raw-path-to-presentation-sort-key resolver beside `_split_field_path` and `resolve_field_label`.
- `model_sentinel/reporting.py`
  - Sort only Pricing groups in `_group_field_changes_for_detail`.
  - Delete `_pricing_rows_by_impact` and its scan-HTML-only call.
  - Carry a precomputed Pricing sort key in `_SummaryEntry` and use it in `_summary_entry_sort_key`.
- `tests/test_provider_profiles.py`
  - Pin profile defaults, OpenRouter ordering metadata, and `with_pricing` preservation.
- `tests/test_change_render.py`
  - Pin exact/leaf resolution, conditional paths, unranked fallback, and non-heuristic behavior.
- `tests/test_reporting.py`
  - Pin cross-model and cross-format ordering while preserving page-level model impact ranking and JSON fidelity.
- `tests/test_render_characterization.py`
  - Update scan text, Markdown, and HTML goldens only after reviewing their intentional Pricing-row permutations.
- `tests/test_render_changes_characterization.py`
  - Update the HTML Change Summary golden and commentary where the new shared order changes it.
- `README.md`
  - Replace the statement that card Pricing rows are impact-sorted; retain impact-ranked model cards.
- `docs/DESIGN.md`
  - Record provider-owned Pricing presentation order in the Reporting section.
- `docs/report_readability_redesign_design.md`
  - Amend the implemented historical design to state that fixed semantic row order supersedes C1's row-level delta sort while F2 page-level impact sorting remains.

## Task 1: Add provider-owned ordering metadata and its resolver

**Files:**

- Modify: `model_sentinel/provider_profiles.py` (`ProviderProfile`, OpenRouter registry constants, `OPENROUTER_PROFILE`)
- Modify: `model_sentinel/change_render.py` (`_split_field_path` / `resolve_field_label` area)
- Test: `tests/test_provider_profiles.py`
- Test: `tests/test_change_render.py`

- [ ] **Step 1: Write failing provider-profile tests**

Add focused assertions that:

- `GENERIC_PROFILE.pricing_field_order == ()`.
- `OPENROUTER_PROFILE.pricing_field_order` is exactly the six-key tuple specified above.
- `resolve_profile("OPENROUTER", price_multiplier=1_000_000, price_divisor=2)` preserves the same tuple when `with_pricing` returns the bound copy.
- The tuple contains no display strings (`"Input"`, `"Output"`) and no broad pattern keys (`"cache"`); it contains only the stated raw leaf identities.

- [ ] **Step 2: Run the provider-profile tests and verify the expected failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_provider_profiles.py -v
```

Expected: FAIL because `ProviderProfile` does not yet expose `pricing_field_order`.

- [ ] **Step 3: Add the immutable profile field and OpenRouter tuple**

Add `pricing_field_order: tuple[str, ...] = ()` to the frozen dataclass. Define a named `_OPENROUTER_PRICING_FIELD_ORDER` constant beside the label registries and pass it to `OPENROUTER_PROFILE`. Rely on `dataclasses.replace` in `with_pricing` to retain it; do not add custom copying logic.

- [ ] **Step 4: Run the provider-profile tests**

Run the command from Step 2.

Expected: all tests in `tests/test_provider_profiles.py` PASS.

- [ ] **Step 5: Write failing sort-key tests**

In `tests/test_change_render.py`, add tests covering all of these cases:

- Deliberately shuffled `pricing.completion`, `pricing.prompt`, `pricing.input_cache_read`, `pricing.input_cache_write`, `pricing.input_cache_write_1h`, and `pricing.input_audio_cache` sort into the approved tuple order.
- `pricing.prompt` sorts before `pricing.overrides[min_prompt_tokens=200000].prompt`, and both sort before cache and Output fields.
- `pricing.overrides[min_prompt_tokens=200000].completion` receives Output's configured rank.
- Exact configured paths take precedence over leaf keys using a synthetic `ProviderProfile`; this pins the resolver contract even though OpenRouter currently uses leaves for the six keys.
- An unranked field such as `pricing.audio` sorts after all configured fields.
- Two unranked fields sort by qualified display label, then raw path.
- A similarly named field such as `pricing.prompt_surcharge` remains unranked; no prefix, substring, or regex inference is allowed.
- `GENERIC_PROFILE` produces deterministic label/path fallback ordering without borrowing OpenRouter's tuple.

- [ ] **Step 6: Run the sort-key tests and verify failure**

Run the exact new test node IDs:

```bash
./.venv/bin/python -m pytest \
  tests/test_change_render.py::test_pricing_field_sort_key_uses_profile_order \
  tests/test_change_render.py::test_pricing_field_sort_key_resolves_conditional_leaf \
  tests/test_change_render.py::test_pricing_field_sort_key_keeps_unranked_fields_deterministic \
  tests/test_change_render.py::test_pricing_field_sort_key_does_not_infer_similar_names \
  -v
```

Expected: FAIL because `pricing_field_sort_key` does not exist.

- [ ] **Step 7: Implement the shared resolver**

Implement the exact sort-key contract above in `change_render.py`. Reuse `_split_field_path` and `resolve_field_label`; the qualified display label used by the key must be produced by `format_qualified_label`, not rebuilt locally. The helper must not call `classify_change`, inspect values/deltas, or categorize the field; it answers only how a raw field path is ordered under one profile.

- [ ] **Step 8: Run focused and module tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_provider_profiles.py tests/test_change_render.py -v
```

Expected: all tests PASS.

- [ ] **Step 9: Run the complete suite, review, and commit Task 1**

Run `./.venv/bin/python -m pytest` and require a clean pass before committing. Before staging, inspect `git diff`. Stage only the four Task 1 files, inspect the complete staged file list and staged diff for sensitive data, then commit with a message such as:

```text
Add provider-defined pricing field order
```

All new fixtures must use conspicuously synthetic providers, model IDs, and values.

## Task 2: Apply the shared order to every human report body

**Files:**

- Modify: `model_sentinel/reporting.py` (`_group_field_changes_for_detail`, `_pricing_rows_by_impact`, `_render_html_card_table`)
- Test: `tests/test_reporting.py`

- [ ] **Step 1: Replace the HTML-only impact-order test with a cross-model fixed-order test**

Rename `test_html_card_sorts_pricing_rows_by_absolute_impact` to describe provider-defined order. Expand the fixture to at least two synthetic models whose delta magnitudes would demand opposite orders under the old implementation:

- Model A: Output delta larger than Input delta.
- Model B: Input delta larger than Output delta.
- Include a cache field and intentionally shuffle each model's `FieldChange` tuple differently.

Assert that each model renders Input, cache, Output in the same order. Parse each model card independently so one model's rows cannot satisfy another model's assertion.

- [ ] **Step 2: Add cross-format scan-report tests**

For the same synthetic data, assert the ordered Pricing labels in scan text, Markdown, and HTML. The test must prove a permutation, not mere presence: collect the ordered labels or compare their indexes inside each model block. Add a JSON control assertion showing that each model's `field_changes` array retains the fixture/source order and raw paths.

- [ ] **Step 3: Add `changes` report body tests**

Construct synthetic storage-shaped change rows for one provider/model with deliberately shuffled Input, cache, and Output paths. Assert the same order in `render_changes_report(format_name="text", ...)` and the model card portion of `render_changes_report(format_name="html", ...)`. Pass `provider_profiles={"synthprov": OPENROUTER_PROFILE.with_pricing(1_000_000, 1)}` so the test proves profile threading rather than an OpenRouter global.

- [ ] **Step 4: Run the focused tests and verify failure**

Run:

```bash
./.venv/bin/python -m pytest \
  tests/test_reporting.py::test_html_cards_use_profile_pricing_field_order_across_opposite_impacts \
  tests/test_reporting.py::test_human_scan_reports_use_profile_pricing_field_order \
  tests/test_reporting.py::test_changes_report_uses_profile_pricing_field_order \
  -v
```

Expected: FAIL. The two scan HTML models still differ because `_pricing_rows_by_impact` uses their deltas; text/Markdown/changes still preserve source order.

- [ ] **Step 5: Sort Pricing once at the shared grouping boundary**

In `_group_field_changes_for_detail`, retain the existing category construction and category order. For each returned category:

- if the final category name is `"Pricing"`, return a new list sorted with `pricing_field_sort_key(fc.field_name, profile)`;
- otherwise, return the original list unchanged.

This placement is intentional. Every scan text/Markdown/HTML body and every `changes` text/HTML body already passes through this function, including default/all/squelched detail modes. Do not sort inside `_field_display_plan`: that plan feeds JSON-adjacent accounting and bulk signatures, and presentation order must not mutate source fidelity or grouping identity.

- [ ] **Step 6: Remove the scan-card private sorter**

Delete `_pricing_rows_by_impact` and the `if category == "Pricing"` branch in `_render_html_card_table`. The table must consume the order supplied by `_group_field_changes_for_detail`. Keep `_model_price_impact`, `_collect_price_movement_summary`, `_PriceMovementModel`, and F2 model-card sorting unchanged.

- [ ] **Step 7: Run focused reporting tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_reporting.py -v
```

Expected: all tests in `tests/test_reporting.py` PASS. The characterization modules have not yet been updated and are handled before the next commit in Task 4.

- [ ] **Step 8: Prove page-level impact ranking did not move**

Run the existing tests that pin page-level impact ranking and headline selection:

```bash
./.venv/bin/python -m pytest \
  tests/test_reporting.py::test_price_movement_headline_names_the_biggest_dollar_mover \
  tests/test_reporting.py::test_impact_sort_leads_with_the_largest_absolute_dollar_move \
  tests/test_reporting.py::test_impact_sort_breaks_a_cents_rounded_tie_with_percent \
  tests/test_reporting.py::test_impact_sort_breaks_a_percent_tie_with_coverage_count \
  tests/test_reporting.py::test_impact_sort_falls_back_to_the_model_id \
  -v
```

Expected: all selected tests PASS without expectation changes. Do not weaken or rename these assertions merely to accommodate field-row ordering.

- [ ] **Step 9: Review Task 2 without committing**

Inspect the diff for accidental non-Pricing reordering. Do not stage or commit while the characterization suite is known to need reviewed expectation updates. Continue directly to Task 3, keeping the change set scoped to the approved ordering behavior.

## Task 3: Give HTML summaries the same provider order

**Files:**

- Modify: `model_sentinel/reporting.py` (`_SummaryEntry`, summary constructors, `_summary_entry_sort_key`)
- Test: `tests/test_reporting.py`

- [ ] **Step 1: Write failing scan and `changes` summary tests**

Add one scan HTML assertion and one `changes` HTML assertion that isolate the Change Summary `<tbody>` and prove Pricing rows for a single model are Input, cache, Output. Use raw paths whose display-label alphabetical order would be cache, Input, Output so the old `_summary_entry_sort_key` cannot pass accidentally.

Also assert that:

- non-Pricing summary rows retain their existing alphabetical field ordering;
- provider then model grouping remains unchanged;
- base Input/Output rows precede their qualified conditional variants;
- presence and squelched summary rows retain their existing category placement and spelling.

- [ ] **Step 2: Run the summary tests and verify failure**

Run:

```bash
./.venv/bin/python -m pytest \
  tests/test_reporting.py::test_scan_change_summary_uses_profile_pricing_field_order \
  tests/test_reporting.py::test_changes_change_summary_uses_profile_pricing_field_order \
  -v
```

Expected: FAIL with cache alphabetized before Input.

- [ ] **Step 3: Carry a precomputed sort key in `_SummaryEntry`**

Add an optional `pricing_sort_key: PricingFieldSortKey | None = None` field to `_SummaryEntry`. Keep it as presentation metadata only; never serialize it.

Update `_build_summary_entries_from_fc` and `_build_summary_entries_from_bulk` to compute `pricing_field_sort_key(raw_field_path, profile)` only when the resolved category is `"Pricing"`. Use keyword arguments for optional dataclass fields so the existing positional `grouped_model_ids` and `anchor` arguments cannot silently shift. Presence and squelched constructors leave `pricing_sort_key=None`.

This precomputation is required because `_build_html_summary_table` combines entries from multiple providers and intentionally has no reliable profile lookup of its own. Re-resolving by provider display label would reintroduce the label-collision bug fixed by the provider-profile refactor.

- [ ] **Step 4: Update `_summary_entry_sort_key`**

Keep category rank, provider, and model ID as the first three levels. Within one provider/model/category:

- use `entry.pricing_sort_key` for Pricing field rows;
- otherwise retain the current `entry.field.casefold()` then `entry.detail.casefold()` fallback.

Use a type-compatible composite key rather than comparing `None` to tuples. The final key must remain deterministic for duplicate labels/details.

- [ ] **Step 5: Run focused summary and reporting tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_reporting.py -v
```

Expected: all tests in `tests/test_reporting.py` PASS.

- [ ] **Step 6: Review Task 3 without committing**

Inspect the Task 3 diff and confirm every `_SummaryEntry` constructor is still type-correct. Do not stage or commit while the characterization suite is known to need reviewed expectation updates. Continue directly to Task 4.

## Task 4: Review and update characterization goldens

**Files:**

- Modify: `tests/test_render_characterization.py`
- Modify: `tests/test_render_changes_characterization.py`
- Verify: `tests/test_render_bulk_characterization.py`

- [ ] **Step 1: Run all renderer characterization modules before editing goldens**

Run:

```bash
./.venv/bin/python -m pytest \
  tests/test_render_characterization.py \
  tests/test_render_changes_characterization.py \
  tests/test_render_bulk_characterization.py \
  -v
```

Expected: failures show ordered permutations of Pricing rows in text, Markdown, scan HTML cards, and HTML summaries. JSON expectations and non-Pricing row contents must not change. Bulk characterization may already pass because scalar price changes are not bulk-grouped.

- [ ] **Step 2: Inspect every golden diff before accepting it**

For each failure, verify:

- the same rows and values remain present exactly once;
- only Pricing-row sequence, zebra-striping classes caused by the new sequence, and commentary describing that sequence changed;
- category order, model order, values, units, deltas, percentages, CSS semantics, anchors, hidden counts, and JSON byte content remain unchanged;
- scan and `changes` summary rows now agree with their corresponding model body;
- dynamic Input/Output qualifiers remain visible and sort after the base field of the same rank.

Do not update a golden wholesale without checking these invariants.

- [ ] **Step 3: Update golden constants and historical commentary**

Edit the exact expected text/Markdown/HTML constants to the reviewed order. Preserve comments that explain the July 25 impact-sort history, but add a concise note that the fixed provider order now supersedes row-level impact sorting across human formats. Remove or rewrite assertions whose stated cause is specifically display-label alphabetical ordering when that is no longer the active Pricing policy.

- [ ] **Step 4: Re-run all characterization modules**

Run the command from Step 1.

Expected: all characterization tests PASS.

- [ ] **Step 5: Render the synthetic HTML fixture for visual QA**

Generate a temporary report outside the repository using the existing synthetic fixture and the project venv:

```bash
ORDER_REPORT=$(mktemp /tmp/model-sentinel-order.XXXXXX.html)
ORDER_REPORT="$ORDER_REPORT" ./.venv/bin/python - <<'PY'
import os
from pathlib import Path

from model_sentinel.reporting import render_scan_report
from tests.test_render_characterization import (
    COMMAND,
    GENERATED_AT,
    characterization_scan_result,
)

Path(os.environ["ORDER_REPORT"]).write_text(
    render_scan_report(
        generated_at=GENERATED_AT,
        command=COMMAND,
        format_name="html",
        provider_results=characterization_scan_result(),
    ),
    encoding="utf-8",
)
PY
open "$ORDER_REPORT"
```

Expected visual result: the Pricing group starts with any present Input row, then cache rows, then Output rows; the category chip remains on the first Pricing row; zebra striping follows field rows and their raw-value continuation rows; the Change Summary repeats the same field sequence for each model.

- [ ] **Step 6: Run the complete suite, review, and commit Tasks 2–4**

Confirm the generated artifact remains under `/tmp` and is not staged. Run the complete suite:

```bash
./.venv/bin/python -m pytest
```

Expected: every test PASS with no failures or errors. Then stage the production/reporting changes and all ordering-related focused and characterization tests from Tasks 2–4. Inspect the complete staged file list and staged diff for sensitive data, and commit with a message such as:

```text
Use consistent pricing order in human reports
```

## Task 5: Synchronize operator and architecture documentation

**Files:**

- Modify: `README.md` (`HTML Auto-Reports` ordering paragraph)
- Modify: `docs/DESIGN.md` (`Reporting` section)
- Modify: `docs/report_readability_redesign_design.md` (`Model cards`, amendments)

- [ ] **Step 1: Update the README contract**

Replace the claim that both row and model ordering are by impact. State separately:

- Within each human-readable Pricing group, the active provider profile defines a stable semantic order; OpenRouter uses Input, cache variants, Output, then unranked Pricing fields alphabetically.
- Across the HTML page, price-changed model cards remain ranked by impact.

Mention that text, Markdown, scan HTML, full HTML, `changes` HTML/text, and Change Summary share the Pricing order; JSON and chronological history are not reordered.

- [ ] **Step 2: Update the current design**

In `docs/DESIGN.md`, add the provider-owned order to the existing Reporting description and reinforce that it is presentation-only. Do not alter the Diff Semantics or storage contracts.

- [ ] **Step 3: Amend the historical readability design**

Change the Model Cards statement that Pricing rows sort by descending absolute delta. Add a dated amendment explaining:

- real reports demonstrated that row-level impact order made Input/Cache/Output move between models;
- stable semantic order now wins for within-card comparability;
- D1 headline movers and F2 page-level model impact order remain intact, so the report still elevates large movements without permuting each card's schema.

- [ ] **Step 4: Review and commit documentation**

Run:

```bash
rg -n "pricing rows|within a card|ordering is by impact|descending absolute delta" \
  README.md docs/DESIGN.md docs/report_readability_redesign_design.md
```

Expected: no active documentation still claims that Pricing rows inside a model card are delta-sorted; historical text is clearly marked as superseded. Stage the three docs, inspect the staged diff for sensitive data, and commit with a message such as:

```text
Document consistent pricing field order
```

## Task 6: Complete verification and regression review

**Files:**

- Verify all project files and tests; no new production changes should be introduced here unless a failure is root-caused and fixed through a new red/green cycle.

- [ ] **Step 1: Run the complete test suite**

The repository instructions require every test category. Model Sentinel's test suite is pytest-based, so run all collected tests—not selected modules only:

```bash
./.venv/bin/python -m pytest
```

Expected: exit code 0 with every test passing and no skipped/failed/error tests. If anything fails, stop completion work, report every failing test, diagnose it, add or correct the failing regression first, and rerun the complete suite.

- [ ] **Step 2: Smoke-test the CLI inside the venv**

Run:

```bash
./.venv/bin/python -m model_sentinel --help
```

Expected: exit code 0 and the CLI usage text. No provider credentials or network request are required.

- [ ] **Step 3: Verify source-fidelity boundaries**

Run focused controls for JSON and history plus the new order tests:

```bash
./.venv/bin/python -m pytest \
  tests/test_diffing.py \
  tests/test_storage.py \
  tests/test_reporting.py \
  -v
```

Expected: PASS. Inspect the new tests to confirm JSON arrays/raw paths and chronological history remain unchanged while human Pricing groups are fixed.

- [ ] **Step 4: Search for stale or duplicate ordering implementations**

Run:

```bash
rg -n "_pricing_rows_by_impact|delta_abs.*sort|Pricing.*sorted|pricing_field_sort_key|pricing_field_order" \
  model_sentinel tests README.md docs
```

Expected:

- no `_pricing_rows_by_impact` definition or call remains;
- one production sort-key resolver exists;
- report assembly calls the resolver only through the shared grouping path and summary-entry construction;
- page-level `_model_price_impact` and Price Movement delta logic remain present;
- documentation matches the new division between field-row order and model-card order.

- [ ] **Step 5: Inspect the complete branch diff and public-repository safety**

Run `git status --short`, `git diff --stat origin/main...HEAD`, and `git diff origin/main...HEAD`. Inspect every changed file and commit message for secrets, credentials, personal data, account data, production payloads, or copied live-report artifacts. Confirm all tests use unmistakably synthetic providers/models/values and no report generated under `/tmp` entered the repository.

- [ ] **Step 6: Final acceptance check**

The implementation is ready only when all of these are true:

- Two models with opposite price-delta magnitudes still render the same Input/cache/Output sequence.
- OpenRouter base and conditional Pricing fields obey the profile tuple.
- Unranked and generic-profile Pricing fields have deterministic fallbacks.
- Scan text, Markdown, concise HTML, full HTML, `changes` text/HTML, and both HTML summaries agree.
- Page-level model cards and Price Movement headlines remain impact-ranked.
- Non-Pricing report-body order, history chronology, JSON, diffs, and storage remain unchanged.
- The complete test suite passes with no skipped, failed, or errored tests.
- Documentation no longer promises row-level impact sorting.

Do not deploy, reinstall the standalone zipapp, reload launchd, push, or open a pull request unless the user separately authorizes those actions.
