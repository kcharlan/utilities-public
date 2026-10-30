import Foundation
import Testing
@testable import BrewVersion
@testable import BrewVersionCore

private actor UndoExpiryGate {
    private var continuation: CheckedContinuation<Void, Never>?
    var ready: Bool { continuation != nil }
    func wait() async { await withCheckedContinuation { continuation = $0 } }
    func finish() { continuation?.resume(); continuation = nil }
}
private struct UndoTransport: HTTPTransport {
    func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse { .init(status: 404, body: Data()) }
}
private struct UndoNotifier: Notifier {}
private struct UndoFixture {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("brew-version-synthetic-undo-" + UUID().uuidString)
    var file: URL { directory.appendingPathComponent("state.json") }
    var failure: URL { directory.appendingPathComponent("synthetic-fail-replace") }
    var store: WatchStore {
        let failure = self.failure
        var io = WatchStoreIO.live
        io.replace = { source, destination in
            if FileManager.default.fileExists(atPath: failure.path) { throw CocoaError(.fileWriteUnknown) }
            try WatchStoreIO.live.replace(source, destination)
        }
        return WatchStore(fileURL: file, io: io)
    }
    @MainActor func controller(_ entries: [WatchEntry]) throws -> WatchController {
        var state = AppState.initial; state.watched = entries; try store.save(state)
        return WatchController(transport: UndoTransport(), installed: nil, store: store, notifier: UndoNotifier())
    }
    func entry(_ name: String = "synthetic-undo") -> WatchEntry {
        let listing = Listing(name: PackageName(name)!, kind: .formula, version: "2.0-synthetic")
        let identity = ReleaseID(listing)
        return WatchEntry(name: listing.name, kind: listing.kind, lastListing: listing,
            lastSeenRelease: identity, notifiedRelease: identity, skippedRelease: identity)
    }
    func clean() { try? FileManager.default.removeItem(at: directory) }
}
@MainActor struct WatchUndoTests {
    @Test func failedRestorationRetainsUndoAfterExpiryAndRetriesFullEntry() async throws {
        let f = UndoFixture(); defer { f.clean() }
        let entry = f.entry(); let other = f.entry("synthetic-other")
        let controller = try f.controller([entry, other])
        let expiry = UndoExpiryGate()
        let undo = WatchUndoAction(waitForExpiry: { await expiry.wait() })
        #expect(undo.remove(entry.name, controller: controller))
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while !(await expiry.ready), ContinuousClock.now < deadline { await Task.yield() }
        try #require(await expiry.ready)
        let expiryTask = undo.expiryTask
        let removedBytes = try Data(contentsOf: f.file)
        try Data().write(to: f.failure)
        undo.restore(controller: controller)
        #expect(controller.state.watched == [other])
        #expect(controller.persistenceError != nil)
        #expect(undo.removed?.entry == entry)
        #expect(undo.retryRequired && !undo.canRemove)
        #expect(!undo.remove(other.name, controller: controller))
        #expect(try Data(contentsOf: f.file) == removedBytes)
        await expiry.finish(); await expiryTask?.value
        #expect(undo.removed?.entry == entry)
        try FileManager.default.removeItem(at: f.failure)
        undo.restore(controller: controller)
        #expect(undo.removed == nil && !undo.retryRequired && undo.canRemove)
        #expect(controller.persistenceError == nil)
        #expect(controller.state.watched == [entry, other])
        #expect(f.store.load().state.watched == [entry, other])
    }
    @Test func watchForPendingNameRetriesSavedEntryInsteadOfAddingFresh() async throws {
        let f = UndoFixture(); defer { f.clean() }
        let entry = f.entry()
        let controller = try f.controller([entry])
        let undo = WatchUndoAction()
        #expect(undo.remove(entry.name, controller: controller))
        try Data().write(to: f.failure)
        undo.restore(controller: controller)
        await undo.watch(entry.name, kind: .formula, controller: controller)
        #expect(controller.state.watched.isEmpty && undo.removed?.entry == entry)
        try FileManager.default.removeItem(at: f.failure)
        await undo.watch(entry.name, kind: .formula, controller: controller)
        #expect(controller.state.watched == [entry])
        #expect(f.store.load().state.watched == [entry])
        #expect(undo.removed == nil && undo.canRemove && !undo.retryRequired)
        #expect(controller.persistenceError == nil)
    }
    @Test func normalRemovalExpiresWithoutRestoring() async throws {
        let f = UndoFixture(); defer { f.clean() }
        let entry = f.entry(); let controller = try f.controller([entry])
        let undo = WatchUndoAction(waitForExpiry: {})
        #expect(undo.remove(entry.name, controller: controller))
        await undo.expiryTask?.value
        #expect(undo.removed == nil)
        #expect(controller.state.watched.isEmpty)
    }
}
