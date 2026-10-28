import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

/// Collects results from helper threads.
private final class Outcomes: @unchecked Sendable {
    private let lock = NSLock()
    private var errors: [String] = []
    private var finished = 0
    private var seconds: TimeInterval = 0

    func finish(error: (any Error)? = nil) {
        lock.lock()
        defer { lock.unlock() }
        finished += 1
        if let error { errors.append("\(error)") }
    }

    func recordWait(_ value: TimeInterval) {
        lock.lock()
        defer { lock.unlock() }
        seconds = value
    }

    var snapshot: (finished: Int, errors: [String], wait: TimeInterval) {
        lock.lock()
        defer { lock.unlock() }
        return (finished, errors, seconds)
    }

    func waitUntilFinished(_ count: Int, timeout: TimeInterval) {
        let deadline = Date().addingTimeInterval(timeout)
        while snapshot.finished < count, Date() < deadline { Thread.sleep(forTimeInterval: 0.01) }
    }
}

private struct Abort: Error {}

@Suite struct StoreTests {
    /// Every table Schema v1 holds (spec section 4 plus the task brief's table list).
    static let schemaV1Tables = [
        "baseline_epochs", "collector_runs", "connection_events", "cursors", "episodes", "eval_points",
        "events", "failed_turns", "incidents", "responses", "rule_state", "settings", "shift_dismissals",
        "source_state", "status_components", "usage_limits",
    ]

    @Test func readWriteOpenCreatesWALDatabaseAtVersion1() throws {
        try withScratchDirectory { directory in
            let url = directory.appending(path: "nested/deeper/telltale.sqlite")
            let store = try Store.open(url, mode: .readWrite)
            withExtendedLifetime(store) {}
            let tables = try RawSQLite.column(url, "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
            #expect(tables == Self.schemaV1Tables)
            #expect(try RawSQLite.scalar(url, "PRAGMA user_version") == "1")
            #expect(try RawSQLite.scalar(url, "PRAGMA journal_mode") == "wal")
            let indexes = try RawSQLite.column(url, "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'responses'")
            #expect(indexes.contains("idx_responses_provider_model_end"))
            #expect(indexes.contains("idx_responses_turn"))
        }
    }

    @Test func readWriteOpenEnablesForeignKeys() throws {
        try withScratchDirectory { directory in
            let store = try Store.open(directory.appending(path: "telltale.sqlite"), mode: .readWrite)
            #expect(throws: StoreError.self) {
                try store.exec("INSERT INTO events (at, kind, provider, scope, title, body, episode_id) VALUES (0, 'k', 'p', 's', 't', 'b', 999)")
            }
        }
    }

    @Test func reopeningAMigratedDatabaseKeepsItsData() throws {
        try withScratchDirectory { directory in
            let url = directory.appending(path: "telltale.sqlite")
            try Store.open(url, mode: .readWrite).set(SettingKey.intervalMinutes, 9)
            #expect(try Store.open(url, mode: .readWrite).value(SettingKey.intervalMinutes) == 9)
        }
    }

    @Test func openRefusesANewerSchema() throws {
        try withScratchDirectory { directory in
            let url = directory.appending(path: "telltale.sqlite")
            try Store.open(url, mode: .readWrite).set(SettingKey.intervalMinutes, 9)
            try RawSQLite.rows(url, "PRAGMA user_version = 2")
            #expect(throws: StoreError.unsupportedSchemaVersion(2)) { try Store.open(url, mode: .readWrite) }
            #expect(throws: StoreError.unsupportedSchemaVersion(2)) { try Store.open(url, mode: .readOnly) }
        }
    }

    @Test func readOnlyOpenOfMissingDatabaseThrowsNotInitialized() throws {
        try withScratchDirectory { directory in
            let url = directory.appending(path: "absent/telltale.sqlite")
            #expect(throws: StoreError.notInitialized) { try Store.open(url, mode: .readOnly) }
            #expect(!FileManager.default.fileExists(atPath: url.deletingLastPathComponent().path))
        }
    }

    @Test func readOnlyOpenOfUnmigratedDatabaseThrowsNotInitialized() throws {
        try withScratchDirectory { directory in
            let url = directory.appending(path: "telltale.sqlite")
            try RawSQLite.rows(url, "CREATE TABLE unrelated (x INTEGER)")
            #expect(throws: StoreError.notInitialized) { try Store.open(url, mode: .readOnly) }
            // Read-only never migrates.
            #expect(try RawSQLite.scalar(url, "PRAGMA user_version") == "0")
            #expect(try RawSQLite.column(url, "SELECT name FROM sqlite_master WHERE type = 'table'") == ["unrelated"])
        }
    }

    /// Ruling R27: the app writes only into a database the collector created and migrated.
    @Test func existingReadWriteOpenNeverCreatesOrMigrates() throws {
        try withScratchDirectory { directory in
            let absent = directory.appending(path: "absent/telltale.sqlite")
            #expect(throws: StoreError.notInitialized) { try Store.open(absent, mode: .readWriteExisting) }
            #expect(!FileManager.default.fileExists(atPath: absent.deletingLastPathComponent().path))

            let empty = directory.appending(path: "empty.sqlite")
            #expect(FileManager.default.createFile(atPath: empty.path, contents: Data()))
            #expect(throws: StoreError.notInitialized) { try Store.open(empty, mode: .readWriteExisting) }
            #expect(try FileManager.default.attributesOfItem(atPath: empty.path)[.size] as? Int == 0)

            let unmigrated = directory.appending(path: "unmigrated.sqlite")
            try RawSQLite.rows(unmigrated, "CREATE TABLE unrelated (x INTEGER)")
            #expect(throws: StoreError.notInitialized) { try Store.open(unmigrated, mode: .readWriteExisting) }
            #expect(try RawSQLite.scalar(unmigrated, "PRAGMA user_version") == "0")

            let url = directory.appending(path: "telltale.sqlite")
            try Store.open(url, mode: .readWrite).set(SettingKey.intervalMinutes, 9)
            let writer = try Store.open(url, mode: .readWriteExisting)
            try writer.transaction { try writer.set(SettingKey.intervalMinutes, 12) }
            #expect(try Store.open(url, mode: .readOnly).value(SettingKey.intervalMinutes) == 12)
            try RawSQLite.rows(url, "PRAGMA user_version = 2")
            #expect(throws: StoreError.unsupportedSchemaVersion(2)) { try Store.open(url, mode: .readWriteExisting) }
        }
    }

    @Test func readOnlyConnectionCannotWrite() throws {
        try withScratchDirectory { directory in
            let url = directory.appending(path: "telltale.sqlite")
            let writer = try Store.open(url, mode: .readWrite)
            try writer.set(SettingKey.intervalMinutes, 12)
            let reader = try Store.open(url, mode: .readOnly)
            #expect(try reader.value(SettingKey.intervalMinutes) == 12)
            #expect(throws: StoreError.self) { try reader.set(SettingKey.intervalMinutes, 30) }
            #expect(throws: StoreError.self) { try reader.upsert(responses: [Synthetic.response(1, endingAt: 100)]) }
            #expect(try reader.value(SettingKey.intervalMinutes) == 12)
        }
    }

    @Test func readOnlyTransactionSeesOneSnapshot() throws {
        try withScratchDirectory { directory in
            let url = directory.appending(path: "telltale.sqlite")
            let writer = try Store.open(url, mode: .readWrite)
            try writer.set(SettingKey.intervalMinutes, 7)
            let reader = try Store.open(url, mode: .readOnly)
            let (first, second) = try reader.transaction {
                let first = try reader.value(SettingKey.intervalMinutes)
                try writer.set(SettingKey.intervalMinutes, 8)
                return (first, try reader.value(SettingKey.intervalMinutes))
            }
            #expect(first == 7 && second == 7)
            #expect(try reader.value(SettingKey.intervalMinutes) == 8)
        }
    }

    @Test func throwingTransactionRollsBack() throws {
        try withScratchDirectory { directory in
            let store = try Store.open(directory.appending(path: "telltale.sqlite"), mode: .readWrite)
            var aborted = false
            do {
                try store.transaction { () throws -> Void in
                    try store.set(SettingKey.intervalMinutes, 42)
                    throw Abort()
                }
            } catch is Abort {
                aborted = true
            }
            #expect(aborted)
            #expect(try store.value(SettingKey.intervalMinutes) == 5)
            // Nested use joins the outer transaction rather than failing.
            try store.transaction { try store.transaction { try store.set(SettingKey.intervalMinutes, 11) } }
            #expect(try store.value(SettingKey.intervalMinutes) == 11)
        }
    }

    @Test func concurrentFirstOpensMigrateOnce() throws {
        try withScratchDirectory { (directory) throws in
            let url = directory.appending(path: "shared/telltale.sqlite")
            let count = 8
            let outcomes = Outcomes()
            let gate = DispatchSemaphore(value: 0)
            for index in 0..<count {
                Thread {
                    gate.wait()
                    do {
                        // Schema v1 uses plain CREATE TABLE, so a second migration would throw "already exists".
                        let store = try Store.open(url, mode: .readWrite)
                        try store.set(SettingKey.intervalMinutes, index + 1)
                        outcomes.finish()
                    } catch {
                        outcomes.finish(error: error)
                    }
                }.start()
            }
            for _ in 0..<count { gate.signal() }
            outcomes.waitUntilFinished(count, timeout: 30)
            let result = outcomes.snapshot
            #expect(result.finished == count)
            #expect(result.errors.isEmpty, "\(result.errors)")
            #expect(try RawSQLite.scalar(url, "PRAGMA user_version") == "1")
            #expect(try RawSQLite.column(url, "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name") == Self.schemaV1Tables)
        }
    }

    /// Timing values live here: the second connection's write waits for the first's
    /// 0.3 s transaction, well inside its 5 s busy timeout.
    @Test func writerDuringOpenTransactionWaitsWithinBusyTimeout() throws {
        try withScratchDirectory { directory in
            let url = directory.appending(path: "telltale.sqlite")
            let holder = try Store.open(url, mode: .readWrite)
            let outcomes = Outcomes()
            let opened = DispatchSemaphore(value: 0)
            let proceed = DispatchSemaphore(value: 0)
            Thread {
                do {
                    let writer = try Store.open(url, mode: .readWrite, busyTimeout: .seconds(5))
                    opened.signal()
                    proceed.wait()
                    let began = Date()
                    try writer.set(SettingKey.intervalMinutes, 17)
                    outcomes.recordWait(Date().timeIntervalSince(began))
                    outcomes.finish()
                } catch {
                    opened.signal()
                    outcomes.finish(error: error)
                }
            }.start()
            opened.wait()
            try holder.transaction {
                try holder.set(SettingKey.collectorEnabled, false)
                proceed.signal()
                Thread.sleep(forTimeInterval: 0.3)
            }
            outcomes.waitUntilFinished(1, timeout: 10)
            let result = outcomes.snapshot
            #expect(result.errors.isEmpty, "\(result.errors)")
            #expect(result.finished == 1)
            #expect(result.wait > 0.1, "the write should have waited for the open transaction")
            #expect(try holder.value(SettingKey.intervalMinutes) == 17)
            #expect(try holder.value(SettingKey.collectorEnabled) == false)
        }
    }

    @Test func writerGivesUpAfterTheBusyTimeout() throws {
        try withScratchDirectory { directory in
            let url = directory.appending(path: "telltale.sqlite")
            let holder = try Store.open(url, mode: .readWrite)
            let impatient = try Store.open(url, mode: .readWrite, busyTimeout: .milliseconds(100))
            try holder.transaction {
                try holder.set(SettingKey.collectorEnabled, false)
                #expect(throws: StoreError.self) { try impatient.set(SettingKey.intervalMinutes, 17) }
            }
            try impatient.set(SettingKey.intervalMinutes, 17)
            #expect(try holder.value(SettingKey.intervalMinutes) == 17)
        }
    }
}
