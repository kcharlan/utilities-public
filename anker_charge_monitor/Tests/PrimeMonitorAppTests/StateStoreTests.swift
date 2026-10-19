import Foundation
import Testing
import PrimeMonitorCore
@testable import PrimeMonitor
@Suite struct StateStoreTests {
    @Test func decodedPathsPreserveAtomicReplacementAndQuarantine() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: root) }
        let directory = root.appending(path: "spaces % café/%2F", directoryHint: .isDirectory)
        let store = StateStore(fileURL: directory.appending(path: "state.json", directoryHint: .notDirectory))
        let first = AppState(charger: appCharger, closedInterval: .m5)
        try store.save(first)
        let reader = try FileHandle(forReadingFrom: store.fileURL)
        defer { try? reader.close() }
        try store.save(.initial)
        #expect(store.load().state == .initial)
        let heldBytes = try #require(try reader.readToEnd())
        #expect(try JSONDecoder().decode(AppState.self, from: heldBytes) == first)
        try Data("first corrupt state".utf8).write(to: store.fileURL)
        #expect(store.load().canSave)
        try Data("second corrupt state".utf8).write(to: store.fileURL)
        #expect(store.load().canSave)
        let files = try FileManager.default.contentsOfDirectory(atPath: directory.path(percentEncoded: false))
        #expect(files.contains("state.json.bad"))
        #expect(files.filter { $0.hasPrefix("state.json.bad-") }.count == 1)
        #expect(!files.contains { $0.hasPrefix(".state-") })
        #expect(!FileManager.default.fileExists(atPath: directory.path(percentEncoded: true)))
        #expect(!FileManager.default.fileExists(atPath: store.fileURL.path(percentEncoded: false)))
        try store.save(first)
        #expect(store.load().state == first)
        #expect(try FileManager.default.contentsOfDirectory(atPath: root.path(percentEncoded: false)) == ["spaces % café"])
    }
    @Test func roundTripAndDefaults() throws {
        let directory = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = StateStore(fileURL: directory.appending(path: "state.json", directoryHint: .notDirectory))
        #expect(store.load().state == AppState(charger: nil, closedInterval: .m1))
        let value = AppState(charger: appCharger, closedInterval: .m5)
        try store.save(value); #expect(store.load().state == value)
        #expect(try FileManager.default.attributesOfItem(atPath: directory.path(percentEncoded: false))[.posixPermissions] as? Int == 0o700)
        #expect(try FileManager.default.attributesOfItem(atPath: store.fileURL.path(percentEncoded: false))[.posixPermissions] as? Int == 0o600)
        try Data("invalid".utf8).write(to: store.fileURL)
        let bad = store.load(); #expect(bad.problem != nil); #expect(bad.canSave); #expect(bad.state.charger == nil)
        #expect(FileManager.default.fileExists(atPath: store.fileURL.appendingPathExtension("bad").path(percentEncoded: false)))
        try store.save(value); #expect(store.load().state == value)
    }
}
