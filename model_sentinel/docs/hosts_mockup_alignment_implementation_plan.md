# Hosts Tab Mockup Alignment and Sort Grouping: Implementation Plan

## Goal and scope

Align the Hosts view with the Design specification and add sort grouping.
This specification is the authority for planned behavior. For unspecified
behavior, use the source at commit `6db4026`. It supersedes conflicting
requirements in `docs/hosts_redesign_implementation_plan.md`.

Changes are scoped to Hosts and its shared component integration. The Hosts
API and uptime storage are outside feature scope. Deployment is a delivery
step after merge, using the README's Standalone Install workflow.

## Source references

Paths are relative to `model_sentinel/`; `app.js`, `app.css` and `index.html`
are in `model_sentinel/browse/assets/`.

| Concern | Authority |
|---|---|
| Hosts view and toolbar | `app.js`: `Hosts`, `HostsToolbar`, `ConditionChips`, `SearchField`, `HostPicker`, `ListMenu`, `ThresholdMenu`, `OptionList`, `CONDITION_NAMES`, `CONDITION_KEYS`, `HOST_CONDITION_KEYS`, `hostConditions`, `normalizeHostConditions`, `evaluateEndpoint` |
| Results | `app.js`: `HostsTable`, `SpreadStrip`, `HostSummary`, `gapText`, `hostRows`, `HostHistory`, `DateRangeFields`, `Hosts` |
| Drawer | `app.js`: `EndpointDrawer`, `RawDrawer`; `app.css`: `.drawer-layer`, `.drawer` |
| Sorting | `app.js`: `clickSort`, `displayedSort`, `stackSort`, `SortHeader`, `SortSummary` |
| Shared pieces | `app.js`: `FilterBar`, `FindModel`, `App` (the `/` shortcut and `inputRef`), `TypeaheadOverlay`, `typeaheadPlacement`, `useFocusTrap`, `UptimeUnavailable`, `hashState`, `resolveState`, `HASH_KEYS`, `LIST_KEYS` |
| Page shell | `index.html` `.shell-header`; `app.css` `.shell-header`, `#app`, `.filter-bar` |
| Styling | `app.css`: tokens in `:root` and the dark-theme blocks, and the Hosts rules |
| Documented behavior | `README.md` Browse History (Hosts text, API paragraph, keyboard paragraph) and Testing (isolated Hosts visual acceptance) |
| Recorded lessons | repository `docs/lessons_learned.md` |
| Tests | `tests/test_browse_smoke.py` (`hosts_server` and its `many_lists`, `output_prices` and `spread_cases` variants, `hosts_page`, `_hosts_fragment`, every `test_hosts_*`); `tests/test_browse_offline.py` (Hosts probes); `tests/test_browse_theme.py` (`PINNED_DARK_TOKENS`); `tests/browse_fixtures.py` (`build_hosts_fixture_db`, `HostsFixtureFacts`) |
| Visual acceptance runtime | `tests/hosts_validation_fixture.py` |
| Version | `model_sentinel/__init__.py` `__version__`; repository `CLAUDE.md` Release Versions |

## Decision index

Audit IDs map the original comparison to implementation authorities. Align
and Merge identify design work; Keep points at the baseline source.

| ID | Area | Decision / authority |
|---|---|---|
| C1 | Chrome | Align: Page chrome |
| C2 | Chrome | Merge: Page chrome |
| C3 | Chrome | Align: Toolbar layout |
| C4 | Chrome | Align: Scrolling |
| T1 | Toolbar | Align: Toolbar layout |
| T2 | Toolbar | Align: Toolbar layout, Copy |
| T3 | Toolbar | Align: Controls |
| T4 | Toolbar | Align: Controls |
| T5 | Toolbar | Align: Conditions |
| T6 | Toolbar | Merge: Copy |
| T7 | Toolbar | Align: Copy |
| T8 | Toolbar | Align: Chips and summary line |
| T9 | Toolbar | Align: Chips and summary line |
| T10 | Toolbar | Merge: Chips and summary line |
| T11 | Toolbar | Merge: Toolbar layout |
| T12 | Toolbar | Merge: Toolbar layout |
| S1 | Model search | Align: Model search |
| S2 | Model search | Align: Model search |
| S3 | Model search | Keep: `SearchField` |
| S4 | Model search | Align: Model search |
| M1 | Menus | Align: Menus |
| M2 | Menus | Align: Menus |
| M3 | Menus | Merge: Menus |
| M4 | Menus | Align: Menus |
| M5 | Menus | Align: Menus |
| M6 | Menus | Align: Menus |
| M7 | Menus | Align: Menus |
| M8 | Menus | Align: Menus |
| M9 | Menus | Align: Menus |
| M10 | Menus | Align: Menus |
| M11 | Menus | Align: Menus |
| M12 | Menus | Align: Menus |
| M13 | Menus | Merge: Menus |
| M14 | Menus | Align: Menus |
| M15 | Menus | Align: Host scope mode |
| M16 | Menus | Align: Host picker |
| M17 | Menus | Merge: Menus |
| R1 | Results | Align: Results table |
| R2 | Results | Align: Results table |
| R3 | Results | Merge: Results table |
| R4 | Results | Align: Results table |
| R5 | Results | Align: Results table |
| R6 | Results | Align: Results table, Cell formats |
| R7 | Results | Align: Results table |
| R8 | Results | Align: Cell formats |
| R9 | Results | Align: Results table |
| R10 | Results | Align: Copy |
| R11 | Results | Keep: `HostsTable` |
| R12 | Results | Merge: Scrolling |
| P1 | Spread strip | Align: Spread strip |
| P2 | Spread strip | Align: Spread strip |
| H1 | One-host summary | Align: One-host summary |
| H2 | One-host summary | Align: One-host summary |
| H3 | One-host summary | Keep: `HostHistory` |
| W1 | Drawer | Align: Drawer behavior |
| W2 | Drawer | Align: Drawer behavior |
| W3 | Drawer | Merge: Drawer behavior |
| W4 | Drawer | Merge: Drawer rows |
| W5 | Drawer | Merge: Drawer columns |
| W6 | Drawer | Align: Cell formats, Drawer rows |
| W7 | Drawer | Align: Sort grouping |
| G1 | Sorting | Align: Chips and summary line |
| G2 | Sorting | Align: Sort grouping |
| Y1 | Type | Merge: Type and color |
| Y2 | Type | Align: Type and color |
| Y3 | Color | Align: Type and color |
| Y4 | Color | Keep: Source references (theme tests) |
| Y5 | Color | Align: Type and color |

## Earlier-plan reference index

Use the Design specification sections below when reconciling these earlier
plan sections; retained behavior comes from the baseline source references.

| Earlier plan section | Replacement authority |
|---|---|
| Layout | Page chrome; Toolbar layout; Scrolling; Controls; Model search; Copy |
| Menus and search | Conditions; Chips and summary line; Menus; Host scope mode; Host picker |
| Results and copy | Results table; Cell formats; Spread strip; One-host summary; Copy |
| Endpoint drawer | Drawer behavior; Drawer rows; Drawer columns |
| Sorting | Sort grouping; Results table → Numeric alignment |

## Design specification

### Page chrome

On Hosts only (`state.view === "hosts"`, set by `App` as `data-view` on
`<body>`):

- **Page header:** `.shell-header` is visually hidden (clipped, not
  `display: none`), so its `<h1>` stays available to assistive technology.
  `#app` top padding becomes 16px.
- **Filter bar:**
  - it renders the view tabs, with Appearance as a compact disclosure at the
    strip's right end;
  - it is not sticky on Hosts;
  - Find model and Providers are not shown on Hosts, and are unchanged on
    every other view.
- **Providers:** they move into the Compare row as a select with the
  accessible name "Provider", shown only when `meta.host_providers` has more
  than one entry.
  - Choosing a provider writes `providers` with that ID first and the others
    after it in their previous order, and clears `hasof`.
- **`/` shortcut:** on Hosts, `/` focuses the model search field. `App` points
  `inputRef` at it while `state.view === "hosts"`.

### Toolbar layout

The toolbar, the table and the pagination line sit in one panel with a
`--panel` background and a `--border` border.

- **Toolbar box:** 12px 16px 10px padding, a 10px gap between rows and a
  `--border` bottom border.
- **Row labels:** "Compare" and "Filter" in muted 13px text, 64px wide. On
  narrow viewports they take their own line.
- **Compare row:** a spacer pushes the Provider, ranking and snapshot selects
  to the right edge. Row match ("Rows: any" or "Rows: all") is a Controls
  select shown while two or more hosts are compared. Its accessible name is
  "Row match"; the ranking and snapshot selects are named "Ranking" and
  "Snapshot".
- **Summary line:** in this order:
  - the chips;
  - "Clear all", as a link-style button shown only while a condition is
    active, or "No filters. Every endpoint counts." in muted text when none
    is;
  - the sort summary;
  - the Show excluded checkbox;
  - the count, right-aligned.

- **Count:** "**n** of N endpoints · **m** models", with `n` and `m` bold,
  17px and tabular, and every number locale-grouped.
- **Results heading:** `.hosts-results-heading` stays as a visually hidden,
  focusable `<h2>` before the table, keeping the drawer's focus fallback.
- **Notes below the panel:** the capture status line, then the
  uptime-unavailable note (`UptimeUnavailable`), in muted 13px text.

### Scrolling

- **Above `48rem`:**
  - the toolbar is sticky at the top of the viewport;
  - the table header is sticky at `top: var(--hosts-toolbar-h)`;
  - the page scrolls, and the table has no vertical scroll box.
- **Toolbar height:** `HostsToolbar`'s `ResizeObserver` measures the
  toolbar into `--hosts-toolbar-h`.
- **At `max-width: 48rem`:** neither the toolbar nor the table header is
  sticky.
- **Horizontal overflow:** when the table is wider than its panel, its
  wrapper gets the class `is-overflowing` (when `scrollWidth > clientWidth`)
  and scrolls horizontally. While overflowing:
  - the model column is sticky at the left edge;
  - the table header is not sticky.
- **The document** never scrolls horizontally.

### Controls

**Toolbar buttons and selects:**
- text size from Type and color, 32px minimum height, 4px 10px padding, 6px radius;
- `--panel-raised` background, `--border` border, `--border-strong` on hover;
- `--ink` text and a 10px `--ink-muted` "▾" caret;
- selects use `appearance: none` with the caret drawn in CSS.

**Set state.** A button whose condition is set has:
- an `--accent` border;
- the background `color-mix(in srgb, var(--accent) 14%, var(--panel-raised))`;
- its Conditions summary in `--accent` after its name.

**Segmented controls:**
- 30px buttons, 4px 10px padding, inside a `--border` outline with a 6px
  radius, separated by 1px `--border` lines;
- a pressed button has an `--accent` background and `--ground` text.

**Compared-host pills:**
- 16px radius, a `--border` border and a `--panel-raised` background;
- a 9px dot in the host's series color;
- a 24px round remove button that fills with `--border` on hover.

**Link-style buttons** (Clear, Clear all, Clear sort): no border, `--accent`
text and 2px 4px padding.

### Conditions

Replace the parallel `CONDITION_NAMES` and `CONDITION_KEYS` arrays with one
`HOST_CONDITIONS` array of `{id, name, keys}`. In this order:

| id | name | keys | Summary (shown after the name in chips and set buttons) |
|---|---|---|---|
| `precision` | Precision | `quant`, `quantset` | The matching shortcut's name when the selection equals it; otherwise up to two values, then "+k"; "none" when empty |
| `uptime` | Uptime | `upwin`, `upmin`, `upmiss` | "≥ <min>% (<1 day, 30 min or 5 min>)", plus " · paused" while paused |
| `status` | Status | `healthy` | "normal only" |
| `context` | Context | `ctxmin` | "≥ <ctxmin as written>" |
| `output` | Max output | `outmin` | "≥ <outmin as written>" |
| `supports` | Supports | `params`, `ntools`, `caching` | Up to two required options, then "+k" |
| `tier` | Tier | `tiers`, `tierset` | Up to two values (`standard` for null), then "+k"; "none" when empty |
| `price` | Price | `plimit` | "<column label, lower case> ≤ <maximum as written>" |
| `hosts` | Hosts | `xhosts`, `xmode` | "excluding <up to two hosts, then +k>" or "only <…>" |
| `search` | Model search | `hq` | The search text in quotation marks |

- `hostConditions` builds its tests by `id`, so condition order no longer
  depends on array positions.
- Evaluation follows this order, and so does an endpoint's first failing
  reason.
- `ThresholdMenu`, `ConditionChips`, the menus' missing-value counts and the
  preset handlers branch on `id`.
- Every visible name and accessible name built from a condition reads `name`.

### Chips and summary line

**Chips.** A chip reads "<name>: <summary> −<removal count>" plus a remove
button. Paused Uptime omits the removal count; its summary follows Conditions.
- It is a 13px pill with a 14px radius and a 2px 4px 2px 10px padding.
- Its background is `color-mix(in srgb, var(--accent) 14%,
  var(--panel-raised))`, with a border of `--accent` at 45%.
- Its remove button is a 22px circle with the accessible name "Remove <name>
  filter".

**Sort summary.** "Sorted by <label> ▲ › <label> ▼" with a link-style "Clear
sort". With no sort set, the main view shows nothing.

### Model search

- **The field:**
  - `type="search"`, 260px wide (full width on narrow viewports), 32px tall;
  - 6px radius, `--ground` background, `--border` border;
  - a leading "⌕" and the placeholder "Filter models…";
  - accessible name "Search models".
- **In-field clear:** a button showing "×" with the accessible name "Clear
  model search", shown while the field has text. It clears the field and `hq`
  with a history entry and returns focus to the field. The browser's own
  search clear is hidden.
- **Suggestions:**
  - keep `SearchField`'s behavior, with the listbox named "Model
    suggestions";
  - matched text is bold `--accent` with no background, set on `mark` inside
    suggestions and inside `OptionList`;
  - option text stays on one line with an ellipsis.

### Menus

- **Placement:**
  - 320px wide, 6px below its button;
  - max-height `min(460px, 100vh − 140px)`;
  - header, search, shortcuts and footer stay fixed; only the option list
    scrolls.
- **Chrome:** `--panel-raised` background, `--border-strong` border, 8px
  radius, shadow `0 18px 40px var(--shadow)`.
- **Header:** the menu `name` (14px, `--ink-strong`) and a muted note at the
  right:
  - "Allow · <k> values" for Precision and Tier;
  - "Require · <k> values" for Supports;
  - "<k> hosts" for Hosts;
  - "at least" for Uptime, Context and Max output;
  - "at most" for Price.
- **Closing:** no Close button. The triggers that close a menu stay as
  `ListMenu` and `ThresholdMenu` at `6db4026` implement them.
- **Focus:** opening a menu focuses its search field. Threshold menus focus
  their custom field, and Status focuses its checkbox. For unavailable
  Uptime, focus the enabled Clear button when a threshold is configured;
  otherwise focus a programmatically focusable menu heading. Clear
  visibility follows Footer.
- **Search field:**
  - placeholder "Filter <name in lower case>…" and an `aria-label` of the
    same text, with no visible label;
  - 32px tall, 6px radius, `--ground` background.
- **Option rows:**
  - checkbox, label and count on one line, the label truncated with an
    ellipsis;
  - 5px 8px padding with a 4px radius;
  - a 12% accent tint on hover and on keyboard highlight;
  - a zero-count option at 45% opacity.
- **Group headings:** 12px `--ink-muted`, padding 8px 8px 2px.
- **Footer:**
  - "Removes **n** of N endpoints" while the condition is set, otherwise "No
    effect yet";
  - a link-style "Clear" only while the condition is set.
- **Missing values:** "Endpoints with missing values: <n>", shown only when
  `n` is above zero. It applies to Precision, Uptime, Status, Context, Max
  output, Supports, Tier and Price. Use `ThresholdMenu`'s `missingFields`
  at `6db4026` for per-condition definitions.
- **Precision:** shortcut pills directly below the search, in the order
  "16-bit or better", "8-bit or better", "Any". Each pill is 13px with a 12px
  radius and a `--border` outline, and turns `--accent` on hover.
- **Supports:** one `OptionList` with one search, grouped "Request
  parameters", "Native tools" and "Caching". "implicit caching" is the option
  in "Caching" and maps to `caching`.
- **Uptime:**
  - "Window": a segmented control with 1 day, 30 min and 5 min;
  - "Presets": a segmented control with 99%, 99.5%, 99.9% and 99.99%, where
    clicking the pressed preset clears it;
  - "Custom": a 120px monospace field with the placeholder "e.g. 99.95" and
    "%" after it;
  - "Keep endpoints without uptime (<n>)";
  - while telemetry is not `available`, follow the earlier plan's
    **Menus and search → Chips and paused uptime** policy, except for the
    closing and focus rules here; put `UptimeUnavailable` at the top and
    apply the Chips and summary line paused-count exception to the footer,
    showing "Paused" in place of the usual effect text.
- **Context and Max output:**
  - "Presets": the values in `ThresholdMenu` at `6db4026`, presented as a
    segmented control;
  - "Custom": the field with the placeholder "e.g. 100K" and "tokens" after
    it;
  - the hint "Endpoints without a value are hidden while this is set."
- **Price:**
  - the price-column select;
  - "Custom": the exact maximum with the placeholder "e.g. 2.5";
  - for a column whose unit is "/1M tokens", "Presets": "≤ $0.5", "≤ $1",
    "≤ $5", "≤ $15", writing that column's limit.
- **Status:** a checkbox "Normal status only" and the hint "Hides endpoints
  the provider reports with a non-zero status code."
- **Bottom sheet:** at `max-width: 48rem`, max-height 72vh with a 12px top
  radius.

### Host scope mode

- The Hosts menu has a segmented "Exclude these / Only these" control above
  its search. It is stored in the new key `xmode`: empty means exclude, and
  `only` means only these.
- With `xmode=only`, the condition passes an endpoint only when its host is
  in `xhosts`.
- An empty `xhosts` keeps the condition inactive in either mode.
- `normalizeHostConditions` drops any `xmode` value other than `only`.

### Host picker

- Header "Compare hosts", with "<n> of <limit>" on the right.
- Search placeholder "Find a host…".
- Option counts read "<n> models".
- Footer "Sorted by models served", and a link-style "Clear" while hosts are
  compared.

### Results table

- **Cells:** use `app.css` table text size and padding at `6db4026`. A
  missing value shows "—" in
  `--border-strong`.
- **Header row:**
  - 8px 10px padding, `--panel` background, a `--border-strong` bottom rule;
  - labels 13px, weight 600, `--ink-muted`, turning `--ink-strong` while
    sorted;
  - the direction arrow is "▲" or "▼" in `--accent` at 11px; the priority
    shows as a 9px superscript while more than one key is displayed;
  - in headers governed by Numeric alignment, the arrow comes before the label.
- **Numeric alignment (authoritative):** right-align headers and cells for
  Best, compared-host values, Spread, Hosts, Rank, Context, Max output, Uptime
  and drawer price columns wherever present. Keep Model, Host name, Endpoint,
  Precision, Status, reasons and Details left-aligned.
- **Rows:**
  - a pointer cursor, a 6% accent tint on hover;
  - the row whose list is open in the drawer gets a 12% accent tint and
    `aria-current="true"`.
  - Clicking a data row opens its drawer, and clicking the open row closes
    it. The row handler ignores clicks that start on a button or link, so
    the model button keeps its own handler and doesn't fire twice.
- **Model cell:** regular weight, `--ink-strong`, at most 300px with an
  ellipsis, and `display_id` as its title; "+1 variant" or "+N variants".
- **Ranking values (authoritative):** main-table Best and compared-host
  values, and their grouping headings, use `rankingText(endpoint, dimension)`.
  Preserve its dimension-specific behavior at `6db4026`; price formatting
  must not replace uptime, context or output ranking values.
- **Best cell:**
  - the ranking value uses Table typography in Type and color, with
    `--ink-strong`, bold in the multi-host table and regular in the one-host
    table;
  - then the winning host and "+k" for tied hosts, in muted 12px text.
- **Host cell:**
  - the ranking value uses Table typography in Type and color;
  - use `HostValue` at `6db4026` to decide whether the value is best; render
    best values bold, preceded by a 7px square rotated
    45° in `--ink-strong`, and retain `HostValue`'s accessible best-value label;
  - the gap follows in muted 12px text using that typography rule.
- **One-host column order:** Model, host value, Rank, Best, Spread,
  Precision, Context, Uptime, Status.
- **Pagination:** inside the panel, a Controls button "Show 50 more", then
  "Showing r of R models" (or "Showing all R models"), in 13px text.

### Cell formats

These apply in the main table and the drawer:

- **Gap:** use "−" (U+2212) as the negative sign and "pt" as the uptime unit.
  Do not change `gapText`'s arithmetic.
- **Rank:** "r of m".
- **Precision:** the `quantization` text in `--ink`.
- **Token counts:**
  - from a million: the count in millions with one decimal place, dropping a
    trailing ".0", plus "M";
  - from a thousand: the count in thousands rounded to a whole number, plus
    "K";
  - below that: the plain number;
  - the full integer is the cell's title, and the text is in `--capacity`.
- **Status:** "normal", or "○ status <code>" in `--ink-muted`.
- **One-host host cell when the host has no endpoint:** "not served" in
  `--ink-muted`.

### Spread strip

- **Size:** 150×18, or 120×18 in the one-host table.
- **Winner:** a 3×16 rect in `--ink-strong`.
- **Other hosts:** r=3 `--ink-muted` dots at .65 opacity.
- **Compared hosts:** r=5 dots in their series colors with a 1.5px `--panel`
  stroke, drawn last.
- **One host, or all hosts equal:** no SVG, just "only host" or "all <k>
  hosts equal" in 12px `--ink-muted`.
- **Retained behavior:** use `SpreadStrip` at `6db4026` for positioning,
  finite-coordinate handling and accessible descriptions.

### One-host summary

A baseline-aligned flex row with wrapping, 12px 16px padding and a `--border`
bottom border. At narrow widths, facts and the precision mix wrap within the
panel according to Scrolling; do not impose a fixed height:

- the host name at 20px;
- "**<n>** models", "**<n>** endpoints", "**<n>** tags", "median uptime **<u>%**" and
  "**<n>** not normal";
- "precision", then a 160×8 mix bar with a 4px radius, then up to three of
  the most common values as "<value> <count>", comma-separated.

Allow text items to shrink with `min-width: 0` and wrap long unbroken host
names with `overflow-wrap: anywhere`.

The mix bar colors values in descending count, using `--series-1`,
`--series-3`, `--series-4`, `--series-5`, `--series-6`, `--series-2`,
`--series-7`, `--series-8`, then `--border-strong`. The value `unknown`
always takes `--border-strong`.

Retain `HostSummary` fact calculations and `HostHistory` behavior at
`6db4026`.

### Drawer behavior

- **Modality:** `EndpointDrawer` becomes a non-modal panel:
  - no backdrop, and the page stays interactive;
  - `role="dialog"` without `aria-modal`, and no focus trap;
  - it uses its own `.endpoint-drawer` positioning. `.drawer-layer`, `.drawer`
    and `RawDrawer` are unchanged.
- **Placement:**
  - fixed to the right edge from the top to the bottom of the viewport,
    `min(760px, 100vw)` wide;
  - `--panel-raised` background, a `--border-strong` left border, and the
    shadow `-18px 0 40px var(--shadow)`;
  - it slides in over 0.18s, with no animation under
    `prefers-reduced-motion`.
- **Focus and Esc:**
  - opening the drawer focuses its heading;
  - `Esc` closes it and returns focus to the row's model button, but only
    while no Hosts menu and no model-search suggestion list is open;
  - those overlays register in a shared open-overlay count, which the
    drawer's `Esc` handler reads;
  - follow `EndpointDrawer` at `6db4026` for `hlist` and navigation.
- **Header:**
  - the list `display_id` at 18px, with the list path as its title;
  - "q of n endpoints qualify" in muted 15px text;
  - "Open dossier" and "Close" as Controls buttons on the right.
- **Under the header:**
  - one muted line "Also served as <names>", where each mapped model is a
    dossier link and aliases are plain text; it is omitted when there is no
    other model or alias;
  - the drawer's sort summary (Chips and summary line), or, with no drawer
    sort, the hint "Click a column to sort. Click again to reverse, a third
    time to remove it. Your first column sorts first; each column you add
    orders rows that tie on the ones before it."

### Drawer rows

- **Cells:** 6px 10px padding, no wrapping, no minimum width.
- **Host name:** regular weight, with a series dot only for compared hosts.
  The endpoint tag is muted.
- **Details:** the last cell holds a "Details" button with `aria-expanded`.
  It toggles a full-width row below that endpoint holding the endpoint
  details block in `EndpointDrawer` at `6db4026`.
- **Failing rows:** dimmed to .5 opacity, except their reason cell, which
  reads "fails <name>". The reason cell is empty on passing rows.

### Drawer columns

- **Order:** Host, Endpoint, the price columns, Precision, Context, Max
  output, Uptime, Status, the reason cell, and the Details button.
- **Price columns:** display each capture price column with at least one
  value among the list's observed endpoints. Keep descriptors for valid
  capture price paths in `drawerColumns`, setting `visible: false` on
  all-empty columns. Follow `normalizeSort` and `displayedSort` at `6db4026`
  so hidden keys remain saved in `dsort`, contribute no active sort or
  grouping while hidden, and resume when visible. Drop paths absent from
  the capture through the existing normalization policy.
- **Price labels:** the short `price_columns` label. The unit is the header's
  title, and is also shown as a muted suffix when it isn't "/1M tokens".

### Sort grouping

**The key.** The grouping key is the first key of `displayedSort` (the first
sort key shown in that table).
- While a grouping key exists, its column gets an 8% accent tint.

**Runs.** A run is a maximal sequence of adjacent rows whose values for the
grouping key compare equal under `stackSort`'s comparison. Two missing values
are equal.

**Where runs apply.** In the main table, and separately within the drawer's
passing and failing groups. They are computed over the rows on the current
page.
- When every run has one row, only the tint is drawn.

**Headings or bands.** When rows ÷ runs is at least 3, each run starts with a
heading row:
- a full-width `<th scope="rowgroup">` reading "<column label> **<value>**
  <k> <noun>";
- the noun is "model" or "models" in the main table and "endpoint" or
  "endpoints" in the drawer;
- a 2px `--border-strong` rule above every heading except the first.

Otherwise each run after the first starts with a 2px `--border-strong` rule,
and every second run gets a 5% `--ink` tint.

**Heading values,** by grouping key:

| Key | Value |
|---|---|
| `model` | `display_id` |
| `best` | Results table → Ranking values |
| `host:<name>` | Results table → Ranking values |
| `price:<path>` | `display_own` |
| `spread` | "×" and the price ratio to one decimal place; for other rankings, the difference |
| `hosts` | "<n> hosts" |
| `rank` | "#<r>" |
| `precision` | the `quantization` text, or "Width not published" for null widths |
| `context`, `output` | Cell formats tokens |
| `uptime` | "<u>%" |
| `status` | "normal" for zero; "absolute status code <magnitude>" otherwise, matching the comparator shared by signed members; missing uses the missing-value label below |
| `host` | the host name |
| `endpoint` | the endpoint tag, else its key |

Any other missing value reads "No value".

**Heading rows** are not focusable, aren't counted in the pagination text,
and don't respond to clicks.

**Failing endpoints.** The drawer's failing group always starts with the
heading "Not qualifying <k> endpoints", with a 3px `--border-strong` rule,
whatever the sort.

### Type and color

- **Text sizes:** toolbar controls and menu body text use 15px/1.45. Use
  Menus for menu-specific overrides and Chips and summary line for chips.
  Summary text and hints use 13px.
- **Table typography (authoritative):** ranking values, prices and gaps use
  the monospace stack with tabular figures.
- **Accent tints:** set buttons, chips, row hover, the open row, option
  hover and highlight, and the grouping column use `color-mix` tints of
  `--accent` at the percentages above.

### Copy

- Every user-facing text and accessible name in the Hosts view says "model"
  or "models" where it said "list" or "lists".
- Snapshot select options read "Snapshot <date>".
- Ranking options:
  - "Rank by <price column label, lower case> price" for each price column;
  - "Rank by uptime (1 day)", "Rank by uptime (30 min)", "Rank by uptime (5
    min)";
  - "Rank by context length";
  - "Rank by max output".
- The default ranking is the `pricing.completion` column when present,
  otherwise the fallback in `Hosts` at `6db4026`.
- No qualifying endpoint: "No endpoint meets every filter. <name> removes the
  most (<k> endpoints)." with a link-style "Clear <name>".

## Tasks

Each task implements its assigned Design specification sections, updates
README Browse History for that deliverable, and runs the full project suite
from `model_sentinel/`:

```bash
.venv/bin/python -m pytest
```

Acceptance requires a passing suite with no skips. Preserve unaffected
coverage; explain changed assertions in each commit body. Use
`tests/test_browse_smoke.py` with synthetic fixture variants from
`tests/browse_fixtures.py`, `tests/test_browse_offline.py` for Node probes,
and the theme/offline guards named in Source references. Add regression
coverage for the listed scenarios; assert the specification rather than
copying its contracts into another checklist.

### Task 1 (Chrome and toolbar task)

Deliver Page chrome, Toolbar layout, Scrolling, Controls, Conditions,
Chips and summary line, Model search, Type and color, and Copy.
Implement through `App`, `FilterBar`, `Hosts`, `HostsToolbar`,
`ConditionChips`, `SearchField`, `SortSummary`, and the condition
authorities in `app.js`, with their `app.css` rules.

Test scenarios:

- Hosts and Activity chrome; Appearance; keyboard search shortcut.
- Provider changes and copied URL normalization.
- Accessible select names and condition labels; active/inactive conditions;
  configured versus evaluated chips and Clear all.
- Model-search clear, draft lifecycle, suggestions and focus fallback.
- Desktop and narrow viewport scrolling; table overflow with the selection
  at `meta.pin_limit`; horizontal-overflow and sticky-column interaction.

Geometry acceptance uses `hosts_server`'s `many_lists` variant:
at 1440×1000 with no compared host, the first data row starts at or above
320px and at least 18 data rows are visible. After a 2000px page scroll,
check the Scrolling contract. At 390px, assert the same contract's narrow
viewport and document-width rules. At 1100px with the selection at the
capture's pin limit, exercise horizontal table scrolling. Suggestions must
be at most 1.5 line heights tall.

### Task 2 (Menus task)

Deliver Menus, Host scope mode and Host picker through `ListMenu`,
`ThresholdMenu`, `OptionList`, `HostPicker`, overlay placement, and the
condition/hash normalization authorities. Add the corresponding
`app.css` rules.

Test scenarios:

- Opening, focus, closing and trigger switching for menu kinds, including
  paused telemetry and recovery; pending editor cancellation.
- Footer and missing-value states; local search, keyboard highlight and
  zero-count rows; shortcuts and grouped Supports selection.
- Uptime toggling and Price-column draft/preset behavior.
- Host scope selection, empty selection, invalid mode and Back/Forward.
- At 1440×1000, opening Precision exposes its options without scrolling;
  overflowing option content scrolls under fixed menu chrome.
- Narrow viewport bottom-sheet placement according to Menus.

### Task 3 (Results task)

Deliver Results table, Cell formats, Spread strip and One-host summary
through `HostsTable`, `HostValue`, `SpreadStrip`, `HostSummary`, and
`gapText`, with their `app.css` rules.

Test scenarios:

- Row and nested-button interaction, drawer open-state semantics and
  excluded-row styling.
- Numeric alignment from Results table, including compared-host and Best
  cells across price, uptime, context and output rankings.
- Cell formats and titles, including missing values and unserved hosts.
- Spread-strip special states with `hosts_server`'s `spread_cases`
  variant; preserve the arithmetic checks in the `gapText` Node probe.
- Summary facts against `HostSummary` baseline calculations, including
  Tags, missing uptime and the precision mix.
- At 1440px wide, the one-host summary is at most 60px tall; this height
  bound is desktop-only. At 390px, use a long synthetic host name and the
  precision mix to assert the One-host summary wrapping contract and the
  document-width rule from Scrolling.

### Task 4 (Drawer task)

Deliver Drawer behavior, Drawer rows and Drawer columns through
`EndpointDrawer`, `drawerColumns`, and dedicated `app.css` rules.
Apply Cell formats and Numeric alignment by reference.

Test scenarios:

- Background interaction, overlay Escape ordering, close focus and URL
  navigation; retain `RawDrawer` baseline behavior on Activity.
- Header, aliases/dossier links and expandable details, retaining baseline
  endpoint facts.
- Collapsed data rows are at most 36px tall; expansion obeys Drawer rows.
- Missing and present price values across lists and captures, following the
  Drawer columns visibility/normalization policy.
- Sort a price column, navigate to a list where it is empty, then return:
  inspect saved `dsort`, active sort summaries and eventual restored order.
  Also exercise a price path absent from the capture.
- Passing/failing reason cells and formatted numeric columns.

### Task 5 (Sort grouping task)

Deliver Sort grouping through a `sortRuns(rows, key, columns)` helper
beside `stackSort`, reused by `HostsTable` and `EndpointDrawer`.
Share the existing comparator and add the corresponding `app.css` rules.
Set `model_sentinel/__init__.py`'s `__version__` to `0.6.0`, the
authorized minor release increment; synchronize maintained declarations.

Test scenarios:

- Node probes for comparator-equal run boundaries, missing values,
  headings/bands selection and singleton runs.
- Signed status members in a common run: assert the comparator and the
  truthful Status heading from Sort grouping.
- Ranking-dependent Best and compared-host grouping headings.
- Main-table and drawer grouping with secondary sort keys, hidden primary
  descriptors, pagination boundaries and separate qualification groups.
- Tint, rules and bands; heading accessibility, click handling and exclusion
  from data-row pagination counts.

## Final validation and delivery

Run the full suite defined under Tasks on the final tree. Check the CLI's
`--version` using `.venv/bin/python model-sentinel --version` against
the Task 5 version authority.

Use README Testing's isolated Hosts visual acceptance procedure, checking
the Design specification at 1440px and 390px in light and dark themes.
Exercise toolbar/menu kinds, comparison selections, drawer and grouped sorts.
Keep its synthetic runtime and evidence outside checkouts, and clean up
only that run's runtime after stopping its server.

After the authorized push, PR and squash merge, deploy using README
Standalone Install and its configuration-free `--version` and
`install_standalone.sh --check` verification against the merged release.
Run the installed browser with the isolated synthetic runtime from README
Testing and compare its served `app.js`, `app.css` and `index.html` bytes
with the merged source assets. Use this asset comparison for browser
delivery verification.
