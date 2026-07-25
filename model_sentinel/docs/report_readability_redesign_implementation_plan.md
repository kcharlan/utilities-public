# Report Readability Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **On code in this plan:** this repository's instructions prohibit pre-writing implementation bodies for a capable executor. Tasks therefore specify exact file paths, names, signatures, data shapes, behavior, and acceptance criteria — and include literal code only where the exact logic is load-bearing (signatures, sort-key tuples, the slug algorithm, CSS selector shapes). Derive the implementation from the description. If a description is ambiguous, stop and ask rather than guessing.

**Goal:** Rebuild the concise HTML scan report as a triage surface — legible pricing, cost-only color semantics, dollar-led price movement, impact ordering, and navigation — on top of a single shared change-classification layer that eliminates the current per-renderer duplication.

**Architecture:** Extract the six-branch change-classification cascade currently duplicated across `_render_smart_change_text` (text/markdown), `_render_html_table_row` (HTML), and `_build_summary_entries_from_fc` into a new format-agnostic module, `model_sentinel/change_render.py`. It returns a frozen `RenderedChange` describing a change in medium-neutral terms; every renderer becomes a thin formatter over it. Semantic fixes then land once. Layout work is confined to the concise HTML path afterward.

**Tech Stack:** Python 3.12+, stdlib only at runtime (no new dependencies). pytest for tests. Self-contained single-file HTML output with inlined CSS and no JavaScript.

**Design source:** [`report_readability_redesign_design.md`](./report_readability_redesign_design.md). Read it before starting. Where this plan and the design disagree, the design wins — report the discrepancy.

## Global Constraints

- **Stdlib only at runtime.** No new third-party dependencies. `reporting.py` and `change_render.py` import only from the stdlib and from sibling `model_sentinel` modules.
- **Reports stay self-contained.** All CSS inlined. **No JavaScript** in generated HTML — the raw-value toggle and navigation are CSS-only. N3 (filter box) is explicitly out of scope.
- **Public repository.** No real provider data in code, tests, fixtures, docs, or commit messages. Test fixtures use conspicuously synthetic model IDs (`alpha`, `beta`, `vendor/model-a`) and prices. This matches the existing convention in `tests/test_reporting.py`.
- **JSON output is never altered.** Full fidelity, including `noop` entries. Audit output must not silently drop records.
- **`_full.html` keeps its current layout.** It inherits semantic fixes (E1, E2, labels, precision) only.
- **Existing detail-policy semantics are unchanged.** Squelch patterns, `--detail` modes, bulk consolidation, and `ReportDetailPolicy` behavior are not in scope.
- **Full suite must pass at every commit.** Baseline: 56 passed. Run `pytest` from `model_sentinel/`.
- **Test integrity.** A test that was green before a change and red after is a signal, not an obstacle. Do not edit a test to make it pass unless the task explicitly says its expectations change; when it does, the edit must be deliberate and commented.
- **Commit style:** concise imperative subject; body when multiple things changed.

## File Structure

| Path | Responsibility |
|---|---|
| `model_sentinel/change_render.py` | **New.** Classification, field labels, value formatting. Format-agnostic. Owns `RenderedChange`, `classify_change`, the label registry, and the numeric/price primitives moved out of `reporting.py`. |
| `model_sentinel/reporting.py` | **Modified.** Report assembly and per-format markup. Stops classifying; consumes `RenderedChange`. Should shrink from 2,849 lines. |
| `tests/test_change_render.py` | **New.** Unit tests for classification, labels, precision, semantics. |
| `tests/test_render_characterization.py` | **New.** Golden-output tests across all four formats, protecting the refactor. |
| `tests/test_reporting.py` | **Modified.** Existing 25 tests; extended for layout, sorting, verdict, anchors. |

---

### Task 1: Characterization test harness

**This task is a precondition for every other task.** Without it, Task 3 is unverifiable.

**Files:**
- Create: `tests/test_render_characterization.py`

**Interfaces:**
- Consumes: `render_scan_report` from `model_sentinel.reporting` (existing signature, keyword-only: `generated_at`, `command`, `format_name`, `provider_results`, `detail_policy`).
- Produces: a module-level fixture builder other tasks reuse. Name it `characterization_scan_result()`, returning a `list[ProviderScanResult]`.

- [ ] **Step 1: Build the fixture covering every classification branch**

Create `characterization_scan_result()` following the `_scan_result` helper pattern already in `tests/test_reporting.py:11` (same keyword arguments, `price_multiplier=1000000`, `price_divisor=1`). It must produce one provider with `ModelDelta` entries whose `FieldChange` tuples collectively exercise **all** of:

| # | Case | Field / values |
|---|---|---|
| 1 | Price change, both sides numeric | `pricing.completion`, `0.000002` → `0.0000035` |
| 2 | Price addition | `pricing.input_cache_read`, `None` → `0.00000005` |
| 3 | Price removal | `pricing.input_cache_write`, `0.00000009` → `None` |
| 4 | Count field, both numeric | `top_provider.context_length`, `131072` → `262144` |
| 5 | Count field, one-sided add | `top_provider.max_completion_tokens`, `None` → `16384` |
| 6 | Count field, one-sided remove | `top_provider.max_completion_tokens`, `8192` → `None` (separate model) |
| 7 | Boolean false → true | `top_provider.is_moderated`, `False` → `True` |
| 8 | Boolean true → false | `top_provider.is_moderated`, `True` → `False` (separate model) |
| 9 | Integer-encoded boolean | `reasoning.default_enabled`, `0` → `1` |
| 9b | Numeric field holding 0/1 | `default_parameters.temperature`, `0` → `1` — must **not** classify as boolean |
| 10 | `null → null` | `default_parameters.temperature`, `None` → `None` |
| 11 | List diff | `supported_parameters`, `["tools"]` → `["tools", "logit_bias"]` |
| 12 | Dynamic override path | `pricing.overrides`, old/new lists of dicts keyed by `min_prompt_tokens`, with a changed `completion` value |
| 13 | Scalar fallback | `expiration_date`, `None` → `"2030-12-31"` |
| 14 | Squelched field | `benchmarks.example_suite`, `[{"score": 1}]` → `[{"score": 2}]` |

Use synthetic model IDs only. Case 12 must use the real `pricing.overrides` list-of-dicts shape so `_expand_pricing_override_changes` ([reporting.py:295](../model_sentinel/reporting.py)) engages and produces a bracketed path — that is the code path being protected.

- [ ] **Step 2: Write golden-output tests for all four formats**

Four tests: `test_characterization_text`, `test_characterization_markdown`, `test_characterization_html`, `test_characterization_json`. Each renders the fixture at `--detail default` and asserts against a stored expected string.

**Store the expected output as a module-level constant in the test file, not an external file.** Reviewers must see the golden text in the diff when it changes.

Markdown gets the same depth of coverage as text and HTML. It currently has only 2 tests against 15 each for text and HTML; that gap is the single largest regression risk in this plan.

- [ ] **Step 3: Add a second golden set at `--detail all`**

Repeat for `ReportDetailPolicy` in `all` mode so squelched-field rendering is also protected. Name them `test_characterization_<format>_detail_all`.

- [ ] **Step 4: Run and confirm green against unmodified source**

```bash
pytest tests/test_render_characterization.py -v
```

Expected: 8 passed. These must pass against **current, unmodified** `reporting.py`. If any fails, the golden string is wrong — fix the golden string, never the source, in this task.

- [ ] **Step 5: Run the full suite**

```bash
pytest
```

Expected: 64 passed (56 baseline + 8 new).

- [ ] **Step 6: Commit**

```bash
git add tests/test_render_characterization.py
git commit -m "Add characterization tests for report renderers"
```

---

### Task 2: The `change_render` module

New module, fully unit-tested, **not yet wired into any renderer.**

**Files:**
- Create: `model_sentinel/change_render.py`
- Create: `tests/test_change_render.py`

**Interfaces:**
- Consumes: `FieldChange` from `model_sentinel.models`.
- Produces (later tasks depend on these exact names):

```python
@dataclass(frozen=True)
class RenderedChange: ...

def classify_change(
    field_change: FieldChange,
    *,
    price_multiplier: int = 1,
    price_divisor: int = 1,
) -> RenderedChange: ...
```

- [ ] **Step 1: Write failing tests for the `RenderedChange` shape and each `kind`**

One test per classification branch, asserting the resulting `kind`, `direction`, and `semantic`:

| Input | `kind` | `direction` | `semantic` |
|---|---|---|---|
| Price, both numeric, increase | `price` | `up` | `cost` |
| Price, both numeric, decrease | `price` | `down` | `cost` |
| Price, `None` → value | `price` | `added` | `coverage` |
| Price, value → `None` | `price` | `removed` | `coverage` |
| Context length change | `count` | `up`/`down` | `capacity` |
| Count one-sided | `count` | `added`/`removed` | `coverage` |
| Boolean either direction | `boolean` | `up`/`down` | `capability` |
| List membership change | `list` | `none` | `capability` |
| `None` → `None` | `noop` | `none` | `neutral` |
| Unclassified scalar | `scalar` | `none` | `neutral` |

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_change_render.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'model_sentinel.change_render'`.

- [ ] **Step 3: Define `RenderedChange`**

Frozen dataclass. Fields, exactly as named in the design:

`kind` (`Literal["price","count","numeric","boolean","list","scalar","noop"]`), `field_path` (str), `label` (str), `qualifier` (str | None), `old_display` (str), `new_display` (str), `old_raw` (str | None), `new_raw` (str | None), `unit` (str | None), `delta_display` (str | None), `delta_abs` (float | None), `pct_display` (str | None), `direction` (`Literal["up","down","added","removed","none"]`), `semantic` (`Literal["cost","capacity","capability","coverage","neutral"]`), `list_added` (tuple[str, ...]), `list_removed` (tuple[str, ...]).

`delta_abs` is for sorting only and must never be formatted for display.

- [ ] **Step 4: Move the shared primitives into the module**

Move verbatim from `reporting.py`, preserving behavior exactly — this step changes no logic:

`_classify_field`, `_both_numeric`, `_numeric_value`, `_is_price_amount_field`, `_is_count_field`, `_fmt_int`, `_pct_change`, `_fmt_price_per_m`, `_normalize_price`.

Keep the leading underscore. Re-export them from `reporting.py` (import at module top) so existing call sites and tests keep working unchanged in this task.

- [ ] **Step 5: Implement `classify_change`**

The branch order must match the current cascade in `_render_smart_change_text` ([reporting.py:1243](../model_sentinel/reporting.py)), with `noop` checked first:

1. `noop` — both `old_value` and `new_value` are `None`, or the two values are equal.
2. `list` — both values are lists. Populate `list_added` / `list_removed` from set difference, sorted, matching `_render_list_diff_text`. `unit` is `"items"`.
3. `boolean` — either value is a `bool`, **or** the field appears in the known-boolean set below and both values are integer-like `0`/`1`. Display `"off"` / `"on"`. `pct_display` is `None` and `delta_abs` is `None` — booleans are never percent-formatted or subtracted. `delta_display` carries the pill text `"enabled"` / `"disabled"`, which is what occupies the delta column.

   **The known-boolean set is required, not optional.** The current code treats only real `bool` instances as boolean, so `reasoning.default_enabled` arriving as integer `0` → `1` falls through to numeric and gets percent arithmetic — that is precisely the E2 defect. Define a module-level frozenset in `change_render.py` alongside the other registries, seeded with the boolean-valued fields observed in the history database:

   `top_provider.is_moderated`, `reasoning.default_enabled`, `reasoning.mandatory`, `deprecated`

   The first three are every field in the history database whose recorded values are `0`/`1`/`true`/`false` and which is semantically a flag. `deprecated` is not observed in any recorded change but appears in `DEFAULT_REPORT_SHOW_FIELDS` ([reporting.py:35](../model_sentinel/reporting.py)); include it as a forward guard.

   **The set restriction is load-bearing.** `default_parameters.repetition_penalty`, `default_parameters.top_p`, and `default_parameters.temperature` also hold `0`/`1` values in the history database, but they are genuinely numeric — a temperature of `1` is a magnitude, not a flag. Treating integer `0`/`1` as boolean for *any* field would misrender them. Apply the boolean branch only to fields in this set.
4. `price` — `_is_price_amount_field` is true and the numeric guard from the current implementation holds. Normalize via `_normalize_price`. `unit` is `"/1M"`.
5. `count` — `_is_count_field` is true. `unit` is `"tok"`. `semantic` is `capacity` when both sides are numeric, `coverage` when one-sided.
6. `numeric` — both numeric, no category match.
7. `scalar` — fallback.

Preserve **exactly** the current guard conditions for price and count. They are subtle (they permit one-sided `None` but reject non-numeric strings) and a paraphrase will change behavior.

**In this task**, `label` returns the raw `field_path` and `qualifier` is always `None`. The registry arrives in Task 5. Formatting precision keeps the current `_fmt_price_per_m` magnitude-based rule; the operand-based rule arrives in Task 6.

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_change_render.py -v
```

Expected: all pass.

- [ ] **Step 7: Run the full suite**

```bash
pytest
```

Expected: 64 + new count, all passing. **Characterization tests must be untouched and green** — nothing is wired up yet, so output cannot have changed.

- [ ] **Step 8: Commit**

```bash
git add model_sentinel/change_render.py tests/test_change_render.py model_sentinel/reporting.py
git commit -m "Add change_render classification module"
```

---

### Task 3: Rewire renderers onto `RenderedChange`

**Behavior-neutral by construction.** The acceptance criterion is that Task 1's golden files are unchanged.

**Files:**
- Modify: `model_sentinel/reporting.py`

**Interfaces:**
- Consumes: `classify_change`, `RenderedChange` from Task 2.
- Produces: no new public surface.

- [ ] **Step 1: Rewrite `_render_smart_change_text` as a formatter**

It takes a `FieldChange`, calls `classify_change`, and formats the resulting `RenderedChange` into the current text form. Its output must be byte-identical to today's for every case in the characterization fixture.

- [ ] **Step 2: Rewrite `_render_html_table_row` as a formatter**

Same, for the HTML `<tr>`. Byte-identical output. It keeps emitting the current four-column row in this task; the eight-column layout arrives in Task 7.

- [ ] **Step 3: Rewrite `_build_summary_entries_from_fc` to consume `RenderedChange`**

Stop re-deriving classification. Byte-identical output.

- [ ] **Step 4: Route the list-diff renderers through `list_added` / `list_removed`**

`_render_list_diff_text`, `_render_html_list_diff`, `_render_bulk_list_diff_text`, `_render_html_bulk_list_diff` stop computing set differences and read them off `RenderedChange`.

- [ ] **Step 5: Verify the ordering trap is respected**

Confirm by inspection that renderers do **not** skip `noop` entries and labels still render as raw dotted paths. Suppression (E1) and labels are Task 4 and Task 5. Turning either on here makes this task unverifiable, because the golden files would then legitimately need edits and could mask a real regression.

- [ ] **Step 6: Run characterization tests**

```bash
pytest tests/test_render_characterization.py -v
```

Expected: 8 passed, **with no edits to the golden strings**. If a golden string needs changing, a regression was introduced — find it rather than updating the expectation.

- [ ] **Step 7: Run the full suite**

```bash
pytest
```

- [ ] **Step 8: Commit**

```bash
git add model_sentinel/reporting.py
git commit -m "Route renderers through shared change classification"
```

---

### Task 4: Suppress no-op rows and fix boolean rendering (E1, E2)

First intentional behavior change. Applies to text, markdown, both HTML paths, and the `changes` report. **Not** JSON.

**Files:**
- Modify: `model_sentinel/reporting.py`
- Modify: `tests/test_render_characterization.py` (deliberate golden updates)
- Modify: `tests/test_change_render.py`

- [ ] **Step 1: Write failing tests**

- `null → null` rows are absent from text, markdown, and both HTML outputs, and **present** in JSON.
- A boolean `True → False` renders `on → off` and its output contains no `%` character. This is the regression test for the current `↓ 100.0%` defect.
- A boolean `False → True` renders `off → on` with a non-empty delta cell. This is the regression test for the current blank-cell defect caused by `_pct_change` returning `""` when `old == 0` ([reporting.py:1213](../model_sentinel/reporting.py)).
- `reasoning.default_enabled` at integer `0 → 1` renders `off → on` and contains no `%`.
- `default_parameters.temperature` at `0 → 1` still renders as a **numeric** change with a percent, confirming the known-boolean set is applied as a restriction and not a blanket rule.

- [ ] **Step 2: Run to verify failure**

- [ ] **Step 3: Implement suppression at the render layer**

Every non-JSON renderer skips entries whose `kind == "noop"`. Filter in one shared helper consumed by all renderers, not per-renderer — duplicating the filter is the exact defect this plan exists to remove.

Suppression happens at render time only. `noop` entries stay in `ModelDelta.field_changes` and in the database, so JSON and audit paths are unaffected.

- [ ] **Step 4: Update the golden strings deliberately**

Golden output loses the `null → null` rows and gains `off`/`on` boolean rendering. Update the constants to the new expected values and confirm every remaining difference is intended. Nothing else in the golden text may change.

- [ ] **Step 5: Run the full suite**

- [ ] **Step 6: Commit**

```bash
git add model_sentinel/ tests/
git commit -m "Suppress no-op rows and render booleans as off/on"
```

---

### Task 5: Field label registry

**Files:**
- Modify: `model_sentinel/change_render.py`
- Modify: `tests/test_change_render.py`
- Modify: `tests/test_render_characterization.py`

- [ ] **Step 1: Write failing tests**

- Exact match wins over suffix match.
- Suffix match resolves a dynamic path: `pricing.overrides[min_prompt_tokens=200000].completion` → `label == "Output"`, `qualifier == "min_prompt_tokens=200000"`.
- Unmatched path falls back to prettified leaf: `hugging_face_id` → `"Hugging face id"`.
- `field_path` is preserved verbatim in every case, including when a label was found.
- `context_length` and `top_provider.context_length` produce **different** labels.

- [ ] **Step 2: Run to verify failure**

- [ ] **Step 3: Add the registry**

Two module-level mappings in `change_render.py`: one keyed by full dotted path, one keyed by leaf segment. Both are plain dicts so adding a name is a one-line edit.

Lookup order: exact path → leaf suffix → prettified-leaf fallback (split on `_`, sentence-case).

Before lookup, strip any bracketed condition from a path segment and carry it as `qualifier`. Reuse the bracket convention produced by `_pricing_override_path` ([reporting.py:348](../model_sentinel/reporting.py)) rather than inventing a parser — that function is the only producer of these paths.

Seed with all 42 entries from the design's "Initial registry contents" section, which were derived from every distinct non-benchmark field name observed in the history database. Copy them exactly, including `context_length` → `"Context length (model)"`.

- [ ] **Step 4: Update golden strings**

Field names change to labels across all four non-JSON outputs. JSON is unaffected — verify that.

- [ ] **Step 5: Run the full suite**

- [ ] **Step 6: Commit**

```bash
git add model_sentinel/change_render.py tests/
git commit -m "Add field label registry with dynamic path support"
```

---

### Task 6: Operand-based precision

**Files:**
- Modify: `model_sentinel/change_render.py`
- Modify: `tests/test_change_render.py`
- Modify: `tests/test_render_characterization.py`

- [ ] **Step 1: Write failing tests**

- A cents-level change renders 2 decimal places on **old, new, and delta alike**.
- A fourth-decimal change renders 4 places on all three.
- Old, new, and delta always share the same precision — assert this as an invariant, not three separate values.
- Precision is capped at 4 places; a value needing more renders at 4.
- Zero still renders as `free`.

- [ ] **Step 2: Run to verify failure**

- [ ] **Step 3: Replace the precision rule**

`_fmt_price_per_m`'s magnitude-based selection (currently 2/4/6 places by size) is replaced by: precision is the greater of the two operands' significant decimal places, capped at 4, applied uniformly to old, new, and delta.

The three values must be formatted together, from a shared computed precision — not by three independent calls that happen to agree.

- [ ] **Step 4: Update golden strings and run the full suite**

- [ ] **Step 5: Commit**

```bash
git add model_sentinel/change_render.py tests/
git commit -m "Align price precision to operand significant decimals"
```

---

### Task 7: Concise HTML card layout (A1, B1, C1)

Layout work begins. Confined to `_render_scan_html` and its helpers; `_full.html` and the text/markdown paths are untouched.

**Files:**
- Modify: `model_sentinel/reporting.py` (`_append_html_field_changes`, `_render_html_table_row`, `_render_html_model_changes`, `_HTML_CSS`)
- Modify: `tests/test_reporting.py`

- [ ] **Step 1: Write failing tests**

- A model card with three change categories emits **exactly one** `<table>` element. This is the C1 regression test.
- A price increase and a context-length increase in the same card produce **different** CSS classes. Assert on class names so a future change that re-merges cost and capacity color fails loudly.
- Every price row exposes both a normalized display value and a `title` attribute containing the raw value.

- [ ] **Step 2: Run to verify failure**

- [ ] **Step 3: Restructure to one table per card**

One `<table>` per model card with a fixed `<colgroup>` of eight columns: category, field, old, arrow, new, unit, delta, percent. Per-category tables auto-size independently today, which is why columns do not align down a card.

Rows group by category in the existing `_CATEGORY_ORDER`. The category name renders as a dim chip in column 1 on the **first row of each group only**; later rows in the group leave it empty. A stronger top border marks group boundaries.

Within the Pricing group, rows sort by descending absolute delta.

- [ ] **Step 4: Drive color from `semantic`**

CSS classes derive from `RenderedChange.semantic`, never from `direction` alone. Mapping per the design's color table: `cost` up red / down green; `capacity` amber both directions; `capability` blue; `coverage` blue; `neutral` dim.

Add the classes to `_HTML_CSS` using existing `:root` custom properties (`--accent-red`, `--accent-green`, `--accent-amber`, `--accent-blue`). Do not introduce new color values.

Numeric columns are right-aligned with `font-variant-numeric: tabular-nums`.

- [ ] **Step 5: Run the full suite**

Characterization goldens for text, markdown, and JSON must be **unchanged** — this task touches concise HTML only. The HTML golden changes; verify every difference is intended layout, not altered values.

- [ ] **Step 6: Commit**

```bash
git add model_sentinel/reporting.py tests/
git commit -m "Rebuild model card as single aligned table with cost-only color"
```

---

### Task 8: Price Movement card (D1, D3)

**Files:**
- Modify: `model_sentinel/reporting.py` (`_PriceMovementModel`, `_PriceMovementSummary`, `_collect_price_movement_summary`, `_price_movement_outcome`, `_render_html_price_movement_summary`, `_HTML_CSS`)
- Modify: `tests/test_reporting.py`

- [ ] **Step 1: Write failing tests**

- **The verdict regression test:** a 4-up / 4-down / 3-both model split yields `"mixed"`, not `"mostly lower"`. Today's implementation derives the verdict from field counts while displaying model counts, so a tied model split can render "mostly lower" — that is the defect.
- A strictly-largest bucket yields `"mostly higher"` / `"mostly lower"`.
- The headline increase panel names the model with the largest absolute per-1M increase and shows its dollar delta.
- With no decreases present, the decrease panel is **omitted**, not rendered empty.
- Tally chips state both units explicitly and independently (models and price fields).

- [ ] **Step 2: Run to verify failure**

- [ ] **Step 3: Extend the summary dataclasses**

`_PriceMovementModel` ([reporting.py:105](../model_sentinel/reporting.py)) currently stores only four counters. Add, per model: the largest absolute per-1M delta and the `RenderedChange` that produced it, for each direction. `_collect_price_movement_summary` populates them while it already iterates visible field changes — no second pass.

- [ ] **Step 4: Rewrite the verdict**

`_price_movement_outcome` derives from **model** buckets, matching the tally directly beneath it:

- one bucket strictly largest → `"mostly higher"` / `"mostly lower"`
- otherwise → `"mixed"`

Append bucket counts to the string: `mixed — 4 up, 4 down, 3 both`.

This is a user-visible behavior change. Historical reports are not regenerated.

- [ ] **Step 5: Rebuild the card markup**

Order: header with verdict → two headline mover panels side by side → labeled tally chip groups → collapsed affected-model list in three buckets.

Headline movers show model ID, field label, `old → new` with unit, absolute delta at the largest type size in the card, and percent.

Bucket labels shorten to `↑ Higher only` / `↓ Lower only` / `↕ Both directions`. The current sentence-form labels are replaced. Zero-count buckets stay omitted, matching current behavior.

Per E5, omit the provider label in the affected-model list when exactly one provider has price changes; retain it when more than one does.

- [ ] **Step 6: Run the full suite and commit**

```bash
git add model_sentinel/reporting.py tests/
git commit -m "Lead price movement with dollar movers and model-based verdict"
```

---

### Task 9: Page structure and impact sorting (E3–E6, F1, F2)

**Files:**
- Modify: `model_sentinel/reporting.py` (`_render_scan_html`, `_append_html_hidden_summary`, `_build_html_summary_table`, `_HTML_CSS`)
- Modify: `tests/test_reporting.py`

- [ ] **Step 1: Write failing tests**

The sort test is the important one. Assert the **full four-level ordering**, including:
- a case where two models tie after cents-rounding and are separated by percent;
- a case separated only by coverage count;
- a model whose only price change is an addition or removal, confirming it sorts at `0.00` on the primary key.

Also: the header states a model count, not a change count; a card with squelched fields renders a `+N hidden` chip in its header and **no** separate squelch section; the Change Summary is inside a closed `<details>`.

- [ ] **Step 2: Run to verify failure**

- [ ] **Step 3: Implement the sort key (F2)**

Applied to tier-1 model cards. Exact key, in order:

```python
(
    -round(max_abs_delta, 2),   # primary: absolute $/1M, rounded to cents
    -max_pct_for_that_field,    # secondary: percent of the field that set the primary
    -coverage_count,            # tertiary: price fields added or removed
    model_id.casefold(),        # quaternary
)
```

The rounding in the primary key is **required**, not incidental. Without it, exact float ties are vanishingly rare and the percent tiebreaker is dead code. Accepted consequence: sub-cent moves all round to `0.00`, tie on the primary key, and are ordered by percent, then coverage, then alphabetically.

- [ ] **Step 4: Implement tiering (F1)**

Tier 1: Price Movement card, added models, removed models, then price-changed model cards in sort order.

Tier 2, inside a single `<details>`: model cards with no price change (alphabetical), the provider-level squelched rollup, and the Change Summary (itself collapsed, per E6).

The disclosure summary line states what is inside, with counts.

- [ ] **Step 5: Implement E3, E4, E5, E6**

- **E3** — per-card squelch collapses to a dim `+N hidden` in the card header, aggregated across categories. Removes today's full section with its own uppercase heading.
- **E4** — header counts models: `N of M models changed · K field changes squelched`. `ProviderScanResult.change_count` ([models.py:80](../model_sentinel/models.py)) is already a model count (`added + removed + changed`); the squelched figure is a **field** count. Label both units explicitly — conflating them is the current defect.
- **E5** — already handled in Task 8 for the movement list; apply the same rule anywhere else a provider label repeats in a single-provider report.
- **E6** — Change Summary collapsed by default, rows grouped under category headers rather than repeating category and provider on every row.

- [ ] **Step 6: Guard against growth**

`_render_scan_html` is currently 163 lines and `_render_changes_html` 133. Neither should grow. If either exceeds its current size, extract the tiering logic into a separate builder function rather than inlining it.

- [ ] **Step 7: Run the full suite and commit**

```bash
git add model_sentinel/reporting.py tests/
git commit -m "Add impact sorting, tiering, and page-level noise reduction"
```

---

### Task 10: Navigation and raw values (N1, R1–R3)

**Files:**
- Modify: `model_sentinel/reporting.py` (`_render_scan_html`, `_HTML_CSS`)
- Modify: `tests/test_reporting.py`

- [ ] **Step 1: Write failing tests**

- Slugs are unique within a report. **`~vendor/model` and `vendor/model` in the same report produce different IDs** — providers emit `~`-prefixed alias entries alongside their base IDs, so this collision occurs in real reports and is not hypothetical.
- **No generated link targets an ID inside tier 2.** Assert this directly; it is the constraint most likely to be violated by a later change.
- Every price row carries a `title` containing scientific notation and the conversion math.
- The report contains no `<script>` element.

- [ ] **Step 2: Run to verify failure**

- [ ] **Step 3: Implement slugs and anchors (N1)**

Slug algorithm: lowercase, replace each non-alphanumeric run with `-`, strip leading and trailing `-`, prefix `m-`. Because that maps `~vendor/model` and `vendor/model` to the same string, disambiguate deterministically: track assigned slugs during render and append a stable numeric suffix to the second and later occurrences, in render order.

Links into cards from: the affected-model list, both headline mover panels, and Change Summary rows. Each card header gets a small dim `↑` link back to the Price Movement card's id.

Add a `:target` rule to `_HTML_CSS` that briefly highlights the card jumped to, so it is obvious where you landed among visually similar cards.

Change Summary rows referencing a **tier-2** model render as plain text, not links — fragment navigation into a closed `<details>` is unreliable across browsers.

- [ ] **Step 4: Implement raw-value tooltips (R1, R2)**

Both price value cells carry a `title` containing, in order: scientific notation, the literal raw value, and the explicit conversion, e.g. `2.0e-6 · 0.000002 × 1,000,000 = $2.00`. Field labels carry a `title` with the full dotted path.

- [ ] **Step 5: Implement the raw-value toggle (R3)**

A single checkbox in the report header labeled "Show raw values". When checked, a dim selectable sub-line appears under each price row showing the raw old → new values.

**CSS only** — a checkbox whose checked state drives sibling or `:has()` selectors. Unchecked by default. This exists because `title` text cannot be selected or copied; the toggle produces text that can be pasted into a spreadsheet. No JavaScript.

- [ ] **Step 6: Run the full suite**

```bash
pytest
```

- [ ] **Step 7: Verify the rendered output in a browser**

Generate a report against the characterization fixture and confirm: anchors jump correctly, the `:target` highlight fires, the raw-value toggle reveals selectable text, and tooltips appear on hover. Automated tests cannot confirm these.

- [ ] **Step 8: Commit**

```bash
git add model_sentinel/reporting.py tests/
git commit -m "Add anchor navigation and raw value inspection"
```

---

### Task 11: Documentation and final verification

**Files:**
- Modify: `model_sentinel/README.md`
- Modify: `docs/report_readability_redesign_design.md` (status line only)

- [ ] **Step 1: Update the README**

The "Report Formatting" and "HTML Auto-Reports" sections describe the old behavior and are now wrong. Update to describe: cost-only red/green semantics, the single-table card, the dollar-led Price Movement card and its model-based verdict, impact ordering, tiering, and the raw-value toggle. The README currently states the Price Movement summary "leads with the dominant direction" — that description no longer matches.

- [ ] **Step 2: Mark the design document implemented**

Change its status line from "approved design, not yet implemented".

- [ ] **Step 3: Run the full suite one final time**

```bash
pytest
```

Report the actual count. Every test must pass.

- [ ] **Step 4: Verify nothing untracked was left behind**

```bash
git status --short
git ls-files model_sentinel/ | grep -E 'change_render|characterization'
```

Both new files must appear as tracked. `.gitignore` rules can silently drop files and `git status` does not show ignored files.

- [ ] **Step 5: Confirm no provider data entered the repository**

```bash
git log --oneline -12
git diff --stat HEAD~10
```

Inspect the full diff for real model IDs, real prices, credentials, or absolute home paths. This repository is public.

- [ ] **Step 6: Commit**

```bash
git add model_sentinel/README.md docs/report_readability_redesign_design.md
git commit -m "Document report readability redesign"
```

---

## Verification Summary

| Design ref | Task |
|---|---|
| Refactor / `change_render.py` | 2, 3 |
| E1 no-op suppression | 4 |
| E2 boolean rendering | 4 |
| Field label registry | 5 |
| Precision rule | 6 |
| A1 price layout | 7 |
| B1 color semantics | 7 |
| C1 single table | 7 |
| D1 dollar-led movers | 8 |
| D3 verdict and tallies | 8 |
| E3 squelch chip | 9 |
| E4 model-based header | 9 |
| E5 provider label omission | 8, 9 |
| E6 Change Summary | 9 |
| F1 tiering | 9 |
| F2 impact sorting | 9 |
| N1 anchors | 10 |
| R1/R2 tooltips | 10 |
| R3 raw-value toggle | 10 |
| Cross-renderer matrix | 4, 5, 6 |
| Documentation | 11 |

**Highest-risk step:** Task 3. It is the only task whose correctness rests entirely on the golden files being genuinely unchanged. If a golden string is edited during Task 3, the refactor's safety guarantee is void — stop and find the regression instead.
