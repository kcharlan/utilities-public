# Report Readability Redesign — Design

Status: **implemented** in the current code.

This document has been corrected in place where implementation diverged from the approved design. Ten such divergences are marked inline and recorded under [Amendments during implementation](#amendments-during-implementation). Where the design and the shipped code disagree, **the code is authoritative** — read the amendments before trusting an unmarked passage.

This design extends the report-detail policy described in
[`DESIGN.md`](./DESIGN.md). Detail-policy semantics (squelch patterns and
`--detail` modes) are unchanged.

## Goal

The concise HTML scan report is a **triage** artifact: answer "what moved, by how much, and does it matter to me" in seconds. The `_full.html` companion, JSON, text, and markdown outputs remain the audit surface.

Three problems drive this work:

1. Pricing changes are hard to read. Raw provider values lead, normalized values are parenthetical, old and new sit in distant columns, and only a percentage is shown — so absolute impact is invisible.
2. Red/green means "cost direction" in one table and "capacity direction" in the next, inside the same card.
3. The page is dominated by low-signal content: repeated squelch notices, `null → null` rows, a duplicated summary table, and alphabetical ordering that buries the largest movers.

## Non-goals

- Changing what is collected, stored, or squelched.
- Changing JSON output shape (full fidelity, unchanged).
- ~~Changing `_full.html` layout. It keeps today's rendering.~~ **Corrected —
  see Amendment 1.** `_full.html` is not a separate renderer:
  [`cli.py`](../model_sentinel/cli.py) generates it by calling the same
  `render_scan_report` with `make_report_detail_policy(mode="all")`. It
  therefore receives every layout change automatically, and holding its
  layout back would require building a second renderer that does not exist.
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

### The core problem the redesign addressed

Before the redesign, `_render_smart_change_text` (text and Markdown) and
`_render_html_table_row` independently implemented the same classification
cascade, while `_build_summary_entries_from_fc` contained a third partial copy.
List and bulk-list rendering had the same duplication.

The implemented architecture consolidates that logic so E1, E2, A1, B1,
labels, and precision have one semantic source.

### Shared module: `model_sentinel/change_render.py`

Owns classification, labeling, and value formatting. Format-agnostic — it returns data, never markup.

**Primary entry point:** `classify_change()` accepts a `FieldChange` and the
resolved `ProviderProfile`, then returns one frozen dataclass instance
describing the change in rendered-but-medium-neutral terms.

**The dataclass** (name it `RenderedChange`) carries at minimum:

- `kind` — the classification branch taken. Literal of: `"price"`, `"count"`, `"numeric"`, `"boolean"`, `"list"`, `"scalar"`, `"noop"`.
- `field_path` — the original dotted path, always preserved for tooltips and audit output.
- `label` — the display label from the registry (see below).
- `qualifier` — optional condition text extracted from a bracketed dynamic path, e.g. the condition in `pricing.overrides[min_prompt_tokens=200000].completion`; `None` for ordinary fields.
- `old_display` / `new_display` — the formatted human values (`"$2.00"`, `"262,144"`, `"off"`, `"—"`).
- `old_raw` / `new_raw` — original provider values as strings, for tooltips and the raw-value toggle.
- `unit` — `"/1M"`, `"tok"`, or `None`. ~~`"items"`~~ **dropped — see Amendment 8:** a list change has no operand row for a unit to sit beside.
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
| `_render_bulk_list_diff_text` / `_render_html_bulk_list_diff` | Same. **Deferred out of step 2, then completed — see Amendment 4.** |
| Numeric, percent, price, list, and scalar formatting primitives | Live in `change_render.py`; `reporting.py` consumes their classified result |
| Field categorization and price/count predicates | Live on `ProviderProfile`, with generic defaults in `provider_profiles.py` |

The former percent-when-old-is-zero behavior was the root cause of the blank
Change cell on `0 → 1` booleans. It is fixed by the boolean branch never
reaching percent logic (E2), not by treating flags as numeric magnitudes.

---

## Field label registry

### Structure

Each registered `ProviderProfile` owns two trivially editable mappings in
`provider_profiles.py`; `change_render.py` resolves labels through the active
profile. This keeps provider vocabulary out of the shared classifier.

Lookup is two-stage, in order:

1. **Exact match** on the full dotted path.
2. **Suffix match** on the final path segment, so dynamically-generated paths resolve. `pricing.overrides[min_prompt_tokens=200000].completion` has leaf `completion` and resolves to "Output".

Unmatched fields fall back to a prettified leaf: split on `_`, sentence-case. `hugging_face_id` → "Hugging face id". The full dotted path is **always** available in the tooltip regardless of whether a label was found.

### Dynamic path handling

When a path segment contains a bracketed condition, strip it for label lookup and surface it as `qualifier`. The condition renders as a parenthetical after the label: **Output** *(min_prompt_tokens=200000)*. Formatting the condition into prose is out of scope; render it literally.

### OpenRouter registry contents

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

**Sentinel rule (amended — see Amendment 2).** The cap at 4 is real, but "render at 4 and rely on the tooltip for exactness" is not, because rounding a non-zero value to 4 places can produce `$0.0000` and `0.0%` — figures that assert *no change* where a change was measured. A column that would round to a degenerate value therefore prints a **bounded sentinel** instead:

| Column | Sentinel |
|---|---|
| Price | `<$0.0001`, `-<$0.0001` |
| Price delta | `+<$0.0001`, `-<$0.0001` |
| Count / numeric | `<0.01`, `-<0.01` |
| Percent | `↑ <0.1%`, `↓ <0.1%` |

The bound is the column's own printable width, so a reader can verify it from what is on screen. Sign is carried outside the bound (`-<$0.0001`, never `$-0.0001`), and the rule lives in one place rather than at each call site.

**Accepted residual: displayed arithmetic need not close under rounding.** A row may read `$2.00 → $2.00` with delta `+<$0.0001`, which does not visibly add up. This is accepted deliberately. Each cell states a true proposition — both prices really do round to `$2.00` at the row's precision, and the movement really is non-zero and smaller than `$0.0001` — even though the row as a whole cannot be checked by eye at that width. The rejected alternative, printing `+$0.0000`, makes the row close by stating something false.

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

**List membership takes `capability`'s pair (amended — see Amendment 8).** The table above says nothing about the `+ member` / `− member` glyphs of a list change, which are not a delta cell and have no `direction`. They are colored blue for an arrival and dim for a departure, matching `capability` up/down, by **one global CSS rule with no per-card override** — a list gaining `logit_bias` is a capability change, and the `+`/`−` glyphs already carry the add-vs-remove distinction that green/red would otherwise duplicate on the one axis B1 reserves.

---

## Raw values (R1 + R2 + R3)

All three, together.

**Tooltip** (native `title`, on both the old and new price cells) contains, in order: the literal raw value, its magnitude in scientific notation as a **parenthetical aside**, and the conversion math.

> `0.000002 (2.0e-6) × 1,000,000 = $2.00`
>
> `2.5 (2.5e0) = $2.50` — a provider needing no conversion (`multiplier == divisor == 1`) gets no factor clause rather than a `× 1` that would read as a conversion.

Scientific notation removes zero-counting; the explicit multiplication answers "is this really $2.00 and not $0.20" without arithmetic. The literal raw value is present so the tooltip remains an audit surface.

**Amended — see Amendment 5.** The design originally specified `2.0e-6 · 0.000002 × 1,000,000 = $2.00`, joining the two with a middle dot. That is unusable: a `·` immediately after a scientific mantissa reads as multiplication, so the stated expression evaluates to 4e-6 rather than $2.00, and with no conversion factor it degrades to `2.5e0 · 2.5 = $2.50` — a bare `A · B = C` in which C is neither operand nor their product. The tooltip exists so a reader can verify a price *without* doing arithmetic; a separator that can be mistaken for an operator defeats the whole feature. Parenthesising the magnitude makes it an aside, leaving exactly one operator chain between the leading operand and the `=`.

The scientific notation is built with `Decimal` on the provider's own string with no format spec, so it is exact rather than rounded, and is `None` on a non-finite value (the tooltip then carries the raw value alone). Where the cell's display is a sentinel, the tooltip's right-hand side is that same bound: `1e-06 (1.0e-6) = <$0.0001` reads "equals less than $0.0001", which is what the bound asserts.

**Field labels** also carry a `title` with the full dotted path.

**Raw-value toggle** — a single checkbox in the report header labeled "Show raw values". When checked, a dim, selectable sub-line appears beneath each price row showing `0.000002 → 0.0000035`. Implemented in CSS only, via a checkbox whose checked state is used by a sibling/`:has()` selector. This exists because `title` text cannot be selected or copied; the toggle produces text that can be pasted into a spreadsheet.

**Default state (amended — see Amendment 1):** unchecked in the concise report, **checked when the detail mode is `"all"`**. That is what lets `_full.html` adopt the concise layout without ceasing to be an audit view — the raw numbers it exists for are inline from the moment it opens.

No JavaScript.

---

## Price Movement card (D1 + D3)

Order of elements:

1. **Header** — "PRICE MOVEMENT" and the verdict.
2. **Two headline movers**, side by side: biggest increase and biggest decrease. Each shows model ID, the field label, `old → new /1M`, absolute delta at the largest type size in the card, and percent.
3. **Tally chips**, two labeled groups.
4. **Collapsed affected-model list**, grouped into four buckets.

### Verdict (D3)

Derived from **model** buckets, matching the tally directly beneath it:

- One bucket strictly largest → "higher" / "lower", qualified by "mostly" **only when some model falls outside the leading bucket** (amended — see Amendment 3).
- Otherwise → "mixed".
- **Fourth outcome (amended — see Amendment 7):** when no model moved in either direction and every price change is a field appearing or disappearing, the verdict is `price fields added/removed`, not "mixed".

The qualifier is dropped on a unanimous population: five models up and none down reads `higher — 5 up`, not `mostly higher — 5 up`. As originally written the rule hedged a result that had nothing to hedge — "mostly" invites the reader to look for the exception, and there is none. Unanimity is tested by summing every non-leading bucket rather than by checking the runner-up alone, so the check does not lean on the sort order to imply the third bucket is empty too.

The verdict string appends the bucket counts: `mixed — 4 up, 4 down, 3 both`.
Before the redesign, the verdict was derived from *field* counts while the
display showed *model* counts, so a 4/4/3 model split could read "mostly
lower." The implemented model-count rule reads "mixed." Historical reports
are not regenerated.

### Headline movers

Selected by largest absolute per-1M delta across all price fields of all affected models — one model for the increase side, one for the decrease side. If no increases exist, that panel is omitted rather than shown empty; same for decreases.

`_PriceMovementSummary` and `_PriceMovementModel` carry, per model, the largest
absolute delta and the `RenderedChange` that produced it, in addition to
counts.

### Tallies

Two labeled chip groups, both stated in explicit units so they cannot be confused:

- `N MODELS` — `↑ n higher`, `↓ n lower`, `↕ n both`, and `± n added/removed only` (amended — see Amendment 7)
- `N PRICE FIELDS` — `↓ n`, `↑ n`, `+n added`, `−n removed`

Bucket labels are short. The current sentence-form labels ("4 with increases and no decreases") are replaced. Zero-count buckets stay omitted.

### Affected-model list

~~Three columns~~ **Four (amended — see Amendment 7):** `↑ Higher only`, `↓ Lower only`, `↕ Both directions`, `± Added/removed only`. Model IDs only. Per E5, the provider label is omitted when exactly one provider has price changes; when more than one does, it is retained.

Each entry links to its card (see N1).

---

## Model cards (C1)

### Header

~~`<model id>` · display name · flex spacer · impact badge · `+N hidden` · back-link.~~ **Corrected — see Amendment 6.** The impact badge was dropped; the header is `<model id>` · display name · flex spacer · `+N hidden` · back-link.

- ~~**Impact badge** — `↑ costs more` / `↓ costs less` / `↕ both directions`, colored per B1. Only on cards with price changes.~~ **Dropped — see Amendment 6.**
- **`+N hidden`** (E3) — dim text, replaces today's full `SQUELCHED` section with its own uppercase header. Aggregate count across all categories on that card.
- **Back-link** (N1) — a small dim `↑` anchored to the Price Movement card.

### Table

**One `<table>` per card**, not one per category. A fixed `<colgroup>` with eight columns: category, field, old, arrow, new, unit, delta, percent. This is what makes columns align down the whole card; per-category tables auto-size independently and currently do not.

Rows are grouped by category in the existing order (Pricing, Context & Limits, Parameters, Capabilities, Other). The category name renders as a dim chip in column 1 on the **first row of each group only**; subsequent rows leave it blank. A slightly stronger top border marks each group boundary.

~~Within Pricing, rows sort by descending absolute delta so the largest move
is first.~~ **Superseded on 2026-08-08 — see Amendment 10.** Pricing rows now
use the active provider profile's stable semantic order: OpenRouter presents
Input, cache variants, and Output first, followed by unranked Pricing fields
alphabetically.

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
| A1 price layout | yes | **yes** | n/a | n/a | no | yes |
| B1 color semantics | yes | **yes** | n/a | n/a | no | yes |
| C1 single table | yes | **yes** | n/a | n/a | no | no |
| D1/D3 price movement | yes | **yes** | n/a | n/a | no | n/a |
| E3–E6, F1, F2, N1, R1–R3 | yes | **yes** | no | no | no | no |

JSON is full-fidelity and unchanged in every row, including `noop` entries — audit output must not silently drop records.

**The `_full.html` column reads "yes" throughout, and the original "no"s were
wrong.** `_full.html` has no renderer of its own —
[`cli.py`](../model_sentinel/cli.py) builds it from the same
`render_scan_report` with `make_report_detail_policy(mode="all")` — so it
inherits A1/B1/C1 and the rest. The audit-specific question is raw-value
visibility: A1 moves the provider's literal number out of the main cell and
into a tooltip and a toggle-controlled sub-line.

**Resolution implemented:** the R3 "Show raw values" checkbox defaults to **checked** when the detail mode is `"all"`. The audit view therefore renders the new layout with every raw value inline and selectable, and no second renderer is needed. See Amendment 1.

---

## Open assumptions

Flagged for review; each was a judgment call, not an instruction.

1. **Cents is the right rounding granularity** for the F2 primary sort key. Coarser loses distinctions between real moves; finer makes the percent tiebreaker dead code.
2. ~~**Precision is capped at 4 decimal places.** Values needing more render at 4 and rely on the tooltip for exactness.~~ **No longer holds — see Amendment 2.** Rounding to 4 places turns a measured change into `$0.0000` / `0.0%`, which denies the change rather than approximating it. Values that would round to a degenerate figure now print a bounded sentinel (`<$0.0001`, `+<$0.0001`, `↑ <0.1%`); see the sentinel rule under "Price display (A1)".
3. **`context_length` is labeled "Context length (model)"** to distinguish it from `top_provider.context_length`. Both occur in the data; the disambiguating wording is a guess at intent.
4. **Change Summary rows for tier-2 models render as plain text** rather than links, to avoid fragment navigation into a closed `<details>`.

---

## Amendments during implementation

Ten places where the shipped behavior differs from the design above. Each is marked inline at the point it applies; this section records what changed and why.

### 1. `_full.html` is not a separate renderer, and adopts the new layout

**Design said:** `_full.html` keeps today's layout and inherits only the semantic fixes (E1, E2, labels, precision).

**Reality:** there is no second renderer to hold back.
[`cli.py`](../model_sentinel/cli.py) produces `_full.html` from the same
`render_scan_report` call with `make_report_detail_policy(mode="all")`, so A1,
B1, C1 and everything after them apply to it automatically. Withholding them
would have meant writing and maintaining a second renderer.

**Resolution:** let it inherit, and close the one real gap. A1 moves the provider's literal value out of the cell, which is precisely what an audit reader opens `_full.html` for; so the R3 "Show raw values" checkbox **defaults to checked when the detail mode is `"all"`**. The audit view gets the readable layout with every raw value inline and selectable. The cross-renderer matrix's `_full.html` column was corrected from "no" to "yes" throughout.

### 2. The 4-decimal cap was replaced by bounded sentinels

**Design said (Open Assumption #2):** values needing more than 4 decimals render at 4 and rely on the tooltip for exactness.

**Reality:** rounding a measured non-zero movement to 4 places produces `$0.0000` and `0.0%` — figures that assert *no change*. A report whose job is to say what moved cannot print a value that denies the movement it just detected.

**Why the reversal, and not more tuning:** three successive precision "escape hatches" were attempted and all three failed the same way — each fixed the column it was aimed at and pushed the contradiction into another (fix the delta, the percent lies; fix the percent, the operands do). Three corrective rules that still produced inconsistent results was taken as evidence the approach was wrong rather than under-tuned, and all three were removed in favour of one rule applied uniformly: **a column that would round to a degenerate value prints a bounded sentinel** — `<$0.0001`, `+<$0.0001`, `↑ <0.1%` — rather than a false zero. The bound is the column's own printable width, so the reader can verify it from what is on screen.

**Accepted residual:** displayed arithmetic no longer closes under rounding. A row can read `$2.00 → $2.00` with delta `+<$0.0001` and not visibly add up. This is accepted: every cell states a true proposition, and only the row-level sum is illegible at that width. The rejected alternative made the row close by printing something false, which is strictly worse — a reader who checks the arithmetic and finds it consistent has been *misled*, where a reader who finds it incomplete has merely been told the column is too narrow.

### 3. The verdict drops "mostly" on a unanimous population

**Design said (D3):** one bucket strictly largest → "mostly higher" / "mostly lower".

**Reality:** five models up and none down produced `mostly higher — 5 up`. "Mostly" invites the reader to hunt for the exception, and there is none — the hedge is not merely redundant, it misdescribes the data.

**Resolution:** drop the qualifier when **both** non-leading buckets are empty (`higher — 5 up`); keep it otherwise (`mostly higher — 4 up, 1 down`). Unanimity is tested by summing every non-leading bucket rather than inspecting the runner-up alone, so the check does not silently depend on the sort order to imply the third bucket is empty too.

### 4. Task 3's step-4 exemption, and its later resolution

**Design said (step 2 / the retirement table):** all six render functions move onto `RenderedChange` in one step, with no behavior change.

**Reality:** two of them could not. `_render_bulk_list_diff_text` and `_render_html_bulk_list_diff` shared their member stringification with `_list_change_signature`, the bulk grouping key, and the two conventions disagreed on structured members — the signature path JSON-encoded them (`{"a": 1}`) while the per-model renderers used Python `repr` (`{'a': 1}`). Moving the bulk renderers while that disagreement stood would have changed bulk-group output as a side effect of a step declared behavior-neutral, and the goldens of the day did not cover bulk grouping, so the change would have landed unobserved. Both functions were left calling the old helper, with the reason recorded at each site.

**Resolution:** the two conventions were later unified on **JSON** (user decision), both renderers were moved onto `RenderedChange`, and the shared `_list_item_text` now lives in `change_render.py` with `_list_change_signature` routed through it. The exemption is closed and the retirement table's row is accurate again.

### 5. The raw-value tooltip's notation

**Design said:** `2.0e-6 · 0.000002 × 1,000,000 = $2.00`.

**Reality:** a middle dot immediately after a scientific-notation mantissa reads as multiplication. The stated expression evaluates to 4e-6, not $2.00, so the tooltip appears to contradict the cell it is explaining — and with no conversion factor it degrades further, to `2.5e0 · 2.5 = $2.50`, a bare `A · B = C` whose C is neither operand nor their product. The tooltip's entire purpose is letting a reader verify a price *without* doing arithmetic; a separator that can be read as an operator defeats it.

**Resolution:** parenthesise the magnitude so it is an aside rather than an operand — `0.000002 (2.0e-6) × 1,000,000 = $2.00`, and `2.5 (2.5e0) = $2.50` where no conversion applies. Everything else is unchanged: `Decimal` on the provider string with no format spec, `None` on a non-finite value, and a bounded right-hand side where the cell itself is a sentinel.

### 6. The card's impact badge was dropped, not built

**Design said (C1, Header):** each card with price changes carries an impact badge in its header — `↑ costs more` / `↓ costs less` / `↕ both directions`, colored per B1.

**Reality:** no such string and no such CSS class was ever written. This is recorded as a deliberate drop rather than an outstanding gap, because building it now would add a third statement of something the page already states twice:

* **the card itself already says it, per row and more precisely.** C1 gives every row a delta and a percent column colored by B1, so a card whose prices moved up is a card with red in its delta column. A header badge reading `↑ costs more` summarises the rows immediately beneath it, at the cost of being the only element on the card that can disagree with them;
* **the Price Movement card already says it, by name.** D1/D3's affected-model list groups every affected model into `↑ Higher only`, `↓ Lower only`, `↕ Both directions` and `± Added/removed only`, and each entry links to its card. A reader who wants "which models cost more" has that list, complete and sorted, before reaching any card.

The badge would also have been the fourth place the higher/lower/both trichotomy is spelled (buckets, tallies, verdict, badge), and the one furthest from the data it describes.

**Resolution:** the header is `<model id>` · display name · flex spacer · `+N hidden` · back-link. The C1 Header section is struck through in place.

### 7. A fourth price-movement bucket, and a fourth verdict outcome

**Design said (D3, Tallies, Affected-model list):** three model buckets — `↑ Higher only`, `↓ Lower only`, `↕ Both directions` — and three verdict outcomes — "higher", "lower", "mixed".

**Reality:** a model whose only price change is a price field *appearing* or *disappearing* belongs to none of the three. It has no direction: B1 already rules that painting an added price red would claim a rise that was never measured, and the same reasoning denies it a directional bucket.

Left in the three-bucket shape, such a model was still counted in the `N MODELS` tally and still had a card, but appeared in no column of the affected-model list directly beneath that tally — so the total did not match the rows under it, which is exactly the class of internal disagreement D3 exists to remove. And a report in which *every* price change is a coverage change produced the verdict "mixed", asserting a mixture of directions where not one direction had been observed.

**Resolution:** a fourth bucket `± Added/removed only` (`coverage`), carried in the same `_PRICE_MOVEMENT_BUCKETS` table as the other three so the column label, the chip label and the colour stay one decision; and a fourth verdict string `price fields added/removed`, returned when no directional bucket holds a model. The `± ` glyph and the `price-coverage` blue are deliberately not any of the three directional pairs.

### 8. B1 and A1 reach the `changes` table and the Change Summary; text and markdown do not move

**Design said:** the cross-renderer matrix already scopes "B1 color semantics" and "A1 price layout" to `changes` HTML with a **yes**, and marks Text/Markdown `n/a`.

**Reality:** two HTML surfaces were left behind, and both were caught by a whole-branch review rather than by a test.

* **The `changes` table colored by `direction`.** `_render_html_table_row` never consulted the semantic table, choosing instead from a private `delta-increase` / `delta-decrease` / `delta-neutral` / `delta-price-*` vocabulary keyed on direction. In the shipped document a context window doubling read **green**, a max output halving read **red**, an added coverage field read **green**, and an informational scalar read **amber** — the precise confusion B1 exists to remove, in the one document with a table of its own. The six direction-named CSS rules are deleted, not merely bypassed, so there is no working second vocabulary left to reach for.
* **List membership was colored per card type.** Blue/dim inside `.card-table` and green/red everywhere else, so one document showed the same membership change blue in a model card and green in a bulk-change card — the same green the Price Movement card uses for a price cut — and green/red again in the `changes` report's standalone list-diff block. Fixed with **one global rule** rather than a per-card-type override, per the note added to the B1 section: no card type and no document wants green here, and a second override would have been a second place for the decision to drift.

**A1 in the Change Summary.** The summary's `Change` cell was built by rendering the *text* report's line and splitting it on `": "`, which imported text's raw-value-first convention into HTML wholesale: the card read `$2.00 → $3.00  /1M  +$1.00  ↑ 50.0%` while the summary index a few inches below read `2e-06 → 3e-06 ($2.00 → $3.00 / 1M, ↑ 50.0%)`. The concise report was hiding raw values in the card and printing them, unconditionally and outside the "Show raw values" toggle, in the index. The cell is now composed from `RenderedChange` in the card's own column order — `old → new unit (delta, pct)` — which also removes the fragile split (a dynamic path such as `pricing.overrides[min_prompt_tokens=200000].completion` puts provider payload text on the left of a `": "`) and makes an absent side unspellable as `null` rather than respelled after the fact.

**`unit` is `None` for a list change**, where the dataclass spec said `"items"`. Every renderer that prints `unit` prints it beside a pair of operands — the card's unit column, the price headline, and now the summary's `old → new unit` — and a list change has no operand row: its counts live inside the `(1 → 2)` parenthesis beside the member names. `"items"` was set at construction, read by nothing, and would have rendered `+logit_bias (1 → 2) items` the moment anything read it.

**Text and markdown are deliberately unchanged** by all of the above. `null` is what `change_render` produces for an absent side and what the text renderer prints; `_SummaryEntry` feeds the HTML summary table and nothing else. The text, markdown and JSON goldens are the audit trail for this branch, and they did not move.

### 9. Duplicate provider labels are a healthcheck warning, not a `ConfigError`

**Design said:** nothing — this rule was added during implementation, as a hard `ConfigError` raised from `load_config`.

**Reality:** by the time it shipped it was redundant *and* the harshest possible response to a working config. This branch already made label collisions harmless: reports group on `provider_id` and disambiguate display as `Label (provider_id)`, which also covers historical rows recorded under a label the current `providers.env` no longer contains — rows a config-time check cannot see at all. So the complete mechanism was the display one, and the incomplete one was the mechanism that halted `scan`, `changes`, `history` and `providers` alike. A scheduled overnight scan would stop on a config that worked yesterday, and the report the user would have received does not exist; that is strictly worse than a report whose two providers share display text and whose rows say which is which.

**Resolution:** `config.describe_duplicate_labels(providers, path)` returns the advisory string or `None`, and `healthcheck` surfaces it as a `provider_labels` check with status `warn` — which does **not** move the exit code. The message still names every offender and the key to edit, and still compares labels exactly. `healthcheck` is the command whose job is to tell the user what to fix; refusing to run every other command was never that job.

### 10. Pricing rows use provider-defined semantic order

**Amended 2026-08-08.**

**Design said (C1):** within a model card, Pricing rows sort by descending
absolute delta so the largest movement appears first.

**Reality:** actual reports exposed cross-model schema drift. Because Input,
Cache, and Output often moved by different amounts, their positions changed
from one model card to the next. The impact sort elevated movement but made
otherwise identical Pricing groups harder to scan and compare.

**Resolution:** stable semantic order wins within every human-readable Pricing
group. The active provider profile owns the preferred field sequence;
OpenRouter presents Input, cache variants, and Output first, followed by
unranked Pricing fields alphabetically. Scan text, Markdown, concise and
full-detail HTML, `changes` text and HTML, and the HTML Change Summary share
that order. This is presentation-only: JSON, chronological history, and stored
source field order do not change.

D1 and F2 remain intact. The Price Movement headline still selects the largest
dollar movers, and price-changed model cards are still ranked by impact across
the page. The amendment removes row-level permutation without weakening the
report's page-level triage priorities.

### 11. Price display and absolute impact use provider-owned field units

**Amended 2026-08-15.**

The fixed `/1M` assumption in A1, D1, R1, summary details, and the unit column
is superseded. Every monetary change resolves one immutable provider-owned
rule, and every human surface consumes that rule's effective conversion and
unit. OpenRouter token rates display `/1M tokens`; search, request, and image
rates retain their own denominators, while an unregistered monetary leaf is
shown conservatively as `/unit unknown`. Raw provider literals remain visible
in the existing audit surfaces, and JSON/history storage is unchanged.

Direction, percentages, Price Movement tallies and model buckets, Change
Summary membership, and tier-one inclusion still cover all monetary fields.
Absolute values from unlike denominators are never compared. D1's global
panels are now labeled “Biggest token-rate increase/decrease” and consider
only OpenRouter's declared primary token comparison group. F2 scores that same
primary group; non-primary-only and coverage-only monetary models remain tier
one, follow scored token movers, and sort by model ID. The wider unit column
wraps long unit labels at narrow widths.
