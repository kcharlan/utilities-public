# Drawdown Theme, Defect Repair, and UI Refresh: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to carry out this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `drawdown.html` three theme modes: Auto (follows the system; the default on every load), Light, and Dark. Repair every measured contrast, layout, keyboard, status, and motion defect. Then apply the agreed design refresh. All of this happens in one single-file page that still passes the full test suite.

**Architecture:**
- **Colour.** Every colour is a CSS custom property whose value is `light-dark(<light>, <dark>)`. `:root` declares `color-scheme: light dark`, so Auto needs no JavaScript and cannot flash. The Light and Dark overrides set a `data-theme` attribute on `<html>`, which pins `color-scheme`. Print always pins light.
- **Chart.** Chart colours move out of JS literals into CSS rules, and the chart is re-rendered at true pixel size.
- **Everything else** is ordinary CSS and small DOM changes inside the existing single-file app.

**Tech stack:** one static HTML file (inline CSS plus one classic inline `<script>`), with no build step. Tests use Node's built-in test runner (`node --test`) with a VM loader, and Playwright 1.63 on Chromium, served by `http-server`.

**Spec:** `Calculation tools/docs/drawdown_theme_and_ui_findings.md`. It is the analysis this plan implements. Its line numbers refer to commit `cc7a570`; where the two documents differ, **this plan wins**.

**Browser support floor** (a decision; there is no fallback): Chrome/Edge 123, Firefox 120, Safari 17.5. Older browsers lose all styling, and the README must say so (Task 17).

---

## Global Constraints

These apply to every task. Each task's requirements implicitly include this section.

- **Scope.** Only `Calculation tools/drawdown.html`, its tests, `Calculation tools/README.md`, and `Calculation tools/docs/` change. Do not touch the sibling calculators.
- **Single file.** No build step, no new dependencies, no new `<link>` or `<script src>`. Google Fonts stays as it is.
- **Exactly one `<script` tag in the file.** Two Node loaders extract the first bare `<script>` (`tests/helpers/load_drawdown.js:9` and `tests/drawdown_dates.test.js:11`). **Do not add a head script.** The design does not need one.
- **The app script stays a classic script** (never `type="module"`).
  - Keep existing **function declarations** as declarations: browser tests reassign some of them. For example, `drawdown.browser.spec.js:464–468, 498, 523` reassign `solveAnnualTarget`.
  - Page globals the browser tests call: `state`, `acceptPins`, `rerender`, `renderChart`, `renderTable`, `renderStats`, `simulate`, `aggregateForView`, `sidebarTimers`, `fmtDate`, `dateForMonth`, `solveAnnualTarget`.
  - The new functions `renderVerdict` and `spreadLabels` must also be declarations reachable as globals.
- **No persistence of any kind.** No `localStorage`, `sessionStorage`, IndexedDB, or cookies. The theme choice lives in memory and resets to Auto on reload. `README.md:5` ("do not … save them in browser storage") must stay true.
- **No legacy fallback for `light-dark()`.**
- **No `console.error` and no uncaught errors.** Every test in `drawdown.browser.spec.js` fails on any `pageerror` or `console.error` (lines 3–11). The drawdown tests in `browser.spec.js` do not listen for errors, so they will not catch them for you.
- **Node VM stubs are minimal.**
  - Top-level script code must not touch `window`, `document.documentElement`, `document.querySelector*`, `matchMedia`, `ResizeObserver` or `requestAnimationFrame`.
  - Everything new that touches the DOM goes in functions called from `init()`, from event handlers, or from browser-only render paths (`rerender`, `renderTable`, `renderChart`). No Node test calls those three.
- **Placement of new wiring in `init()`.** All new `init()` wiring goes **after** the existing `inputs.forEach(...)` listener loop.
  - Reason: `drawdown_dates.test.js` stubs `getElementById` to throw a sentinel for any id except `today-stamp`, and asserts that `init()` throws exactly that sentinel.
  - Wiring placed before the loop that uses any other API would throw a different error.
- **Stub-safe DOM access in shared paths.** Any new DOM access inside `showScenarioStatus`, `readParams` or `renderStats` must tolerate a missing element or a plain-object stub. Follow the existing patterns: `if (el)` guards, `el.setAttribute?.(...)` and `el.classList?.toggle(...)`. `renderStats` must keep looking up only `stats` (`drawdown_sales.test.js:222–228` asserts this).
- **Status wording.** When the view is stale, the status text must contain `Showing the last valid projection`. Several browser tests and `drawdown_edits.test.js:180` assert this.
- **Model and export untouched.** Do not change simulation, validation, CSV, or pin-transaction logic. This is a presentation and interaction change only.
- **Font sizes.** After Task 11, font sizes come only from `--fs-*` tokens.
- **Public repository.** All fixtures and screenshots use synthetic values. Do not commit screenshots.
- **No duplicate logic.** Before writing any non-trivial logic, search for an existing implementation. This plan names the helpers to create; reuse them. Share CSS through selector lists, not copied declaration blocks.
- **Commits.** One commit per task. Each has an imperative subject and a non-empty body saying what changed, why, and what validation ran. End the body with the attribution lines your session instructions require. Inspect the staged file list and diff for sensitive data before every commit.
- **Paths contain spaces.** Always quote `"Calculation tools"`.
- **Full-suite gate.** Every task ends with the full suite green, run from `Calculation tools`:
  - `npm test`, which runs `node --test tests/*.test.js` and then `playwright test`.
  - Entry baseline on `cc7a570`: Node **106 pass, 0 fail**; Playwright **43 pass, 0 fail**.
  - Counts only go up. Report every failure by name.
- **Test reliability.**
  - For anything asynchronous (transitions, debounced recalculation, ResizeObserver, layout after `setViewportSize`), use Playwright's retrying assertions (`toHaveCSS`, `toHaveAttribute`, `toHaveText`, `expect.poll`). Never rely on a single `getComputedStyle` read.
  - Read geometry with `page.evaluate(() => el.getBoundingClientRect())`. `boundingBox()` returns `null` for zero-height shapes such as a flat line.

---

## Test locks

These existing assertions constrain markup and code. The **Required action** column says whether to preserve the lock or deliberately update it. When you update one, add a one-line comment in the test explaining why the markup legitimately changed, and keep every behavioural assertion.

| Assertion | Location | Required action |
|---|---|---|
| `<label>Income effective rate<span class="hint">…</label>\s*<span class="input-wrap"><input type="number" id="tax-rate" …>` (and the same for `sale-tax-rate`) | `drawdown_sales.test.js:55–63` | **Update (Task 8):** change the expected label and hint markup exactly as Task 8 specifies. Keep `type="number"`, the input attribute order, and the label text. |
| `const inputs = [ … 'sale-tax-rate' … ];` | `drawdown_sales.test.js:64` | Preserve the array literal and its name. |
| `<th>Gross sold</th>` exact; no `<th>Sold</th>`; `r.sold > 0 ? fmtMoney(r.sold) : '—'` | `drawdown_sales.test.js:265–269` | Preserve. **Column-header `<th>`s get no attributes.** |
| Footnote extracted via `/<p class="footnote">…<\/p>/` with 7 text assertions | `drawdown_sales.test.js:271–285` | **Update (Task 16).** |
| `.table-section { max-width:100% }` with no overflow; `.table-scroll { max-width:100%; max-height:calc(100vh - 24px); overflow:auto }` in that order; `<div class="table-scroll">\s*<table class="amort">` | `drawdown_sales.test.js:287–298` | Preserve. New properties may be appended **after** `overflow: auto;` inside that rule. `<colgroup>` inside the table is fine. |
| `id="today-stamp"></strong>` exact, and `init()` sets it first | `drawdown_dates.test.js:66–79` | Preserve. |
| `#today-stamp` is clicked to blur a cell editor, so it must stay visible and uncovered | `drawdown.browser.spec.js:592` | Preserve (Tasks 6 and 12). |
| `renderStats` looks up only `stats` and emits exactly 5 `class="stat"` | `drawdown_sales.test.js:222–263` | Preserve. The verdict gets its own function. |
| `renderPinEditor` field inputs carry `data-key=… min=… max=…` | `drawdown_sales.test.js:157–171` | Preserve the field-input markup. |
| XPath `..`/`..` from a `.pin-field-input` reaches the element with class `changed`, so the chain must stay `.pin-editor-field > .input-wrap > input` | `drawdown.browser.spec.js:553` | Preserve. Do not add wrappers around field inputs (Task 5). |
| `td[data-money-detail]:focus::after` `content` contains the money detail | `drawdown.browser.spec.js:65` | Preserve the `::after { content: attr(data-money-detail) }` rule while restyling (Task 3). |
| `#chart path[data-series="cash|principal|floor"]` count 1 each; floor `d` parsed by `/[ML] [\d.]+ ([\d.]+)/g` with min y ≥ 8 | `drawdown.browser.spec.js:114, 129–136` | Preserve: path commands as `M x y` / `L x y` with plain non-negative decimals, and `padT ≥ 8`. No other `<path>` gets `data-series`. |
| `#chart-y-labels` contains `floor $900K`; for an empty projection it and `#chart-x-labels` are empty and there are zero `#chart path` elements | `drawdown.browser.spec.js:137, 156–164` | Preserve. New decoration renders only when rows exist. |
| `#chart` contains the text `reserve failure` | `drawdown.browser.spec.js:153` | Preserve. The failure label stays SVG `<text>`. |
| Selectors used by tests: `#amort-body tr[data-month]`, `td[data-key]`, `.col-period`, `.col-date`, `.pin-action` (with `data-month` and `data-id`), `.pin-field-input`, `#pin-month`, `#pin-save`, `#pin-cancel`, `#pin-editor-error`, `.cell-edit-input`, `.cell-edit-details`, `.cell-edit-feedback`, `#adjustments-list .adj-entry[data-id\|data-month]`, `.adj-remove`, `#scenario-status`, `#export-csv`, `#clear-pins`, `#calc-button`, `#unit-years`, `#stats .stat`, `#table-footer` | both specs | Preserve every id, class, and data attribute. |

---

## Binding interfaces (names every task uses)

### Theme mechanics

These are load-bearing: specificity and print interplay were verified in a browser probe. Use exactly this.

```css
:root { color-scheme: light dark; /* tokens follow */ }
:root[data-theme="light"] { color-scheme: light; }
:root[data-theme="dark"]  { color-scheme: dark; }
@media print { :root, :root[data-theme] { color-scheme: light; } }  /* must come after the two rules above */
```

### Colour tokens

Each token is declared once in the first `:root {` block. The pairs below are contrast-verified, including text on every row tint; do not change them without re-running the Task 1 contrast test.

| Token | `light-dark(` light `,` dark `)` | Role |
|---|---|---|
| `--surface` | `#F2ECE0`, `#16130E` | page and input background |
| `--surface-raised` | `#EAE3D5`, `#1D1913` | sidebar, chart panel |
| `--surface-sunken` | `#E3DAC8`, `#25201A` | editor gradient end |
| `--text` | `#1A1814`, `#ECE4D4` | primary text; strong fills |
| `--text-muted` | `#4E473E`, `#BDB19E` | secondary text (was `--ink-soft`) |
| `--text-subtle` | `#645B4F`, `#9C907D` | hints, meta, axis labels (was `--ink-fade`) |
| `--accent` | `#946A1C`, `#DDAE52` | ochre lines, markers, borders (≥3:1) |
| `--accent-strong` | `#7A5516`, `#DDAE52` | ochre text; Save fill and border; focus ring (≥4.5:1) |
| `--negative` | `#7A2A1F`, `#E48A78` | failure, negative deltas |
| `--negative-soft` | `#B85D4F`, `#C9705F` | floor dot, remove border |
| `--positive` | `#2C4A3E`, `#8CC2A8` | positive deltas |
| `--series-principal` | `#6B4423`, `#C08A5C` | investments line, gross-sold text |
| `--rule` | `#CDC1AD`, `#3B3429` | decorative rules only |
| `--rule-fine` | `#E6DDC9`, `#2A251D` | row separators |
| `--control-border` | `#7F7361`, `#7C7060` | input, button, and toggle borders; scrollbar thumb (≥3:1) |
| `--accent-tint` | `rgba(148,106,28,0.09)`, `rgba(221,174,82,0.10)` | pinned row, changed field |
| `--accent-tint-strong` | `rgba(148,106,28,0.14)`, `rgba(221,174,82,0.12)` | chart-hover row |
| `--negative-tint` | `rgba(122,42,31,0.06)`, `rgba(228,138,120,0.10)` | insolvent row, reserve band |
| `--negative-halo` | `rgba(122,42,31,0.2)`, `rgba(228,138,120,0.25)` | insolvency dot halo |
| `--band-tint` | `rgba(26,24,20,0.03)`, `rgba(236,228,212,0.03)` | table banding |
| `--label-halo` | `rgba(234,227,213,0.85)`, `rgba(29,25,19,0.85)` | y-label background |
| `--texture-dot` | `rgba(26,24,20,0.035)`, `rgba(236,228,212,0.035)` | body dot grid |
| `--glow-warm` | `rgba(184,134,42,0.04)`, `rgba(221,174,82,0.035)` | body gradient |
| `--glow-cool` | `rgba(44,74,62,0.04)`, `rgba(140,194,168,0.03)` | body gradient |
| `--shadow` | `rgba(0,0,0,0.12)`, `rgba(0,0,0,0.5)` | tooltip and popover shadow |

**Aliases** are plain `var()`, not `light-dark`: `--series-cash: var(--positive)`, `--series-floor: var(--accent)`, `--focus-ring: var(--accent-strong)`, `--on-strong: var(--surface)`. The last is the text colour on any `--text`, `--accent-strong` or `--negative` fill.

**Rename map for existing uses:**
- `--paper` → `--surface`; `--paper-warm` → `--surface-raised`; `--paper-deep` → `--surface-sunken`.
- `--ink` → `--text`; `--ink-soft` → `--text-muted`; `--ink-fade` → `--text-subtle`.
- `--oxblood` → `--negative`; `--oxblood-soft` → `--negative-soft`; `--forest` → `--positive`; `--umber` → `--series-principal`.
- `--ochre-pale` → `--accent-tint`.
- **`--ochre` splits by use:**
  - `color:` → `--accent-strong`.
  - Background **and** border of the Save button → `--accent-strong`.
  - Every other border, outline, background, marker or line → `--accent`.
- **`--rule` splits by use:**
  - Borders of `.input-wrap`, `.toggle`, `.table-actions button`, `.pin-btn`, and the scrollbar → `--control-border`.
  - Everything else stays `--rule`.
- Delete `--forest-soft`, `--ochre-soft` and `--rule-soft`.

### Type scale (Task 11)
`--fs-2xs: 11px; --fs-xs: 12px; --fs-sm: 13px; --fs-base: 14px; --fs-md: 16px; --fs-lg: 20px; --fs-xl: 28px; --fs-2xl: 40px; --fs-display: clamp(36px, 7vw, 62px);`

### New JS functions and module state
Each is defined once and reused.

| Name | Task | Contract |
|---|---|---|
| `setPressed(buttons, activeButton)` | 2 | For each button, toggle class `active` and set `aria-pressed` to `"true"` or `"false"`. Used by the unit toggle **and** the theme toggle. |
| `applyTheme(choice)` | 2 | `choice` is `'auto'`, `'light'` or `'dark'`; anything else is ignored. See Task 2. |
| `spreadLabels(items, minGap, lo, hi)` | 4 | Takes `[{key, y}]` and returns new items in the original order, with `y` adjusted so neighbours are ≥ `minGap` apart and inside `[lo, hi]`. The algorithm is in Task 4. |
| `let lastChartRows = null; let chartGeometry = null;` | 4 | `chartGeometry = { W, H, padL, padR, padT, padB, innerW, innerH, n, safeMax, xOf, yOf, floorOf }`, holding the same closures `renderChart` draws with. |
| `let pendingFocus = null; let pinEditorOpener = null;` plus `restorePendingFocus()` | 8 | One-shot focus management. See Task 8. |
| `openCellFromElement(cell)` | 8 | Calls `openCellEditor(cell, +cell.dataset.month, cell.dataset.key)`. It is the single path shared by the tbody click and keydown delegates. |
| `pinFieldLabel(phase, key)` | 9 | Returns the label `renderPinEditor` shows for a field, including the end-phase income wording and the `' (monthly)'` suffix. Used by `renderPinEditor` **and** `issueLabel`. |
| `const SIDEBAR_FIELDS = { key: { id, label } }` | 9 | The single per-field map for the sidebar. `readParams` derives its id map from it. |
| `const ISSUE_LABELS = { … }` | 9 | Labels for non-sidebar issue fields. |
| `issueLabel(item)` | 9 | Returns a human label for a validation issue (see Task 9). Exported in `tests/helpers/load_drawdown.js`. |
| `renderVerdict(rows, result)` | 12 | Fills `#verdict`. Called from `rerender` right after `renderStats`. |
| `updateFieldReadout(input)` | 15 | Writes the formatted value into the input's `.field-readout`. |

### New DOM ids and classes
- **Theme:** `.theme-toggle` in `.brand` containing `#theme-auto`, `#theme-light` and `#theme-dark`; `.theme-switching` on `<html>`.
- **Status:** `.sidebar-status-anchor`; `#scenario-status[data-tone="pending"|"error"]`.
- **Header:** `.header-meta`; `#verdict` (class `verdict`, plus `is-failure` / `is-stale`); `#verdict-note`.
- **Chart:** `#chart-tooltip`, `.chart-grid`, `.chart-reserve-band`, `.chart-end-label`, `.chart-hover`, `.chart-crosshair`, `.chart-failure-line`, `.chart-failure-label`, `.chart-pin-line`, `.chart-pin-dot`, `.chart-y-label--floor`.
- **Pin editor:** `.pin-editor-section`, `.pin-editor-move`, `.pin-editor-row.is-entering`, `.pin-editor-host--sidebar`.
- **Table:** `.gutter-actions`; `tr.col-groups`, `tr.col-heads`, `th.col-group`; `tr.is-chart-hover`.
- **Sidebar:** `.adj-open`, `.field-control`, `.field-readout`, `.sr-only`.
- **Method appendix:** `.method`, `#method-title`, `.method-list`, `.method-item`.

---

## File map

| File | Responsibility | Tasks |
|---|---|---|
| `Calculation tools/drawdown.html` | all CSS, markup, and script changes | 1–16 |
| `Calculation tools/tests/drawdown_theme_tokens.test.js` (new) | Node guards: contrast, literal-free styling, theme structure, no storage, single script, type scale, dead CSS, no footnote | 1, 10, 11, 16 |
| `Calculation tools/tests/drawdown.browser.spec.js` | new Playwright tests, appended in one `test.describe('theme and UI', …)` block. Use this file, **not** a new spec: `playwright.config.js` `testMatch` lists files explicitly, and this file already carries the error guard. | 1–9, 12–15 |
| `Calculation tools/tests/drawdown_sales.test.js` | deliberate lock updates | 8, 16 |
| `Calculation tools/tests/drawdown_edits.test.js` | `issueLabel` unit tests | 9 |
| `Calculation tools/tests/helpers/load_drawdown.js` | expose `issueLabel` and `pinFieldLabel` in `__api` | 9 |
| `Calculation tools/README.md` | documentation | 17 |
| `Calculation tools/docs/LESSONS_LEARNED.md` (new; the name follows the repo precedent `cognitive_switchyard/docs/LESSONS_LEARNED.md`) | project lessons | 17 |

---

## Phase 0: Setup

### Task 0: Branch, baseline, context
- [ ] Read `Calculation tools/README.md`, this plan, and the spec.
- [ ] If PKM tools are available, run `pkm_resolve_project` for the repo, then `pkm_search` and `pkm_query_tags` (tag `calculation-tools`) for prior decisions. Note anything relevant in your first commit body.
- [ ] `git switch -c drawdown-theme-ui` from `main` at or after `cc7a570`.
- [ ] Commit the plan and findings docs as `Add drawdown theme and UI plan and findings`.
- [ ] Set up tests: `cd "Calculation tools" && npm ci && npx playwright install chromium`.
- [ ] Run `npm test`. Expected: Node 106/106 and Playwright 43/43. If anything differs, stop and report it by name before you change anything.

---

## Phase 1: Theme foundation

### Task 1: Themed token system and removal of hard-coded colours

**Files:** modify `drawdown.html` (CSS `:root` block; every `var(--…)` use, including in JS template strings; every colour literal; the chart SVG template; the legend markup). Create `tests/drawdown_theme_tokens.test.js`. Add tests to `tests/drawdown.browser.spec.js`.

**Interfaces:** produces the token names and the theme mechanics above.

**Requirements**
1. **Theme mechanics.** Replace the `:root` block with the table's tokens, each as `light-dark(light, dark)` (aliases as `var()`). Add the four theme-mechanics rules exactly as given.
2. **Rename.** Apply the rename map to every `var(--…)` use, including the inline `style="color:var(--oxblood)"` in the `renderTable` notes template. After this task, no old token name remains anywhere.
3. **Move every colour literal outside the token block into tokens.** Today that is 11 hex and 9 `rgba()` occurrences, all known. Concretely:
   - **Body.** Dot grid → `--texture-dot`; the two ellipse gradients → `--glow-warm` and `--glow-cool`.
   - **Small literals:**
     - `.chart-y-label` background → `--label-halo`.
     - Tooltip `box-shadow` → `--shadow`.
     - Insolvency-dot halo → `--negative-halo`.
     - `tr.is-insolvent` → `--negative-tint`.
     - `.pin-editor-field.changed` → `--accent-tint`.
   - **Dead rules.** Delete `.pull-quote`, `.pq-mark` and `.amort .marker-dot.surplus`. They contain a literal or reference a token this task deletes (`--forest-soft`).
   - **Chart SVG template (`renderChart`).** Remove the `stroke`, `fill`, `font-family` and `font-size` presentation attributes. Give the pin line and pin dot the classes `chart-pin-line` and `chart-pin-dot`, and the failure line and text `chart-failure-line` and `chart-failure-label`. Style them in CSS:
     - `#chart path[data-series="cash"] { stroke: var(--series-cash) }`, and likewise for `principal` and `floor`.
     - Floor: `stroke-dasharray: 5 4`. Paths: `fill: none`.
     - `.chart-pin-*` in `--accent`.
     - `.chart-failure-*` in `--negative`.
     - `.chart-failure-label { font-family: 'Fraunces', Georgia, serif; font-style: italic; }`, with its font size set in CSS.
   - **Floor y-label.** Replace the inline `color:#B8862A` with a class `chart-y-label--floor { color: var(--accent-strong) }`.
   - **Legend swatches.** Replace the inline `background:#…` with modifier classes. They are solid tokens for now; Task 13 restyles them.
   - **Chart top strip.** `linear-gradient(90deg, var(--positive), var(--accent), var(--negative))`.
4. **Scrollbar.** `scrollbar-color: var(--control-border) transparent;` and the WebKit thumb uses `--control-border`.
5. **Filled controls.** They use `color: var(--on-strong)` on `--text`, `--accent-strong` or `--negative` fills. This applies to the calc button, the active toggle, `.table-actions button:hover`, the Save button, `.pin-btn:hover`, and `.remove-btn:hover`. The Save and Remove hover fill is `--negative`.

**Node tests: create `tests/drawdown_theme_tokens.test.js`.** It uses `calculatorHtml` from `./helpers/load_drawdown`. Write these first; each must fail before implementation and pass after.
- **Token block extraction.** Take the text from the first `:root {` to its first `}`; the block has no nested braces. Parse `/--([a-z0-9-]+):\s*light-dark\(\s*(#[0-9A-Fa-f]{6})\s*,\s*(#[0-9A-Fa-f]{6})\s*\)/g`; the rgba tokens are deliberately not matched. Implement the WCAG 2.x relative luminance and contrast ratio yourself (sRGB linearisation with a 0.04045 threshold; ratio `(L1 + 0.05) / (L2 + 0.05)`).
- **Contrast.** For **both** modes (index 0 = light, 1 = dark):
  - ≥ 4.5 against each of `surface`, `surface-raised` and `surface-sunken`: `text`, `text-muted`, `text-subtle`, `accent-strong`, `negative`, `positive`, `series-principal`.
  - ≥ 3.0 against each of the three surfaces: `accent`, `negative-soft`, `control-border`.
  - ≥ 4.5 for `surface` against each of the fills `accent-strong`, `negative` and `text`.
  - The assertion message names the token, mode, surface and ratio.
- **Literal-free styling.** Take the file with the token block removed. Assert zero matches for `/(?<!&)#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b/g`, and zero matches for `/rgba?\(|color-mix\(/g`.
  - The hex regex was checked against the current file: it finds exactly the 11 known literals, with no false positives.
  - `color-mix` is excluded because all tints are tokens.
- **Theme structure.** The `:root` block contains `color-scheme: light dark`. The file matches `/:root\[data-theme="light"\]\s*\{\s*color-scheme:\s*light;/` and `/:root\[data-theme="dark"\]\s*\{\s*color-scheme:\s*dark;/`. An `@media print` block containing `color-scheme: light` appears **after** the dark rule (compare indices).
- **Old names gone.** No match for `/var\(--(paper|ink|oxblood|forest|ochre|umber|rule-soft)\b/`.
- **No storage.** `doesNotMatch(/localStorage|sessionStorage|indexedDB|document\.cookie/)`.
- **Single script tag.** `(calculatorHtml.match(/<script\b/g) || []).length === 1`.

**Browser tests.** Use `toHaveCSS` or `expect.poll`. The scheme flips live after `page.emulateMedia`, with no reload needed.
- **Dark system scheme:**
  - Body `background-color` is `rgb(22, 19, 14)`.
  - The cash path's `stroke` is `rgb(140, 194, 168)`.
  - The first `.chart-y-label`'s background is `rgba(29, 25, 19, 0.85)`.
  - The body's `background-image` contains `rgba(236, 228, 212, 0.035)`.
- **Light system scheme:** body `rgb(242, 236, 224)`; cash stroke `rgb(44, 74, 62)`; `background-image` contains `rgba(26, 24, 20, 0.035)`.
- **Print.** `emulateMedia({ media: 'print', colorScheme: 'dark' })` yields a light body background.

**Verify.** Run `node --test tests/drawdown_theme_tokens.test.js`, then `npm test`. Screenshot both schemes at 1440×900 (scratch dir, not committed).
- Expected visible changes in light mode: darker subtle text, ochre text, accent lines and muted text, and clearly visible control borders (1.51:1 becomes 3.94:1).
- The dark theme reads as warm umber-black, not blue-grey.
- List anything else that changed.

**Commit:** `Theme drawdown colours with light-dark tokens`.

### Task 2: Auto / Light / Dark control in the sidebar masthead

**Files:** `drawdown.html` (the `.brand` markup, CSS, `init()`, and the unit-toggle handlers); `tests/drawdown.browser.spec.js`.

**Interfaces:** consumes the Task 1 mechanics; produces `setPressed` and `applyTheme`.

**Requirements**
1. **Markup.** After `.tagline` inside `.brand`, add a `role="group"` `aria-label="Color theme"` container `.theme-toggle` holding three `<button type="button">`s:
   - `#theme-auto` (text "Auto", `title="Follow the system setting"`, initially class `active` and `aria-pressed="true"`).
   - `#theme-light` ("Light", `aria-pressed="false"`).
   - `#theme-dark` ("Dark", `aria-pressed="false"`).
   - Each carries `data-theme-choice`.
2. **Styling.** A compact inline segmented control: `display: inline-flex`; buttons `flex: 0 0 auto; padding: 4px 9px`. Share the visual declarations with `.toggle` (border, uppercase, tracking, active = `--text` fill with `--on-strong` text) through selector lists such as `.toggle button, .theme-toggle button { … }`. Do not copy them.
3. **`setPressed`.** Refactor the Months/Years handlers (currently duplicated `classList.add` and `classList.remove`) to use it. Add `type="button"` and `aria-pressed` to `#unit-months` and `#unit-years`.
4. **`applyTheme(choice)`.** Keep it this small; the one subtle part is suppressing transitions for a frame:
   ```js
   function applyTheme(choice) {
     if (!['auto', 'light', 'dark'].includes(choice)) return;
     const root = document.documentElement;
     root.classList.add('theme-switching');            // CSS: .theme-switching * { transition: none !important; }
     if (choice === 'auto') root.removeAttribute('data-theme');
     else root.setAttribute('data-theme', choice);
     setPressed(document.querySelectorAll('.theme-toggle button'),
       document.querySelector(`.theme-toggle button[data-theme-choice="${choice}"]`));
     requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove('theme-switching')));
   }
   ```
5. **Wiring.** Wire the click listeners in `init()` **after** the `inputs.forEach` loop. Theme changes do not call `recalc` or `rerender`.

**Browser tests**
- **Auto follows the system live.** With a dark system scheme the body is dark; switching the system to light makes it light. `<html>` has no `data-theme`, and `#theme-auto` has `aria-pressed="true"`.
- **Dark overrides a light system.** Click `#theme-dark` on a light system: `data-theme="dark"`, body dark, cash stroke `rgb(140, 194, 168)`, and only `#theme-dark` pressed.
- **Light overrides a dark system.** Click `#theme-light` on a dark system: body light.
- **Auto restores following.** Clicking `#theme-auto` makes the page follow a system flip again.
- **No persistence.** Click Dark, then `page.reload()`: there is no `data-theme`, Auto is pressed, and `page.evaluate(() => [localStorage.length, sessionStorage.length, document.cookie])` returns `[0, 0, '']`.
- **Keyboard.** Focus `#theme-dark` and press `Space`: the theme is dark.
- **Unit toggle.** Clicking `#unit-years` sets `aria-pressed="true"` on it and `"false"` on `#unit-months`.

**Commit:** `Add Auto, Light, and Dark theme control to drawdown masthead`.

---

## Phase 2: Contrast and focus beyond the palette

### Task 3: Focus rings, affordance contrast, and disabled states

**Files:** `drawdown.html` (CSS; one line in `renderTable`); `tests/drawdown.browser.spec.js`.

**Requirements**
1. **Focus rings.**
   - Add `:where(button, [tabindex]):focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }`.
   - `.input-wrap:focus-within` gets `border-color: var(--focus-ring); box-shadow: 0 0 0 1px var(--focus-ring);`.
   - The `td[data-money-detail]:focus` outline uses `--focus-ring`. Keep its `::after` content rule (test lock).
   - `.cell-edit-input:focus` uses `box-shadow: 0 0 0 2px var(--focus-ring)`.
2. **Resting "+" affordance.** Remove `opacity: 0.35` from `.pin-action` and use `color: var(--text-subtle)` at full opacity. Hover and pinned states use `--accent-strong`. Ochre marker dots use `--accent`.
3. **Disabled buttons.**
   - Add `button:disabled { opacity: 0.45; cursor: not-allowed; transition: opacity 0.15s ease 0.25s; }`.
   - The **0.25s delay is intentional**. Export is disabled during the 220 ms pending-input window on every keystroke, and the delay stops it flickering. Re-enabling uses the base transition, with no delay.
   - Guard every hover inversion with `:not(:disabled)`: `.table-actions button`, `.pin-btn`, `.calc-button`, and the toggles.
4. **Clear pins.** In `renderTable`, next to the pin-count update, set `#clear-pins`'s `disabled = state.pins.length === 0` (guard `if (el)`). Keep the handler's early return.

**Browser tests**
- **Disabled export.** After filling `#expense` with `''` and polling until `sidebarTimers.size` is 0: `await expect(page.locator('#export-csv')).toHaveCSS('opacity', '0.45')`. Hovering it does not produce the `--text` fill.
- **Clear pins state.** Disabled on load. Enabled after `acceptPins([{ id: 'synthetic', at_month: 1, start: { expense: 5001 }, end: {} }]); rerender();`.
- **Focus ring.** Press `Tab` until `document.activeElement.id === 'theme-light'` (bound the loop at 40 presses). Its `outline-style` is then `solid`.
- **Existing tests.** The tests at `:398` (clear pins) and `:65` (focus `::after` detail) still pass.

**Commit:** `Repair drawdown focus, affordance, and disabled-state contrast`.

---

## Phase 3: Layout defects

### Task 4: Pixel-true chart geometry and correctly placed y-labels

**Files:** `drawdown.html` (`renderChart`, chart CSS, `init()`); `tests/drawdown.browser.spec.js`.

**Interfaces:** produces `spreadLabels`, `lastChartRows` and `chartGeometry`.

**Requirements**
1. **Real pixel size.** Remove `preserveAspectRatio="none"` from `#chart`. In `renderChart`:
   - Take `const box = svg.getBoundingClientRect(); W = Math.round(box.width) || 1000; H = Math.round(box.height) || 200`. Use this, not `clientWidth`, which is unreliable on outer `<svg>` in some engines.
   - Set `viewBox` to `0 0 W H`. Keep `padT = 8` and `padB = 8`.
   - Format every emitted coordinate with `.toFixed(2)`.
   - Set `lastChartRows` (`null` for no rows) and `chartGeometry`.
2. **Root cause of the label offset.** `.chart-y-labels` is `top: 38px; left: 22px` inside a wrapper that is already aligned with the SVG. Set it to `top: 0; left: 0; width: auto;`.
   - Each label is `position: absolute; top: <y>px; transform: translateY(-50%); white-space: nowrap;`.
   - The three label y positions (max, floor, $0) come from `spreadLabels(items, 14, padT, H - padB)`.
   - Label text is unchanged.
3. **`spreadLabels` algorithm** (load-bearing):
   1. Copy the items and sort by `y`.
   2. Set `y[0] = max(y[0], lo)`.
   3. Forward pass: `y[i] = max(y[i], y[i-1] + minGap)`.
   4. If the last item exceeds `hi`, set `y[last] = hi` and run a backward pass: `y[i] = min(y[i], y[i+1] - minGap)`.
   5. Clamp every item to `[lo, hi]`.
   6. Return the items in their **original** order. Never mutate the input.

   If the gaps cannot fit within `[lo, hi]`, clamping wins. That cannot happen with three labels on a plot ≥ 200px tall.
4. **Resize.** In `init()` after the inputs loop, if `typeof ResizeObserver === 'function'`, observe `#chart`. On change, coalesce into one `requestAnimationFrame` that calls `renderChart(lastChartRows)` when `lastChartRows` is set. `renderChart` must never set the SVG's own width or height: its size is CSS-only, which keeps the observer from looping.

**Browser tests** (geometry via `page.evaluate` and `getBoundingClientRect`)
- **Default scenario at 1440×900.** No nudging occurs, because 630K, 100K and 0 are far apart.
  - The floor label's centre is within 2px of `svgTop + chartGeometry.yOf(floor)`.
  - The max label's centre is within 2px of `svgTop + padT`, and `$0`'s centre is within 2px of `svgTop + H − padB`.
  - Every label's left edge is ≥ the SVG's left, and every label is < 18px tall.
- **`spreadLabels`, checked in the page via `page.evaluate`:**
  - `[{key:'a',y:50},{key:'b',y:52}]` with `(14, 0, 200)` gives y values 50 and 64, in the original order.
  - `[{key:'a',y:195},{key:'b',y:198}]` gives 186 and 200.
  - `[{key:'a',y:-5}]` with `(14, 0, 200)` gives 0.
  - The input array is unchanged.
- **Resize.** After `setViewportSize({ width: 1024, height: 800 })`, `expect.poll` until the viewBox width equals `Math.round(svg.getBoundingClientRect().width)`.
- **Existing chart tests** (`:123`, `:140`, `:156`) still pass.

**Commit:** `Render drawdown chart at pixel size and align axis labels`.

### Task 5: Pin and cell editors that never hide their actions

**Files:** `drawdown.html` (CSS, `renderPinEditor` markup around the move field, `renderAdjustments` sidebar host); `tests/drawdown.browser.spec.js`.

**Requirements**
1. **Load-bearing CSS.** The sticky and `100cqw` behaviour was verified in a probe. The selector specificity matters: `.amort td:first-child` is (0,2,1), and `.amort td` sets `white-space: nowrap`.
   ```css
   .table-scroll { /* existing properties… */ container-type: inline-size; }   /* append after overflow: auto; */
   .amort tr.pin-editor-row > td { text-align: left; }                          /* (0,2,2) beats .amort td:first-child */
   .pin-editor { position: sticky; left: 0; width: 100cqw; box-sizing: border-box; white-space: normal;
                 font-family: 'Hanken Grotesk', system-ui, sans-serif; }
   .pin-editor-grid { grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); }
   .pin-editor-actions { flex-wrap: wrap; }
   .pin-editor-host--sidebar { width: 100%; table-layout: fixed; border-collapse: collapse; }
   .pin-editor-host--sidebar .pin-editor { position: static; width: auto; padding: 14px 12px; }
   ```
2. **Sidebar host.** In `renderAdjustments`, the sidebar wrapper `<table>` gets `class="pin-editor-host--sidebar"`.
3. **Pin editor internals.**
   - The section `<h4>`s get class `pin-editor-section`. They span `grid-column: 1 / -1` and are styled as tracked small caps in `--text-muted` with a fine rule.
   - The effective-month control becomes a block `.pin-editor-move`: its label, then `#pin-month` inside an `.input-wrap`, then `#pin-effective-date` in `--text-subtle`. Keep the ids, attributes and behaviour.
   - Do **not** add wrappers around `.pin-field-input` (test lock `:553`).
   - `.pin-reset-field` and the inline cell editor's `.cell-reset-field` share the `.pin-editor-actions .reset` look through one selector list.
   - `#pin-move-note` uses `--text-subtle` italic. `#pin-editor-error` uses `--negative` with `margin-top: 8px`.
4. **Inline cell editor parts.** These are currently unstyled and inherit `nowrap`.
   - `.cell-edit-details` uses `--text-subtle` at `--fs-xs` (or its pre-Task-11 size).
   - `.cell-edit-feedback` uses `--negative`.
   - Both get `white-space: normal; max-width: 260px;`.

**Browser tests**
- **In-table editor at 1440×900.** Set `#expense` to `12000`, poll until `sidebarTimers.size` is 0, and click `tr[data-month="3"] .pin-action`.
  - `#pin-save`'s right edge ≤ `.table-scroll`'s right edge.
  - After `scrollLeft = scrollWidth`, the `.pin-editor`'s left edge is within 1px of the scroller's left edge, and `#pin-save` is still inside the scroller.
  - The editor `td` computes `text-align: left`.
- **In-table editor at 390×844.** Open the editor for month 2: `.pin-editor-sub`'s height is > 20px (it wraps), and `#pin-save` is inside the scroller.
- **Sidebar recovery editor.** Run `acceptPins([{ id: 'synthetic-late', at_month: 100, start: { expense: 6000 }, end: {} }]); rerender();`, fill `#periods` with `50`, then click the `.adj-entry`.
  - `.sidebar`'s `scrollWidth ≤ clientWidth`.
  - `#pin-save`'s right edge ≤ `.sidebar`'s right edge.
  - `#pin-save` can be clicked **without** `force`.

**Commit:** `Keep drawdown editor actions reachable in table and sidebar`.

### Task 6: Responsive layout

**Files:** `drawdown.html` (CSS; header markup); `tests/drawdown.browser.spec.js`.

**Requirements**
1. **Header meta row.** The main header's eyebrow and date stamp become one flex row, `.header-meta` (`justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px 16px`). The stamp is no longer `position: absolute`. Keep `<strong id="today-stamp"></strong>` exactly.
2. **Stats grid.** `.stats` becomes `display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); overflow: hidden;`.
   - Draw dividers with `box-shadow: 1px 0 0 var(--rule), 0 1px 0 var(--rule)` on each `.stat`. The outer edges clip away, and empty grid cells stay blank rather than rule-coloured.
   - Remove `.stat { border-right }` and the `.stat:last-child` rule.
   - Keep `.stats`'s top and bottom borders, and the transparent stat background so the texture shows.
3. **Chart head.** `.chart-head` gets `flex-wrap: wrap; gap: 6px 16px;`.
4. **At `@media (max-width: 900px)`:**
   - `.layout { grid-template-columns: minmax(0, 1fr) }`.
   - `.sidebar { position: static; max-height: none; overflow: visible; border-right: 0; border-bottom: 1px solid var(--rule); }`.
   - `.main { padding: 24px 16px 40px }`.
   - The sidebar (masthead, theme, inputs) stays first; this is intentional.
   - Chart height is owned by Task 13.
5. **At `@media (max-width: 560px)`:** `.sidebar { padding: 20px 16px 28px }`, and the table actions wrap under the table title.
6. **Page overflow.** Only `.table-scroll` may scroll horizontally. The page never does.

**Browser tests** (use `expect.poll` for geometry after `setViewportSize`)
- **At 390×844:**
  - `document.documentElement.scrollWidth ≤ innerWidth`.
  - `#chart`, `.stats` and `.table-scroll` each have a width ≥ 300.
  - The sidebar's bottom edge ≤ `.main`'s top edge.
  - The rects of `.today-stamp` and the header `h2` do not intersect.
- **At 1024×800:** every `.stat-label` is < 30px tall, and the page does not overflow horizontally.

**Commit:** `Make drawdown layout responsive down to phone width`.

---

## Phase 4: Interaction and accessibility

### Task 7: Motion that does not replay

**Files:** `drawdown.html`; `tests/drawdown.browser.spec.js`.

**Requirements**
1. **Rows.** Delete `.amort tbody tr { animation: fadein … }` and the row template's `style="animation-delay:…"`.
2. **Pin-editor row.** It fades only when it first opens. `renderPinEditor` adds class `is-entering` only on the render that opens it, and the fade rule targets `.pin-editor-row.is-entering`.
   - Carry the one-shot "just opened" signal in Task 8's focus mechanism (`pendingFocus` set by an opener).
   - If Task 8 isn't done yet, add a module-level `let pinEditorJustOpened = false`, and have Task 8 fold it into `pendingFocus`. Do not leave both mechanisms in place.
3. **Transitions.** Replace every `transition: all` (5 rules) with the explicit properties that change: `background-color`, `color`, `border-color`, `transform`, `opacity`.
4. **Reduced motion.**
   ```css
   @media (prefers-reduced-motion: no-preference) { html { scroll-behavior: smooth; } }
   @media (prefers-reduced-motion: reduce) {
     *, *::before, *::after { animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; transition-duration: 0.01ms !important; }
   }
   ```
   Remove the bare `html { scroll-behavior: smooth }`.
5. **JS smooth scroll.** In `jumpToPin`, `scrollIntoView({ behavior: 'smooth' })` becomes `behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'`. This runs in the browser only, from a handler.

**Browser tests**
- **No row replay.** Count `animationstart` events (capture listener) whose target matches `#amort-body tr[data-month]`. Fill `#expense` with `5100` and poll until `sidebarTimers.size` is 0: the count is 0.
- **No editor replay.** With an editor open, trigger a rerender (`rerender()` in the page): no `animationstart` fires on `.pin-editor-row`.
- **Reduced motion.** With `emulateMedia({ reducedMotion: 'reduce' })`, open an editor: the editor row's computed `animation-duration` parses to < 0.001s.

**Commit:** `Stop drawdown animation replay and honor reduced motion`.

### Task 8: Keyboard-operable editing, focus management, labelled inputs

**Files:** `drawdown.html` (the row template, `renderAdjustments`, `togglePinEditor`, `jumpToPin`, the cell-editor open and close paths, `rerender`, `init()`, sidebar markup, CSS); `tests/drawdown_sales.test.js` (the lock update); `tests/drawdown.browser.spec.js`.

**Requirements**
1. **Gutter buttons.** Change the `+` and ✎ `.pin-action` spans to `<button type="button" class="pin-action" …>`. Keep the `data-month` and `data-id` attributes and the click listeners.
   - Accessible names: `aria-label="Add adjustment at month N"` or `"Edit adjustment at month N"`.
   - Wrap the buttons in `<span class="gutter-actions">` (`display: inline-flex; flex-wrap: wrap; gap: 2px`). **Do not** make the `<td>` flex.
   - Button reset: `background: none; border: 0; padding: 0; color: inherit;`. Do **not** use `font: inherit`: keep `.pin-action`'s Fraunces 16px.
   - Size: 24×24px.
2. **Enter or Space on an editable cell.** Add one `keydown` listener on `#amort-body` in `init()`, next to the existing click delegate.
   - It acts only when `e.target.matches('td.editable-cell')` **and** `e.key` is `Enter` or `' '`. Typing inside `.cell-edit-input` has a different target, so it is ignored.
   - Then `preventDefault()` and call `openCellFromElement(e.target)`.
   - Rework the click delegate to call `openCellFromElement(cell)` too.
3. **Adjustments entries.** Replace `.adj-entry-when` with `<button type="button" class="adj-open">Month N · date</button>` in the same position.
   - Add **no** listener: its click bubbles to the existing `.adj-entry` handler, which calls `jumpToPin` exactly once.
   - Style it as the old italic `--accent-strong` text, with no button chrome.
4. **Focus management.** This is load-bearing: every open and close rebuilds the DOM via `rerender`, which drops focus to `<body>`. Use one mechanism:
   - **Module state:** `let pendingFocus = null; let pinEditorOpener = null;`.
   - **`restorePendingFocus()`:** `if (pendingFocus) { document.querySelector(pendingFocus)?.focus({ preventScroll: true }); pendingFocus = null; }`. Call it at the end of `rerender`, and in the inline cell editor's cancel path, which restores `innerHTML` without a rerender.
   - **Pin-editor openers.** When `togglePinEditor(month, id)` or `jumpToPin(id)` **opens** an editor:
     - Set `pendingFocus = '.pin-editor .pin-field-input'`.
     - Set `pinEditorOpener` to the opener's selector: `#amort-body .pin-action[data-month="M"]:not([data-id])`, `#amort-body .pin-action[data-id="ID"]`, or `.adj-entry[data-id="ID"] .adj-open`.
   - **Pin-editor close detection.** In `rerender`, just before calling `restorePendingFocus()`: `if (!state.editing && pinEditorOpener) { pendingFocus = pinEditorOpener; pinEditorOpener = null; }`. This single check covers Save, Cancel, Escape and Remove.
   - **Cell editor.** When an inline cell editor closes by Enter or Escape, return focus to its cell. Set `pendingFocus` to `td[data-month="M"][data-key="K"]` before the commit path's `rerender`, and before calling `restorePendingFocus()` in the cancel path.
   - **Never set `pendingFocus` on ordinary rerenders.** Test `:546` requires that a sidebar debounce doesn't steal focus from a field being edited.
5. **Accessible names.**
   - Every sidebar `<label>` gets `for="<input id>"` (11 inputs).
   - Three labels repeat or nearly repeat. Prefix them with visually hidden context through a `.sr-only` utility class (the standard clip pattern):
     - External income's "Monthly" becomes the name "External income, monthly".
     - Expenses' "Monthly" becomes "Expenses, monthly".
     - Investments' "Monthly income" becomes "Investments, monthly income".
   - **Hints** stay visible inside the label but are removed from the accessible name. Each `<span class="hint">` gets `id="<input id>-hint"` and `aria-hidden="true"`, and each such input gets `aria-describedby="<input id>-hint"`. `aria-describedby` still reads text from a directly referenced `aria-hidden` element.
   - **Test lock update.** Update the two regexes in `drawdown_sales.test.js:55–63` to the new label form, for example `<label for="tax-rate">Income effective rate<span class="hint" id="tax-rate-hint" aria-hidden="true">applied to recurring income<\/span><\/label>\s*<span class="input-wrap"><input type="number" id="tax-rate" value="25" step="0\.5" min="0" max="100"`. Place `aria-describedby` **after** `max="100"` so the rest of the locked attribute order is unchanged. Add a comment.

**Browser tests**
- **"+" by keyboard.** Focus `tr[data-month="2"] .pin-action` and press `Enter`: `#pin-save` is visible, `#pin-month` has the value `2`, and `document.activeElement` matches `.pin-editor .pin-field-input`. Press `Escape`: the editor closes and focus is back on that `+` button (`toBeFocused`).
- **Editable cell by keyboard.** Focus `tr[data-month="2"] td[data-key="expense"]` and press `Enter`: `.cell-edit-input` is visible and focused. Press `Escape`: focus returns to the same cell. Press `Space`: the editor opens again.
- **Adjustments entry by keyboard.** With one synthetic pin, focus `.adj-open` and press `Enter`: `#pin-month` has the pin's month, and focus is inside the editor. Click `#pin-cancel`: focus returns to `.adj-open`.
- **No focus theft.** The existing test `:546` still passes.
- **Accessible names.**
  - `page.getByLabel('Starting cash', { exact: true })` resolves to `#buffer-initial`.
  - `getByLabel('Expenses, monthly', { exact: true })` resolves to `#expense`.
  - `getByLabel('Periods', { exact: true })` resolves to `#periods`.
  - `#periods` has the accessible description `0 = run until reserve failure or cap` (check `aria-describedby` and the referenced element's text).
- **Enter in the input still commits once.** The existing tests at `:496` and `:521` still pass.

**Commit:** `Make drawdown editing keyboard-operable with managed focus and labels`.

### Task 9: Calm, visible, human-worded status

**Files:** `drawdown.html` (`SIDEBAR_FIELDS`, `ISSUE_LABELS`, `pinFieldLabel`, `issueLabel`, `readParams`, `renderPinEditor`, `showScenarioStatus`, status markup, CSS); `tests/helpers/load_drawdown.js`; `tests/drawdown_edits.test.js`; `tests/drawdown.browser.spec.js`.

**Requirements**
1. **One field map.** Hoist a module-level `SIDEBAR_FIELDS`:

   | Key | `id` | `label` |
   |---|---|---|
   | `buffer_initial` | `buffer-initial` | Starting cash |
   | `floor` | `floor` | Floor |
   | `external_income` | `external-income` | External income, monthly |
   | `investments_initial` | `investments-initial` | Principal |
   | `investment_income` | `investment-income` | Investments, monthly income |
   | `modifier` | `modifier` | Income modifier |
   | `expense` | `expense` | Expenses, monthly |
   | `inflation` | `inflation` | Annual inflation |
   | `tax_rate` | `tax-rate` | Income effective rate |
   | `sale_tax_rate` | `sale-tax-rate` | Asset sale effective rate |
   | `num_periods` | `periods` | Periods |

   - `readParams`'s local `ids` object becomes `Object.fromEntries(Object.entries(SIDEBAR_FIELDS).map(([key, field]) => [key, field.id]))`, with the same result.
   - `init()`'s literal `const inputs = [...]` stays, because it is test-locked (a documented exception).
   - Add a Node test asserting that every `SIDEBAR_FIELDS` id appears both in `init`'s `inputs` literal (regex over `calculatorHtml`) and as `id="…"` in the markup.
2. **`ISSUE_LABELS`** for non-sidebar issue fields: `unit: 'Horizon unit'`, `at_month: 'Effective month'`, `id: 'Adjustment'`, `start: 'Beginning of month'`, `end: 'End of month'`, `annual_edits: 'Annual target'`, `pins: 'Adjustments'`, `dateAnchor: 'Projection dates'`. Fields whose message stands alone get `''`: `params`, `options`, `model`, `throughMonth`, `startMonth`, `draft`.
3. **`pinFieldLabel(phase, key)`.** Extract the exact expression `renderPinEditor` uses today: `"Next month's investment income"` for end-phase income, otherwise `def.label`, plus `' (monthly)'` for `expense`, `external_income` and `investment_income`. `renderPinEditor` calls it, and its output must be byte-identical (test `:569`).
4. **`issueLabel(item)`.** Check in this order:
   1. If `item.field` is in `ISSUE_LABELS`, return that value (possibly `''`).
   2. Else, if `item.origin === 'adjustment'` and `PARAM_DEFS` has the field, return `pinFieldLabel(item.phase ?? 'start', item.field)`.
   3. Else return `SIDEBAR_FIELDS[item.field]?.label ?? item.field`.
5. **Status text.** Each line is `${location}${label ? `${label}: ` : ''}${item.message}`, keeping the `Adjustment at month N — ` location prefix. The draft issue's message becomes `Updating after your change…`, so the pending text reads `Showing the last valid projection. Updating after your change…`.
6. **Tone.**
   - With `issues.length === 0`, call `status.removeAttribute?.('data-tone')`.
   - Otherwise `data-tone` is `pending` when every issue's field is `draft`, else `error`. Set it with `status.setAttribute?.(…)`: the Node stub has neither method.
   - `pending` style: `--text-muted` text with no border and no fill, so it reads as a quiet "Updating…" line.
   - `error` style: the current bordered box, re-pointed to tokens.
7. **Placement without layout jumps.** The status overlays the sidebar's top instead of pushing the inputs:
   ```css
   .sidebar-status-anchor { position: sticky; top: 0; height: 0; z-index: 4; }
   .sidebar-status-anchor > #scenario-status { position: absolute; top: 0; left: 0; right: 0; }
   ```
   - Put `<div class="sidebar-status-anchor">` containing `#scenario-status` as the **first child** of `.sidebar`. Keep `role="status" aria-live="polite" hidden`.
   - The error box uses `--surface-raised` and `--shadow`, so it reads above the masthead and stays visible while the desktop sidebar scrolls. On mobile it sticks to the viewport top while the sidebar is in view.
8. **Field association.** In `readParams`, wherever `aria-invalid="true"` is set on a control, also call `setAttribute?.('aria-errormessage', 'scenario-status')`, and remove it where `aria-invalid` is removed. The existing stub `setAttribute(name)` ignores other names.
9. **Verdict hook (for Task 12).** `showScenarioStatus` toggles `.is-stale` on `#verdict` and shows `#verdict-note` **only for the `error` tone**, so the verdict doesn't flicker on every keystroke. Guard with `if (el)` and `classList?.toggle`.

**Tests**
- **Node (`drawdown_edits.test.js`).** First add `issueLabel` and `pinFieldLabel` to the `__api` list in `load_drawdown.js`. Then assert:
  - `issueLabel({ field: 'buffer_initial' }) === 'Starting cash'`.
  - `issueLabel({ field: 'buffer', origin: 'adjustment', month: 3 }) === 'Buffer (set to)'`.
  - `issueLabel({ field: 'investment_income', origin: 'adjustment', phase: 'end' }) === "Next month's investment income (monthly)"`.
  - `issueLabel({ field: 'at_month', origin: 'adjustment' }) === 'Effective month'`.
  - `issueLabel({ field: 'model' }) === ''`.
  - `issueLabel({ field: 'draft' }) === ''`.
  - `issueLabel({ field: 'mystery' }) === 'mystery'`.
  - The existing assertions (`/period/i`, `/Showing the last valid projection/`, `/adjustment.*month 1/i`) still pass unchanged.
- **Pending status (browser).** In **one** `page.evaluate`: set `#expense`'s value, dispatch `new Event('input', { bubbles: true })`, then read the status's `data-tone`, `textContent` and `hidden`. This is deterministic because the draft status is set synchronously in the input listener. Expect `pending`, text containing `Showing the last valid projection` and not `draft`, and `hidden === false`.
- **Error status (browser).** Fill `#buffer-initial` with `''` and poll until `sidebarTimers.size` is 0.
  - `data-tone="error"`.
  - The text contains `Starting cash:` and not `buffer_initial`.
  - `#buffer-initial` has `aria-errormessage="scenario-status"`.
  - After scrolling `.sidebar` to its bottom, the status's top edge is still within 4px of the sidebar's top edge.
- **No layout jump.** `#buffer-initial`'s top edge is identical before and during the pending status.

**Commit:** `Show drawdown validation status calmly, visibly, and in plain words`.

### Task 10: Cleanup and font fallbacks

**Files:** `drawdown.html`; `tests/drawdown_theme_tokens.test.js`.

**Requirements**
1. **Dead code.** Confirm Task 1 removed `.pull-quote`, `.pq-mark` and `.amort .marker-dot.surplus`. Delete the empty `tr.is-pinned + tr td {}` rule. Delete the empty `if (r.surplus && …) { }` block in `renderTable`; keep the `surplus` model field, since aggregation uses it.
2. **Font fallback.** `.chart-legend` gets `font-family: 'Hanken Grotesk', system-ui, sans-serif`.

**Tests (Node).**
- No match for `/pull-quote|pq-mark|marker-dot\.surplus/`.
- No match for `/if \(r\.surplus[^)]*\)\s*\{\s*(\/\/[^\n]*\n\s*)?\}/`.
- No font family without a fallback: `doesNotMatch(/font-family:\s*'[^']+'\s*;/)`.

**Commit:** `Remove dead drawdown styles and add font fallbacks`.

---

## Phase 5: Design refresh

### Task 11: Type scale

**Files:** `drawdown.html` (CSS); `tests/drawdown_theme_tokens.test.js`.

**Requirements**
1. **Tokens.** Add the nine `--fs-*` tokens to `:root`. They are not colours, so the contrast parser ignores them.
2. **Mapping.** Replace every `font-size` outside `:root`, including sizes added by Tasks 1–10, with a token:
   - 9, 9.5, 10, 10.5 and 11 → `--fs-2xs`.
   - 11.5 and 12 → `--fs-xs`.
   - 12.5 → `--fs-sm`.
   - 14 → `--fs-base`.
   - 15, 16 and 17 → `--fs-md`.
   - 19 → `--fs-lg`.
   - 26 → `--fs-xl`.
   - 36 → `--fs-2xl`.
   - 62 → `--fs-display`.

   Tracked caps may need `letter-spacing` reduced from 0.2em to 0.16em to avoid new wrapping.
3. **Re-check layouts.** Text grows slightly, so re-run and re-inspect the Task 5 and Task 6 checks at 1440, 1024 and 390.

**Tests (Node).**
- With the `:root` block removed, the `<style>` block has no `/font-size:\s*[\d.]+px/`.
- The file has no `font-size="` attribute.
- `:root` has at most 9 `--fs-` tokens, and none below 11px (parse the px values; `clamp(36px, …)` counts as 36).

**Commit:** `Consolidate drawdown typography into a nine-step scale`.

### Task 12: Verdict-first headline

**Files:** `drawdown.html` (header markup, `renderVerdict`, `rerender`, CSS); `tests/drawdown.browser.spec.js`.

**Requirements**
1. **Header markup.**
   - `.header-meta`'s eyebrow text becomes `The verdict`.
   - Replace `<h2>Investment <em>Drawdown</em></h2>` with `<h2 id="verdict" class="verdict">Projection pending</h2>`, followed by `<p id="verdict-note" class="verdict-note" hidden>Showing the last valid projection while inputs are corrected.</p>`.
   - Keep `.subtitle`; it stays accurate because the simulation is monthly even in yearly view.
   - The sidebar masthead and the page `<title>` are unchanged.
2. **`renderVerdict(rows, result)`.** Called in `rerender` right after `renderStats`, guarded with `if (el)`. Copy, exactly:
   - No rows: `Projection unavailable`.
   - `terminatedReason === 'reserve_failure'`: `Reserve fails <em>${fmtDate(dateForMonth(result.terminatedAtMonth), 'months')}</em>`, and add class `is-failure`.
   - `'cap'`: `Reserve holds through <em>the 100-year cap</em>`.
   - Otherwise: `Reserve holds through <em>${fmtDate(rows.at(-1).date, 'months')}</em>`.
   - Remove `is-failure` whenever the result isn't a failure.
3. **Style.**
   - `.verdict` uses the Fraunces display settings of today's h2 at `--fs-display`. The `em` is italic; `.is-failure em` uses `--negative`.
   - `.verdict.is-stale, .verdict.is-stale em { color: var(--text-subtle) }`. Use colour, **not** opacity: opacity drops failure text below 3:1.
   - `.verdict-note` is `--fs-xs` italic `--text-subtle`.

**Browser tests**
- **Default scenario.** `#verdict` has the text `Reserve holds through ` + `fmtDate(dateForMonth(120), 'months')`, computed in the page.
- **Failure.** Use the synthetic failure setup from the test at `:140`: the verdict contains `Reserve fails` and `fmtDate(dateForMonth(1), 'months')`, and has `is-failure`.
- **Stale.** Fill `#expense` with `''` and poll until `sidebarTimers.size` is 0: `is-stale` is present and `#verdict-note` is visible. Fill `5000`: both cleared.
- **No flicker while typing.** During a pending-only state (dispatch an input in one `page.evaluate`, as in Task 9), `#verdict` does **not** have `is-stale`.
- **Empty projection.** Call `renderVerdict([], { terminatedReason: 'invalid' })` directly: the text is `Projection unavailable`. (The `:156` setup calls `renderStats` and `renderChart`, not `rerender`.)

**Commit:** `Lead the drawdown header with the reserve verdict`.

### Task 13: Chart as centrepiece

**Files:** `drawdown.html` (`renderChart`, chart markup and CSS, `init()`); `tests/drawdown.browser.spec.js`.

**Interfaces:** consumes `lastChartRows`, `chartGeometry` and `spreadLabels` from Task 4.

**Requirements**
1. **Size.** Chart height is 280px, or 220px at ≤ 900px; this task owns it, in CSS only.
   - `padR` is `112` when `W >= 600`, otherwise `56`.
   - `.chart-x-labels` gets `padding-right: ${padR}px` from `renderChart` (an inline numeric style is fine here), so the last date aligns with the plot end.
2. **Render order, all inside `#chart` and only when rows exist:**
   1. Three horizontal `.chart-grid` `<line>`s at 25%, 50% and 75% of `innerH` (`--rule-fine`, 1px).
   2. `.chart-reserve-band`: a `<path>` **without** `data-series`. Its path is the floor points left to right, then `L lastX yZero L firstX yZero Z`, filled with `--negative-tint` and no stroke.
   3. The three series paths (unchanged `data-series`).
   4. Pin markers.
   5. The failure marker and label (unchanged text `reserve failure`).
   6. End labels.
   7. The hover group.
3. **End labels.** Two `<text class="chart-end-label" dominant-baseline="middle">` elements at `x = padL + innerW + 8`, coloured by series.
   - Text at `W >= 600`: `Buffer ${fmtMoneyCompact(last.buffer)}` and `Investments ${fmtMoneyCompact(last.investments)}`.
   - Text below 600: the value only; the legend identifies the series.
   - The y values come from `spreadLabels([...], 14, padT, H - padB)`.
4. **Legend line samples.** Each legend swatch becomes an 18×0 inline-block with a 2px top border in the series colour: solid for Buffer and Investments, dashed for Floor.
5. **Hover.**
   - **Markup:** `<g class="chart-hover" visibility="hidden">` containing a vertical `.chart-crosshair` `<line>` (`--text-subtle`, 1px) and one `<circle>` per series marked with `data-hover-series` (**not** `data-series`).
   - **Tooltip:** `<div id="chart-tooltip" class="chart-tooltip" hidden>` in the chart's relative wrapper, styled with `--surface-raised` background, `--control-border` border, `--shadow`, `--fs-xs` and `pointer-events: none`.
   - **Listeners.** Add these on `#chart` in `init()` after the inputs loop:
     - **`pointermove`,** when `chartGeometry` and `lastChartRows` exist:
       - Compute the index: `const px = e.clientX - svg.getBoundingClientRect().left`, then `idx = n === 1 ? 0 : clamp(Math.round((px - padL) / innerW * (n - 1)), 0, n - 1)`. Don't use `offsetX`: over child elements it is relative to the child.
       - Position the crosshair and dots with `chartGeometry.xOf`, `yOf` and `floorOf`. Never re-derive the scale.
       - Show the tooltip with `fmtDate(row.date, 'months')` and Buffer, Investments and Floor via `fmtMoney`. Place it at `x + 12`, flipped to `x − width − 12` if it would overflow the wrapper.
       - Set `tr.is-chart-hover` on exactly one table row:
         - Months view: `#amort-body tr[data-month="${row.month}"]`.
         - Years view: the last `#amort-body tr[data-month]` whose `data-month` is ≤ `row.month`.
       - Remove the class from any previous row first. Never scroll.
     - **`pointerleave`:** hide the group and the tooltip, and remove `is-chart-hover`.
6. **Accessibility.** `#chart` gets `role="img"` and an `aria-label` set on each render: `Trajectory of buffer, investments, and floor from <first date> to <last date>`. The table stays the accessible data source.
7. **Empty projection.** No band, grid, end labels or hover content, and the tooltip is hidden. Keep the existing empty-case clearing.

**Browser tests**
- **Default scenario at 1440.** One `.chart-reserve-band`, three `.chart-grid`, and two `.chart-end-label`s containing `Buffer` and `Investments`.
- **Label collision.** With synthetic params where buffer and investments end equal (`buffer_initial: 100000, investments_initial: 100000, floor: 0`, zero flows, `num_periods: 12`), the two end labels' `y` values differ by ≥ 14.
- **Hover.** Move the mouse to the chart's horizontal middle:
  - `#chart-tooltip` is visible and contains the page-computed `fmtDate(...)` of the middle row.
  - `.chart-hover` is visible.
  - Exactly one `tr.is-chart-hover` exists.
  - Moving outside the chart clears all three.
  - In years view, hover still marks exactly one row.
- **Narrow.** At 390 width, the end labels contain `$` but not `Buffer`.
- **Existing tests** (`:114`, `:123`, `:140`, `:153`, `:156`) still pass. The empty projection has zero `#chart path` elements.

**Commit:** `Make the drawdown chart the centrepiece with band, labels, and hover`.

### Task 14: Ledger table

**Files:** `drawdown.html` (thead markup, `<colgroup>`, table CSS); `tests/drawdown.browser.spec.js`.

**Requirements**
1. **Column widths.** Add a `<colgroup>`: `48px`, `52px` and `150px` for the first three columns, then eight `auto` columns (11 `<col>`s). From `.amort th:first-child`, delete only `width: 28px`; keep its alignment and padding.
2. **Group header row.** The thead gets a first row, `<tr class="col-groups">`:
   - Cells: `<th class="col-group" colspan="3"></th>`, `<th class="col-group" colspan="4">Flows</th>`, `<th class="col-group" colspan="2">Balances</th>`, `<th class="col-group" colspan="1">Sales</th>`, `<th class="col-group" colspan="1"></th>`. The colspans sum to 11.
   - The existing header row gets `class="col-heads"`. Its `<th>`s keep **no attributes**.
   - Scope the existing `th:nth-child(...)` alignment rules to `.amort thead .col-heads th:nth-child(...)`.
3. **Row backgrounds, sticky columns and borders.** Load-bearing:
   - `:where()` keeps banding from outranking the state tints.
   - Layering a translucent tint over an opaque surface keeps sticky cells opaque.
   - `border-collapse: separate` makes cell borders travel with sticky cells.
   ```css
   .amort { border-collapse: separate; border-spacing: 0; }
   .amort tbody tr { --row-bg: var(--surface); background: var(--row-bg); }
   .amort tbody tr:where(:nth-child(even of :not(.pin-editor-row))) { --row-bg: linear-gradient(var(--band-tint) 0 0), var(--surface); }
   .amort tbody tr:hover         { --row-bg: linear-gradient(var(--accent-tint) 0 0), var(--surface); }
   .amort tbody tr.is-pinned     { --row-bg: linear-gradient(var(--accent-tint) 0 0), var(--surface); }
   .amort tbody tr.is-insolvent  { --row-bg: linear-gradient(var(--negative-tint) 0 0), var(--surface); }
   .amort tbody tr.is-chart-hover{ --row-bg: linear-gradient(var(--accent-tint-strong) 0 0), var(--surface); }
   .amort tbody tr:not(.pin-editor-row) > td:nth-child(-n+3) { position: sticky; background: var(--row-bg); z-index: 2; }
   .amort tbody tr:not(.pin-editor-row) > td:nth-child(1) { left: 0; }
   .amort tbody tr:not(.pin-editor-row) > td:nth-child(2) { left: 48px; }
   .amort tbody tr:not(.pin-editor-row) > td:nth-child(3) { left: 100px; }
   .amort thead .col-heads th:nth-child(-n+3), .amort thead .col-groups th:first-child { position: sticky; background: var(--surface); z-index: 1; }
   .amort thead .col-heads th:nth-child(1) { left: 0; } .amort thead .col-heads th:nth-child(2) { left: 48px; } .amort thead .col-heads th:nth-child(3) { left: 100px; }
   .amort thead .col-groups th:first-child { left: 0; }
   ```
   Then clean up the old rules:
   - Delete the old pinned and hover `linear-gradient(90deg, …)` row backgrounds and the `tr.is-insolvent` background.
   - Remove `position: relative` from `.amort tr.is-pinned td:first-child`. Sticky already makes the cell the containing block for its `::before` bar, and the old (0,3,2) rule would override sticky.
   - Move the pinned row's top line from `border-top` to `box-shadow: inset 0 1px 0 var(--accent)` on its cells, to avoid double rules under `separate`.
   - The thead keeps `position: sticky; top: 0; z-index: 5`, which is already a stacking context above the body cells.

**Browser tests**
- **Group headers.** The thead contains `Flows`, `Balances` and `Sales`, and the existing `<th>Gross sold</th>` Node test passes.
- **Sticky columns.** At 1024×800, set `.table-scroll.scrollLeft = 200`. The first data row's `.col-date` left edge is within 1px of the scroller's left + 100, and the first cell of `.col-groups` is at the scroller's left edge.
- **Banding.** Data rows 1 and 2 have different computed `background-image`.
- **Pinned wins over banding.** Pin month 2 (an even row): row 2's computed `background-image` contains the accent-tint rgba, not the band tint.
- **Pinned gutter stays sticky.** On that pinned row, the gutter cell computes `position: sticky`.
- **Editor row not sticky.** With an editor open, the editor row's `td` computes `position: static`.
- **Earlier tests.** Task 5's editor tests and Task 13's hover test still pass.

**Commit:** `Group and anchor drawdown ledger columns`.

### Task 15: Sidebar form polish

**Files:** `drawdown.html` (sidebar markup for the six money fields, CSS, `init()` listener loop); `tests/drawdown.browser.spec.js`.

**Requirements**
1. **Uniform input width.** `.field .input-wrap { width: 128px }`. Merge the input sizing (`flex: 1; width: auto; min-width: 0`) with the existing `.pin-editor-field .input-wrap input` rule into one selector list.
2. **Money readouts.** For the six `$` fields (`buffer-initial`, `floor`, `external-income`, `investments-initial`, `investment-income`, `expense`):
   - Wrap the `.input-wrap` in `<span class="field-control">`, followed by `<output class="field-readout" for="<id>" aria-hidden="true"></output>`. It is `aria-hidden` because the value is already announced from the input.
   - `.field-control` is `display: grid; justify-items: end; gap: 2px`. The readout is `--fs-2xs`, `--text-subtle` and mono.
   - The tax fields keep their locked markup and get no readout.
3. **`updateFieldReadout(input)`.**
   - Find `input.closest('.field-control')?.querySelector('.field-readout')`. If there is none, return.
   - Set its text to `fmtMoney(Number(input.value))` when `input.value.trim() !== ''` and the number is finite, else `''`.
   - Call it inside the existing `inputs.forEach` input listener, and once per input in `init()` after the loop.
4. **Demote Recalculate.** `.calc-button` becomes a secondary control: transparent background, `--control-border` border, `--text` text, and hover `--text` fill with `--on-strong`. It stays full width with the same id and label.

**Browser tests**
- **Readout on load.** `#buffer-initial`'s readout is `$270,000`.
- **Readout updates.** Filling `1234567` shows `$1,234,567`; filling `''` empties it.
- **Aligned left edges.** All 11 `.sidebar .field .input-wrap` left edges are within 1px of each other at 1440×900.
- **Recalculate still works.** The existing `#calc-button` tests pass.

**Commit:** `Align drawdown sidebar inputs and add formatted money readouts`.

### Task 16: Method appendix

**Files:** `drawdown.html` (replace `<p class="footnote">`, CSS); `tests/drawdown_sales.test.js` (the lock update); `tests/drawdown_theme_tokens.test.js`.

**Requirements**
1. **Replace the footnote.** Use `<section class="method" aria-labelledby="method-title"><h3 id="method-title">Method <em>&amp; scope</em></h3><dl class="method-list">…</dl></section>`.
   - It has seven `<div class="method-item"><dt>…</dt><dd>…</dd></div>` entries, one per current `<strong>` topic, in order: Method, Tax, Income ledger, Pins, Export, Termination, Scope.
   - The `<dt>` is the `<strong>` title without its trailing period.
   - The `<dd>` is the following text **verbatim**, including `<em>` and `<code>`.
   - Drop the `·` separators.
2. **Style.**
   - Upright (not italic) body text in `--text-muted` at `--fs-sm`, with `line-height: 1.6`.
   - `dt` is tracked small caps in `--text`.
   - The list is `display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px 32px`, and the section has `max-width: 1100px`.
3. **Update the lock.** In `drawdown_sales.test.js:271–285`, extract with `/<section class="method"[^>]*>([\s\S]*?)<\/section>/` and add a comment. Keep all 7 content assertions.

**Tests.** The updated `drawdown_sales.test.js` test passes. In `drawdown_theme_tokens.test.js`, assert the file does not contain `class="footnote"`.

**Commit:** `Turn drawdown footnote into a structured method appendix`.

### Task 17: Documentation, lessons, and final verification

**Files:** `Calculation tools/README.md`; create `Calculation tools/docs/LESSONS_LEARNED.md`.

**Requirements**
1. **README, `drawdown.html` section.** Document:
   - **Themes.** Auto is the default on every load and follows the system. Light and Dark overrides live in page memory only, with nothing stored. Printing always uses light.
   - **Verdict headline.**
   - **Chart hover** highlights the matching table row.
   - **Keyboard operation:** `+` and ✎ buttons, Enter or Space on editable cells, Adjustments entry buttons, and focus returning after an editor closes.
   - **Layout** stacks below 900px.
   - **Status overlay** at the top of the sidebar.
   - **Money readouts.**
   - **Clear pins** is disabled when there are no pins.
   - **Method appendix.**
2. **README, Usage section.** Replace "Chrome, Safari, Firefox, or another modern browser" with the support floor (Chrome/Edge 123+, Firefox 120+, Safari 17.5+), and state that `drawdown.html` does not render correctly on older versions.
3. **README, test paragraph.** Mention the theme-token guard (contrast, literal-free styling, no storage, single script) and the added browser coverage. Keep `README.md:5` accurate. Do not hard-code test counts.
4. **`docs/LESSONS_LEARNED.md`.** Short entries (what's non-obvious, what to do instead) covering:
   - Two loaders extract the first `<script>`.
   - The `init()` sentinel ordering constraint.
   - SVG presentation attributes are overridden by CSS, but inline `style` is not.
   - `light-dark()` inside custom properties resolves at the use site.
   - `:nth-child(of S)` adds S's specificity, so wrap banding in `:where()`.
   - Sticky cells need opaque layered backgrounds and `border-collapse: separate`.
   - `100cqw` plus sticky keeps a full-width row inside a horizontal scroller.
   - Rerender drops focus; use `pendingFocus`.
   - Test-locked markup, listed with where it lives.
5. **PKM.** If PKM tools are available, record the outcome and key lessons, as the global instructions ask.

**Final verification** (report each item explicitly):
- [ ] `npm test` passes in full. Report the Node and Playwright pass/fail counts: 0 failures, with counts ≥ 106 and ≥ 43 plus the new tests.
- [ ] **Visual matrix.** Take screenshots at 1440×900, 1024×800 and 390×844, each in four states: Auto-light, Auto-dark, forced Light on a dark OS, and forced Dark on a light OS. Check the default scenario, the failure scenario (expense 12000), an open pin editor, the sidebar recovery editor, yearly view, and hover. Save them to a scratch dir, not the repo. List anything that looks wrong, without rationalising it.
- [ ] **Duplicate-logic sweep:**
  - `rg -n "classList\.(add|remove)\('active'\)" drawdown.html` matches only inside `setPressed`.
  - `rg -n "openCellEditor\(" drawdown.html` shows the definition plus `openCellFromElement`.
  - `rg -n "Next month's investment income" drawdown.html` matches only inside `pinFieldLabel`.
  - There is exactly one `spreadLabels` definition.
  - The reset-link and toggle styles appear only as selector lists.
- [ ] **Guards.** The Node guards pass, and `rg -n "localStorage|sessionStorage" drawdown.html` is empty.
- [ ] **Git hygiene.** `git status --porcelain --ignored -- "Calculation tools"` shows no stray artefacts (`.playwright-mcp/`, screenshots), and `test-results/` stays ignored. `git ls-files "Calculation tools/docs"` lists the plan, the findings and `LESSONS_LEARNED.md`.
- [ ] **Commit bodies.** `git log main..HEAD --format='%h %s%n%b'` shows a non-empty body on every commit.

**Commit:** `Document drawdown themes, accessibility, and layout changes`.

---

## Out of scope (by decision)

- Remembering the theme across reloads.
- `light-dark()` fallbacks for pre-2024 browsers.
- Theming the sibling calculators.
- Changing number inputs to text inputs. They are locked by tests and by validation behaviour; the readouts deliver the separator benefit instead.
- Any simulation, validation, CSV or pin-transaction change.
- Removing the table's own scroll region (deliberate and test-locked; `drawdown_sales.test.js:287–298`) or the desktop sidebar's scroll. The status overlay makes the latter harmless.
- Consolidating the two Node script extractors (spec §1.5). It was needed only for a head script, and this design has none.
- A shaded "failure zone" on the chart. Failure is always the final simulated row, so a zone would have zero width; the failure line and label carry the signal.
- Moving inputs below the results on phones. The masthead and inputs lead intentionally.

## Risks to watch

- **Wider text changes layout measurements.** Task 11 grows some text. Re-run the Task 5, 6 and 14 geometry checks after it.
- **The resize observer must not loop.** If `renderChart` ever sets the SVG's width or height, the ResizeObserver will loop.
- **Drawn chart shapes vs the `#chart path` count.** Any new `<path>` in `#chart` changes the "empty projection has 0 paths" contract. The band renders only with rows; everything else uses `<line>`, `<circle>`, `<text>` or `<g>`.
- **Specificity.** Existing rules outrank naive new selectors: `.amort td:first-child`, `.amort tr.is-pinned td:first-child`, and `.amort td { white-space: nowrap }`. When a rule doesn't apply, check specificity before reaching for `!important`. Only the reduced-motion rules and the theme-switch transition suppression use `!important`.
- **Focus management must stay one-shot.** If a rerender ever sets `pendingFocus` without an opener or closer, typing in the editor will lose focus (guarded by test `:546`).
