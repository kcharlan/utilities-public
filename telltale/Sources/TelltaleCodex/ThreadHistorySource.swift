import Foundation
import TelltaleCore

/// Failed turns from Codex's `thread_history_N.sqlite` (spec section 6.2).
public enum ThreadHistorySource {
    /// A row is written when a turn starts and updated when it ends, so each scan starts this far
    /// before where the last one finished.
    public static let rescanWindow: TimeInterval = 2 * 60 * 60

    public static let columns = ["thread_id", "turn_id", "status", "error_json", "started_at", "completed_at"]

    /// Where the next scan starts, given the time the last one finished.
    public static func rescanStart(after lastScan: Date) -> Date { lastScan.addingTimeInterval(-rescanWindow) }

    /// The failed turns that started at or after `since`, from the highest-numbered database.
    /// No database is no turns. `model` stays nil; the model is attributed later from the
    /// ingested responses.
    ///
    /// Throws `ReadOnlySQLite.Busy` when Codex holds the file, `ReadOnlySQLite.Closed` when a closed
    /// WAL database has no `-wal` to read, `ReadOnlySQLite.FormatProblem` when the table or a column
    /// is missing, and `ReadOnlySQLite.Failure` for any other SQLite error.
    public static func read(
        codexHome: URL, since: Date, busyTimeout: Duration = .milliseconds(250), step: SQLiteStep = .live
    ) throws -> [FailedTurnRecord] {
        guard let url = ReadOnlySQLite.highestNumbered("thread_history", in: codexHome) else { return [] }
        let database = try ReadOnlySQLite.open(url, busyTimeout: busyTimeout, step: step)
        try database.requireColumns(columns, in: "thread_turns")
        let rows = try database.query(
            """
            SELECT thread_id, turn_id, error_json, started_at, completed_at FROM thread_turns
            WHERE status = 'failed' AND COALESCE(started_at, completed_at) >= ?
            ORDER BY COALESCE(started_at, completed_at), thread_id, turn_id
            """, [.integer(Int64(since.timeIntervalSince1970.rounded(.down)))]
        ) { row -> FailedTurnRecord? in
            guard let thread = try row.text(0), let turn = try row.text(1) else { return nil }
            let started = row.integer(3) ?? row.integer(4)
            guard let started else { return nil }
            let error = errorFields(try row.text(2))
            return FailedTurnRecord(
                provider: .codex, threadID: thread, turnID: turn, startedAt: Date(timeIntervalSince1970: TimeInterval(started)),
                completedAt: row.integer(4).map { Date(timeIntervalSince1970: TimeInterval($0)) }, model: nil,
                errorCode: error.code, message: error.message)
        }
        return rows.compactMap { $0 }
    }

    static let unknownCode = "unknown"

    /// `error_json.codexErrorInfo` is the code, a string such as `serverOverloaded`; a serialized
    /// enum with a payload is `{"name": {...}}`, and then the name is the code. A row with no
    /// readable error is still a failed turn.
    private static func errorFields(_ json: String?) -> (code: String, message: String) {
        guard let json, let object = try? JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: Any] else {
            return (unknownCode, "")
        }
        let message = object["message"] as? String ?? ""
        switch object["codexErrorInfo"] {
        case let code as String where !code.isEmpty: return (code, message)
        case let payload as [String: Any]:
            return (payload.keys.sorted().first ?? unknownCode, message)
        default: return (unknownCode, message)
        }
    }
}
