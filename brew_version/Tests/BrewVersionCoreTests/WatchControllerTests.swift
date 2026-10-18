import Foundation
import Testing
@testable import BrewVersionCore

actor RecordingNotifier: Notifier {
    var notices: [Notice] = []
    var persisted: [AppState] = []
    let store: WatchStore?
    init(store: WatchStore? = nil) { self.store = store }
    func post(_ notice: Notice) async {
        notices.append(notice)
        if let store { persisted.append(store.load().state) }
    }
}
actor ControlledWatchTransport: HTTPTransport {
    var pending: [URL: CheckedContinuation<HTTPResponse, any Error>] = [:]
    var started: [URL] = []
    func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse {
        started.append(url)
        return try await withCheckedThrowingContinuation { pending[url] = $0 }
    }
    func finish(_ url: URL, version: String = "2.0") {
        pending.removeValue(forKey: url)?.resume(returning: HTTPResponse(status: 200, body: Data("{\"versions\":{\"stable\":\"\(version)\"}}".utf8)))
    }
    func waiting(_ count: Int) -> Bool { pending.count == count }
}

@MainActor func waitForRequests(_ count: Int, on transport: ControlledWatchTransport) async throws {
    let deadline = ContinuousClock.now.advanced(by: .seconds(3))
    while !(await transport.waiting(count)), ContinuousClock.now < deadline {
        await Task.yield()
    }
    try #require(await transport.waiting(count), "Expected controlled requests did not start")
}
func watchURL(_ name: PackageName = watchName, kind: PackageKind = .formula) -> URL {
    URL(string: "https://formulae.brew.sh/api/\(kind.rawValue)/\(name).json")!
}
func watchResponse(_ version: String, etag: String? = nil, kind: PackageKind = .formula) -> Result<HTTPResponse, URLError> {
    .success(HTTPResponse(status: 200, body: Data((kind == .formula ? "{\"versions\":{\"stable\":\"\(version)\"}}" : "{\"version\":\"\(version)\"}").utf8), etag: etag))
}
@MainActor struct WatchControllerTests {
    @Test func addBaselinesWithoutNotice() async {
        let f = WatchFixture(); defer { f.clean() }
        let transport = StubTransport([watchURL(): [watchResponse("1.0")]])
        let notifier = RecordingNotifier()
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: notifier)
        await c.add(watchName, kind: nil)
        #expect(c.state.watched.count == 1 && c.state.watched[0].lastSeenRelease?.version == "1.0")
        #expect(c.amberCount == 0 && c.persistenceError == nil)
        #expect(await notifier.notices.isEmpty)
    }
    @Test func addingWatchedNameIsNoOp() async {
        let f = WatchFixture(); defer { f.clean() }
        let transport = StubTransport([watchURL(): [watchResponse("1")]])
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: RecordingNotifier())
        await c.add(watchName, kind: .formula); await c.add(watchName, kind: .formula)
        #expect(c.state.watched.count == 1)
        #expect(await transport.requests.count == 1)
    }
    @Test func checkNotifiesOncePerVersion() async {
        let f = WatchFixture(); defer { f.clean() }
        let transport = StubTransport([watchURL(): [watchResponse("1"),watchResponse("2"),watchResponse("2"),watchResponse("3")]])
        let notifier = RecordingNotifier()
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: notifier)
        await c.add(watchName, kind: .formula)
        for _ in 0..<3 { await c.checkNow() }
        #expect(await notifier.notices.map(\.title) == ["synthetic-watch 2 is on Homebrew", "synthetic-watch 3 is on Homebrew"])
        #expect(c.amberCount == 1)
    }
    @Test func checkUsesKnownKind() async {
        let f = WatchFixture(); defer { f.clean() }
        let transport = StubTransport([watchURL(kind: .cask): [watchResponse("1",kind: .cask),watchResponse("2",kind: .cask)]])
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: RecordingNotifier())
        await c.add(watchName, kind: .cask); await c.checkNow()
        #expect(await transport.requests.map(\.url) == [watchURL(kind: .cask),watchURL(kind: .cask)])
        #expect(c.state.watched[0].lastListing?.version == "2")
    }
    @Test func removedFromHomebrewShowsError() async {
        let f = WatchFixture(); defer { f.clean() }
        let transport = StubTransport([watchURL(): [watchResponse("1"),.success(HTTPResponse(status: 404, body: Data()))]])
        let notifier = RecordingNotifier()
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: notifier)
        await c.add(watchName, kind: .formula); await c.checkNow()
        #expect(c.state.watched[0].lastError == "Not found in Homebrew.")
        #expect(c.state.watched[0].lastListing?.version == "1")
        #expect(await notifier.notices.isEmpty)
    }
    @Test func popoverClosedClearsUnseen() async {
        let f = WatchFixture(); defer { f.clean() }
        let transport = StubTransport([watchURL(): [watchResponse("1"),watchResponse("2"),watchResponse("2"),watchResponse("2")]])
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: RecordingNotifier())
        await c.add(watchName, kind: .formula); await c.checkNow(); await c.checkNow()
        #expect(c.amberCount == 1)
        let restarted = WatchController(transport: transport, installed: nil, store: f.store, notifier: RecordingNotifier())
        #expect(restarted.amberCount == 1)
        restarted.popoverClosed()
        #expect(restarted.amberCount == 0 && f.store.load().state.watched[0].lastSeenRelease?.version == "2")
        await restarted.checkNow()
        #expect(restarted.amberCount == 0)
    }
    @Test func removeAndRestore() async throws {
        let f = WatchFixture(); defer { f.clean() }
        var state = AppState.initial
        let secondName = PackageName("synthetic-second")!
        let second = baseline(Listing(name: secondName, kind: .formula, version: "1.0"))
        state.watched = [baseline(),second]; try f.store.save(state)
        let c = WatchController(transport: StubTransport([:]), installed: nil, store: f.store, notifier: RecordingNotifier())
        let removed = try #require(c.remove(watchName))
        #expect(removed.index == 0 && c.state.watched.map(\.name) == [secondName])
        c.restore(removed.entry, at: removed.index)
        #expect(c.state == state)
    }
    @Test func skipClearsAmber() async {
        let f = WatchFixture(); defer { f.clean() }
        let transport = StubTransport([watchURL(): [watchResponse("1"),watchResponse("2")]])
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: RecordingNotifier())
        await c.add(watchName, kind: .formula); await c.checkNow(); c.skip(watchName)
        #expect(c.amberCount == 0 && c.state.watched[0].skippedRelease?.version == "2")
    }
    @Test func overdueAfterSleepRunsOneCheck() async throws {
        let f = WatchFixture(); defer { f.clean() }
        var state = AppState.initial; state.watched = [baseline()]; state.lastCheck = Date(timeIntervalSince1970: 0)
        try f.store.save(state)
        let transport = StubTransport([watchURL(): [watchResponse("1")]])
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: RecordingNotifier(), now: { Date(timeIntervalSince1970: 18000) })
        await c.checkIfDue(); await c.checkIfDue()
        #expect(await transport.requests.count == 1)
        #expect(c.state.lastCheck == Date(timeIntervalSince1970: 18000))
    }
    @Test func concurrentCheckIsIgnored() async throws {
        let f = WatchFixture(); defer { f.clean() }
        var state = AppState.initial; state.watched = [baseline()]; try f.store.save(state)
        let transport = ControlledWatchTransport()
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: RecordingNotifier())
        let check = Task { await c.checkNow() }
        try await waitForRequests(1, on: transport)
        await c.checkNow()
        #expect(c.isChecking)
        #expect(await transport.started.count == 1)
        await transport.finish(watchURL()); await check.value
        #expect(!c.isChecking)
    }
    @Test func cacheSurvivesRestart() async {
        let f = WatchFixture(); defer { f.clean() }
        let transport = StubTransport([watchURL(): [watchResponse("1",etag: "synthetic-tag"),.success(HTTPResponse(status:304, body: Data()))]])
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: RecordingNotifier())
        await c.add(watchName, kind: .formula); await c.checkNow()
        let next = StubTransport([watchURL(): [.success(HTTPResponse(status:304, body: Data()))]])
        let restarted = WatchController(transport: next, installed: nil, store: f.store, notifier: RecordingNotifier())
        await restarted.checkNow()
        #expect(await next.requests.first?.etag == "synthetic-tag")
        #expect(restarted.state.watched[0].lastError == nil)
    }
    @Test func stateSavedAfterEachMutation() async throws {
        let f = WatchFixture(); defer { f.clean() }
        let c = WatchController(transport: StubTransport([watchURL(): [watchResponse("1")]]), installed: nil, store: f.store, notifier: RecordingNotifier())
        await c.add(watchName, kind: .formula); #expect(f.store.load().state == c.state)
        c.skip(watchName); #expect(f.store.load().state.watched[0].skippedRelease?.version == "1")
        let removed = try #require(c.remove(watchName)); #expect(f.store.load().state.watched.isEmpty)
        c.restore(removed.entry, at: removed.index); #expect(f.store.load().state == c.state)
        c.setInterval(CheckInterval(minutes: 90)!); #expect(f.store.load().state.interval.minutes == 90)
    }
    @Test func failedMutationDoesNotPublish() async throws {
        let f = WatchFixture(); defer { f.clean() }
        var state = AppState.initial; state.watched = [baseline()]; try f.store.save(state)
        let failures = IOFailures(); failures.operation = "replace"
        let c = WatchController(transport: StubTransport([watchURL(PackageName("synthetic-new")!): [watchResponse("1")]]), installed: nil, store: WatchStore(fileURL: f.file, io: failures.io), notifier: RecordingNotifier())
        c.skip(watchName); #expect(c.state == state && c.persistenceError != nil)
        #expect(c.remove(watchName) == nil); #expect(c.state == state)
        c.setInterval(CheckInterval(minutes: 90)!); #expect(c.state == state)
        let restored = baseline(Listing(name: PackageName("synthetic-restored")!, kind: .formula, version: "1.0"))
        c.restore(restored, at: 0); #expect(c.state == state)
        await c.add(PackageName("synthetic-new")!, kind: .formula); #expect(c.state == state)
        #expect(f.store.load().state == state && c.canSave)
        failures.operation = nil; c.skip(watchName)
        #expect(c.persistenceError == nil && c.state.watched[0].skippedRelease != nil)
    }
    @Test func blockedLoadDoesNotCheckOrMutate() async throws {
        let f = WatchFixture(); defer { f.clean() }
        try f.store.save(.initial); let corrupt = Data("synthetic corruption".utf8); try corrupt.write(to: f.file)
        let failures = IOFailures(); failures.operation = "move"
        let transport = StubTransport([watchURL(): [watchResponse("1")]])
        let c = WatchController(transport: transport, installed: nil, store: WatchStore(fileURL: f.file, io: failures.io), notifier: RecordingNotifier())
        #expect(!c.canSave && c.persistenceError != nil)
        await c.checkNow(); await c.checkIfDue(); await c.add(watchName, kind: .formula)
        c.skip(watchName); _ = c.remove(watchName); c.restore(baseline(),at:0); c.setInterval(CheckInterval(minutes:90)!); c.popoverClosed(); c.retryLoad()
        #expect(!c.canSave && c.state == .initial)
        #expect(await transport.requests.isEmpty)
        #expect(try Data(contentsOf: f.file) == corrupt)
        failures.operation = nil; c.retryLoad()
        #expect(c.canSave && c.persistenceError != nil)
        await c.add(watchName, kind: .formula)
        #expect(c.state.watched.count == 1 && c.persistenceError == nil)
    }
    @Test func savePrecedesNotice() async throws {
        let f = WatchFixture(); defer { f.clean() }
        var state = AppState.initial; state.watched = [baseline()]; try f.store.save(state)
        let failures = IOFailures(); failures.operation = "replace"
        let notifier = RecordingNotifier(store: f.store)
        let c = WatchController(transport: StubTransport([watchURL(): [watchResponse("2"),watchResponse("2")]]), installed: nil, store: WatchStore(fileURL: f.file, io: failures.io), notifier: notifier)
        await c.checkNow()
        #expect(c.state == state && c.persistenceError != nil)
        #expect(await notifier.notices.isEmpty)
        failures.operation = nil; await c.checkNow()
        #expect(await notifier.notices.count == 1)
        #expect(await notifier.persisted.first?.watched[0].notifiedRelease?.version == "2")
        #expect(await notifier.persisted.first?.lastCheck != nil)
    }
    @Test func inFlightCheckPreservesConcurrentMutationsAndGenerations() async throws {
        let f = WatchFixture(); defer { f.clean() }
        let names = (0..<4).map { PackageName("synthetic-race-\($0)")! }
        var state = AppState.initial
        state.watched = names.map { baseline(Listing(name: $0, kind: .formula, version: "1.0")) }
        try f.store.save(state)
        let transport = ControlledWatchTransport(); let notifier = RecordingNotifier()
        let c = WatchController(transport: transport, installed: nil, store: f.store, notifier: notifier)
        let check = Task { await c.checkNow() }
        try await waitForRequests(4, on: transport)
        _ = c.remove(names[0])
        let removed = try #require(c.remove(names[1])); c.restore(removed.entry, at: removed.index)
        c.skip(names[2]); c.setInterval(CheckInterval(minutes: 90)!)
        for name in names { await transport.finish(watchURL(name)) }
        await check.value
        #expect(c.state.watched.map(\.name) == Array(names.dropFirst()))
        #expect(c.state.watched[0] == removed.entry)
        #expect(c.state.interval.minutes == 90)
        #expect(c.state.watched[1].skippedRelease?.version == "1.0")
        #expect(c.state.watched[1].lastListing?.version == "2.0")
        #expect(c.state.watched[2].lastListing?.version == "2.0")
        #expect(await notifier.notices.map(\.name).sorted { $0.rawValue < $1.rawValue } == Array(names.suffix(2)))
        #expect(f.store.load().state == c.state)
    }

    @Test func checksLimitRequestsAndReadFreshInstalledVersions() async throws {
        let f = WatchFixture(); defer { f.clean() }
        let names = (0..<6).map { PackageName("synthetic-limit-\($0)")! }
        var state = AppState.initial
        state.watched = names.map { baseline(Listing(name: $0, kind: .formula, version: "1.0")) }
        try f.store.save(state)
        let prefix = f.directory.appendingPathComponent("synthetic-prefix")
        let keg = prefix.appendingPathComponent("Cellar/\(names[0])/0.5")
        try FileManager.default.createDirectory(at: keg, withIntermediateDirectories: true)
        try Data(#"{"source":{"tap":"homebrew/core"}}"#.utf8).write(to: keg.appendingPathComponent("INSTALL_RECEIPT.json"))
        let reader = InstalledReader(prefixes: HomebrewPrefix.detectAll(candidates: [prefix]), applicationDirectories: [])
        let transport = ControlledWatchTransport()
        let notifier = RecordingNotifier()
        let c = WatchController(transport: transport, installed: reader, store: f.store, notifier: notifier)
        let check = Task { await c.checkNow() }
        try await waitForRequests(4, on: transport)
        #expect(await transport.started.count == 4)
        await transport.finish(watchURL(names[0]))
        try await waitForRequests(4, on: transport)
        #expect(await transport.started.count == 5)
        await transport.finish(watchURL(names[1]))
        try await waitForRequests(4, on: transport)
        #expect(await transport.started.count == 6)
        for name in names.dropFirst(2) { await transport.finish(watchURL(name)) }
        await check.value
        #expect(c.state.watched[0].installed?.version == "0.5")
        #expect(c.state.watched[0].isAmber)
        #expect(await notifier.notices.first(where: { $0.name == names[0] })?.body == "You have 0.5.")
        // A second read observes a changed installation, without rebuilding the reader.
        let nextKeg = prefix.appendingPathComponent("Cellar/\(names[0])/3.0")
        try FileManager.default.createDirectory(at: nextKeg, withIntermediateDirectories: true)
        try Data(#"{"source":{"tap":"homebrew/core"}}"#.utf8).write(to: nextKeg.appendingPathComponent("INSTALL_RECEIPT.json"))
        for name in names.dropFirst() { _ = c.remove(name) }
        let nextCheck = Task { await c.checkNow() }
        try await waitForRequests(1, on: transport)
        await transport.finish(watchURL(names[0]))
        await nextCheck.value
        #expect(c.state.watched[0].installed?.version == "3.0" && c.amberCount == 0)
    }
}
