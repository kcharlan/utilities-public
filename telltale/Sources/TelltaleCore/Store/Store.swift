import Foundation
import SQLite3

public enum StoreError: Error, Equatable, Sendable, LocalizedError {
    /// A read-only open found no database, or one that was never migrated.
    case notInitialized
    /// The database was written by a newer Telltale.
    case unsupportedSchemaVersion(Int)
    case sqlite(code: Int32, message: String, context: String)
    case invalidData(String)

    public var errorDescription: String? {
        switch self {
        case .notInitialized: "The Telltale database hasn't been created yet."
        case .unsupportedSchemaVersion(let version): "The Telltale database uses schema version \(version), which this copy doesn't understand."
        case .sqlite(let code, let message, let context): "SQLite error \(code) (\(message)) while \(context)"
        case .invalidData(let message): message
        }
    }

    /// True for SQLITE_BUSY and SQLITE_LOCKED: another connection holds the database.
    public var isBusy: Bool {
        if case .sqlite(let code, _, _) = self { return code == SQLITE_BUSY || code == SQLITE_LOCKED }
        return false
    }
}

/// Telltale's SQLite database (spec section 4), through the system `SQLite3` module.
///
/// One `Store` per thread; it is not `Sendable`. The collector is the single writer; the app
/// opens `.readOnly` and writes only settings and user actions through a short-lived
/// `.readWrite` connection.
public final class Store {
    public enum Mode: Sendable { case readOnly, readWrite }

    public let mode: Mode
    let db: OpaquePointer
    private var inTransaction = false

    private init(db: OpaquePointer, mode: Mode) {
        self.db = db
        self.mode = mode
    }

    deinit { sqlite3_close_v2(db) }

    /// Opens the database. `.readWrite` creates the directory and file, turns on WAL and foreign
    /// keys, and migrates to `user_version` 1 inside `BEGIN IMMEDIATE`, so concurrent first
    /// opens are safe. `.readOnly` never migrates and throws `notInitialized` when
    /// `user_version` is 0.
    public static func open(_ url: URL, mode: Mode, busyTimeout: Duration = .seconds(5)) throws -> Store {
        let timeoutMilliseconds = Int32(clamping: max(0, busyTimeout.components.seconds) * 1_000
            + busyTimeout.components.attoseconds / 1_000_000_000_000_000)
        let flags: Int32
        switch mode {
        case .readOnly:
            guard FileManager.default.fileExists(atPath: url.path) else { throw StoreError.notInitialized }
            flags = SQLITE_OPEN_READONLY | SQLITE_OPEN_FULLMUTEX
        case .readWrite:
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            flags = SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX
        }
        var handle: OpaquePointer?
        let code = sqlite3_open_v2(url.path, &handle, flags, nil)
        guard code == SQLITE_OK, let handle else {
            let message = handle.map { String(cString: sqlite3_errmsg($0)) } ?? "out of memory"
            sqlite3_close_v2(handle)
            throw StoreError.sqlite(code: code, message: message, context: "opening \(url.lastPathComponent)")
        }
        let store = Store(db: handle, mode: mode)
        sqlite3_busy_timeout(handle, timeoutMilliseconds)

        switch mode {
        case .readOnly:
            let version = try store.userVersion()
            if version == 0 { throw StoreError.notInitialized }
            if version > Schema.currentVersion { throw StoreError.unsupportedSchemaVersion(version) }
        case .readWrite:
            try store.exec("PRAGMA foreign_keys = ON")
            // Switching a fresh file to WAL can report busy without consulting the busy handler
            // while another first open does the same, so retry within the timeout.
            let deadline = ContinuousClock.now.advanced(by: busyTimeout)
            try store.retryingWhileBusy(until: deadline) { try store.exec("PRAGMA journal_mode = WAL") }
            try store.migrateIfNeeded()
        }
        return store
    }

    // MARK: Transactions

    /// Runs `body` in one transaction: `BEGIN IMMEDIATE … COMMIT` for a writer, a plain `BEGIN`
    /// (one consistent snapshot) for a read-only connection. A throw rolls back. A nested call
    /// joins the outer transaction.
    public func transaction<T>(_ body: () throws -> T) throws -> T {
        if inTransaction { return try body() }
        try exec(mode == .readWrite ? "BEGIN IMMEDIATE" : "BEGIN")
        inTransaction = true
        defer { inTransaction = false }
        do {
            let result = try body()
            try exec("COMMIT")
            return result
        } catch {
            _ = try? exec("ROLLBACK")
            throw error
        }
    }

    // MARK: Settings

    /// The stored value, or the key's default when it is absent or no longer decodes.
    public func value<V>(_ key: SettingKey<V>) throws -> V {
        guard let stored = try storedJSON(key), let decoded = try? StoreJSON.decode(V.self, from: stored) else { return key.defaultValue }
        return decoded
    }

    /// False when a value is stored for `key` but no longer decodes, so `value` returns the default
    /// in its place. True when it decodes or nothing is stored.
    func storedSettingDecodes<V>(_ key: SettingKey<V>) throws -> Bool {
        guard let stored = try storedJSON(key) else { return true }
        return (try? StoreJSON.decode(V.self, from: stored)) != nil
    }

    private func storedJSON<V>(_ key: SettingKey<V>) throws -> String? {
        try query("SELECT value_json FROM settings WHERE key = ?", [.text(key.name)]) { $0.text(0) }.first
    }

    public func set<V>(_ key: SettingKey<V>, _ value: V) throws {
        try run(
            "INSERT INTO settings (key, value_json) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value_json = excluded.value_json",
            [.text(key.name), .text(try StoreJSON.encode(value))])
    }

    // MARK: Migration

    private func userVersion() throws -> Int {
        try query("PRAGMA user_version") { $0.int(0) }.first ?? 0
    }

    private func migrateIfNeeded() throws {
        // Fast path: an already-migrated database needs no write lock.
        let observed = try userVersion()
        if observed == Schema.currentVersion { return }
        if observed > Schema.currentVersion { throw StoreError.unsupportedSchemaVersion(observed) }
        try transaction {
            // Re-check under the write lock: another first open may have migrated meanwhile.
            let version = try userVersion()
            if version > Schema.currentVersion { throw StoreError.unsupportedSchemaVersion(version) }
            guard version == 0 else { return }
            for statement in Schema.version1 { try exec(statement) }
            try exec("PRAGMA user_version = \(Schema.currentVersion)")
        }
    }

    private func retryingWhileBusy(until deadline: ContinuousClock.Instant, _ body: () throws -> Void) throws {
        while true {
            do {
                try body()
                return
            } catch let error as StoreError where error.isBusy && ContinuousClock.now < deadline {
                Thread.sleep(forTimeInterval: 0.01)
            }
        }
    }

    // MARK: SQL helpers (module-internal; the Store+ extensions build on these)

    func error(_ context: String) -> StoreError {
        .sqlite(code: sqlite3_errcode(db), message: String(cString: sqlite3_errmsg(db)), context: context)
    }

    /// Runs one or more statements that return no data.
    func exec(_ sql: String) throws {
        guard sqlite3_exec(db, sql, nil, nil, nil) == SQLITE_OK else { throw error(Self.summary(of: sql)) }
    }

    /// Prepares `sql` for repeated use inside a loop or batch.
    func prepare(_ sql: String) throws -> Statement {
        var handle: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &handle, nil) == SQLITE_OK, let handle else {
            sqlite3_finalize(handle)
            throw error(Self.summary(of: sql))
        }
        return Statement(store: self, handle: handle, sql: sql)
    }

    /// Runs one statement and returns the number of rows it changed.
    @discardableResult
    func run(_ sql: String, _ parameters: [SQLValue] = []) throws -> Int {
        try prepare(sql).run(parameters)
    }

    func query<T>(_ sql: String, _ parameters: [SQLValue] = [], _ map: (Row) throws -> T) throws -> [T] {
        try prepare(sql).rows(parameters, map)
    }

    var lastInsertedRowID: Int64 { sqlite3_last_insert_rowid(db) }

    private static func summary(of sql: String) -> String {
        let flat = sql.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        return flat.count > 80 ? String(flat.prefix(80)) + "…" : flat
    }
}

// MARK: - Statements and rows

enum SQLValue {
    case null
    case int(Int64)
    case double(Double)
    case text(String)
    case blob(Data)

    static func integer(_ value: Int) -> SQLValue { .int(Int64(value)) }
    static func integer(_ value: Int?) -> SQLValue { value.map { .int(Int64($0)) } ?? .null }
    static func string(_ value: String?) -> SQLValue { value.map { .text($0) } ?? .null }
    static func bool(_ value: Bool) -> SQLValue { .int(value ? 1 : 0) }
    /// Dates are stored as REAL Unix seconds.
    static func date(_ value: Date) -> SQLValue { .double(value.timeIntervalSince1970) }
    static func date(_ value: Date?) -> SQLValue { value.map { .double($0.timeIntervalSince1970) } ?? .null }
}

/// A prepared statement, finalized when released. Used on the thread that owns its `Store`.
final class Statement {
    private let store: Store
    private let handle: OpaquePointer
    private let sql: String

    fileprivate init(store: Store, handle: OpaquePointer, sql: String) {
        self.store = store
        self.handle = handle
        self.sql = sql
    }

    deinit { sqlite3_finalize(handle) }

    /// Binds `parameters`, steps to completion, resets, and returns the rows changed.
    @discardableResult
    func run(_ parameters: [SQLValue] = []) throws -> Int {
        defer { sqlite3_reset(handle) }
        try bind(parameters)
        while true {
            switch sqlite3_step(handle) {
            case SQLITE_ROW: continue
            case SQLITE_DONE: return Int(sqlite3_changes(store.db))
            default: throw store.error(sql)
            }
        }
    }

    func rows<T>(_ parameters: [SQLValue] = [], _ map: (Row) throws -> T) throws -> [T] {
        defer { sqlite3_reset(handle) }
        try bind(parameters)
        var result: [T] = []
        while true {
            switch sqlite3_step(handle) {
            case SQLITE_ROW: result.append(try map(Row(handle: handle)))
            case SQLITE_DONE: return result
            default: throw store.error(sql)
            }
        }
    }

    private func bind(_ parameters: [SQLValue]) throws {
        sqlite3_reset(handle)
        sqlite3_clear_bindings(handle)
        let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
        for (offset, value) in parameters.enumerated() {
            let index = Int32(offset + 1)
            let code: Int32
            switch value {
            case .null: code = sqlite3_bind_null(handle, index)
            case .int(let number): code = sqlite3_bind_int64(handle, index, number)
            case .double(let number): code = sqlite3_bind_double(handle, index, number)
            case .text(let string): code = sqlite3_bind_text(handle, index, string, -1, transient)
            case .blob(let data):
                // An empty Data has a nil base address, which SQLite would bind as NULL.
                code = data.isEmpty
                    ? sqlite3_bind_zeroblob(handle, index, 0)
                    : data.withUnsafeBytes { sqlite3_bind_blob(handle, index, $0.baseAddress, Int32($0.count), transient) }
            }
            guard code == SQLITE_OK else { throw store.error("binding parameter \(index) of \(sql)") }
        }
    }
}

/// The current row of a statement, read by zero-based column index.
struct Row {
    fileprivate let handle: OpaquePointer

    func isNull(_ column: Int32) -> Bool { sqlite3_column_type(handle, column) == SQLITE_NULL }

    func int(_ column: Int32) -> Int { Int(sqlite3_column_int64(handle, column)) }
    func optionalInt(_ column: Int32) -> Int? { isNull(column) ? nil : int(column) }
    func bool(_ column: Int32) -> Bool { sqlite3_column_int64(handle, column) != 0 }
    func double(_ column: Int32) -> Double { sqlite3_column_double(handle, column) }
    func optionalDouble(_ column: Int32) -> Double? { isNull(column) ? nil : double(column) }
    func date(_ column: Int32) -> Date { Date(timeIntervalSince1970: double(column)) }
    func optionalDate(_ column: Int32) -> Date? { optionalDouble(column).map { Date(timeIntervalSince1970: $0) } }

    func text(_ column: Int32) -> String {
        sqlite3_column_text(handle, column).map { String(cString: $0) } ?? ""
    }

    func optionalText(_ column: Int32) -> String? { isNull(column) ? nil : text(column) }

    func blob(_ column: Int32) -> Data {
        guard let bytes = sqlite3_column_blob(handle, column) else { return Data() }
        return Data(bytes: bytes, count: Int(sqlite3_column_bytes(handle, column)))
    }
}

/// JSON for the `*_json` columns and settings: dates as Unix seconds, keys sorted.
enum StoreJSON {
    static func encode<V: Encodable>(_ value: V) throws -> String {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .secondsSince1970
        encoder.outputFormatting = [.sortedKeys]
        do {
            return String(decoding: try encoder.encode(value), as: UTF8.self)
        } catch {
            throw StoreError.invalidData("Couldn't encode \(V.self): \(error.localizedDescription)")
        }
    }

    static func decode<V: Decodable>(_ type: V.Type, from json: String) throws -> V {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .secondsSince1970
        return try decoder.decode(type, from: Data(json.utf8))
    }
}
