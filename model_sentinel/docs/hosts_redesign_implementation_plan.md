# Hosts Tab Redesign: Implementation Plan

## Goal and scope

Rebuild the Hosts controls and results as a toolbar, compact comparison table,
and endpoint drawer, and add multi-column sorting. This plan is the available
specification; the original approved mockup and usability audit are unavailable.
It supersedes the UI sections of `docs/hosts_tab_implementation_plan.md`.

Preserve condition evaluation, exact ranking, row admission, API resource
identity, and uptime storage according to the authorities below. The API gains
one price-display field. Deployment is a separately authorized delivery step,
not an application feature in this plan.

## Source authorities and global constraints

Paths below are relative to `model_sentinel/`. Asset symbols refer to
`model_sentinel/browse/assets/app.js` unless another path is named.

| Concern | Authority to preserve or extend |
|---|---|
| Condition state and meaning | `HOST_CONDITION_KEYS`, `CONDITION_NAMES`, `CONDITION_KEYS`, `normalizeHostConditions`, `hostConditions`, `evaluateEndpoint`, `capacityMinimum` |
| Exact arithmetic and ranking | `exactRational`, `decimalRational`, `compareRational`, `rationalMagnitude`, `rankValue`, `rankCompare`, `bestEndpoints` |
| Row admission and default ordering | `hostRows`; do not change its admission rules |
| Editor lifecycle | `ConditionText`, including `editorRef`; price-column behavior in `ConditionPopover` |
| Existing menu values and condition-specific behavior | `ConditionPopover`, interpreted with `hostConditions`; intentional changes are specified under Menus |
| Shared UI | `TypeaheadOverlay`, `Portal`, `useFocusTrap`, `useApi`, `hashState`, `useHashState`, `resolveState`, `sameList`, `ErrorBanner`, `UptimeUnavailable` |
| History and date range | `HostHistory`, `RangePresets`, date fieldset and `dateChange` in `FilterBar` |
| Existing endpoint facts | `HostEndpointFacts`; retain its facts in the drawer as specified below |
| Hosts API and identity | `model_sentinel/browse/hosts_api.py`: `hosts_response`, `host_name`; `model_sentinel/browse/api.py`: `hosts`, `host_history`, `meta` |
| Price formatting | `change_render.format_price_values` and its precision helpers |
| Visual tokens and meaning | `app.css`: `:root` and dark-theme tokens; use these as the existing components do |
| Shared sticky filter bar and breakpoint | `app.css`: `.filter-bar` and its `max-width: 48rem` rule |
| Documentation | `README.md`: Browse History and Testing; `docs/LAUNCHD.md` for runtime delivery |
| Browser tests and fixtures | `tests/test_browse_smoke.py`: every `test_hosts_*`, `hosts_server`, `hosts_page`, `_hosts_fragment`; `tests/browse_fixtures.py`: `build_hosts_fixture_db`, `HostsFixtureFacts` |
| Arithmetic and API tests | `tests/test_browse_offline.py`: `test_hosts_exact_rationals_preserve_tiny_negative_zero_ties_and_decimal_limits`; `tests/test_browse_api.py` |
| Isolated visual acceptance | `tests/hosts_validation_fixture.py`; `tests/validation_runtime.py` |
| Lessons | PKM project `utilities-public`, knowledge 158, 159, 164; repository `docs/lessons_learned.md` |
| Version | `model_sentinel/__init__.py`: `__version__` |

Use packaged Preact/htm and plain CSS. Keep the browser offline and read-only.
Preserve existing logging, error handling, normalization race guards and
fresh-resource rendering. Keep runtime files and screenshots outside Git
checkouts and use conspicuously synthetic fixtures. Follow the repository's
Python venv and public-data rules.

## Layout

The global `FilterBar` stays in place. On Hosts it omits its date range,
`RangePresets`, and Detail controls. Extract the existing date fieldset and
handler into `DateRangeFields({span, state, write})`, behaving as the current
`FilterBar` does. Render it and `RangePresets` in the Host history header.
Extend `HostHistory` with `write` and `span`; pass `meta.date_span` as `span`.
Other views continue using their existing controls through the extracted piece.

Replace the question line, roster and Hosts controls with a non-sticky toolbar:

| Row | Contents in order |
|---|---|
| Compare | Removable compared-host pills; Add host; row rule; ranking; snapshot |
| Filters | Condition menu buttons in `CONDITION_NAMES` order except Model search; Model search field |
| Chips | Configured-condition chips; Clear all |
| Summary | Main-table sort summary; Show excluded; qualifying count |

Show the row rule only with at least two compared hosts. Preserve `match` when
it is hidden. The ranking select uses `Hosts`'s existing dimension construction.
The snapshot control becomes a select, newest first, labeled **Host capture**;
use capture IDs as option values and date plus model count as option text.
This replaces the Hosts date input and Earlier/Later buttons; Catalog's
`SnapshotPicker` remains unchanged. Preserve explicit unavailable captures and
provider ownership normalization as `Hosts` currently does.

Below the toolbar, render the one-host summary when applicable, then the
results table, pagination, capture status, and Host history when one host is
compared. Keep capture errors, unavailable states and empty captures according
to `Hosts`'s existing rendering, before applying the result-state rules below.

The table scrolls on each axis inside its container. Set its maximum height to
`calc(100dvh - var(--hosts-scroll-offset))`. The offset is the measured sticky
filter-bar height above `48rem`, zero otherwise; maintain it with a
`ResizeObserver` and breakpoint listener, with cleanup. The header sticks to
the container top and the model column to its left. Constrain widths so the
document never scrolls horizontally.

At `max-width: 48rem`, toolbar rows wrap, condition menus and the host picker
become bottom sheets, and the drawer fills the width. Replace obsolete Hosts
`760px` rules with this breakpoint. The global filter bar keeps its own sticky
policy; only the new Hosts toolbar is non-sticky.

## Menus and search

### Interaction and editor ownership

Use `TypeaheadOverlay` for menu positioning and portals. Menus trap Tab within
their controls but must allow pointer interaction with other toolbar triggers.
Extend `useFocusTrap` with an optional policy that suppresses background
inerting for these nonmodal menus; retain its current default for modal drawers
and other existing callers. Menus use `role="dialog"` without `aria-modal`.
Keep the shared hook's cleanup and focus restoration, adapted so dismissing
with a pointer does not steal focus from the clicked control. Search remains
a combobox with focus in its input; its listbox does not install a dialog trap.

One toolbar menu is open at a time. Opening leaves the hash unchanged. Close
on Escape, outside pointer interaction, another trigger opening, or a hash
change outside the menu's owned keys. Escape returns focus to the trigger;
a direct click on another trigger opens that menu in the same interaction.
Condition menus own their `CONDITION_KEYS` entry; the picker owns `hosts`.
Compare other hash keys to their opening values. Cancel pending text commits
before teardown for unrelated navigation, condition removal, or Clear all;
an intentional close may flush valid input using the existing editor contract.

Extend `ConditionText` with `inputProps` and an optional `onKeyDown` callback.
Call the callback first; when it returns `true` or prevents the event's default,
skip the built-in key flush. Spread ARIA/input properties without replacing
its internal input, blur, and cancellation lifecycle. Expose a draft replacement
operation on `editorRef` that cancels the timer, replaces the visible and latest
ref draft, and suppresses stale blur commits. Search suggestion selection uses
that operation before pushing `hq`; it consumes Enter and prevents a pending
partial draft from committing afterward. Pointer selection has the same
lifecycle. Free typing continues using debounce and `replaceState`.

### Menu contents

Derive names and owned keys from the condition authorities. Preserve existing
values, units, exact validation, missing-value reporting and price-target draft
behavior from `ConditionPopover`, except for the deliberate changes here:

| Condition | New presentation or interaction |
|---|---|
| Exclude hosts | Checkbox list; explanation that checked hosts are left out of comparisons |
| Status | Checkbox with explanation, retaining its predicate |
| Precision | Checkbox list grouped by descending `precision_bits`, then Width not published; preserve existing shortcut bit/null policy; inactive displays every option checked; first uncheck activates with remaining values; Any removes the condition |
| Uptime | Threshold menu; paused handling below |
| Context length | Threshold menu |
| Max output | Threshold menu with presets 8K, 32K, 64K, 128K, replacing its current presets |
| Supports | Checkbox groups headed Request parameters and Native tools; caching control |
| Service tier | Checkbox list; inactive displays every option checked; first uncheck activates with remaining values |
| Price limit | Threshold menu with existing price-column/draft semantics |

Retain Service tier and Supports missing-value information from
`ConditionPopover` alongside the other existing missing-field information.
When a condition is evaluated, its menu shows its independent removal count
and a Clear button. Clearing resets its `CONDITION_KEYS` using the same empty
value types as existing removal, after canceling pending editors.

`OptionList` supplies case-insensitive substring filtering, highlighted matches,
a checkbox row per option, arrow-key navigation and Space/Enter selection.
Group headings and shortcut controls come from the menu definition above.
Each option count is the endpoints passing every other evaluated condition
and matching that option, using `evaluateEndpoint`. The picker instead shows
`hosts[].list_count`. Option filtering is local UI state.

**Host picker:** every host, ordered by lists served descending and name for
ties. Checking appends to `hosts`; unchecking removes it. Disable unchecked
options at `meta.pin_limit`. Clear empties `hosts`. This picker replaces the
roster; the roster's name/uptime sort modes and coverage summary move out of
the selection interface. The one-host summary retains host coverage facts.

**Model search:** a `SearchField` combobox suggests capture list `display_id`s
and mapped model IDs by case-insensitive substring, highlighting the match.
Deduplicate suggestions, sort by text, and show at most 20. Arrow keys choose a
suggestion, Enter or a pointer selects it with a history entry, and Escape
closes the list. Selection obeys the consumed-key and draft lifecycle above.

**Chips and paused uptime:** derive configured chips from normalized condition
state, and evaluated conditions from `hostConditions`. A configured uptime
threshold remains visible when telemetry is unavailable: button and chip say
paused; omit its numeric removal count, retaining its remove button. Show
`UptimeUnavailable` in its menu and disable controls other than Clear and
Close. Other configured chips carry the independent removal counts currently
computed in `Hosts`. Precision uses a shortcut name when selection matches;
otherwise Precision and Service tier name up to two values then a remainder
count. Other chips summarize their condition in words. No-filter copy follows
Empty-result messaging.

**Clear all:** empty `HOST_CONDITION_KEYS`; keep ranking, row rule, Show
excluded, compared hosts, provider, snapshot and sort. This intentionally
changes Reset's treatment of ranking, row rule and Show excluded.

## Results and copy

Use `hostRows` for admission and default ordering; apply explicit sorting
only afterward. One row means one endpoint list, regardless of mapped-model
count. The Summary count is **<q> of <n> endpoints · <r> lists**, where q is
the capture-wide qualifying endpoint count, n is the captured endpoint count,
and r is the admitted row count before pagination. Label pagination **Showing
<v> of <r> lists**, with v the rendered row count. Start with 50 rows and add
50 with Show 50 more. Reset this component-local limit on condition, search,
compared-host, row-rule, Show excluded, ranking, sort or capture changes.

Columns appear in this order; parenthesized keys are their sort keys:

| Column | Visibility and content |
|---|---|
| Model (`model`) | Always; `display_id` button opens the endpoint drawer, even for unmapped lists; show +k variants for additional mapped models |
| Best (`best`) | Always; winning value and host, plus count of other tied hosts |
| Spread (`spread`) | Always; Spread strip below |
| Host value (`host:<name>`) | One per compared host; best qualifying endpoint on ranking dimension, then gap to best |
| Rank (`rank`) | One host compared; rank and denominator from `bestEndpoints` |
| Precision (`precision`), Context (`context`), Uptime (`uptime`), Status (`status`) | One host compared; the compared host's best endpoint facts, rendered as `HostEndpointFacts` does; uptime uses `upwin` |
| Hosts (`hosts`) | No hosts or several compared; number of hosts with a qualifying ranking value (`best.ranked.length`) |

Price cells use the API's new `display_own`. Other ranking values retain their
stored precision; use locale grouping only for integer capacities.
A host without a qualifying ranking value shows an em dash, has no best
marker, and remains inspectable through the drawer.

Apply row presentation in this precedence:

- `row.endpoints` empty: dim the row, Best says **No qualifying endpoint**,
  Spread is empty and host cells show em dashes.
- Qualifying endpoints but no `row.best.winner`: Best says **No values for
  this ranking**, Spread is empty and host cells show em dashes.
- Otherwise render values normally. Show excluded can admit a row through a
  selected host's observed presence while an unselected host qualifies and
  wins; do not dim the whole row or suppress its winner in that case.

A host value equal to the winner is bold with a diamond and accessible label
**best in row**. This comparison includes exact zero.

### Gap to best

Replace `winnerDifference` with `gapText(value, winner, dimension)` returning
`{text, title}`. Compute on exact rationals with BigInt. Equality is checked
first and returns best, including equality at zero. For unequal values:

- Uptime: `(value - winner)` in percentage points; two decimals, rounded half
  away from zero. A nonzero gap rounding to zero shows signed `<0.01 pp`.
- Other dimensions: `100 * (value - winner) / abs(winner)` percent; whole
  numbers rounded half away from zero. A nonzero gap rounding to zero shows
  signed `<1%`. A zero winner yields empty text and a title explaining that
  a percentage gap from zero is undefined.

Use a plus sign for a positive arithmetic difference and minus for negative:
price values worse than the minimum have plus; capacity/uptime below the
maximum have minus. This also defines negative-price behavior. For nonzero
gaps the title uses the same signed quantity and unit with
`rationalMagnitude`, described as an approximate magnitude, not unrounded.
Preserve that helper's existing precision; do not use it for comparisons.

### Spread strip

Draw each entry of `best.ranked` as an SVG dot with host/value title, compared
hosts in selection-order series colors, other hosts neutral, and a bar at the
winner. Keep ranking and tie decisions exact. A single ranked host reads
only host; equal exact values read all <k> hosts equal.

For strictly positive price values, use a logarithmic axis with the lowest
at the left. Compute logs from bounded leading decimal digits and the decimal
exponent of each rational; do not convert the complete numerator/denominator
to Number. If any price is zero or negative, use a linear axis over every
value, lowest at the left. Other dimensions use a linear axis with best left.
For linear drawing, compute each normalized coordinate as an exact rational
within [0,1], then convert a bounded fixed-point projection to Number.
Zero belongs at its linear position, not necessarily the edge for signed data.

Never emit nonfinite SVG coordinates. Distinct exact values may overlap at
one drawing coordinate; keep a separately titled mark and an accessible text
list of host/value pairs, and never label such values equal. Cover extremely
small, huge, signed, zero, and close unequal inputs in tests.

### One-host summary

Preserve the facts from `HostProfile`'s summary. Replace its precision text
with a mix bar and name the
three most common quantizations (count descending, name for ties).

### Empty-result messaging

After capture-level unavailable/error/empty handling from `Hosts`, apply:

- No qualifying endpoints and at least one evaluated condition: use `Hosts`'s
  existing `.host-no-qualifying` diagnostic copy.
  The tie order stays as `Hosts` currently determines it. A **Clear <name>**
  button removes that condition, rather than merely focusing its editor.
  Show this diagnostic even if Show excluded admits rows.
- If admitted rows are empty and the preceding diagnostic is absent: use
  `Hosts`'s existing row-rule empty message. This also
  covers hosts serving disjoint lists under all; make no zero-coverage claim.
- The chips row shows **No filters. Every endpoint counts.** only with no
  configured chips and a nonempty capture. It may accompany the row-rule
  message because it describes endpoint eligibility, not row admission.

## Endpoint drawer

Opening writes `hlist=<list path>` as a history entry. Normalize nonexistent
list paths away with `replaceState`. The right-side modal panel uses the
existing default `useFocusTrap` policy. Close button, backdrop and Escape push
an entry removing `hlist`, so closing a copied URL also works. Back/Forward
replays URL state: after a sort, Back first undoes that sort; when Back reaches
the opening entry's predecessor it closes the drawer. Do not force history
traversal to skip sort entries. Keep `dsort` while closed.

Restore focus to the originating model button on close when it still exists;
for a copied URL use the matching rendered row button, otherwise a focusable
results heading. Avoid restoring focus while navigating away to a dossier.
The header names the list and qualifying/observed endpoint counts. Open dossier
uses the first mapped model and is disabled with an explanation when unmapped.
Also retain an individual dossier button for each mapped model in the mapped
models section. Show aliases as `HostListTitle` currently does.

Render the drawer sort summary, then every observed endpoint for the list.
Passing endpoints precede failing endpoints, with failing rows dimmed. Sorting
applies independently within the passing and failing groups. Default order
within each group is ranking value in ranking direction, then host and key.

| Column (sort key) | Content |
|---|---|
| Host (`host`) | Host name and compared-host series dot |
| Endpoint (`endpoint`) | Tag/key as `HostEndpointFacts` does, plus an Endpoint details disclosure |
| Capture price columns (`price:<path>`) | `display_own`, with raw-price tooltip as existing endpoint facts do |
| Precision (`precision`) | Existing endpoint precision presentation |
| Context (`context`), Max output (`output`) | Existing capacity presentation |
| Uptime (`uptime`) | Same window/value policy as the Results uptime column |
| Status (`status`) | Existing status presentation |
| Reason (unsorted) | First failing `evaluateEndpoint` reason, using its condition name |

Retain `HostEndpointFacts` inside Endpoint details (refactor for drawer use
only as needed), preserving the renderer's facts. Main rows stay compact;
endpoint detail can expand inside the drawer.

## Sorting

`clickSort(list, key)` cycles absent → ascending appended → descending in
place → removed. Other keys retain order. `stackSort(items, list, columns,
fallback)` compares earlier keys before later keys, then fallback order and
original order for stability. Null values sort last in either direction.
Only displayed columns participate; valid hidden keys remain saved for when
the column returns. Main fallback is `hostRows` order; drawer fallback is
defined under Endpoint drawer.

Every sortable header contains a button; show direction and, for a sort
stack, priority number. Only the primary active displayed header carries
`aria-sort`. `SortSummary` renders active displayed labels and directions in
priority order plus Clear sort, or a hint generated from the click cycle.

`hsort` and `dsort` are list keys in `HASH_KEYS`/`LIST_KEYS`, with items
`a:<key>` or `d:<key>`. Valid keys come from the corresponding column tables;
validate dynamic host names and price paths against the capture. Preserve
hidden keys according to the displayed-column policy above; drop malformed keys and duplicates after the first
through `replaceState`. Sort clicks and Clear sort push history entries.
Changing ranking keeps sorting. Sort values:

| Kind | Comparison value |
|---|---|
| Price/host/Best | Exact `rankValue` rationals with `compareRational` |
| Precision | `[precision_bits, quantization]`; null bits missing |
| Status | Absolute status code; null missing |
| Spread | Prices: exact highest/lowest ratio, missing with fewer than two ranked hosts or nonpositive lowest; other dimensions: exact best-minus-worst, missing with fewer than two ranked hosts |
| Rank, Hosts, Context, Max output, Uptime | Numeric values from their column definitions |
| Model, Host, Endpoint | `localeCompare` |

## Intentional interaction changes and test migration

This section points to changed contracts; keep unaffected assertions and
replace assertions that conflict with those contracts. Do not delete coverage
for facts moved into the drawer.

| Existing surface/assertion | Replacement authority |
|---|---|
| Reset defaults, including unchecked Show excluded (`test_hosts_conditions_empty_chips_show_excluded_and_reset`, `test_hosts_reset_preserves_provider_hosts_snapshot_and_normalizes_bad_conditions`) | Clear all under Menus and search; assert retained settings |
| Question/roster/popover selectors and open-to-activate behavior | Layout and Menus and search; opening alone has no state effect |
| Precision Any and inactive tier/precision checks | Menu contents |
| Max output presets and roster sort choices | Menu contents and Host picker |
| Snapshot date input/Earlier/Later (`test_hosts_snapshot_picker_and_unmapped_list_titles`) | Layout select; choose a capture ID and assert date option text, URL, Back/Forward |
| Largest-removal focus action | Empty-result messaging; assert removal and result recovery |
| Matrix/profile/per-cell disclosures | Results and Endpoint drawer; assert facts in their new locations |
| Primary title dossier/unmapped noninteraction (`test_hosts_mapped_primary_title_opens_dossier_and_unmapped_title_stays_plain`, grouping/navigation and snapshot tests) | Endpoint drawer; assert opening for mapped/unmapped lists and retain per-model dossier navigation inside it |
| Old difference prose and host-summary arrangement | Gap to best and One-host summary |

The old empty-result messages remain the copy authorities named under
Empty-result messaging; retain their exact assertions. Compare the new
toolbar policy with `.hosts-controls` in `app.css`. Mockup differences cannot
be checked without the mockup.

## Tasks

### Task 1: Toolbar and menus

Deliver Layout and Menus and search, including FilterBar/history range
extraction. Keep the existing matrix/profile temporarily beneath the toolbar.

- Add `HostsToolbar`, `OptionList`, `ListMenu`, `ThresholdMenu`, `HostPicker`,
  `SearchField`, `ConditionChips`, `DateRangeFields` in `app.js`.
- Extend `ConditionText` and `useFocusTrap` per Interaction and editor ownership.
- Remove `QuestionLine`, `ConditionPopover`, `HostRoster`, and the controls
  block in `Hosts` after transferring their retained behavior.
- Replace obsolete toolbar/menu/roster CSS using Layout and source tokens.
- Update README Browse History and keyboard guidance for this task's changes.
- Migrate affected browser tests per Intentional interaction changes and test
  migration; record replacements and reasons in the commit body.
- Add tests for menu opening without hash writes; direct trigger switching;
  option edits keeping menus open; unrelated navigation dismissal; Escape,
  outside pointer and focus behavior; counts; substring highlighting; picker
  limits; chip removal/paused/no-filter states; Clear all retention; snapshot
  select; history date controls; narrow bottom sheets and overflow.
- Regress suggestion Enter/pointer before debounce, subsequent blur and timer
  expiry without stale-text overwrite; preserve existing price-editor race,
  column and Back/Forward cases.

Acceptance: run Full-suite validation.

### Task 2: Compact results and endpoint drawer

Deliver Results and copy and Endpoint drawer; preserve the Toolbar task's
interfaces. Sorting controls arrive in the Sorting task.

- In `model_sentinel/browse/hosts_api.py`, add `display_own` per price entry using
  `format_price_values` on that leaf alone; keep `display` unchanged.
- Add `HostsTable`, `SpreadStrip`, `HostSummary`, `EndpointDrawer`, `gapText`.
- Remove `HostMatrix`, `HostCell`, `HostProfile`, `HostListTitle`,
  `ExcludedEndpoints`, `winnerDifference`, `hostRankText` after replacement;
  keep the endpoint-facts renderer for the drawer.
- Add/normalize `hlist`; replace obsolete result CSS with container, summary,
  strip and drawer styles; place `HostHistory` per Layout.
- Update README Browse History and its API paragraph for this deliverable.
- API tests assert independent formatting and unchanged shared formatting.
- Adapt the existing exact-arithmetic Node probe to end before
  `capacityMinimum` and test `gapText`; retain existing arithmetic assertions.
- Browser tests cover compact row height (at most twice body line height),
  pagination/count domains, spread states and finite signed/tiny projections,
  exact best markers/gap titles, row precedence (including selected failing
  host/unselected winning host with Show excluded), empty copy, one-host
  summary/history, and drawer navigation/details/failed reasons.
- Preserve tests for ties, missing ranks, exact winners, stale-resource
  suppression, history coverage/truncation and legacy/telemetry states.
- Exercise the sticky header through actual vertical scrolling, and no page
  horizontal overflow at 1100px and 390px with `meta.pin_limit` selected;
  extend synthetic fixtures if needed. Verify per-model dossier links and
  mapped/unmapped drawer opening and copied-URL close/focus behavior.

Acceptance: run Full-suite validation.

### Task 3: Multi-column sorting and release

Deliver Sorting in the main and drawer tables.

- Add its helper/component interfaces, URL normalization, column value
  functions and styles to `app.js`/`app.css`.
- Update README Browse History with user-facing sorting behavior and keys.
- Release version `0.5.0` in the maintained package declaration.
- Add a Node probe covering sort cycle, stable fallback, missing-last in each
  direction and exact-rational distinctions lost by Number.
- Browser tests exercise primary/secondary sort, reversing/removing keys,
  main modes, hidden-key restoration, ranking changes, URL canonicalization,
  reload/Back/Forward, drawer sort-before-close history, and ARIA headers.

Acceptance: run Full-suite validation and Visual acceptance.

## Full-suite validation

From `model_sentinel/`, run `.venv/bin/python -m pytest`. Every project test
category must pass with no skips. This gate applies before each executable
change is committed and to the final integrated tree. Report failures by
name/output and fix them. Documentation-only plan edits need no tests.
Verify `.venv/bin/python model-sentinel --version` reports Release version
from the Sorting task; verify deployed identity again during delivery.

## Visual acceptance

Follow README Testing's isolated Hosts acceptance builder and browse command.
Use a fresh empty runtime directory outside every checkout, a task-specific
shell variable such as `hosts_acceptance_home`, and the project's venv
interpreter. Select the populated capture specified by the README. Inspect
at 1440px and 390px in light/dark themes: toolbar/menu kinds, compared-host
modes, result scroll behavior, endpoint drawer and main/drawer sorting.
Use synthetic runtime data only, check browser errors/external requests,
stop the server, and remove only the fresh directory this run created.
