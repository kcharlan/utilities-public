# Lessons learned

## Compare history metadata at display granularity

Comparing entire method or policy objects can report an invisible change and
hide changed rows when the page suppresses row comparisons for a method change.
Compare only the displayed label and caps, preserving the shape the page reads;
test metadata-only changes together with an independently changed row.

## Keep tier identity ahead of search

Assign tier numbers before filtering so a search does not change a system's
ranked group. Browser tests counting data rows must distinguish tier heading
rows, and chart resize checks must wait for the responsive viewBox to update.

## Preserve exact limits behind rounded controls

An official threshold displayed at rounded precision can change classification if
the display value is fed back into comparisons. Represent the official selection
separately from custom input and compare with the original value. Exercise a
synthetic row between the displayed and exact thresholds, including restoration
of saved settings. JavaScript object lookups for external tokens must also avoid
inherited properties so unknown tokens remain visible.

When a numeric input applies values on each keystroke, converting and writing
the value back can destroy a decimal point while the user is still typing. Keep
the browser's editable draft separate from the applied number, and test actual
sequential keystrokes as well as the resulting threshold. Numeric placeholders
must use the same units as their labels.

## Display-aware history and board fallbacks

Choose a history baseline using the same formatting and scoring mode as the
display; a raw change can be invisible and hide an earlier visible change.
Test consecutive snapshots in each mode. Treat unknown categories as themselves
instead of assigning a known category's label or chart encoding by default.

## Grouped cleanup and ignored paths

Apply path exclusions before a grouped result is counted or capped, and apply
them again to the live candidates when a bulk action runs. Test an excluded
entry beyond the visible cap and change the exclusions after presenting the
group so the test catches both stale totals and unsafe execution.
When resolving candidate paths for exclusions, handle unresolvable entries
individually; supported Python versions can differ in symlink-loop behavior.

## Synthetic directory modes and umask

When a test requires a specific directory mode, explicitly chmod the synthetic fixture and assert its precondition: mkdir’s requested mode is filtered by the caller’s umask. Preserve the post-operation mode assertion so rejection and non-mutation remain tested under restrictive umasks.

## Cleanup traps and temporary paths

Keep a temporary path available for the lifetime of its EXIT trap and refer to it as data from a cleanup function. Interpolating a path into trap source breaks when its directory contains shell quoting characters. Preserve the original exit status, report cleanup failure, and make only one removal attempt.

In Zsh, returning a failure from an EXIT trap does not replace the original successful exit status. Disable the trap and explicitly exit with the captured primary status or a cleanup-only failure status.

Zsh's `path` array is tied to `PATH`; using `local path` for a cleanup loop can make external commands unavailable. Use a non-special variable name and exercise the real command lookup in a synthetic regression, including both successful and failed primary operations.

## 2026-11-12: Preserve Preact sibling state when showing a banner

Storage Monitor's Findings filters reset after every Trash because, with Preact
and htm, `value && html...` leaves an empty text node when `value` is `''` or
`0`. When the element appears, Preact can pair it with the next unkeyed sibling
of the same type and remount that sibling's whole subtree, losing its state. Use
`cond ? html... : null`, and key siblings that must keep their state.

## 2026-11-11: Listed on the website is not installable

On 2026-11-10 a Homebrew formula PR merged at 17:23 EST, the website
published the release at 17:44, and local `brew update` first obtained it at
18:44. An alert based only on the website could precede an installable update
by an hour. The reason for the lag was not established. Check the local tool's
own listing before promising an installable release, and record bounded events
so a future delay can be investigated.

## 2026-11-10: Take report stub field names from the real command

`usage-monthly-csv` exported Codex cached input under `cachedInputTokens`, but
`ccusage codex daily --json` emits that value as `cacheReadTokens`. `jq` turns a
missing field into an empty cell, so every row lost the value without an error.
The stub tests passed because their fake output used the script's name, not the
command's.

Copy stub fields from real output, and in the test that runs the real command
assert each column's value as well as dates and totals.

## 2026-10-31: Compare old and new in a browser when moving React code to Preact

The offline port merged with every suite green; side-by-side browser comparison
with the old pages then found the regressions, and losing every embedded font
passed too. Run that comparison for a framework port and turn each difference
into a test. htm keeps single spaces that JSX dropped, and Playwright normalizes
whitespace, so assert spacing with raw `textContent` (`assert_exact_text`).
The browser fires blur when a focused element is removed and Preact delivers it
(React suppressed it), which turned Escape in an inline editor into a save:
cancel the commit before removing the field. Preact doesn't re-assert controlled
values, so put the DOM value back after rejected
input, a failed toggle or unchanged state. A `<select>` with no matching value
renders blank where React showed the first option. Preact core treats
`spellCheck` as unknown; write `spellcheck`. A font without the requested weight
gets synthetic bold rather than a cap at its heaviest face, so embed that weight
or stop requesting it. Recharts measures grid ticks separately from labels, so a
replacement chart can't reuse label positions for grid lines. A test that waits
for a state with no bound hangs rather than fails; give mutation runs a timeout.
Chromium turns `:focus-visible` on at the first keydown after a mouse click, so
judge how focus arrived in the focus handler, not when the key lands. An
`<input>` strips newlines from `.value` but not from `.defaultValue`, so compare
a field with the `.value` captured at mount to tell whether it changed.

## 2026-10-31: Verify offline ports in the rendered browser

Block external requests and check browser errors while exercising actual views; source checks alone cannot catch runtime parsing, input events, CSS cascade or SVG attribute differences. Compare isolated synthetic baseline and port screenshots after fonts and layout settle. Preserve icon wrappers, portal attachment timing, dependent-fetch selection guards and raw string escape semantics where they affect rendering. Charts need real browser coverage for axes, legends, single points and resizing, in addition to geometry tests. Keep canonical embedded assets synchronized and test drift.

## 2026-10-31: Apply transaction inclusion to every import output

Div Conv's skipped-action branch preserved reinvestments in cooked CSV while
omitting them from QIF, so a CSV import still admitted transactions reported as
skipped. Apply the adapter's action decision before adding rows to either output;
retain source validation and explicit warnings. Filter on transaction action,
not security names or amount signs: funds change and legitimate withdrawals and
dividend adjustments can be negative. Synthetic regressions cover both Fidelity
contracts and Vanguard, changed funds, unmapped reinvestment securities, and
negative, zero and positive amounts.

## 2026-10-30: Reproduce a CDN failure with the headers a page sends

esm.sh reported healthy and each Recharts dependency opened directly, yet Git
Fleet and RouterView could not load. Browser module imports always send `Origin`.
With that header the ranged `es-toolkit` URLs bypassed Cloudflare's stale copy and
reached an origin returning `no space left on device`; `react-is@19.3.0?external=react`
failed either way. Compare `curl` with and without `Origin` before calling a URL
healthy, and read the failing request in the browser's network log. Published
exact-version modules kept serving, so a temporary import map routed those URLs
to them. The subsequent offline port replaced the remote stack and removed the
import-map contracts; embedded assets no longer depend on that service.

## 2026-10-30: Select the editable fixture and wait for its content

Launchmaster's browser test opened the first job after sorting by status, which
selected a synthetic failed job with no plist. Checking only that the editor
container appeared let the test race the asynchronous request and miss its
404. Select the synthetic job with an actual plist and assert the loaded content
before finishing; keep the browser error guard active.

## 2026-10-30: Keep test registry fixtures and argument separators explicit

Once the shared registry contained real projects, guard tests that substituted a
synthetic repository still read the real registry and failed on unrelated paths.
Give those tests an empty synthetic registry; keep the separate invalid-registry
test so validation remains covered. `argparse.parse_known_args` can consume `--`
when a positional argument precedes it, so split the raw arguments at the
separator before parsing runner controls and test both option and positional
forwarding. A warm uv script cache can make `uv python find --script` return
the script environment instead of its Homebrew interpreter; discover with
`--no-cache` in private scratch and test both cold and warm cache states.

## 2026-10-29: Snapshot closed Codex databases without changing their source

A closed WAL database can be read through a private APFS clone only after validating
the source, clone and header, and checking for writer races. Preserve the filename
and modification stamp together so rotation and failed reads retry correctly.
`SQLiteSnapshotTests` covers cleanup, alias rejection and writer races;
`changedClosedDatabasesAreReadFromSnapshots`, `rotatedClosedDatabaseWithSameDateIsRead`
and `failedSnapshotReadIsRetriedWithoutFileChange` cover the cursor behavior.

## 2026-10-29: A skip that reports ready ends a real problem's episode

Telltale skips a Codex database that is busy or that Codex has closed, and a
skip contributed no problem, so the source reported ready whenever Codex was
idle. With a genuine schema change, each Codex session reported the format
problem afresh and each idle spell cleared it: "unavailable since" restarted, the
Collector health notification fired again and a false "running again" recovery
posted in between. A skip is not a read, so it must keep the last verdict: the
Codex cursor now holds each database's last format problem (`threadHistoryProblem`,
`logsProblem`, optional so 0.2.0 cursors still decode), set by a read that finds
one, cleared by a good read and reported again on a skip. Regression:
`closedDatabaseKeepsItsFormatProblem`, with `cursorWithoutKeptProblemsDecodes`.

## 2026-10-29: "Unavailable since" must restart when the kind of unavailability changes

`CollectorRun` kept a source's `unavailableSince` for as long as it stayed
unready, so a source that went from "not set up" to "format problem" reported
the format problem as starting when the earlier, different problem did. That
also hid whether a format problem had been seen by one run or two. A source now
keeps its start only while the same kind of state continues (the text may
change) and restarts it on any other transition. `CollectorHealth` relies on that
start: a format problem notifies only when a report's `updatedAt` is later than
its `unavailableSince`, so one run shows on the lamp but does not post. Regression:
`notSetUpThenFormatProblemRestartsUnavailableSince`, with
`formatProblemFromOneRunShowsButDoesNotNotify` and `oneRunFormatProblemPostsNothing`
covering the policy.

## 2026-10-29: Read-only SQLite can't open a WAL database its writer closed

Telltale reported a "format problem" for Codex's databases whenever Codex was
closed. Codex's last connection deletes `-wal` and `-shm`; the system SQLite a
`mode=ro` reader links then opens the file but fails its first statement with
`SQLITE_CANTOPEN` (14), which looked like a changed schema. The fixtures hid it
because the system SQLite keeps the WAL on close by default
(`SQLITE_FCNTL_PERSIST_WAL` is 1), so a test writer's close left both files in
place. `CodexDatabase.closeLikeCodex()` now turns persistence off before closing,
and `reopen(_:)` writes again afterwards. The reader recognizes the state by a WAL
header (bytes 18 and 19 equal 2) with no `-wal` and skips the file quietly like a
busy one, keeping its cursor. Treat that evidence as a hint, not proof that no one
has the file open, and keep an unreadable main file a failure. Colophon's lessons
cover how other readers behave on the same files.

## 2026-10-28: Distinguish cold start from a still-learning baseline

A model can have enough active days to judge speed while its baseline is still
learning toward the full history target. Arrival copy that lists models past cold
start must include both learning and fully ready states, and exclude only cold
models. Exercise the intermediate state explicitly in the read-model test.
An arrival that is already pending must also survive a later in-progress rebuild;
the rebuild's current backfill state does not erase the completed arrival.

## 2026-10-28: Keep stream diagnostics aligned with cursor checkpoints

When an incremental transcript reader defers an incomplete response, events,
diagnostic counts and version observations after that response must also wait
for the cursor to advance. Snapshot those outputs with the checkpoint so a
later pass neither duplicates events nor records metadata beyond its offset.
Detect format drift from fields independently of whether timestamps parse, and
compare source versions by version precedence rather than file traversal order.
Decode identity separately from optional usage so malformed usage still raises
drift, and persist invalid-format observations with the cursor. Guard stored
latest snapshots by observation time: a later ingest can contain an older event.

## 2026-10-28: A SwiftUI alert clears its binding before a confirm task runs

Telltale 0.1.0's Rebuild from Codex logs… did nothing when confirmed. The alert
was bound to the model's `confirmingRebuild` flag, and its Rebuild button started
`Task { await model.confirmRebuild() }`, which began with `guard confirmingRebuild`.
Closing the alert sets the binding false, which cleared the flag before the task
ran, so the guard returned silently: no write, no error, no run. The unit test
called `requestRebuild()` then `confirmRebuild()` directly and never saw the
dismissal. An alert button's action must not read back state that the alert's
own binding clears: take what it needs from the `presenting:` value its closure
receives, or treat the button itself as the confirmation. A test of a confirmation
should dismiss first (call the binding's setter), then confirm.

## 2026-10-28: A Swift deploy leaks into two temp dirs, including from its preflight

Brew Version's and Anker Charge Monitor's deployers ran `make release` with the
caller's `TMPDIR`. A unique scratch path means a new set of leftovers on every
deploy: about 22 empty `TemporaryDirectory.*` folders and lock files named after
the scratch path. Pointing `TMPDIR` into the removed scratch does not cover
everything. Each compile still drops a `TemporaryDirectory.*` holding only an
empty `.keep-directory` into `getconf DARWIN_USER_TEMP_DIR` whatever `TMPDIR`
says, and even `xcrun swift --version` leaves a `TemporaryDirectory.*` in
`TMPDIR`. Give every toolchain call the scratch `TMPDIR`, including version
checks. After the build, passing or failing, remove only new marker-only
directories from the Darwin dir. Test it with a fake Darwin dir, through a
`getconf` double on the fixture `PATH`, so the suite never sweeps the real one.

## 2026-10-28: Never pin NSApp.appearance, and make "follow the system" nil all the way up

A native acceptance harness pinned light or dark with its own buttons. They
set `NSApp.appearance` as well as the panel's, and that pin outranks the
system for every window that has no appearance of its own. A dashboard set to
Match system (`window.appearance = nil`) then inherited the pin, so it stayed
Light under a Dark system, ignored system changes even after closing and
reopening, and looked intermittent because it depended on whether a harness
button had been pressed first. A harness may override only the specific window
or panel it is exercising; it must never set `NSApp.appearance`. Following the
system means `nil` at every level above the view: no window appearance and no
application appearance. Test it by pinning through the harness, choosing the
follow-the-system setting, then asserting both appearances are nil and that
the window's `effectiveAppearance` matches `NSApp.effectiveAppearance`.

## 2026-10-27: Verify plan ports by test identity and injected boundaries

A subset port cannot use whole-file test counts as a coverage check. Record
source-to-destination test names, preserve the selected cases, and permit
explicitly documented adaptations. Inject installation locations as well as
runtime homes so an auto-install regression can run entirely in temporary
storage. Run final validation after harness and snapshot edits, and include
untracked files when inspecting a proposed implementation for private data.

## 2026-10-23: Apply provider policy throughout structured expansion

Checking parameter membership only at the original changed path lets an
introduced parent bypass malformed-operand validation. Pass the active profile
through recursive flattening and stop at every recognized membership path,
including exact custom nested paths. Endpoint capability admission must also
consider expanded descendants when the original parent is not admitted; an
absent parent and an empty parent must give the same capability selection and
summary. Preserve unrelated full-detail parent metadata and original source
records while selecting eligible leaves.

## 2026-10-23: Count endpoint capabilities before selecting report detail

Concise endpoint reports previously selected only price, presence and
conditional rows, hiding meaningful parameter and capability changes. Classify
capability leaves using the provider profile before detail filtering and count
changed lists before applying the cap. Preserve each original change record
when expanding supplied objects, and track whether any full-detail content
exists so parameter set no-ops do not create empty headings or inflate the
detail-only remainder. Price, status and context routing still take priority
over custom capability patterns.

## 2026-10-23: Normalize frozen JSON at the presentation boundary

Model Sentinel freezes comparison-event arrays into tuples and mappings into
read-only proxies. A renderer recognizing only mutable lists or dictionaries
therefore loses member deltas and structured leaf expansion after semantic
projection. Detach mappings and list/tuple containers recursively before
presentation, preserving the immutable event and raw source records. Test the
normalize/diff-to-event, stored-event and direct compatibility paths separately.
Provider-recognized parameter-name collections use validated unique string
membership; malformed or unknown operands stay neutral and cannot bulk-group
as capabilities. Every browser transition consumer must show the same member
evidence. Filtering human no-ops must retain recorded counts, identities and
truncation evidence rather than implying complete history from a loaded page.

## 2026-10-23: Check pointer layering and empty-menu focus with nonmodal panels

A nonmodal drawer makes background triggers usable, so their portaled menus
and suggestions must paint above it. Scope the higher layer to Hosts rather
than changing the generic typeahead or raw evidence drawer. Assert actual
overlap, elementFromPoint ownership and physical clicks in both themes and
after narrow resizing; visibility assertions cannot detect occlusion. Retain
first-Escape overlay dismissal and second-Escape drawer dismissal.
An empty Price capture renders no custom editor and no unconfigured Clear
button. Select the existing programmatically focusable heading instead of an
absent text field, and exercise both Tab directions plus Escape trigger return.
Keep the ordinary priced-capture custom-field focus regression alongside it.

## 2026-10-23: Scope table hover feedback to actionable data rows

Adding inert group headings to a tbody also subjects them to broad row-hover
rules. A later heading background rule can still lose on specificity. Restrict
interactive hover selectors to the existing model-row identity attribute,
and regress both heading background stability and preserved data-row feedback
with real pointer hover in light and dark themes.
Keep identity-only selector conditions specificity-neutral with `:where()`:
otherwise narrowing a hover rule can override the selected-row background.
Include hovering the open `aria-current` row in that same state matrix.

## 2026-10-23: Keep exact sort-group equality and ratio headings together

Hosts grouping must use the same missing-value and exact rational comparator
as sorting; display strings can round unequal values together or distinguish
equal signed status magnitudes. Partition before grouping and group only the
current page. Render shared status magnitudes explicitly rather than choosing
one signed member's status. Round price-ratio headings with integer arithmetic:
converting a finite exact ratio to Number can produce Infinity. Cover an
extreme synthetic ratio alongside signed members, missing runs and pagination.

## 2026-10-23: Make endpoint inspection nonmodal without losing saved sorts

Model Sentinel's modal endpoint layer intercepted the second pointer click
needed to toggle an open results row and prevented replacing it from another
row. Use independent panel positioning and heading focus, preserving the raw
evidence drawer's modal lifecycle. Gate panel Escape on the shared Hosts
overlay count during capture, before descendant handlers can synchronously
dismiss their overlay and lower the count during that same event. A bubble
listener can otherwise close both suggestions and panel with one key. Force
immediate rendering in a focused browser regression and check the settled
first key preserves hlist, then the second closes and restores focus.
Keep all capture-valid price descriptors when hiding all-empty columns for
one model: normalization validates capture identity while displayed sort
controls active ordering. Regress physical row toggling, replacement, nested
model buttons, overlay Escape, and saved price sorts across models/captures.
Filter the heading identity from mapped names and aliases before deciding
whether to render an "Also served as" line; a single-model fixture whose
display ID equals its mapped model catches otherwise redundant copy.

## 2026-10-23: Deliberate presets must replace uncommitted editor text

When a numeric preset equals the already committed value, cancelling a pending
draft and writing that same value does not trigger the editor's value-change
effect. Its field can keep showing the abandoned draft even though the URL and
filter still use the preset. Apply deliberate presets through the existing
`replaceDraft` lifecycle only when reselecting the committed value. Other
presets cancel the draft and follow the URL update; an optimistic field update
can race immediate Back/Forward ahead of the hash render. Regress reselecting
the current price and capacity preset while a different exact draft is pending,
then wait beyond debounce.
Focus traps also need `:disabled` checks so descendants of a disabled fieldset
cannot become their first or last focus target when telemetry is paused.
When no enabled controls remain, prevent both Tab directions and retain the
programmatically focused heading; returning early otherwise releases focus to
the page while its menu remains open. Escape must still restore its trigger.
Fixed popup chrome also needs a shrinkable body: nonshrinking threshold forms
can exceed the space below a trigger on landscape screens. Keep the header and
footer fixed, and let the form body alone scroll when constrained. Test every
control with a real hit test after bringing it into view, check that the chrome
does not move, and cover paused forms whose controls are all disabled.

## 2026-10-23: Separate page stickiness from horizontal comparison scrolling

When a table uses page scrolling, an overflowing horizontal wrapper becomes
the sticky header's scrolling ancestor. Measure overflow and disable vertical
header stickiness in that mode, including clearing the first column's inherited
`top` offset while retaining its horizontal stickiness. Use `overflow: clip`
before the resize observer settles to prevent a transient document-width leak
without creating another scrolling ancestor. Check the real header and model
column after horizontal scrolling, and check document width immediately after
desktop-to-mobile resizing. Portaled suggestion options also inherit shared
typeahead layout: explicitly use a single text line so marked matches do not
become separate grid rows.

Compact rendering also exposed a baseline overlay readiness race: a drawer
could be visible before `useEffect` registered its Escape listener. Register
focus-trap listeners with `useLayoutEffect`, retaining the existing deferred
focus movement and cleanup. A DOM mutation observer that sends Escape as soon
as the drawer exists reproduces the missing-listener interval deterministically;
ordinary content visibility assertions can finish before deferred effects.

An absolutely positioned disclosure panel must size to its own contents,
bounded by the viewport, rather than inheriting a percentage limit from its
small trigger. Check each option against its clipping ancestors and hit-test
its visible center before clicking: browser automation can otherwise scroll
a clipped row internally and make an inaccessible option look usable.

## 2026-10-22: Treat unselected combobox navigation and focus departure explicitly

A suggestion index of -1 means no active option; it is not an existing index
to wrap. Handle the first ArrowUp as selecting the last option and the first
ArrowDown as selecting the first, then wrap ordinary navigation. Close a
suggestion list when keyboard focus leaves the search control as well as on
Escape and outside pointer interaction. Keep pointer selection from causing a
premature blur, and retain the editor's pending-draft cancellation when a
suggestion is chosen. Test initial upward navigation, keyboard departure into
another menu, and both Enter and pointer selection before debounce.

## 2026-10-22: Keep independent history visible when result filters exclude every row

Model Sentinel's one-host history was nested inside its qualifying profile
results, so an empty condition result also hid the host's history and its date
controls. Render an independently keyed history resource from the selected host,
outside the filtered-results branch. Regress both its ordinary view and the
same host with no qualifying rows; result admission must not control access to
unfiltered history.

When a capture selector adds an explicit unavailable capture to an API's ordered
options, retain the timestamp ordering and use IDs only to break ties. Import
identity need not follow observation time; test with those orders deliberately
different.

## 2026-10-22: Give debounced condition editors an explicit commit lifecycle

Model Sentinel's price editor captured an old column in its timer. Blurring
a pending draft while removing the condition also queued replace and push
updates whose normalization effects alternated forever. Read the latest commit
target from a ref, cancel timers and blur commits before removal, and apply a
column selection to the current draft as one action. Ignore normalization
effects whose source state no longer matches the current hash/resource; the
same race can happen when a pending value precedes a checkbox change. Keep
typing as replace and deliberate presets as push; let their displayed value follow URL state
so fast Back/Forward cannot leave an optimistic draft behind. Regress the
whole edit/switch/remove sequence with a watchdog outside the browser renderer.
When invalid intermediate text falls back to the last committed value, apply
that same exact text to a newly selected target too; restoring only the field
leaves its visible target and the active URL filter inconsistent.
Resynchronize the editor's local price-column selection when the committed URL
path changes, even if its numeric text does not. Preserve a column-only draft
while no limit exists by following path changes rather than every rerender.
Represent the absence of a committed target separately from the initial
default: clearing a ceiling must retain the local column for retyping, while
restoring an active URL ceiling must override that draft even when its target
equals the initial default. Regress both transitions with exact text, missing
counts, filter outcomes and Back/Forward navigation.

## 2026-10-22: Reject synthetic runtime targets in both worktree and main checkout

Model Sentinel's acceptance builder originally checked only the checkout
containing its source. From a linked worktree that allowed synthetic runtime
files inside the main public checkout. Resolve Git's common directory and
check both checkout roots by filesystem identity before writing. Exercise the
shared isolation helper through each runtime builder, including symlink/case
aliases, and clean only the exact fresh test-created target in a failure path.
Known checkout roots are not exhaustive. Check resolved target ancestry for
Git checkout markers (directories or linked-worktree files) before creating
directories, and regress unrelated checkouts using disposable synthetic Git
repositories and the preflight alone so no runtime files are written there.

## 2026-10-22: Exercise primary navigation targets, not only nearby links

Model Sentinel's Hosts rows exposed individual mapped-model dossier buttons,
but the primary list title remained plain text despite its action contract.
Testing only the secondary links missed that gap. Exercise the primary title
itself against a real synthetic dossier, retain each shared-list model link,
and assert unmapped titles remain noninteractive. Similarly, test the visible
view tab directly in addition to keyboard shortcuts.

## 2026-10-22: Validate snapshot ownership before requesting a new provider

Model Sentinel's shared Providers controls preserve view-specific hash keys.
Hosts initially reused `hasof` after the selected provider changed, sending an
exact scrape ID owned by the previous provider and receiving a 400. Validate
the requested ID against the selected provider's saved successful scrapes
before issuing the request. If it does not belong there, request the default
capture and canonicalize the returned ID with `replaceState`. Keep explicit
valid uncaptured and failed snapshots exact; do not substitute another capture
for them. Regress provider changes, malformed IDs, and Back navigation with
the isolated synthetic Hosts fixture and the browser's console-error guard.

## 2026-10-22: Mark telemetry processing separately from sample presence

A missing numeric sample cannot distinguish an unprocessed archive from a
processed capture with empty lists or rejected values. Keep a capture-level
completion marker and write it with its samples in one transaction. Backfill
each archive independently, use the observation parser and duplicate-key
authority unchanged, and count unmatched observations rather than inventing
links. Preserve raw telemetry separately from validated numeric columns;
Python booleans are integers but are not valid uptime percentages. Regress
empty processing, duplicate identities, late write failures and retries with
synthetic archives.

## 2026-10-22: Validate bundled tax rules separately from frozen parity inputs

Tax2's engine correctly supported earned-only components, but its bundled PA
EIT component was disabled, so entering earned income never added local EIT.
Exercise the live bundled rules with synthetic mixed income, earned-only and
unearned-only cases, and state allocations. Check the displayed result and
downloads too. Preserve historical parity rules and outputs; document and
compare intentional live-rule differences explicitly rather than regenerating
the retired-engine oracle. Keep bundled locality labels generic.

## 2026-10-20: Use the system CLI consistently in usage exports

`usage-monthly-csv` invoked a pinned npm package while the user's `ccusage`
command used a newer installation. The old adapter discovered only `.jsonl`,
so Codex's migration of cold logs to `.jsonl.zst` silently removed historical
days and undercounted surviving dates. Compare the actual versions and source
discovery rules before blaming CSV conversion or calendar filtering.

Call the system command, including interactive Zsh functions and aliases,
rather than choosing a separate package version in the wrapper. Test with real
compressed synthetic logs as well as report stubs: a stub that returns complete
JSON cannot reveal an upstream discovery failure. Keep the synthetic home and
reports outside the checkout, force offline pricing, and verify token totals
as well as dates.

## 2026-10-20: Size a menu bar icon item with variableLength, not squareLength

Brew Version's mug sat in visibly wider gaps than neighbouring items.
`NSStatusItem.squareLength` makes the button as wide as the bar's thickness
(22pt), so a 12.5pt mug got 3pt more blank on each side than `variableLength`,
which sizes the item to its image. Measure the ink margins inside the status
item's window before guessing at a cause: a button title adds its own cell
insets, which length does not change.

## 2026-10-19: Keep app activation separate from deployment provenance

An app-only deployer must not inherit CLI `--help`/`--version` probes: those
arguments can launch a real GUI and its credential/cloud work. Reuse the
existing whole-bundle activation owner, bind complete bundle bytes/modes and
the selected signing certificate to a private receipt, and include the actual
installer/signing scripts in the exact Git-index build inventory. Exercise
receipt and cleanup failures after activation as transaction failures too;
restore the prior app and receipt while retaining independent recovery copies.
Audit the canonical `/Applications` destination without silently falling back
to a home copy. Launch-at-login registration remains a separate native check.
When staging an admitted source snapshot, explicitly restore each indexed file
mode after creation: writeFile's requested mode is reduced by the caller's
umask. A private synthetic build checks exact 0644/0755 inputs under umask 077.

## 2026-10-19: Draw coloured menu bar icons yourself; don't tint template images

Brew Version marked a watched update by setting `contentTintColor` on its
template status image. The macOS 27 menu bar ignores that tint and draws the
template image black, so the alert vanished on a dark bar. The button's
`effectiveAppearance` is no guide either: it reported VibrantLight while the
bar was dark. An `NSImage(size:flipped:drawingHandler:)` does get the bar's
real appearance at draw time, so draw dynamic colours there. Choose ones
that stay opaque: `labelColor` is only 70% black in VibrantLight, while
`textColor` is opaque in all four appearances. To test, render the image into
a bitmap under each appearance and check its pixels. To see real menu bar
items, wrap a scratch harness in an ad hoc signed `.app`, because items from an
unbundled binary never appear.

## 2026-10-18: Give overlay scroll bars a gutter instead of widening a popover

macOS overlay scroll bars draw on top of a scroll view's trailing edge, so
Brew Version's section counts and collapse chevron sat under the scroll bar.
Widening the popover only moves that edge. Extend the scroll view into the
popover's existing side margin and pad its content by the same amount, so
the scroll bar travels in empty space and content alignment is unchanged.
For pinned list headers, use the panel's own behind-window material as the
header background so rows vanish beneath it without a visible bar. Test the
scroll view's frame against the popover edge, and compare a rendered header
strip before and after scrolling, with a guard that the rows really moved.

## 2026-10-18: Record unreadable DSL fields before suppressing their blocks

Brew Version's tap reader skipped a `version compute_version do` statement
while entering its ignored block, then treated the explicit version as absent
and accepted a later URL or literal version. Record first-field presence in
the active package scope before handling its block. Preserve the unreadable
arguments and suppress the body independently. Regress both URL fallback and
later literal replacement, plus matching and ignored architecture scopes, so
the correction cannot admit fields from a suppressed parent.

## 2026-10-18: Port regex anchors and filename suffix removal together

Brew Version's Homebrew detector matched ordinary URLs but diverged after
percent-decoding an LF: Ruby's `^`/`$` match line boundaries, while default
Foundation expressions do not. Enable line anchors with Unix LF semantics,
and translate Ruby's `\Z` explicitly: ICU still accepts CR and Unicode final
terminators for `\Z` in Unix mode. A regex extension match before a trailing
LF is not necessarily a literal filename suffix; Ruby's `File.basename`
removes it only when the filename actually ends with it. Preserve that check
instead of blindly dropping the captured length. Generate expected URL and
tag results through the pinned upstream implementation for LF, CRLF, CR,
NEL, Unicode line/paragraph separators, vertical tab and form feed.

## 2026-10-18: Separate typed normalization from canonical identity decoding

Brew Version's tap normalizer removes one reserved repository prefix, matching
Homebrew. Reusing it for a canonical accessor or Codable decode removed a
second prefix, changed a package's identity, and could make a successfully saved
watch unreadable when the second pass identified an official tap. Share segment
validation while keeping typed normalization separate from canonical decoding.
Regress repeated and mixed prefixes through accessors, both identity Codable
roundtrips and actual watch-store save/load, including a reserved core alias.

## 2026-10-17: Refresh "at launch" means every launch, and match brew outdated

Brew Version's spec said Other updates refreshes "when the app starts and once
every 24 hours", but the build only refreshed when 24 hours had passed, so a
relaunch kept a day-old catalog and missed releases `brew upgrade` installed.
Treat a per-launch refresh as unconditional, give a bulk download its own
user-set interval, and show the data's age so staleness is visible. When
comparing with Homebrew, match its default semantics: `brew outdated` skips
self-updating casks, whose Caskroom version is often older than the app.

## 2026-10-17: Reused AppKit windows keep their original Space

Brew Version keeps one Settings `NSWindow` alive across opens. Closing it only
orders it out, so it stays on the desktop Space where it was first shown, and
reopening it from the menu bar on another desktop switched the user back to
that Space. Give a reused utility window `.moveToActiveSpace` so it comes to
the user's current desktop instead; the reused status panel also needs
`.fullScreenAuxiliary` to appear over a full-screen app. Offscreen and single-desktop acceptance
cannot reveal this; test the window's collection behavior, and check native
acceptance with at least two desktops.

## 2026-10-17: Check the native window's viewport after rapid content resizes

A correct SwiftUI measurement and NSScrollView.documentVisibleRect can still
hide a header. In the live Brew Version panel, successive measured resizes ran
before AppKit updated contentLayoutRect; its later resize applied an old delta
to an already-sized root. A 534-point window contained a 609-point root and
scroll view, hiding the first 75 points. Offscreen warning-growth tests passed
because the scroll view reported its own oversized viewport. Compare the root,
scroll view and hosted visible region with the actual window too. Read passive
frames without forcing layout, retain the observed boundary order as a failing
regression, and verify the same content transitions in the live panel. Repairing
the root in windowDidResize passed a boundary replay but failed live because a
later framework write could still undo it. Trace synchronous setters as well as
notifications before deciding which layer owns viewport sizing.

The synchronous setter stack showed the layout engine applying a translated
autoresizing constraint's stale root/parent height offset after the resize
delegate returned. Making the root follow the window's public content layout
guide and pinning the scroll view to that root removes the second sizing owner.
Removing an unused fitting-size read alone did not resolve the live defect.

## 2026-10-17: macOS 27 status items are hosted out of process

MenuBarAgent draws status items and forwards their clicks; the app owns no
status-bar window. Forwarded presses have event number 0 and unreliable
press/release timing, and pressing the icon takes focus from the app before the
expanded-interface session's begin arrives. Any second owner of the open/close
decision races that session: a transient popover's own dismissal, a button
action, a popover anchored to the button (which starts a session by itself),
or dismissing on resign key/active while the pointer is on the icon. Let the
session open a plain panel; hide synchronously, then cancel.

The session does not close on a second press of its own item: that press
reaches neither the app nor the session. A global mouse monitor does see it.
Close only for a press that went down after the session began and went down
and up on the item; the opening press precedes its begin, and NSEvent
timestamps share `ProcessInfo.systemUptime`'s clock. The item's own window can
be taller than the menu bar, so test placement by its center, not its edges.
Check window ownership (`CGWindowListCopyWindowInfo`) and log what actually
arrives (a local event monitor plus focus notifications) before trusting an
in-process event model, and regress the recorded order, not an idealized one.

## 2026-10-17: Verify status-item lifecycle ownership at the real boundary

Refusing transient popover dismissal over a status button assumes its later
action will arrive. AppKit can consume the gesture instead, leaving repeated
clicks unable to close the interface. Removing that veto does not by itself
resolve late actions or a fresh opening request during animated dismissal:
isShown can remain true until close completion. Regress those callback orders
through the real controller. Apple's macOS 27 expanded-interface lifecycle
offers system tracking ownership, but its integration still requires actual
input verification; an initial ten-click pass followed by failures is not
acceptance. Helper toggle tests cannot establish native event delivery.

## 2026-10-17: Keep diagnostic notification recovery independent

A test notification must not clear or replace a failed package notification.
Retain recovery by notice kind and guard asynchronous completions with request
identity, rather than restoring a shared-state snapshot after an await. Test
success, denial, posting failure and overlapping completion in both directions.
Keep Retry visible for pending notices even after authorization recovers.

## 2026-10-30: Retain the current rolling notification payload

A failed package alert must retain list membership independently of its retry
slot. While authorization is suspended, the list can shrink without posting a
new banner; read the current payload after the authorization and request-token
checks so retry cannot restore stale entries. Preserve the initial sound until
a package post succeeds. Test the suspended retry with a nonempty shorter list.
Publish membership changes before waiting for a delivery to finish, and
serialize retries with normal package posts. An in-flight post can complete
after removal, so remove again after it completes; track sound by alert episode
so an older successful post cannot consume a new episode's sound.

## 2026-10-17: Observe native event paths without forcing layout

App reopen and accessibility press do not reproduce a physical status-button
gesture. Correlate actual actions and close callbacks before attributing a fix.
A diagnostic fittingSize read can force layout and conceal the defect under
investigation; passive logs should inspect already-loaded bounds and frames.
Keep synthetic diagnostic labels visibly distinct, including when a menu bar
manager hides them.

## 2026-10-17: Verify deployment targets in generated binaries

Changing the main package and plist leaves independently generated harness and
snapshot packages behind. Inspect actual Mach-O minimum versions and bundle
metadata for every maintained product, and regress installer rejection before
activation when the supported-runtime contract changes.

## 2026-10-17: Scope private-log permissions to the logs

A process-wide umask 077 can change synthetic source fixture modes and create
real source/index mismatches in installer tests. Keep the evidence parent private
and logs mode 0600 while retaining the test commands' normal fixture umask.
Diagnose and rerun the complete failed category without weakening mode checks.

## 2026-10-17: Measure complete inline warnings before allocating list height

A Label can truncate recovery guidance to one line in a narrow native popover
while wrapping correctly in a grouped Form. Allow vertical text sizing and keep
the full message available. Measure the warning stack's actual height when
budgeting the package viewport instead of assuming a fixed warning allowance.
Regress the maintained host with long copy, positive list height and a reachable
footer, then inspect the actual warning and both rendered appearances.

## 2026-10-17: Preserve localized error sentence boundaries

Localized descriptions may already end in punctuation or whitespace. Blindly
appending a period creates double punctuation or punctuation on another line.
Normalize that shared authorization/posting message boundary while retaining the
description and recovery instruction. Exercise real thrown errors with and
without terminal punctuation rather than sanitizing only a screenshot fixture.

## 2026-10-17: Choose copied package commands from installed state

An amber watch can represent a new release of an uninstalled package. Copy
install for that case and upgrade only for an installed package, retaining
--cask for casks. Regress both kinds and both installation states, and verify the
actual clipboard action rather than relabeling an unchanged upgrade command.

## 2026-10-17: Preserve Close Window when owning native application menus

An AppKit lifecycle must install the standard Command-W responder-chain action
as well as Quit and Edit commands. Keep its target nil so the current window
handles performClose:, and verify actual Settings close/reopen separately from
menu item construction.

## 2026-10-17: Publish popover host geometry, not only view fitting size

A content-hugging SwiftUI view can measure correctly while its actual
NSHostingController still publishes preferredContentSize zero. Opt the maintained
popover host into preferred-content-size updates. Regress that same factory
through fresh hosts and dark/light changes, including long content and a positive
scroll viewport. Inspect the live popover too; a separately sized offscreen view
does not establish the AppKit presentation contract.

## 2026-10-17: Give an AppKit-owned grouped Form a real content area

A flexible grouped Form inside NSWindow(contentViewController:) can collapse to
zero height while accessibility still exposes every control. A footer alone may
determine the initial window size. Give the owned window explicit content and
minimum dimensions and prevent hosting from shrinking that contract. Test the
actual window controller and form viewport, then open it natively; a renderer
which supplies a generous initial frame can mask this bug.

## 2026-10-17: Coalesce superseded filesystem captures instead of restarting them

Two overlapping callers that each restart after a generation mismatch can keep
invalidating each other. Retain the shared capture for the overlapping group,
adopt its result or one replacement for new metadata, and resolve further missing
names with targeted reads. Count actual full scans for two and three controlled
callers, including different cask metadata; a stale-publication guard alone does
not bound work.

## 2026-10-17: Reconcile newer observations after the final suspension

Rejecting an older targeted read's dictionary publication is insufficient if its
caller still returns and persists the stale local result. Reconcile matching
observations after every remaining await, including detached derivation work,
then publish and evaluate without suspension. Regress the saved installed version,
amber count and notice output under the exact delayed-read ordering.

## 2026-10-17: Keep search installation reads targeted

Search and Watch need installation information for their result names, not a full
Cellar/Caskroom inventory and Other updates derivation. Preserve the concrete
reader's named lookup through the protocol boundary, resolve exact listing
metadata away from the main actor and count actual receipt admissions. Retain
full inventory work for operations that require it.

## 2026-10-17: Separate validated network data from cache persistence

After both catalog lists validate, publish the slim pair and conditional ETags
in memory even when writing the cache fails. Report that distinct failure without
converting the successful fetch into an unsuccessful request. Retain the warning
through later transport failures until persistence succeeds, so reconnect and
interval handling do not repeatedly download the complete catalog.

## 2026-10-17: Reject suspiciously shrunken successful catalog responses

Nonempty is not enough to admit a refreshed bulk list. Compare usable item counts
with the previous list and reject a drop below half, preserving both indexes,
on-disk bytes and ETags atomically. Test each list independently and the exact
half boundary so protection does not reject a valid boundary case.

## 2026-10-17: Let an explicit check test HTTP despite the path monitor

An unsatisfied NWPathMonitor result does not establish that an HTTP request
cannot work, especially with VPN routing. Gate automatic work with path state,
but let an explicit Check now attempt the request and show its actual result.
Regress both manual bypass and the retained automatic gate.

## 2026-10-17: Retain reconnect retries after partially successful checks

A successful lookup in a batch must not erase unreachable results in other rows.
Track any unreachable result for reconnect and keep the batch success clock
unchanged while those results remain unreachable. Test one successful and one
unreachable row followed by reconnect and require the failed row to recover
while persistence retry floors remain intact.

## 2026-10-17: Stage live bundle displacement during rollback too

A validated backup does not justify deleting the live app in place. Explicit
rollback and activation recovery must rename it into owned staging on the apps
volume, including when the prior release intentionally had no app. Regress inode
identity, forbid recursive deletion of the live path, inject displacement failure
and model separate apps/backup devices. Delete displaced trees during collected
cleanup after publication, preserving all recovery diagnostics.

## 2026-10-17: Reuse the compiled version scanner

Version comparison runs repeatedly while deriving installed updates. Keep the
immutable NSRegularExpression compiled once and use capture alternatives for
token classification instead of compiling a scanner per comparison or a regex
per token. Preserve pinned Homebrew pair parity and external Unicode regressions.

## 2026-10-17: Verify native control styling in rendered and live views

A requested buttonBorderShape can still render as a rounded rectangle with the
current macOS bordered style. Inspect the actual pixels and apply the intended
capsule clipping to the native control when needed. Test content sizing through
the maintained host and inspect every synthetic state in both appearances;
source modifiers alone do not establish visual compliance.

## 2026-10-17: Treat a matching typeahead prefix as a normal search state

When a single valid prefix has catalog suggestions, its exact-token 404 is not
a useful spelling error. Suppress only that row, retain invalid/network and
multi-name failures, and navigate suggestions and results through one selection
model. Preserve an explicit cask/formula choice through request changes and
pending Return rather than resetting to the first suggestion.

## 2026-10-17: Reject legacy cache formats before reading their payloads

Ignoring a decoded legacy envelope still allocates and scans its large base64
payload, and freed allocator pages may remain in the process footprint. Put a
fixed marker at the start of the valid JSON cache and check it with bounded I/O
on the same descriptor before reading or decoding the remainder. Regress actual
bytes read and full-read calls for small and large invented legacy envelopes;
`cached() == nil` alone already passed with the allocation bug. An unmarked slim
cache also refetches once. Preserve atomic pair replacement and typed 304 reuse,
then measure the real legacy-present cold launch separately from tests.

## 2026-10-17: Present the scheduler's retry deadline rather than its success clock

The last successful check alone cannot predict the next automatic request:
unreachable attempts and failed saves impose separate interval floors. Extract
the existing watch gate deadline and use it for both scheduling and display.
Preview reconnect using that same policy: transport backoff can be bypassed,
failed-save backoff cannot. Regress first failures as well as failures following
success with an injected clock; never adjust retries to fit incorrect UI text.

## 2026-10-17: Make watched rows individually accessible through shared selection

An accessible section's merged text is not an individually selectable row.
Contain each row in a named accessibility group, retain its child actions,
expose selected state and route its default action through the same selection
and fresh native focus request as a mouse click. Native responder tests cover
focus renewal, Delete/Undo and search safety; an offscreen SwiftUI host may not
materialize the live accessibility tree, so verify that tree and its actions
with actual assistive input separately.

## 2026-10-17: Give hosted watching scroll views a positive intrinsic viewport

A ScrollView with only maxHeight can collapse to zero in an AppKit-hosted
popover even while accessibility still lists its rows. Use an explicit bounded
watching viewport, keeping the footer outside it. Regress the complete maintained
popover with saved watches, Other updates off and a custom interval under fresh
hosting/reopen, inspecting the actual native scroll frame rather than only rows.

## 2026-10-17: Apply appearance at the popover presentation boundary

Changing NSApplication.appearance does not necessarily update a popover that
inherits the status button's appearance. Apply a requested appearance to the
popover, its hosted content and current window, and retain it for Settings windows
created later. Test effective native appearance, then verify the real harness
buttons visibly change both palettes; a pressed button alone establishes no effect.

## 2026-10-17: Native focus appearance does not prove Delete command routing

A SwiftUI row can show an editing focus ring while its onKeyPress handler never
receives Backspace or forward Delete in an AppKit-hosted popover. Give the clicked
row an explicit native responder for both hardware keys and deleteBackward:/
deleteForward:. Keep the handler row-local so a search text editor remains its
own responder, and avoid replaying old row clicks after a view rebuild. Exercise
native key events and responder switching against persisted removal/Undo, then
repeat the actual click/key gesture; offscreen routing alone is insufficient.

## 2026-10-17: Preserve Undo and Redo when replacing app command menus

Owning an AppKit lifecycle also means preserving standard editing commands.
Install responder-chain undo: and redo: with Command-Z and Shift-Command-Z,
leaving their targets nil so the focused text editor supplies its undo manager.
Regress selectors, modifier masks and responder routing, not just menu titles.

## 2026-10-17: Bound synchronization waits in controlled concurrency tests

A yield loop waiting for a test gate can hang the suite when the action under
test never reaches it. Give the condition a monotonic deadline, propagate a
timeout failure and release pending continuations on test exit. Test the
missing-signal timeout path without dropping the original behavior assertions.

## 2026-10-17: Own a menu bar app's Settings window explicitly

A SettingsLink inside an AppKit-hosted popover depends on SwiftUI scene context.
Own and retain an NSWindow hosting the maintained Settings view; activate the
application and bring that same window forward on every open. A prototype must
use this exact path rather than a separate demonstration scene. Offscreen reuse
tests do not establish actual window activation or native input acceptance.

## 2026-10-17: Separate status-button toggles from transient dismissal

A transient popover can dismiss on status-button mouse-down before its mouse-up
action, making a toggle reopen it. Veto automatic dismissal for that button's
native event and let its explicit close own the action. Preserve transient menu
and child-sheet semantics; verify their real timing with native input.

## 2026-10-17: Give click-selected watch rows editing focus

Default keyboard navigation does not guarantee focus for plain focusable rows.
Editing focus is necessary but, as the later native-routing lesson above records,
does not establish key delivery in an AppKit-hosted popover. Route Delete from
the focused watch row only; a search field's Delete must keep editing its text.
Renew search focus on every popover open. Action tests cannot establish the
system's native focus behavior.

## 2026-10-17: Native menu checks need selection state

A checkmark image in a menu label is not a native selected menu item. Use a
Picker with tagged intervals and include a custom current value among its
options. Retain invalid custom input and keep its sheet open if saving fails.

## 2026-10-17: Queue Return against current search intent

Debouncing alone leaves Return able to watch retained rows from an old query.
Retain results through both debounce and transport, share the active request,
await its completion on Return and reject submissions after text or kind changes.
Controlled waits must prove rapid typing suppresses intermediate requests and
that pending Return watches only the current result.

## 2026-10-17: Observe notification failures at their system boundary

An unread lastError property hides permission denial and posting failures.
Observe separate authorization and delivery errors in both app views; retain a
failed notice for explicit retry after recovery. Inject the OS API boundary for
denial, thrown errors and successful retry without a production simulation mode.

## 2026-10-17: Revalidate homepage schemes when executing the action

An external homepage URL is not automatically safe to open as a web page.
Admit only absolute http/https URLs with a host, both when presenting the action
and immediately before invoking the workspace. Exercise the actual action with
synthetic file, script, mail, relative and web URLs.

## 2026-10-17: Render installed-source qualifications consistently

A self-updating cask's Caskroom fallback qualifies the installed version even
after Watch moves it between sections. Reuse one source-note helper across
watched, search and Other rows so changing presentation cannot hide that fact.

## 2026-10-17: Refresh login approval when Settings becomes key

Login Item approval can change in System Settings while the app stays open.
Refresh the service on key-window callbacks and offer the system panel when
approval is required. Record actual registration errors; a signing assumption
does not establish that registration failed or succeeded.

## 2026-10-17: Describe watched updates in the status item's accessibility

Changing a mug image alone leaves assistive clients without its update state.
Derive its symbol and accessibility description from the same observed amber
count, and regress actual observation across skip/removal state changes.

## 2026-10-17: Wire scheduling gates through the application boundary

A gated controller cannot prevent an ungated app startup or a path adapter that
drops offline events. Start unknown/offline, await every network update and let
the controller alone schedule reconnect work. Exercise real controller retries
through the event source, including initial offline, wake, periodic and reconnect.

## 2026-10-17: Display persistence advice for its explicit failure kind

Successful quarantine recovery and rejected saves need different advice. Render
the failed-action save hint only for the controller's saveFailure state, while
preserving the blocked-load Retry action and original diagnostic text.

## 2026-10-17: Cleanup must preserve the failure that required recovery

A throwing finally block replaces an earlier activation or restoration error;
force removal suppresses missing paths, not I/O or permission errors. Collect
each cleanup failure and attempt every remaining owned directory before
reporting the primary error, all cleanup paths and the durable backup path.
Apply the same rule inside atomic file publication, before the installer can
observe the error. Cleanup-only failure after completed activation must retain
the selected release, report that outcome explicitly and exit nonzero; it must
not trigger a second rollback. Inject compound failures for deploy and rollback,
compare retained backups and live artifacts, and assert every cleanup attempt.

## 2026-10-17: Keep native activation moves on the destination device

Copying to a backup under HOME can cross volumes safely; renaming the live app
there cannot. Move the displaced bundle into the staging folder inside the
apps directory. Model devices by path boundaries in regression injection so
same-device renames succeed and only cross-device renames raise EXDEV. Retain
a separate failure test for a genuinely failed same-device activation move.

## 2026-10-17: Validate copied backup payloads before live mutation

Hashing the source does not validate its copy. Re-read command, receipt,
metadata and the complete app tree against their captured identities before
activation. Corrupt each payload independently and assert the live bytes,
modes and inodes remain untouched; write-failure tests alone miss silent damage.

## 2026-10-17: Preserve activation and restoration error evidence

Publish the durable recovery path before activation begins. If recovery fails,
report the original activation error, the recovery error and that same retained
backup path. Regress explicit rollback failure too: a second restore must not
replace the error that explains why the first recovery became necessary.

## 2026-10-17: Tie relaunch guidance to an actual bundle replacement

A running app needs relaunch guidance after deployment or explicit rollback
replaces its bundle. An already-current deployment needs no notice. Keep the
process-detection override conspicuously test-only and run signed synthetic
lifecycle cases for all three paths.

## 2026-10-17: Admit every required native source input at the fleet boundary

Installer-required golden help is also fleet-required source inventory. Remove
it from a committed synthetic index to exercise the missing-required case;
merely deleting a tracked working file only exercises generic source drift.
Require the source-inventory diagnostic before the child installer is invoked.

## 2026-10-17: Assemble releases without stale files or executable overwrites

Clear the bounded prior app bundle before assembly, then copy executables to
unique temporary siblings and rename them into place. A valid signature can
seal stale resources, and signing after overwriting can conceal prior inode
damage. Hold file descriptors to signed invented old executables across a real
release build, checking both their bytes and new path identities. Run this
integration category after Swift tests, outside SwiftPM's test process.

## 2026-10-17: Put acceptance homes in private OS temporary space

Required synthetic acceptance builds should use plain mktemp -d rather than
adding homes to the owner's HOME. Keep their packages, invented inventory and
runtime evidence inside that private directory and print the path for bounded
cleanup. Building/signing the harness establishes no native interaction result.

## 2026-10-17: Preserve the metadata that gave a snapshot its meaning

An installed cask snapshot depends on the caller's auto-updates flag and app
artifact names. A later scan without a pending add's metadata can legitimately
read Caskroom while the caller requires the newer app-bundle version. Do not
substitute a shared snapshot merely because it is newer. Consume the caller's
accepted capture without another suspension; a small lock-protected immediate
cache copy removes an unnecessary final actor hop. Keep cache get/store
actor-bound and every mutable dictionary access under the private lock. Regress
both add and check with real synthetic Caskroom/app-bundle fixtures and a held
cache executor, asserting saved source/version, amber state and notices.

## 2026-10-17: Reject superseded snapshots at every consumer boundary

Protecting publication of a derived update list is insufficient if a rejected
filesystem snapshot is still returned to watch evaluation. Retry superseded
captures and retain the accepted snapshot; consume it only after the caller's
final await before persistence or notification. Regress a blocked check while
a later search observes an installation change, then assert saved installed
version, amber state and delivered notices, not only the Other updates list.

## 2026-10-17: Capture mutable cache state after other asynchronous work

A cache actor's identity can stay unchanged while another operation adds an
entry. Taking its snapshot before a suspended installation scan lets an older
check overwrite a newer add's saved ETag. Read the cache after the scan, retain
the cache-identity guard, and merge without another await. A controlled blocked
scan with a concurrent add must preserve both watches and both conditional
entries in actual saved state.

## 2026-10-17: Keep catalog caches proportional to the fields the app uses

Persist decoded Listing indexes and ETags, not raw JSON encoded as base64.
Typed decoding can discard large bottle/dependency metadata without constructing
a full Foundation object graph. Hold the indexes in an actor, read disk once,
and reuse decoded listings on 304. Regress cache size with large invented ignored
metadata and corrupt disk after loading to prove memory-backed revalidation.

## 2026-10-17: An empty bulk success must not erase a good catalog

HTTP 200 does not establish a usable catalog. Reject lists with zero usable
items and replace formula/cask indexes only after both validate. Preserve the
prior pair and ETags after partial, malformed, empty or failed refreshes.
Synthetic successful fixtures must contain usable items too.

## 2026-10-17: Scope a visibility setting to its own content

Other updates and prefix suggestions share the catalog but have different
visibility contracts. Turning off installed updates must leave suggestions
available during hydration, reload and refresh. Gate the installed section,
not the shared catalog resource.

## 2026-10-17: Capture installed state once away from the main actor

Inventory admission and installed-version lookup must share a single receipt
pass. Capture an installation snapshot off-main, reuse it for watched checks
and Other updates, and generation-check publication after suspension. A blocked
scan regression should prove UI state can change while it waits; a receipt-read
counter catches accidental inventory-plus-lookup passes.

## 2026-10-17: Avoid persistence and scans for unchanged state

Compare a normalized candidate with committed state before saving. Closing an
already acknowledged popover or selecting the current setting must not write.
Filter a captured installation snapshot after watch or visibility changes;
interval, skip and close commits do not require fresh filesystem inventory.

## 2026-10-17: Track successful checks separately from transport attempts

An entirely unreachable check must retain its previous successful timestamp.
Keep a separate attempt clock to bound retries, and let reconnect bypass that
transport floor even if a recent manual failure followed a successful check.
Start automatic scheduling behind a network gate until the path monitor answers.

## 2026-10-17: Failed saves need their own automatic retry floor

A successful request followed by rejected persistence must not repeat each
minute. Bound automatic requests by the configured interval from the failed
save, including across reconnects, while permitting an immediate manual retry.
Apply the same rule to catalog timestamps; injected clocks and request counts
prove cadence without sleeping or changing successful-check timestamps.

## 2026-10-17: Prune conditional caches at watch lifecycle boundaries

Persist only entries whose names are watched. Removal must evict the in-memory
conditional cache too, and an in-flight old cache snapshot must not be merged
after that boundary changes, even when Undo restores the same name. Regress
both saved bytes and outgoing ETags; search-only entries must never accumulate
in saved watch state.

## 2026-10-17: Expose persistence recovery kinds separately from message text

Setting aside corrupt state successfully is a recovery warning, not a failed
save. Expose explicit recovery-warning, blocked-load and failed-save states so
UI retry hints follow the actual recovery action without parsing error prose.

## 2026-10-17: Admit legacy casks only for absent receipts

Caskroom version directories can predate install receipts. Admit those legacy
casks in both lookup and inventory, preserving app-bundle lookup and the
Caskroom fallback for self-updating packages. Absence is an explicit exception:
existing malformed, unreadable, unknown or nonofficial receipts still exclude
the installation, as do version-directory symlinks. Keep formula receipts
mandatory and regress both admission paths with synthetic filesystem fixtures.

## 2026-10-17: Never assume Unicode scanner and classifier agree

Foundation's case-insensitive scanner can match Kelvin sign and long s through
ASCII letter patterns while its anchored classifier finds no match. External
folder and bundle versions must not trap on that disagreement. Fall back to a
string token instead of force-unwrapping the classifier, and retain actual
Unicode regressions beside the pinned upstream ASCII comparison matrix.

## 2026-10-17: Compare formula revisions after upstream versions

A formula keg suffix is a package revision, not another upstream version token.
Comparing `1.0_2` directly with `1.0.1` misses the newer upstream release.
Split only the last underscore followed entirely by ASCII digits, default to
revision zero, compare upstream versions first and numeric revisions on a tie.
Reuse this rule for status and highest-keg selection; preserve valid opt links,
cask ordering, deterministic ties and arbitrary-precision revision comparison.

## 2026-10-16: Merge awaited watch results into committed state

A check must apply results to the current committed watch state after its final
await. Capture each watch's generation when starting work and reject results
for removed or restored generations, even when the package name matches again.
Otherwise a late response can change an undone removal or overwrite a newer
skip or interval. A controlled transport regression should hold requests while
mutating all those fields, then inspect both persisted state and notifications.
Persist candidates before publishing state or posting notices; retain the
previous bytes and visible values on failed writes.

## 2026-10-16: Bound and identify asynchronous menu bar searches

Search, watched checks and additions need one shared lookup permit pool; separate
per-operation limits exceed the intended request bound when UI actions overlap.
Identify each query generation and publish only its current result. Derive the
watched flag from committed state at publication and refresh it on successful
watch mutations. Preserve a watched package's known kind during search instead
of falling back to a formula-first lookup. Controlled transports can hold one
query while a newer query or a watch mutation commits, without live inventory.

An undo action must consume its saved entry only after the restore commits.
Cancel its normal expiry after a failed restore so the user can retry; do not
replace that pending recovery with another removal. Route a same-name Watch
through restoration too, or a fresh add can strand the recovery as a duplicate
and lose its saved acknowledgements. Test the actual app action against the
real controller and failing atomic-replace seam, then retry successfully.

## 2026-10-16: Retain validated recovery bytes until activation finishes

A move-based native app activation can fail before the old bundle leaves its
live path. The original fix retained a backup copy but did not verify its copied
bytes before activation; the later backup-validation fix closes that gap.
Do not delete the retained backup before that move succeeds: recovery then
loses the app it needs to restore. Validate and keep the copy through all
command, app and receipt transitions, and
inject failures both before moving the old app and after publishing each new
artifact. Compare independent byte/type/full-mode snapshots after restoration;
receipt hashes alone cannot prove that recovery preserved the original tree.

## 2026-10-16: Preserve explicit search intent and bound native result content

A catalog suggestion includes both name and kind. Preserve both in transient
search intent, and include kind in the text task's identity: selecting a cask
whose name already fills the field must requery even when the text is unchanged.
Editing clears that explicit choice; existing name-only watches retain their
known kind. Test the app's suggestion action through lookup and Watch against
colliding synthetic formula/cask responses, plus cancellation and late results.

Bound suggestions and multi-token results inside their own scroll viewport,
with the input and footer outside it. Follow keyboard selection with scrollTo.
For offscreen SwiftUI layout tests, separate presentation from its asynchronous
query task: creating a host for the whole section can restart the task, clear
results and accidentally measure empty content. Test the maintained presentation
component with populated results and verify that removing the bound makes the
test fail on real geometry. This does not establish native keyboard acceptance.

Native executable diagnostics require successful exit, exact stdout and empty
stderr. A signed executable can satisfy stdout while emitting an unexpected
warning. Regress each flag at both build and installed activation boundaries,
and compare the prior artifacts and retained recovery snapshots after failure.

## 2026-10-16: Keep catalog validation and persisted freshness separate

Bulk catalog lists form one usable snapshot. Validate both before replacing
the cache; a successful first list cannot replace half of a good pair when the
second fails. Conditional responses require validated prior bytes, and stale
fallback content must not advance the successful-fetch clock. Track attempts
separately to bound offline retries. Independent catalog and watched checks
must merge into current committed state after their final await, with tests
forcing both completion orders and state-save failures.

## 2026-10-16: Distinguish installation links from real version directories

A cask can have a genuine `latest` version directory. Exclude version symlinks
by filesystem type, not by a reserved-looking basename; otherwise an admitted
installation disappears from point lookup and inventory before app-bundle
lookup or unversioned status evaluation. Cover both real `latest` directories
and `latest` symlinks with synthetic installation fixtures.

## 2026-10-16: Preserve upstream token semantics in version comparisons

Homebrew's version ordering is asymmetric when zero tokens meet suffixes;
do not assume reversing operands negates the result. Its post-release pattern
also starts with a wildcard: `1post2` uses the first numeric run as the token
revision. Generate both ordered expectations from pinned upstream methods,
including wildcard and zero positions, before porting. Brew Version retains
these synthetic parity cases in `VersionOrderTests.homebrewParity`.

## 2026-10-16: Preserve confirmed popup state when status checks fail

A failed or rejected worker status reply does not establish that capture is
off or empty. Keep confirmed capture values explicitly stale, show unknown
values before the first successful reply, and disable affected actions until
recovery. Do not pass an empty synthetic payload through the success renderer.
Regress both worker messaging failures and rejected or incomplete replies,
including successful recovery without capture mutations.

An outside focus outline can disappear behind a rounded fold's overflow clip.
Use an inset outline and check collapsed summaries and full-width row buttons
in light and dark Chromium. Scope error notice colors to each skin so a later
skin-specific neutral selector cannot override the error tone.

## 2026-10-16: Verify extension popup typography and empty-state layout in Chromium

Chromium's extension stylesheet can give `body` a relative font size even when
the root declares the intended size. Explicitly inherit the root font on the
popup body and assert its computed size in browser tests. Empty states inside
structured lists also need selectors strong enough to override item layouts;
otherwise a plain message can be squeezed into a grid column. Keep light and
dark screenshots and computed-style regressions beside the popup behavior tests.

## 2026-10-15: Preserve calculator cache precedence during webserver updates

The live Nginx configuration had a calculator-specific `no-store` rule absent
from source. Keep that rule in the maintained configuration: its `^~` prefix
prevents the common asset regex from replacing calculator JavaScript's cache
policy. Preserve static-first delivery and the shared dynamic fallback inside
the prefix. Verify real response headers and routes with an isolated Nginx
fixture, including missing calculator assets and ordinary asset 404s. Docker
Desktop bind-mount deletions can propagate asynchronously; observe deletion
inside the disposable container before testing the missing-landing branch.

## 2026-10-15: Test temporal conversion policy across every CLI target

TOML and YAML parsers can produce native Python dates and datetimes; TOML also
produces native times. JSON and XML writers need explicit ISO serialization,
while YAML should normalize only times so its native date/datetime types survive.
Keep TOML's native writer and preserve ordinary strings, including YAML's quoted
time values. A shared temporal hook must reject unknown objects rather than
silently stringifying them.

The converter's [test_temporal_cli_matrix](../data_format_converter/tests/test_cli.py)
loads each source fixture, exercises every actual supported target, and compares
the complete parsed mapping and value types after unwrapping XML's synthetic
root. Retain nested direct-writer regressions and
[test_yaml_temporal_policy](../data_format_converter/tests/test_yaml_conv.py) /
[test_toml_temporal_policy](../data_format_converter/tests/test_toml_conv.py):
a substring check cannot detect type loss, dropped fields, or lost marker values.

Measure temporal types separately during dependency upgrades. The TOON baseline
already preserved dates and datetimes, but converted times and binary values to
null and rejected comment-only input. Its released writer now preserves times,
rejects binary through the CLI error path, and accepts comment-only input; keep
those regressions rather than claiming all temporal behavior changed together.

## 2026-10-15: Retain reference reconstruction guards in optimized variants

Reversible Skew's optimized transform accepted smaller periodic BWT payloads
that did not reconstruct the original bytes. Preserve the `rs.py:transform`
reconstruction guard when accelerating MTF/RLE operations, falling back to raw
blocks when comparison fails. Random-only tests exercise passthrough and miss
this failure: retain periodic and varied synthetic regressions, require the
varied case to take the transformed path, and cross-decode both implementations.
See [Reversible Skew's guide](../reversible-skew/README.md) for project validation.

## 2026-10-15: Compose inventory coverage and npm audit evidence across views

Manifest inventory failures are independent of declaration rows. Fleet cards and
per-repository summaries must consume persisted analysis errors and missing tools
even for empty results or fully checked rows, while declaration KPIs continue to
count only actual row states. Exercise both cases through the rendered browser.

npm outdated can report installed versions while audit evaluates the virtual
lock tree. Reuse lock-version evidence, require a concrete matching evaluated
version, and match the audit's affected node location before applying a finding.
A same-name nested vulnerable node does not implicate the direct declaration.
Mocks must include real affected-node evidence rather than validating name-only
attribution; retain valid current/outdated evidence when audit versions differ.
Select npm-shrinkwrap before package-lock in the same parser; invalid selected
shrinkwrap evidence must not silently certify a different fallback lock tree.

## 2026-10-15: Attribute package-manager checks to declaring projects and evaluated versions

A manifest path is part of a dependency declaration's identity and also selects
the package-manager working directory. Group checks by the resolved declaring
directory so a monorepo's nested projects cannot inherit root-project tool output.
An npm lock supplies a concrete version, not registry comparison evidence; require
an actual comparison even after successful empty outdated output. Treat audit
errors and required report fields as evidence boundaries, including lock-specific
failures, rather than promoting audit prerequisites to successful coverage.

Findings-only reports cannot prove that an absent declaration was evaluated.
Prefer explicit all-package comparison rows or evaluated module/version evidence,
and retain unchecked reasons where that evidence is unavailable. Current
govulncheck JSON is a versioned message stream: OSV database candidates are not
findings, SBOMs establish evaluated modules, and finding attribution includes the
version regardless of message order. When an audit contains several versions of
one name, preserve the matching version's advisory instead of the last name match.

## 2026-10-15: Preserve dependency declaration identity across manifests

Git Fleet previously deduplicated and stored dependency rows by repository,
manager, and package name, losing repeated declarations in nested manifests.
Include the manifest path in parsing, persistence, stale-row deletion, and
overlap attribution. Normalize Python names before deciding identity; preserve
fallback reference identifiers. Test schema migration against historical DDL,
including SQL NULL sources and normalized-name collisions, and invalidate
legacy health coverage rather than presenting old results as fresh evidence.

## 2026-10-15: Verify extension release identity during deployment

The extension repair was deployed with its previous manifest version, so the
browser still displayed `0.5.0` after a successful reload. Bump the manifest
version for a released extension change and verify it in both the source and
deployed manifest before handing off the browser reload. Matching source bytes
alone does not establish that the displayed release identity was updated.

## 2026-10-15: Redacted diagnostics still need text-only rendering

In `docker/llm_collector/extension`, decoding paths to redact identifiers also
decoded encoded markup. The popup interpolated that sanitized text into
`innerHTML`, creating an actual image and attempting an external request under
the extension CSP. Redaction removes sensitive content; it does not make text
safe for an HTML parser. Render every dynamic diagnostic field, neighboring
count row and identity value with `textContent` and DOM elements. Preserve the
sanitizer's byte limits independently. Keep the list present in renderer tests
and exercise observation, normalization and rendering together; verify the
actual popup in isolated Chromium with resource attempts intercepted.

## 2026-10-15: Treat diagnostic restoration and persistence as recoverable states

In `docker/llm_collector/extension`, waiting only for the enable setting let
completion events miss records whose session read was still pending. Register
listeners synchronously, sanitize bounded staging immediately, and serialize
events and controls after both initialization results settle. A failed read
means storage is unread, not empty: merge bounded staged records after reload,
or intentionally replace the owned key through a successful clear.

Session callback completion does not imply persistence success. Read
`chrome.runtime.lastError` inside each callback, keep failures observable in
status/export, and publish clear success only after the latest empty write.
Use generations so obsolete writes/retries cannot restore cleared content.
Bound count, serialized UTF-8 bytes, individual records and bodies separately;
Chrome's actual memory quota needs its own browser measurement. Evict even an
oversized singleton and remove additional owners of evicted in-flight records.
Preserve live redaction provenance rather than reparsing sanitized JSON prefixes
during every retention pass. Test Unicode, late growth, unread stores, failed
callbacks, deferred clear, and worker stop/wake with a fresh synthetic profile.
Check byte limits again after redaction: repeated short token values can expand
to longer replacement markers, including in standalone restored debug paths.

## 2026-10-15: Commit transport history with prompt accounting

In `docker/llm_collector/extension`, counting each Gemini WebChannel POST counts
transport retries repeatedly. Google's WireV8 encoder identifies messages as
`ofs + reqN`, where `N` is a relative message ID, not an array position; retry
reordering can lower the offset and leave sparse indexes. Join raw byte chunks
before decoding forms so keys, base64 prefixes and UTF-8 sequences remain whole.

Persist salted endpoint/SID hashes and interval history in the delivery owner's
same transaction as queued counts. Include non-prompt IDs, retain the salt and
history across extension and browser lifecycle boundaries, and fail closed at
bounds without eviction. Browser tab IDs and session-storage nonces cannot
establish durable transport identity. Known replays should need no write.
Exercise rejected persistence, mixed retries, lost acknowledgements, and explicit
queued-count clearing with an observation-identity conservation oracle.

## 2026-10-15: Persist immutable delivery identity before sending

In `docker/llm_collector`, serializing pending-count writes did not serialize
submissions. Two overlapping sends reused one sequence with different snapshots;
both replies subtracted counts although the collector accepted only the first.
Persist one immutable batch and keep newer observations in a separate queue.
Publish cloned state only after storage succeeds, and preserve an uncertain
batch across retries, clear actions and worker restarts. Persist a migration
baseline marker so an offline restart cannot submit before reconciliation.

Resetting a reporting period must retain deduplication receipts. Snapshot,
clearing and save need one lock boundary; otherwise a concurrent add can fall
between the snapshot and clear and disappear. Test conservation with observation
identities: accepted and uncertain in-flight sets may overlap after a lost reply,
so adding their counts is an invalid oracle.

Fetch resolving means headers arrived, not that body consumption succeeded.
Classify aborts and stream transport failures during JSON reading as retryable,
while treating malformed JSON as a protocol error. Publish a counted diagnostic
only after the observation commits. Keep rejected-recording diagnostics in the
session buffer and distinguish their errors from transient delivery errors;
an empty or unrelated successful drain cannot restore a rejected observation.

## 2026-10-15: Sanitize every diagnostic representation

In `docker/llm_collector/extension`, a credential-name regex applied to raw JSON
missed names supported by the form/query policy and values that were not strings.
Decoded URL containers, URL-valued headers, debug paths, and restored session
records provided additional ways around otherwise working capture redaction.

Use one sensitive-name classifier after parsing each recognized representation.
Bound structural inspection and decoding, omit uninspectable content, and use
own-property maps for untrusted member names. Treat session restoration as an
admission boundary: sanitize before publishing records and rewrite the safe
representation. Test the complete popup export and console boundary, including
when capture is off, because testing one capture field cannot establish that the
same credential is absent from neighboring diagnostic fields.

Review caught two boundary errors: recognizing one valid Link target does not
validate the remaining header, and reparsing a safe JSON prefix after truncation
loses long prompts. Consume an entire recognized container before publishing
any of it. Preserve live sanitation provenance outside serialized records, so
admission can distinguish a fully inspected prefix from untrusted restored text.

## 2026-10-15: Separate dependency findings from check coverage

An unchanged declaration after a missing or failed tool is not a clean health
result. Track outdated and vulnerability evidence separately, retain bounded
failure reasons, and derive display severity after enrichment. Preserve proven
findings when the other check is incomplete. Do not promote a declared version
constraint to an installed version. Persist missing tools and manifest inventory
even when parsing yields no rows, and keep quick scans from overwriting them.
Run blocking network and package-manager checks in a worker thread so requests
and scan progress remain responsive. Test that responsiveness with a worker
blocked on an event released by the server event loop.

Dependency snapshot persistence also needs explicit failure rollback. A caller
that catches a scan error and commits unrelated progress can otherwise publish
earlier metadata and row writes. Protect metadata, upserts and stale deletion
with a savepoint; roll back the savepoint on failure and preserve the caller's
outer transaction. Regress with real SQLite trigger failures, followed by the
caller's commit, and compare the complete previous snapshot.

Python direct-reference identity needs a distinct path from distribution-name
normalization. Parse URL authority before separating a VCS revision from its
path: an SSH user separator is not a revision, and revisions can contain slashes.
Keep extras and markers as declaration text and reject wildcard pins as concrete
versions. Filtering direct-reference result rows does not exclude their URLs
from an auditor that reads the original mixed manifest; filter the actual audit
input too. Regress the full parse-to-persistence path and inspect synthetic
auditor input, because parser-only tests miss later identity normalization and
whole-manifest external work.

### Git Fleet: declaration sources and discovery inventory

Manifest priority can silently discard independent Python declarations. Discover
pyproject, requirements variants and leading PEP 723 metadata together, and keep
resolved include-file provenance separate from the including file. A file inventory
must record attempted reads, empty files and failures independently of dependency
rows. Adjacent locks supply versions only; ambiguous versions must block checker
entry before any floating resolution can run. PEP 723 extraction needs its greedy
closing-line grammar, not a first-terminator scan or fixed prelude byte cutoff.

An arbitrary requirements include can also look like a discovered script. Parse
explicit manifests and their includes before script candidates, and let an existing
resolved-path inventory record own that file. A harmless metadata probe must never
replace or remove the include's empty, populated or failed record. Regress both
filename orders and assert one actual read, not merely one surviving declaration.

### Git Fleet: evaluate Python declarations and validate audit evidence

An unpinned declaration still has a registry evaluation: retain the highest allowed
usable release as a floating wanted version, without calling it installed or
current. Apply `SpecifierSet.filter` to the candidate set so explicit prerelease
constraints and fallback behavior follow packaging's semantics. Cache successes
and failures by normalized name for one scan, and distinguish connection failures
from HTTP/JSON errors before opening an offline breaker.

Auditing the original manifest can resolve extra dependencies and conflate versions
declared in different projects. Audit exact evaluated pins with dependency resolution
disabled, splitting conflicting versions of one normalized name into separate
batches. Treat process status and JSON as a joint evidence contract: missing entries,
skips, malformed advisories, duplicate names, version mismatches and status/advisory
contradictions cannot establish clean coverage. Regress matching across manifests
and limit failures to the affected batch. Synthetic auditor fixtures must use real
exit semantics and the requested versions so they cannot conceal these errors.

### Git Fleet: findings and coverage are independent report dimensions

A vulnerability or update headline does not prove both health checks ran. Count
unchecked declarations from the independent check states in SQL and the UI, and
allow a finding to appear in both Attention Required and Not Checked. Count
manifest reads from discovery inventory so empty or failed files survive reports.
Refresh metadata after a scan before publishing the report; stale parent props can
otherwise pair fresh rows with old missing-tool and inventory information. Browser
regressions should inspect real downloaded contents and use one shared synthetic
fixture to compute API, UI and report expectations.

A declaration timestamp is not a scan timestamp. An inventory-only scan can have
no declaration timestamps; label that absence explicitly instead of claiming the
repository was not scanned. Never substitute a quick-scan time for dependency
evaluation history.

### 2026-11-11: Keep Brew Version retry evidence and deadlines aligned

The watch footer and automatic eligibility must use the same deadline, including
failed-save backoff while an announcement is pending; reconnect must respect it
too. Keep the independent catalog cadence separate. Diagnostic regressions must
assert recorded values and units, not merely event names, and confirmation events
must follow a successful state save.

### Brew Version: validate tap cache identity before conditional requests

Two locally named taps can point to the same GitHub repository and file. A URL-keyed
listing cache therefore does not prove that its parsed package name and kind match
the request. Reuse its ETag and accept a 304 only when both match; otherwise request
the file unconditionally and treat a 304 as lacking a usable cache entry. Keep
regressions for shared-remote aliases and mismatched cached kinds so conditional
requests cannot return another package's identity or parsed metadata.

## 2026-10-18: Share tap discovery with the existing installation capture group

Tap Other updates needs an installation snapshot before fetching its listings,
then the fetched metadata before deriving its rows. A separate discovery scan
bypasses the controller's capture coalescing: an overlapping watched check can
then cause three full scans. Keep discovery, tap HTTP awaits and final combined
catalog derivation in one existing capture group, allowing one metadata
replacement and retaining the targeted-read revision reconciliation. Regress
actual snapshot counts under a held refresh/check overlap, alongside kind-specific
retained tap listings after later checks.

## 2026-10-18: Port Homebrew version detection against a generated corpus

Generate synthetic URL/tag expectations with the pinned Homebrew implementation
before porting parser order, stem handling and regex behavior. Keep the source
commit in the port and corpus, cover every parser family and negative cases,
and compare the generated expectations in Swift tests. Handpicked happy paths
miss suffix removal and regex-anchor differences between Ruby and Foundation.

## 2026-10-18: Resolve directory links without changing tap remote paths

Foundation directory enumeration needs a resolved URL for a selected Formula
directory symlink. Rebuild each enumerated child under the lexical URL so the
GitHub request keeps its repository-relative Formula path. Preserve Git config
casing semantics separately: section/key names are case-insensitive, while the
remote subsection name `origin` is case-sensitive. Regress links and mixed-case
config independently instead of lowercasing the whole config before parsing.

## 2026-10-18: Preserve parsed package identity through suggestion actions

Homebrew tap-prefix normalization is not idempotent for repeated reserved
prefixes. A suggestion already owns a canonical PackageName; converting it to
text and parsing it again can select a different tap. Preserve the object in
the transient request and route explicit selections through the same controller
search pipeline using a valid token. Copy-version actions must resolve that
same selected name and kind, rather than consulting only the official catalog.
Keep debounce, cancellation and request-generation checks around both actions.

## 2026-10-18: Keep explicit source intent through the final Watch lookup

Brew Version displayed a chosen official result but used bare-name fallback
again when Watch performed its second HTTP lookup. An official 404 then saved
a tap watch. Share the search/add pipelines with an exact-source mode for
suggestions, results and Other updates actions; reserve bare fallback for raw
input. Match suggestions by name and kind, including when another kind is
already watched. Preserve Undo restoration before issuing a fresh add.

## 2026-10-18: Receipt provenance comes from the writer, not tap directory aliases

At Homebrew commit 3073d6a8c34f71da054b000cfdbb62594a07c969,
`Library/Homebrew/tab.rb`'s `AbstractTab.create` writes
`formula_or_cask.tap&.name`; `cask/tab.rb` uses `cask.tap&.name` too.
`tap.rb` constructs `@name` from parsed user/repository and lowercases it.
Thus receipt `source.tap` is canonical already. Typed prefix normalization can
strip another reserved prefix and assign a removed source to another tap.
Validate canonical segments and compose package identities without aliases;
fold case only, and admit official provenance only for canonical core/cask.
Synthetic receipt fixtures must follow that writer format. Capture tapped
membership once per snapshot/point read, rather than rescanning for each receipt.

## 2026-10-22: Preserve stored uptime precision in dossier cells

JavaScript's default `Number.toLocaleString()` rounds to three fractional
digits: a synthetic stored uptime of 99.9999 became a misleading 100%.
Render uptime with the same numeric string interpolation as Hosts details;
reserve locale grouping for integer token capacities. Keep browser coverage
for high precision alongside real zero and missing samples in both themes
and at narrow widths. Validate these cases with isolated synthetic runtime
data rather than reading real provider captures.

## 2026-10-22: Keep compact comparison descriptions inside their scroll container

Model Sentinel's absolutely positioned accessible spread descriptions escaped
an unpositioned table scroller and enlarged the document on narrow screens.
Anchor them to the spread component even when they are visually clipped, and
exercise document width with both no compared hosts and the full selection.
Compact rows also need a larger isolated fixture to exercise real vertical
scrolling and pagination; endpoint count alone does not create additional list
rows. Retain a focusable results heading when filters remove every row so a
copied endpoint drawer can still close to a useful focus target.

A derived pagination fallback is not a state reset: showing 50 rows when the
comparison key differs still leaves the previous key's expanded limit stored.
Returning with Back can revive all 112 rows. Replace the retained paging key
and limit when comparison inputs change, and regress expand, change ranking,
then Back to the original ranking; both transitions must show only 50 rows.

## 2026-10-23: Separate compact endpoint cells from complete endpoint facts

Model Sentinel's compact Hosts precision cells share data with expandable
endpoint facts. Keep quantization-only cell rendering separate from the full
precision formatter so published bit widths remain available in the details.
Likewise, determine host absence from observed endpoints rather than the
qualifying best group: Show excluded can admit an observed host whose endpoints
all fail filters. Preserve that distinction without broadening row admission.
Shorter cell copy can also remove expected horizontal overflow; retain column
space and the existing sticky-corner scroll regression when tightening text.

## 2026-10-22: Scope browser URL normalization checks to the fragment

A browser assertion searching the complete URL for an invalid numeric value
can match the synthetic server's randomly assigned port instead of URL state.
Model Sentinel's invalid uptime value `101` matched port `51019` even after
the hash was correctly normalized. Anchor invalid-state patterns after `#`
so they still catch every malformed saved value without depending on the
ephemeral origin.

## 2026-10-22: Keep saved interaction state valid across empty results and history

Model Sentinel's active sort survived filtering while its summary and Clear sort
disappeared with the results table. Keep controls for retained state in the
persistent toolbar. A connected drawer origin can still belong to another list
after Back navigation; verify its list identity before restoring focus, then
fall back to the closing list's row or the results heading. Search option
navigation must ignore an empty suggestion list, and its active descendant
must name an existing option. Regress these transitions in the real browser,
including recovery from empty suggestions to a selectable result.

## 2026-10-28: A prefix-only temp check misses the toolchain's own leftovers

Brew Version's and Anker's `check_tmpdir.sh` watched only their own `brew-version-` and `prime-`
names, so `make test` passed while each run left dozens of entries in temporary space: empty
`TemporaryDirectory.*` folders and SwiftPM lock files named after the package path
(`..._brew_version_.build.lock`, `..._brew-version-acceptance.XXXXXX_package_.build.lock`), plus
one marker-only `TemporaryDirectory.*` per compile in `getconf DARWIN_USER_TEMP_DIR`, which
ignores `TMPDIR`. A leak check has to own where the toolchain writes, not just match names: run
the suite with `TMPDIR` in a private directory the check removes, point every nested builder's
SwiftPM at a directory inside its own home, and sweep only the run's new marker-only Darwin
folders. `tools/check_no_temp_leaks.sh` does all three for both projects; Telltale's copy predates
it. Moving the suite's `TMPDIR` into the checkout broke two hidden assumptions: the snapshot
renderers require their home under `FileManager.default.temporaryDirectory`, which stays the
Darwin user temp dir, so a test's snapshot home must be made there explicitly; and Anker's
secrets-scanner test expected no Git repository above its scratch, so it now sets
`GIT_CEILING_DIRECTORIES`.

## 2026-10-28: Disambiguation must include generated labels

A name-disambiguation pass can create a label that already belongs to another model. Check the
final labels against one another, including labels generated by earlier collision handling. For
historical events that stored display text instead of IDs, derive the visible model set first and
update only the recognizable name position in known event copy, including an older generated
suffix; preserve the remaining wording. The visible set includes every model named by rows,
alerts and prompts, even when their activity windows differ.

## 2026-10-29: Tie retained database verdicts to their source file

A skipped SQLite read is not evidence of recovery, but a format verdict from a
previously selected database must not survive a switch to a newer file. Record
the file alongside the verdict and preserve legacy cursors without a file name.
A transient read failure must not replace or become a retained format verdict;
regress busy and closed files, unreadable files, and file changes with synthetic
databases. `busyDatabaseKeepsItsFormatProblem`, `transientReadFailureIsNotKept`,
`readFailureLeavesAnEarlierFormatProblemKept`,
`keptProblemIsDroppedWhenCodexMovesToANewFile`, and
`readFailureAfterFileChangeDropsTheOldFormatProblem` guard those transitions.

## 2026-10-29: Distinguish source read failures from format drift

A failed file read does not establish that a provider changed its format. Keep
read and format verdicts separate and give format verdicts precedence when both
occur in one ingest. Preserve the start time only across reports of the same
kind; apply the same delayed notification policy to both. `formatProblemOutranksAReadProblem`,
`unreadableTranscriptIsAReadProblem`, `readProblemKeepsItsSinceAcrossRuns`,
`movingFromFormatToReadProblemRestartsSince`, and the Collector health and
provider summary regressions cover classification, presentation and transitions.

## 2026-10-29: Enforce the ingest lookback at the collector boundary

A source may read an entire rollout that spans the lookback boundary, or return
old lines during catch-up. Filter response ends, compaction times and connection
event times in the collector on every ingest; preserve the remaining batch fields
and settle old failed turns through the existing path. `batchDropsRecordsFromBeforeTheCutoff`,
`linesFromBeforeTheLookbackAreNotStored`, `catchUpAfterTheLookbackKeepsOnlyRecentLines`
and `coldStartReadsOnlyLinesInsideTheLookback` cover the boundary, preserved fields,
collector storage and a real synthetic rollout.

## 2026-10-29: Keep failed-turn alert totals tied to counted membership

The most recent event describes one batch, not every failure in an open episode.
Persist ordered counted IDs and reason codes with the canonical total in the
evaluation transaction, and never infer membership from settlement timestamps.
Legacy totals can have unknown reasons. `failedTurnAlertCountsEveryFailureInTheEpisode`,
`settledFailuresAtTheEpisodeBoundaryAreNotCounted`,
`legacyFailedTurnEpisodeKeepsItsCountWithoutInventingReasons`, and
`failedTurnDetailsRecordOnlyCountedBatches` cover the stale wording and its causes.

## 2026-10-29: Keep acknowledgement actions scoped to rendered alerts

Capture the rows the user saw when acknowledging a list, and remove delivered notifications only
after the guarded database write succeeds. `acknowledgeAllCoversOnlyTheAlertsShown`,
`failedAcknowledgeDoesNotRemoveNotifications`, and `removeDeliveredMatchesThreadIdentifiers`
cover concurrent episodes, write failures, and notification thread identity.

## 2026-10-29: Collector acknowledgement must follow readable health

Collector problem identity must include repair-only red states, and a failed
assessment must not clear stored acknowledgement. A retained stale panel must
not enable writes. Regressions: `repairOnlyRedCollectorHasAProblemKey`,
`collectorAcknowledgementClearsWhenHealthy`, and
`collectorAcknowledgementNeedsTheInstalledCopyAndADatabase`.

## 2026-10-29: Render acknowledgement detail once

The snapshot already supplies the acknowledgement line as alert detail. Appending
it again in either alert view duplicates it; `acknowledgedRowShowsOneAcknowledgementLine`
checks the panel's rendered height, and the maintained snapshots expose the layout.

### 2026-10-29 — Idle arrival wording

A provider with stored models outside the sidebar window is idle, not learning from recent responses. `arrivalForAnIdleProviderSaysItIsIdle` and `versionAndIdleArrivalCopy` guard the arrival wording and its window.

### 2026-10-29 — Silent speed reversals

Telltale speed reversals need a silent ended outcome as well as closing the stored episode; otherwise catch-up can notify for an episode already replaced. Regression coverage: `reversalEndsTheOppositeEpisode`, `fasterIsReversedBySlower`, `reversalInsideACatchUpPassPostsNoStaleNotice`, and `reversalDoesNotLiftAShiftDismissal`.

### 2026-10-29 — Telltale panel speed points

Panel numbers must follow the stored evaluation point, including its freshness and
matched-response availability, rather than the dashboard's last-hour aggregate.
`rowMatchesTheSpeedReadingNotTheLastHour`, the thin/cold/idle/stale row tests,
and `panelScenesUseStoredSpeedReadings` cover both the visible dashes and notes.

### 2026-10-29 — Telltale open speed alerts

Open speed rows need the stored episode extreme, not the last event body: a non-escalating change otherwise leaves the row stale. `speedAlertStatesItsWorstSinceOnset`, `reversedSpeedAlertIsNew`, `speedAlertWithoutAUsableWorstKeepsItsEventWording`, and `worstValueAlertsDisambiguateModels` cover both directions, replacement acknowledgement, fallback boundaries, and naming collisions.

### 2026-10-30 — Rolling notification delivery

The delivered list can lag a successful post, so an absent identifier immediately
following delivery is not evidence of acknowledgement. A grace period protects
membership (`recentPostIsNotTreatedAsCleared`). On macOS 27, `usernoted` rejected
an ad hoc bundle under `/private/tmp` but accepted one under the user's home.
A single retry slot also lost package alerts when test notifications failed;
separate failure slots preserve the current package list (`failedPostLeavesPackagesListed`).

### 2026-10-30 — Capture warnings in synthetic extraction tests

Pandas deprecated the in-place `DataFrame.drop` keyword even though CSV output
remained correct. Assign the returned frame and check extraction stderr for
warnings alongside the synthetic CSV comparisons, so deprecations are visible.

### 2026-10-30 — Counter recovery and reset writes

Decode errors must follow the same preservation path as malformed counter text;
otherwise corrupt bytes crash the interface before recovery. Resetting only the
cumulative file avoids a later lifetime-file failure after the reset has already
been published. Numeric conversion can also overflow even when JSON parses;
preserve that input as corrupt too. The Transcription state tests cover these cases.

## 2026-10-30: Track upload ownership and retain explicit UI selections

Never infer ownership of a caller's file from its name, and allocate upload
storage only when processing starts. Duration fallback must handle decoder errors,
not just missing imports, and form selections must flow from the widget return
value. Regression coverage: `test_path_mode_keeps_upload_prefixed_file`,
`test_divider_rerun_makes_no_batch`, `test_divider_duration_falls_back_to_whisper`,
and `test_app_uses_selected_model`.

# Pytest option-only discovery

An option list is not necessarily a collection target: pytest option values
such as `-k counter` and `--basetemp <path>` must not be mistaken for paths.
Use pytest's parsed argument source to supply a project default, while retaining
explicit paths and node IDs. `transcription/tests/test_launcher.py` checks this
from synthetic caller directories with sentinel tests.

### 2026-11-01 — Integration repair lessons

Pure ASGI guards must handle WebSockets as well as HTTP. A raw WebSocket probe
returns on accept or close and cancels the remaining task, since an accepted
application may stay open indefinitely. When browser tests leave an event loop
on the test thread, run synchronous asyncio probes in a separate thread and
still exercise real mutation and WebSocket paths.

Compare each generated output with every source by file identity (`-ef` in
shell), including links and batch inputs. Stage output before publication,
propagate failures, and restore prior destinations after a multi-file failure;
report retained backups if rollback fails. Resolve asset references within the
permitted source root.

For process timeouts retain the spawned group leader unreaped while inspecting
and cleaning descendants. Skip exited or zombie members and signal only
revalidated live members; inspection or signaling denial fails closed without a
second cleanup attempt. Nested validators clean their child on outer SIGTERM and
restore signal handlers. Descendants can inherit pipes, so clean the group before
joining readers and test a signal-resistant descendant.

Historical local dates need the timezone offset at the event, not today's
offset. Normalize offset-bearing time-series timestamps to instants before
matching, while retaining local timezone interpretation for legacy naive input.
Time Machine snapshot names encode local wall-clock time. Resolve the local
offset at the snapshot date before serializing to UTC, and test both standard
and daylight time under a fixed timezone.
When testing QuickTime conversion, write the QuickTime CreateDate specifically:
an unqualified ExifTool assignment can create an overriding XMP value. Under
Bash errexit, use an increment whose return status is successful at zero.

Reject redirects and require HTTPS before attaching provider credentials; test
credential-bearing paths with synthetic TLS. Escape backslashes before quotes
when embedding notification text in AppleScript. Propagate notification errors
to status and logs. Capture mount enumeration status before filtering: an empty
result and failed observation differ. Bound status and repair commands and test
timeouts and direct-child cleanup with synthetic tools and homes.

Reject empty, future-dated or disproportionately small backup exports before
pruning older copies. For remote workbook edits, fetch the version before the
content, condition writes on it, refetch and reapply on conflict, bound retries,
and retain pending edits on failure. Do not upload unconditionally without a
version. Test suspicious backup and conflicting write paths with synthetic data.

SQLite connection context managers do not close connections. Close explicitly
before byte comparisons; delayed WAL checkpointing can otherwise change files
later. Preserve complete primary keys, large values, hidden rowids and sequence
high-water marks during edits and rebuilds. Start transactions before DDL,
check affected row counts and test rollback after an earlier schema change.

Audit GET helpers for lazy initialization and caching as well as obvious
writes. Initialize runtime state at startup and make reads tolerate missing
files. Rendered HTML must escape unmatched text and attributes, and exported
redaction must be checked after decoding CSV and HTML. Preserve machine paths
as structured values rather than reconstructing them from display labels.

Preserve workspace and worker identity through interrupted recovery. Refuse a
dirty target, preserve conflicts for manual resolution and remove registered
worktrees before branches. An operator pause or abort is distinct from success
and failure. Explicit repository environment paths must follow the task
workspace, not merely a changed working directory. Use path-limited commits
when staging selected paths so unrelated staged changes cannot enter them.

A discovery snapshot is not proof that a later file read succeeds: validate
the opened descriptor, frozen length and fingerprint, bound malformed-record
recovery, and treat per-file size failures as unreadable input. Apply limits
during file and network reads. A read error does not prove corruption; retain
state and block writes until retry. Run expensive refresh work off the UI
thread only when due.

For deployment, compare working bytes with the indexed blob before trusting
them; reject empty projects and malformed generated markers. Validate a saved
application independently before rollback, and defer interruption until a
synchronous child returns and restoration is complete. Snapshot every executed
helper, Compose/build input and read-only runtime file; preserve deployed
configuration and writable volumes. Retain bundles referenced by running or
stopped containers and skip pruning when inspection fails.

Reverse proxies must preserve the external Host including port, including in
health checks. Match reserved routes before fallback, and do not infer an
upstream from shared client IP and User-Agent. Validate an extension request's
initiator and redact sibling name/value records and tuples. Quarantine invalid
persistent state without automatically restarting empty; preserve batches when
delivery receipts may be lost and require explicit duplicate-aware recovery.

Streaming adapters must inspect upstream status before headers, keep usage
request-local and report later stream errors. Test concurrent completions and
split markers. When upstream cache fetches fail, propagate the error instead of
caching an empty success, then test both retry and a valid empty result. A
finite SSE queue wait needs heartbeats for healthy slow work and must close
orphaned or completed streams.

For local health monitors, update cached notices after successful writes and
continue sampling sleep on failed reads. A backward clock requires retaining
recorded grid points and clearing future-derived episode or streak state while
preserving valid open episodes. Compare normalized rule models before and after
warning-only validation and exercise synthetic suspicious and bundled rules.

Infer payment cadence without treating partial calendar years as complete, or
use payment spacing. Workbook duration edits require formulas over the supported
horizon and summary references to the edited duration. Test cross-filesystem
temporary output replacement rather than assuming rename works.

On macOS, `shutil.copystat` may not preserve ACLs or extended attributes.
Verify required security metadata when atomically replacing a file, account for
OS-managed provenance, and restore the post-write modification time when native
metadata copying would replace it with the old destination's time.

Persist an aggregate snapshot and its progress marker in one transaction after
successful commands. Incremental same-day replacement can discard earlier
contributions. When a field remains editable during save, wait for a successful
write response and editing to end before asserting database state.

Budget YAML aliases and merges before downstream serializers expand them, and
exercise recursive and bounded cases in each implementation. Restrictive CSPs
can require browser wait predicates as functions instead of strings. When a
runner appends arguments to multiple categories, use a precise `-k` expression
for focused tests rather than appending unit paths to a browser category.
When a synthetic deployment fixture copies the current source `Info.plist`,
keep its receipt and expected version aligned with that plist after a release
bump; otherwise the fixture represents an impossible mixed-version bundle.
For compiled CLIs, check the deployer's expected version even when the deployer
lives outside the project directory, and bind the current synthetic fixture to
the CLI source version. Two matching stale strings can otherwise hide rejection
of the current release.

### 2026-10-31 — Exercise the deployed scheduled command

A scheduled runner can keep executing checkout code even when the standalone
artifact is current. Build the deployed artifact in a synthetic home, remove the
checkout, and run the generated job with cached credentials. Validate executable
admission both during installation and each run. Preserve operator settings when
replacing an existing runtime installer.

### 2026-10-31 — Prune only after successful forward deployment

Backup retention belongs after activation, validation and cleanup. Failure,
rollback, unchanged and dry-run paths must preserve older recovery copies.
Order eligible real directories by modification time and descending name on
ties; reject linked roots and ancestors before touching contents. Remove
read-only descendants without following nested links, and report pruning
failures as warnings with the affected path.
Include slash-terminated linked roots in admission tests: `lstat` can otherwise
follow the final link. An EXIT trap is too late to gate retention; explicitly
check final permission changes and owned staging cleanup before pruning.

### 2026-10-31 — Size Git output buffers for tracked files

Node's default subprocess output buffer is smaller than some tracked synthetic
fixtures. Deployment admission must size its `git show` buffer from the source
bytes already read, while retaining exact index comparisons. Exercise a large
tracked blob through the default inventory and verify that both staged and
unstaged mismatches still fail before publication.
Synthetic Git fixtures must also suppress inherited automatic maintenance for
their Git commands and child deployers. Otherwise a maintenance lock can vanish
during a whole-tree snapshot. An aggressive-maintenance regression should keep
the complete mutation assertion and verify that maintenance never starts.

### 2026-10-30 — Requirements include and constraint handling

Dependency checks must follow both spaced and attached requirement includes and
fail closed on unsupported directives or unreadable files. Constraints limit
versions but do not install packages; track their traversal separately so a
constraint cannot hide the same file when it is later included as requirements.
The shared uv guard's synthetic parser tests cover these cases.
An allowlist for requirement lines must validate operators, versions and marker
expressions as well as names; accepting arbitrary suffixes defers malformed input
until dependency installation. Reject valid syntax outside the supported subset
explicitly rather than guessing at it.

### 2026-10-30 — uv ignores dependency Python upper bounds

uv intentionally ignores upper bounds in a dependency's `Requires-Python`
metadata. A passing suite and `uv pip check` therefore do not establish that a
dependency supports the interpreter in use. Docpipe constrains readability-lxml
below 0.9 because 0.9 excludes Python 3.15; its regression checks both the
declared range and the resolved version. Review that constraint when adopting a
new supported readability-lxml release.

### 2026-10-30 — Validate standalone Python specifiers as specifiers

When reusing a requirement parser for `requires-python`, separate the synthetic
package name from the specifier with whitespace. Otherwise malformed text such
as `oops>=3.12,<3.16` becomes part of the package name and can pass validation.
Reject requirement markers as well: they are valid on dependencies but not in
`requires-python`. The shared uv guard covers names, extras, markers, valid caps
and explicit deferrals.

### 2026-11-01 — Guard optional image cleanup without masking failures

Image build cleanup must handle an unmatched glob or missing optional path without
forcing removal. Guard each fixed path or glob entry, including dangling symlinks,
and propagate removal errors. Exercise the actual shell fragment against synthetic
present, absent, linked and failing inputs so cleanup does not silently regress.

### 2026-11-02 — Detect sensitive URL fragment parameters

Scan fragment parameters as well as query parameters using the shared sensitive
key vocabulary, and preserve names recognized by the prior matcher. Export
regressions should include secrets too short for generic opaque-token detection;
formats that omit a field cannot independently prove that field was redacted.

### 2026-11-02 — Check application-level success in HTTP responses

A 200 response carrying `ok: false` is not a successful operation. Check the
response body before closing a dialog or reporting success, and test both the
rejected and confirmed paths.

### 2026-11-02 — Scan encoded structured content before export decisions

Pattern matching decoded content alone misses sensitive field names and opaque
values inside encoded JSON. Reuse the structured scanner within existing depth
and length limits, then target the encoded container so severity-based bulk
decisions cannot leave its detected contents in an export.

### 2026-11-02 — Check file identity across editing sessions

Atomic replacement protects a single write but does not detect an external edit
made after a document was opened. Record the file identity at open and after
successful saves, reject conflicting in-place saves, and leave a Save As escape
hatch for the unsaved edits. Tests that adjust the file's modification time as
setup must reopen it before exercising the save contract.

## 2026-11-02: Treat future saved check times as due

A persisted success timestamp can be later than the current wall clock after a
clock correction. Treat it as absent when computing the next check or catalog
refresh; otherwise an automatic check or manual refresh can stall until the
clock catches up. Exercise the actual controller requests and displayed deadline
with an injected clock as well as the scheduling helper.

## 2026-11-02: Compare Homebrew formula version schemes before versions

Homebrew can reset a formula's version numbering by increasing its
`version_scheme`. Comparing version strings alone then reports an old keg as
ahead. Retain the optional scheme from both the listing and the selected keg's
receipt, default missing values to zero, and compare schemes before package
versions. A higher listing scheme marks differing versions outdated; equal
versions remain current. Preserve optional decoding for existing saved data.

### 2026-11-02 — Collector health and backwards clocks

Run IDs preserve recording order when wall time moves backwards; timestamp ordering can hide newer failures. Reset a source problem's future start to the current run time so a later report can confirm it. The rollback regressions cover both the store and health evaluation and the source-state confirmation path.

### 2026-11-02 — Preserve failed Git status observations

A failed Git status command is an unknown working tree, not a clean one. Store
its error independently from history-scan errors, retain unknown counts through
the API, and clear the error only after a successful status scan. Count worktree
deletions and type changes among modified files. Corrupt-index, timeout, API
recovery, and browser-card regressions cover these paths.
Preserve the leading status columns of real porcelain output across subprocess
helpers: stripping whitespace can turn a worktree change into a staged one.
Exercise both deletion and type change through an actual quick scan.

### 2026-11-02 — Resolve default branches from local refs

A checkout's current branch is not necessarily its default, and a previously
stored default can become stale. Prefer the local origin HEAD reference, then
local main or master, and refresh the stored value during branch scans. Real
synthetic repositories cover feature and detached checkouts and remote HEAD.

## 2026-11-02: Preserve alerts when report rendering fails

Model Sentinel saves scan results before rendering reports, so a renderer exception
could lose the change alert after the baseline had already advanced. Catch failures
at the report boundary, redact credential values from the fallback, and apply both
change and error notification policies to the recorded result summary.
Fallback artifact writes can fail too: emit outside the original exception
handler, keep the redacted console diagnostic, and attempt notification and
retention cleanup even if the artifact cannot be written.

### 2026-11-02 — Report conversion failures to scripted callers

Missing or malformed inputs and output write errors must propagate to the CLI's
nonzero exit and stderr path. Exercise each failure with synthetic input and
check that input errors preserve an existing output file.

### 2026-11-02 — Separate Git branch refs from checkout state and paths

`git branch` can report a detached HEAD as a pseudo-branch; enumerate
`refs/heads` instead when persisting local branches. End revision arguments
with `--` in history commands so a branch sharing a directory name remains
unambiguous. Exercise both cases against synthetic Git repositories.

## 2026-11-02: Distinguish missing selected baselines from first saves

Model Sentinel treated a missing dated or prior-day baseline as an initial save
even when the provider had history, creating false additions and advancing its
snapshot. Check for any saved history before allowing an initial baseline and
exercise both missing selections with real saved snapshots.

### 2026-11-02 — Validate decoded credential shapes

Valid JSON can still be the wrong type for downstream credential handling.
Reject non-object values at the decoding boundary so both streaming and
non-streaming requests return an authentication error before contacting an upstream.

### 2026-11-02 — Include shared build helpers in fleet inventories

When a native release moves a build helper outside its project tree, include that
helper in both the deployer's required inputs and the fleet audit's indexed scope
and child inventory. Synthetic deployment and fleet fixtures must carry it too.
Test an indexed helper's removal so the fleet audit reports an unverified source
instead of silently omitting a release input.

### 2026-11-02 — Test refreshed dependencies after installing them

Refreshing a lockfile does not update an existing dependency installation. Install
the refreshed lock before running its dependent tests, and stop if installation
fails. Assert the ordering and failure path with a strict external-command stub.

### 2026-11-02 — Preserve schemas for empty extraction results

DataFrames inferred from empty row lists have no columns, so downstream filters
and CSV readers can fail even when an empty result is valid. Declare the input
and output schemas explicitly and exercise both empty workouts and absent metric
records through the complete extraction pipeline.

### 2026-11-02 — Reject XML values that disappear

An empty list produces no XML elements, silently dropping its key. Reject it
at serialization and cover both the serializer and the CLI error boundary;
document other XML round-trip type losses separately.

### 2026-11-02 — Read unborn Git branches from symbolic HEAD

An empty repository can have a named current branch even though `rev-parse`
cannot resolve HEAD to a commit. Read the symbolic HEAD for quick scans, as for
default-branch fallback, and retain detached HEAD as unknown. Exercise empty
repositories with real Git and an isolated database through both scan paths.

### 2026-11-02 — Deduplicate Git worktrees by shared directory

Linked worktrees have distinct top-level paths but share repository history.
Group discovery candidates by their Git common directory, preferring the main
checkout even when a linked worktree is encountered first. If the main checkout
is outside the scan root, retain the first discovered linked worktree. Exercise
both cases with real synthetic repositories.

### 2026-11-02 — Handle decoding errors at the import boundary

Decoding a CSV upload outside the error-handling block let invalid UTF-8 turn
bad input into a server error. Catch decoding errors at that boundary and test
the HTTP response alongside the unchanged database state.

## 2026-11-02: Restrict retention to owned files

Model Sentinel's configurable report directory can contain unrelated files. A
suffix and age alone do not establish ownership: cleanup must also match the
report names the application creates, while preserving protected paths. Test
both owned and unrelated aged files in a synthetic shared directory.

## 2026-11-02: Use provider-specific stable identifiers for saved catalogs

Model Sentinel's generic model identity fallbacks accepted a display name as an
OpenRouter model ID, allowing a malformed catalog to replace a saved baseline.
Require the provider's ID field in its profile, while retaining generic and
custom profile fallbacks. Exercise rejection through a saved scan and verify
that other providers still save successfully.

### 2026-11-02 — Preserve loaded jobs after failed unloads

A backup alone does not make deleting a loaded job's plist safe when unloading
fails. Keep the original plist and report the backup path, while allowing an
already unloaded job to be deleted even if bootout fails. Exercise both paths
using synthetic plists and a mocked unload operation.

### 2026-11-02 — Reject incomplete block payloads before replacing output

A short read can look like a successful RAW block and cause atomic output to
replace a valid destination with truncated data. Check header and payload lengths
before writing, and test both absent and existing destinations on failure.

### 2026-11-02 — Traverse document containers when extracting text

Office documents can nest paragraphs and slide shapes inside content controls
and groups. Walk those containers in order and reuse the normal paragraph,
table, and shape processing; strict-mode synthetic conversions catch silent
text loss that a successful return code alone misses.

### 2026-11-02 — Treat orphan creation as a branch modifier

Git's worktree orphan option modifies a new or reset branch mode rather than
replacing it. Validate incompatible start points separately and test the actual
symbolic HEAD and missing commit in a synthetic repository.

### 2026-11-02 — Keep SQLite lock waits off the event loop

Blocking SQLite operations inside async routes can stall unrelated requests for
the full busy timeout. Run database work in worker threads and exercise a locked
write through a real server with an independently timed status request. A SQLite
connection context manager commits or rolls back but does not close the handle;
close test fixture and readback connections explicitly.

## 2026-11-02: Generated Markdown tables through HTML converters

When an HTML-to-Markdown pipeline constructs table Markdown before calling the
converter, preserve those blocks across conversion. HTML whitespace collapsing
and `<br>` hard breaks can change empty-cell padding and table line endings;
restore the surrounding block prefix on every line, and escape source
backslashes before pipe delimiters. Check rendered cell values and quoted
table structure as well as exact top-level lines. List markers belong only on
the first line; indent continuation lines and ensure every placeholder is
resolved even when the converter emits an unexpected prefix.

### 2026-11-02 — Validate direction before normalizing amounts

Taking an absolute value can turn an unsupported positive withdrawal into an
outgoing transfer. Reject the unexpected sign before normalization and test a
later invalid row across a batch so no earlier outputs are committed.

## 2026-11-02: Validate import headers before opening the database

An absent CSV cost column was treated like an empty value, silently importing
rows at zero cost. Reject missing required headers before acquiring a database
connection, and test rollback with a failure on the second valid row so the
first insert must actually be undone.

### 2026-11-02 — Encode SQLite BLOBs consistently across exports

Passing SQLite bytes directly to a CSV writer produces a Python bytes
representation instead of a portable encoding. Reuse the API's value encoder
and serialize BLOB objects as JSON text in CSV cells; test both export formats
with binary bytes, large integers, Unicode and nulls.

### 2026-11-02 — Ad hoc walks must resolve hard-link ownership

Storage Monitor's native walker emits hard-linked files as candidates rather than adding their bytes to directory totals. Every standalone walk must resolve those candidates before rolling up totals, just as a full scan does. Regression fixtures should compare an unindexed estimate with `du` before the directory moves, while retaining a watchlist fallback check for the shared path.

### 2026-11-02 — Validate identifying fields before replacing reports

An absent upstream date silently produced an unusable CSV. Reject rows missing
both supported date fields and test that the prior output remains byte-identical
after failure, while allowing optional fields to remain empty.

### 2026-11-02 — Apply literal-text protection to every spreadsheet output

A workbook writer can preserve user strings as literal cells while a CSV fallback emits the same values as formulas. Apply the protection to each output path and test a parsed CSV row, including every user text field and the unchanged non-text columns.

### 2026-11-02 — Confirm each permanent snapshot deletion

Single-item and administrator deletion paths need the same irreversible-action
confirmation as bulk deletion. Exercise cancellation and acceptance through the
browser, checking that cancellation sends no request and acceptance sends one.

### 2026-11-02 — Accept qpdf repairs without hiding errors

qpdf returns exit 3 for successful operations with warnings, which can stop a
shell script before it publishes repaired output. Apply its warning exit policy
to each processing call, and test with a synthetic damaged cross-reference table
whose warning status is verified before checking the output pages.

### 2026-11-02 — Clear derived selections when wildcard matches disappear

A live file preview that only refreshes for nonempty matches can submit stale
selections after the pattern changes. Clear the selection on an empty result and
test both the warning and unchanged persisted counters through the UI.

### 2026-11-02 — macOS `mktemp -t` can ignore the test's `TMPDIR`

On macOS, `mktemp -t` may select the Darwin user temporary directory before `TMPDIR`. A test that checks only its own `TMPDIR` can therefore pass without observing the application's files. When testing cleanup, inject a narrowly scoped creator that uses an explicit absolute template, record the paths, and verify they exist at the operation boundary before asserting their removal.

### 2026-11-02 — Guard entry points when sourcing shell scripts

Guard a script's main call when its functions are also sourced. Source the
complete script in tests so a trailing line cannot cause main to run unexpectedly.

## 2026-11-02: Name icon-only controls in the rendered interface

RouterView's Settings icon had no accessible name, so users of assistive technology could not identify it and role-based browser tests could not find it. Give icon-only controls an accessible label and exercise the real control by role.

### 2026-11-02 — macOS Bash 3.2 assertions need explicit failure handlers

A standalone `[[ ... ]]` can fail without stopping a script under macOS Bash
3.2 even with `set -e`. Add an explicit failure handler to each assertion and
probe actual failing inputs to confirm later commands do not run. For destructive
UI actions, select the named target and arrange a deterministic decoy first so
positional selection fails the test.

## 2026-11-02: Treat filename prefixes as literal text

User-selected prefixes can contain regex metacharacters. Compare the prefix as
literal text before matching the dated suffix, and exercise discovery filters
with hidden files as well as ordinary files at multiple depths.

## 2026-11-02: Preserve row fields beyond declared export columns

An upstream column declaration can lag behind its rows, so writing only the
declared fields silently loses data. Include sorted undeclared row keys, warn
with their names rather than values, and exercise both missing-value modes with
exact synthetic CSV output.

## 2026-11-02: Canonicalize accepted dates at the input boundary

ISO parsers can accept compact and week-date spellings as well as calendar dates.
Store the parsed date in canonical form before using it in filenames or other
outputs, and test each accepted spelling against the resulting value.

## 2026-11-02: Drain request handlers before closing shared databases

Stopping an HTTP accept loop does not finish daemon request threads. Model
Sentinel's server must join its handlers before closing their SQLite connections;
bound inactive socket reads so an incomplete local request cannot block shutdown
forever. Coordinate an in-flight request and guard the close in a regression test
so the unsafe ordering is detected without closing SQLite during a query.

## 2026-11-02: Guard branch resets against commit loss

Before resetting a local branch, check whether its tip is an ancestor of the
selected start point and require explicit force when it is not. Exercise the
refusal and forced reset with real synthetic Git repositories, checking both
the branch ref and destination path.
Use full local refs for membership checks: Git's shortened display name can
change when a tag shares the branch name, bypassing a guard keyed by that name.

## 2026-11-02: Handle decoding failures at the input boundary

Parsing error handlers cannot catch invalid text encoding when a file is decoded
before parsing. Exercise invalid bytes through the CLI and report decoding errors
through the same structured input-error contract without creating output.

## 2026-11-02: Describe each launchd calendar entry independently

Combining fields across StartCalendarInterval entries can invent a schedule and
hide real trigger times. Group only entries differing in weekday, preserve the
other entries separately, and cover month, day and both Sunday encodings with
direct schedule tests alongside an API smoke test.

## 2026-11-02: Verify converted links and their emitted targets together

HTML-to-Markdown converters can discard both element IDs and fragment links.
When combining pages, explicitly emit each page anchor and verify rewritten
links against the resulting document, including pages without headings.
Escape attribute values when emitting raw HTML, and parse the emitted IDs in
tests so quotes and entity-like filenames cannot disguise malformed markup.

## 2026-11-02: Normalize distance records before aggregation

An output column labelled kilometres can silently misstate mixed-unit records if
it sums raw values or assumes one unit. Convert each record using its declared
unit before deduplication and aggregation; reject missing or unknown units.

## 2026-11-02: Cover every launchd domain in target selection

Apple and non-Apple daemons both use the system launchd domain. Exercise every
discovered plist domain and the unknown fallback when constructing job targets
and bootstrap prefixes, so a new or overlooked domain cannot silently use the
user GUI domain.

## 2026-11-02: Scope shared Makefile self-tests to their caller

A shared self-test that always exercises every consumer couples otherwise independent project suites. Accept explicit consumer selections, validate them before making scratch space, and retain the unscoped form for the fleet-wide check.

## 2026-11-02: Compute imported cache rates from imported prompt tokens

RouterView CSV imports populate `tokens_prompt` but not `native_tokens_prompt`.
Aggregating the latter made the cache hit rate zero even when imported rows had
cached tokens. Exercise summary totals and filtered rates through a real CSV
import so the aggregate uses the data actually stored by the active path.

## 2026-11-02: Extend Excel tables when appending workbook rows

Writing cells below an Excel table does not extend its range or filter. Exercise
the shipped template through consecutive appends, and extend matching tables
and their filters while preserving the workbook's formulas and lookup cells.

## 2026-11-02: Label destructive date boundaries with their timezone

RouterView's purge used UTC calendar dates for both generations and daily summaries, but its button did not identify the timezone. State the timezone at the control and in the setup guide, and exercise the rendered label alongside an independent boundary test so users can predict which rows remain.


## 2026-11-03: Guard Bash assertion style, not only individual lines

The remediation fixed macOS Bash 3.2's silently ignored `[[ ... ]]` failures in the scripts it touched, but identical lines in three other suites kept passing without checking anything. When a language trap makes assertions vacuous, add a repository check for the pattern (`tools/tests/test_bash_assertions.sh`) so new and untouched scripts are covered too.

## 2026-11-03: zsh skips the EXIT trap when errexit fires inside a function

Under zsh 5.9 with `set -e`, a failing command inside a function, or a function returning nonzero at top level, ends the script without running `trap … EXIT`, so shell suites left their temp roots in `$TMPDIR` whenever a test failed. `exit` and failing top-level commands still run the trap: run each test function in a subshell, `( "$test" )`, or make assertion helpers `exit`. Avoid `test || exit 1`: the `||` context disables errexit inside the function, so its failing steps are ignored.

## 2026-11-03: Calling blur() from keydown runs onBlur with the old state

HAR Scope's zoom field set its "cancel" state and then called `blur()` on Escape, but `onBlur` runs synchronously in the same handler and still saw the typed value, so Escape applied the edit instead of cancelling it. Signal a cancel that a synchronous handler must see through a ref, and test the cancel key, not only the accept key.

## 2026-11-03: Build test temp directories on pytest's tmp_path

Git Fleet's `make_tmpdir` helper called `tempfile.mkdtemp()` with no cleanup, leaving 42 directories in `$TMPDIR` on every suite run until more than 1,200 had built up. Test helpers that need fresh directories should be fixtures on `tmp_path` or `tmp_path_factory`, so pytest's retention removes them. To prove a suite is clean, run it with `TMPDIR` pointed at a private empty directory and count what is left.

## 2026-11-03: Exercise every API consumer of shared status fields

Fleet and repository detail both expose quick status, so exercise each consumer when changing its presentation. Share the rule in `present_quick_status` and cover boundary cases through `test_repo_detail_quick_status_matches_fleet`.

## 2026-11-03: Don't cap local log readers below real sizes

An audit added line, file and zstd-window caps to Telltale's log readers. Real Codex rollouts already exceeded them, and because a failed read keeps no cursor, the collector retried those files every run and showed a sticky "can't read Codex's logs" alert. A size cap on a local file the user's own tools wrote only turns valid input into a permanent failure; leave such reads bounded by the decoder's own limits and available memory. If a limit is ever needed, measure the real maxima first, set the limit well above them, and test above it with conspicuously synthetic inputs, including large single-segment zstd frames and resumed plain lines. Telltale's `ZstdLargeInputTests`, `LineReaderLargeLineTests` and provider regressions do this; `LargeLogSizes` records how their sizes were chosen.

## 2026-11-03: Preserve dynamic error types when rendering read failures

Foundation can bridge Swift errors to NSError, so a broad NSError cast can hide a
Swift error's own description. Check the dynamic NSError type and CocoaError
explicitly, then prefer a Swift CustomStringConvertible description; exercise
both protocols, an NSError subclass and the localized fallback.

## 2026-11-03: Test actor responsiveness through lock ordering

A wall-clock deadline around an async sleep also measures unrelated work on the
same actor. Hold the contested resource until the actor observes the operation
in flight, then release it and verify the actual write. A bounded watchdog
prevents a broken synchronous operation from hanging the test; deliberately
move the write onto the actor to confirm the test catches that regression.

## 2026-11-03: Hover a chart only after it is drawn at its measured width

The shared SVG chart first draws at a 400px placeholder width and measures its container in an effect after paint. A Playwright `mouse.move` sent in that window lands outside the placeholder plot, the chart clears its hover, and Chromium sends no further move when the chart resizes under the stationary cursor, so the tooltip never appears; Git Fleet's date-boundary activity test failed this way under load. Call `_wait_for_chart_width` in `git-multirepo-dashboard/tests/test_e2e.py` before a single-move hover; `test_chart_hover_waits_for_measured_width` holds the placeholder width to prove the wait is needed.

## 2026-11-11: Keep native select fallbacks among the options

When a native select's saved or default value is absent from its options, its displayed value can disagree with the application state. Keep the fallback option available even when its count is zero, and test both the default and an unavailable saved choice against the rendered control.

## 2026-11-11: Wait for browser hash state to render

After navigating to a new hash on the same page, wait for the rendered state to
settle before asserting it; a synchronous read can observe the previous state.

## 2026-11-11: Attach page-wide listeners before the first paint

Model Ladder attached its `hashchange` listener in a Preact `useEffect`, which runs after paint. A hash change in the first moments after load was missed, and `test_index_selector_and_borrowed_costs` failed about one run in three when it navigated to a new hash straight after a reload. Attach listeners that must not miss an early event in `useLayoutEffect`.

## 2026-11-11: A cleanup rule keyed on a directory name needs a deny list and a shared-folder rule

Storage Monitor offered any directory named `Cache`, `Caches` or `.cache` as a one-click Trash target and collapsed nested matches into the outermost one. That made the whole of `~/.cache` a single "low risk" item, although it holds many tools' data including the uv cache the app runs from, and it offered live system state such as the CoreSpotlight index and Apple containers. Treat a folder shared by many owners as review-only and list its entries, refuse system-managed and synced locations on the server as well as in discovery, and confirm every move. Move with `os.rename` and fail closed: `shutil.move` falls back to copying the tree and deleting the source when the rename is refused.

## 2026-11-11: Classify review risk after all action gates

Storage Monitor initially chose a discovery rule's actionable risk before grouping small matches as review-only. Include size, staleness and protection in the action decision before choosing risk, and test rules whose actionable and review risks differ.

## 2026-11-11: Isolate system-discovered roots before report tests

A Storage Monitor report test enumerated host temporary directories when a new collector used OS-discovered roots without a suite-wide fixture. Pin those roots to synthetic directories and guard host enumeration before any report builder runs. Keep the fixture directories outside walker inputs: putting them inside each test's input tree changed native enumeration counts. No cleanup action was run against the host roots.

## 2026-11-11: Recheck descendants and protected containers before moving a directory

An indexed newest time cannot prove a directory stayed stale: an in-place file edit does not update its parent directory timestamp. Before a cleanup rename, enumerate the directory again with the native walker and refuse incomplete results. Protect both a managed worktree and any cleanup target enclosing it; check indexed markers for report-time eligibility and current markers again at execution.

### Storage Monitor report boundaries

A cleanup report can outlive the state it describes, and a missing running-app probe is not evidence that a cache owner has quit. Treat an unknown probe as review-only for Library cache entries, and keep reports bounded while exposing counts and bytes omitted from a truncated list.

When eligibility depends on a later report-wide probe, carry that eligibility from discovery to the gate and test assembled reports using indexed entries. Tests that inject already-actionable findings cannot detect a missing activation. Apply path and indexed-content protections before enabling the action.

### Storage Monitor system-root contracts and index scale

Synthetic root replacement concealed an unsupported macOS `confstr` key, silently dropping the per-user temporary and cache roots. Keep report and action tests synthetic, but separately check the read-only system lookup against `getconf` without enumerating the real directory. Small synthetic indexes also concealed repeated full-table protection queries and quadratic candidate deduplication; retain a representative large-index timing regression alongside correctness checks.

## 2026-11-12: Preserve snapshot order within a timestamp

A seconds-only snapshot filename silently overwrote distinct fetches made in the same second. Allocate an ordered suffix for collisions, including identical clock values, and test retention when more snapshots share that timestamp than the store keeps.

## 2026-11-12: Validate persisted page state and preserve chart boundaries

URL and browser storage values are untrusted even in an offline page. Validate each field before using it, and save URL state independently of storage so a blocked storage API does not disable copied links. A logarithmic chart cannot place zero on its axis: show a zero cap at the plot boundary, shade the positive range and explain the placement. Format small positive step values with enough precision to avoid reporting them as zero, including the axis units.

Number input `min` attributes do not prevent users entering negative or incomplete values. Apply the same validation to live state as restored state before deriving chart coordinates, and build logarithmic domains without overflowing at finite numeric extremes.

### 2026-11-12 — Filter changes using displayed precision

When a change panel reports differences in displayed numbers, compare the same
formatted values the page shows. Raw price or latency differences can otherwise
produce a change whose two displayed endpoints look identical. Test invisible
rounding differences, visible differences, and transitions to and from missing
values in every display mode; keep unrounded values for calculations and meters.

## 2026-11-12: Guard every browser storage consumer

A guarded Findings preference could not prevent a blocked-storage error from the
separate theme initializer. Guard each storage read and write, preserve an OS
preference fallback, and test the dashboard with storage methods throwing.

## 2026-11-12: Keep comparison details outside fixed-width tables

Long explanatory text inside a comparison table can force one column wider and
crush the others. Place the details outside the table, set explicit minimum
column widths, and test the open details state with long synthetic text and a
narrow viewport.

Keyboard navigation through a long picker must expose the active item to
assistive technology and keep it visible. Move focus to the actual option,
scroll it into view, and test navigation beyond the list's visible height.
