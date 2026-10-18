# Brew Version implementation and acceptance record

## Version 1.1.0 tap support validation — 2026-10-18

Release sources and the signed local release bundle declare version 1.1.0,
bundle build 4. The signed CLI reports `1.1.0`; rendered Settings shows
`Brew Version 1.1.0`. No release approval, deployment or production launch is
implied by this record. Earlier approval below applies to its historical release.

| Automated check | Current result |
| --- | --- |
| `make -C brew_version test` | Passed: 243 core, 21 CLI and 72 app Swift tests; all 5 Node release integration cases; no skips. |
| `make -C brew_version release` | Passed: release CLI/app builds and strict signature verification. |
| `make -C brew_version acceptance` | Passed: 2 synthetic service tests and separately signed harness build; no GUI launched. |
| `make -C brew_version settings-prototype` | Passed: separately signed maintained Settings prototype build; no GUI launched. |
| `make -C brew_version snapshots` | Passed: all eighteen PNGs (nine states in both appearances), layout/pixel guards and bounded long-list checks. Every PNG was inspected visually. |
| Signed CLI `--help` and `--version` | Passed offline; help matches the golden fixture and version reports 1.1.0. Source and built bundle plists match, including build 4. |
| `node --test tools/tests/deploy_brew_version.test.mjs` | Passed: all 43 synthetic installer cases, no skips. |
| `zsh tools/tests/test_check_local_deployments.zsh` | Passed: `check_local_deployments tests: PASS`. |

The final visual set includes `tap-watching` (official, amber tap and untapped
error rows) and `tap-suggestions` (tap kind/Installed labels), in light and dark.
All headers and footers are visible; errors wrap inside their rows. The
version-dense tap row middle-truncates its secondary tap label; full identity
remains available in help and accessibility. Rendering establishes layout only.

Native action regressions were written before UI edits and failed for missing
row/status presentation, then passed. A further regression reproduced selecting
a repeated-prefix tap suggestion resolving and watching a different tap/version.
Explicit choices now retain their parsed identity through the existing search
pipeline. Copy-version resolves the selected source and kind, with editing and
cancellation regressions. The first complete run caught a synthetic harness
recovery test bypassing the maintained ten-minute catalog floor; fault controls
now advance only the harness clock. The final full suite above passed after
that correction. No production refresh timing was changed.

The synthetic harness preserves its original controls and cases and adds
Tap failures/Restore tap responses and Remove tap/Restore tap. Its service
tests verify installed tap provenance, both exact singular failure counts,
recovery and the untapped watch error. All inventory, transports and state
are invented and private; production has no simulation switch.

| Current native/owner gate | Disposition for 1.1.0 |
| --- | --- |
| Tap rows, full-name help/accessibility, suggestions, Return/Command-C, full install/upgrade commands and status/recovery copy | Partial: controller observed the specific synthetic cases below. Full remaining cases require separate native follow-up; automated action tests and PNGs do not establish physical input or the live accessibility tree. |
| Status-item repeated presses, manager-hidden fallback, notification/Finder reopen, full panel bounds | Unmet for this release: requires current native interaction. Historical observations below are retained. |
| Search focus/arrows, pending Return, collisions, long result scrolling and Delete/Undo | Partial: collision selection and selected-group Delete/Undo observed below; remaining cases require native input. |
| Settings retention/activation, interval menu/checkmark, invalid/valid input, Command-W and both native appearances | Partial: validation, persistence, Command-W and light/dark observations below; remaining window/menu cases require follow-up. |
| Production notification permission/delivery/click, denial and error recovery | Unmet: requires owner/system acceptance; no production app launched. |
| Login registration/approval, status refresh, settings handoff, logout/reboot and cleanup | Unmet: requires owner/system acceptance; no login registration changed. |
| Deployment receipt, installed/running versions and installed login target | Unmet: no deployment authorized or performed. Verify agreement after separately approved deployment. |

Controller native synthetic follow-up on the current signed harness observed
an installed tap suggestion ranked first for `synthetic-shared`, separate
official/tap rows, tap selection plus Return saving the full-name watch, an
amber tap row and its full-name accessibility Watching group. The Copy upgrade
action pasted exactly `brew upgrade synthetic-owner/synthetic-tap/synthetic-shared`.
Tap failures displayed both exact singular status lines while retaining rows.
Remove tap displayed the exact no-longer-tapped error while retaining version
`4.5.6`; Restore tap recovered. These observations close those specific
synthetic native cases, not the broader gates in the table.

The same follow-up observed Settings version 1.1.0, invalid nine-minute input
remaining editable with the 10–1440 validation error, and valid 47-minute input
persisting into “Every 47 min” after Command-W and reopening. Native notification
authorization reported “Notifications are not allowed for this application”;
permissions were not changed, so delivery/click remains unmet. Open at login
stayed off with “App service unavailable”; it was not toggled. Physical
MenuBarAgent presses, VoiceOver announcements, production notifications and
logout/reboot/login registration remain unmet. No owner inventory was used.

Additional controller CUA selected the named full-tap Watching group, removed
it with BackSpace, then restored it with Undo; the accessibility tree showed
Watching 1 again. Light and dark native screenshots included the full header,
footer and notification-denial warning. Command-C on the selected installed
tap suggestion resolved its full-name request; pasting verified exactly
`4.5.6`. Settings Command-W closed the window, and reopening the panel showed
the persisted 47-minute interval. Notification permissions were unchanged.

Final controller follow-up watched the tap cask from Other updates; its selected
row copied exactly `brew upgrade --cask synthetic-owner/synthetic-tap/synthetic-app`.
Reopened Settings retained 47 minutes and version 1.1.0, with login still off
and the notifications-off recovery message visible. Turning Other updates off,
closing Settings with Command-W and reopening/searching retained installed tap
and official suggestions. Quit Brew Version exited the fresh harness; an exact
executable process check confirmed it was no longer running. The controller
also inspected every one of the eighteen maintained PNGs with the same layout
findings. No further live checks were performed; the remaining physical,
production, notification-delivery and login gates above stay unmet.

Task 9's combined validation step remains partial until its separate native
gates are completed or explicitly dispositioned by the owner. Private log,
snapshot and signed harness paths are recorded in the task handoff report.

## Owner release approval — 2026-10-17

The owner approved releasing version 1.0.0 and merging PR #57 with the
following acceptance decisions. This approval supersedes the outstanding-gate
language in the earlier investigation records below.

| Check | Release disposition |
| --- | --- |
| Repeated physical status-item open/close | Owner confirmed reliable single-click opening and closing across multiple instances and windows. Closed. |
| Actual Open at login | Owner confirmed startup after logout/login and after reboot. Closed. |
| Live panel resizing and complete header/footer | Maintained synthetic build passed search, warning, clear, collapse/expand and both appearances; earlier record gives the separate native and regression evidence. Closed for the reproduced clipping path. |
| Notification delivery and click opening | Owner previously confirmed Notification Center delivery and a notification click opening the app. Closed. |
| Notification opening followed by one icon press to close | Owner explicitly deferred this check; a failure can be addressed later. Accepted release limitation. |
| Status-item count accessibility / VoiceOver | Owner explicitly waived this check for this release. Skipped, not a passing result. |
| Keyboard focus and desktop/Space behavior | Focus moves, but returning to the app or opening Settings from another desktop switches to desktop 1. Owner accepted this known bug for release and requested a separate follow-up. Not marked fixed. |
| Login approval-required service state | Not observed on this host; retained automated coverage only. Recorded limitation, not a claimed native pass. |

The desktop follow-up should reproduce opening Settings while another Space
is active and switching back to the app after moving focus elsewhere. Expected
behavior is to preserve the current Space, dismissing the panel when focus
moves away. The observed switch to desktop 1 must be investigated separately;
no cause or fix is asserted here. The owner will squash-merge PR #57 and delete
its remote branch. Final local cleanup and deployment await a separate owner
prompt after that merge. This change records approval; it performs neither
merge nor deployment.

## Current release acceptance follow-up

The owner found a real repeated-status-click defect after the earlier visual
round: first open/close works, but subsequent popovers can be clipped above the
screen. Fresh-host renders and ordinary app-reopen checks did not establish
this path. Passing automated suites or changing the deployment target alone
did not close the defect.

A later owner check found that the top appeared complete but repeated status
presses were swallowed. Passive logging of the distinctly labeled synthetic
TEST item correlated six such presses with our transient-close veto and no
subsequent button action. The veto assumed AppKit would deliver that action.
An outside click closed the popover normally. This establishes the click bug's
cause; it does not establish the cause of the original clipped screenshot.
The menu bar manager had hidden TEST initially, which was a diagnostic identity
problem rather than evidence that the manager caused the app's click defect.

A private candidate replaced manual target/action ownership with macOS 27's
public expanded-interface delegate/session lifecycle. The owner then performed
ten actual TEST status presses and confirmed that every click worked, with no
clipping and the complete header/footer visible. Passive session/close logs
corroborated alternating transitions and stable on-screen geometry. A subsequent
Finder-reopen check exposed an already-visible session-start case. Adopting
that session fixed Finder reopening, but the owner's follow-up again found
missed closing clicks; its trace showed immediate close/reopen sessions. The
status correction was still unaccepted at that stage, while native-session
ownership and the popover's independent transient tracker were isolated. The
integrated replacement and subsequent physical results are recorded below.

The owner also recalled a CodexBar click fix. Its actual historical patch and
upstream [menu-card repair](https://github.com/steipete/CodexBar/commit/7465c6a11674d4cacb97b8f023dd9ad8fc70e446)
use parent-view mouse-down/up ownership for controls inside a native menu.
Its separate [shortcut repair](https://github.com/steipete/CodexBar/pull/1470)
avoids queued reopening during menu tracking. These are relevant ownership
examples, rather than a verified drop-in popover fix. A minimal always-allow
close control still needed two clicks, and exposed a late mouse-up action
after native dismissal. A mouse-down-only candidate also failed intermittently:
a fresh click during an unfinished close was treated as another close because
the popover still reported itself shown. Ten successful physical cycles followed
by another failure did not establish acceptance. The controller's logical
presentation and close-completion boundary required the replacement below.
No CodexBar implementation was copied.

The chosen replacement architecture keeps the existing rich content in an
owned panel, using the expanded-interface session to show it and synchronously
order it out. This follows Apple's documented custom-window lifecycle and
removes the popover's separate tracker and animated-close state. Compared with
another mouse-action workaround or a custom-view menu, it preserves the existing
search and row controls while requiring explicit sizing, screen containment,
keyboard and programmatic-opening regressions.

The root cause was established afterwards from the retained private traces and
the host itself. macOS 27's MenuBarAgent
(`/System/Library/CoreServices/MenuBarAgent.app`, which registers the
`com.apple.appkit.status-items` workspace) hosts status items: the app owns no
status-bar window, and the button receives forwarded clicks. Every mouse event
the button received had event number 0; one press/release pair was stamped
1 µs apart and another release arrived 0.76 s after its press. In the
always-allow control the popover dismissed itself on a forwarded mouse-up and
the toggle action arrived 0.40–0.66 s later, against a 0.54–0.56 s close
animation, so each close was a race; one of seven reopened. Every app-initiated
popover show was followed 30–116 ms later by a session begin with no press
(seven of seven), while app-initiated panel shows produced none: a popover
anchored to the button joins the session itself, a second owner. The first
panel candidate still failed the Finder-reopen close. Pressing the icon took
focus from the app about 45 ms before the begin, the resign handlers hid the
panel, and the begin reopened it. Placeholder anchors such as (0, −39) also
placed that panel at the lower-left screen corner.

The integrated controller therefore has one owner. Begin shows the panel and
the session's end hides it. Owned dismissal (Escape, Settings, custom interval,
focus moving elsewhere) hides synchronously, then cancels the session it was
showing. Late or stale ends are ignored by session identity, so no request
waits on an acknowledgment. A begin while a Finder- or notification-opened
panel is visible closes it. Focus loss while the pointer is on the placed
icon's menu-bar column is left to the session. An anchor counts as placed only
when its center lies in a screen's menu bar: a placed item's window can be
taller than the bar, such as (1599, 1277.5, 22, 64) on a 39-point bar.
Otherwise the panel opens at the top right of the first screen. NSPopover,
`PopoverActions` and `PopoverAppearance` are gone from production.

The first physical round on that controller opened on every press but never
closed on one. A passive TEST event log showed why: while a session shows the
panel, a press on the item delivers no event, no focus change and no end to the
app; only moving to another item or focusing another app ended the session.
Other developers report the same macOS 27 behavior ("left-click while open no
longer toggles (event is missing?)") in
[Apple's developer forums](https://developer.apple.com/forums/thread/832823),
and Apple's [WWDC26 guidance](https://developer.apple.com/videos/play/wwdc2026/289/)
covers only begin, end and cancel. The press does reach MenuBarAgent, so a
global left-mouse monitor (no permission needed for mouse events) recognizes
it. A press closes the panel only when it went down after the session began and
went down and up on the item's column. The opening press always goes down
before its begin arrives, so it cannot close its own panel; event timestamps
and `ProcessInfo.systemUptime` share one clock. Finder and notification
openings have no session, so their closing press is still left to the begin.

Results on the checkout, 2026-10-17: `make -C brew_version test` ran 221 Swift
tests (150 core, 11 CLI, 60 app including 24 panel tests) and 5 release/build
cases, all passing with none skipped. `make -C brew_version release` signed and
verified both products; `--help` and `--version` (1.0.0) passed. `make -C
brew_version acceptance` passed its service case and built the harness. `make
-C brew_version snapshots` validated all fourteen PNGs, byte-identical to the
inspected set from earlier that day. Removing the pointer check, the press time
rule or the press close each makes its regressions fail. On a private synthetic
TEST build of this source, with the menu bar manager running, the owner's
physical round closed on 8 of 8 icon presses, including cycles of about half a
second, with no reopen; every opening press was ignored by the close rule
(begin arrived 50–85 ms after mouse-down, before mouse-up), and pressing a
neighboring item closed it. A follow-up check reopened the running TEST app the
way Finder does; one press on its icon closed the panel and it stayed closed.
The log showed the recorded order: the press took focus from the app, the
focus-loss handlers left the panel alone because the pointer was on the icon,
the begin arrived 40 ms after mouse-down and closed the panel by cancelling its
new session, and no reopen followed. The notification-click opening uses the
same programmatic path but was not pressed in this round.

The first release now targets macOS 27, matching the available development and
acceptance host. All maintained package, bundle, generated harness/snapshot and
installer contracts were changed together in 2bd713e. Actual binary metadata
and retired-runtime rejection tests cover that policy. Earlier macOS 14 gates
and compatibility promises below are historical and superseded. Version stays
1.0.0 for this unpublished initial release; no OS installation is required.

Settings now has an ordinary **Send test notification** action using the real
notification service and click handler, without changing watched packages.
The owner confirmed that these tests appear in Notification Center and clicking
one opens Brew Version. Delivery and notification-click acceptance are therefore
established on the current host. Pop-up banner presentation remains a separate
OS-setting/delivery-condition investigation; API submission alone is never
presented as delivered. The owner also confirmed that Open at login persists
across repeated panel and Settings reopens; actual launch after login is deferred
until a convenient login/reboot, without requiring one during development.

An independent task review caught diagnostic interference with a failed package
notification: the original test action could clear or replace its retry payload.
Commit b436eb2 separates package and diagnostic recovery and guards asynchronous
completions by request identity. Its full Brew suite passed, and scoped independent
review found that interference addressed with no new findings. The status
interaction correction is integrated, and its physical results are recorded
above; an icon press after a notification-click opening remains unexercised.

### Retained panel geometry and scoped closeout review

Subsequent live acceptance reproduced the clipped header after search results
and notification warnings changed the retained panel's height. This was a real
viewport defect despite passing maintained-view snapshots. Passive synchronous
setter traces showed AppKit translating a temporary root/parent height mismatch
into an autoresizing constraint, then applying that offset again when the
window's frame view caught up. A 534-point window ended up with a 609-point root
and scroll view, hiding 75 points at the top. The scroll view's own
documentVisibleRect still reported enough space and concealed that ancestor
clipping from the earlier assertions.

The correction gives the window, material and viewport one sizing contract:
the root has no translated autoresizing mask and is pinned to the window's
public contentLayoutGuide; the scroll view is pinned to the material's edges.
The independently measured hosted document and small-screen outer scrolling
remain. A resize-delegate repair and a lazy fitting-size experiment both failed
live and were discarded. No delayed correction, frame clamp or click-lifecycle
replacement was retained. The regression replays the captured late frame write
after ordinary resize handling, then requires normal parent layout to restore
the actual window size and full hosted visibility. It failed all three geometry
assertions before the correction; it is a recorded-boundary replay, rather than
a claim that a hidden window naturally reproduces the live framework order.

The same scoped review found two other edge cases. Actual other-application
workspace activation now dismisses the panel even when the pointer rests on its
icon, while preserving the recorded icon-focus-before-begin exception and
excluding this app and MenuBarAgent. The controller regressions inject isolated
workspace notification centers. Four recorded hidden-item placeholder
rectangles now use the first-screen fallback even when they overlap a lower
display's menu bar.
Public geometry supplies no reliable placed flag: an actual anchor exactly
equal to one of those rectangles deliberately gets that fallback and no icon
hit region; other negative-origin and tall placements still qualify normally.

On the corrected private synthetic build, live CUA checks kept the complete
rounded header and footer through empty state, six suggestions, explicit cask
lookup/add, the actual authorization warning, search clear, list collapse/expand
and repeated search, in both appearances. Passive geometry then agreed at
534 points for window, root and scroll, with hosted visible origin zero.
A menu bar manager and its helper were running at that final geometry check and
were not quit or reconfigured. This establishes the observed content-resize
path; CUA app-window input does not establish physical MenuBarAgent icon input.
The earlier owner-performed status-click results above remain distinct from
this check. The new workspace-activation route has callback-order regressions;
its actual physical icon/keyboard-switch combination has not been repeated.

The final maintained synthetic build, without diagnostic tracing, also passed
that exact search/cask/warning/clear sequence, followed by light-mode
collapse/expand and repeated search, then dark-mode clear. Both synthetic apps
were quit through their normal Quit control and their process absence checked.
The definitive `make -C brew_version test release acceptance settings-prototype
snapshots` passed 226 Swift tests (150 core, 11 CLI, 65 app), all 5 isolated
release/build checks and the synthetic service case, without failures or skips.
Both release signatures passed strict verification; help and short help matched
the golden fixture, version output was exactly `brew-version 1.0.0` with empty
stderr, and actual release binary minimum versions were 27.0. All fourteen final
light/dark snapshot PNGs were byte-identical to the set inspected earlier that
day. Scoped independent re-review found no remaining source findings.

Before the owner release approval above, outstanding current-system checks
were the physical status/count
accessibility route on this final build, the new workspace-activation route's
physical input ordering, one icon press after a notification-click opening,
actual launch after login and the approval-required login branch. The owner
deferred logout/reboot; no such action was performed. The approval-required
service state was unavailable on this host. Notification Center delivery/click
and persisted Open at login were already owner-confirmed above; banner display
is a separate OS presentation condition. The supported minimum is macOS 27,
not the historical macOS 14 requirement. These commits update the PR and local
builds; they do not install, deploy, publish a release or merge the PR.

## Earlier final visual and correctness round


The corrective wave after a081f38 is complete through executable commit
13b99dd. Independent task reviews, their scoped fix reviews and the final
whole-wave review found no remaining actionable source findings. This section
supersedes the earlier layout, counts and current-gate statements below.
Version 1.0.0 remains the unpublished initial release. No deployment, push,
merge or history rewrite was performed.

### Correctness feedback and regressions

| Requested item | Implemented behavior | Retained regression evidence |
| --- | --- | --- |
| A1: overlapping installed scans | A concurrent caller group shares one capture and at most one replacement. Superseded callers adopt newer work; further missing listing metadata uses named reads. Exact cask metadata and later observations are reconciled after every await before publication and evaluation. | `InstallationSnapshotTests.overlappingHydrationsShareABoundedScan` and `overlappingFreshCaskMetadataAdoptsNewerCapture`, each with two and three callers; `thirdCatalogCallerKeepsItsNewMetadataWithoutAThirdScan`; `missingMetadataReadAdoptsNewerSearchBeforeCheckCommit`. |
| A1: repeated regex compilation | Reuse one compiled `VersionOrder` scanner and capture alternatives for token classification. | Retained Homebrew ordering/parity and external Unicode tests, including the 2,704-pair comparison matrix. |
| A2: search/add full rescans | Use the existing named installed reader only for result names, without inventory scanning or Other updates derivation. Preserve newer targeted observations and exact selected cask metadata. | `InstallationSnapshotTests.searchAndAddReadOnlyTheirResultNames`, `olderTargetedReadCannotReplaceNewerInstalledObservation` and retained caller-metadata cases. |
| A3: manual check blocked offline | Manual Check now attempts HTTP regardless of path-monitor state. Automatic checks remain gated. | `ControllerRegressionTests.manualCheckBypassesOfflinePathWhileAutomaticCheckWaits`. |
| A4: valid download lost on write failure | Publish both validated indexes and ETags in memory before persistence. Expose a distinct cache-write warning, retain it through transport fallback and advance successful-fetch cadence. Clear it after successful cache persistence. | `CatalogTests.validDownloadSurvivesUnwritableCacheAndReusesItsETags` with and without a prior pair; `WatchControllerCatalogTests.catalogCacheWriteFailurePublishesMemoryAndWarnsWithoutRepeatingDailyFetch`. |
| A5: suspicious catalog shrink | Reject a refreshed list with fewer than half the previous usable items, preserving both lists, disk bytes and ETags atomically. Admit exactly half. | `CatalogTests.suspiciousUsableCountPreservesBothListsAndETags` for formula and cask; `exactlyHalfPreviousUsableCountIsAdmitted`. |
| A5: partial unreachable reconnect | Any unreachable result retains reconnect retry, including batches with successful rows. Successful rows persist, while the batch does not advance the successful-check clock. Failed-save retry floors remain intact. | `ControllerRegressionTests.partialUnreachableCheckRetriesOnReconnect` and retained scheduler/persistence cases. |
| A5: rollback removes live app | Activation and restoration share apps-volume staging displacement, including restoring a saved absence. Keep displaced trees until collected cleanup and retain validated durable recovery backups. | Installer tests forbid recursive deletion of the live path, compare displaced inode/bytes, inject failed displacement and exercise simulated cross-device rollback. All 42 Brew Version cases pass. |
| A5: Close Window | Install standard nil-target `performClose:` on Command-W. | `NativeActionsTests.appKitLifecycleRetainsStandardQuitAndEditingCommands`; actual Settings close/reopen observed. |
| A5: tautological cache identity | Remove reference comparisons that cannot fail. Read the current cache synchronously after the final await, preserving concurrent additions and removal/Undo boundaries. | Retained concurrent-cache, removal and restoration regressions; delayed installed-observation case above. |
| A5: absent-package command | Copy install for absent packages and upgrade for installed ones, preserving `--cask` for casks. | `NativeActionsTests.commandOffersInstallOnlyForAbsentPackages` covers both kinds/states; actual absent-formula copy/paste verified. |

The original scan-count regressions reproduced three full scans for two callers
and 36 for three. Search/add receipt admissions were two/four instead of one/two.
The scoped core review then exposed one final-suspension race: an older missing-
metadata read could persist installed version 1 after a newer search observed 2,
causing a false amber row and notice. The controlled saved-state/amber/notice
regression failed before c228e96 and passes after final reconciliation.

An older test that forced another scan for identical metadata was adjusted to
request genuinely new metadata, retaining its stale-publication assertions.
The add-side race now gates the targeted read rather than requiring a full
scan; installed app version, zero amber and no-notice assertions remain intact.
No assertions were removed to obtain a pass.

### Native redesign and hosting repairs

The maintained popover is 340 points wide, hugs short content and bounds long
content to about 560 points. Only the package/results list scrolls. It uses
system typography and material, 12-point outer padding, compact rounded search,
counted/tooltipped section headers and a compact interval/next-check/icon footer.
One shared row presents kind glyph, name, status/fallback source and a separate
monospaced version column. Orange means a newer release; accent fill means
selection. Borderless row actions appear on hover or selection and are hidden
from hit testing and accessibility otherwise. Watch is a small native capsule.
Suggestions and results share keyboard selection and preserve explicit kind.
The Other disclosure respects Reduce Motion.

Custom opens the reused AppKit Settings window with the minutes field focused;
there is no popover sheet. Grouped Settings has labeled checking/Other/general
sections, switches, native interval controls, stepper/validation, inline recovery
warnings and a centered version footer. The window is 460 points wide with an
explicit 440-point content/minimum height and compact transparent titlebar.

Actual native checks found gaps hidden by separately sized offscreen content:
the owned Settings window collapsed to its footer, and the popover host published
zero preferred size despite a positive view fitting size. Tests now exercise
the actual Settings controller and maintained StatusContent host factory through
fresh hosts and appearance changes. Explicit window geometry and preferred-size
publication corrected both contracts; the live full popover and Settings were
then observed in both palettes. A separate review caught truncated recovery
copy. Shared inline warnings now size vertically; their measured height reduces
the list budget, retaining a reachable footer. A long-warning host regression
failed at 568 points before the repair and passes within 560 afterward.
Notification punctuation tests exercise actual authorization/posting errors
with absent punctuation, period, exclamation, question and trailing newline.

### Current native and visual acceptance

All native input used CUA on synthetic, separately identified bundles. This
round did not inspect or mutate owner state, cache or installed inventory,
launch the production app, change notification settings or register login items.
The earlier real-memory measurements below apply to d208d95, not this new UI
source; no new footprint measurement is claimed.

| Check | Actual observation in this round |
| --- | --- |
| Full popover and warnings | Complete header, list, footer and test-only accessory observed in Dark and Light after host sizing repair. Actual notification authorization error wraps completely, with Retry and footer visible. |
| Settings and interval | Full grouped form in both palettes. Preset 30 has its native checkmark; Custom opens separate Settings with minutes selected. Invalid 9 retains validation; valid 47 Return updates the interval. Command-W closes normally; gear reopens. Login remains Off. |
| Search, kind and pending Return | Compact suggestions without a false prefix error; Down highlights and Return watches the selected result. Explicit colliding cask resolves version `4.0-synthetic`. Delayed `synthetic-cask` Return completes as a watched cask. |
| Long results / clipboard | Arrows traverse all 22 results to the fully visible last selection and back, with input/footer reachable. Copy/paste of the first selected version gives `1.0-synthetic`. Selected absent-formula amber row copies `brew install synthetic-formula`. |
| Physical row selection and recovery | Actual pointer click selects a watch and reveals its actions; Backspace removes it; immediate Undo restores its saved amber/fallback state. This closes the earlier physical mouse-selection gate. Individually named accessibility selection and search-local Delete remain covered by prior native observations and retained regressions. |
| Quit | Each launched candidate quit through normal Command-Q. Exact-executable process checks found no production, acceptance or Settings prototype app running. |
| Still unverified | Actual status-item mug/count accessibility and same-click toggle; visible notification delivery and click; actual login approval-required branch; macOS 14 runtime. Earlier attempted routes and constraints are recorded below. Offscreen images and API success do not establish these results. |

`make -C brew_version snapshots` builds the maintained sources and synthetic
composition in fresh private OS temporary space. Offscreen NSHostingView/window
appearances are set explicitly and drawing runs under
`performAsCurrentDrawingAppearance`. Native material is supplied only at the
render boundary. Painted-pixel, width, horizontal-content, positive-viewport,
long-list and long-warning checks reject blank or collapsed captures.

All fourteen final PNGs were inspected in both appearances by the controller
and independent reviewer. Their names and logical sizes are:

| State (`-light.png` and `-dark.png`) | Points |
| --- | --- |
| `empty` | 340 × 260 |
| `watching` | 340 × 305 |
| `other-updates` | 340 × 383 |
| `search-results` | 340 × 303 |
| `suggestions` | 340 × 338 |
| `error` | 340 × 415 |
| `settings` | 460 × 388 |

The Settings render measures root content; the real owned window's 460 × 440
contract is tested and observed separately. Final images show readable recovery
guidance, correct sentence boundaries and complete rows/footer. Images remain
outside Git, mode 0600 beneath a mode-0700 temporary directory; exact paths are
provided in the completion handoff. No shell screen capture was used.

### Final automated validation for this round

All categories below passed on final executable source 13b99dd without failures,
cancellations or skips. The broad matrix ran fresh after the last source change;
source stayed unchanged throughout. Later wrap-up changes are prose only.

| Command/category | Result |
| --- | --- |
| `make -C brew_version test` | 190 Swift tests: 150 core, 11 CLI, 29 app; all 3 isolated Node release/build integration cases |
| `make -C brew_version release` | Signed CLI/app and strict signature verification |
| Signed CLI `--help`, `-h`, `--version` | Exact golden help, version `brew-version 1.0.0`, exit 0 and empty stderr for each flag |
| `make -C brew_version acceptance` | One synthetic service test and signed optimized harness |
| `make -C brew_version settings-prototype` | Signed optimized maintained Settings prototype |
| `make -C brew_version snapshots` | All 14 images, decoded-pixel and layout guards, both appearances |
| Four root installer suites from the Validation Matrix | 80 cases, including 42 Brew Version cases |
| `node --test tools/tests/check_static_deployments.test.mjs` | 17 cases |
| `zsh tools/tests/test_check_local_deployments.zsh` | Complete PASS marker |
| Market Atlas `npm test` | 423 Node tests plus 6 original browser runs: three flat-file and three isolated HTTP |
| Market Atlas `npm run test:synthetic` | 267 Node plus 78 invented compiler tests |
| Market Atlas prepared-venv full unittest discovery | 79 compiler tests including retained-input reproduction |

The exact broad commands are the same as the earlier matrix table below. All
six final external exit files contain 0; controller inspection confirmed the
counts and complete fleet marker. Existing locked Node dependencies, managed
Chromium, verified external data and prepared external compiler venv were reused.
No data acquisition, dependency/browser download, environment replacement,
online build or installed-site acceptance occurred. Private logs stay outside
Git. The wrap-up independently rechecked golden CLI bytes/empty stderr, all
four product/harness/prototype strict signatures and version declarations at
1.0.0. No installed/deployed version is claimed.

### Decisions and tradeoffs added in this round

1. Supersede fixed 300/390-point viewports with content-measured lists inside
   the 340-point popover. Cost: native measurement state and maximum-height tuning.
2. Open Custom in the retained Settings window, with field focus. Cost: a separate
   window for this edit; the old popover-sheet decision is superseded.
3. Share at most two full captures per overlapping caller group, then target
   missing metadata and reconcile after all awaits. Cost: explicit capture and
   observation ordering state to preserve exact cask semantics.
4. Keep validated catalogs/ETags in memory when disk writes fail and show the
   failure. Cost: the new cache cannot survive restart until persistence succeeds.
5. Reject usable counts below half the prior list. Cost: a legitimate large
   catalog contraction retains old data until the guard is reconsidered.
6. Suppress only a single-prefix NotFound when valid suggestions exist. Cost:
   an exact nonexistent token with longer matches initially shows suggestions.
7. Own the actual Settings viewport and popover preferred-size contract; measure
   warning height. Cost: explicit AppKit geometry and layout regressions in
   addition to standalone view rendering.
8. Clip the native bordered Watch control to the requested capsule because the
   shape modifier alone did not render it. Cost: one additional shape boundary.
9. Partition core, installer and UI source ownership among subagents and merge
   documentation centrally. Cost: coordinated commit windows and final settled
   validation. Every bug has retained regression evidence and a newest-first
   lessons entry.

## Earlier owner-feedback round (historical)

The following records describe earlier candidates and preserve their evidence.
Use the current round above for final counts, layout and native gates. Memory
figures below were measured on the stated earlier source, not remeasured here.

### Legacy cache admission repair

Ignoring the old raw/base64 envelope after whole-file Data loading and decoding
still allocated and scanned its payload. The cache now uses a valid JSON
envelope whose sorted keys start with the fixed `brew-version-catalog-v2`
marker. A 44-byte read admits this format before the remaining file is read or
decoded, using the same file descriptor throughout. Raw envelopes and earlier
unmarked schema-1 slim indexes refetch once without their ETags; saved watches
are unaffected. The nested slim index keeps its schema and validation, typed
bulk decoding, read-once actor hydration, 304 reuse and atomic pair replacement.

A real-file I/O seam makes the allocation regression observable. With the old
whole-read behavior, invented legacy envelopes read all 230 and 1,333,566 bytes
and invoked the full read once each, despite returning no cached catalog.
The corrected path rejects both during prefix admission. Additional cases
cover truncated/unknown prefixes, admitted malformed payloads, unmarked slim
refetch and typed restart hydration with ETags and memory-backed 304 reuse.
Final legacy-present cold and slim-cache warm process measurements pass the
idle target; exact results and the separate transient peak are recorded below.

Fresh validation passes all 172 Swift tests (138 core, 11 CLI, 23 app), all
three isolated release/build integration cases without skips, the signed
release and strict signatures, exact golden CLI `--help`/`-h` and version
output with empty stderr, the one-test synthetic acceptance service and signed
harness, and the signed Settings prototype. Source, built plist and CLI remain
1.0.0. The repair does not publish or deploy a release.

### Earlier acceptance and remaining release gates

All requested source corrections are committed and reviewed. Real native input
also exposed and corrected Delete routing, a collapsed Watching viewport,
ineffective appearance controls and inaccessible merged watch rows. The earlier
locked-desktop limitation and pending statements in the historical sections
below describe earlier candidates; this section records the final outcomes.

At this earlier checkpoint, actual status-button toggle/count accessibility,
physical-coordinate row selection, notification delivery/click and the minimum
macOS 14 runtime were unverified. The final visual round above closes physical
row selection; the other gates remain open. The login approval-required branch
was not needed on this host. Details of the earlier attempts follow below.

No live installation, deployment, push or merge was performed. The version
remains the unpublished initial release 1.0.0. Original saved state was restored
byte-for-byte after acceptance; the new slim cache is retained. Production and
launched temporary apps are quit, and Open at login is off.

## Owner feedback resolution

Each test name below refers to the retained complete suite. Live observations
are listed separately so source coverage is not mistaken for native acceptance.

| Item | Final change | Regression evidence |
| --- | --- | --- |
| Must 1: formula revisions | Compare upstream version first, then arbitrary-precision numeric revision; highest-keg selection shares that rule. Corrected the plan's installedForm contract. | `UpdateStatusTests.formulaRevisionFollowsUpstreamVersion`, `InstalledReaderTests.formulaKegRevisionOrdering`, including all four requested combinations. |
| Must 2: memory/cache | Persist only typed Listing indexes and ETags; decode bulk responses off-main; reuse 304 indexes; reject empty/unusable 200s. Reject old envelopes with a bounded 44-byte admission read before payload allocation/decoding. | `CatalogRegressionTests.unusableSuccessRetainsValidPair`, `bulkyIgnoredMetadataDoesNotSurviveCacheOrRevalidation`, `oldRawCacheIsIgnoredAndReplaced`; all `CatalogCacheIOTests`, especially actual byte-count/whole-read assertions. Real final footprints below. |
| Must 3: Settings/native | AppKit owns a reused Settings NSWindow and activation. Added native row responder, stable viewports, shared appearance propagation, standard Edit commands and individual accessible row selection. | `NativeActionsTests.settingsReuseRefreshAndLoginApprovalAction`, `watchRowNativeDeleteRoutesBothKeysAndPreservesSearchEditing`, `sharedWatchSelectionRenewsNativeFocusWithoutStealingSearchEditing`, `fullPopoverKeepsWatchingViewportAfterFreshHostingWithOtherHidden`, `appearanceAppliesToPopoverAndActualHostedContent`; itemized native results below. |
| Must 4: failed checks | An unreachable check leaves success time unchanged; startup awaits the network gate; reconnect retries unreachable requests; failed saves keep an interval floor. Footer and scheduler share the actual retry deadline. | `ControllerRegressionTests.unreachableDoesNotBecomeSuccessfulCheck`, `startupWaitsForNetworkAndReconnectRetriesUnreachableImmediately`, `reconnectRetriesFailureDespiteRecentSuccessfulCheck`, `rejectedSaveBacksOffAutomaticChecksButManualRetryIsImmediate`, both reconnect/save regressions and both nextAutomaticCheck regressions; `SystemEventsTests.initialOfflineAndReconnectUseControllerRetryCadence`. |
| Should 5: Unicode crash | Classification handles scanner matches outside ASCII without force-unwrapping a missing class. | `VersionOrderTests.externalUnicodeDoesNotTrap`; retained ordered-pair parity coverage. |
| Should 6: legacy casks | Admit an actual Caskroom version directory when its receipt is absent; malformed, foreign and symlink cases retain their safeguards. | `InstalledReaderTests.legacyCaskWithoutReceipt`, `legacyCaskSymlinkIsNotInstalled` and provenance cases. |
| Should 7: suggestions | Catalog suggestions load and survive independently of Other visibility, including hydrate/retry/refresh. | `WatchControllerCatalogTests.hiddenOtherUpdatesKeepsSuggestions`, `reenablingOtherUpdatesHydratesThenChecksDue`, `catalogRefreshUsesSuccessfulFetchCadence`; native Other-off observations below. |
| Should 8: main-thread/no-op work | Retain one off-main installed snapshot, reject stale generations and preserve caller cask metadata; unrelated commits reuse results and unchanged state does not save. | `ControllerRegressionTests.noOpCloseAndSettingsDoNotWrite`; `InstallationSnapshotTests.otherUpdatesAdmitsEachReceiptOnce`, `blockedScanLeavesMainActorResponsiveAndUnrelatedCommitsDoNotScan`, stale-publication/concurrent-cache/caller-metadata regressions. |
| Should 9: cross-volume update | Displace live app inside apps-directory staging; durable backup can be on another volume. | Installer `update succeeds when backup and apps are on different simulated devices`, plus genuine activation-move failure recovery. |
| Should 10: recovery copy | Re-read and validate app, command, receipt and metadata before activation; print backup first; preserve primary, restoration and all cleanup errors with recovery path. | Eight backup payload corruption/failure cases, deploy/rollback compound recovery cases and six cleanup regressions in `deploy_brew_version.test.mjs`. |
| Should 11: relaunch notice | Guidance follows actual replacement, including rollback, and is absent on already-current. Process override is explicitly `BREW_VERSION_DEPLOY_TEST_ONLY_PGREP`. | Installer `running app notice follows replacement and rollback but not already-current deployment`. |
| Should 12: fleet inventory | Golden help is required before Brew Version native audit. | `test_native_brew_version_deployment` commits a synthetic inventory without golden help and requires source-inventory-unverified output. |
| Should 13: docs/build | Root prerequisites surfaced; acceptance required and OS-temporary; removed obsolete OS/prose claims; release clears stale resources and publishes executables via temporary sibling plus rename. Lessons are newest first, including moved October 16 entries. | Three `Tests/ReleaseChecks/release.test.mjs` real-build cases check stale signed resources, held executable descriptors and both private harness homes; documentation inspection. |
| Smaller 1: recovery hint | Hint is limited to an actual failed save, distinct from quarantine recovery/load failures. | `ControllerRegressionTests.recoveryWarningIsDistinctFromFailedSave`, `NativeActionsTests.nativeActionPolicies`. |
| Smaller 2: notifications | Permission and posting failures are observable in popover/Settings; explicit retry retains the latest failed notice. | `NativeActionsTests.notificationDenialErrorAndPostingRetryAreObservable`; actual visible authorization error and real production consent prompt below. |
| Smaller 3: search | Debounce 300 ms, retain rows during wait/transport; pending Return awaits the current text/kind intent and rejects stale intent. | `SearchInputTests.debounceRetainsResultsAndReturnWaitsForCurrentIntent`, `inFlightLookupRetainsPreviousRows`, `editingAfterReturnExcludesStaleSubmission`; actual delayed Return below. |
| Smaller 4: homepage | Both action availability and execution require an absolute http/https URL with host. | `NativeActionsTests.homepageActionRejectsUnsafeSchemes`. |
| Smaller 5: fallback note | Shared installed-source note appears in watched, search and Other rows. | `NativeActionsTests.nativeActionPolicies`; actual Other Watch and watched fallback note below. |
| Smaller 6: login status | Refresh on Settings key-window callback; approval-required state exposes the normal system Login Items action. | `NativeActionsTests.settingsReuseRefreshAndLoginApprovalAction`; actual register/unregister below. |
| Smaller 7: listing cache | Removal evicts conditional entries; search is not persisted; saves prune to watched identities; old suspended work cannot resurrect an entry after Undo. | `ControllerRegressionTests.removedAndSearchedListingsStayOutOfPersistedWatchCache`, `removalEvictsConditionalCacheBeforeReadding`; `InstallationSnapshotTests.removedAndRestoredWatchCannotRegainCacheFromSuspendedCheck`. |
| Smaller 8: status accessibility | Observed watched-update count drives the status symbol, label/help and tooltip, including zero/one/many wording. | `NativeActionsTests.statusObservationPublishesAmberChanges`, `nativeActionPolicies`; actual status-item accessibility remains unverified. |

## Real release memory acceptance

Measured the final signed release from commit d208d95 with an empty watched
list and the actual public catalog. The original 68,121,629-byte raw cache was
left in place before the cold launch; it was not removed to improve the result.
Both measurements used `footprint -f bytes --noCategories <pid>` at CPU 0.0%.
All diagnostics and original state backups stay outside the public checkout.

| Launch | Idle phys_footprint | Peak phys_footprint | Cache |
| --- | ---: | ---: | --- |
| Cold, legacy cache present, fresh catalog fetched | 47,989,888 bytes (45.77 MiB) | 225,543,344 bytes | Replaced by marked slim index, 3,397,362 bytes |
| Second launch from that slim cache | 73,221,152 bytes (69.83 MiB) | 73,401,376 bytes | Same bytes and modification time; no bulk replacement |

Both idle values meet the well-under-150-MB target. The cold download/decoding
peak is reported separately and is not an idle result. The preceding candidate
failed at 250,021,088 bytes idle when it decoded the legacy envelope before
rejecting it; the bounded preflight repair and real-file regression close that
specific failure. An earlier low-memory cold diagnostic that removed the old
cache is not used as acceptance evidence.

After normal native Quit, the original state was copied back atomically and
`cmp` confirmed identical bytes. The runtime folder is mode 0700 and state file
0600. The new cache remains for the next launch. Private temporary test watches
and fabricated previous-release baselines are absent from the restored state.

## Earlier native acceptance observations

All native input used the supported CUA interface on the unlocked current Mac.
The final cache-only repair does not change UI sources. UI observations below
use the corrected signed harness at f8faa40, with final production Settings,
focus, version and Quit repeated at d208d95. Earlier failed candidates are
described in historical sections only.

| Required check | Observed result |
| --- | --- |
| Settings gear, activation/front, close/reopen | PASS on final production: gear opens Settings 1.0.0; normal reopen while Settings is open exposes the popover, gear brings Settings forward; close returns to focused popover; gear reopens Settings. Automated identity test separately proves the same NSWindow is retained. Actual status-button usability is not established. |
| Search focus | PASS on first visible open and normal reopen; closing Settings returns to focused search. Production initial launch remains quiet. |
| Search arrows, Return, Command-C | PASS: native Return watches the selected synthetic result; Command-C copied its version, verified by paste. Arrow navigation traversed 22 query results to both ends; input/footer controls remained reachable. |
| Pending Return and explicit cask choice | PASS: a deliberately delayed lookup accepted Return for the current intent after completion. Explicit colliding cask suggestion watched the cask version rather than the formula version. |
| Selected-row Delete and Undo | PASS through each named accessibility group's normal selection action: selected state/native row focus observed; both Backspace and forward Delete removed the row, Undo restored its saved amber/fallback state. Search Backspace edited the query without removing a watch. Physical coordinate selection was unverified at this checkpoint: CUA returned `-10005 noWindowsAvailable` despite available AX/screenshot, after refreshed bindings, Settings round trip and both screenshot coordinate scales. The final visual round above subsequently verifies the actual pointer gesture. |
| Long results / Watching viewport | PASS for arrow scrolling to both ends and accessible input/footer controls. After hiding Other and reopening, watched rows remained visible in the corrected 390-point viewport. A cropped long-result capture does not establish every physical pixel of every row. |
| Interval menu and Custom sheet | PASS: native current-interval checkmarks observed for preset 30 and custom 47; menu remained open without dismissing popover. Invalid 9 retained editable text and validation; valid Save and Cancel returned to the open popover with the expected value. |
| Other visibility / Watch / fallback | PASS: Other off retained six suggestions; Other Watch added the synthetic fallback cask with the same visible source note and amber state in Watching. |
| Light / Dark and editing | PASS: actual harness Light/Dark palettes changed after the appearance fix. Native Command-Z/Shift-Command-Z undo/redo query text. |
| Notification permission and errors | PASS: final production context exposed the normal consent prompt and Allow was chosen. System Settings confirmed Allow on. Synthetic authorization failure was visible in both views. Deterministic authorization/post/retry tests pass; actual visible delivery and click remain unverified. |
| Notification delivery/click | UNVERIFIED: a controlled fabricated prior-release baseline triggered a real check/update, without a posting error, but no visible notification-center window/banner was observable in either foreground or background attempts. Temporary and Persistent alert styles were tried; original Temporary restored. Normal Notification Center access timed out; Fn-N was unsupported (`keyNotFound("fn")`). No Focus/sharing changes, notification-database reset, signing/location changes or alternate UI automation were used. API acceptance is not delivery/click proof, and no cause is asserted. |
| Open at login | PASS for actual harness register → Enabled → Off; no approval was required. Final production and harness Settings showed Off. Key-refresh/approval button behavior is covered by injected service tests; actual requiresApproval state and its OS action remain unverified on this host. |
| Status mug/count/accessibility and same-click close | UNVERIFIED: own-app AX exposed application/Edit menus but no status button. SystemUIServer timed out (`-10005 timeoutReached`), including after normal keyboard status-area focus. No hidden input hooks or alternate UI technology were used. Source/policy/observation tests pass; these do not prove native status interaction. |
| Quit / cleanup | PASS: normal Command-Q and read-only exact-executable process absence checks. Open at login off; original saved state restored; authorized notification permission remains enabled; alert style restored and System Settings returned to its original General panel. |
| macOS 14 | UNVERIFIED: no minimum-supported-runtime host is available. Build deployment target and signatures do not establish runtime acceptance. |

The remaining gates need native access that can address the actual status item,
observe delivered notifications and run on macOS 14. Repeated inaccessible UI
probes do not establish a pass. The branch is retained for review; no merge or
deployment decision is implied by passing source and automated checks.

## Earlier automated validation

Final executable source is d208d95; subsequent edits update only this record
and README acceptance wording. Complete Brew Version validation ran on that
source with no test failures or skips:

| Command/category | Result |
| --- | --- |
| `make -C brew_version test` | 172 Swift tests: 138 core, 11 CLI, 23 app; all 3 isolated real release/build integration cases pass |
| `make -C brew_version release` | Both products build, sign and pass strict signature verification |
| Signed `--help`, `-h`, `--version` | Golden help bytes match; version is `brew-version 1.0.0`; every flag exits 0 with empty stderr |
| `make -C brew_version acceptance` | One synthetic service test and optimized signed harness pass |
| `make -C brew_version settings-prototype` | Optimized signed maintained Settings prototype passes |

Controller rechecked both strict signatures, all three CLI flags and source/
built version declarations after the real memory/native run. Source constant,
source plist, release plist, CLI and observed Settings all agree at 1.0.0.
No live installed/deployed version is claimed. No automated assertion was
weakened, coverage removed or retained acceptance replaced with invented data.

After the final source repair, all six broad matrix commands were run again
fresh, each exiting 0 with no failures or skips:

| Working directory / command | Result |
| --- | --- |
| Root: `node --test tools/tests/deploy_storage_monitor.test.mjs tools/tests/deploy_colophon.test.mjs tools/tests/deploy_brew_version.test.mjs tools/tests/deploy_calculator_pages.test.mjs` | All 77 installer tests pass, including 39 Brew Version cases |
| Root: `node --test tools/tests/check_static_deployments.test.mjs` | All 17 static-audit tests pass |
| Root: `zsh tools/tests/test_check_local_deployments.zsh` | `check_local_deployments tests: PASS` |
| `Calculation tools/backtest`: `npm test` | All 423 Node tests and all three original browser scenarios at both flat-file and isolated HTTP targets pass: six browser runs |
| `Calculation tools/backtest`: `npm run test:synthetic` | All 267 Node tests and 78 invented compiler tests pass |
| `Calculation tools/backtest`: `PYTHONDONTWRITEBYTECODE=1 "$MARKET_ATLAS_TEST_PYTHON" -B -m unittest discover -s data -p 'test_*.py' -v` | All 79 compiler tests pass, including retained-input reproduction |

Market Atlas reused the existing locked Node dependencies, managed Chromium,
verified external data and prepared external compiler venv. Both npm drivers
used that same venv and disabled bytecode. No acquisition, dependency/browser
download, environment replacement, online build or installed-site acceptance
occurred. Data-bearing logs remain in private mode-0700 OS temporary space.

## Decisions to preserve

1. Use the plan's exact feature branch in the existing checkout; preserve the supplied plan in its own initial documentation commit. Cost: branch can be renamed; one extra documentation commit.
2. Keep the upstream BSD notice with the comparator port and signed bundle. Cost: an extra notice resource and packaging copy.
3. Preserve the running SwiftPM helper's absolute executable and bundle arguments for the isolated-PATH test. Cost: another toolchain may require adapting only this test launcher.
4. Preserve legacy eager option handling, interval replacement semantics and duplicate argument positions. The added release flag follows eager help handling.
5. Preserve pinned Homebrew ordering, including asymmetry; select tied folders deterministically. A real cask latest directory is admitted, while version-directory symlinks are excluded; valid formula opt links still select their keg. Independent ordered-pair fixtures caught the post-token first-number bug.
6. Keep uninstalled acknowledgement separate from notification deduplication. Cost if wrong: confusing repeated-poll/acknowledgement behavior.
7. Restore allocates a new generation; results requested before removal cannot mutate the restored entry. Cost: refreshed listing may wait for the next check.
8. Merge into committed state after the final await and save without suspension before publishing/notifying. Cost if wrong: concurrent user actions could be erased.
9. Ignore retryLoad during an active add/check. Cost: retry may need repeating after active work finishes.
10. Keep quarantine recovery warning until valid reload or successful save. Cost: warning can remain visible longer.
11. Persist an explicit failed watch request as an error row; first later success still baselines silently. Cost: direct callers can leave a misspelled watch until removal.
12. Reject inconsistent nested saved values and listing/name mismatches. Cost: incompatible manual edits are quarantined rather than partly admitted.
13. Use a narrow internal I/O seam for failure tests. Cost: a new failure category may require another seam; no production simulation switch exists.
14. Make hydrateCatalog async so cache I/O/decoding is off MainActor and startup can await content. This changes the plan's synchronous signature. Cost: callers must await hydration.
15. Atomically cache both slim Listing indexes and ETags in a versioned envelope. Ignore the legacy raw/base64 format. Cost: the first launch with an old cache fetches fresh lists; no external cache consumer exists.
16. Use one four-request permit pool across checks, additions and search. Cost: large searches may queue behind checks; cancelled queued work drops before transport.
17. **Superseded by decision 32.** The original implementation retained SwiftUI SettingsLink pending runtime evidence. The owner subsequently required explicit AppKit window ownership independent of scene context.
18. Failed Undo suspends normal expiry and blocks replacement removals until successful retry; same-name Watch restores the saved entry. Cost: another Stop watching action waits for recovery. Ordinary Undo still expires after five seconds.
19. Preserve an explicitly selected suggestion's kind in transient `SearchInput`, including task identity when text is unchanged. Editing clears it; an existing watch's known kind takes precedence. Saved watches remain name-only identities. Cost: a colliding package of the other kind must be unwatched before switching kinds.
20. **Superseded by the final visual round.** Use a fixed 300-point search viewport for suggestions and results, with input/footer outside and selection-following scrolling. Cost: short queries retain blank viewport space.
21. Expose interval bounds once in `CheckInterval` and format the validation copy from them using the current locale. Cost: grouping follows system locale rather than always using English punctuation.
22. Reject any stderr from signed CLI diagnostics for all three help/version flags, at build and activation. Cost: a future intentional CLI warning must be considered explicitly before changing this contract.
23. Use the normal interval retry floor after transport or persistence failure. Reconnect bypasses transport backoff but preserves failed-save backoff. Cost: a reconnected machine with a save failure waits until that interval floor or a manual retry.
24. Keep a Quit footer action for a Dock-less temporary app. Harness-only appearance and synthetic service injection remain outside production composition. Cost: extra footer width and a separately built acceptance entry point.
25. Encode installer app-tree identity with sorted paths, entry types, full modes and content hashes, including directories/root. Derive expected version and golden help from admitted tracked inputs. Cost: metadata-only mode changes require a matching release; these checks establish identity, not compiler reproducibility.
26. Displace the live bundle inside apps-directory staging; retain the separately copied durable backup until recovery is no longer needed. Cost: both temporary staging and a retained backup consume space during activation.
27. Validate every saved backup payload against captured source identities and publish the path before activation. Preserve both errors if recovery fails. Cost: another complete app-tree read and more explicit operator recovery evidence.
28. Print running-app relaunch guidance only after replacement, including explicit rollback. Name the process-detector override BREW_VERSION_DEPLOY_TEST_ONLY_PGREP. Cost: tests must use the explicit override name.
29. Add standalone Node release integration checks after Swift Testing, building only in private OS temporary space and invoking release rather than test. Hold old executable descriptors and rebuild signed stale bundles. Cost: two isolated release builds plus synthetic acceptance/prototype builds per full test run.
30. Make synthetic acceptance a required category and use plain mktemp -d for both harnesses. Require golden help at the fleet inventory boundary too. Cost: operators clean up the printed temporary homes after native acceptance.
31. Collect cleanup failures through the installer operation boundary, including staging, restoration and shared atomic-file publication. Attempt all remaining cleanup, then report primary errors, every failed path and the durable backup. A completed deploy or rollback with cleanup failure retains the selected release and exits 1 with an explicit completion message. Cost: failed scratch paths remain for operator cleanup and an otherwise valid deployment still needs attention.

32. AppKit owns application lifecycle and a retained Settings window hosting the maintained SettingsView. Gear activation, key-window login refresh and reuse after closing are explicit. The synthetic prototype uses that exact controller. Cost: the app owns window lifetime instead of a SwiftUI Settings scene.
33. Production initial launch stays quiet, including at login; a normal user reopen shows its popover and renews search focus. Only the synthetic harness/prototype present their maintained UI at launch. No hidden automation flag or global shortcut exists. Cost: native tools must use the normal reopen route to inspect a windowless running release. AppKit composition explicitly retains standard Quit/Edit commands previously supplied by SwiftUI App.
34. Keep transient popover semantics, but veto status-button transient dismissal and let the button's explicit close own the toggle. Native menus/panels are excluded by AppKit's transient contract; sheets retain their child-window lifetime. Cost: final native timing still requires actual input acceptance.
35. Debounce current search intent for 300 ms while retaining existing rows. Return awaits that same request and rejects it if text/kind changes. Cost: the old rows remain visible during the pending query; a pending Return does not act on them.
36. Observe separate notification authorization and posting failures, retain the failed notice for an explicit retry, and expose actionable errors in both views. Inject only the system API boundary. The harness can fail one post at this boundary; its default permission, delivery and click path still uses the real system center. Cost: retry re-delivers the latest failed notice after permission/service recovery.
37. Refresh login status when Settings becomes key and offer the system Login Items panel for requiresApproval. Keep registration errors as observed API results; do not infer signing limitations. Cost: a narrow service adapter is maintained for deterministic tests.
38. Use native Picker tags for interval selection, including a custom current value; preserve invalid custom text after a failed save. The final visual round moves this edit from a sheet to the retained Settings window. Cost: custom current values add one temporary option to the menu.
39. Render the same installed-source note in watched, search and Other rows; gate homepage availability and execution to absolute http/https URLs. Cost: nonweb homepage values have no action.
40. Start production scheduling offline, await every path update in the controller, and reserve periodic/wake events for scheduledTick. The controller alone owns the reconnect tick and retry floor. Cost: automatic network work waits for the monitor's initial answer; disk hydration can proceed immediately.
41. Continue the required memory repair after the final source-review wave when the real legacy-present cold measurement fails. Add bounded format admission before reading/decoding, using the same file descriptor. Cost: one further commit/review/runtime measurement and a one-time unconditional refetch for raw and earlier unmarked slim caches.
42. Replace SwiftUI-only watch-row key handling with a row-owned native first responder after actual input showed a focus ring without Delete. It handles both hardware delete keys and standard delete commands without intercepting mouse hits or installing a global monitor. Cost: a small native responder bridge and renewed focus identity per selection.
43. **Superseded by the final visual round.** Give Watching an explicit 390-point viewport after native reproduction of its collapse with Other hidden; keep the footer outside. Cost: short/empty watch lists retain blank space.
44. Give each watch an individually named accessibility group/default selection action, sharing the same renewed focus path as mouse input and preserving child actions. Cost: changed VoiceOver grouping and announcement order; actual named selection/Delete were inspected independently of offscreen tests.
45. Present Next check from the scheduler's shared attempt/success/failed-save deadline rather than a separate last-success formula. Cost: footer wording now exposes offline and failed-save retry timing rather than a simple success-time estimate.

The owner-required slim-cache, formula PkgVersion and legacy-cask receipt decisions
supersede the original plan's raw cache/combined-version/receipt-only assumptions.
Their implementation and regressions are recorded in the catalog follow-up below;
Task 11 consumes those APIs without restoring the superseded behavior.

## Historical validation record

The counts and review statements below describe their individual earlier waves;
they are not current Task 10 validation or final whole-branch review evidence.

The implementation task reviews, whole-branch review and scoped review of all
four final fixes are complete. All four findings are addressed, with no new
breakage identified. Native runtime acceptance remains outstanding.

| Validation | Result |
| --- | --- |
| Complete Swift suite | 121 tests pass: 104 core, 11 CLI, 6 app |
| Release build and strict signatures | Pass for command and app; source, built plist and CLI version agree |
| Synthetic acceptance service / signed harness / Settings prototype | Pass for service test and builds; no GUI launch |
| All native/calculator installer suites | 59 tests pass, including 21 Brew Version cases |
| Static audit / complete fleet suite | 17 static tests pass; fleet reports PASS |
| Market Atlas complete suite | 423 Node tests and all six original browser runs pass |
| Market Atlas synthetic suite | 267 Node tests and 78 compiler tests pass |
| Full compiler discovery | 79 tests pass, including retained-input reproduction |

Market Atlas used the owner's already prepared external data and compiler environment. Its complete results precede the final native app/installer fixes, which did not change its code or the shared audit runner. No data acquisition, dependency/browser download, environment replacement or installed-site acceptance was performed. Data-bearing evidence remains outside the checkout.

## Final review fix wave

All four accepted final-review findings are implemented and the scoped
re-review is clean. Suggestion kind now survives lookup and Watch, multi-name search has
a bounded scrolling region, interval validation copy derives from domain bounds,
and CLI activation rejects unexpected stderr.

Regression evidence: removing explicit kind propagation resolves and watches the
synthetic shared token as a formula instead of a cask. Removing the production
search viewport produces 5,294-point offscreen content for 100 results instead
of 300 points. Query-generation, cancellation and known-watch-kind regressions
remain in the complete suite. Interval tests exercise bounds and US/German
grouping. Six signed synthetic executable cases reject stderr from all three
flags at build and activation and preserve prior artifacts and recovery copies.
The transient action checks cancellation before both lookup and empty-query
clearing; a cancelled empty task cannot erase a newer result.

The initial offscreen whole-section probe measured cleared content because its
query task restarted on hosting. The maintained `SearchResults` presentation is
now tested directly with all 100 rows present, without starting that task.
This establishes layout only. Native acceptance now explicitly includes a large
multi-token query, arrow scrolling, reachable input/footer and Return/Command-C.
The locked-desktop and unavailable macOS 14 gates remain unmet.

Fresh automated validation for the fix wave (no skips): 121 Swift tests
(104 core, 11 CLI, 6 app), 59 combined native/calculator installer tests and
17 static-audit tests pass. Release build and strict signatures, the one-test
synthetic acceptance service and signed harness, signed Settings prototype,
and offline CLI help/version smoke checks pass. Source plist, release plist
and CLI report the same initial release version. The complete fleet suite
reports PASS. The installer-only change does not alter the shared
static audit or its child runner, so Market Atlas's previously recorded complete
results were not rerun or presented as fresh results for this wave.

## Installer recovery choice

The earlier implementation retained a copy of the old app but did not validate
the copied tree before activation. Task 10 now re-reads and validates the app,
command, receipt and metadata against captured source identities before live
mutation. It prints the recovery backup first. Displace the old live bundle
inside the apps-directory staging folder so its move stays on the same device;
the durable backup may live on another device. Retain that verified copy through
activation and report both activation and restoration errors plus its path if
recovery fails. The cost is extra disk I/O and a retained backup per attempt.

## Catalog and scheduling follow-up

The cache now persists schema-1 slim Listing indexes with each list's ETag.
`CatalogClient` is an actor: `cached()` requires `await`, disk hydration runs once
per client, and 304 reuses decoded indexes. Bulk and individual API responses
share typed Listing field decoding; ignored API metadata is not retained.
Empty or unusable successful lists preserve the previous pair. The synthetic
acceptance service now supplies a usable cask list instead of treating `[]` as
a valid successful catalog.

Other updates visibility no longer controls catalog suggestions. Installation
snapshots and update derivation run off-main with stale-generation rejection;
watch filtering uses the retained derived list. Each rack is admitted once,
including the previously corrected legacy-cask and formula-revision behavior.
Unchanged state does not save. Conditional listing persistence is pruned to
watched names, and removal replaces the cache boundary so suspended old work
cannot reintroduce a removed watch's ETag after Undo.

The controller exposes `PersistenceIssue` separately from its message. Recovery
warnings, blocked loads and failed saves have distinct values. Its new
`networkAvailable` initializer argument and async `setNetworkAvailable(_:)`
support startup gating and immediate unreachable-check retries on reconnect,
while failed saves retain an automatic interval floor. App/SystemEvents and
retry-hint UI wiring is part of the following native-UI task.

Fresh validation: 144 Swift tests pass (127 core, 11 CLI, 6 app), the signed
release and strict signatures pass, CLI help matches the golden fixture with
empty stderr, and source/built plist/CLI versions agree at 1.0.0. The synthetic
acceptance service's one test and signed harness build pass. No GUI was launched
for this core task; release footprint and native acceptance are separate gates.

Scoped review found two asynchronous consumer gaps in that follow-up. A rejected
installation capture could still reach watch evaluation, and an earlier cache
snapshot could overwrite a concurrent addition. Superseded captures now retry
before returning; watch/search publication reads the accepted installed snapshot
after its final await. Checks capture conditional cache entries after the
installation await and retain the cache-identity guard. Controlled regressions
assert actual saved installed versions, amber state, notices and both saved
ETags. Fresh fix-round validation passes 146 Swift tests (129 core, 11 CLI,
6 app), release/signature and CLI checks, and the one-test synthetic acceptance
service plus signed harness build. Native and final footprint gates remain
separate from this fix round.

A second scoped review found that a newer shared installation snapshot may lack
a pending caller's cask auto-update/app-artifact metadata. The final cache await
allowed that substitution to persist Caskroom version 1 instead of app-bundle
version 2. Add and check now retain their exact accepted caller-metadata snapshot
through commit without further suspension. `ListingCache.snapshot()` is a
nonisolated synchronous value copy from small private NSLock-protected storage;
get/store remain actor-bound, and no mutable storage escapes the lock. The
internal cache dependency seam enables controlled actor-executor regression
without a production simulation mode. Both real synthetic cask variants and
concurrent stores/snapshots pass alongside all earlier race regressions.
Fresh validation passes 148 Swift tests (131 core, 11 CLI, 6 app), release and
signature checks, CLI output/stderr checks, and synthetic acceptance service and
signed harness build. Source, built plist and CLI remain 1.0.0; this core round
does not publish a release or establish new native/footprint acceptance.

## Installer and build follow-up validation

Task 10 addresses review items Should 9–13. The backup/device/recovery choices
above are exercised by signed synthetic lifecycle tests: a device-boundary
EXDEV update succeeds, genuine activation failure restores the old release,
corruption or failure of any backup payload leaves live artifacts untouched,
and failed restoration preserves both errors and the recovery path. Running-app
guidance covers replacement, already-current and explicit rollback paths.
The fleet now rejects a committed source inventory missing golden help before
running the native child audit.

The release target clears the bounded old app bundle, then copies each
executable to a unique temporary sibling before renaming. The full test target
adds three isolated Node integration checks for stale signed resources, held
executable inodes/bytes, and private OS-temporary acceptance/prototype homes.
No production UI source changed in this task.

Fresh Task 10 automated results, without skips:

| Validation | Result |
| --- | --- |
| Complete Swift suite | 148 pass: 131 core, 11 CLI, 6 app |
| Release build integration | 3 pass, including both synthetic harness builders |
| Release / strict signatures / offline CLI | Pass; golden help and version have empty stderr |
| Synthetic acceptance / Settings prototype | 1 service test passes; both signed builds pass; no GUI launch |
| Four native/calculator installer suites | 71 pass, including 33 Brew Version cases |
| Static audit / complete fleet suite | 17 pass / PASS |
| Market Atlas complete | 423 Node tests and all six original browser runs pass |
| Market Atlas synthetic / full compiler | 267 Node + 78 compiler / 79 compiler pass |

Source plist, release plist and CLI agree at 1.0.0. This task did not deploy or
publish a release. Market Atlas used only the prepared external data, locked
Node dependencies, managed Chromium and prepared compiler venv, with bytecode
disabled. No data, dependency or browser acquisition occurred. Data-bearing
logs stay in a fresh mode-0700 OS temporary directory outside the checkout.
Native UI interactions and final cold/cache memory measurements remain
controller-owned acceptance after the following UI task.

### Cleanup recovery review follow-up

Cleanup in an installer finally block could replace activation/restoration
errors and skip the remaining cleanup. Six signed synthetic regressions were
RED before the fix: compound deploy and rollback failures, completed deploy
and rollback with cleanup-only failure, failed app staging copy, and atomic
publication with failed staging cleanup. Cleanup now accumulates through the
operation boundary, including shared `atomicFile`, which serves every native
installer. Every owned cleanup is attempted, and the final error retains the
primary failures, each failed cleanup path and the durable backup path.

Cleanup-only failure after completed deploy or rollback keeps the selected
release active, returns status 1, and reports that activation completed. It
does not undo successful rollback merely because removing its staging folder
failed. A strengthened atomic-publication regression also requires the backup
path after successful restoration; the operation boundary supplies it.

Fresh full follow-up validation passes without skips: 148 Swift tests and
3 release integration tests, signed release and CLI help/version checks, the
one-test synthetic acceptance service and both signed harness builds,
77 combined installer tests (39 Brew Version), 17 static tests and the complete
fleet suite. Market Atlas passes 423 Node tests and six original browser runs,
267 synthetic Node plus 78 compiler tests, and all 79 full compiler tests.
Prepared external data, locked Node dependencies, managed Chromium and the
prepared venv were reused without acquisition or environment changes. Source,
release plist and CLI remain 1.0.0. No GUI, live deployment or final memory
acceptance was performed by this follow-up.

## Native interaction source follow-up

Task 11 implements the AppKit-owned reused Settings route, editing focus for
watched rows, per-open search focus and status-button transient-dismissal
ownership. The interval menu uses actual Picker selection, including custom
current values; invalid or failed-save custom input remains available. Search
retains results through a 300 ms debounce and transport, with Return awaiting
its current text/kind intent. Changing intent rejects that pending submission.

Notification authorization/denial/post errors are observable in both views and
can retry the latest failed notice. Login status refreshes on Settings key-window
callbacks, with an approval-settings action. Homepage actions admit only absolute
http/https URLs at execution; all installed rows share the fallback note. Status
accessibility tracks the observed watched-update count. Production starts network
scheduling offline and forwards every path update to the controller's awaited
network setter; startup hydrates disk without an extra ungated tick.

Fresh automated validation passes 160 Swift tests (131 core, 11 CLI, 18 app),
all three isolated release/build integration cases, signed release and strict
signature verification, exact golden CLI help and version with empty stderr,
the one-test synthetic acceptance service and signed harness, and the signed
Settings prototype. Source plist, release plist and CLI agree at 1.0.0. No
release was published or deployed. The full synthetic harness initially presents
the maintained popover; the prototype opens the exact maintained AppKit Settings
window. Offscreen window/action tests use injected presentation and OS service
boundaries, so they do not establish native activation, input or registration.

Current-system native checks and final cold/cache memory measurements remain
pending for controller-owned CUA acceptance after scoped review. No GUI was
launched for this source task, and no earlier diagnostic footprint is presented
as final acceptance. The README lists every required native observation; the
minimum supported runtime remains unavailable.

## Native routing review follow-up

Scoped review found that the replacement AppKit Edit menu omitted standard text
Undo/Redo. Both now use nil-target responder-chain commands with Command-Z and
Shift-Command-Z; regression coverage checks selectors, modifiers and routing.
Controlled search-test gates now have cancellation-aware monotonic deadlines and
release pending continuations on early exit; their no-signal timeout branches
are tested without dropping the original search behavior assertions.

Controller-owned native input on the preceding candidate showed a selected watch
row's editing focus ring but no removal after either delete key. This supersedes
the assumption that SwiftUI editing focus plus onKeyPress established Delete
routing. A row-owned native view now takes first-responder ownership on that
row's click, handles Backspace/forward Delete and standard delete commands,
and routes removal through the existing saved-state Undo action. It never
intercepts mouse hits or installs an app-wide key monitor; rebuilt rows do not
replay old focus requests. Offscreen native-event/responder-switching tests
verify persisted removal, Undo and search-text Delete safety. The live click/key
gesture still requires a repeat against the corrected candidate.

The same native run confirmed a collapsed Watching viewport with Other updates
off, and ineffective harness Light controls. A full maintained-popover regression
reproduced the zero-height scroll under fresh hosting; the Watching viewport now
has an explicit 390-point height with its footer outside. Short lists retain
blank viewport space. Harness appearance actions now set the actual popover,
hosted content/current window and current/future Settings appearance; native
effective-appearance tests cover both palettes. Live visibility and appearance
checks must also be repeated against this corrected candidate.

Fresh complete validation of all five corrections passes 164 Swift tests
(131 core, 11 CLI, 22 app), all three isolated release/build cases, release and
strict signatures, golden CLI help/version with empty stderr, the one-test
synthetic acceptance service and signed harness, and the signed Settings
prototype. Source, release plist and CLI remain 1.0.0. No automated category
has a remaining failure or skip. No GUI was launched for this source round;
actual native results and final release footprints remain controller-owned.

## Scheduler footer and accessible row follow-up

The footer previously derived Next check only from the last successful check.
After an unreachable scheduled attempt it could show the already elapsed
deadline, and a first failed save could hide the retry time. The controller now
exposes `nextAutomaticCheck` from the same `watchCheckDeadline` used by the
automatic watch gate. It includes attempt and failed-save floors, and previews
the actual reconnect policy while offline. Reconnect bypasses transport delay
but retains persistence delay; retry cadence itself is unchanged. Fake-clock
regressions assert explicit deadlines and actual request counts after first
failures, failures following success, reconnect and subsequent success.

Controller-owned native inspection found Watching's heading and both row texts
merged into one accessible text target, so assistive input could not select a
specific watch. Each row now contains its existing children in a named
`Watching NAME` accessibility group, exposes selected state and offers a default
selection action. Mouse and accessibility actions share `WatchRowSelection.select`
and a fresh native focus request; Delete still uses the row-local responder and
existing persistence/Undo path. The regression verifies renewed focus, saved
removal/Undo, search-local Delete and no stale request replay after row rebuilds.
Named live groups and their retained child actions still need actual AX-tree
verification: an offscreen SwiftUI host did not materialize that live tree, so
the automated responder result does not claim accessibility or mouse acceptance.

The first-launch quiet behavior and fixed 390-point Watching / 300-point search
viewports remain. The controller owns final native selection/Delete checks and
cold/cache release footprints; the minimum supported runtime remains unavailable.

Fresh validation passes 167 Swift tests (133 core, 11 CLI, 23 app), all three
isolated release/build integration cases with no skips, signed release/strict
signatures, exact golden `--help` and `-h`, and `--version` with empty stderr for
all flags. Source and release plists and CLI agree at 1.0.0. The synthetic service
test and signed harness, and the signed maintained Settings prototype, pass.
This source wave did not deploy or publish a release. No shared installer/audit
or Market Atlas consumer changed, so their preceding complete results remain
historical evidence and were not redundantly rerun.
