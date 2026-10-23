# Lessons learned

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
