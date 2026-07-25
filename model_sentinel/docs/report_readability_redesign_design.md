# Report Readability Redesign — Design

Status: approved design, not yet implemented.

Supersedes the presentation decisions in [`report_detail_policy_plan.md`](./report_detail_policy_plan.md) where they conflict. Detail-policy semantics (squelch patterns, `--detail` modes) are unchanged.

## Goal

The concise HTML scan report is a **triage** artifact: answer "what moved, by how much, and does it matter to me" in seconds. The `_full.html` companion, JSON, text, and markdown outputs remain the audit surface.

Three problems drive this work:

1. Pricing changes are hard to read. Raw provider values lead, normalized values are parenthetical, old and new sit in distant columns, and only a percentage is shown — so absolute impact is invisible.
2. Red/green means "cost direction" in one table and "capacity direction" in the next, inside the same card.
3. The page is dominated by low-signal content: repeated squelch notices, `null → null` rows, a duplicated summary table, and alphabetical ordering that buries the largest movers.

## Non-goals

- Changing what is collected, stored, or squelched.
- Changing JSON output shape (full fidelity, unchanged).
- Changing `_full.html` layout. It keeps today's rendering.
- Adding runtime dependencies. Reports stay self-contained, single-file, and (except where noted in N3, which is deferred) JavaScript-free.

---

## Locked decisions

| Ref | Decision |
|---|---|
| A1 | Single decimal-aligned price presentation: `$2.00 → $3.50 /1M`, absolute delta, percent |
| B1 | Red/green reserved for **cost** direction only; capacity/limit changes use a neutral accent |
| C1 | One table per model card with a shared `<colgroup>`; category becomes a row-group chip |
| D1 | Price Movement leads with the largest dollar movers by name and amount |
| D3 | Verdict and tallies use the same unit (models); labels shortened; chips replace `·` runs |
| E1 | Suppress `null → null` rows |
| E2 | Booleans render `off → on`; never percent-formatted |
| E3 | Per-card squelch collapses to a `+N hidden` chip in the card header |
| E4 | Header counts **models**, not changes |
| E5 | Provider label omitted from movement lists when only one provider changed |
| E6 | Change Summary collapsed by default, grouped by category |
| F1 | Two tiers: pricing + added/removed above, everything else behind one disclosure |
| F2 | Cards sorted by impact |
| N1 | Bidirectional anchor navigation between summary and cards |
| R1 | Tooltip shows the conversion math |
| R2 | Tooltip shows scientific notation |
| R3 | Page-level "Show raw values" toggle reveals selectable raw text |

---

## Architecture

### The core problem to fix first

`_render_smart_change_text` ([reporting.py:1243](../model_sentinel/reporting.py), serves text and markdown) and `_render_html_table_row` ([reporting.py:2617](../model_sentinel/reporting.py)) independently implement the same six-branch classification cascade — list diff, price amount, count field, both-numeric, boolean, fallback — with the guard conditions duplicated verbatim. `_build_summary_entries_from_fc` is a third partial copy. The same split exists for list diffs (`_render_list_diff_text` / `_render_html_list_diff`) and bulk list diffs (`_render_bulk_list_diff_text` / `_render_html_bulk_list_diff`).

Every fix below (E1, E2, A1, B1, labels, precision) would otherwise have to be applied two or three times. Consolidate first.

### New module: `model_sentinel/change_render.py`

Owns classification, labeling, and value formatting. Format-agnostic — it returns data, never markup.

**Primary entry point:** a function that accepts a `FieldChange` plus the provider's `price_multiplier` and `price_divisor`, and returns a single frozen dataclass instance describing the change in rendered-but-unformatted-for-medium terms.

**The dataclass** (name it `RenderedChange`) carries at minimum:

- `kind` — the classification branch taken. Literal of: `"price"`, `"count"`, `"numeric"`, `"boolean"`, `"list"`, `"scalar"`, `"noop"`.
- `field_path` — the original dotted path, always preserved for tooltips and audit output.
- `label` — the display label from the registry (see below).
- `qualifier` — optional condition text extracted from a bracketed dynamic path, e.g. the condition in `pricing.overrides[min_prompt_tokens=200000].completion`; `None` for ordinary fields.
- `old_display` / `new_display` — the formatted human values (`"$2.00"`, `"262,144"`, `"off"`, `"—"`).
- `old_raw` / `new_raw` — original provider values as strings, for tooltips and the raw-value toggle.
- `unit` — `"/1M"`, `"tok"`, `"items"`, or `None`.
- `delta_display` — formatted absolute delta (`"+$1.50"`, `"+250,144"`), or `None`.
- `delta_abs` — the numeric absolute delta as a float, or `None`. Used by the F2 sort; not for display.
- `pct_display` — `"↑ 63.6%"` / `"↓ 20.5%"`, or `None`.
- `direction` — `"up"`, `"down"`, `"added"`, `"removed"`, `"none"`.
- `semantic` — `"cost"`, `"capacity"`, `"capability"`, `"coverage"`, `"neutral"`. **This, not `direction`, drives color.** See B1 below.
- `list_added` / `list_removed` — tuples of strings for `kind == "list"`, else empty.

**`kind == "noop"`** is how E1 is implemented: a change whose old and new values are both null, or otherwise semantically identical, classifies as `noop`. Every renderer skips `noop` entries. This is deliberately centralized rather than filtered per-renderer.

### Existing functions to retire or reduce

| Function | Disposition |
|---|---|
| `_render_smart_change_text` | Reduced to a thin text formatter over `RenderedChange` |
| `_render_html_table_row` | Reduced to a thin HTML formatter over `RenderedChange` |
| `_build_summary_entries_from_fc` | Consumes `RenderedChange`; stops re-deriving classification |
| `_render_list_diff_text` / `_render_html_list_diff` | Consume `list_added` / `list_removed` |
| `_render_bulk_list_diff_text` / `_render_html_bulk_list_diff` | Same |
| `_pct_change`, `_fmt_price_per_m`, `_fmt_int`, `_normalize_price`, `_both_numeric`, `_numeric_value`, `_is_price_amount_field`, `_is_count_field`, `_classify_field` | Move into `change_render.py`. They are the shared primitives; reporting.py imports them |

The percent-when-old-is-zero behavior at [reporting.py:1213](../model_sentinel/reporting.py) — returning `""` — is the root cause of the blank Change cell on `0 → 1` booleans. It is fixed by the boolean branch never reaching percent logic (E2), not by changing `_pct_change` itself.

---

## Field label registry

### Structure

A module-level mapping in `change_render.py`. **Must be trivially editable** — adding a name is a one-line change.

Two-stage lookup, in order:

1. **Exact match** on the full dotted path.
2. **Suffix match** on the final path segment, so dynamically-generated paths resolve. `pricing.overrides[min_prompt_tokens=200000].completion` has leaf `completion` and resolves to "Output".

Unmatched fields fall back to a prettified leaf: split on `_`, sentence-case. `hugging_face_id` → "Hugging face id". The full dotted path is **always** available in the tooltip regardless of whether a label was found.

### Dynamic path handling

When a path segment contains a bracketed condition, strip it for label lookup and surface it as `qualifier`. The condition renders as a parenthetical after the label: **Output** *(min_prompt_tokens=200000)*. Formatting the condition into prose is out of scope; render it literally.

### Initial registry contents

Derived from every distinct non-benchmark `field_name` in the history database, 2026-03-14 through 2026-07-25 (42 names). Seed with these:

**Pricing** — `pricing.prompt` → Input · `pricing.completion` → Output · `pricing.input_cache_read` → Cache read · `pricing.input_cache_write` → Cache write · `pricing.input_cache_write_1h` → Cache write (1h) · `pricing.input_audio_cache` → Audio cache · `pricing.audio` → Audio · `pricing.audio_output` → Audio output · `pricing.image` → Image · `pricing.image_output` → Image output · `pricing.web_search` → Web search · `pricing.internal_reasoning` → Internal reasoning · `pricing.request` → Per request · `pricing.overrides` → Conditional pricing

**Context & limits** — `top_provider.context_length` → Context length · `context_length` → Context length (model) · `top_provider.max_completion_tokens` → Max output

**Capabilities** — `reasoning` → Reasoning · `reasoning.default_enabled` → Reasoning default · `reasoning.default_effort` → Reasoning effort · `reasoning.supported_efforts` → Supported efforts · `reasoning.mandatory` → Reasoning required · `supported_parameters` → Supported parameters · `supported_voices` → Supported voices · `architecture.modality` → Modality · `architecture.input_modalities` → Input modalities · `architecture.instruct_type` → Instruct type

**Metadata** — `top_provider.is_moderated` → Moderated · `knowledge_cutoff` → Knowledge cutoff · `expiration_date` → Expiration date · `description` → Description · `name` → Name · `created` → Created · `links` → Links · `hugging_face_id` → Hugging Face ID

**Default parameters** — `default_parameters` → Default parameters · and the six leaves `frequency_penalty`, `presence_penalty`, `repetition_penalty`, `temperature`, `top_k`, `top_p` → Frequency penalty, Presence penalty, Repetition penalty, Temperature, Top-K, Top-P

Note `context_length` and `top_provider.context_length` are distinct fields that both occur; they must not share a label verbatim or the report becomes ambiguous.

---

## Value formatting

### Price display (A1)

Normalized to per-1M using the existing `canonical_price = raw * PRICE_MULTIPLIER / PRICE_DIVISOR` rule. Presented as five aligned table columns: old, arrow, new, unit, then delta and percent.

**Precision rule:** old, new, and delta all render at the **same** decimal precision — the greater of the two operands' significant decimal places, capped at 4. Consequences, all intended:

- A change in whole cents shows cents: `$2.00 → $3.50`, delta `+$1.50`.
- A change in the fourth decimal shows four: `$0.1500 → $0.1425`, delta `−$0.0075`.
- A sub-cent move is visually obvious as a sub-cent move rather than being rounded into invisibility.

`_fmt_price_per_m`'s current magnitude-based precision selection is replaced by this operand-based rule. `0` still renders as `free`.

### Alignment

Numeric columns are right-aligned with `font-variant-numeric: tabular-nums` and a fixed `<colgroup>`, so decimal points line up down the entire card.

### Counts

Thousands-separated. Delta shown with explicit sign: `+250,144`, `−131,072`.

### Booleans (E2)

Render `off → on`. Direction is `"up"`/`"down"`, semantic is `"capability"`. **No percent, no delta.** A pill reading `enabled` / `disabled` occupies the delta column.

### Added / removed values

The absent side renders as `—`. The delta column carries a neutral `added` / `removed` pill. No percent. `direction` is `"added"` / `"removed"`, `semantic` is `"coverage"`.

---

## Color semantics (B1)

Color is driven by `semantic`, never by `direction` alone.

| Semantic | Up | Down | Rationale |
|---|---|---|---|
| `cost` | red | green | Higher price is bad |
| `capacity` | amber | amber | Larger context is not "good" in the same axis; direction carried by the arrow |
| `capability` | blue | dim | On/off, not better/worse |
| `coverage` | blue | blue | Field appeared or disappeared |
| `neutral` | dim | dim | |

The practical effect: green and red appear **only** on money. A `↑ 227.7%` context increase and a `↑ 63.6%` price increase are never the same color again.

---

## Raw values (R1 + R2 + R3)

All three, together.

**Tooltip** (native `title`, on both the old and new price cells) contains, in order: scientific notation for the raw value, and the conversion math.

> `2.0e-6 · 0.000002 × 1,000,000 = $2.00`

Scientific notation removes zero-counting; the explicit multiplication answers "is this really $2.00 and not $0.20" without arithmetic. The literal raw value is present so the tooltip remains an audit surface.

**Field labels** also carry a `title` with the full dotted path.

**Raw-value toggle** — a single checkbox in the report header labeled "Show raw values". When checked, a dim, selectable sub-line appears beneath each price row showing `0.000002 → 0.0000035`. Implemented in CSS only, via a checkbox whose checked state is used by a sibling/`:has()` selector. Unchecked by default. This exists because `title` text cannot be selected or copied; the toggle produces text that can be pasted into a spreadsheet.

No JavaScript.

---

## Price Movement card (D1 + D3)

Order of elements:

1. **Header** — "PRICE MOVEMENT" and the verdict.
2. **Two headline movers**, side by side: biggest increase and biggest decrease. Each shows model ID, the field label, `old → new /1M`, absolute delta at the largest type size in the card, and percent.
3. **Tally chips**, two labeled groups.
4. **Collapsed affected-model list**, grouped into three buckets.

### Verdict (D3)

Derived from **model** buckets, matching the tally directly beneath it:

- One bucket strictly largest → "mostly higher" / "mostly lower".
- Otherwise → "mixed".

The verdict string appends the bucket counts: `mixed — 4 up, 4 down, 3 both`. This is a behavior change: the current implementation derives the verdict from *field* counts while displaying *model* counts, so 2026-07-25 currently reads "mostly lower" despite models being tied 4/4/3. It will now read "mixed". Historical reports are not regenerated.

### Headline movers

Selected by largest absolute per-1M delta across all price fields of all affected models — one model for the increase side, one for the decrease side. If no increases exist, that panel is omitted rather than shown empty; same for decreases.

`_PriceMovementSummary` and `_PriceMovementModel` ([reporting.py:81–148](../model_sentinel/reporting.py)) currently store only counts. They must additionally carry, per model, the largest absolute delta and the `RenderedChange` that produced it.

### Tallies

Two labeled chip groups, both stated in explicit units so they cannot be confused:

- `N MODELS` — `↑ n higher`, `↓ n lower`, `↕ n both`
- `N PRICE FIELDS` — `↓ n`, `↑ n`, `+n added`, `−n removed`

Bucket labels are short. The current sentence-form labels ("4 with increases and no decreases") are replaced. Zero-count buckets stay omitted.

### Affected-model list

Three columns: `↑ Higher only`, `↓ Lower only`, `↕ Both directions`. Model IDs only. Per E5, the provider label is omitted when exactly one provider has price changes; when more than one does, it is retained.

Each entry links to its card (see N1).

---

## Model cards (C1)

### Header

`<model id>` · display name · flex spacer · impact badge · `+N hidden` · back-link.

- **Impact badge** — `↑ costs more` / `↓ costs less` / `↕ both directions`, colored per B1. Only on cards with price changes.
- **`+N hidden`** (E3) — dim text, replaces today's full `SQUELCHED` section with its own uppercase header. Aggregate count across all categories on that card.
- **Back-link** (N1) — a small dim `↑` anchored to the Price Movement card.

### Table

**One `<table>` per card**, not one per category. A fixed `<colgroup>` with eight columns: category, field, old, arrow, new, unit, delta, percent. This is what makes columns align down the whole card; per-category tables auto-size independently and currently do not.

Rows are grouped by category in the existing order (Pricing, Context & Limits, Parameters, Capabilities, Other). The category name renders as a dim chip in column 1 on the **first row of each group only**; subsequent rows leave it blank. A slightly stronger top border marks each group boundary.

Within Pricing, rows sort by descending absolute delta so the largest move is first.

---

## Tiering and sorting (F1 + F2)

### Tier 1 — above the disclosure

1. Price Movement card
2. Added models
3. Removed models
4. Model cards that have **at least one price change**, sorted per F2

### Tier 2 — inside a single `<details>`

1. Model cards with no price changes (capability, parameter, metadata only), alphabetical
2. Provider-level squelched rollup
3. Change Summary (itself collapsed, per E6)

Summary line on the disclosure states what is inside, with counts.

### Sort key (F2)

Applied to tier-1 model cards, in order:

1. **Absolute per-1M delta**, descending — the largest `delta_abs` across the model's price fields, **rounded to cents** before comparison.
2. **Percent change**, descending — the percent of the field that produced the primary key.
3. **Coverage count**, descending — number of price fields added or removed.
4. **Model ID**, ascending.

The rounding in step 1 is required for step 2 to ever apply. Without it, exact float ties are vanishingly rare and the percent tiebreaker would be dead code. Rounding to cents means two models that both move ~$1.40 tie on the primary key and are then correctly ordered by relative impact.

**Accepted consequence:** sub-cent moves all round to `$0.00` and tie on the primary key, so they are ordered by percent, then coverage, then alphabetically. These are negligible moves and their mutual ordering does not carry meaning.

Models whose only price change is an addition or removal have no `delta_abs`; they sort as `0.00` on the primary key and are separated by the coverage tiebreaker.

---

## Navigation (N1)

**Anchors.** Every model card gets a stable `id`. Model IDs contain `/`, `.`, `:`, and `~`, so they need slugification: lowercase, non-alphanumerics to `-`, collapse runs, prefix with `m-`.

**Collision handling is mandatory, not theoretical.** Providers emit alias entries prefixed with `~`, so paired IDs of the form `~vendor/model-latest` and `vendor/model-latest` occur together in a single report and would collide under naive stripping. Disambiguate deterministically — a stable suffix on the second and later occurrences within a report, assigned in render order.

**Links into cards** from: Price Movement affected-model list entries, Price Movement headline movers, and Change Summary rows.

**Links back** from each card header to `#price-movement`. The browser back button already returns you; the explicit link is for discoverability.

**Landing feedback.** `:target` CSS applies a brief highlight to the card that was jumped to, so it is obvious where you landed among visually similar cards.

**Constraint:** do not generate links that point *into* tier 2, because fragment navigation into a closed `<details>` is not reliable across browsers. All price-movement link targets live in tier 1 by construction. Change Summary rows live in tier 2 and link *outward* into tier 1, which is fine. Rows in the Change Summary that reference a tier-2 model render as plain text, not links.

N3 (a filter box) is explicitly deferred — it would introduce the first JavaScript into the report.

---

## Cross-renderer behavior matrix

Which changes apply where. This is the answer to "fix it everywhere, not just for E1/E2".

| Change | Concise HTML | `_full.html` | Text | Markdown | JSON | `changes` HTML |
|---|---|---|---|---|---|---|
| E1 `null → null` suppression | yes | yes | yes | yes | **no** | yes |
| E2 boolean rendering | yes | yes | yes | yes | **no** | yes |
| Field labels | yes | yes | yes | yes | **no** | yes |
| Delta precision rule | yes | yes | yes | yes | **no** | yes |
| A1 price layout | yes | no | n/a | n/a | no | yes |
| B1 color semantics | yes | no | n/a | n/a | no | yes |
| C1 single table | yes | no | n/a | n/a | no | no |
| D1/D3 price movement | yes | no | n/a | n/a | no | n/a |
| E3–E6, F1, F2, N1, R1–R3 | yes | no | no | no | no | no |

JSON is full-fidelity and unchanged in every row, including `noop` entries — audit output must not silently drop records.

`_full.html` inherits the semantic fixes (E1, E2, labels, precision) because they are correctness issues, but keeps its current layout because it is the audit view.

---

## Implementation sequencing

Order matters. Steps 1 and 2 are preconditions.

1. **Characterization tests.** Before any behavior change, add tests capturing current text, markdown, HTML, and JSON output for a fixture exercising all six classification branches plus: a price addition, a price removal, a boolean in each direction, a `null → null` pair, a list diff, and a dynamic `pricing.overrides[...]` path. Land these green against unmodified code. Without them the refactor is unverifiable.

2. **Extract `change_render.py`.** Move the shared primitives, introduce `RenderedChange` and the classifier, and rewrite the six render functions to consume it. **No behavior change intended in this step** — the characterization tests must still pass untouched. Any test that needs editing here is a regression, not an expected change.

   Note the ordering trap: the classifier gains the `noop` kind in this step, but renderers must **not** yet skip `noop` entries, and labels must still resolve to the raw dotted path. Suppression (E1) and labeling switch on in step 3. Turning them on early makes step 2 unverifiable, because the characterization tests would then legitimately need edits and could mask a real regression.

3. **Semantic fixes**: E1, E2, field labels, precision rule. Characterization tests are updated deliberately, with the expected new output.

4. **Concise HTML layout**: A1, B1, C1, plus the CSS.

5. **Price Movement card**: D1, D3, including the `_PriceMovementSummary` extension to carry deltas.

6. **Page structure**: E3–E6, F1, F2.

7. **Navigation and raw values**: N1, R1–R3.

---

## Test criteria

New tests, beyond the characterization suite:

**Classification** — one test per `kind`. Explicitly: `null → null` classifies as `noop`; a boolean never produces a percent; a price addition produces `direction == "added"` and `semantic == "coverage"`; a `pricing.overrides[cond].completion` path resolves to label "Output" with the condition in `qualifier`.

**Labels** — exact match wins over suffix match; unmatched path falls back to prettified leaf; `field_path` is preserved in every case; `context_length` and `top_provider.context_length` produce distinct labels.

**Precision** — a cents-level change renders 2dp on old, new, and delta; a 4th-decimal change renders 4dp on all three; the three are always consistent with each other.

**Color semantics** — a price increase and a context increase in the same fixture produce different CSS classes. Assert on the class names, so a future change that re-merges them fails.

**Sort** — assert the full four-level ordering, including a constructed case where two models tie after cents-rounding and are separated by percent, and a case separated only by coverage count.

**Verdict** — a 4/4/3 model split yields "mixed", not "mostly lower". This is the regression test for the current defect.

**Anchors** — slugs are unique within a report; `~vendor/model` and `vendor/model` in the same report produce different IDs. Assert no generated link targets an ID inside tier 2.

**Structure** — a card with three categories emits exactly one `<table>`; `null → null` rows are absent from HTML, text, and markdown, and **present** in JSON.

Full suite must pass:

```bash
pytest
```

Baseline at design time: 56 passed. By format, existing tests exercise text 15×, HTML 15×, JSON 3×, markdown 2×.

---

## Risks

**Markdown is the thin spot.** Only two existing tests exercise markdown, against fifteen each for text and HTML. A markdown regression during step 2 is the most likely failure to escape review. The characterization tests must cover markdown at parity with the others; this is the single highest-value mitigation in the plan.

**`_render_scan_html` is 163 lines and `_render_changes_html` 133.** Both will need restructuring for F1/F2. Neither should grow. If either exceeds its current size after the change, that is a signal the tiering logic belongs in a separate builder function rather than inline.

**The verdict change is user-visible and silent.** Reports generated before and after will disagree on days with tied model buckets. Called out here so it is not mistaken for a bug later.

**Scope.** Roughly 250–300 new lines in `change_render.py`, ~300 lines rewritten across six render functions, plus CSS. reporting.py should shrink from 2,849 lines.

---

## Open assumptions

Flagged for review; each was a judgment call, not an instruction.

1. **Cents is the right rounding granularity** for the F2 primary sort key. Coarser loses distinctions between real moves; finer makes the percent tiebreaker dead code.
2. **Precision is capped at 4 decimal places.** Values needing more render at 4 and rely on the tooltip for exactness.
3. **`context_length` is labeled "Context length (model)"** to distinguish it from `top_provider.context_length`. Both occur in the data; the disambiguating wording is a guess at intent.
4. **Change Summary rows for tier-2 models render as plain text** rather than links, to avoid fragment navigation into a closed `<details>`.
