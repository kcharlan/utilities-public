# Brew Version

Brew Version reads current formula and cask versions from Homebrew's public API
and packages in your taps from their GitHub repositories.
The Swift `brew-version` command supports one-time lookups and watching until a
version changes. The shared core also supports the native menu bar app,
which watches chosen packages and notifies about their updates without running
`brew` or upgrading packages.

This native macOS app is a deliberate exception to the UI Shapes defaults in
the repository's `agents.md`.

## Requirements

- macOS 27 or newer. Releases target the current major version;
  compatibility with earlier macOS versions is not promised.
- Xcode or the Command Line Tools providing Swift 6 and the macOS 27 SDK.
- Node.js for deployment tooling and release build integration tests.
- Network access to Homebrew's HTTPS public API and `raw.githubusercontent.com` for tap lookups.

The Swift package has no external dependencies. The CLI needs neither `curl`
nor `jq`. The app bundle is named `Brew Version.app`, uses the
`local.utilities.brew-version` bundle identifier and `BrewVersion` executable,
and is a menu bar app without a Dock icon. The app is not sandboxed because it
reads Homebrew installation folders and application bundles. The release
target packages and signs both products; deployment uses the repository
installer.

## Build and test

From the repository root:

```sh
make -C brew_version build
make -C brew_version test
```

The test target runs the complete Swift Testing suite, including transport,
lookup, CLI parsing, output, timestamps, and watch behavior, followed by the
Node release build integration tests. Those tests build twice in private OS
temporary space, check that stale signed resources disappear, and hold old
executable file descriptors to verify their inodes and bytes survive a rebuild.
They invoke release directly rather than recursively invoking the test target.
They also check that the release plist, both Mach-O products and the snapshot
builder require the supported macOS 27 runtime.
The integration category also runs the acceptance and Settings prototype
builders with an invented HOME, requiring their printed private homes to be
mode-0700 children of their `TMPDIR` that keep only the signed bundle, and
checks that a failed builder removes its whole home.
`make test` runs the suite under the repository's shared
[`tools/check_no_temp_leaks.sh`](../tools/check_no_temp_leaks.sh), with `TMPDIR`
in a private run directory inside the ignored `.build/tmp/` that the check
removes afterwards, SwiftPM's package lock files and `TemporaryDirectory.*`
folders included. The check fails if the suite, passing or failing, leaves a
Brew Version entry (a `brew-version-` name, or a lock file named after a
`brew_version` or `brew-version-*` package path) in that directory, in
`$TMPDIR` or in Foundation's per-user temporary directory
(`getconf DARWIN_USER_TEMP_DIR`). Every compile also leaves a
`TemporaryDirectory.*` holding only an empty `.keep-directory` in that per-user
directory whatever `TMPDIR` says; the check removes the run's new ones and
names any other new one it leaves. Every test and harness temporary name uses
the `brew-version-` prefix, and the integration tests put each builder
home inside their own scratch directory, which they remove: through `TMPDIR`,
or through `BREW_VERSION_HARNESS_HOME`, a new path where a builder keeps its
whole build for the caller to inspect and remove. The builders point SwiftPM's
`TMPDIR` inside that home, and the integration tests check that nothing else
lands beside it. The suite also runs the check's own self-test,
`tools/tests/test_check_no_temp_leaks.sh`. Run one suite at a
time: a concurrent run of this project's suite can trip the check.
`make build` and `make release` run SwiftPM with `TMPDIR` in the ignored
`.build/tmp/`, so its package lock files and `TemporaryDirectory.*` folders
stay out of the caller's temporary directory; they do not sweep the per-user
markers.
Tests use synthetic responses; a live lookup is a separate acceptance check.

Render the maintained native views without reading owner state or showing windows:

```sh
make -C brew_version snapshots
```

This required visual category builds in a fresh mode-0700
`$TMPDIR/brew-version-snapshots.*` directory and prints its path and the command
that removes it. It writes twenty mode-0600 PNGs: `empty`, `watching`,
`other-updates`, `search-results`, `suggestions`, `error`, `settings`, `tap-watching`,
`tap-suggestions` and `scrolled` (a long list scrolled under its pinned header), each with
`-light.png` and `-dark.png`. The renderer checks actual painted pixels, widths,
content-hugging empty state, long-list bounds and native scroll viewports.
Inspect every PNG, then check the real popover, menus and Settings in both
appearances; offscreen rendering does not establish native input or activation.
Keep the printed images outside the repository for review. The builder keeps
only the PNGs: it removes its scratch package and fixtures when it finishes, and
its whole directory if the build fails or is interrupted. Remove the directory
once you have reviewed the images. SwiftPM's lock files and `TemporaryDirectory.*`
folders stay in that directory, and the target runs the builder under
`tools/check_no_temp_leaks.sh --sweep-only`, which removes the build's empty
per-user markers and fails if it leaves any Brew Version entry other than a
directory in either temporary directory. `make acceptance` and
`make settings-prototype` run their builders the same way.

To run the debug command from the repository root, resolve SwiftPM's binary
directory (its layout varies by toolchain):

```sh
brew_version_bin="$(swift build --package-path brew_version --show-bin-path)"
"$brew_version_bin/brew-version" --help
```

## Command usage

```text
brew-version [OPTIONS] PACKAGE...
```

- `--formula` or `--cask` forces all names to that kind. Otherwise each name
  tries official formula first, then official cask, then a unique tap match.
- `--watch [SECONDS]` or `--watch=SECONDS` checks immediately, then repeats
  every 300 seconds by default, until any version changes.
- `--version` prints the release version. `-h` and `--help` print full help.
- Names use lowercase letters, digits and `@ + . _ -`, beginning with a letter
  or digit. Tap packages use `user/tap/name`; tap segments use lowercase letters,
  digits and `. _ -`, starting with a letter or digit. See Taps below.

One name prints only its version; several names print `name: version`.
Watch output includes local date, time, time zone, name and version on every
check. A changed version includes its initial version and exits successfully.
Output is line buffered so watch lines appear promptly through a pipe.
Lookups run in argument order and stop at the first error, preserving earlier
output. Press Ctrl-C to stop watching.

Exit codes are 0 for success (including detecting a change), 1 for a lookup
error, and 2 for invalid arguments. Watch intervals are positive whole seconds
through `4294967295`; leading zeroes are accepted. The app's minimum interval
does not apply to the CLI.

### Compatibility with the bash command

The CLI preserves the existing argument ordering and watch loop. Deliberate
changes are covered by the named regression tests:

- `RunCLITests.helpAndVersion`: adds the release version flag.
- `ArgumentsTests.table`: caps watch seconds at the representable UInt32 limit.
- `UsageTests.expectedHelp`: adds version help, removes the external dependency
  requirement and calls exit code 1 a lookup error.
- `RunCLITests.lookupWithoutDependencyTools`: removes `curl` and `jq` checks.
- Tap lookups add source-qualified names and unique bare-name fallback; ambiguous
  tap matches report sorted full names instead of choosing one.
- `TransportTests.timeoutPolicy`: uses a 10-second idle request timeout and
  30-second total resource timeout for individual lookups.

The release version comes from the tracked Info.plist through
`BrewVersionRelease.version`; a core test verifies that they agree.

## Taps

Packages from locally added third-party taps work in search, watches, Other
updates and the CLI. Tap names normalize case and Homebrew repository prefixes;
official core/cask aliases use their ordinary short package names. A bare search
shows the official match and every matching tapped package as separate rows.
Suggestions include local tap names before any remote lookup, mark Installed
by package kind, and order installed matches first, exact short names next,
then official before tap and full-name order (up to eight rows). A query with
slashes matches full-name prefixes. Rows show the short name and tap; tooltips,
accessibility names and copied install/upgrade commands retain the full name.

Adding a bare name chooses official formula, then official cask (restricted by
the selected kind), then a unique tap match. Several tap matches produce an
ambiguity error listing their sorted full names. Use `user/tap/name` to choose
a source explicitly. A successful watch saves that resolved identity, so later
checks never silently switch sources. A failed bare add saves no watch.
Selecting a suggestion, search result or Other updates row chooses that exact
source and kind, including the final Watch lookup. If the official package
disappears, that choice never falls back to a tap.

The local index reads tapped directories and Git origin configuration as text;
the app and CLI never execute brew, git, Ruby or tap code. Only GitHub origins
can be checked. Versions come from HTTPS files at
`raw.githubusercontent.com/owner/repository/HEAD/path`, without waiting for
`brew update`. Conditional requests use ETags; freshness remains subject to
GitHub's HTTP caching. The app rescans taps on catalog refresh and manual
refresh. Removing a tap leaves its watches with an explicit error and stops
admitting its installed receipts; it never turns them into official installs.

The text reader accepts literal versions and derives formula versions from a
literal URL/tag using the pinned Homebrew URL detector when no explicit version
exists. It reads stable/macOS and matching architecture scopes, ignores nested
resources, bottles and other non-package scopes, and never evaluates dynamic
Ruby. Unreadable explicit versions stay errors. Cask `:latest`, revision,
auto-update and app metadata retain their existing semantics.

Other updates checks installed tap packages on its catalog cadence through the
shared four-request scheduler, independently of official catalog success. It
retains previous tap listings when a source fails and reports separate counts:
“Couldn't check N tap packages.” for HTTP/network failures and
“N tap packages can't be checked.” for unsupported, missing or unreadable
sources (with singular wording for one). These rows never notify or increase
the watched amber count. Tap notifications use “NAME VERSION is in TAP”; see
the rolling alert behavior under Saved watches and checks.

Rollback safety: official watches/cache remain under the original `watched`
and `listingCache` state keys; tap entries use `tapWatched` and
`tapListingCache`. Version 1.0.2 can still load the official entries, but ignores
the tap keys and drops them on its first save. Preserve a private state backup
before rolling back if tap watches must be restored later.

## Saved watches and checks

The app core persists chosen watches, release acknowledgements, skipped releases,
check interval and conditional listing cache in `state.json` under
`~/Library/Application Support/Brew Version/`. The directory is private (0700)
and the file is private (0600). Changed state writes atomically before the
visible state changes; notifications follow a successful save. A failed save
keeps the previous state and can be retried. Closing an already acknowledged
popover or choosing the current setting does not write. Saved conditional
listing entries are limited to watched names; removing a watch evicts its cache.

Unreadable or invalid saved state is moved to `state.json.bad` before starting
fresh. Existing recovery files are preserved with unique suffixes. If that move
fails, checking and mutations stay disabled until a load retry succeeds.

Watches default to every 30 minutes, with presets from 10 minutes to 6 hours
and whole-minute custom intervals from 10 minutes to 24 hours. A first lookup
sets a baseline without notifying. Installed updates stay amber unless skipped;
new releases for uninstalled packages stay amber across polls and restarts until
the popover closes. Checks use at most four concurrent lookups and retain settings and
watch changes made while the network is busy. A check with any unreachable lookup
does not advance the last successful check. Automatic failures retry no sooner
than the chosen interval; reconnect retries an unreachable check promptly.
Failed saves retain that interval floor across reconnects; manual checks can
retry immediately. The next-check footer uses these same scheduler deadlines,
including failed attempts and saves. While offline it describes the reconnect
deadline instead: reconnect can bypass an unreachable request's delay, but
cannot bypass a failed save's interval floor.

Unacknowledged updates share one rolling notification. The first update sounds;
later updates replace it silently, newest first, with updates from the same check
ordered by name. macOS may truncate a long body, but the title retains the count.
Clicking the alert opens the popover and acknowledges the list; dismissing it,
opening the popover, or closing it after an update arrived also clears the list.
Skip, stop watching and upgrading remove affected entries without reposting;
Undo restores a watch without relisting it. Amber state remains independent.
The list survives restart and is reconciled quietly. If the system no longer lists
the alert at a later check, the next update starts a fresh list; denied notifications,
disabled Notification Center listing and failed posts keep the list for retry.
An acknowledgement that cannot be saved leaves the list and alert intact.
Launch removes older delivered alerts and test notifications. The saved schema is
unchanged: older state without the alert list loads, and unknown entry keys are
ignored (`stateWithoutAlertListLoads`, `entryDecodingIgnoresUnknownKeys`).

## Catalog and Other updates

The optional catalog client reads Homebrew's formula and cask bulk lists for
prefix search suggestions and installed, unwatched updates. Only admitted
Homebrew core/cask and currently tapped installations appear; these updates never notify or affect
the watched update count. Self-updating casks retain their installed-version
source, including the fallback to Homebrew's records. Like `brew outdated`,
Other updates hides a self-updating cask whose installed version comes only
from that fallback, because Homebrew's record is often older than the app
itself. Settings **Include self-updating apps** (off by default, like
`brew outdated --greedy`) lists them too; the section notes how many are hidden.
A self-updating cask whose app version can be read still appears when behind.

Formula versions compare the upstream version first and the numeric keg revision
second, matching Homebrew's package version semantics. Legacy Caskroom version
folders without an install receipt count as installed. An existing unreadable,
malformed or untapped-source receipt still excludes the cask, and version
folder symlinks are excluded. Formula kegs require a core or currently tapped
receipt. Casks with receipts require the official cask tap or a currently tapped
source; legacy receipt-free casks remain official. Receipt provenance separates
official and tap identities even when their short names collide.
Receipt `source.tap` is Homebrew's canonical tap name, not a typed or directory
alias. Admission folds case but never strips another repository prefix or
reassigns a removed source to another tapped repository. Tap membership is
captured once for each snapshot or point read.

At startup, callers await `WatchController.hydrateCatalog()` to restore cached
suggestions and Other updates even when a network refresh is not due. This API
is async so reading and decoding bulk cache data runs away from the main actor.
`scheduledTick()` independently starts watched checks and catalog refreshes.
The catalog refreshes once at every launch, then on its own Other updates
interval (Settings: 30 minutes to 24 hours, default 1 hour), separate from the
watched interval because each refresh downloads Homebrew's full lists (about
7 MB compressed). The popover's refresh button also refreshes the catalog when
it is more than 10 minutes old, bypassing the path monitor's offline gate.
Failed automatic attempts retry no sooner than every 10 minutes, without
changing the last successful catalog timestamp. The Other updates header shows
when the list was last updated, that it is updating, or why the last refresh
failed while the previous list stays visible. Disabling Other updates clears
only that section; prefix suggestions still hydrate and refresh on the same
cadence. Installation snapshots run away from the main actor, admit each receipt
once, and are reused when filtering watches or changing unrelated settings.
Overlapping refresh callers share a capture and at most one replacement for
new metadata; further missing names use targeted reads. Search and Watch read
only their result names and do not rescan the full installation or recompute
Other updates. Manual Check now attempts HTTP even when the path monitor reports
offline; automatic checks retain that gate. Reconnect retries unreachable rows
after mixed successful/failed checks too.

The catalog cache lives under `~/Library/Caches/Brew Version/`. Its
`catalog.json` snapshot contains a versioned pair of slim Listing indexes and
their ETags, replaced atomically only after both responses validate. The JSON
envelope starts with a fixed `brew-version-catalog-v2` format marker, checked
with a bounded read before the remaining file is allocated or decoded. Legacy
raw/base64 envelopes and earlier unmarked slim indexes are ignored without
reading their payloads. They refetch once without old ETags and are replaced
on the next successful refresh; saved watches are unaffected.
Unknown API metadata is discarded during typed decoding away from the main
actor. A partial, invalid, empty or failed download retains the previous pair
as stale content. A list with fewer than half the previous usable item count
is also rejected. If both lists validate but disk persistence fails, the new
pair and ETags remain available in memory, with a visible cache-write warning;
successful fetch cadence still advances. A 304 response reuses the decoded
listings; without a valid index, the client retries unconditionally. Each client
reads its disk cache once. The slim cache, typed decoding and bounded format
admission exist to keep idle memory well under the 150 MB target: 1.0.0
measured about 46–70 MiB idle, with a higher transient peak during a cold
catalog download.
The bulk transport uses a 10-second idle timeout and a 120-second total timeout.
Catalog timestamps and the visibility/collapse settings use the same atomic
state-save boundary as watches, retaining committed values when saving fails.

## Menu bar app

Build the signed app and CLI with `make -C brew_version release` from the
repository root. Products are `brew_version/build/release/Brew Version.app`
and `brew_version/build/release/brew-version`. Signing is local ad hoc signing;
the bundle includes Homebrew's license notice. Open the app to get a mug in
the menu bar. Initial launch stays quiet, including at login; opening the running
app again shows its popover. An amber dot on the mug means a watched update is
available, matching the dot on its row; its accessibility label includes the
number of watched updates. The mug outline follows the menu bar's light or dark
appearance. The status item is as wide as its image rather than the bar's
height, so it widens by 3pt while the amber dot shows.

The popover shows the last check, refresh, and a search field. Search accepts
space-separated names, rejects invalid names, and suggests catalog prefixes.
Lookups wait about 300 ms after typing and retain the previous results until
the current lookup completes. Return during that wait watches the selected
result of the current query; editing again cancels that pending intent.
Select a result with the arrow keys or click; Return watches it, and Command-C
copies its version. Only explicitly watched packages can notify. The first
watch requests notification permission if the OS has not already decided it.
The rolling alert and acknowledgement rules are described in Saved watches and checks.
Selecting a catalog suggestion preserves its formula/cask kind through lookup
and Watch. An explicit suggestion kind also controls its version lookup when
the same name is already watched with another kind; the saved watch stays as
chosen. Automatic search uses an existing watch's known kind. Editing clears
the suggestion choice. Suggestions and results share a content-sized scrolling
region bounded by the popover height, keeping the search field and footer
reachable. Arrow selection scrolls the selected result into view.

Watching sorts updates first, then names. Amber rows offer an upgrade command
for installed packages or an install command for packages not installed, plus a
skip action. The app only copies commands. A row's context
menu and its hover ellipsis menu contain **Stop watching NAME**. Selecting a row
and pressing Delete also removes it. Removal deletes its saved watch state;
**Undo** restores it for five seconds. Closing the popover acknowledges unseen
releases of packages that are not installed.

Each watch is an individually named accessibility group, **Watching NAME**,
with its child actions retained. Its default accessibility action selects the
row and gives it the same native editing focus as clicking it; selected state
is exposed to assistive technology. Delete in search continues editing text.

If Undo cannot save, its recovery entry stays available until restoration
succeeds. Retry Undo after correcting the save problem; further Stop watching
actions stay disabled so they cannot replace that entry. Watching the same
package from search or Other updates retries the saved restoration, preserving
its acknowledgements and skipped version. The recovery line stays visible
while searching too. The usual five-second expiry applies before a failure.

**Other updates** lists installed, unwatched updates on this Mac and never alerts.
Use Watch to move an item to Watching. Click its header to collapse the list,
or turn it off in Settings. Below the header, the section shows when the list
was last updated; set how often it refreshes in Settings. The footer's watch
interval menu accepts the presets or a whole number of minutes from 10 through
1,440; the footer shows the next check.
**Custom…** opens Settings with its minutes field focused; enter a value and
press Return or Apply. Invalid input remains editable with inline validation.
The popover uses a 340-point layout that hugs short content; only the package
list scrolls when needed. Its scroll bar travels in the popover's right margin, so
it never covers counts, chevrons or row actions, and the "Watching" and "Other
updates" headers stay pinned while their own rows scroll beneath them. Hover or select a watch to reveal its icon actions.
The Settings gear activates a reused AppKit-owned window containing the version,
interval, Other updates toggle, Other updates interval, Include self-updating
apps and Open at login, including the service's status
and registration errors. The login status refreshes whenever that window becomes
key; required approval offers **Open Login Items Settings**. Notification
authorization and posting failures appear in both Settings and the popover,
with **Retry notifications** after correcting the reported problem. Settings
also offers **Send test notification**, which sends a clearly labeled test
through the same notification service without changing any watches. Allow
notifications if macOS asks, look for the banner or Notification Center entry,
then click it and confirm that the popover opens. A submitted request alone
does not establish delivery. Turn Open at login off before quitting a temporary
build-folder copy.

The app composes its state and cache paths under the current user's home:
`~/Library/Application Support/Brew Version/state.json` and
`~/Library/Caches/Brew Version/`. Removing the app leaves both folders; delete
them by hand if the saved watches and catalog are no longer wanted.
Persistence problems appear in the popover; a blocked load disables mutations
and refresh until Retry succeeds. A recovered quarantine warning is distinct
from a failed save; only the latter calls for retrying the failed action.

### Settings and native acceptance gates

AppKit owns the application delegate, status item, the popover's panel and the
Settings window; SwiftUI supplies their content. On macOS 27 the system's
MenuBarAgent hosts the status item. A press on the closed item starts its
expanded-interface session, whose begin shows the popover in an owned panel;
the session's end hides it at once, without animation. A press on the item
while the popover is open reaches neither the app nor the session, so a global
mouse monitor recognizes that press and closes the popover. Escape, Settings
and clicks elsewhere hide it and cancel the session. Pressing the icon of a
popover opened from Finder or a notification closes it. While the item is
hidden or not yet placed, the popover opens at the top right of the menu-bar
screen. The Settings window
is retained after closing, and the gear activates the app and brings that same
window forward. Both reused windows move to the current desktop Space when shown,
and the panel also appears over a full-screen app.

The panel replaced an `NSPopover` deliberately: an anchored popover joins the
expanded-interface session as a second owner, and its own transient dismissal
raced the forwarded clicks, so repeated presses were swallowed or reopened it.
Keep one owner of open/close. The root lessons file records the observed event
order and the panel's single sizing contract (root pinned to the window's
content layout guide) under its 2026-10-17 Brew Version entries in
[`docs/lessons_learned.md`](../docs/lessons_learned.md).

The minimum supported runtime is macOS 27, matching the acceptance host.
Automated tests, offscreen layout and signatures establish no native input
result. Two gates have never been observed natively and rely on automated
coverage only: the status item's update count through VoiceOver (waived by the
owner for 1.0.0) and the login item's approval-required state (not reachable
on the acceptance host).

Record each current-system check separately:

- Mug, amber update count and accessibility state. Press the status item
  repeatedly, slowly and quickly; every press must open or close the popover
  exactly once, with the whole popover, including header and footer, on-screen.
  Reopen the app from Finder, or click a notification, then press the icon once:
  the popover must close. Click outside the popover, then press the icon once:
  it must open. Run these with the menu bar manager running; while it hides the
  item, Finder reopening places the popover at the top right. One miss fails.
- First-open and reopen search focus; arrows, Return, Command-C; Return while
  lookup is pending; explicitly choose the cask for a colliding name.
- Click a watched row and press Delete with default keyboard navigation; Undo
  must restore its saved state. Verify each named accessibility group can be
  selected independently, retains its child actions and announces selection.
  Delete in the search field must edit text. Offscreen responder tests do not
  establish the live accessibility tree or physical mouse gesture.
- Long multi-token results scroll to both ends while input/footer stay reachable.
- Current interval has a native checkmark, including a custom current value;
  opening its menu preserves the popover. Custom opens Settings with the minutes
  field focused and no popover sheet. Invalid input remains editable; valid
  Apply/Return persists the interval. Command-W closes Settings normally.
- Settings opens, activates, comes forward, closes and reopens as the same
  window, while the status item remains usable.
- Other updates Watch and fallback source note; turning Other updates off
  preserves suggestions. Watched fallback rows also show their source note.
- Tap rows show short name plus tap with full-name help/accessibility; verify
  official and tap collisions, installed formula/cask suggestions, Return,
  Command-C, full-name install/upgrade commands, untapped errors, and both
  exact tap failure status lines with recovery in the synthetic harness.
- Use Settings **Send test notification** to verify permission, visible delivery
  and a click opening the popover in the production app. Authorization denial
  and posting errors are visible and retryable.
- Login registration and any required approval; status refresh on window key;
  Open Login Items Settings action. Record the actual status/error without
  assuming that the signing method determines the result.
- Light and dark appearances; turn Open at login off, quit both temporary
  apps and the release, and verify that no login registration remains.

Launching `build/release/Brew Version.app` directly is supported for testing.
The installer is a separate deployment check; it does not repair popover layout.
After rebuilding, quit the running copy and open the new build to test its code.
Enabling Open at login on a temporary build registers that bundle location;
disable it there before switching to the installed copy, then enable it from
the installed app if desired. Logout/reboot acceptance can be recorded later;
persisting the switch across Settings reopens establishes only its current state.

`make -C brew_version acceptance` is a required automated validation category.
It builds a separately identified, signed synthetic bundle in a fresh private
`$TMPDIR/brew-version-acceptance.*` home and prints its path and the command that
removes it. The home keeps only the bundle and its synthetic state; the builder
removes its scratch package when it finishes, and the whole home if the build
fails or is interrupted. It copies the maintained production UI/notifier/core sources into a
scratch Swift package, replacing only the application entry and services.
It also runs a synthetic service test without launching a GUI. The harness
uses no owner state, inventory, application folders or live HTTP requests.
The harness immediately opens the maintained popover. Search for
`synthetic-formula` and press Return to establish its baseline.
**Advance release and check** changes its listing and checks again; click the
delivered notification and require the popover to open. **Other updates**
contains `synthetic-installed`, from a private invented Homebrew receipt, and
`synthetic-fallback`, an invented legacy self-updating cask whose app is absent.
Watch that cask to check its fallback note in both sections. Search
`synthetic-shared` and select the cask suggestion: its version is `4.0-synthetic`,
while the formula is `3.0-synthetic`. `synthetic-cask` is another watchable cask;
add two watches to exercise click/Delete/Undo without real inventory.
For rolling-alert acceptance use a fresh home under the user's home directory
(`BREW_VERSION_HARNESS_HOME`): on macOS 27 `usernoted` rejected a bundle in
`/private/tmp`. Establish permission in System Settings > Notifications. Watch
`synthetic-formula` and `synthetic-cask`, then close the popover after pressing
**Both in 5s** or **Cask then formula**. Verify same-check ordering, silent
replacement and newest-first order, one delivered entry, click, dismiss, popover
acknowledgement, and clearing in Notification Center followed by a fresh list.
The latter may be reported as a click by macOS. Finish delayed sequences before
testing the failure and retry controls.
**Light** and **Dark** are harness appearance controls. **Delay next lookup** holds the next individual
synthetic lookup for two seconds, so type and press Return while it is pending.
After real notification authorization, **Test posting failure** injects one
harness-only service error through the maintained notifier. Require its error
in the popover and Settings; **Retry notifications** must deliver the synthetic
retry notice and clear the error. Normal prompt/delivery/click still uses the
real system notification center. The production app has
no simulation environment switch. Use normal OS notification controls for any
permission changes; do not erase notification databases. Quit the harness,
turn its login toggle off, and remove only its printed fresh home when finished.

The native search checklist also includes a large query: enter
`synthetic-formula synthetic-installed synthetic-01 synthetic-02 synthetic-03 synthetic-04 synthetic-05 synthetic-06 synthetic-07 synthetic-08 synthetic-09 synthetic-10 synthetic-11 synthetic-12 synthetic-13 synthetic-14 synthetic-15 synthetic-16 synthetic-17 synthetic-18 synthetic-19 synthetic-20`.
The harness returns invented not-found rows for the numbered names. Arrow to
the last row and back to the first; require each selection to stay visible,
the input and footer to remain reachable, and Return/Command-C on the first
row to watch/copy the expected synthetic formula. Record actual input and
visibility observations separately from the offscreen layout test.

Synthetic tap acceptance: search `synthetic-tool` or the full
`synthetic-owner/synthetic-tap/synthetic-tool`; check Installed, tap labeling,
full-name copied upgrade command and watch identity. `synthetic-app` supplies a
tap cask (version `7.8`) and its `--cask` command; `synthetic-shared` collides
with the official formula/cask. **Tap failures** injects one HTTP failure and
one unreadable formula into the installed tap refresh; require both exact
singular status lines. **Restore tap responses** clears both counts. These
controls advance only the synthetic clock beyond the refresh floor. **Remove
tap** parks the synthetic repository outside the tapped tree; a watched tap
package must show the exact untapped error. **Restore tap** returns it. These
controls extend the original synthetic cases; none exists in production.

For the minimal Settings-only gate, run
`make -C brew_version settings-prototype`; it prints a separately signed
prototype path in another fresh private home. It opens the exact maintained
AppKit-owned Settings window at launch, using the same synthetic composition.
Both builders share their source-copy/build/signing implementation; the
prototype has no separate discarded Settings scene.

## Deployment

Use the [Native Brew Version deployment guide](../docs/local_deployment_sync.md#native-brew-version-deployment)
for deploy, dry-run, read-only audit, rollback and fleet-audit commands. The
installer builds admitted tracked inputs, installs the signed CLI and app as
one release, and preserves watches and catalog state. It never opens or quits
the app. Quit and reopen an already running app after deployment.
