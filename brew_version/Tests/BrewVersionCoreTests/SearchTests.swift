import Foundation
import Testing
@testable import BrewVersionCore

@MainActor struct SearchTests {
    @Test func tokenization() {
        #expect(tokenize("a  b a Bad") == [.valid(PackageName("a")!), .valid(PackageName("b")!), .invalid("Bad")])
    }
    @Test func searchDeduplicatesAndRejectsInvalid() async {
        let f = WatchFixture(); defer { f.clean() }
        let name = PackageName("synthetic-formula")!
        let transport = StubTransport([watchURL(name): [watchResponse("1"), watchResponse("1")]])
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: RecordingNotifier())
        await c.search("synthetic-formula Bad synthetic-formula")
        #expect(c.results.count == 2)
        guard case .found(let listing, nil, false) = c.results.first else { Issue.record("Expected found result"); return }
        #expect(listing.name == name)
        #expect(c.results.last == .invalid("Bad"))
        #expect(await transport.requests.count == 1)
        await c.add(name, kind: .formula)
        guard case .found(_, _, true) = c.results.first else { Issue.record("Watch state is stale"); return }
        _ = c.remove(name)
        guard case .found(_, _, false) = c.results.first else { Issue.record("Removal state is stale"); return }
    }
    @Test func exhaustedKindsNotFound() async {
        let f = WatchFixture(); defer { f.clean() }
        let transport = StubTransport([watchURL(): [.success(.init(status:404,body:Data()))],watchURL(kind:.cask): [.success(.init(status:404,body:Data()))]])
        let c = WatchController(transport:transport,installed:nil,store:f.store,notifier:RecordingNotifier())
        await c.search(watchName.rawValue)
        #expect(c.results == [.notFound(watchName)])
    }
    @Test func watchedSearchUsesKnownKind() async throws {
        let f = WatchFixture(); defer { f.clean() }
        var state = AppState.initial
        state.watched = [WatchEntry(name: watchName, kind: .cask)]
        try f.store.save(state)
        let transport = StubTransport([watchURL(kind: .cask): [watchResponse("1", kind: .cask)]])
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: RecordingNotifier())
        await c.search(watchName.rawValue, kind: .formula)
        #expect(await transport.requests.map(\.url) == [watchURL(kind: .cask)])
        guard case .found(let listing, _, true) = c.results.first else { Issue.record("Expected watched cask"); return }
        #expect(listing.kind == .cask)
    }
    @Test func newerQueryAndClearWin() async throws {
        let f = WatchFixture(); defer { f.clean() }
        let transport = ControlledWatchTransport()
        let c = WatchController(transport:transport,installed:nil,store:f.store,notifier:RecordingNotifier())
        let old = Task { await c.search("synthetic-old", kind: .cask) }
        try await waitForRequests(1,on:transport)
        await c.search("Bad")
        await transport.finish(watchURL(PackageName("synthetic-old")!, kind: .cask))
        await old.value
        #expect(c.results == [.invalid("Bad")])
        c.clearSearch(); #expect(c.results.isEmpty)
    }
    @Test func cancelledSelectedKindSearchCannotPublish() async throws {
        let f = WatchFixture(); defer { f.clean() }
        let transport = ControlledWatchTransport()
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: RecordingNotifier())
        let search = Task { await c.search(watchName.rawValue, kind: .cask) }
        try await waitForRequests(1, on: transport)
        search.cancel()
        await transport.finish(watchURL(kind: .cask))
        await search.value
        #expect(c.results.isEmpty)
        #expect(await transport.started == [watchURL(kind: .cask)])
    }
    @Test func pendingSearchUsesCommittedWatchState() async throws {
        let f = WatchFixture(); defer { f.clean() }
        var state = AppState.initial
        state.watched = [WatchEntry(name: watchName, kind: .formula)]
        try f.store.save(state)
        let transport = ControlledWatchTransport()
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: RecordingNotifier())
        let search = Task { await c.search(watchName.rawValue) }
        try await waitForRequests(1, on: transport)
        let removal = try #require(c.remove(watchName))
        await transport.finish(watchURL())
        await search.value
        guard case .found(_, _, false) = c.results.first else { Issue.record("Late search retained removed Watch state"); return }
        c.restore(removal.entry, at: removal.index)
        guard case .found(_, _, true) = c.results.first else { Issue.record("Undo did not update search"); return }
        let cleared = Task { await c.search(watchName.rawValue) }
        try await waitForRequests(1, on: transport)
        c.clearSearch()
        await transport.finish(watchURL())
        await cleared.value
        #expect(c.results.isEmpty)
    }
    @Test func searchAndChecksShareFourSlots() async throws {
        let f = WatchFixture(); defer { f.clean() }
        var state = AppState.initial
        state.watched = (0..<4).map { WatchEntry(name:PackageName("synthetic-watch-\($0)")!,kind:.formula) }
        try f.store.save(state)
        let transport = ControlledWatchTransport()
        let c = WatchController(transport:transport,installed:nil,store:f.store,notifier:RecordingNotifier())
        let check = Task { await c.checkNow() }
        try await waitForRequests(4,on:transport)
        let search = Task { await c.search("synthetic-search-0 synthetic-search-1") }
        for _ in 0..<100 { await Task.yield() }
        #expect(await transport.started.count == 4)
        for n in state.watched { await transport.finish(watchURL(n.name)) }
        await check.value
        try await waitForRequests(2,on:transport)
        for n in 0..<2 { await transport.finish(watchURL(PackageName("synthetic-search-\(n)")!)) }
        await search.value
        #expect(c.results.count == 2)
    }
}
