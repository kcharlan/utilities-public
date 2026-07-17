# Drawdown Calculator — Mid-Series Scenario Editing (Pin System Overhaul)

**Date:** 2026-07-11
**Target file:** `Calculation tools/drawdown.html` (single-file HTML app; this architecture must be preserved)
**Status:** Approved design, pending implementation plan

## Background

The drawdown calculator already contains a "pin" system implementing
edit-anywhere-roll-forward: hovering a table row reveals a `+` control that opens
an inline editor with all 9 scenario parameters; saved pins apply forward from
that month, past rows are immutable, and multiple pins at different months
compose. Browser verification (2026-07-11) confirmed single-pin roll-forward
works correctly, and surfaced two defects that make the feature read as missing
or broken:

1. **Undiscoverable control.** The `+` affordance is `opacity: 0` until row
   hover and sits at the far right of the row. The only documentation is one
   sentence in the page-bottom footnote.
2. **Phantom overrides (correctness bug).** The pin editor displays money
   baselines rounded to whole dollars (`Math.round`) and percent baselines at
   2 decimals, but the save path compares the displayed value against the exact
   fractional baseline with a 1e-9 tolerance (`floatsEqual` in
   `savePinFromEditor`). Any field whose baseline is fractional — buffer after
   month 1, inflation-drifted expense — is silently saved as an override the
   user never made. Because `buffer` is an *absolute* override, a later pin
   freezes the buffer at a stale snapshot: reproduced by pinning expense at
   month 12 and external income at month 36, then editing the month-12 pin —
   month 35 showed $127,999 and month 36 teleported back to $225,035 (~$97k
   discontinuity from stale frozen state).

This spec covers fixing those defects and extending the pin system with direct
cell editing, a read-only adjustments panel, and CSV override notation.

## Scope (build order)

### 1. Fix phantom overrides

Only fields the user actually touched may be saved as overrides.

- Track a per-field **dirty flag**, set when the user edits that field's input
  (its `input` event), rather than inferring change by comparing the input's
  current value to the baseline.
- On save, persist only dirty fields whose value differs from baseline. A save
  with zero touched fields must produce zero overrides (and therefore no pin,
  per the existing "no pin if no overrides" rule).
- "Reset all to baseline" clears all dirty flags.
- The `changed` visual highlight on a field follows the dirty flag, not the
  value comparison — so an untouched field with a fractional baseline is never
  highlighted, and a touched field edited back to the baseline value is no
  longer saved.
- Editing an **existing** pin: fields already overridden by the pin start as
  dirty (they are genuine user choices being re-displayed); all other fields
  start clean. Clearing an override is done by "Reset all to baseline" or by
  the user restoring the baseline value in a dirty field (dirty + equal to
  baseline → override dropped on save).

### 2. Relocate and surface the pin control

- Move the pin control from the last table column to a **new narrow gutter
  column at the far left**, before the period (`#`) column, in both the header
  and body. The gutter co-locates the control with the existing pinned-row
  indicator (the 3px ochre left-edge bar) and the left-weighted row-hover
  gradient.
- Rest state: the `+` glyph is **always visible at ~35% opacity** in the fade
  ink color. On row hover: full opacity, ochre. When the row is pinned: a
  permanent full-opacity ochre `✎`.
- The `colspan` of the pin-editor row and any other column-count-dependent
  markup/CSS (`nth-child` alignment rules) must be updated for the new column
  order.
- Add a **one-line hint** in the table header area, under "The Amortization,"
  in the existing italic Fraunces caption style:
  *"Click + on any row to change assumptions from that month forward."*
- The footnote's existing "Pins" sentence remains as the detailed reference,
  updated if its description of the control location no longer matches.
- No animation, pulse, or first-visit coach marks.

### 3. In-table cell editing

Direct editing for the four value columns that map to pin fields:

| Column        | Pin field           | Semantics on commit                        |
|---------------|---------------------|--------------------------------------------|
| Expense       | `expense`           | Re-bases the expense stream; inflation continues from the new value |
| Inv. Income   | `investment_income` | Re-bases income; triggers the existing epoch reset (baseline principal/income re-anchor, cumulative reduction cleared) |
| Buffer        | `buffer`            | Absolute: sets the buffer balance at that month |
| Investments   | `investments`       | Absolute: sets principal at that month; triggers epoch reset |

Behavior:

- Click an editable cell → the cell content is replaced by an inline numeric
  input pre-filled with the current displayed value. **Enter commits, Escape
  cancels, blur commits.** Commit creates a pin at that month with that single
  field override, or merges the field into an existing pin at that month.
  Committing a value equal to the cell's pre-state baseline creates no
  override (and removes that field's override if one existed).
- Hover affordance on editable cells: pointer cursor and a subtle dotted
  underline (or equivalent), so editable vs. computed cells are
  distinguishable. Computed columns (Net, Δ, Sold, Notes, dates) are not
  editable.
- Overridden cells (a pin at that month overrides that field) get a persistent
  ochre marker so edits remain visible after commit.
- The inline editor's tooltip/affordance states which flavor of edit it is:
  absolute ("sets balance at this month") vs. re-base ("changes this value
  going forward").
- **Years view:** an edit maps to the year's **first month** — the same rule
  the pin editor already uses. The displayed aggregate cell values in years
  view are sums (expense, income) or end-of-year balances (buffer,
  investments); the inline input must pre-fill with the mapped month's
  pre-state value, not the aggregate, and the affordance/tooltip must make the
  "applies at <first month of year>" mapping visible.
- The full pin editor remains the only path for the non-column fields:
  inflation, tax rate, floor, modifier, external income.
- Cell editing and the pin editor write to the same `state.pins` model; no
  parallel data structure.

### 4. Sidebar "Adjustments" panel (display-only)

- New sidebar group, following the existing group pattern, labeled
  **"Adjustments"** with the next ordinal (`§ 07`).
- Renders a chronological read-only list of pins: month + formatted date, and
  each overridden field with its value (formatted per field type). Pure render
  of `state.pins` — no add or edit capability in the panel.
- Each entry has a **remove** control (deletes that pin, rerenders).
- Clicking an entry (other than its remove control) **scrolls to that row in
  the table and opens its pin editor** — a shortcut to the main view's
  existing editor, not a second editing surface.
- When no pins exist the group remains visible with a quiet empty state
  (*"none — edit any row"* in the caption style). Keeping the group visible
  doubles as feature discovery, consistent with scope item 2.
- In years view, jump-to-row targets the year row containing the pin's month.

### 5. CSV export: override notation

- Add one new column, `overrides`, after the existing `pinned` column.
- Populated only on rows where a pin applies: machine-friendly,
  semicolon-separated `key=value` pairs with raw unformatted numbers, e.g.
  `expense=8000; external_income=3000`. Percent-type fields export their
  stored decimal form (e.g. `tax_rate=0.28`). The whole field is quoted.
- Existing columns are unchanged, preserving anything built against the
  current export shape.
- In years view, a year row aggregates all pins applied within that year;
  if multiple pins fall in one year, concatenate their pairs.

## Non-goals

- **No pin persistence across reloads.** The calculator loads fresh every
  time; pins live only in in-page state. This is a deliberate decision, not an
  omission.
- No add/edit capability in the Adjustments panel.
- No changes to the simulation engine's semantics (pin application order,
  epoch reset, inflation compounding, termination rules).
- No architectural change: the app stays a single self-contained HTML file.

## Error handling

- Inline cell inputs and pin-editor inputs reject non-numeric input (numeric
  input type, as today). Empty or unparseable inline input on commit is
  treated as cancel.
- Negative values follow the same constraints the pin editor applies today
  (percent fields bounded; modifier non-negative).
- Removing a pin from the panel while its editor is open closes the editor.

## Verification criteria

The project has no automated test suite (intentionally simple single-file
apps; the repo validation matrix specifies smoke-testing HTML calculators in a
browser). Verification is via Playwright MCP against the served page, per the
recorded feedback that embedded single-file UIs must be verified in a real
browser:

1. **Phantom-override regression:** open a pin editor at a month with
   fractional baselines (e.g. month 12+), change exactly one field, save →
   the pin contains exactly one override; the row note reads "pinned" with one
   named field. A save with no touched fields creates no pin.
2. **Compose-and-edit:** pin expense at month 12, pin external income at month
   36, then change the month-12 pin's expense → months 36+ reflect both the
   upstream change and the month-36 override, with no balance discontinuity at
   month 36 beyond the external-income change itself.
3. **Cell editing:** click each of the four editable columns, commit a value →
   correct single-field pin created; Escape leaves state untouched;
   re-committing the baseline value removes the override. Verify years-view
   mapping to the year's first month.
4. **Gutter control:** `+` visible without hover at reduced opacity; pinned
   rows show `✎`; pin editor opens from the left gutter; table column
   alignment intact (left-aligned text columns still left-aligned).
5. **Adjustments panel:** reflects pins after add/edit/remove from any
   surface; remove works; click jumps to row and opens editor; empty state
   correct after "Clear pins."
6. **CSV:** export with multiple pins in both months and years view; verify
   the `overrides` column format and that pre-existing columns are unchanged.
7. **Fresh load:** reload the page → no pins present.
