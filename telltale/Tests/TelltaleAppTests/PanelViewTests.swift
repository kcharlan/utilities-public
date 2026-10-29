import AppKit
import Synchronization
import SwiftUI
import Testing
import TelltaleCore
import TelltaleTestSupport
import UserNotifications
@testable import Telltale

private struct SyntheticKickstartFailure: LocalizedError {
    var errorDescription: String? { "Synthetic kickstart failure" }
}

/// Spec section 9.1's panel and section 4's narrow read-write path (`UserActions`).
@MainActor @Suite struct PanelViewTests {
    @Test func failedAcknowledgeDoesNotRemoveNotifications() async throws {
        try await withAsyncScratchDirectory { directory in
            let paths = PanelWorld.paths(directory)
            let service = NotificationServiceStub()
            let content = UNMutableNotificationContent()
            content.threadIdentifier = "synthetic.thread"
            service.deliveredNotifications = [try deliveredNotification(for: UNNotificationRequest(identifier: "synthetic-notice", content: content, trigger: nil))]
            let model = PanelModel(store: PanelWorld.live(paths), actions: PanelWorld.actions(paths), notifier: UserNotifier(service: service))
            model.acknowledge([PanelSnapshot.Alert(color: .amber, text: "Synthetic", key: "synthetic", threadID: "synthetic.thread")])
            await Task.yield()
            #expect(model.actionError != nil && service.removedIdentifiers.isEmpty)
            #expect(!FileManager.default.fileExists(atPath: paths.database.path))
        }
    }
    @Test func acknowledgeAndMarkAsNewRoundTrip() throws {
        try withScratchDirectory { directory in
            let paths = PanelWorld.paths(directory)
            let writer = try PanelWorld.seed(paths)
            try PanelWorld.addAlert(writer)
            let live = PanelWorld.live(paths)
            let model = PanelModel(store: live, actions: PanelWorld.actions(paths), notifier: UserNotifier(service: NotificationServiceStub()))
            model.acknowledge(live.snapshot.alerts)
            live.reload()
            let alert = try #require(live.snapshot.alerts.first)
            #expect(alert.acknowledgedAt != nil && live.snapshot.attention == nil)
            model.markAsNew(alert)
            live.reload()
            #expect(live.snapshot.alerts.first?.acknowledgedAt == nil && live.snapshot.attention == .amber)
        }
    }
    @Test func successfulAcknowledgeRemovesMatchingNotifications() async throws {
        try await withAsyncScratchDirectory { directory in
            let paths = PanelWorld.paths(directory)
            let writer = try PanelWorld.seed(paths)
            try PanelWorld.addAlert(writer)
            let live = PanelWorld.live(paths)
            let alert = try #require(live.snapshot.alerts.first)
            let thread = try #require(alert.threadID)
            let service = NotificationServiceStub()
            let content = UNMutableNotificationContent(); content.threadIdentifier = thread
            service.deliveredNotifications = [try deliveredNotification(for: UNNotificationRequest(identifier: "synthetic-notice", content: content, trigger: nil))]
            let model = PanelModel(store: live, actions: PanelWorld.actions(paths), notifier: UserNotifier(service: service))
            model.acknowledge([alert])
            #expect(await eventually { service.removedIdentifiers == ["synthetic-notice"] })
            #expect(model.actionError == nil)
        }
    }
    @Test func acknowledgeAllCoversOnlyTheAlertsShown() throws {
        try withScratchDirectory { directory in
            let paths = PanelWorld.paths(directory)
            let writer = try PanelWorld.seed(paths)
            try PanelWorld.addAlert(writer)
            let live = PanelWorld.live(paths)
            let shown = live.snapshot.alerts
            let onset = Synth.local(2026, 9, 4, 9, 0)
            try writer.insertEpisode(EpisodeRow(rule: RuleID.slower.rawValue, provider: ProviderID.codex.rawValue, scope: "synthetic-second-model", direction: .slower, onset: onset, firedAt: onset, severity: LampColor.amber.rawValue, worstValue: 0.75))
            let model = PanelModel(store: live, actions: PanelWorld.actions(paths), notifier: UserNotifier(service: NotificationServiceStub()))
            model.acknowledge(shown)
            live.reload()
            #expect(live.snapshot.alerts.count == 2)
            #expect(live.snapshot.alerts.filter { $0.acknowledgedAt == nil }.count == 1)
        }
    }
    @Test func rendersNothingToReportWhenQuiet() throws {
        try withScratchDirectory { directory in
            let paths = PanelWorld.paths(directory)
            try PanelWorld.seed(paths)
            let model = PanelModel(store: PanelWorld.live(paths), actions: PanelWorld.actions(paths), notifier: UserNotifier(service: NotificationServiceStub()), calendar: Synth.newYork)
            #expect(model.emptyMessage == "Nothing to report.")
            #expect(model.checkedText == "Checked 09:29")
            #expect(model.store.snapshot.signals == [.speed, .errors, .link, .provider, .load, .collector])
            // The strip leaves Collector to the footer.
            #expect(model.stripSignals == [.speed, .errors, .link, .provider, .load])
            let host = NSHostingView(rootView: PanelView(model: model, openSettings: {}, openDashboard: nil))
            #expect(host.fittingSize.width == 340)
            let quietHeight = host.fittingSize.height
            // The rendered text isn't asserted here: even hosted in an offscreen window, SwiftUI
            // publishes no accessibility children without an assistive client (probed: the hosting
            // view reports 0), and AppKit exposes no text otherwise. The snapshot harness
            // (Tests/Snapshots) checks each scene's snapshot and its PNGs are read by eye; here the
            // panel lays out at its width and follows the model's empty message.

            // A two-line alert replaces the one-line empty message.
            try PanelWorld.addAlert(try Store.open(paths.database, mode: .readWrite))
            model.store.reload()
            #expect(model.emptyMessage == nil)
            host.layoutSubtreeIfNeeded()
            #expect(host.fittingSize.height > quietHeight)
        }
    }

    @Test func waitingPanelHasNoCheckedTime() throws {
        try withScratchDirectory { directory in
            let paths = PanelWorld.paths(directory)
            let model = PanelModel(store: PanelWorld.live(paths), actions: PanelWorld.actions(paths), notifier: UserNotifier(service: NotificationServiceStub()), calendar: Synth.newYork)
            #expect(model.checkedText == nil)
            #expect(model.store.snapshot.footer == "Waiting for the collector's first run.")
            #expect(!FileManager.default.fileExists(atPath: paths.database.path))
        }
    }

    @Test func checkNowCallsKickstart() async throws {
        try await withAsyncScratchDirectory { directory in
            let paths = PanelWorld.paths(directory)
            try PanelWorld.seed(paths)
            let kicks = Mutex(0)
            let fails = Mutex(false)
            let actions = PanelWorld.actions(paths) {
                kicks.withLock { $0 += 1 }
                if fails.withLock({ $0 }) { throw SyntheticKickstartFailure() }
            }
            let model = PanelModel(store: PanelWorld.live(paths), actions: actions, notifier: UserNotifier(service: NotificationServiceStub()), calendar: Synth.newYork)
            await model.checkNow()
            #expect(kicks.withLock { $0 } == 1)
            #expect(!model.checking && model.actionError == nil)

            fails.withLock { $0 = true }
            await model.checkNow()
            #expect(kicks.withLock { $0 } == 2)
            #expect(model.actionError == "Synthetic kickstart failure")
            fails.withLock { $0 = false }
            await model.checkNow()
            #expect(model.actionError == nil)
        }
    }

    @Test func actionsNeverCreateTheDatabase() async throws {
        try await withAsyncScratchDirectory { directory in
            let paths = PanelWorld.paths(directory)
            let actions = PanelWorld.actions(paths)
            #expect(throws: StoreError.notInitialized) { try actions.set(.collectorEnabled, false) }
            #expect(throws: StoreError.notInitialized) { try actions.requestRebuild() }
            #expect(throws: StoreError.notInitialized) { try actions.requestRebuild(provider: .codex) }
            #expect(throws: StoreError.notInitialized) { try actions.dismissArrival(provider: .codex) }
            #expect(throws: StoreError.notInitialized) { try actions.acknowledge([PanelSnapshot.Alert(color: .amber, text: "Synthetic", key: "synthetic")]) }
            #expect(throws: StoreError.notInitialized) { try actions.markAsNew(key: "synthetic") }
            #expect(!FileManager.default.fileExists(atPath: paths.appSupport.path))

            // A file the collector created but hasn't migrated is left alone too (ruling R27).
            try FileManager.default.createDirectory(at: paths.appSupport, withIntermediateDirectories: true)
            #expect(FileManager.default.createFile(atPath: paths.database.path, contents: Data()))
            #expect(throws: StoreError.notInitialized) { try actions.set(.collectorEnabled, false) }
            #expect(throws: StoreError.notInitialized) { try actions.acknowledge([PanelSnapshot.Alert(color: .amber, text: "Synthetic", key: "synthetic")]) }
            #expect(throws: StoreError.notInitialized) { try actions.markAsNew(key: "synthetic") }
            #expect(try FileManager.default.attributesOfItem(atPath: paths.database.path)[.size] as? Int == 0)
            try FileManager.default.removeItem(at: paths.database)

            try PanelWorld.seed(paths)
            try actions.set(.collectorEnabled, false)
            try actions.requestRebuild()
            try actions.requestRebuild(provider: .codex)
            let store = try Store.open(paths.database, mode: .readOnly)
            #expect(try store.value(.collectorEnabled) == false)
            #expect(try store.value(.rebuildRequestedAt) == PanelWorld.now)
            #expect(try store.value(.providerRebuildRequests) == ["codex": PanelWorld.now])
        }
    }

    @Test func dismissArrivalPersistsAtomically() throws {
        try withScratchDirectory { directory in
            let paths = PanelWorld.paths(directory)
            try PanelWorld.seed(paths)
            let store = try Store.open(paths.database, mode: .readWriteExisting)
            try store.set(.pendingArrivals, ["codex", "synthetic-other"])
            try PanelWorld.actions(paths).dismissArrival(provider: .codex)
            let reader = try Store.open(paths.database, mode: .readOnly)
            #expect(try reader.value(.pendingArrivals) == ["synthetic-other"])
            #expect(try reader.value(.dismissedArrivals) == ["codex"])
        }
    }

    @Test func dismissedArrivalStaysHiddenAfterReload() throws {
        try withScratchDirectory { directory in
            let paths = PanelWorld.paths(directory)
            let store = try PanelWorld.seed(paths)
            try store.set(.pendingArrivals, ["codex"])
            try store.setBackfill(ProviderBackfill(reason: .new, startedAt: PanelWorld.now, through: PanelWorld.now, finishedAt: PanelWorld.now, announce: true), unit: "codex")
            let live = PanelWorld.live(paths)
            #expect(live.snapshot.arrivals.first?.firstModel == Synth.model)
            let model = PanelModel(store: live, actions: PanelWorld.actions(paths), notifier: UserNotifier(service: NotificationServiceStub()))
            model.dismissArrival(.codex)
            #expect(live.snapshot.arrivals.isEmpty)
            #expect(PanelWorld.live(paths).snapshot.arrivals.isEmpty)
        }
    }

    @Test func shiftPromptAcceptsAndUndoes() throws {
        try withScratchDirectory { directory in
            let paths = PanelWorld.paths(directory)
            try seedShift(paths)
            let live = LiveStore(paths: paths, sources: PanelWorld.sources, calendar: Synth.newYork, now: { Synth.local(2026, 9, 17, 12) }, health: { nil })
            let actions = UserActions(paths: paths, calendar: Synth.newYork, now: { Synth.local(2026, 9, 17, 12) }, kickstart: {}, changed: { live.reload() })
            let model = PanelModel(store: live, actions: actions, notifier: UserNotifier(service: NotificationServiceStub()), calendar: Synth.newYork)
            let shift = try #require(live.snapshot.shift)
            #expect(live.snapshot.shiftText == "Example has been about 25% slower than usual for 3 days. Accept as usual?")
            #expect(model.acceptSince(for: shift) == Synth.local(2026, 9, 15))

            model.accept(shift, since: Synth.local(2026, 9, 15))
            #expect(model.actionError == nil)
            let confirmation = try #require(model.confirmation)
            #expect(confirmation.text.hasPrefix("Example's usual speed is now ") && confirmation.text.hasSuffix(" than before."))
            #expect(live.snapshot.shift == nil)

            model.undoAcceptance()
            #expect(model.confirmation == nil && model.actionError == nil)
            #expect(live.snapshot.shift != nil)

            model.keepAsAbnormal(try #require(live.snapshot.shift))
            #expect(live.snapshot.shift == nil && model.actionError == nil)
        }
    }

    /// R31: the panel's lasting-shift prompt links to the status-page incidents in its period.
    @Test func shiftPromptLinksItsIncidents() throws {
        try withScratchDirectory { directory in
            let paths = PanelWorld.paths(directory)
            try seedShift(paths)
            try Store.open(paths.database, mode: .readWrite).upsert(incidents: [PanelWorld.incident(published: Synth.local(2026, 9, 16, 10))])
            let live = LiveStore(paths: paths, sources: PanelWorld.sources, calendar: Synth.newYork, now: { Synth.local(2026, 9, 17, 12) }, health: { nil })
            let actions = UserActions(paths: paths, calendar: Synth.newYork, now: { Synth.local(2026, 9, 17, 12) }, kickstart: {}, changed: { live.reload() })
            let model = PanelModel(store: live, actions: actions, notifier: UserNotifier(service: NotificationServiceStub()), calendar: Synth.newYork)
            #expect(model.shiftIncidents.map(\.name) == ["Synthetic slow responses"])
            #expect(model.shiftIncidents.map(\.link) == [URL(string: "https://status.example.com/incidents/inc_synthetic_07")!])
        }
    }

    /// The snapshot harness showed a 2 tok/s wobble around usual 42 drawn as a full-height wave:
    /// the scale has a floor of a quarter of usual, so noise stays small and a 26% drop still fills it.
    @Test func sparklineKeepsSmallWobblesSmall() {
        let rect = CGRect(x: 0, y: 0, width: 64, height: 16)
        let wobble = Sparkline(values: [41, 43, 41, 43, nil, 42], reference: 42).path(in: rect).boundingRect
        #expect(wobble.height < rect.height / 2)
        #expect(wobble.minY >= rect.minY && wobble.maxY <= rect.maxY)
        let drop = Sparkline(values: [42, 42, 31, 31], reference: 42).path(in: rect).boundingRect
        #expect(drop.height > rect.height * 0.75)
        #expect(drop.minY >= rect.minY && drop.maxY <= rect.maxY)
    }

    /// Sep 1–14 at 40 tok/s, then Sep 15–17 at 30 tok/s inside a slower episode each day.
    private func seedShift(_ paths: TelltalePaths) throws {
        let store = try Store.open(paths.database, mode: .readWrite)
        var synth = Synth()
        for day in 1...14 { try store.upsert(responses: synth.responses(20, throughput: 40, from: Synth.local(2026, 9, day, 9))) }
        for day in 15...17 {
            try store.upsert(responses: synth.responses(10, throughput: 30, from: Synth.local(2026, 9, day, 9)))
            try store.insertEpisode(EpisodeRow(
                rule: RuleID.slower.rawValue, provider: ProviderID.codex.rawValue, scope: Synth.model, direction: .slower,
                onset: Synth.local(2026, 9, day, 8, 50), firedAt: Synth.local(2026, 9, day, 9, 5), endedAt: Synth.local(2026, 9, day, 9, 30),
                endReason: EpisodeRow.EndReason.cleared, severity: LampColor.amber.rawValue, worstValue: 0.75))
        }
    }
}

