import Foundation
import Testing
import TelltaleCore
import TelltaleTestSupport
@testable import Telltale

/// Spec section 4's database-read contract for the panel: read-only, refreshed by filesystem
/// changes and a poll, never creating or initializing the database.
@MainActor @Suite struct LiveStoreTests {
    @Test func refreshesWhenDatabaseChanges() async throws {
        try await withAsyncScratchDirectory { directory in
            let paths = PanelWorld.paths(directory)
            let writer = try PanelWorld.seed(paths)
            // An hour's poll: only the filesystem watch can see the change in time.
            let live = PanelWorld.live(paths, watch: true)
            #expect(live.snapshot.checkedAt != nil && live.snapshot.alerts.isEmpty)
            #expect(live.snapshot.models.map(\.name) == ["Example"])
            live.start()
            defer { live.stop() }
            try PanelWorld.addAlert(writer)
            #expect(await eventually { live.snapshot.alerts.map(\.text) == [PanelWorld.alertText] })
            #expect(live.snapshot.lamps[.speed] == .amber)
        }
    }

    @Test func pollFallbackRefreshes() async throws {
        try await withAsyncScratchDirectory { directory in
            let paths = PanelWorld.paths(directory)
            let writer = try PanelWorld.seed(paths)
            let live = PanelWorld.live(paths, poll: .milliseconds(50), watch: false)
            live.start()
            defer { live.stop() }
            try PanelWorld.addAlert(writer)
            #expect(await eventually { live.snapshot.mostSevere == .amber })
        }
    }

    @Test func missingDatabaseWaitsThenLoadsAfterCollectorCreatesIt() async throws {
        try await withAsyncScratchDirectory { directory in
            let paths = PanelWorld.paths(directory)
            let live = PanelWorld.live(paths, watch: true)
            live.start()
            defer { live.stop() }
            await live.refresh()
            #expect(live.snapshot == PanelSnapshot.waiting(sources: PanelWorld.sources))
            #expect(live.snapshot.footer == "Waiting for the collector's first run.")
            #expect(live.snapshot.checkedAt == nil && live.snapshot.models.isEmpty && live.lastError == nil)
            // Reading never creates the database or its directory.
            #expect(!FileManager.default.fileExists(atPath: paths.appSupport.path))

            try PanelWorld.seed(paths)
            #expect(await eventually { live.snapshot.checkedAt != nil })
            #expect(live.snapshot.models.map(\.name) == ["Example"] && live.lastError == nil)
        }
    }

    @Test func uninitializedDatabaseIsRetried() async throws {
        try await withAsyncScratchDirectory { directory in
            let paths = PanelWorld.paths(directory)
            // The collector has created the file but not yet migrated it.
            try FileManager.default.createDirectory(at: paths.appSupport, withIntermediateDirectories: true)
            #expect(FileManager.default.createFile(atPath: paths.database.path, contents: Data()))
            let live = PanelWorld.live(paths, poll: .milliseconds(50), watch: false)
            #expect(live.snapshot == PanelSnapshot.waiting(sources: PanelWorld.sources) && live.lastError == nil)
            // Still empty: the app never initializes it.
            #expect(try FileManager.default.attributesOfItem(atPath: paths.database.path)[.size] as? Int == 0)

            live.start()
            defer { live.stop() }
            try PanelWorld.seed(paths)
            #expect(await eventually { live.snapshot.checkedAt != nil })
        }
    }

    @Test func databaseReadFailureIsVisibleAndRetryable() async throws {
        try await withAsyncScratchDirectory { directory in
            let paths = PanelWorld.paths(directory)
            try PanelWorld.seed(paths, alerting: true)
            let live = PanelWorld.live(paths)
            let loaded = live.snapshot
            #expect(loaded.alerts.count == 1 && loaded.checkedAt != nil)

            // Something replaces the database with a file SQLite can't read.
            try removeDatabase(paths)
            try Data("synthetic non-database bytes".utf8).write(to: paths.database)
            await live.refresh()
            let error = try #require(live.lastError)
            #expect(error.hasPrefix("Telltale can't read its database: ") && error.hasSuffix(". Retrying automatically."))
            // The previous snapshot stays, marked stale by the footer.
            #expect(live.snapshot.alerts == loaded.alerts && live.snapshot.models == loaded.models && live.snapshot.checkedAt == loaded.checkedAt)
            #expect(live.snapshot.footer == error)

            // The same path recovers once the collector writes a good database again.
            try removeDatabase(paths)
            try PanelWorld.seed(paths)
            await live.refresh()
            #expect(live.lastError == nil)
            #expect(live.snapshot.alerts.isEmpty && live.snapshot.checkedAt != nil && live.snapshot.footer == "")
        }
    }

    private func removeDatabase(_ paths: TelltalePaths) throws {
        for suffix in ["", "-wal", "-shm"] {
            let url = URL(fileURLWithPath: paths.database.path + suffix)
            if FileManager.default.fileExists(atPath: url.path) { try FileManager.default.removeItem(at: url) }
        }
    }
}
