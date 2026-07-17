# Drawdown Pin-Editing Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-07-11-drawdown-pin-editing-design.md` — read it before starting. The spec is the authority on behavior; this plan is the authority on task order and boundaries.

**Goal:** Fix the pin system's phantom-override bug and extend it with a visible left-gutter pin control, direct in-table cell editing, a read-only sidebar Adjustments panel, and CSV override notation.

**Architecture:** All work happens inside the single self-contained file `Calculation tools/drawdown.html` (embedded CSS + vanilla JS, no build step, no dependencies). The existing pin data model (`state.pins` = array of `{ at_month, overrides }`, applied in month order by `simulate()`) is unchanged; every new surface reads/writes that same model.

**Tech Stack:** Plain HTML/CSS/JS. Verification via a local static server and browser automation (Playwright MCP) or manual browser checks.

## Global Constraints

- The app MUST remain one self-contained HTML file: `Calculation tools/drawdown.html`. No external JS/CSS files, no new dependencies, no build step.
- The path contains a space — always quote it in shell commands.
- No pin persistence of any kind (no localStorage, no URL state). Fresh page load = zero pins. This is a spec non-goal, not an omission.
- No changes to simulation semantics in `simulate()`: pin application order, epoch reset, inflation compounding, termination rules all stay as-is. (Task 1 changes what gets *saved* into pins, not how pins are *applied*.)
- Match the existing design language: Fraunces/Hanken Grotesk/JetBrains Mono, the CSS custom-property palette (`--ochre`, `--ink-fade`, etc.), existing `.group` / caption / italic-hint patterns. No animations beyond what exists, no pulses, no coach marks.
- Line numbers cited below are from the pre-change file and will drift as tasks land — anchor by function name and quoted text, not by line number.
- There is no automated test suite for this project (per repo validation matrix, HTML calculators are browser-smoke-tested). Each task ends with browser verification against the served page, then a commit. Serve with: `cd "Calculation tools" && npx --yes http-server -p 4199 -a 127.0.0.1 --silent` and load `http://127.0.0.1:4199/drawdown.html`. If the Playwright MCP is available, use it (snapshot/evaluate/click); otherwise verify manually and record what you observed. When dispatching `input` events programmatically to these fields, set the value via the native `HTMLInputElement` value setter and then dispatch `new Event('input', { bubbles: true })`, otherwise the page's listeners won't fire.

## Orientation (read first)

Key existing pieces in `Calculation tools/drawdown.html`:

- `state` object (~line 1024): `params`, `pins`, `editing`.
- `PARAM_DEFS` (~line 1011): the 9 pin-editable fields, each `{ key, label, fmt, absolute? }`.
- `simulate()` (~line 1049): monthly loop; applies pins at the top of each month iteration; each row records `pre_state` (pre-pin snapshot, used as editor baselines) and `effective_state`.
- `aggregateForView()` (~line 1278): years view groups 12 months per row; `first_month` / `last_month` / `source_rows` on year rows.
- `renderTable()` (~line 1460): builds tbody HTML string; current column order is `# | Date | Expense | Inv. Income | Net | Δ | Buffer | Investments | Sold | Notes | (pin)` — pin action is the **last** (11th) column; wires `.pin-action` click handlers after `innerHTML` assignment.
- `renderPinEditor()` (~line 1555): builds the inline editor row (`colspan="11"`); fields carry `data-key`, `data-fmt`, `data-baseline`.
- `attachPinEditorEvents()` (~line 1632): wires editor inputs (input listener toggles `.changed` by comparing value to baseline), save/cancel/remove/reset buttons.
- `savePinFromEditor()` (~line 1682): iterates ALL `.pin-field-input`s and saves every field whose value differs from `data-baseline` by more than 1e-9 (`floatsEqual`) — **this value-comparison is the phantom-override bug**, because money baselines are displayed through `Math.round()` and pct through `.toFixed(2)`.
- `rerender()` (~line 1740): simulate → aggregate → renderStats/renderChart/renderTable → attachPinEditorEvents. Every state change funnels through this; the whole tbody is rebuilt each time.
- `exportCsv()` (~line 1758): builds CSV from view rows; last column is `pinned` yes/blank.
- Sidebar groups (~lines 860–926): repeating `.group` blocks with `.group-label` (`<span>Name</span><span class="ordinal">§ NN</span>`); last is Horizon `§ 06`.
- CSS: `.pin-action` is `opacity: 0` until row hover (~line 606); pinned rows get a 3px ochre left-edge bar via `tr.is-pinned td:first-child::before` (~line 586); left-aligned columns are set via `nth-child(1), (2), (10)` rules on `.amort th/td` (~lines 510, 522).

---

### Task 1: Fix phantom overrides (dirty-flag tracking)

**Files:**
- Modify: `Calculation tools/drawdown.html` — `renderPinEditor()`, `attachPinEditorEvents()`, `savePinFromEditor()`

**Interfaces:**
- Produces: `savePinFromEditor()` must be callable exactly as today (Task 3's cell editor does NOT call it — cell edits write pins directly — but Task 4 relies on pins containing only genuine user overrides).

Behavior to implement (spec §1):

- Maintain a per-editor-session set of **dirty field keys**. A field becomes dirty when the user fires its `input` event. When the editor opens on an **existing** pin, initialize the dirty set to that pin's override keys (they are genuine prior user choices); all other fields start clean. A fresh (non-pinned) editor starts with an empty dirty set.
- The `.changed` visual class on a field follows: dirty AND value ≠ baseline. An untouched field is never highlighted regardless of fractional-baseline display rounding; a dirty field restored to its baseline value loses the highlight.
- On save: persist only fields that are dirty AND differ from baseline (keep the existing `floatsEqual` tolerance for the difference check and the existing pct ÷100 conversion). A save with zero qualifying fields removes any existing pin at that month and creates nothing (the existing "no pin if no overrides" behavior at the end of `savePinFromEditor` already handles this once the iteration is restricted — verify it does).
- "Reset all to baseline" clears the dirty set in addition to its current input-value resets.
- Where to keep the dirty set is the implementer's choice (e.g. on `state.editing`), but it must not survive editor close/cancel, and per-field state must be re-derived every time the editor is (re)opened.

- [ ] **Step 1: Reproduce the bug (pre-change baseline).** Serve the page, open the pin editor at month 12, change only Expense (base) to 8000, save. Observe the row note reads "pinned 2 overrides" (buffer phantom-pinned). This is the failing behavior the task fixes — record it.
- [ ] **Step 2: Implement dirty-flag tracking** per the behavior above.
- [ ] **Step 3: Verify the fix in the browser.**
  - Repeat Step 1's scenario → note must read `pinned expense (base)` (single override); reopening the editor shows exactly one `.changed` field.
  - Open an editor at month 12+, touch nothing, save → no pin created, pin count unchanged.
  - Compose-and-edit regression (spec verification §2): pin expense=8000 at month 12; pin external_income=3000 at month 36 (verify it saves as exactly one override); then edit the month-12 pin to expense=12000 → the Buffer column must show NO discontinuity at month 36 beyond the external-income change itself (pre-fix it teleported ~$97k).
  - Edit an existing pin and restore its field to baseline, save → pin disappears (override dropped, empty pin pruned).
- [ ] **Step 4: Commit** with subject `Fix phantom pin overrides via dirty-field tracking`.

---

### Task 2: Left-gutter pin control + discoverability hint

**Files:**
- Modify: `Calculation tools/drawdown.html` — table `<thead>` markup, `renderTable()` row template, `renderPinEditor()` colspan, `.amort` CSS `nth-child` rules, `.pin-action` CSS, table-head markup/CSS, footnote "Pins" sentence

**Interfaces:**
- Produces: final column order that Task 3 and Task 5 depend on:
  `1: pin gutter | 2: # | 3: Date | 4: Expense | 5: Inv. Income | 6: Net | 7: Δ | 8: Buffer | 9: Investments | 10: Sold | 11: Notes`
  (total still 11 columns; the old trailing pin column is removed, not kept).

Behavior to implement (spec §2):

- Move the pin cell from last to **first** in both `<thead>` and the body row template. The gutter column stays narrow (the existing `width: 28px` header treatment moves with it) and its content centered.
- Update every column-count/position dependency:
  - `.amort th/td` left-align rules: currently `nth-child(1), (2), (10)`; the text-left columns become `nth-child(2), (3), (11)`; the gutter's `nth-child(1)` gets the centered narrow treatment; the ochre pinned-row bar selector `tr.is-pinned td:first-child::before` now lands on the gutter cell — confirm that still renders correctly (it should, and co-locating bar + control is the point of this task).
  - `renderPinEditor()`'s `colspan="11"` stays 11 — confirm.
  - Check for any other `:first-child` / `:last-child` / `nth-child` rules on `.amort` that assumed the old order.
- Rest-state visibility: `.pin-action` changes from `opacity: 0` to always visible at reduced opacity (~0.35) in `--ink-fade`; on row hover, full opacity and `--ochre`; on a pinned row, the glyph is `✎` (already the case) at full opacity in `--ochre` at rest (already the case via `tr.is-pinned .pin-action` — verify it still applies after the move).
- Hint line: under the "The Amortization" heading in `.table-head`, add a one-line caption in the existing italic Fraunces caption style (match `.pin-editor-sub` / `.stat-detail` typography): `Click + on any row to change assumptions from that month forward.` Keep the existing actions (pin count, Clear pins, Export CSV) where they are.
- Update the footnote's **Pins** sentence to match the new location/affordance (it currently says "Hover any row…").

- [ ] **Step 1: Implement** the markup, CSS, and copy changes above.
- [ ] **Step 2: Verify in the browser** (spec verification §4):
  - Without hovering, every row shows a faint `+` in the left gutter; hovering a row strengthens it to ochre.
  - Pin a row → gutter shows ochre `✎` plus the existing 3px left bar; unpinned rows unaffected.
  - Editor opens from the gutter control in both months and years view; editor row spans the full table width.
  - Column alignment: `#`, `Date`, `Notes` left-aligned; money columns right-aligned; no header/body misalignment.
  - The hint line renders under the heading in both views and doesn't collide with the action buttons.
- [ ] **Step 3: Commit** with subject `Move pin control to left gutter and surface discoverability`.

---

### Task 3: In-table cell editing

**Files:**
- Modify: `Calculation tools/drawdown.html` — `renderTable()` row template + post-render wiring, new commit helper, CSS for editable/overridden cells

**Interfaces:**
- Consumes: Task 2's column order; `state.pins`; each base row's `pre_state` (field baselines) from `simulate()`.
- Produces: a single commit path — describe it as `commitCellEdit(month, key, value)` (name at implementer's discretion, but ONE function) — that merges/removes a single field override in the pin at `month` and rerenders. The Adjustments panel (Task 4) needs no interface beyond `state.pins` + `rerender()`.

Behavior to implement (spec §3):

- Editable columns and their pin fields: Expense→`expense`, Inv. Income→`investment_income`, Buffer→`buffer`, Investments→`investments`. All other columns are untouched.
- Mark editable cells in the row template (e.g. a class + `data-month` + `data-key`); wire clicks via **event delegation on the tbody** (the tbody is rebuilt by `innerHTML` every rerender — per-cell listeners added before a rerender are lost, and the pin-action wiring already re-runs per render; delegation avoids growing that pattern by four more loops).
- Click → replace cell content with a numeric inline input, pre-filled with the row's **pre_state** value for that field (NOT the displayed post-simulation value for buffer/investments — the displayed value already includes the month's delta/sales; the baseline the pin editor uses is `pre_state`, and cell editing must agree with it). Money fields pre-fill rounded to whole dollars, same as the pin editor display.
- Keys: **Enter commits, Escape cancels, blur commits.** Gotchas the implementer must handle:
  - Escape must not trigger the blur-commit (cancel sets a flag or detaches before blur fires).
  - Empty or unparseable input on commit = cancel (spec Error handling).
  - Commit triggers `rerender()`, which destroys the input — don't touch the input after rerender.
  - Only one inline cell editor open at a time; opening a new one cancels the previous. Opening a cell editor while the pin editor row is open is allowed but simplest is to close the pin editor (`state.editing = null`) when a cell edit begins — pick one and be consistent.
- Commit semantics (must match the pin editor's model exactly):
  - Target month: months view → the row's month; years view → the row's `first_month` (same rule `renderTable` already uses for `pinMonth`).
  - If committed value equals the field's baseline (`pre_state`, `floatsEqual` tolerance): remove that field's override from any pin at that month; if the pin ends up with zero overrides, delete the pin.
  - Otherwise: merge `{ [key]: value }` into the existing pin at that month, or create a new pin `{ at_month, overrides: { [key]: value } }`.
- Affordances:
  - Editable cells get a pointer cursor and a subtle dotted underline on hover (visible only on hover is fine; the gutter `+` and hint line carry rest-state discovery).
  - Editable cells carry a `title` tooltip stating the edit flavor: Buffer/Investments → "sets the balance at this month"; Expense/Inv. Income → "changes this value going forward". In years view the tooltip must also state the mapping, e.g. "applies at <Mon YYYY>" for the year's first month.
  - A cell whose field is overridden by a pin at that month gets a persistent ochre marker (e.g. small dot or underline in `--ochre`) so committed edits stay visible. Determine "overridden" from the row's `overrides_applied` / pin lookup, not from a separate bookkeeping structure.
- Years view: the input pre-fills with the **mapped month's** pre_state value, not the year-row aggregate (year rows carry `pre_state` = first month's snapshot already — use it). Aggregate sums (expense, income) will visibly differ from the input value; that is expected and why the tooltip states the mapping.

- [ ] **Step 1: Implement** the cell editor per above.
- [ ] **Step 2: Verify in the browser** (spec verification §3):
  - Months view: for EACH of the four columns — click, type a new value, Enter → row note shows a pin with exactly that one field; later months roll forward; earlier months unchanged.
  - Escape leaves state untouched (no pin, cell restored). Blur commits. Empty input + Enter = cancel.
  - Commit the baseline value back into an overridden cell → override removed; single-field pin disappears entirely.
  - Buffer edit: confirm the committed value behaves as the month's **starting** balance (absolute set applied before the month's flows), consistent with pinning buffer via the pin editor at the same month — the two paths must produce identical simulations.
  - Cell edit on a month that already has a multi-field pin → field merges in; other overrides intact (check by reopening the pin editor).
  - Years view: edit Expense on a year row → pin lands at the year's first month; tooltip shows the mapping; input pre-filled with that month's pre_state (not the annual sum).
  - Overridden-cell ochre marker appears after commit and survives rerenders.
- [ ] **Step 3: Commit** with subject `Add in-table cell editing for expense, income, buffer, investments`.

---

### Task 4: Sidebar Adjustments panel (display-only)

**Files:**
- Modify: `Calculation tools/drawdown.html` — sidebar markup after the Horizon group, new render function called from `rerender()`, panel CSS following the existing `.group` pattern

**Interfaces:**
- Consumes: `state.pins`, `PARAM_DEFS` (labels + `fmt` for formatting values), `fmtVal()`/`fmtDate()`/`dateForMonth()`, `state.editing`, `rerender()`.

Behavior to implement (spec §4):

- New sidebar group after Horizon: `.group-label` = `Adjustments` / ordinal `§ 07`, placed **before** the Recalculate button.
- Content = pure render of `state.pins`, sorted by `at_month`: each entry shows the month + formatted date (e.g. `Month 12 · May 2027` — reuse `dateForMonth` + `fmtDate`) and each overridden field as `label → formatted value` using `PARAM_DEFS` labels and per-`fmt` formatting (reuse `fmtVal`; display pct fields as percentages, matching the pin editor). Pins beyond the current horizon still list (the sim ignores them; the panel must not).
- Re-render the panel from `rerender()` so every surface (pin editor, cell edits, Clear pins, Remove pin) keeps it in sync automatically. Wire entry events after each panel render (or delegate).
- Each entry has a **remove** control: deletes that pin from `state.pins`; if the removed pin's month is currently open in the pin editor, close the editor (`state.editing = null`); rerender. No confirmation dialog (consistent with existing "Clear pins").
- Clicking an entry (outside its remove control): set `state.editing = { month: at_month }`, `rerender()`, then scroll the table row into view — in years view target the year row containing that month (row `data-month` values are year-first months; find the row whose pin-month range covers it). Scroll AFTER rerender (the tbody was just rebuilt). No editing capability inside the panel itself.
- Empty state: group stays visible with the caption-style line `none — edit any row` (spec locks "visible with empty state", not hidden).
- Styling: follow the existing sidebar `.group` / `.field` typography; remove control styled like the existing small text/underline actions (e.g. `.pin-editor-actions .reset`), not a heavy button.

- [ ] **Step 1: Implement** the panel per above.
- [ ] **Step 2: Verify in the browser** (spec verification §5):
  - No pins → group visible with empty-state line.
  - Create pins via BOTH the pin editor and a cell edit → both appear, chronologically ordered, values formatted per type (money with `$`, pct as `%`).
  - Remove from panel → pin gone from table notes, chart markers, and pin count; removing the pin whose editor is open closes the editor.
  - Click an entry → table scrolls to the row and its pin editor is open (months view); years view scrolls to the containing year row with the editor open.
  - "Clear pins" button → panel returns to empty state.
- [ ] **Step 3: Commit** with subject `Add read-only Adjustments panel to sidebar`.

---

### Task 5: CSV export override notation

**Files:**
- Modify: `Calculation tools/drawdown.html` — `exportCsv()`

**Interfaces:**
- Consumes: view rows' `pinned_at_this_row` / `source_rows` (years view) and pin `overrides`.

Behavior to implement (spec §5):

- Append ONE new header, `overrides`, after the existing `pinned` column. All existing columns and their order are unchanged.
- Populated only on rows where a pin applies; otherwise empty string.
- Format: semicolon-separated `key=value` pairs, raw unformatted numbers (no `$`, `%`, or thousands separators), pct fields in stored decimal form. The whole field wrapped in double quotes. Example row value: `"expense=8000; external_income=3000"`.
- Years view: a year row must aggregate ALL pins whose month falls inside that year (walk the row's `source_rows` for `pinned_at_this_row`, or filter `state.pins` by the row's `first_month..last_month` range — note the current year-row `pinned_at_this_row` only captures the FIRST pin in the year, so it is NOT sufficient); concatenate multiple pins' pairs with the same separator.
- Key order within a pin: iterate `PARAM_DEFS` order for determinism.

- [ ] **Step 1: Implement** per above.
- [ ] **Step 2: Verify** (spec verification §6): with two pins in the same year (e.g. months 14 and 20) plus one elsewhere — export in months view (each pinned row carries its own pairs; all other rows have an empty final field) and in years view (the shared year concatenates both pins). Open the CSV in a text editor: header row ends `...,pinned,overrides`; quoted field parses as one cell (spot-check by importing into a spreadsheet or splitting on commas outside quotes); numbers are raw decimals.
- [ ] **Step 3: Commit** with subject `Add overrides column to CSV export`.

---

### Task 6: Final end-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Fresh-load check** (spec verification §7): hard-reload the served page → zero pins, empty Adjustments panel, no console errors (favicon 404 is pre-existing and acceptable).
- [ ] **Step 2: Full workflow pass:** cell-edit expense at month 12 → pin editor at month 36 changing tax rate + floor → cell-edit buffer at month 60 in years view → panel shows 3 entries → edit the month-12 pin to a different value → verify months 36+ and 60+ recompute with no stale-value discontinuities → export CSV in both views and confirm overrides column → remove a pin from the panel → chart pin markers and pin count track every change.
- [ ] **Step 3: Regression sweep of untouched behavior:** sidebar parameter inputs + Recalculate, months/years toggle, chart rendering, stats row, depletion footer (set expenses high to force depletion), Clear pins.
- [ ] **Step 4: Report** results per repo rules — every check listed with observed outcome, failures verbatim. Do not summarize as "passing" if anything failed.

## Self-review notes (already applied)

- Spec coverage: §1→Task 1, §2→Task 2, §3→Task 3, §4→Task 4, §5→Task 5, non-goals→Global Constraints, verification §§1–7 distributed into task verify steps + Task 6.
- The years-view CSV aggregation gap (`pinned_at_this_row` only carries the first pin of a year) is called out explicitly in Task 5 so the implementer doesn't inherit it silently.
- Buffer cell-edit pre-fill uses `pre_state`, matching the pin editor's baseline semantics — flagged in Task 3 because the displayed cell value is post-flows and using it would double-apply the month's delta.
