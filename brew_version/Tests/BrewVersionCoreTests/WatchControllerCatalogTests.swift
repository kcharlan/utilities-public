import Foundation
import Testing
@testable import BrewVersionCore

@MainActor private final class CatalogClock {
    var date = Date(timeIntervalSince1970: 1_000_000)
}

extension WatchControllerTests {
    @Test(arguments: ["absent", "fresh", "overdue"])
    func catalogRefreshUsesSuccessfulFetchCadence(_ status: String) async throws {
        let f = WatchFixture(); defer { f.clean() }
        let clock = CatalogClock()
        var state = AppState.initial
        state.lastCatalogFetch = clock.date.addingTimeInterval(status == "overdue" ? -86400 : 0)
        try f.store.save(state)
        let directory = f.directory.appendingPathComponent("catalog")
        if status != "absent" { _ = try await seedCatalog(directory) }
        let transport = catalogStub()
        let c = WatchController(transport: StubTransport([:]), installed: nil, store: f.store,
                                notifier: RecordingNotifier(), now: { clock.date },
                                catalogClient: CatalogClient(transport: transport, cacheDirectory: directory))
        await c.refreshCatalogIfDue()
        #expect(await transport.requests.count == (status == "fresh" ? 0 : 2))
        #expect(c.catalog?.suggestions(prefix: "").count == 2)
        #expect(c.state.lastCatalogFetch == clock.date)
    }
    @Test func hiddenOtherUpdatesKeepsSuggestions() async throws {
        let f = WatchFixture(); defer { f.clean() }
        var state = AppState.initial; state.showOtherUpdates = false; try f.store.save(state)
        let transport = catalogStub()
        let c = WatchController(transport: StubTransport([:]), installed: nil, store: f.store, notifier: RecordingNotifier(),
                                catalogClient: CatalogClient(transport: transport, cacheDirectory: f.directory.appendingPathComponent("catalog")))
        await c.hydrateCatalog(); await c.scheduledTick()
        #expect(await transport.requests.count == 2)
        #expect(c.catalog?.suggestions(prefix: "synthetic").count == 2 && c.others.isEmpty)
        c.retryLoad()
        #expect(c.catalog?.suggestions(prefix: "synthetic").count == 2)
    }
    @Test func restartHydratesBeforeDue() async throws {
        let f = try InstallationFixture()
        try f.install("prefix/Cellar/synthetic-formula/1", kind: .formula)
        let directory = f.root.appendingPathComponent("cache"); _ = try await seedCatalog(directory)
        let store = WatchStore(fileURL: f.root.appendingPathComponent("state/state.json"))
        let clock = CatalogClock()
        var state = AppState.initial; state.lastCatalogFetch = clock.date; try store.save(state)
        let transport = StubTransport([:])
        let c = WatchController(transport: transport, installed: f.reader(), store: store, notifier: RecordingNotifier(),
                                now: { clock.date }, catalogClient: CatalogClient(transport: transport, cacheDirectory: directory))
        await c.hydrateCatalog()
        #expect(c.catalog?.suggestions(prefix: "synthetic").count == 2)
        #expect(c.others.map(\.listing.name.rawValue) == ["synthetic-formula"])
        await c.refreshCatalogIfDue()
        #expect(await transport.requests.isEmpty)
    }
    @Test func watchingAnOtherUpdateMovesIt() async throws {
        let f = try InstallationFixture()
        try f.install("prefix/Cellar/synthetic-formula/1", kind: .formula)
        let directory = f.root.appendingPathComponent("cache"); _ = try await seedCatalog(directory)
        let c = WatchController(transport: StubTransport([watchURL(PackageName("synthetic-formula")!): [watchResponse("2")]]),
                                installed: f.reader(), store: WatchStore(fileURL: f.root.appendingPathComponent("state/state.json")),
                                notifier: RecordingNotifier(), catalogClient: CatalogClient(transport: StubTransport([:]), cacheDirectory: directory))
        await c.hydrateCatalog()
        #expect(c.others.count == 1)
        await c.add(PackageName("synthetic-formula")!, kind: .formula)
        #expect(c.others.isEmpty && c.state.watched.count == 1)
    }
    @Test func stopWatchingReturnsItToOthers() async throws {
        let f = try InstallationFixture()
        try f.install("prefix/Cellar/synthetic-formula/1", kind: .formula)
        let directory = f.root.appendingPathComponent("cache"); _ = try await seedCatalog(directory)
        let name = PackageName("synthetic-formula")!
        let store = WatchStore(fileURL: f.root.appendingPathComponent("state/state.json"))
        var state = AppState.initial; state.watched = [WatchEntry(name: name, kind: .formula)]; try store.save(state)
        let c = WatchController(transport: StubTransport([:]), installed: f.reader(), store: store, notifier: RecordingNotifier(),
                                catalogClient: CatalogClient(transport: StubTransport([:]), cacheDirectory: directory))
        await c.hydrateCatalog(); #expect(c.others.isEmpty)
        let removed = try #require(c.remove(name)); #expect(c.others.count == 1)
        c.restore(removed.entry, at: removed.index); #expect(c.others.isEmpty)
    }
    @Test func failedRefreshDoesNotAdvanceFetchTime() async throws {
        let f = WatchFixture(); defer { f.clean() }
        let directory = f.directory.appendingPathComponent("catalog"); _ = try await seedCatalog(directory)
        let clock = CatalogClock()
        var state = AppState.initial; state.lastCatalogFetch = clock.date.addingTimeInterval(-86400); try f.store.save(state)
        let transport = StubTransport([catalogURL(.formula): [catalogResponse(500), catalogResponse(500), catalogResponse(500)]])
        let c = WatchController(transport: StubTransport([:]), installed: nil, store: f.store, notifier: RecordingNotifier(),
                                now: { clock.date }, catalogClient: CatalogClient(transport: transport, cacheDirectory: directory))
        await c.refreshCatalogIfDue(); await c.refreshCatalogIfDue()
        #expect(await transport.requests.count == 1)
        #expect(c.state.lastCatalogFetch == state.lastCatalogFetch)
        clock.date.addTimeInterval(1799); await c.refreshCatalogIfDue(); #expect(await transport.requests.count == 1)
        clock.date.addTimeInterval(1); await c.refreshCatalogIfDue(); #expect(await transport.requests.count == 2)
        await c.refreshCatalogIfDue(); #expect(await transport.requests.count == 2)
        #expect(f.store.load().state.lastCatalogFetch == state.lastCatalogFetch)
    }
    @Test func reenablingOtherUpdatesHydratesThenChecksDue() async throws {
        let f = WatchFixture(); defer { f.clean() }
        let directory = f.directory.appendingPathComponent("catalog"); _ = try await seedCatalog(directory)
        let clock = CatalogClock()
        var state = AppState.initial; state.showOtherUpdates = false; try f.store.save(state)
        let transport = ControlledCatalogTransport()
        let c = WatchController(transport: StubTransport([:]), installed: nil, store: f.store, notifier: RecordingNotifier(),
                                now: { clock.date }, catalogClient: CatalogClient(transport: transport, cacheDirectory: directory))
        c.setShowOtherUpdates(true)
        try await waitForCatalogRequests(1, on: transport)
        #expect(c.catalog?.suggestions(prefix: "").count == 2)
        #expect(c.state.showOtherUpdates)
        await transport.finish(.formula)
        try await waitForCatalogRequests(1, on: transport)
        await transport.finish(.cask)
        try await waitForCatalogIdle(c)
        #expect(c.state.lastCatalogFetch == clock.date)
        c.setOtherUpdatesCollapsed(true)
        #expect(f.store.load().state.otherUpdatesCollapsed)
        c.setShowOtherUpdates(false)
        #expect(c.catalog?.suggestions(prefix: "synthetic").count == 2 && c.others.isEmpty)
    }
    @Test func catalogPersistenceFailureKeepsCommittedState() async throws {
        let f = WatchFixture(); defer { f.clean() }
        try f.store.save(.initial)
        let bytes = try Data(contentsOf: f.file)
        let failures = IOFailures(); failures.operation = "replace"
        let c = WatchController(transport: StubTransport([:]), installed: nil,
                                store: WatchStore(fileURL: f.file, io: failures.io), notifier: RecordingNotifier(),
                                catalogClient: CatalogClient(transport: catalogStub(), cacheDirectory: f.directory.appendingPathComponent("catalog")))
        await c.refreshCatalogIfDue()
        #expect(c.state.lastCatalogFetch == nil && c.persistenceError != nil)
        #expect(c.catalog == nil)
        #expect(try Data(contentsOf: f.file) == bytes)
        c.setShowOtherUpdates(false)
        #expect(c.state.showOtherUpdates)
        c.setOtherUpdatesCollapsed(true)
        #expect(!c.state.otherUpdatesCollapsed)
    }
    @Test func scheduledTickRefreshesDaily() async throws {
        let f = WatchFixture(); defer { f.clean() }
        let directory = f.directory.appendingPathComponent("catalog"); _ = try await seedCatalog(directory)
        let clock = CatalogClock()
        var state = AppState.initial
        state.lastCheck = clock.date; state.lastCatalogFetch = clock.date
        state.watched = [baseline()]; try f.store.save(state)
        let watches = StubTransport([watchURL(): [watchResponse("2"), watchResponse("3")]])
        let bulk = catalogStub()
        let c = WatchController(transport: watches, installed: nil, store: f.store, notifier: RecordingNotifier(),
                                now: { clock.date }, catalogClient: CatalogClient(transport: bulk, cacheDirectory: directory))
        await c.scheduledTick()
        #expect(await bulk.requests.isEmpty)
        #expect(await watches.requests.isEmpty)
        clock.date.addTimeInterval(1800); await c.scheduledTick()
        #expect(await watches.requests.count == 1); #expect(await bulk.requests.isEmpty)
        clock.date.addTimeInterval(84600); await c.scheduledTick()
        #expect(await watches.requests.count == 2); #expect(await bulk.requests.count == 2)
        #expect(c.state.lastCatalogFetch == clock.date && c.state.lastCheck == clock.date)
    }
    @Test(arguments: [true, false])
    func concurrentCatalogAndWatchChecksPreserveBothCommits(_ catalogFirst: Bool) async throws {
        let f = WatchFixture(); defer { f.clean() }
        var state = AppState.initial; state.watched = [baseline()]; try f.store.save(state)
        let clock = CatalogClock()
        let watches = ControlledWatchTransport(); let bulk = ControlledCatalogTransport()
        let c = WatchController(transport: watches, installed: nil, store: f.store, notifier: RecordingNotifier(),
                                now: { clock.date }, catalogClient: CatalogClient(transport: bulk, cacheDirectory: f.directory.appendingPathComponent("catalog")))
        let tick = Task { await c.scheduledTick() }
        try await waitForRequests(1, on: watches); try await waitForCatalogRequests(1, on: bulk)
        await c.scheduledTick()
        #expect(await watches.started.count == 1)
        #expect(await bulk.started.count == 1)
        c.setInterval(CheckInterval(minutes: 60)!); c.setOtherUpdatesCollapsed(true)
        if !catalogFirst {
            await watches.finish(watchURL())
            let deadline = ContinuousClock.now.advanced(by: .seconds(3))
            while c.isChecking, ContinuousClock.now < deadline { await Task.yield() }
            try #require(!c.isChecking)
            #expect(c.state.lastCheck == clock.date)
        }
        await bulk.finish(.formula); try await waitForCatalogRequests(1, on: bulk); await bulk.finish(.cask)
        if catalogFirst {
            try await waitForCatalogIdle(c)
            #expect(c.state.lastCatalogFetch == clock.date)
            await watches.finish(watchURL())
        }
        await tick.value
        #expect(c.state.lastCatalogFetch == clock.date && c.state.lastCheck == clock.date)
        #expect(c.state.watched[0].lastListing?.version == "2.0")
        #expect(c.state.interval.minutes == 60 && c.state.otherUpdatesCollapsed)
        #expect(f.store.load().state == c.state)
    }
}

actor ControlledCatalogTransport: HTTPTransport {
    var pending: [URL: CheckedContinuation<HTTPResponse, any Error>] = [:]
    var started: [URL] = []
    func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse {
        started.append(url)
        return try await withCheckedThrowingContinuation { pending[url] = $0 }
    }
    func finish(_ kind: PackageKind) {
        pending.removeValue(forKey: catalogURL(kind))?.resume(returning: HTTPResponse(status: 200,
            body: Data((kind == .formula ? syntheticFormulaList : syntheticCaskList).utf8)))
    }
    func waiting(_ count: Int) -> Bool { pending.count == count }
}
@MainActor func waitForCatalogRequests(_ count: Int, on transport: ControlledCatalogTransport) async throws {
    let deadline = ContinuousClock.now.advanced(by: .seconds(3))
    while !(await transport.waiting(count)), ContinuousClock.now < deadline { await Task.yield() }
    try #require(await transport.waiting(count), "Expected controlled catalog requests did not start")
}
@MainActor func waitForCatalogIdle(_ controller: WatchController) async throws {
    let deadline = ContinuousClock.now.advanced(by: .seconds(3))
    while controller.isRefreshingCatalog, ContinuousClock.now < deadline { await Task.yield() }
    try #require(!controller.isRefreshingCatalog)
}
