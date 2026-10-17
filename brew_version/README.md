# Brew Version

Brew Version reads current formula and cask versions from Homebrew's public API.
The Swift `brew-version` command supports one-time lookups and watching until a
version changes. The shared core also supports the native menu bar app,
which watches chosen packages and notifies about their updates without running
`brew` or upgrading packages.

This native macOS app is a deliberate exception to the UI Shapes defaults in
the repository's `agents.md`.

## Requirements

- macOS 14 or newer.
- Xcode or the Command Line Tools providing Swift 6.
- Node.js for deployment tooling and release build integration tests.
- Network access to Homebrew's HTTPS public API for lookups.

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
The integration category also runs the acceptance and Settings prototype
builders with an invented HOME, requiring their printed private homes to be
children of the OS temporary root with mode 0700.
Tests use synthetic responses; a live lookup is a separate acceptance check.

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
  tries formula first, then cask.
- `--watch [SECONDS]` or `--watch=SECONDS` checks immediately, then repeats
  every 300 seconds by default, until any version changes.
- `--version` prints the release version. `-h` and `--help` print full help.
- Names use lowercase letters, digits and `@ + . _ -`, beginning with a letter
  or digit. Third-party taps are not supported.

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
- `TransportTests.timeoutPolicy`: uses a 10-second idle request timeout and
  30-second total resource timeout for individual lookups.

The release version comes from the tracked Info.plist through
`BrewVersionRelease.version`; a core test verifies that they agree.

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
watch changes made while the network is busy. An entirely unreachable check
does not advance the last successful check. Automatic failures retry no sooner
than the chosen interval; reconnect retries an unreachable check promptly.
Failed saves retain that interval floor across reconnects; manual checks can
retry immediately. The next-check footer uses these same scheduler deadlines,
including failed attempts and saves. While offline it describes the reconnect
deadline instead: reconnect can bypass an unreachable request's delay, but
cannot bypass a failed save's interval floor.

## Catalog and Other updates

The optional catalog client reads Homebrew's formula and cask bulk lists for
prefix search suggestions and installed, unwatched updates. Only admitted
Homebrew core/cask installations appear; these updates never notify or affect
the watched update count. Self-updating casks retain their installed-version
source, including the fallback to Homebrew's records.

Formula versions compare the upstream version first and the numeric keg revision
second, matching Homebrew's package version semantics. Legacy Caskroom version
folders without an install receipt count as installed. An existing unreadable,
malformed, unknown-tap or third-party receipt still excludes the cask, and version
folder symlinks are excluded. Formula kegs always require an official core receipt.

At startup, callers await `WatchController.hydrateCatalog()` to restore cached
suggestions and Other updates even when a network refresh is not due. This API
is async so reading and decoding bulk cache data runs away from the main actor.
`scheduledTick()` independently starts watched checks and catalog refreshes;
the catalog is fetched when absent or 24 hours after successful revalidation.
Failed attempts use the watched interval as an in-memory retry floor, without
changing the last successful catalog timestamp. Disabling Other updates clears
only that section; prefix suggestions still hydrate and refresh on the same
cadence. Installation snapshots run away from the main actor, admit each receipt
once, and are reused when filtering watches or changing unrelated settings.

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
as stale content. A 304 response reuses the decoded listings; without a valid
index, the client retries unconditionally. Each client reads its disk cache once.
The bulk transport uses a 10-second idle timeout and a 120-second total timeout.
Catalog timestamps and the visibility/collapse settings use the same atomic
state-save boundary as watches, retaining committed values when saving fails.

## Menu bar app

Build the signed app and CLI with `make -C brew_version release` from the
repository root. Products are `brew_version/build/release/Brew Version.app`
and `brew_version/build/release/brew-version`. Signing is local ad hoc signing;
the bundle includes Homebrew's license notice. Open the app to get a mug in
the menu bar. Initial launch stays quiet, including at login; opening the running
app again shows its popover. A filled mug means a watched update is available; its accessibility label includes
the number of watched updates.

The popover shows the last check, refresh, and a search field. Search accepts
space-separated names, rejects invalid names, and suggests catalog prefixes.
Lookups wait about 300 ms after typing and retain the previous results until
the current lookup completes. Return during that wait watches the selected
result of the current query; editing again cancels that pending intent.
Select a result with the arrow keys or click; Return watches it, and Command-C
copies its version. Only explicitly watched packages can notify. The first
watch requests notification permission if the OS has not already decided it.
Selecting a catalog suggestion preserves its formula/cask kind through lookup
and Watch. An existing watch retains its known kind; editing the search clears
the suggestion choice. Suggestions and results share a 300-point scrolling
region that keeps the search field and footer reachable. Arrow selection scrolls
the selected result into view.

Watching sorts updates first, then names. Amber rows offer the upgrade command
to copy and a skip action. The app never executes an upgrade. A row's context
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

Other updates on this Mac lists installed, unwatched updates and never alerts.
Use Watch to move an item to Watching. Click its header to collapse the list,
or turn it off in Settings. The interval menu accepts the presets or a whole
number of minutes from 10 through 1,440; the footer shows the next check.
The Settings gear activates a reused AppKit-owned window containing the version,
interval, Other updates toggle and Open at login, including the service's status
and registration errors. The login status refreshes whenever that window becomes
key; required approval offers **Open Login Items Settings**. Notification
authorization and posting failures appear in both Settings and the popover,
with **Retry notifications** after correcting the reported problem. Turn Open at
login off before quitting a temporary build-folder copy.

The app composes its state and cache paths under the current user's home:
`~/Library/Application Support/Brew Version/state.json` and
`~/Library/Caches/Brew Version/`. Removing the app leaves both folders; delete
them by hand if the saved watches and catalog are no longer wanted.
Persistence problems appear in the popover; a blocked load disables mutations
and refresh until Retry succeeds. A recovered quarantine warning is distinct
from a failed save; only the latter calls for retrying the failed action.

### Settings and native acceptance gates

AppKit owns the application delegate, status item, popover and Settings window;
SwiftUI supplies their content. The Settings window is retained after closing,
and the gear activates the app and brings that same window forward. The
[implementation record](docs/implementation_notes.md#native-acceptance-observations)
lists observed current-system results and the remaining status-item, physical
mouse-selection and notification-delivery/click gates. The minimum supported
runtime is unavailable and remains a separate release gate. Automated tests,
offscreen layout and signatures establish no native input result.

Record each current-system check separately:

- Mug, amber update count and accessibility state; click the open status item
  and require it to close and remain closed.
- First-open and reopen search focus; arrows, Return, Command-C; Return while
  lookup is pending; explicitly choose the cask for a colliding name.
- Click a watched row and press Delete with default keyboard navigation; Undo
  must restore its saved state. Verify each named accessibility group can be
  selected independently, retains its child actions and announces selection.
  Delete in the search field must edit text. Offscreen responder tests do not
  establish the live accessibility tree or physical mouse gesture.
- Long multi-token results scroll to both ends while input/footer stay reachable.
- Current interval has a native checkmark, including a custom current value;
  opening its menu preserves the popover. Custom invalid input remains editable;
  valid Save and Cancel preserve the popover and the expected interval.
- Settings opens, activates, comes forward, closes and reopens as the same
  window, while the status item remains usable.
- Other updates Watch and fallback source note; turning Other updates off
  preserves suggestions. Watched fallback rows also show their source note.
- Notification prompt, delivery and notification click opening the popover;
  authorization denial and posting errors are visible and retryable.
- Login registration and any required approval; status refresh on window key;
  Open Login Items Settings action. Record the actual status/error without
  assuming that the signing method determines the result.
- Light and dark appearances; turn Open at login off, quit both temporary
  apps and the release, and verify that no login registration remains.

`make -C brew_version acceptance` is a required automated validation category.
It builds a separately identified, signed synthetic bundle in a fresh private
home created by `mktemp -d` in OS temporary space and prints its
path. It copies the maintained production UI/notifier/core sources into a
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
visibility observations separately from the offscreen layout test; the
implementation record lists the completed observations and their limits.

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

## Implementation record

The [implementation and acceptance record](docs/implementation_notes.md) lists
decisions, deviations, automated validation and the outstanding native UI gates.
