import Foundation
import Testing
@testable import BrewVersionCore

// Blocks only a background scan; a mistaken main-actor scan records the error
// and returns so the regression fails without deadlocking the test process.
private final class ControlledInstallation: InstalledReading, @unchecked Sendable {
    private let lock = NSLock()
    private let gate = DispatchSemaphore(value: 0)
    private var scans = 0
    private var mainActorScan = false
    let reader: InstalledReader
    init(_ reader: InstalledReader) { self.reader = reader }
    var count: Int { lock.withLock { scans } }
    var scannedMainThread: Bool { lock.withLock { mainActorScan } }
    func snapshot(listings: [Listing]) -> InstalledSnapshot {
        let captured = reader.snapshot(listings: listings)
        let first = lock.withLock {
            scans += 1; mainActorScan = mainActorScan || Thread.isMainThread
            return scans == 1
        }
        if first && !Thread.isMainThread { _ = gate.wait(timeout: .now() + 5) }
        return captured
    }
    func release() { gate.signal() }
}

@MainActor struct InstallationSnapshotTests {
    @Test func otherUpdatesAdmitsEachReceiptOnce() async throws {
        let f = try InstallationFixture()
        try f.install("prefix/Cellar/synthetic-formula/1", kind: .formula)
        try f.install("prefix/Caskroom/synthetic-cask/1", kind: .cask)
        let catalog = try await seedCatalog(f.root.appendingPathComponent("catalog"))
        let reads = ReceiptReads()
        let reader = InstalledReader(prefixes: HomebrewPrefix.detectAll(candidates: [f.root.appendingPathComponent("prefix")]),
                                     applicationDirectories: [], readData: { url in
            reads.record(url); return try Data(contentsOf: url)
        })
        let updates = otherUpdates(catalog: catalog, installed: reader, watched: [])
        #expect(updates.map(\.listing.name.rawValue) == ["synthetic-cask", "synthetic-formula"])
        #expect(reads.count == 2)
    }
    @Test func blockedScanLeavesMainActorResponsiveAndUnrelatedCommitsDoNotScan() async throws {
        let f = try InstallationFixture()
        try f.install("prefix/Cellar/synthetic-formula/1", kind: .formula)
        let directory = f.root.appendingPathComponent("catalog"); _ = try await seedCatalog(directory)
        let reader = ControlledInstallation(f.reader())
        let store = WatchStore(fileURL: f.root.appendingPathComponent("state/state.json"))
        var state = AppState.initial; state.watched = [baseline()]; try store.save(state)
        let c = WatchController(transport: StubTransport([:]), installed: reader,
                                store: store,
                                notifier: RecordingNotifier(), catalogClient: CatalogClient(transport: StubTransport([:]), cacheDirectory: directory))
        let hydration = Task { await c.hydrateCatalog() }
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while reader.count == 0 && ContinuousClock.now < deadline { await Task.yield() }
        try #require(reader.count == 1)
        #expect(!reader.scannedMainThread)
        c.setInterval(CheckInterval(minutes: 60)!); c.popoverClosed(); c.setOtherUpdatesCollapsed(true); c.skip(watchName)
        #expect(reader.count == 1)
        #expect(c.others.isEmpty)
        reader.release(); await hydration.value
        #expect(c.others.map(\.listing.name.rawValue) == ["synthetic-formula"])
        c.setInterval(CheckInterval(minutes: 90)!); c.popoverClosed()
        #expect(reader.count == 1)
    }
    @Test func olderBlockedSnapshotCannotReplaceNewerInstallation() async throws {
        let f = try InstallationFixture()
        try f.install("prefix/Cellar/synthetic-formula/1", kind: .formula)
        let directory = f.root.appendingPathComponent("catalog"); _ = try await seedCatalog(directory)
        let reader = ControlledInstallation(f.reader())
        let c = WatchController(transport: StubTransport([:]), installed: reader,
                                store: WatchStore(fileURL: f.root.appendingPathComponent("state/state.json")),
                                notifier: RecordingNotifier(), catalogClient: CatalogClient(transport: StubTransport([:]), cacheDirectory: directory))
        let hydration = Task { await c.hydrateCatalog() }
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while reader.count == 0 && ContinuousClock.now < deadline { await Task.yield() }
        try #require(reader.count == 1)
        try f.install("prefix/Cellar/synthetic-formula/3", kind: .formula)
        await c.checkNow()
        #expect(reader.count == 2 && c.others.isEmpty)
        reader.release(); await hydration.value
        #expect(c.others.isEmpty)
    }
    @Test func removedAndRestoredWatchCannotRegainCacheFromSuspendedCheck() async throws {
        let f = try InstallationFixture()
        let store = WatchStore(fileURL: f.root.appendingPathComponent("state/state.json"))
        var state = AppState.initial; state.watched = [baseline()]
        state.listingCache = [watchURL(): CachedListing(etag: "synthetic-old", listing: watchListing())]
        try store.save(state)
        let reader = ControlledInstallation(f.reader())
        let c = WatchController(transport: StubTransport([watchURL(): [watchResponse("2", etag: "synthetic-new")]]),
                                installed: reader, store: store, notifier: RecordingNotifier())
        let check = Task { await c.checkNow() }
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while reader.count == 0 && ContinuousClock.now < deadline { await Task.yield() }
        try #require(reader.count == 1)
        let removed = try #require(c.remove(watchName))
        c.restore(removed.entry, at: removed.index)
        reader.release(); await check.value
        #expect(c.state.watched[0] == removed.entry)
        #expect(store.load().state.listingCache.isEmpty)
    }
    @Test func supersededCheckUsesCurrentInstallationForPersistenceAmberAndNotices() async throws {
        let f = try InstallationFixture()
        try f.install("prefix/Cellar/synthetic-watch/1", kind: .formula)
        let store = WatchStore(fileURL: f.root.appendingPathComponent("state/state.json"))
        var state = AppState.initial; state.watched = [baseline()]; try store.save(state)
        let reader = ControlledInstallation(f.reader())
        let notifier = RecordingNotifier(store: store)
        let transport = StubTransport([watchURL(): [watchResponse("2"), watchResponse("2")]])
        let c = WatchController(transport: transport, installed: reader, store: store, notifier: notifier)
        let check = Task { await c.checkNow() }
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while reader.count == 0 && ContinuousClock.now < deadline { await Task.yield() }
        try #require(reader.count == 1)
        try f.install("prefix/Cellar/synthetic-watch/2", kind: .formula)
        await c.search(watchName.rawValue)
        guard case .found(_, let installed, _) = c.results.first else { Issue.record("Expected current installed search result"); reader.release(); await check.value; return }
        #expect(installed?.version == "2")
        reader.release(); await check.value
        #expect(store.load().state.watched[0].installed?.version == "2")
        #expect(c.amberCount == 0)
        #expect(await notifier.notices.isEmpty)
    }
    @Test func concurrentAddCacheSurvivesAnOlderBlockedCheck() async throws {
        let f = try InstallationFixture()
        let store = WatchStore(fileURL: f.root.appendingPathComponent("state/state.json"))
        var state = AppState.initial; state.watched = [baseline()]; try store.save(state)
        let added = PackageName("synthetic-added")!
        let transport = StubTransport([watchURL(): [watchResponse("2", etag: "synthetic-check")],
                                       watchURL(added): [watchResponse("1", etag: "synthetic-add")]])
        let reader = ControlledInstallation(f.reader())
        let c = WatchController(transport: transport, installed: reader, store: store, notifier: RecordingNotifier())
        let check = Task { await c.checkNow() }
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while reader.count == 0 && ContinuousClock.now < deadline { await Task.yield() }
        try #require(reader.count == 1)
        await c.add(added, kind: .formula)
        #expect(store.load().state.listingCache[watchURL(added)]?.etag == "synthetic-add")
        reader.release(); await check.value
        let saved = store.load().state
        #expect(saved.watched.map(\.name) == [watchName, added])
        #expect(saved.listingCache[watchURL(added)]?.etag == "synthetic-add")
        #expect(saved.listingCache[watchURL()]?.etag == "synthetic-check")
    }
}

private final class ReceiptReads: @unchecked Sendable {
    private let lock = NSLock()
    private var reads = 0
    var count: Int { lock.withLock { reads } }
    func record(_ url: URL) {
        if url.lastPathComponent == "INSTALL_RECEIPT.json" { lock.withLock { reads += 1 } }
    }
}
