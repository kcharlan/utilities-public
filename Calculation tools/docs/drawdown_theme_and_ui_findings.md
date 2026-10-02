# drawdown.html: dark mode, System theme, and look & feel findings (v2, after adversarial review)

Scope: `Calculation tools/drawdown.html` (3,355 lines; CSS 10–993, markup 995–1164, script 1166–3353). These are findings only; no repository file was changed.

> **Historical reference:** These findings describe commit `cc7a570`, before the theme and UI refresh delivered in `702a2c8` on 2026-09-29. They are measured design evidence, not an open defect list or implementation backlog. The delivered implementation uses mechanism M1 (`light-dark()`) with no head script and no storage, rather than the M2 recommendation below. Current behavior is documented in [the README](../README.md), with maintenance guidance in [lessons learned](LESSONS_LEARNED.md). The completed implementation plan has been retired; line numbers and pre-refresh measurements below remain historical.

**Evidence**
- Source reading.
- Playwright Chromium renders at 1440×900, 1024×800 and 390×844, including DOM geometry measurements.
- `emulateMedia({colorScheme:'dark'})`.
- An in-browser probe: dark values were injected into the existing tokens with `addStyleTag`, and nothing was written to disk.
- WCAG 2.x contrast ratios computed in Node.
- An independent adversarial review. Every claim it raised was re-verified before being accepted.

---

## Part 1: What dark mode plus "System" requires

### 1.1 Current state
- **No theming exists.** The file has no `@media` rule of any kind and does not use `prefers-color-scheme`, `color-scheme`, `data-theme`, `matchMedia` or web storage. With a dark scheme emulated, the body background stays `rgb(242,236,224)`.
- **Colour is mostly tokenised.** There are 17 custom properties on `:root` (11–29) and 158 `var(--…)` uses, 157 in CSS and 1 inline at 2446.
  - Tokens are named by pigment (`--paper`, `--ink`, `--oxblood`, `--ochre`), not by role.
- **Sibling calculators follow the system scheme with CSS only.** None of them has an override or uses storage.
  - `early_loan…`: light default plus a dark media query (20).
  - `lump_sum…` (18) and `money_sense…` (20): dark default plus a light media query.
  - The siblings also have responsive `@media` rules (early_loan 43, lump_sum 38, money_sense 51 and 75). drawdown.html has none.

### 1.2 Colour sources a token swap will not reach
The probe (dark values in the existing tokens only) confirmed each row below. A whole-file grep for hex, `rgb()` and `rgba()` literals, JS template strings included, finds nothing beyond this list. The CSV export carries no colour.

| Location | Literal | Result under the dark probe |
|---|---|---|
| 2355–2357 | SVG series strokes `#2C4A3E` / `#6B4423` / `#B8862A` (presentation attributes) | Cash line 1.80:1, principal 2.06:1 on the dark chart surface: near-invisible |
| 2358–2359 | pin marker line and circle `#B8862A` | stays light-mode ochre |
| 2360–2361 | reserve-failure line and `<text>` `#7A2A1F` | 1.81:1, near-invisible |
| 2368 | floor y-label, inline `style="color:#B8862A"` | inline style beats the stylesheet |
| 1099–1101 | legend swatches, inline `background:#…` | stay light-mode |
| 495 | `.chart-y-label` background `rgba(234,227,213,.85)` | cream boxes; light text on cream is unreadable |
| 42–45 | body dot grid and two tint gradients (rgba) | dot grid disappears |
| 639, 688, 712, 847, 977 | tooltip shadow, insolvency-dot halo, insolvent-row tint, changed-field tint, pull-quote tint (dead) | tuned for light only |
| 24 | `--ochre-pale` (alpha 0.08) | also the cell-editor focus ring (772), which is near-invisible in both modes |
| 68–72 | sidebar scrollbar custom-coloured with `var(--rule)` | `color-scheme` does not affect it. The thumb measures 1.39:1 in light mode and 1.42:1 with the proposed dark rule colour, so it needs its own token |
| native controls | `#pin-month` (2582) and `.pin-reset-field` (2562) have no CSS and render with UA styling | need `color-scheme` set per theme |

**Mechanics of the chart override**
- SVG presentation attributes have zero specificity, so any stylesheet rule overrides them. This includes `fill` on `<text>` and `opacity`.
- For example, `#chart path[data-series="cash"]{stroke:var(--series-cash)}` recolours the line without touching the JS.
- Pin and failure markers are the only `line`, `circle` and `text` elements in `#chart`, so element selectors work. Classes would be clearer but are not required.
- Inline `style=` (2368, 1099–1101) must move to classes.
- If chart colour lives in CSS, a theme switch needs no chart re-render.

### 1.3 Token model
- A pure same-name swap produced a mostly coherent page in the probe. Filled controls invert and still pass contrast:
  - Recalculate and the active Months/Years button (paper on ink): 14.66:1.
  - Save (paper on ochre): 9.04:1.
  - Hover state of Recalculate, Save and Remove (paper on oxblood): 7.24:1.
- **Visual-weight side effect.** In dark mode the full-width Recalculate button becomes the brightest block on the page (`#ECE4D4`). That is a design question, not a contrast failure.
- **Role tokens are recommended, not strictly required.** The reasons:
  - `--ochre` does two jobs, line/fill and text. As text it fails AA in light mode (9 text-colour uses, 8 of them live). Light mode needs a darker text variant and dark mode does not. Pigment names cannot express that split.
  - New tokens are needed regardless: `--series-cash`, `--series-principal`, `--series-floor`, `--marker-failure`, `--label-halo`, `--texture-dot`, `--shadow`, `--control-border`, `--scrollbar`.

### 1.4 Mechanism options
- **M1: `light-dark()` plus `color-scheme`.** Each token is written once as `light-dark(L, D)`. The root gets `color-scheme: light dark`, and an override sets `color-scheme` to light or dark.
  - The support floor is Chrome/Edge 123, Firefox 120 and Safari 17.5. It became Baseline "newly available" in May 2024, so it is not yet "widely available" on 2026-09-29. Live support tables were not checked.
  - Because M1 puts `light-dark()` inside custom properties, an unsupported browser makes each `var()` use invalid at computed-value time. The result is UA defaults: black text, transparent backgrounds, and none of the page's styling. It stays readable but the design is gone, and there is no graceful fallback.
- **M2: one dark block plus a JS-resolved System mode (recommended).**
  - Light tokens stay on `:root`. Dark tokens are defined once under `:root[data-theme="dark"]` together with `color-scheme: dark`, and `:root[data-theme="light"]` sets `color-scheme: light`.
  - A small head script resolves the preference and sets `data-theme`. It uses a valid stored value if one exists, otherwise `matchMedia('(prefers-color-scheme: dark)')`.
  - The page is JS-rendered anyway, so depending on JS for System mode costs nothing new.
- **M3: duplicated blocks** (a media query plus an attribute block). This duplicates the entire dark palette. A generator is ruled out because `README.md:3` says "no build step" and root `CLAUDE.md` treats these as single-file pages.

**Constraints on M2**
1. **Placement.** Put the head script before the render-blocking Google Fonts `<link>` (7–9). An inline script placed after a pending stylesheet waits for it. Also consider `<meta name="color-scheme" content="light dark">` or setting `documentElement.style.colorScheme` early. Without either, a dark-OS user may briefly see a light canvas while the fonts CSS loads or stalls offline. That flash is plausible but not measured.
2. **Storage safety.** Wrap storage in try/catch and validate the stored value (`light|dark`, anything else means System). **Never `console.error`.** Both Playwright specs fail on any `pageerror`, and `drawdown.browser.spec.js:4–11` also fails on any `console.error`.
3. **System listener.** The `matchMedia` change listener must re-check the current preference on each event and act only while in System.
4. **Switch smoothness.** `transition: all` appears on 5 rules, so a theme flip animates unevenly. Consider suppressing transitions during the switch.

### 1.5 Test-harness constraints (load-bearing)
- **Two independent extractors take the first bare `<script>`:** `tests/helpers/load_drawdown.js:9` and `tests/drawdown_dates.test.js:11`. Both use `/<script>\s*([\s\S]*?)<\/script>/`. A bare `<script>` in `<head>` would be extracted instead of the app, breaking every Node suite.
- **Recommended fix.** Export the extracted script from the helper, have the dates test use it (removing the duplicate regex), and match an explicit marker such as `<script id="app">`.
  - Minimal alternative: give only the head script an attribute (`<script id="theme-init">`). That needs zero test changes but leaves the implicit coupling and the duplicate in place.
- **The Node vm contexts are minimal.** They have no `window`, `matchMedia`, `localStorage` or `document.documentElement`. The dates test runs `init()` with a `getElementById` stub that throws for every id except `today-stamp`.
  - So theme wiring in the app script must not run at top level.
  - Inside `init()` it must come after 3287, or in event handlers only.
  - A function defined by the head script does not exist in those contexts and must only be called from handlers.
- **The app script must stay a classic script** (not `type="module"`). The browser specs call page globals: `state`, `acceptPins`, `rerender`, `renderChart`, `sidebarTimers`.

### 1.6 Control
- **Form.** A tri-state control, "Auto · Light · Dark", with `type="button"` and `aria-pressed` (or a radiogroup).
- **Reuse.** `.toggle` cannot be reused as-is: it is a full-width flex bar with `flex:1` buttons. It needs a compact variant.
- **Duplicate logic to extract.** The Months/Years active-state code is repeated per button (3302–3318). A third toggle should share an extracted helper.
- **Placement is a user decision.** Neither location is sticky.
  - Main header, top-right: the absolutely positioned date stamp (1090) is already there and collides at narrow widths.
  - Sidebar brand block (996–1001).

### 1.7 Docs, print and tests
- **README.** `README.md:5` says the pages do not "save them in browser storage". Persisting the theme choice needs that sentence amended, unless the choice stays session-only. The Usage paragraph and the Playwright-coverage paragraph need an update as well.
- **Print.** There is no `@media print`. With dark active, browsers omit backgrounds by default, so near-white text could print on white paper. Per-browser behaviour was not verified. Recommendation: force the light tokens under `@media print`.
- **New Playwright tests.**
  - Dark system scheme with no preference: dark tokens apply, and the computed chart strokes are the dark series colours.
  - Explicit Light beats a Dark system scheme.
  - A persisted choice survives reload and is applied before the app script runs.
  - A live system change while in Auto.
  - Storage throwing: the page still renders and no console error is logged.
- **Node tests.** The single consolidated extractor still returns the app script.
- **Existing assertions.** No existing test asserts computed colours. The only `getComputedStyle` use reads `::after` content (`drawdown.browser.spec.js:65`), so that tooltip pseudo-element content must be preserved.

### 1.8 Candidate dark palette ("lamplit ledger")
The idea is warm umber-black instead of the siblings' blue-grey. Contrast is measured against paper / paper-warm / paper-deep.

| Token | Value | Contrast |
|---|---|---|
| paper / paper-warm / paper-deep | #16130E / #1D1913 / #25201A | (backgrounds) |
| ink | #ECE4D4 | 14.66 / 13.84 / 12.78 |
| ink-soft | #BDB19E | 8.77 / 8.28 / 7.65 |
| ink-fade | #9C907D | 5.91 / 5.58 / 5.15 |
| oxblood (negative) | #E48A78 | 7.24 / 6.83 / 6.31 |
| oxblood-soft | #C9705F | 5.26 on paper |
| forest (positive, cash) | #8CC2A8 | 9.17 / 8.66 / 8.00 |
| ochre | #DDAE52 | 9.04 / 8.54 / 7.88 |
| umber (principal, sold) | #CFA27A | 8.03 / 7.58 / 7.00 |
| control border | #7C7060 | 3.83 / 3.62 / 3.34 |
| decorative rule | #3B3429 | 1.51 (decorative only; do not use for controls or the scrollbar) |

- **Limitation: the series are hard to tell apart without colour.** In this palette, cash/forest (L 0.470), floor/ochre (L 0.463) and principal/umber (L 0.405) are close in luminance. They differ mainly by hue, plus the dash on the floor line. A non-colour cue is needed (see 2.10).
- **Not yet rendered as a full theme.** These values were validated for contrast and applied to tokens only.

### 1.9 Decisions (resolved 2026-09-29)
1. A tri-state override: Auto · Light · Dark. Auto (follow the system) is the default on every load.
2. No persistence: the choice lives in page memory only, so `README.md:5` stays true.
3. M1 (`light-dark()`), with no legacy-browser guard.
4. Light-mode contrast is repaired in the same effort, along with every other defect and every Part 2 design direction.
5. The control goes in the sidebar masthead (the brand block).

---

## Part 2: Look & feel

The page has a committed, distinctive direction: an antiquarian financial almanac.
- Fraunces display with opsz and SOFT axes, Hanken Grotesk body, JetBrains Mono tabular figures.
- A parchment palette with oxblood, forest, ochre and umber.
- A 22px dot-grid texture, "§ 01" ordinals and tracked small caps.

That identity is worth keeping, so the recommendations fix its execution rather than replace it. Defects come first, ranked.

### 2.1 Mobile and narrow widths: the main column collapses to nothing
- There are zero media queries, and the grid has a fixed `360px` sidebar (53).
- **At 390×844:**
  - `.main` is 96px wide, which is its padding alone.
  - `.header`, `.stats`, `#chart` and `.table-scroll` are 0px wide, and `.chart-container` is 46px. The chart does not render.
  - The document is 894px wide and scrolls horizontally, and the date stamp collides with the header.
- **At 1024:** the stat labels wrap to 2–3 lines.

### 2.2 Unreachable-pin recovery editor is clipped in the sidebar
This is the recovery path the README documents.
- **Reproduction:** add a pin at month 100, set Periods to 50, then click the Adjustments entry.
- The editor renders inside the sidebar (3026–3027) at 653px wide in a 359px sidebar with `overflow-x: hidden`.
- Save pin, Remove and Cancel sit beyond the clip edge (Save's right edge is at 657 against a sidebar edge of 360), so a mouse cannot reach them.
- Scrolling the editor into view shifted the whole sidebar sideways: section labels were cut off at the left edge.

### 2.3 Chart y-axis labels are drawn in the wrong place (trust defect)
- **Cause:** `.chart-y-labels` has `top:38px; left:22px` (482–489) inside a wrapper that is already aligned to the SVG (1104).
- **Measured at 1440:**
  - The SVG top is at 386. The `$630K` label is at 427, which is *below* the $600K principal line at 402.
  - The `floor $100K` label is at 581, against a floor line at 548.
  - The `$0` label is at 608, against a zero line at 578.
- **Overlap:** the 60px label column makes the floor label wrap to two lines (581–609), and that label covers "2026" in "Oct 2026".

### 2.4 In-table pin editor hides its primary action
- **Reproduction:** set expense to 12000. The Notes column then contains items such as "reserve funding needed".
- **Measured at 1440:** the table is 1083px wide in a 984px scroller. The third field column and **Save pin** (right edge 1467, scroller edge 1392) are clipped behind horizontal scroll. The default scenario does not overflow.
- **Unfinished internals:**
  - The editor `td` is a `:first-child`, so it inherits `text-align:center` (617) and JetBrains Mono.
  - The unstyled `<h4>` headings (2521) sit in grid cells and occupy field slots.
  - `#pin-month` is a native white inset input.
  - `.pin-reset-field`, `#pin-effective-date`, `#pin-move-note` and `#pin-editor-error` have no CSS.

### 2.5 Contrast failures in light mode (WCAG 2.x)
| Pair | Ratio | Where |
|---|---|---|
| ink-fade #9A9085 on paper / warm / deep | 2.66 / 2.45 / 2.26 | 18 text uses: hints, stat details, footnote, axis labels, period column, "—" |
| ochre #B8862A as text | 2.75 / 2.54 / 2.33 | 8 live uses: adjustment dates, pin count, editor title, "+" hint, changed labels |
| paper on ochre (Save label) | 2.75 | button text |
| resting "+" (ink-fade at opacity .35) | 1.36 | the only visible pin affordance |
| ochre focus outline on cells (618–622) | 2.75 | needs 3:1 |
| `.marker-dot.pinned` (ochre) | 2.75 / 2.54 / 2.33 | needs 3:1 (non-text) |
| floor chart line (ochre) on paper-warm | 2.54 | needs 3:1 (graphics) |
| input border #CDC1AD on paper | 1.51 | control boundary; 1.4.11 needs 3:1 |
| sidebar scrollbar thumb | 1.39 | |

`--oxblood-soft` passes 3:1 (3.78 / 3.49 / 3.21). `--forest-soft` is used only by the never-emitted surplus dot.

**Repair candidates (measured):**
- ink-fade: #645B4F (5.66 / 5.22 / 4.80).
- ochre text: #7A5516 (5.69 / 5.24 / 4.82).
- control border: #7F7361 (3.94 / 3.63 / 3.34).

**Trade-off:** #645B4F sits close to ink-soft #5C544A, which collapses the three-tier ink hierarchy to two. Hierarchy would then have to come from size, italics and weight.

**Compounding:** there are 16 distinct font sizes (one, 17px, only in dead CSS), with 12 declarations at 9–10px. These are often the same low-contrast elements.

### 2.6 The whole edit surface is mouse-only
- The "+" and ✎ controls are `<span>`s (2456) with tabIndex −1.
- Editable cells have `tabindex="0"`, but Enter and Space do nothing (measured). The only opener is a click delegate (3341).
- `.adj-entry` rows are clickable `<div>`s.
- Sidebar `<label>`s are not associated with their inputs (`input.labels.length === 0`), so no input has an accessible name.
- The Months/Years buttons have no `aria-pressed` and default to `type=submit`.
- `outline:none` is set on inputs (245), and the file has no `:focus-visible` rules.

**Test lock:** `drawdown_sales.test.js:55–66` regex-match the exact `<label>…</label>\s*<span class="input-wrap"><input …>` markup for both tax fields. Associating labels changes that markup, so those assertions must be updated deliberately.

### 2.7 Validation feedback: noisy, off-screen, machine-worded; disabled export looks enabled
- **Every keystroke shows error-styled status.** It displays oxblood-bordered text such as "Showing the last valid projection. draft: Input changed; …" (3296).
  - The internal key "draft" leaks into the message.
  - The box appears above Recalculate (a layout jump).
  - Export is disabled for about 220ms.
- **Real errors use internal keys too.** For example "buffer_initial: Enter a nonnegative number." (3090 uses `item.field`).
- **The status is off-screen.** `#scenario-status` sits at the bottom of the sidebar (1081): its top measured 964 in a 900px viewport, and Recalculate's top was at 982.
- **Disabled export looks enabled.** It is `disabled` while stale (3095), but there is no `:disabled` style: opacity stays 1, the cursor stays a pointer, and hover still inverts it.
- **"Clear pins" is always shown and enabled,** and does nothing when there are no pins (1119, 3326).

### 2.8 Motion replays on every recalculation
- Each rerender replaces `tbody.innerHTML` (2476), and every row carries `animation: fadein` (960–962) with a staggered delay (2455).
- One sidebar edit fired 120 `animationstart` events, so the whole table fades back in after typing.
- There is no `prefers-reduced-motion` handling.

### 2.9 Two nested scrollers
- **Sidebar:** scrollHeight 1061 vs 900.
- **Table:** `max-height: calc(100vh - 24px)` (515), giving 876px of viewport over 4,136px of content.
- The table scroller is deliberate and test-locked (`drawdown_sales.test.js:287–298`, "bounded two-axis scroll region for sticky headers"). Treat it as a trade-off to revisit, not a defect.

### 2.10 Chart rendering
- `preserveAspectRatio="none"` (1105) scales x and y independently, so the "reserve failure" text and the stroke widths distort with container width.
- Light-mode cash (L 0.058) and principal (L 0.074) differ only by hue, which is weak for colour-vision deficiency. The legend also sits apart from the lines.
- The plot is 200px tall for a chart about 940px wide, which flattens slopes.
- **Test lock:** `drawdown.browser.spec.js:153` asserts that `#chart` (the SVG) contains "reserve failure". Moving that text into an HTML overlay requires updating that test.

### 2.11 Smaller items
- There is no thousands separator in the inputs (270000, 600000).
- `.chart-legend` uses `font-family:'Hanken Grotesk'` with no fallback (467), as does the SVG `font-family="Fraunces"` (2361).
- The subtitle says "month-by-month" in yearly view as well.
- Dead CSS:
  - `.pull-quote` / `.pq-mark` (968–992).
  - `.marker-dot.surplus` (687), which is never emitted because the note is suppressed (2447–2449).
  - The empty rule at 696–698.
  - `--rule-soft`, defined but never used.

### 2.12 Improvement directions
1. **A verdict-first headline.** Six pieces of branding copy span the sidebar brand block (mark, "Drawdown", tagline) and the main header (eyebrow, "Investment Drawdown", subtitle). Let the main display headline carry the outcome instead: "Solvent through Sep 2036" or "Reserve fails Mar 2031", in Fraunces, oxblood on failure. This becomes the page's one memorable element and uses space already spent on repetition.
2. **Make the chart the centrepiece.**
   - A taller plot.
   - A shaded band below the floor for the protected reserve.
   - A shaded failure zone.
   - Direct end-of-line labels instead of the detached legend.
   - A hover crosshair synchronised with the table row.
   - `vector-effect: non-scaling-stroke` so strokes don't distort.
3. **A ledger table.**
   - A grouped header (Flows | Balances).
   - Faint banding.
   - A sticky first column.
   - No whole-table replay: animate only the cells that changed, or nothing.
4. **The sidebar form.**
   - Fixed-width input slots, so prefix and suffix no longer create ragged left edges (the inflation box is wider; modifier and periods are narrower).
   - Associated labels.
   - A calm "updating…" state instead of error styling.
   - Real errors shown at the top of the sidebar and on the offending field, using human labels.
   - Demote Recalculate, since auto-recalculation already runs at 220ms.
   - Thousands separators on blur.
5. **A structured Method appendix.** The footnote is about 300 words of 11.5px italic at 2.45–2.66:1. Turn it into structured, non-italic content, such as a definition list or one `<details>` per topic.
6. **A type scale.** Consolidate the 16 sizes to about 8 steps, with a minimum of 11px for tracked caps.
7. **Responsive plan.**
   - Below about 900px, stack the sidebar above the main column.
   - Collapse the 5 stats to 2–3 columns.
   - Let the header stamp flow inline.
   - Allow only the table to scroll horizontally.
   - The siblings' `@media` rules are precedent.
8. **Dark identity.** Warm umber-black paper, a faint light dot grid, and pigments lifted in lightness (1.8). Avoid glows and neutral blue-grey, so the dark theme is recognisably the same almanac.

### 2.13 Limits
- Chromium only; Safari and Firefox were not rendered.
- Contrast was computed from token hex values. Text over the rgba texture and gradients was not pixel-sampled.
- The dark palette is untested as a complete rendered theme.
- Print behaviour under a dark theme was not verified per browser.
- The pre-paint flash risk (1.4, item 1) is inferred, not measured.
- `light-dark()` support figures come from knowledge, not a live support table.
