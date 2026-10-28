import Foundation
import SQLite3

/// A writable connection to a synthetic Codex SQLite file (`thread_history_N.sqlite` or
/// `logs_N.sqlite`), with Codex's table and column names (spec sections 6.2 and 6.3). Rows are
/// synthetic. The connection stays open, so a WAL-mode file keeps its `-wal` and `-shm` side files
/// like Codex's live ones.
public final class CodexDatabase {
    public enum Journal: String, Sendable {
        case wal = "WAL"
        case delete = "DELETE"
    }

    public enum Value: Sendable {
        case integer(Int64)
        case text(String)
        case null
    }

    public struct Failure: Error, CustomStringConvertible {
        public let description: String
    }

    public static let retryTarget = "codex_core::responses_retry"

    public let url: URL
    private let db: OpaquePointer
    private let columns: Set<String>
    private var nextOrdinal: Int64 = 0

    private init(url: URL, db: OpaquePointer, columns: Set<String>) {
        self.url = url
        self.db = db
        self.columns = columns
    }

    deinit { sqlite3_close_v2(db) }

    // MARK: Creation

    private static let threadTurnsColumns: [(String, String)] = [
        ("thread_id", "TEXT NOT NULL"), ("turn_id", "TEXT NOT NULL"), ("rollout_ordinal", "INTEGER NOT NULL"),
        ("status", "TEXT NOT NULL"), ("error_json", "TEXT"), ("started_at", "INTEGER"), ("completed_at", "INTEGER"),
        ("duration_ms", "INTEGER"), ("first_user_item_id", "TEXT"), ("final_agent_item_id", "TEXT"),
        ("rollout_byte_offset", "INTEGER"), ("rollout_end_ordinal", "INTEGER"), ("rollout_end_byte_offset", "INTEGER"),
        ("root_turn_id", "TEXT")
    ]

    private static let logsColumns: [(String, String)] = [
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"), ("ts", "INTEGER NOT NULL"), ("ts_nanos", "INTEGER NOT NULL"),
        ("level", "TEXT NOT NULL"), ("target", "TEXT NOT NULL"), ("feedback_log_body", "TEXT"), ("module_path", "TEXT"),
        ("file", "TEXT"), ("line", "INTEGER"), ("thread_id", "TEXT"), ("process_uuid", "TEXT"),
        ("estimated_bytes", "INTEGER NOT NULL DEFAULT 0")
    ]

    /// `thread_history_<number>.sqlite` with table `thread_turns`, minus any `omitting` columns.
    public static func threadHistory(
        codexHome: URL, number: Int = 1, omitting: Set<String> = [], journal: Journal = .wal
    ) throws -> CodexDatabase {
        try create(codexHome.appending(path: "thread_history_\(number).sqlite"), table: "thread_turns", columns: threadTurnsColumns, omitting: omitting, journal: journal)
    }

    /// `logs_<number>.sqlite` with table `logs`, minus any `omitting` columns.
    public static func logs(
        codexHome: URL, number: Int = 2, omitting: Set<String> = [], journal: Journal = .wal
    ) throws -> CodexDatabase {
        try create(codexHome.appending(path: "logs_\(number).sqlite"), table: "logs", columns: logsColumns, omitting: omitting, journal: journal)
    }

    private static func create(
        _ url: URL, table: String, columns: [(String, String)], omitting: Set<String>, journal: Journal
    ) throws -> CodexDatabase {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        var handle: OpaquePointer?
        guard sqlite3_open_v2(url.path, &handle, SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX, nil) == SQLITE_OK,
            let handle
        else { throw Failure(description: "open failed: \(url.lastPathComponent)") }
        sqlite3_busy_timeout(handle, 5_000)
        let kept = columns.filter { !omitting.contains($0.0) }
        let database = CodexDatabase(url: url, db: handle, columns: Set(kept.map(\.0)))
        try database.execute("PRAGMA journal_mode = \(journal.rawValue)")
        try database.execute("CREATE TABLE \(table) (\(kept.map { "\($0.0) \($0.1)" }.joined(separator: ", ")))")
        return database
    }

    // MARK: Rows

    /// A thread turn. `thread`/`turn` numbers give `thread_synthetic_NN` and `turn_synthetic_NN`.
    public func addTurn(
        thread: Int = 1, turn: Int, status: String, errorJSON: String? = nil, startedAt: Date?, completedAt: Date? = nil
    ) throws {
        nextOrdinal += 1
        try insert("thread_turns", [
            "thread_id": .text(String(format: "thread_synthetic_%02ld", thread)),
            "turn_id": .text(String(format: "turn_synthetic_%02ld", turn)),
            "rollout_ordinal": .integer(nextOrdinal), "status": .text(status),
            "error_json": errorJSON.map(Value.text) ?? .null,
            "started_at": startedAt.map { .integer(Int64($0.timeIntervalSince1970)) } ?? .null,
            "completed_at": completedAt.map { .integer(Int64($0.timeIntervalSince1970)) } ?? .null
        ])
    }

    /// Updates a turn's status and completion, as Codex does when a turn ends.
    public func finishTurn(thread: Int = 1, turn: Int, status: String, errorJSON: String?, completedAt: Date) throws {
        try execute("""
            UPDATE thread_turns SET status = \(Self.quote(status)), error_json = \(errorJSON.map(Self.quote) ?? "NULL"),
                completed_at = \(Int64(completedAt.timeIntervalSince1970))
            WHERE thread_id = \(Self.quote(String(format: "thread_synthetic_%02ld", thread)))
                AND turn_id = \(Self.quote(String(format: "turn_synthetic_%02ld", turn)))
            """)
    }

    /// A log row; returns its id. The default is a WARN retry row.
    @discardableResult
    public func addLog(
        at date: Date, level: String = "WARN", target: String = CodexDatabase.retryTarget, body: String?
    ) throws -> Int64 {
        let seconds = date.timeIntervalSince1970.rounded(.down)
        try insert("logs", [
            "ts": .integer(Int64(seconds)), "ts_nanos": .integer(Int64(((date.timeIntervalSince1970 - seconds) * 1e9).rounded())),
            "level": .text(level), "target": .text(target), "feedback_log_body": body.map(Value.text) ?? .null
        ])
        return sqlite3_last_insert_rowid(db)
    }

    /// Deletes log rows with ids below `id`, as Codex's retention does.
    public func pruneLogs(before id: Int64) throws {
        try execute("DELETE FROM logs WHERE id < \(id)")
    }

    // MARK: Synthetic text

    /// `{"message": ..., "codexErrorInfo": ...}`, the shape of `error_json` (spec section 6.2).
    public static func errorJSON(code: String, message: String) -> String {
        let object: [String: Any] = ["message": message, "codexErrorInfo": code]
        return String(decoding: try! JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]), as: UTF8.self)
    }

    /// A retry log body: a synthetic span prefix, then `retries=`, `max_retries=` and `sampling_error=`.
    public static func retryBody(retries: Int = 1, maxRetries: Int = 5, samplingError: String) -> String {
        "session_loop{thread_id=thread_synthetic_01}:turn{turn.id=turn_synthetic_01 model=gpt-6.1-sol}: "
            + "retrying turn_id=turn_synthetic_01 retries=\(retries) max_retries=\(maxRetries) sampling_error=\(samplingError)"
    }

    public static let disconnectError =
        "stream disconnected before completion: WebSocket protocol error: Connection reset without closing handshake"
    public static let websocketLimitError =
        "Responses websocket connection limit reached (60 minutes). Create a new websocket connection to continue."

    // MARK: Transactions and SQL

    public func execute(_ sql: String) throws {
        var message: UnsafeMutablePointer<CChar>?
        guard sqlite3_exec(db, sql, nil, nil, &message) == SQLITE_OK else {
            let text = message.map { String(cString: $0) } ?? "unknown"
            sqlite3_free(message)
            throw Failure(description: "\(text): \(sql)")
        }
    }

    /// Holds the write lock (and, in rollback-journal mode, blocks readers once data is written)
    /// until `commit()`.
    public func beginImmediate() throws { try execute("BEGIN IMMEDIATE") }
    public func beginExclusive() throws { try execute("BEGIN EXCLUSIVE") }
    public func commit() throws { try execute("COMMIT") }

    private func insert(_ table: String, _ values: [String: Value]) throws {
        let present = values.filter { columns.contains($0.key) }.sorted { $0.key < $1.key }
        let rendered = present.map { entry -> String in
            switch entry.value {
            case .integer(let number): String(number)
            case .text(let text): Self.quote(text)
            case .null: "NULL"
            }
        }
        try execute("INSERT INTO \(table) (\(present.map(\.key).joined(separator: ", "))) VALUES (\(rendered.joined(separator: ", ")))")
    }

    private static func quote(_ text: String) -> String { "'" + text.replacingOccurrences(of: "'", with: "''") + "'" }
}
