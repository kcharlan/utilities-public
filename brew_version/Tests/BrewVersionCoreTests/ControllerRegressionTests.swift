import Foundation
import Testing
@testable import BrewVersionCore

@MainActor private final class RetryClock {
    var date = Date(timeIntervalSince1970: 1_000_000)
}

@MainActor struct ControllerRegressionTests {
    @Test func nextAutomaticCheckUsesUnreachableAttemptAndReconnectPolicy() async throws {
        let f = WatchFixture(); defer { f.clean() }
        let clock = RetryClock()
        var state = AppState.initial; state.watched = [baseline()]; state.lastCheck = clock.date
        try f.store.save(state)
        let transport = StubTransport([watchURL(): [.failure(URLError(.notConnectedToInternet)), watchResponse("2")]])
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: RecordingNotifier(), now: { clock.date })
        #expect(c.nextAutomaticCheck == .scheduled(Date(timeIntervalSince1970: 1_001_800)))
        clock.date.addTimeInterval(1800); await c.checkIfDue()
        #expect(c.state.lastCheck == Date(timeIntervalSince1970: 1_000_000))
        #expect(c.nextAutomaticCheck == .scheduled(Date(timeIntervalSince1970: 1_003_600)))
        await c.setNetworkAvailable(false)
        #expect(c.nextAutomaticCheck == .waitingForNetwork(notBefore: nil))
        clock.date.addTimeInterval(60); await c.setNetworkAvailable(true)
        #expect(await transport.requests.count == 2)
        #expect(c.nextAutomaticCheck == .scheduled(Date(timeIntervalSince1970: 1_003_660)))
    }
    @Test(arguments: [false, true]) func nextAutomaticCheckRetainsFailedSaveDeadlineAcrossReconnect(previousSuccess: Bool) async throws {
        let f = WatchFixture(); defer { f.clean() }
        let clock = RetryClock()
        var state = AppState.initial; state.watched = [baseline()]
        if previousSuccess { state.lastCheck = clock.date.addingTimeInterval(-1800) }
        try f.store.save(state)
        let failures = IOFailures(); failures.operation = "replace"
        let transport = StubTransport([watchURL(): [watchResponse("2"), watchResponse("2")]])
        let c = WatchController(transport: transport, installed: nil, store: WatchStore(fileURL: f.file, io: failures.io), notifier: RecordingNotifier(), now: { clock.date })
        await c.checkIfDue()
        #expect(c.nextAutomaticCheck == .scheduled(Date(timeIntervalSince1970: 1_001_800)))
        await c.setNetworkAvailable(false)
        #expect(c.nextAutomaticCheck == .waitingForNetwork(notBefore: Date(timeIntervalSince1970: 1_001_800)))
        failures.operation = nil; clock.date.addTimeInterval(60); await c.setNetworkAvailable(true)
        #expect(await transport.requests.count == 1)
        #expect(c.nextAutomaticCheck == .scheduled(Date(timeIntervalSince1970: 1_001_800)))
        clock.date.addTimeInterval(1740); await c.checkIfDue()
        #expect(await transport.requests.count == 2)
        #expect(c.nextAutomaticCheck == .scheduled(Date(timeIntervalSince1970: 1_003_600)))
    }
    @Test func unreachableDoesNotBecomeSuccessfulCheck() async throws {
        let f = WatchFixture(); defer { f.clean() }
        var state = AppState.initial; state.watched = [baseline()]; try f.store.save(state)
        let clock = RetryClock()
        let transport = StubTransport([watchURL(): [.failure(URLError(.notConnectedToInternet)), watchResponse("2")]])
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: RecordingNotifier(), now: { clock.date })
        await c.checkIfDue()
        #expect(c.state.lastCheck == nil)
        #expect(c.nextAutomaticCheck == .scheduled(Date(timeIntervalSince1970: 1_001_800)))
        #expect(c.state.watched[0].lastError == "Couldn't reach Homebrew.")
        clock.date.addTimeInterval(60); await c.checkIfDue()
        #expect(await transport.requests.count == 1)
    }
    @Test func rejectedSaveBacksOffAutomaticChecksButManualRetryIsImmediate() async throws {
        let f = WatchFixture(); defer { f.clean() }
        var state = AppState.initial; state.watched = [baseline()]; try f.store.save(state)
        let failures = IOFailures(); failures.operation = "replace"
        let clock = RetryClock()
        let transport = StubTransport([watchURL(): [watchResponse("2"), watchResponse("2"), watchResponse("2")]])
        let c = WatchController(transport: transport, installed: nil, store: WatchStore(fileURL: f.file, io: failures.io),
                                notifier: RecordingNotifier(), now: { clock.date })
        await c.checkIfDue()
        clock.date.addTimeInterval(60); await c.checkIfDue()
        #expect(await transport.requests.count == 1)
        #expect(c.state.lastCheck == nil)
        failures.operation = nil; await c.checkNow()
        #expect(await transport.requests.count == 2)
        #expect(c.state.lastCheck == clock.date)
    }
    @Test func startupWaitsForNetworkAndReconnectRetriesUnreachableImmediately() async throws {
        let f = WatchFixture(); defer { f.clean() }
        var state = AppState.initial; state.watched = [baseline()]; try f.store.save(state)
        let clock = RetryClock()
        let transport = StubTransport([watchURL(): [.failure(URLError(.notConnectedToInternet)), watchResponse("2")]])
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: RecordingNotifier(),
                                now: { clock.date }, networkAvailable: false)
        await c.scheduledTick(); #expect(await transport.requests.isEmpty)
        await c.setNetworkAvailable(true)
        #expect(c.state.lastCheck == nil)
        await c.setNetworkAvailable(false)
        clock.date.addTimeInterval(60)
        await c.setNetworkAvailable(true)
        #expect(await transport.requests.count == 2)
        #expect(c.state.lastCheck == clock.date)
    }
    @Test func recoveryWarningIsDistinctFromFailedSave() throws {
        let f = WatchFixture(); defer { f.clean() }
        try f.store.save(.initial); try Data("synthetic corrupt".utf8).write(to: f.file)
        let failures = IOFailures()
        let c = WatchController(transport: StubTransport([:]), installed: nil,
                                store: WatchStore(fileURL: f.file, io: failures.io), notifier: RecordingNotifier())
        #expect(c.persistenceIssue == .recoveryWarning && c.canSave)
        failures.operation = "replace"; c.setInterval(CheckInterval(minutes: 60)!)
        #expect(c.persistenceIssue == .saveFailure)
        failures.operation = nil; c.setInterval(CheckInterval(minutes: 60)!)
        #expect(c.persistenceIssue == nil)
    }
    @Test func noOpCloseAndSettingsDoNotWrite() throws {
        let f = WatchFixture(); defer { f.clean() }
        var state = AppState.initial; state.watched = [baseline()]; try f.store.save(state)
        let failures = IOFailures(); failures.operation = "replace"
        let c = WatchController(transport: StubTransport([:]), installed: nil,
                                store: WatchStore(fileURL: f.file, io: failures.io), notifier: RecordingNotifier())
        c.popoverClosed(); c.setInterval(.standard); c.setOtherUpdatesCollapsed(false)
        #expect(c.persistenceError == nil)
        #expect(c.state == state)
    }
    @Test func removedAndSearchedListingsStayOutOfPersistedWatchCache() async throws {
        let f = WatchFixture(); defer { f.clean() }
        let removed = PackageName("synthetic-removed")!
        let searched = PackageName("synthetic-search")!
        let transport = StubTransport([watchURL(removed): [watchResponse("1", etag: "synthetic-r")],
                                       watchURL(searched): [watchResponse("1", etag: "synthetic-s")],
                                       watchURL(): [watchResponse("1", etag: "synthetic-w"), watchResponse("2", etag: "synthetic-w2")]])
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: RecordingNotifier())
        await c.add(removed, kind: .formula); _ = c.remove(removed)
        #expect(f.store.load().state.listingCache.isEmpty)
        await c.search(searched.rawValue)
        await c.add(watchName, kind: .formula); await c.checkNow()
        #expect(Set(f.store.load().state.listingCache.values.map(\.listing.name)) == [watchName])
    }
    @Test func removalEvictsConditionalCacheBeforeReadding() async throws {
        let f = WatchFixture(); defer { f.clean() }
        let transport = StubTransport([watchURL(): [watchResponse("1", etag: "synthetic-old"), watchResponse("2", etag: "synthetic-new")]])
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: RecordingNotifier())
        await c.add(watchName, kind: .formula); _ = c.remove(watchName)
        await c.add(watchName, kind: .formula)
        #expect(await transport.requests.map(\.etag) == [nil, nil])
        #expect(f.store.load().state.listingCache[watchURL()]?.etag == "synthetic-new")
    }
    @Test func reconnectRetriesFailureDespiteRecentSuccessfulCheck() async throws {
        let f = WatchFixture(); defer { f.clean() }
        let clock = RetryClock()
        var state = AppState.initial; state.watched = [baseline()]; state.lastCheck = clock.date; try f.store.save(state)
        let transport = StubTransport([watchURL(): [.failure(URLError(.notConnectedToInternet)), watchResponse("2")]])
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: RecordingNotifier(), now: { clock.date })
        await c.checkNow(); await c.setNetworkAvailable(false)
        clock.date.addTimeInterval(60); await c.setNetworkAvailable(true)
        #expect(await transport.requests.count == 2)
        #expect(c.state.lastCheck == clock.date)
    }
    @Test func reconnectDoesNotBypassFailedSaveBackoff() async throws {
        let f = WatchFixture(); defer { f.clean() }
        var state = AppState.initial; state.watched = [baseline()]; try f.store.save(state)
        let failures = IOFailures(); failures.operation = "replace"
        let clock = RetryClock()
        let transport = StubTransport([watchURL(): [watchResponse("2"), watchResponse("2")]])
        let c = WatchController(transport: transport, installed: nil,
                                store: WatchStore(fileURL: f.file, io: failures.io), notifier: RecordingNotifier(), now: { clock.date })
        await c.checkIfDue(); await c.setNetworkAvailable(false)
        failures.operation = nil; clock.date.addTimeInterval(60); await c.setNetworkAvailable(true)
        #expect(await transport.requests.count == 1 && c.state.lastCheck == nil)
        clock.date.addTimeInterval(1740); await c.checkIfDue()
        #expect(await transport.requests.count == 2 && c.state.lastCheck == clock.date)
    }
    @Test func rejectedCatalogTimestampSaveBacksOffIncludingReconnect() async throws {
        let f = WatchFixture(); defer { f.clean() }
        try f.store.save(.initial)
        let failures = IOFailures(); failures.operation = "replace"
        let clock = RetryClock()
        let bulk = StubTransport([catalogURL(.formula): [catalogResponse(200, syntheticFormulaList), catalogResponse(200, syntheticFormulaList)],
                                  catalogURL(.cask): [catalogResponse(200, syntheticCaskList), catalogResponse(200, syntheticCaskList)]])
        let c = WatchController(transport: StubTransport([:]), installed: nil,
                                store: WatchStore(fileURL: f.file, io: failures.io), notifier: RecordingNotifier(), now: { clock.date },
                                catalogClient: CatalogClient(transport: bulk, cacheDirectory: f.directory.appendingPathComponent("catalog")))
        await c.refreshCatalogIfDue()
        #expect(c.state.lastCatalogFetch == nil && c.persistenceIssue == .saveFailure)
        for _ in 0..<5 { clock.date.addTimeInterval(60); await c.refreshCatalogIfDue() }
        await c.setNetworkAvailable(false); await c.setNetworkAvailable(true)
        #expect(await bulk.requests.count == 2)
        failures.operation = nil; clock.date.addTimeInterval(1500); await c.refreshCatalogIfDue()
        #expect(await bulk.requests.count == 4)
        #expect(c.state.lastCatalogFetch == clock.date)
    }
}
