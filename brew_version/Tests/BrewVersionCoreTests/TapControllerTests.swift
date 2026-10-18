import Foundation
import Testing
@testable import BrewVersionCore

private final class TapControllerFixture: @unchecked Sendable {
    let watch = WatchFixture()
    var root: URL { watch.directory.appendingPathComponent("prefix") }
    func seed(_ short: String = "synthetic-tool", kind: PackageKind = .formula, owner: String = "synthetic-owner") throws {
        let tap = root.appendingPathComponent("Library/Taps/\(owner)/homebrew-synthetic-tap")
        let config = tap.appendingPathComponent(".git/config")
        try FileManager.default.createDirectory(at: config.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("[remote \"origin\"]\n url = https://github.com/\(owner)/homebrew-synthetic-tap.git\n".utf8).write(to: config)
        let file = tap.appendingPathComponent("\(kind == .formula ? "Formula" : "Casks")/\(short).rb")
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("# synthetic fixture".utf8).write(to: file)
    }
    var index: TapIndex { TapIndex.scan(prefixes: [HomebrewPrefix(root: root)]) }
    deinit { watch.clean() }
}
private struct TapInstallations: InstalledReading {
    var names: [PackageKind: Set<PackageName>]
    func installed(_ name: PackageName, kind: PackageKind, listing: Listing?) -> InstalledVersion? {
        names[kind]?.contains(name) == true ? .init(version: "1.2.3", source: kind == .formula ? .cellar : .caskroom) : nil
    }
    func snapshot(listings: [Listing]) -> InstalledSnapshot {
        var result = InstalledSnapshot()
        for (kind, names) in names { for name in names { result.versions[kind, default: [:]][name] = installed(name, kind: kind, listing: nil) } }
        return result
    }
}
private func tapURL(_ short: String = "synthetic-tool", kind: PackageKind = .formula) -> URL {
    URL(string: "https://raw.githubusercontent.com/synthetic-owner/homebrew-synthetic-tap/HEAD/\(kind == .formula ? "Formula" : "Casks")/\(short).rb")!
}
private func tapResponse(_ version: String = "4.5.6") -> Result<HTTPResponse, URLError> { .success(.init(status: 200, body: Data("version \"\(version)\"".utf8))) }
private let tapMissing: Result<HTTPResponse, URLError> = .success(.init(status: 404, body: Data()))

@MainActor struct TapControllerTests {
    let bare = PackageName("synthetic-tool")!
    let full = PackageName("synthetic-owner/synthetic-tap/synthetic-tool")!
    fileprivate func controller(_ f: TapControllerFixture, _ t: any HTTPTransport, installed: (any InstalledReading)? = nil, catalog: CatalogClient? = nil, notifier: RecordingNotifier = RecordingNotifier()) -> WatchController {
        WatchController(transport: t, installed: installed, store: f.watch.store, notifier: notifier, catalogClient: catalog, taps: { f.index })
    }
    @Test func bareSearchShowsOfficialAndTapRows() async throws {
        let f = TapControllerFixture(); try f.seed("synthetic-shared")
        let name = PackageName("synthetic-shared")!
        let t = StubTransport([watchURL(name): [watchResponse("9.0.1")], tapURL("synthetic-shared"): [tapResponse()]])
        let c = controller(f, t); await c.search(name.rawValue)
        #expect(c.results.compactMap { if case .found(let l, _, _) = $0 { return l.name.rawValue }; return nil } == [name.rawValue, "synthetic-owner/synthetic-tap/synthetic-shared"])
    }
    @Test func bareSearchNotFoundOnlyWhenNoSource() async throws {
        let f = TapControllerFixture(); try f.seed()
        let c = controller(f, StubTransport([watchURL(bare): [tapMissing], watchURL(bare, kind: .cask): [tapMissing], tapURL(): [tapResponse()]]))
        await c.search(bare.rawValue)
        #expect(c.results.count == 1)
        #expect(c.results.first.map { if case .found(let l, _, _) = $0 { return l.name == full }; return false } == true)
    }
    @Test func bareAddSavesResolvedFullName() async throws {
        let f = TapControllerFixture(); try f.seed()
        let t = StubTransport([watchURL(bare): [tapMissing], tapURL(): [tapResponse(), tapResponse("7.8")]])
        let c = controller(f, t, installed: TapInstallations(names: [.formula: [full]]))
        await c.add(bare, kind: .formula)
        #expect(c.state.watched.first?.name == full)
        #expect(c.state.watched.first?.installed?.version == "1.2.3")
        await c.checkNow()
        #expect(c.state.watched.first?.lastListing?.version == "7.8")
        #expect(await t.requests.filter { $0.url == watchURL(bare) }.count == 1)
        #expect(f.watch.store.load().problem == nil)
    }
    @Test func bareAddDoesNotDuplicateFullWatch() async throws {
        let f = TapControllerFixture(); try f.seed()
        var saved = AppState.initial
        saved.watched = [WatchEntry(name: full, kind: .formula, unseenRelease: true, lastError: "synthetic retained metadata")]
        try f.watch.store.save(saved)
        let bytes = try Data(contentsOf: f.watch.file)
        let c = controller(f, StubTransport([watchURL(bare): [tapMissing], tapURL(): [tapResponse()]]))
        await c.add(bare, kind: .formula)
        #expect(c.state == saved)
        #expect(try Data(contentsOf: f.watch.file) == bytes)
        #expect(f.watch.store.load().problem == nil)
    }
    @Test func failedBareAddDoesNotSave() async throws {
        for failure in [tapMissing, .failure(URLError(.notConnectedToInternet)), .success(HTTPResponse(status: 503, body: Data()))] {
            let f = TapControllerFixture(); try f.watch.store.save(.initial)
            let bytes = try Data(contentsOf: f.watch.file)
            let t = StubTransport([watchURL(bare): [failure, watchResponse("4.5.6")]])
            let c = controller(f, t); await c.add(bare, kind: .formula)
            #expect(c.state.watched.isEmpty && c.state.listingCache.isEmpty)
            #expect(try Data(contentsOf: f.watch.file) == bytes)
            #expect(c.results.contains { if case .failed(let n, _) = $0 { return n == bare }; return false })
            await c.add(bare, kind: .formula)
            #expect(c.state.watched.first?.name == bare)
        }
    }
    @Test func checkNeverSwitchesSource() async throws {
        let f = TapControllerFixture(); try f.seed()
        var s = AppState.initial; s.watched = [WatchEntry(name: bare, kind: .formula)]; try f.watch.store.save(s)
        let t = StubTransport([watchURL(bare): [tapMissing], tapURL(): [tapResponse()]])
        let c = controller(f, t); await c.checkNow()
        #expect(c.state.watched.first?.lastError != nil)
        #expect(await t.requests.map(\.url) == [watchURL(bare)])
    }
    @Test func addAndCheckTapWatch() async throws {
        let f = TapControllerFixture(); try f.seed()
        let n = RecordingNotifier()
        let c = controller(f, StubTransport([tapURL(): [tapResponse(), tapResponse("7.8")]]), installed: TapInstallations(names: [.formula: [full]]), notifier: n)
        await c.add(full, kind: .formula); await c.checkNow()
        #expect(c.amberCount == 1)
        #expect(await n.notices.first?.title == "synthetic-tool 7.8 is in synthetic-owner/synthetic-tap")
    }
    @Test func untappedWatchShowsErrorWithoutNotice() async throws {
        let f = TapControllerFixture(); try f.seed()
        let n = RecordingNotifier(); let c = controller(f, StubTransport([tapURL(): [tapResponse()]]), notifier: n)
        await c.add(full, kind: .formula)
        try FileManager.default.removeItem(at: f.root.appendingPathComponent("Library/Taps"))
        await c.refreshNow()
        #expect(c.state.watched.first?.lastError == "synthetic-owner/synthetic-tap is no longer tapped.")
        #expect(c.state.watched.first?.lastListing?.version == "4.5.6")
        #expect(await n.notices.isEmpty)
    }
    @Test func missingFileInPresentTapUsesNotFoundInTap() async throws {
        let f = TapControllerFixture(); try f.seed()
        let c = controller(f, StubTransport([tapURL(): [tapResponse()]])); await c.add(full, kind: .formula)
        try FileManager.default.removeItem(at: f.root.appendingPathComponent("Library/Taps/synthetic-owner/homebrew-synthetic-tap/Formula/synthetic-tool.rb"))
        await c.refreshNow()
        #expect(c.state.watched.first?.lastError == "Not found in synthetic-owner/synthetic-tap.")
        #expect(c.state.watched.first?.lastListing?.version == "4.5.6")
    }
    @Test func indexReadyBeforeFirstCheck() async throws {
        let f = TapControllerFixture(); try f.seed()
        var s = AppState.initial; s.watched = [WatchEntry(name: full, kind: .formula)]; try f.watch.store.save(s)
        let c = controller(f, StubTransport([tapURL(): [tapResponse()]])); await c.checkNow()
        #expect(c.state.watched.first?.lastListing?.name == full)
    }
    @Test func tapOtherUpdatesSurviveLaterChecks() async throws {
        let f = TapControllerFixture(); try f.seed()
        let c = controller(f, StubTransport([tapURL(): [tapResponse()]]), installed: TapInstallations(names: [.formula: [full]]))
        await c.refreshCatalogIfDue(); #expect(c.others.map(\.listing.name) == [full])
        await c.checkNow(); #expect(c.others.map(\.listing.name) == [full])
        #expect(c.installedNames[.formula] == [full])
    }
    @Test func tapOtherUpdatesWithoutOfficialCatalog() async throws {
        let f = TapControllerFixture(); try f.seed()
        let bulk = StubTransport([URL(string: "https://formulae.brew.sh/api/formula.json")!: [.failure(URLError(.notConnectedToInternet))]])
        let c = controller(f, StubTransport([tapURL(): [tapResponse()]]), installed: TapInstallations(names: [.formula: [full]]), catalog: CatalogClient(transport: bulk, cacheDirectory: f.watch.directory.appendingPathComponent("cache")))
        await c.refreshCatalogIfDue()
        #expect(c.others.map(\.listing.name) == [full])
        #expect(c.catalogRefreshError == "You're offline.")
        #expect(c.state.lastCatalogFetch == nil)
        await c.refreshCatalogIfDue(); #expect(await bulk.requests.count == 1)
    }
    @Test func tapKindsStaySeparate() async throws {
        let f = TapControllerFixture(); try f.seed(); try f.seed(kind: .cask)
        let t = StubTransport([tapURL(): [tapResponse("4.5.6")], tapURL(kind: .cask): [tapResponse("7.8")]])
        let c = controller(f, t, installed: TapInstallations(names: [.formula: [full], .cask: [full]]))
        await c.refreshCatalogIfDue(); await c.checkNow()
        #expect(c.others.count == 2)
        #expect(Set(c.others.map(\.listing.version)) == ["4.5.6", "7.8"])
        #expect(c.suggestions(prefix: "synthetic-tool").filter(\.installed).count == 2)
        #expect(c.suggestions(prefix: "synthetic-owner/synthetic-tap/").count == 2)
    }
    @Test func tapFailureCounts() async throws {
        let f = TapControllerFixture(); try f.seed(); try f.seed("synthetic-app", kind: .cask)
        let app = PackageName("synthetic-owner/synthetic-tap/synthetic-app")!
        let c = controller(f, StubTransport([tapURL(): [.failure(URLError(.timedOut))], tapURL("synthetic-app", kind: .cask): [.success(.init(status: 200, body: Data("version compute_version".utf8)))]]), installed: TapInstallations(names: [.formula: [full], .cask: [app]]))
        await c.refreshCatalogIfDue()
        #expect(c.tapCheckFailures == 1 && c.tapUncheckable == 1)
    }
    @Test func suggestionsRankInstalledTapFirst() async throws {
        let f = TapControllerFixture(); try f.seed()
        let c = controller(f, StubTransport([tapURL(): [tapResponse()]]), installed: TapInstallations(names: [.formula: [full]]))
        await c.refreshCatalogIfDue()
        #expect(c.suggestions(prefix: "synthetic", limit: 1).first?.name == full)
    }
    @Test func sameShortNameWatchesStaySeparate() async throws {
        let f = TapControllerFixture(); try f.seed()
        let c = controller(f, StubTransport([watchURL(bare): [watchResponse("9.0.1")], tapURL(): [tapResponse()]]))
        await c.add(bare, kind: .formula); await c.add(full, kind: .formula)
        #expect(Set(c.state.watched.map(\.name)) == [bare, full])
    }
}

private actor HeldTapAddTransport: HTTPTransport {
    private var pending: [CheckedContinuation<HTTPResponse, Never>] = []
    var count: Int { pending.count }
    private var released = false
    func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse {
        if url.host == "formulae.brew.sh" { return HTTPResponse(status: 404, body: Data()) }
        if released { return try tapResponse().get() }
        return await withCheckedContinuation { pending.append($0) }
    }
    func finish(_ index: Int) {
        pending[index].resume(returning: try! tapResponse().get())
        if index == 1 { released = true }
    }
}

private final class HeldTapInstallation: InstalledReading, @unchecked Sendable {
    private let lock = NSLock()
    private var calls = 0
    let entered = DispatchSemaphore(value: 0)
    let release = DispatchSemaphore(value: 0)
    var count: Int { lock.withLock { calls } }
    func installed(_ name: PackageName, kind: PackageKind, listing: Listing?) -> InstalledVersion? {
        lock.withLock { calls += 1 }; entered.signal(); _ = release.wait(timeout: .now() + 5)
        return .init(version: "1.2.3", source: .cellar)
    }
    func snapshot(listings: [Listing]) -> InstalledSnapshot { InstalledSnapshot() }
}
extension TapControllerTests {
    @Test func concurrentBareAndFullAddsCoalesce() async throws {
        for bareFirst in [true, false] {
            let f = TapControllerFixture(); try f.seed()
            let installed = HeldTapInstallation()
            let t = HeldTapAddTransport()
            let c = controller(f, t, installed: installed)
            let first = Task { await c.add(bareFirst ? bare : full, kind: .formula) }
            let deadline = ContinuousClock.now.advanced(by: .seconds(3))
            while await t.count < 1, ContinuousClock.now < deadline { await Task.yield() }
            try #require(await t.count == 1)
            var secondDone = false
            let second = Task { await c.add(bareFirst ? full : bare, kind: .formula); secondDone = true }
            while await t.count < 2, ContinuousClock.now < deadline { await Task.yield() }
            try #require(await t.count == 2)
            await t.finish(0)
            while installed.count == 0, ContinuousClock.now < deadline { await Task.yield() }
            #expect(installed.count == 1)
            await t.finish(1)
            while !secondDone && installed.count < 2, ContinuousClock.now < deadline { await Task.yield() }
            #expect(secondDone)
            c.setInterval(CheckInterval(minutes: 60)!)
            installed.release.signal(); installed.release.signal()
            await first.value; await second.value
            #expect(installed.count == 1)
            #expect(c.state.watched.count == 1 && c.state.watched.first?.name == full)
            #expect(c.state.interval.minutes == 60)
            #expect(f.watch.store.load().problem == nil)
            installed.release.signal(); _ = c.remove(full)
            await c.add(full, kind: .formula)
            #expect(c.state.watched.count == 1) // Both reservations were released.
        }
    }
    @Test func failedBareAddAmbiguityAndTapErrors() async throws {
        for ambiguous in [true, false] {
            let f = TapControllerFixture(); try f.seed()
            if ambiguous { try f.seed(owner: "synthetic-other") }
            try f.watch.store.save(.initial); let bytes = try Data(contentsOf: f.watch.file)
            let c = controller(f, StubTransport([watchURL(bare): [tapMissing], tapURL(): [.failure(URLError(.timedOut))]]))
            await c.add(bare, kind: .formula)
            #expect(c.state == .initial)
            #expect(try Data(contentsOf: f.watch.file) == bytes)
            #expect(c.results.contains { if case .failed = $0 { return true }; return false })
        }
    }
}

private actor HeldFailureTransport: HTTPTransport {
    var started = false
    private var gate: CheckedContinuation<HTTPResponse, any Error>?
    func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse {
        started = true
        return try await withCheckedThrowingContinuation { gate = $0 }
    }
    func fail() { gate?.resume(throwing: URLError(.timedOut)); gate = nil }
}
private final class TapSnapshotGate: InstalledReading, @unchecked Sendable {
    private let lock = NSLock()
    private var scans = 0
    let release = DispatchSemaphore(value: 0)
    let names: TapInstallations
    init(_ name: PackageName) { names = TapInstallations(names: [.formula: [name], .cask: [name]]) }
    var count: Int { lock.withLock { scans } }
    func installed(_ name: PackageName, kind: PackageKind, listing: Listing?) -> InstalledVersion? { names.installed(name, kind: kind, listing: listing) }
    func snapshot(listings: [Listing]) -> InstalledSnapshot {
        let ordinal = lock.withLock { scans += 1; return scans }
        if ordinal == 1 { _ = release.wait(timeout: .now() + 5) }
        return names.snapshot(listings: listings)
    }
}
@MainActor private final class TapControllerClock { var date = Date(timeIntervalSince1970: 1_000_000) }
extension TapControllerTests {
    @Test func failedBareAddSuppressesStaleSearchError() async throws {
        let f = TapControllerFixture(); let transport = HeldFailureTransport()
        let c = controller(f, transport)
        let add = Task { await c.add(bare, kind: .formula) }
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while !(await transport.started), ContinuousClock.now < deadline { await Task.yield() }
        try #require(await transport.started)
        await c.search("Bad")
        await transport.fail(); await add.value
        #expect(c.results == [.invalid("Bad")])
        #expect(c.state.watched.isEmpty)
    }
    @Test func tapRefreshAndCheckShareAtMostTwoCaptures() async throws {
        let f = TapControllerFixture(); try f.seed(); try f.seed(kind: .cask)
        let reader = TapSnapshotGate(full)
        let c = controller(f, StubTransport([tapURL(): [tapResponse()], tapURL(kind: .cask): [tapResponse("7.8")]]), installed: reader)
        let refresh = Task { await c.refreshCatalogIfDue() }
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while reader.count == 0, ContinuousClock.now < deadline { await Task.yield() }
        try #require(reader.count == 1)
        let check = Task { await c.checkNow() }
        for _ in 0..<100 { await Task.yield() }
        reader.release.signal(); await refresh.value; await check.value
        #expect(reader.count <= 2)
        #expect(c.others.map(\.listing.name) == [full, full])
        #expect(Set(c.others.map(\.listing.version)) == ["4.5.6", "7.8"])
        #expect(c.suggestions(prefix: "synthetic-tool").filter(\.installed).count == 2)
    }
    @Test func officialRecoveryDoesNotClearOrDisplaceTapUpdates() async throws {
        let f = TapControllerFixture(); try f.seed()
        let clock = TapControllerClock()
        let bulk = StubTransport([catalogURL(.formula): [.failure(URLError(.timedOut)), catalogResponse(200, syntheticFormulaList)], catalogURL(.cask): [catalogResponse(200, syntheticCaskList)]])
        let c = WatchController(transport: StubTransport([tapURL(): [tapResponse(), tapResponse()]]), installed: TapInstallations(names: [.formula: [full]]), store: f.watch.store, notifier: RecordingNotifier(), now: { clock.date }, catalogClient: CatalogClient(transport: bulk, cacheDirectory: f.watch.directory.appendingPathComponent("cache")), taps: { f.index })
        await c.refreshCatalogIfDue()
        #expect(c.catalogRefreshError != nil && c.state.lastCatalogFetch == nil)
        #expect(c.others.map(\.listing.name) == [full])
        clock.date.addTimeInterval(600); await c.refreshCatalogIfDue()
        #expect(c.catalogRefreshError == nil && c.state.lastCatalogFetch == clock.date)
        #expect(c.others.map(\.listing.name) == [full])
    }
    @Test func installedTapRanksAboveMoreOfficialMatchesThanLimit() async throws {
        let f = TapControllerFixture(); try f.seed()
        let official = "[" + (0..<12).map { "{\"name\":\"synthetic-\($0)\",\"versions\":{\"stable\":\"9.0.1\"}}" }.joined(separator: ",") + "]"
        let bulk = StubTransport([catalogURL(.formula): [catalogResponse(200, official)], catalogURL(.cask): [catalogResponse(200, syntheticCaskList)]])
        let c = controller(f, StubTransport([tapURL(): [tapResponse()]]), installed: TapInstallations(names: [.formula: [full]]), catalog: CatalogClient(transport: bulk, cacheDirectory: f.watch.directory.appendingPathComponent("cache")))
        await c.refreshCatalogIfDue()
        #expect(c.suggestions(prefix: "synthetic", limit: 8).count == 8)
        #expect(c.suggestions(prefix: "synthetic", limit: 8).first?.name == full)
    }
    @Test func tapFailureRetainsLastKindSpecificListings() async throws {
        let f = TapControllerFixture(); try f.seed(); try f.seed(kind: .cask)
        let clock = TapControllerClock()
        let c = WatchController(transport: StubTransport([tapURL(): [tapResponse(), .failure(URLError(.timedOut))], tapURL(kind: .cask): [tapResponse("7.8"), tapResponse("9.0.1")]]), installed: TapInstallations(names: [.formula: [full], .cask: [full]]), store: f.watch.store, notifier: RecordingNotifier(), now: { clock.date }, taps: { f.index })
        await c.refreshCatalogIfDue(); clock.date.addTimeInterval(600); await c.refreshCatalogIfDue()
        #expect(c.others.first { $0.listing.kind == .formula }?.listing.version == "4.5.6")
        #expect(c.others.first { $0.listing.kind == .cask }?.listing.version == "9.0.1")
        #expect(c.tapCheckFailures == 1)
    }
}

extension TapControllerTests {
    @Test func resolvedAddPreservesWatchRestoredDuringInstalledRead() async throws {
        let f = TapControllerFixture(); try f.seed()
        let reader = HeldTapInstallation()
        let c = controller(f, StubTransport([watchURL(bare): [tapMissing], tapURL(): [tapResponse()]]), installed: reader)
        let pending = Task { await c.add(bare, kind: .formula) }
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while reader.count == 0, ContinuousClock.now < deadline { await Task.yield() }
        try #require(reader.count == 1)
        let listing = Listing(name: full, kind: .formula, version: "7.8")
        let restored = WatchEntry(name: full, kind: .formula, lastListing: listing, lastSeenRelease: ReleaseID(listing), notifiedRelease: ReleaseID(listing), skippedRelease: ReleaseID(listing), unseenRelease: true)
        #expect(c.restore(restored, at: 0))
        reader.release.signal(); await pending.value
        #expect(c.state.watched == [restored])
        #expect(f.watch.store.load().state.watched == [restored])
    }
    @Test func canonicalResolvedIdentitySurvivesCheckAndPersistence() async throws {
        let f = TapControllerFixture(); try f.seed()
        let source = f.root.appendingPathComponent("Library/Taps/synthetic-owner/homebrew-synthetic-tap")
        let destination = source.deletingLastPathComponent().appendingPathComponent("homebrew-homebrew-synthetic-tap")
        try FileManager.default.moveItem(at: source, to: destination)
        let canonical = try #require(f.index.entries(shortName: bare.shortName, kinds: .formula).first?.name)
        #expect(canonical.rawValue == "synthetic-owner/homebrew-synthetic-tap/synthetic-tool")
        let t = StubTransport([watchURL(bare): [tapMissing], tapURL(): [tapResponse(), tapResponse("7.8")]])
        let c = controller(f, t, installed: TapInstallations(names: [.formula: [canonical]]))
        await c.add(bare, kind: .formula); await c.checkNow()
        #expect(c.state.watched.first?.name == canonical)
        #expect(c.state.watched.first?.lastListing?.name == canonical)
        #expect(c.state.watched.first?.installed?.version == "1.2.3")
        #expect(f.watch.store.load().state.watched.first?.name == canonical)
    }
    @Test func tapUnreachableKeepsCheckTimestampAndRetriesOnReconnect() async throws {
        let f = TapControllerFixture(); try f.seed()
        var state = AppState.initial
        state.lastCheck = Date(timeIntervalSince1970: 42)
        state.watched = [WatchEntry(name: full, kind: .formula)]
        try f.watch.store.save(state)
        let c = controller(f, StubTransport([tapURL(): [.failure(URLError(.timedOut)), tapResponse()]]))
        await c.checkNow()
        #expect(c.state.lastCheck == state.lastCheck)
        await c.setNetworkAvailable(false); await c.setNetworkAvailable(true)
        #expect(c.state.watched.first?.lastListing?.version == "4.5.6")
        #expect(c.state.lastCheck != state.lastCheck)
    }
}
