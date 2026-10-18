import Foundation
import Testing
@testable import BrewVersionCore

@MainActor private final class CadenceClock {
    var date = Date(timeIntervalSince1970: 2_000_000)
}

private func repeatedCatalog(_ count: Int, cask: String = syntheticCaskList) -> StubTransport {
    StubTransport([catalogURL(.formula): Array(repeating: catalogResponse(200, syntheticFormulaList), count: count),
                   catalogURL(.cask): Array(repeating: catalogResponse(200, cask), count: count)])
}

@MainActor struct CatalogCadenceTests {
    @Test func savedStateWithoutNewSettingsLoadsWithDefaults() throws {
        let f = WatchFixture(); defer { f.clean() }
        var state = AppState.initial; state.catalogInterval = CheckInterval(minutes: 240)!; state.includeSelfUpdating = true
        try f.store.save(state)
        // Remove the keys a 1.0.1 state file never had.
        var object = try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: f.file)) as? [String: Any])
        object.removeValue(forKey: "catalogInterval"); object.removeValue(forKey: "includeSelfUpdating")
        try JSONSerialization.data(withJSONObject: object).write(to: f.file)
        let load = f.store.load()
        #expect(load.problem == nil && load.canSave)
        #expect(load.state.catalogInterval == .catalogStandard && !load.state.includeSelfUpdating)
        #expect(!FileManager.default.fileExists(atPath: f.file.path + ".bad"))
    }
    @Test func catalogIntervalPresetsAndDefault() {
        #expect(CheckInterval.catalogStandard.minutes == 60)
        #expect(CheckInterval.catalogPresets.map(\.label) == ["30 minutes", "1 hour", "2 hours", "4 hours", "12 hours", "24 hours"])
        #expect(AppState.initial.catalogInterval == .catalogStandard)
    }
    @Test func catalogIntervalControlsAutomaticRefresh() async throws {
        let f = WatchFixture(); defer { f.clean() }
        let directory = f.directory.appendingPathComponent("catalog"); _ = try await seedCatalog(directory)
        let clock = CadenceClock()
        var state = AppState.initial; state.lastCatalogFetch = clock.date; state.catalogInterval = CheckInterval(minutes: 120)!
        try f.store.save(state)
        let bulk = repeatedCatalog(2)
        let c = WatchController(transport: StubTransport([:]), installed: nil, store: f.store, notifier: RecordingNotifier(),
                                now: { clock.date }, catalogClient: CatalogClient(transport: bulk, cacheDirectory: directory))
        await c.refreshCatalogIfDue()
        #expect(await bulk.requests.count == 2)
        clock.date.addTimeInterval(3600); await c.refreshCatalogIfDue()
        #expect(await bulk.requests.count == 2)
        clock.date.addTimeInterval(3600); await c.refreshCatalogIfDue()
        #expect(await bulk.requests.count == 4)
        #expect(c.state.lastCatalogFetch == clock.date)
        c.setCatalogInterval(CheckInterval(minutes: 30)!)
        #expect(f.store.load().state.catalogInterval.minutes == 30)
    }
    @Test func manualRefreshSkipsFreshCatalogAndIgnoresNetworkGate() async throws {
        let f = WatchFixture(); defer { f.clean() }
        let directory = f.directory.appendingPathComponent("catalog"); _ = try await seedCatalog(directory)
        let clock = CadenceClock()
        var state = AppState.initial; state.lastCatalogFetch = clock.date.addingTimeInterval(-300); try f.store.save(state)
        let bulk = repeatedCatalog(1)
        let c = WatchController(transport: StubTransport([:]), installed: nil, store: f.store, notifier: RecordingNotifier(),
                                now: { clock.date }, catalogClient: CatalogClient(transport: bulk, cacheDirectory: directory),
                                networkAvailable: false)
        await c.refreshNow()
        #expect(await bulk.requests.isEmpty)
        clock.date.addTimeInterval(300); await c.refreshNow()
        #expect(await bulk.requests.count == 2)
        #expect(c.state.lastCatalogFetch == clock.date)
    }
    @Test func failedRefreshReportsReasonUntilNextSuccess() async throws {
        let f = WatchFixture(); defer { f.clean() }
        let directory = f.directory.appendingPathComponent("catalog"); _ = try await seedCatalog(directory)
        let clock = CadenceClock()
        var state = AppState.initial; state.lastCatalogFetch = clock.date.addingTimeInterval(-7200); try f.store.save(state)
        let bulk = StubTransport([catalogURL(.formula): [catalogResponse(500), catalogResponse(200, syntheticFormulaList)],
                                  catalogURL(.cask): [catalogResponse(200, syntheticCaskList)]])
        let c = WatchController(transport: StubTransport([:]), installed: nil, store: f.store, notifier: RecordingNotifier(),
                                now: { clock.date }, catalogClient: CatalogClient(transport: bulk, cacheDirectory: directory))
        await c.refreshCatalogIfDue()
        #expect(c.catalogRefreshError == "Homebrew returned HTTP 500.")
        #expect(c.state.lastCatalogFetch == state.lastCatalogFetch)
        #expect(c.catalog?.suggestions(prefix: "synthetic").count == 2)
        // A failed launch refresh retries after the shortest check interval.
        clock.date.addTimeInterval(600); await c.refreshCatalogIfDue()
        #expect(c.catalogRefreshError == nil && c.state.lastCatalogFetch == clock.date)
    }
    @Test func unreadableSelfUpdatingCasksAreHiddenUntilIncluded() async throws {
        let f = try InstallationFixture()
        try f.install("prefix/Caskroom/synthetic-cask/1", kind: .cask)
        try f.install("prefix/Caskroom/synthetic-unreadable/1", kind: .cask)
        try f.app("1")
        let casks = #"[{"token":"synthetic-cask","version":"3","auto_updates":true,"artifacts":[{"app":["Synthetic.app"]}]},{"token":"synthetic-unreadable","version":"3","auto_updates":true,"artifacts":[{"app":["Synthetic Missing.app"]}]}]"#
        let store = WatchStore(fileURL: f.root.appendingPathComponent("state/state.json"))
        let c = WatchController(transport: StubTransport([:]), installed: f.reader(), store: store, notifier: RecordingNotifier(),
                                catalogClient: CatalogClient(transport: repeatedCatalog(1, cask: casks), cacheDirectory: f.root.appendingPathComponent("catalog")))
        await c.refreshCatalogIfDue()
        // The readable app is really behind, so it stays; the unreadable one is hidden.
        #expect(c.others.map(\.listing.name.rawValue) == ["synthetic-cask"])
        #expect(c.others.first?.installed.source == .appBundle)
        #expect(c.hiddenSelfUpdatingCount == 1)
        c.setIncludeSelfUpdating(true)
        #expect(c.others.map(\.listing.name.rawValue) == ["synthetic-cask", "synthetic-unreadable"])
        #expect(c.hiddenSelfUpdatingCount == 0)
        #expect(store.load().state.includeSelfUpdating)
    }
}
