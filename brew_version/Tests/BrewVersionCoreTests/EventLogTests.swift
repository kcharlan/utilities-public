import Foundation
import Testing
@testable import BrewVersionCore

struct EventLogTests {
    @Test func recordsPrivateJSONLinesAndTruncatesStrings() async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("brew-version-log-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: dir) }
        let log = EventLog(directory: dir, now: { Date(timeIntervalSince1970: 0) })
        log.record("synthetic", ["value": .string(String(repeating: "x", count: 501))])
        await log.flush()
        let data = try Data(contentsOf: log.fileURL)
        let object = try #require(JSONSerialization.jsonObject(with: data) as? [String: String])
        #expect(object["event"] == "synthetic")
        #expect(object["t"] == "1970-01-01T00:00:00.000Z")
        #expect(object["value"] == String(repeating: "x", count: 500) + "…")
        #expect((try FileManager.default.attributesOfItem(atPath: dir.path)[.posixPermissions] as? Int) == 0o700)
        #expect((try FileManager.default.attributesOfItem(atPath: log.fileURL.path)[.posixPermissions] as? Int) == 0o600)
    }
    @Test func rotatesExistingAndBoundsArchives() async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("brew-version-log-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: dir) }
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try Data(repeating: 65, count: 20).write(to: dir.appendingPathComponent("events.jsonl"))
        let log = EventLog(directory: dir, maxBytes: 10, archives: 2)
        await log.flush()
        #expect(FileManager.default.fileExists(atPath: dir.appendingPathComponent("events.1.jsonl").path))
        for _ in 0..<5 { log.record("synthetic", [:]); await log.flush() }
        #expect(FileManager.default.fileExists(atPath: dir.appendingPathComponent("events.1.jsonl").path))
        #expect(FileManager.default.fileExists(atPath: dir.appendingPathComponent("events.2.jsonl").path))
        #expect(!FileManager.default.fileExists(atPath: dir.appendingPathComponent("events.3.jsonl").path))
    }
    @Test func reportsWriteFailureWithoutThrowing() async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("brew-version-log-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: dir) }
        try Data().write(to: dir)
        let log = EventLog(directory: dir)
        log.record("synthetic", [:]); await log.flush()
        #expect(log.lastWriteError != nil)
    }
}
