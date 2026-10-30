# Brew Version Rolling Alert Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Dispatch coding subagents sequentially for the tasks, with one whole-branch review after implementation and no between-task reviews, as the owner requested. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the rolling alert defined in Behavior.

**Architecture:** `WatchController` computes an `AlertDigest` from watch state and hands it to `UserNotifier` through a serial queue. The task interfaces define the persistence and system-service boundaries.

**Tech Stack:** Swift 6, Swift Testing, AppKit, SwiftUI, UserNotifications. No new dependencies.

**Spec:** This document. The Behavior and macOS 27 evidence sections are the agreed design.

## Global Constraints

- Release version is `1.2.0` with `CFBundleVersion` `9`, set in `Sources/BrewVersionCore/Release.swift` and `Resources/Info.plist`.
- Use `synthetic-*` package names for new fixtures and examples.
- The amber dot, row amber state and `amberCount` keep their current meaning. The alert list only tracks what has not been acknowledged.
- No new Settings control.
- `evaluate(_:listing:installed:)` keeps its signature and its notification text.
- Saved state stays at its current `schema`.
- Follow `agents.md` for Git, public-repository data and runtime-state policy, and `docs/local_deployment_sync.md#native-brew-version-deployment` for deployment. Use a feature branch.
- Run filtered tests under the leak check, from the repository root, because bare `swift test` bypasses it:

```bash
(cd brew_version && mkdir -p .build/tmp && TMPDIR="$PWD/.build/tmp/" ../tools/check_no_temp_leaks.sh --names '(^|_)brew[-_]version[-_]' swift test --filter '<pattern>')
```

## Review Focus

- Callback-free clearing: `clearedAlertStartsFreshList` and `alertWasClearedReadsDeliveredList`. Native coverage is deferred for this path; see `AcceptanceDelegate.applicationDidFinishLaunching`.
- Retry and authorization: `failedPostRetriesCurrentList`, `failedFirstAlertKeepsItsSound`, `failedPostLeavesPackagesListed`, `deniedNotificationsKeepTheList`, and `shrinkDuringRetryPostsCurrentList`.
- Delivery timing: `recentPostIsNotTreatedAsCleared` and `retryStartsGracePeriod`.
- Persistence failure: `failedAcknowledgementKeepsAlert`.
- Compatibility: `stateWithoutAlertListLoads` and `entryDecodingIgnoresUnknownKeys`. Running the previous release is outside this gate.

---

## Behavior

The text of a one-package and a several-package alert is defined by `singleDigestKeepsTheIndividualAlertText` and `digestOrdersNewestFirstThenByName`.

| Situation | Result |
|---|---|
| New update, list empty | Banner with sound |
| New update while the list is outstanding | Same alert is replaced. Banner shows, no sound |
| Newer version of a listed package | Its version updates in place and it moves to the front. Banner shows, no sound |
| Several updates in one check | One alert, ordered by name |
| More packages than the body shows | Follow the macOS 27 evidence for display limits; retain the title count and newest-first order |
| Click the alert | List clears, alert leaves, popover opens |
| Dismiss with the X | List clears and the popover stays closed |
| Clear in Notification Center | Alert leaves and the list clears. The popover also opens if macOS reports this as a click, which the macOS 27 evidence could not rule out |
| Open the popover | List clears and the alert is removed |
| Popover closes after an update arrived while it was open | List clears and the alert is removed |
| Upgrade, Skip or Stop watching | Package leaves the list. Empty list removes the alert. A shorter list does not repost, because that would raise a banner that only says something went away |
| Undo of Stop watching | Package returns without alerting again |
| App quits and relaunches | List survives and launch stays quiet. An alert with no list behind it is removed at launch |
| Alert no longer delivered at the next check | Old list counts as acknowledged, and the check starts a new list |
| Any launch | Delivered alerts other than the rolling alert are removed. This clears earlier per-package alerts and any leftover test notification |
| Notifications denied or posting failed | Saved membership stays. Retry delivers the current list, retaining the initial sound until a successful post |
| Acknowledgement save fails | Saved membership stays and the app requests no notification removal. A system-removed alert is handled by the next-check rule |

Short names are used in the several-package body, including for tap packages, and its title reads the same for official and tap packages.

## macOS 27 evidence

These observations come from synthetic ad hoc signed probe runs on the macOS 27 development host on 2026-10-30, plus the system log of real alerts. The probe was not retained. The owner performed the clicks and reported the sounds.

Observed:
- Reusing an identifier leaves one delivered notification with the new text, and each replacement shows a banner, including one with no sound.
- `content.sound == nil` is silent, and `.default` chimes.
- `getDeliveredNotifications` lags a post by about a second.
- `removeDeliveredNotifications` after `add` left nothing delivered, whether sent before the add completed or at any delay tested up to a second after it.
- `.customDismissAction` delivers `UNNotificationDismissActionIdentifier` when the X is clicked, and a body click delivers `UNNotificationDefaultActionIdentifier`.
- Clearing from Notification Center removed the alert and reported the default action. The run could not distinguish this from a body click.
- Delivered notifications survived quitting and relaunching the app, and alerts posted during sleep could still be acted on after wake.
- A long body truncates with an ellipsis, and the title stays whole.
- `usernoted` refused a bundle run from `/private/tmp` with "Failed to find or validate client". A bundle under the home directory was accepted, and its entry appeared in System Settings > Notifications while it ran.
- In one trial, an allowed decision was still reported after the home-directory copy of the probe was deleted and reinstalled 2 seconds later. Another copy of the bundle stayed on disk throughout.

Not measured, and handled by design rather than by evidence:
- Notification Center listing turned off: `alertWasCleared` never reports cleared in that state.
- A Mac restart: if it clears delivered alerts, the next check starts a new list, and amber rows still show the updates.
- Whether a notification decision carries from the probe to the rebuilt harness, which has a different executable and signature. The native gate checks permission first.
- A harness run from its default `$TMPDIR` home.

## File structure

- `brew_version/Sources/BrewVersionCore/WatchState.swift`: saved list field, `notice(for:)`, `AlertDigest`, `AlertDelivery`, `alertDigest(for:)`.
- `brew_version/Sources/BrewVersionCore/WatchController.swift`: `Notifier` protocol, serial alert queue, check integration, acknowledgement, reconciliation.
- `brew_version/Sources/BrewVersion/UserNotifier.swift`: fixed-identifier delivery, retry payload, response handling, delivered-list checks.
- `brew_version/Sources/BrewVersion/StatusItemController.swift`, `AppDelegate.swift`: acknowledgement and launch hooks.
- `brew_version/Tests/Acceptance/*`, `Tests/Snapshots/Snapshots.swift`: harness conformance and controls.
- `brew_version/README.md`, `docs/lessons_learned.md`: behavior and lessons.

---

### Task 1: Saved alert list and digest

**Files:**
- Modify: `brew_version/Sources/BrewVersionCore/WatchState.swift` (`WatchEntry`, `evaluate`)
- Test: `brew_version/Tests/BrewVersionCoreTests/EvaluateTests.swift`, `brew_version/Tests/BrewVersionCoreTests/WatchStoreTests.swift`

**Interfaces:**
- Consumes: `updateStatus(listing:installed:)`, `ReleaseID`, `PackageName.shortName`, `PackageName.tap`.
- Produces:
  - `WatchEntry.alertPendingSince: Date?`, the last `init` parameter, defaulting to `nil`.
  - `public func notice(for entry: WatchEntry) -> Notice?`
  - `public enum AlertDelivery: Equatable, Sendable { case keepCurrent, silent, withSound }`
  - `public struct AlertDigest: Equatable, Sendable { public let names: [PackageName]; public let title: String; public let body: String; public init(names: [PackageName], title: String, body: String) }`
  - `public func alertDigest(for watched: [WatchEntry]) -> AlertDigest?`

- [x] **Step 1: Write the failing tests**

```swift
@Test func digestOrdersNewestFirstThenByName() throws {
    let older = Date(timeIntervalSince1970: 100), newer = Date(timeIntervalSince1970: 200)
    let digest = try #require(alertDigest(for: [pending("synthetic-a", "1.0", older),
                                                pending("synthetic-c", "3.0", newer),
                                                pending("synthetic-b", "2.0", newer)]))
    #expect(digest.names.map(\.rawValue) == ["synthetic-b", "synthetic-c", "synthetic-a"])
    #expect(digest.title == "3 updates on Homebrew")
    #expect(digest.body == "synthetic-b 2.0, synthetic-c 3.0, synthetic-a 1.0")
}
@Test func singleDigestKeepsTheIndividualAlertText() throws {
    let digest = try #require(alertDigest(for: [pending("synthetic-a", "2.0", Date(timeIntervalSince1970: 1))]))
    #expect(digest.title == "synthetic-a 2.0 is on Homebrew")
    #expect(digest.body == "You have 0.5.")
}
@Test func digestSkipsEntriesThatAreNoLongerAmberOrNotPending() {
    var skipped = pending("synthetic-a", "2.0", Date(timeIntervalSince1970: 1))
    skipped.skippedRelease = skipped.lastListing.map(ReleaseID.init)
    var told = pending("synthetic-b", "2.0", Date(timeIntervalSince1970: 1))
    told.alertPendingSince = nil
    #expect(alertDigest(for: [skipped, told]) == nil)
}
@Test func tapDigestUsesShortNames() throws {
    let since = Date(timeIntervalSince1970: 1)
    let digest = try #require(alertDigest(for: [
        pending("synthetic-owner/synthetic-tap/synthetic-tool", "7.8", since),
        pending("synthetic-a", "2.0", since)
    ]))
    #expect(digest.body == "synthetic-a 2.0, synthetic-tool 7.8")
}

func pending(_ name: String, _ version: String, _ since: Date) -> WatchEntry {
    let listing = Listing(name: PackageName(name)!, kind: .formula, version: version)
    return WatchEntry(name: listing.name, kind: .formula, lastListing: listing,
                      installed: InstalledVersion(version: "0.5", source: .cellar),
                      alertPendingSince: since)
}
```

In `WatchStoreTests`, add:
- `stateWithoutAlertListLoads`: load `Fixtures/state-1.0.2.json` the way `TapNameTests` loads it and assert every `alertPendingSince == nil`. Then save and reload an entry with a date and assert it round-trips.
- `entryDecodingIgnoresUnknownKeys`: encode a `WatchEntry`, add a `synthetic-future-key` to the JSON, and assert it decodes equal to the original.

- [x] **Step 2: Run the tests to verify they fail**

Run the filtered command from Global Constraints with pattern `EvaluateTests|WatchStoreTests`.
Expected: compile failure naming `alertPendingSince` and `alertDigest`.

- [x] **Step 3: Implement in `WatchState.swift`**

Extract only the title and body text from `evaluate` into `notice(for:)`, keeping its wording. The `notifiedRelease` guards and all state changes stay in `evaluate`, which ends with `return (next, notice(for: next))`. Its existing tests must pass unchanged.

`alertDigest(for:)` keeps entries where `alertPendingSince != nil && isAmber && notice(for:) != nil` and returns `nil` when empty. Implement the ordering and text pinned by this task's digest tests, using `ReleaseID.displayVersion`. Apply the Behavior table's truncation policy.

- [x] **Step 4: Run the tests to verify they pass**

Run the same filtered command.
Expected: PASS, with `EvaluateTests.transitions` unchanged.

- [x] **Step 5: Commit**

Subject: `Add Brew Version's saved alert list and digest`. Explain the change's purpose in the body.

### Task 2: One rolling alert per update list

**Files:**
- Modify: `brew_version/Sources/BrewVersionCore/WatchController.swift` (`Notifier`, `checkNow`)
- Modify: `brew_version/Sources/BrewVersion/UserNotifier.swift`
- Modify: `brew_version/Tests/Acceptance/AcceptanceApp.swift`, `brew_version/Tests/Acceptance/AcceptanceServiceTests.swift`, `brew_version/Tests/Snapshots/Snapshots.swift`
- Test: `brew_version/Tests/BrewVersionCoreTests/WatchControllerTests.swift`, `brew_version/Tests/BrewVersionCoreTests/TapControllerTests.swift`, `brew_version/Tests/BrewVersionAppTests/NativeActionsTests.swift`, plus every `Notifier` conformance in `brew_version/Tests` (find them with `rg ': Notifier' brew_version/Tests`)

**Interfaces:**
- Consumes: `alertDigest(for:)`, `AlertDigest`, `AlertDelivery`, `WatchEntry.alertPendingSince`.
- Produces:

```swift
public protocol Notifier: Sendable {
    func syncAlert(_ digest: AlertDigest?, delivery: AlertDelivery) async
    func alertWasCleared() async -> Bool
    func requestAuthorization() async
}
// Protocol extension defaults: syncAlert does nothing, alertWasCleared returns false.
```

  - `UserNotifier.alertIdentifier: String`, a `static let` with value `"brew-version.updates"`.
  - `NotificationService.deliveredIdentifiers() async -> Set<String>`
  - `NotificationService.removeDelivered(_ identifiers: [String])`
  - `WatchController.alertQueueDrained() async` (internal, for tests).
  - `WatchController.enqueueAlert(_ delivery: AlertDelivery) -> Task<Void, Never>` (private).
  - `UserNotifier.init(service: any NotificationService, now: @escaping () -> Date = Date.init)`

- [ ] **Step 1: Migrate the test doubles**

`RecordingNotifier`:
- `notices: [AlertDigest]` appends for `.silent` and `.withSound` only.
- `deliveries: [AlertDelivery]` appends for every `syncAlert`.
- `syncs: [AlertDigest?]` appends for every `syncAlert`.
- `var lastSyncCleared: Bool { syncs.last.map { $0 == nil } ?? false }`
- `func setCleared(_ value: Bool)`, returned by `alertWasCleared()`.
- `var clearedQueries: Int` counts `alertWasCleared()` calls.
- `persisted` still records when `notices` appends.

The other `Notifier` conformances become empty conformances. `NotificationServiceStub` gains `var deliveredIDs: Set<String>`, `var removed: [String]`, `var listsInCenter = true`, `var authorizationGate: (@MainActor () async -> Void)?`, `var authorizationStatusCalls = 0` and `var authorizationGateCall = 1`. Increment the call counter on each `authorizationStatus()` invocation and await the gate when it equals `authorizationGateCall`.

To keep the existing retry tests meaningful, add these to `NativeActionsTests.swift`:

```swift
extension UserNotifier {
    func post(_ notice: Notice) async {
        await syncAlert(AlertDigest(names: [notice.name], title: notice.title, body: notice.body), delivery: .withSound)
    }
}
func digest(_ text: String) -> AlertDigest {
    AlertDigest(names: [PackageName("synthetic-digest")!], title: text, body: text)
}
```

Update these existing tests for the agreed behavior change, and name them in the commit body:
- `inFlightCheckPreservesConcurrentMutationsAndGenerations`: expect `notices.count == 1` and that digest's sorted `names` to equal `Array(names.suffix(2))`.
- `checksLimitRequestsAndReadFreshInstalledVersions`: replace the `first(where:)` line with `#expect(notice(for: c.state.watched[0])?.body == "You have 0.5.")`.

- [ ] **Step 2: Write the failing tests**

```swift
@Test func oneCheckPostsOneAlertForSeveralPackages() async throws {
    // Two watches advance in one check.
    #expect(await notifier.notices.count == 1)
    #expect(await notifier.notices[0].title == "2 updates on Homebrew")
    #expect(await notifier.deliveries == [.withSound])
}
@Test func sameCheckOrdersByName() async throws {
    // A clock that steps on every now() call, and ControlledWatchTransport finishing synthetic-a before
    // synthetic-z in one check. Stamping per result would list z first.
    #expect(await notifier.notices[0].names == [PackageName("synthetic-a")!, PackageName("synthetic-z")!])
}
@Test func laterCheckReplacesTheListSilently() async throws {
    // First check advances synthetic-a, second advances synthetic-b.
    #expect(await notifier.notices.map(\.title) == ["synthetic-a 2 is on Homebrew", "2 updates on Homebrew"])
    #expect(await notifier.notices.last?.names.first == PackageName("synthetic-b")!)
    #expect(await notifier.deliveries == [.withSound, .silent])
}
@Test func newerVersionOfListedPackageStaysOneEntry() async throws {
    // synthetic-a 2 then 3 without acknowledgement.
    #expect(await notifier.notices.last?.names == [PackageName("synthetic-a")!])
    #expect(await notifier.notices.last?.title == "synthetic-a 3 is on Homebrew")
}
@Test func newerVersionMovesListedPackageToTheFront() async throws {
    // synthetic-a then synthetic-b are listed, then synthetic-a gets a newer version.
    #expect(await notifier.notices.last?.names.first == PackageName("synthetic-a")!)
    #expect(await notifier.notices.count == 3)
}
@Test func listSurvivesRestart() async throws {
    // A new controller on the same store, then a check with another update: the digest lists both.
}
@Test func unchangedCheckDoesNotRealert() async throws {
    // A third identical check appends nothing to deliveries.
}
```

In `NativeActionsTests`:

```swift
@Test func alertsReuseOneIdentifierAndCategory() async {
    let service = NotificationServiceStub(); service.status = .authorized
    let notifier = UserNotifier(service: service)
    await notifier.syncAlert(digest("first"), delivery: .withSound)
    await notifier.syncAlert(digest("second"), delivery: .silent)
    #expect(Set(service.requests.map(\.identifier)) == [UserNotifier.alertIdentifier])
    #expect(Set(service.requests.map(\.content.categoryIdentifier)) == [UserNotifier.alertIdentifier])
    #expect(service.requests[0].content.sound != nil && service.requests[1].content.sound == nil)
}
@Test func failedPostRetriesCurrentList() async {
    // First digest fails posting. keepCurrent with a longer digest updates the retry payload without posting.
    // retry() posts exactly one more request, with the longer digest's body and a sound.
}
@Test func failedFirstAlertKeepsItsSound() async {
    // .withSound fails, then .silent succeeds: the successful request has a sound.
    // Repeat with .silent also failing: retry() posts with a sound.
}
@Test func shrinkDuringRetryPostsCurrentList() async throws {
    let service = NotificationServiceStub(); service.status = .authorized
    let notifier = UserNotifier(service: service)
    service.postingFailure = "Synthetic posting failure"
    await notifier.syncAlert(digest("synthetic-a 2, synthetic-b 2"), delivery: .withSound)
    service.postingFailure = nil
    service.authorizationGateCall = service.authorizationStatusCalls + 2
    service.authorizationGate = {
        await notifier.syncAlert(digest("synthetic-b 2"), delivery: .keepCurrent)
    }
    await notifier.retry()
    #expect(service.requests.count == 2)
    let request = try #require(service.requests.last)
    #expect(request.content.body == "synthetic-b 2")
    #expect(request.content.sound != nil)
}
@Test func laterSuccessSupersedesAnEarlierFailure() async { /* lastError is nil and retry posts nothing */ }
@Test func testNotificationStaysSeparateFromTheRollingAlert() async { /* test uses a UUID identifier, no category, and leaves a pending package failure intact */ }
@Test func failedPostLeavesPackagesListed() async throws {
    // Regression for the lost alert. A real WatchController and UserNotifier share a stub service.
    // synthetic-a's post fails, a later check finds synthetic-b and posts successfully:
    // the successful request's body names both packages.
}
```

- [ ] **Step 3: Run the tests to verify they fail**

Run the filtered command with pattern `WatchControllerTests|TapControllerTests|NativeActionsTests`.
Expected: compile failure naming `syncAlert` and `UserNotifier.alertIdentifier`.

- [ ] **Step 4: Implement the controller**

Add `private var alertQueue: Task<Void, Never>?`. `enqueueAlert` captures the digest on the main actor and appends one `syncAlert` call to the chain, so calls run in commit order:

```swift
@discardableResult private func enqueueAlert(_ delivery: AlertDelivery) -> Task<Void, Never> {
    let digest = alertDigest(for: state.watched), previous = alertQueue, notifier = self.notifier
    let next = Task { await previous?.value; await notifier.syncAlert(digest, delivery: delivery) }
    alertQueue = next
    return next
}
```

In `checkNow`, replace the `notices` array:
- After `var candidate = state` and before the result loop, record `previousDigest = alertDigest(for: candidate.watched)`, `listWasEmpty` from `candidate.watched`, and one `let stamp = now()` for the whole check. This section must stay free of suspensions.
- For each success, set `alertPendingSince = stamp` when `evaluate` returns a notice. Otherwise set it to `nil` when the entry is no longer amber.
- After `commit`, read the new digest. With no notices and an unchanged digest, enqueue nothing.
- With no notices and a changed digest, enqueue `.keepCurrent`.
- With notices, enqueue `listWasEmpty ? .withSound : .silent`.
- Await the enqueued task, so the post still follows the save and `checkNow` still returns after it.

- [ ] **Step 5: Implement the notifier**

Replace `FailedNotice.notice` with a private `PendingPost { identifier, title, body, sound: Bool, category: String? }`. Implement the diagnostic path as pinned by `testNotificationStaysSeparateFromTheRollingAlert`.

`syncAlert`:
- `nil` digest, whatever the delivery: set a new `latestPosts[.package]`, clear `failures[.package]` and `lastAlertPost`, then call `service.removeDelivered([Self.alertIdentifier])`. The new token stops a retry that is waiting on authorization.
- Retain a current package payload independently of the failure slot, updating it on every nonnil sync. `.keepCurrent` updates that payload and any package failure's title/body, preserving its pending sound, without starting a post.
- After authorization suspensions and the `latestPosts` token guard, a package post reads the current payload rather than its pre-await copy. On failure retain that current payload. This applies to initial posts and retries; `shrinkDuringRetryPostsCurrentList` pins the nonempty mutation case.
- `.silent` and `.withSound`: post through the existing authorization path with `identifier: Self.alertIdentifier` and `categoryIdentifier = Self.alertIdentifier`. Set `content.sound` for `.withSound`, and for `.silent` when the pending package failure has a sound.

Set `lastAlertPost = now()` only on a successful current-token `.package` post. The timing tests in Review Focus define its use; diagnostic posts do not change it.

`NativeNotificationService` implements the new service methods. Its `init` registers `UNNotificationCategory(identifier: UserNotifier.alertIdentifier, actions: [], intentIdentifiers: [], options: [.customDismissAction])`. Update `SnapshotNotifications` and `SyntheticNotificationService`. The harness's Test posting failure button calls `syncAlert` with a synthetic digest.

Leave `alertWasCleared` at its default until the acknowledgement work.

- [ ] **Step 6: Run the tests and builders to verify they pass**

Run:

```bash
make -C brew_version test
make -C brew_version acceptance
make -C brew_version snapshots
```

Expected: all pass, which also proves the harness and snapshot sources still compile. Remove the directories those builders print.

- [ ] **Step 7: Commit**

Subject: `Consolidate Brew Version alerts into one rolling alert`. The body names the updated tests and why they changed, and records the lost-alert fix.

### Task 3: Acknowledge, clear and release

**Files:**
- Modify: `brew_version/Sources/BrewVersionCore/WatchController.swift` (`retryLoad`, `remove`, `skip`, `popoverClosed`, `checkNow`)
- Modify: `brew_version/Sources/BrewVersion/UserNotifier.swift`, `StatusItemController.swift` (`presentPanel`), `AppDelegate.swift` (`applicationDidFinishLaunching`)
- Modify: the files named in Global Constraints for the release version
- Modify: `brew_version/Tests/Acceptance/SyntheticTransport.swift`, `AcceptanceApp.swift`, `AcceptanceServiceTests.swift`
- Modify: `brew_version/README.md`, `docs/lessons_learned.md`
- Test: `brew_version/Tests/BrewVersionCoreTests/WatchControllerTests.swift`, `brew_version/Tests/BrewVersionCoreTests/ControllerRegressionTests.swift`, `brew_version/Tests/BrewVersionAppTests/NativeActionsTests.swift`, `brew_version/Tests/BrewVersionAppTests/StatusPanelTests.swift`, `brew_version/Tests/BrewVersionAppTests/WatchUndoTests.swift`

**Interfaces:**
- Consumes: `enqueueAlert`, `alertQueueDrained`, `UserNotifier.alertIdentifier`, `NotificationService.deliveredIdentifiers`, `NotificationService.removeDelivered`.
- Produces:
  - `WatchController.acknowledgeAlerts()` (public, synchronous, safe to call repeatedly).
  - `WatchController.reconcileAlert()` (public): enqueues `.keepCurrent` when `canSave`.
  - `UserNotifier.acknowledgeAlert: (() -> Void)?`
  - `UserNotifier.handleResponse(actionIdentifier: String, requestIdentifier: String)`
  - `UserNotifier.alertWasCleared() async -> Bool`, replacing the default.
  - `UserNotifier.removeLegacyAlerts() async`
  - `UserNotifier.deliveryGrace: TimeInterval`, a `static let` of `5`.
  - `NotificationService.listsInNotificationCenter() async -> Bool`

- [ ] **Step 1: Write the failing tests**

Core:

```swift
@Test func acknowledgingClearsListAndRemovesAlert() async throws {
    // After a check that alerts, acknowledgeAlerts() then alertQueueDrained():
    #expect(c.state.watched.allSatisfy { $0.alertPendingSince == nil })
    #expect(await notifier.lastSyncCleared)
    #expect(c.amberCount == 1) // Installed update stays amber.
}
@Test func acknowledgedPackagesStayOutOfTheNextAlert() async throws { /* a later update lists only itself, with sound */ }
@Test func skipRemoveAndUpgradeShrinkWithoutReposting() async throws {
    // Three listed: skip one, stop watching one, then a check sees the third upgraded.
    #expect(await notifier.notices.count == 1)
    #expect(await notifier.lastSyncCleared)
}
@Test func undoRestoresWithoutRelisting() async throws { /* restore leaves alertPendingSince nil and raises nothing */ }
@Test func clearedAlertStartsFreshList() async throws {
    // notifier.setCleared(true) before a check that finds a new update.
    #expect(await notifier.notices.last?.names == [newPackage])
    #expect(await notifier.deliveries.last == .withSound)
}
@Test func clearedAlertIsNotQueriedWithAnEmptyList() async { /* clearedQueries stays 0 */ }
@Test func failedAcknowledgementKeepsAlert() async throws {
    // A failing WatchStoreIO: the list stays in state and syncs gains no nil digest.
}
@Test func popoverClosedAcknowledgesAlertRaisedWhileOpen() async throws { /* popoverClosed clears the list for installed and uninstalled packages */ }
@Test func launchRemovesAlertWithNoList() async { /* empty list: reconcileAlert() records a nil digest and raises nothing */ }
@Test func launchKeepsListedAlertQuiet() async throws { /* saved list: reconcileAlert() appends .keepCurrent and notices stays empty */ }
@Test func retryLoadReconcilesAlert() async throws { /* retryLoad() after the store changes records the reloaded list's digest */ }
```

App:

```swift
@Test func dismissAcknowledgesWithoutOpeningPopover() {
    // handleResponse(actionIdentifier: UNNotificationDismissActionIdentifier, requestIdentifier: UserNotifier.alertIdentifier)
    // acknowledged 1, showPopover 0.
}
@Test func clickAcknowledgesAndOpensPopover() { /* default action: acknowledged 1, showPopover 1 */ }
@Test func clickingTestNotificationOpensPopoverWithoutAcknowledging() { /* UUID identifier: acknowledged 0, showPopover 1 */ }
@Test func recentPostIsNotTreatedAsCleared() async {
    // Post at t with deliveredIDs empty: false just inside deliveryGrace, true just outside it.
}
@Test func retryStartsGracePeriod() async { /* a post that fails then succeeds through retry() is inside the grace period */ }
@Test func alertWasClearedReadsDeliveredList() async {
    // Past deliveryGrace: deliveredIDs containing alertIdentifier gives false, empty gives true.
}
@Test func deniedNotificationsKeepTheList() async { /* status .denied, deliveredIDs empty: false */ }
@Test func pendingFailureIsNotTreatedAsCleared() async { /* failed post, deliveredIDs empty, past deliveryGrace: false */ }
@Test func notificationCenterOffNeverClears() async { /* listing off, deliveredIDs empty, past deliveryGrace: false */ }
@Test func clearDuringRetryDoesNotRepost() async {
    // After a failed post, the gate fires on the second authorizationStatus() call, the one inside the post path.
    // It calls syncAlert(nil, delivery: .keepCurrent): retry() posts no new request.
}
@Test func legacyCleanupKeepsTheRollingAlert() async {
    // deliveredIDs = ["synthetic-legacy-id", UserNotifier.alertIdentifier]: removed == ["synthetic-legacy-id"].
}
```

In `StatusPanelTests.swift`'s `DirectPanelOpeningTests`, add `openingPopoverAcknowledgesAlerts`. Give `PanelFixture` a stored controller and a local `Notifier` recorder of `syncAlert` digests, plus an init option for pending entries. Call `showPopover()`, drain the queue through the controller, and assert the list is empty and the recorder's last digest is `nil`.

In `AcceptanceServiceTests`, add `advanceStepsEachPackageIndependently`: repeated `advance()` steps only the formula, and `advanceCask()` steps only `synthetic-cask`, including its catalog entry.

- [ ] **Step 2: Run the tests to verify they fail**

Run the filtered command with pattern `WatchControllerTests|ControllerRegressionTests|NativeActionsTests|DirectPanelOpeningTests|WatchUndoTests`.
Expected: compile failure naming `acknowledgeAlerts`, `handleResponse` and `removeLegacyAlerts`.

- [ ] **Step 3: Implement the controller changes**

`acknowledgeAlerts()`: `guard canSave`, return if nothing is pending, clear every `alertPendingSince`, `guard commit(candidate)`, then `enqueueAlert(.keepCurrent)`.

`popoverClosed()` clears the field in its candidate and enqueues the same way when anything was pending.

`skip` clears that entry's field. `remove` clears the field on the entry it returns, so Undo cannot relist it. Both enqueue `.keepCurrent` when something was pending.

`retryLoad` calls `reconcileAlert()` after replacing state.

In `checkNow`, immediately after `refreshInstalled(extraListings:)` and before `let snapshot = cache.snapshot()`:

```swift
await alertQueue?.value
let alertCleared = state.watched.contains { $0.alertPendingSince != nil } ? await notifier.alertWasCleared() : false
```

When `alertCleared` is true, clear every candidate `alertPendingSince` immediately after `var candidate = state`, before `previousDigest` and `listWasEmpty` are computed.

- [ ] **Step 4: Implement the app changes**

`alertWasCleared()` returns `false` unless all of these hold: `service.authorizationStatus()` is `.authorized`, `service.listsInNotificationCenter()` is true, no package failure is pending, and `lastAlertPost` is `nil` or older than `deliveryGrace`. It then returns whether `deliveredIdentifiers()` lacks `alertIdentifier`.

`NativeNotificationService.listsInNotificationCenter()` reads `notificationCenterSetting == .enabled`. `SnapshotNotifications` and `SyntheticNotificationService` conform.

The UserNotifications delegate calls `handleResponse` on the main actor. `handleResponse` calls `acknowledgeAlert?()` when the request is the rolling alert, and calls `showPopover?()` unless the action is `UNNotificationDismissActionIdentifier`.

`removeLegacyAlerts()` removes every delivered identifier except `alertIdentifier`.

`StatusItemController.presentPanel()` calls `controller.acknowledgeAlerts()` after `makeKeyAndOrderFront`.

`AppDelegate.applicationDidFinishLaunching` sets `notifier.acknowledgeAlert = { [weak controller] in controller?.acknowledgeAlerts() }`. It runs `await notifier.removeLegacyAlerts()` and `controller.reconcileAlert()` in the launch `Task` before `hydrateCatalog()`. `AcceptanceApp` sets the same closure.

- [ ] **Step 5: Extend the acceptance harness**

`SyntheticTransport`: `advance()` steps the formula one major version per call, keeping its first result unchanged for `baselineAdvanceAndCatalogAreSynthetic`. `advanceCask()` does the same for `synthetic-cask`, including the catalog list.

In `AcceptanceDelegate.applicationDidFinishLaunching`, add delayed controls for the native gate:
- **Both in 5s:** after 5 seconds, advance both packages, call `SyntheticEnvironment.advanceRefreshClock()`, and call `checkNow()`.
- **Cask then formula:** after 5 seconds, advance the cask, advance the clock and check. After 20 more seconds, do the same for the formula.

- [ ] **Step 6: Bump the version and update docs**

Set the release version from Global Constraints.

Update `brew_version/README.md`:
- Reconcile the Taps, Saved watches and checks, and Menu bar app sections with Behavior; keep one authoritative explanation in the README and cross-reference it elsewhere.
- Document compatibility using `stateWithoutAlertListLoads` and `entryDecodingIgnoresUnknownKeys` as the source.
- Update Settings and native acceptance gates from this task's native gate, including its harness controls and the macOS 27 evidence.

Add a dated `docs/lessons_learned.md` entry covering the delivered-list and `usernoted` observations in the macOS 27 evidence section, and the single retry slot that lost alerts. Name `failedPostLeavesPackagesListed` and `recentPostIsNotTreatedAsCleared`.

- [ ] **Step 7: Run the full automated gate**

Run every `brew_version` command in the Validation Matrix in `agents.md`, plus the CLI smoke checks it lists.

Use the Validation Matrix's acceptance criteria. Compare every snapshot PNG with a build of the base commit, inspect each image, and explain any difference. Remove each directory the builders print.

- [ ] **Step 8: Run the native gate with the owner**

Use a fresh harness home according to the macOS 27 evidence. Run these commands in one shell session:

```bash
harness_home="$HOME/.brew-version-harness-$(date +%s)"
BREW_VERSION_HARNESS_HOME="$harness_home" make -C brew_version acceptance
```

Open the printed app and watch `synthetic-formula` and `synthetic-cask`. Establish authorization before proceeding, using the macOS 27 evidence for Settings placement. Record each result separately against Behavior. Before each delayed step, press the button, then click elsewhere to close the popover:

- **Both in 5s:** verify the same-check ordering and initial-delivery rows; then verify the click row.
- **Cask then formula:** verify the initial-delivery and outstanding-list replacement rows, newest-first order, and delivered entry count; then open from the mug and verify the popover row.
- **Cask then formula:** dismiss the cask alert and verify the dismiss row; verify the formula alert against the empty-list row and require that it names only the formula. Acknowledge it before continuing.
- **Both in 5s:** let the banner slide away, then clear it in Notification Center and verify the corresponding row. Then **Cask then formula:** verify the new cask alert against the empty-list row and require that it names only the cask. Wait for the scheduled formula alert, verify the outstanding-list row, and acknowledge it before continuing.
- **Test posting failure**, then **Retry notifications:** verify the failure/retry row and require the error to clear. No delayed sequence may remain running at this step.

When finished, turn the harness's login toggle off, quit it, and remove its home:

```bash
rm -r -- "$harness_home"
```

Follow the deployment guide referenced in Global Constraints for installed acceptance.

- [ ] **Step 9: Commit**

Subject: `Clear Brew Version's rolling alert on acknowledgement and release`. The body records the release version, the acknowledgement rules and the harness's delayed buttons.

## Rejected alternatives

- **One alert per check only:** leaves separate overnight checks as separate alerts, which the owner's request covers.
- **Delay window or hold-until-wake:** adds latency, and the rolling alert already merges checks.
- **`threadIdentifier` grouping:** still leaves individual alerts to clear.
- **Saving `Notice` values in the list:** would duplicate entry state and could go stale.
- **Capping the body at a package count:** use the Behavior table's display-limit policy instead.
