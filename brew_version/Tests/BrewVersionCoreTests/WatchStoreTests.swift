import Foundation
import Testing
@testable import BrewVersionCore

struct WatchFixture {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("brew-version-synthetic-brew-watch-\(UUID())")
    var file: URL { directory.appendingPathComponent("state.json") }
    var store: WatchStore { WatchStore(fileURL: file) }
    func clean() { try? FileManager.default.removeItem(at: directory) }
}
enum SyntheticIOError: Error { case denied }
final class IOFailures: @unchecked Sendable {
    private let lock = NSLock()
    private var value: String?
    var operation: String? {
        get { lock.withLock { value } }
        set { lock.withLock { value = newValue } }
    }
    var io: WatchStoreIO {
        WatchStoreIO(read: { url in
            if self.operation == "read" { throw SyntheticIOError.denied }
            return try Data(contentsOf: url)
        }, move: { from, to in
            if self.operation == "move" { throw SyntheticIOError.denied }
            try FileManager.default.moveItem(at: from, to: to)
        }, write: { data, url in
            if self.operation == "write" { throw SyntheticIOError.denied }
            try data.write(to: url)
        }, replace: { from, to in
            if self.operation == "replace" { throw SyntheticIOError.denied }
            try WatchStoreIO.live.replace(from, to)
        })
    }
}
struct WatchStoreTests {
    @Test func stateWithoutAlertListLoads() throws {
        let fixture = try #require(Bundle.module.url(forResource: "state-1.0.2", withExtension: "json", subdirectory: "Fixtures"))
        let f = WatchFixture(); defer { f.clean() }
        try FileManager.default.createDirectory(at: f.directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try FileManager.default.copyItem(at: fixture, to: f.file)
        let loaded = f.store.load()
        #expect(loaded.problem == nil && loaded.canSave)
        #expect(!loaded.state.watched.isEmpty)
        #expect(loaded.state.watched.allSatisfy { $0.alertPendingSince == nil })
        var state = loaded.state
        state.watched[0].alertPendingSince = Date(timeIntervalSince1970: 123)
        try f.store.save(state)
        #expect(f.store.load().state == state)
    }
    @Test func entryDecodingIgnoresUnknownKeys() throws {
        var entry = baseline()
        entry.alertPendingSince = Date(timeIntervalSince1970: 123)
        let encoded = try JSONEncoder().encode(entry)
        var object = try #require(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
        object["synthetic-future-key"] = "synthetic-value"
        let data = try JSONSerialization.data(withJSONObject: object)
        #expect(try JSONDecoder().decode(WatchEntry.self, from: data) == entry)
    }
    @Test func missingFile() {
        let f = WatchFixture(); defer { f.clean() }
        let loaded = f.store.load()
        #expect(loaded.state == .initial && loaded.problem == nil && loaded.canSave)
    }
    @Test func roundTrip() throws {
        let f = WatchFixture(); defer { f.clean() }
        var state = AppState.initial
        var entry = baseline()
        entry.skippedRelease = ReleaseID(watchListing())
        entry.notifiedRelease = ReleaseID(watchListing())
        entry.unseenRelease = true
        state.watched = [entry]
        state.lastCheck = Date(timeIntervalSince1970: 123)
        state.listingCache = [URL(string: "https://synthetic.invalid/listing")!: CachedListing(etag: "synthetic-etag", listing: watchListing())]
        try f.store.save(state)
        #expect(f.store.load().state == state)
    }
    @Test func privateModes() throws {
        let f = WatchFixture(); defer { f.clean() }
        try FileManager.default.createDirectory(at: f.directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o755])
        try f.store.save(.initial)
        #expect(try FileManager.default.attributesOfItem(atPath: f.directory.path)[.posixPermissions] as? Int == 0o700)
        #expect(try FileManager.default.attributesOfItem(atPath: f.file.path)[.posixPermissions] as? Int == 0o600)
    }
    func invalidStates() throws -> [Data] {
        var state = AppState.initial; state.watched = [baseline()]
        let valid = try JSONEncoder().encode(state)
        let object = try #require(JSONSerialization.jsonObject(with: valid) as? [String: Any])
        var schema = object; schema["schema"] = 99
        var interval = object; interval["interval"] = ["minutes": 9]
        var name = object
        var entries = try #require(name["watched"] as? [[String: Any]])
        var release = object
        var releaseEntries = entries
        releaseEntries[0]["lastSeenRelease"] = ["kind": "formula", "version": "", "revision": -1]
        release["watched"] = releaseEntries
        entries[0]["name"] = "Synthetic/INVALID"
        name["watched"] = entries
        return [Data("synthetic malformed JSON".utf8)] + (try [schema,interval,name,release].map { try JSONSerialization.data(withJSONObject: $0) })
    }
    @Test func corruptStateIsSetAside() throws {
        for data in try invalidStates() {
            let f = WatchFixture(); defer { f.clean() }
            try FileManager.default.createDirectory(at: f.directory, withIntermediateDirectories: true)
            try data.write(to: f.file)
            let loaded = f.store.load()
            #expect(loaded.canSave && loaded.problem != nil && loaded.state == .initial)
            #expect(!FileManager.default.fileExists(atPath: f.file.path))
            #expect(try Data(contentsOf: f.file.appendingPathExtension("bad")) == data)
        }
    }
    @Test func unreadableStateIsSetAside() throws {
        let f = WatchFixture(); defer { f.clean() }
        try f.store.save(.initial)
        let bytes = try Data(contentsOf: f.file)
        let failures = IOFailures(); failures.operation = "read"
        let loaded = WatchStore(fileURL: f.file, io: failures.io).load()
        #expect(loaded.canSave && loaded.problem != nil)
        #expect(try Data(contentsOf: f.file.appendingPathExtension("bad")) == bytes)
    }
    @Test func existingBadFileSurvives() throws {
        let f = WatchFixture(); defer { f.clean() }
        try f.store.save(.initial)
        let bad = f.file.appendingPathExtension("bad")
        try Data("synthetic earlier evidence".utf8).write(to: bad)
        try Data("synthetic new corruption".utf8).write(to: f.file)
        #expect(f.store.load().canSave)
        #expect(try String(contentsOf: bad, encoding: .utf8) == "synthetic earlier evidence")
        let files = try FileManager.default.contentsOfDirectory(at: f.directory, includingPropertiesForKeys: nil)
        let unique = try #require(files.first { $0.lastPathComponent.hasPrefix("state.json.bad-") })
        #expect(try String(contentsOf: unique, encoding: .utf8) == "synthetic new corruption")
    }
    @Test func quarantineFailureBlocksWrites() throws {
        let f = WatchFixture(); defer { f.clean() }
        try f.store.save(.initial)
        let corrupt = Data("synthetic corruption".utf8); try corrupt.write(to: f.file)
        let failures = IOFailures(); failures.operation = "move"
        let loaded = WatchStore(fileURL: f.file, io: failures.io).load()
        #expect(!loaded.canSave && loaded.problem != nil && loaded.state == .initial)
        #expect(try Data(contentsOf: f.file) == corrupt)
        #expect(try FileManager.default.contentsOfDirectory(atPath: f.directory.path) == ["state.json"])
    }
    @Test func saveFailureKeepsPreviousBytes() throws {
        let f = WatchFixture(); defer { f.clean() }
        try f.store.save(.initial)
        let bytes = try Data(contentsOf: f.file)
        let failures = IOFailures()
        var changed = AppState.initial; changed.showOtherUpdates = false
        for operation in ["write", "replace"] {
            failures.operation = operation
            #expect(throws: (any Error).self) { try WatchStore(fileURL: f.file, io: failures.io).save(changed) }
            #expect(try Data(contentsOf: f.file) == bytes)
            #expect(try FileManager.default.contentsOfDirectory(atPath: f.directory.path) == ["state.json"])
        }
    }
    @Test func decodedStateRejectsDuplicates() throws {
        let f = WatchFixture(); defer { f.clean() }
        var state = AppState.initial; state.watched = [baseline(), baseline()]
        try FileManager.default.createDirectory(at: f.directory, withIntermediateDirectories: true)
        try JSONEncoder().encode(state).write(to: f.file)
        #expect(f.store.load().problem != nil)
        for identity in [#"{"kind":"formula","version":"","revision":0}"#, #"{"kind":"formula","version":"1","revision":-1}"#] {
            #expect(throws: (any Error).self) { try JSONDecoder().decode(ReleaseID.self, from: Data(identity.utf8)) }
        }
        let cask = try JSONDecoder().decode(ReleaseID.self, from: Data(#"{"kind":"cask","version":"1","revision":5}"#.utf8))
        #expect(cask.revision == 0)
    }
}
