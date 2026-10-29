import Foundation
import TelltaleCore

/// Disconnects and retries from Codex's `logs_N.sqlite` (spec section 6.3).
public enum RetryLogSource {
    public static let target = "codex_core::responses_retry"
    public static let columns = ["id", "ts", "ts_nanos", "level", "target", "feedback_log_body"]

    /// The routine 60-minute websocket reconnect (spec section 6.3, plan call).
    static let websocketLimitText = "websocket connection limit reached"

    /// Longest `detail` kept, in characters.
    public static let maximumDetail = 300

    /// The currently selected database, if one exists.
    public static func database(codexHome: URL) -> URL? {
        ReadOnlySQLite.highestNumbered("logs", in: codexHome)
    }

    /// WARN retry rows after `afterID`, from the highest-numbered database. `maxID` is the highest
    /// id in the table, to pass back as `afterID`; `oldestRetained` is the time of its oldest row
    /// of any kind.
    ///
    /// Event source ids are `<database name>:<row id>`, so a new `logs_N` file never reuses an
    /// earlier file's ids. If `afterID` is past every id in the table (the log was replaced by a
    /// fresh file) the read restarts from the beginning.
    ///
    /// Throws as `ThreadHistorySource.read` does.
    public static func read(
        codexHome: URL, afterID: Int64, busyTimeout: Duration = .milliseconds(250), step: SQLiteStep = .live
    ) throws -> (events: [ConnectionEventRecord], maxID: Int64, oldestRetained: Date?) {
        guard let url = database(codexHome: codexHome) else { return ([], afterID, nil) }
        let name = url.deletingPathExtension().lastPathComponent
        let database = try ReadOnlySQLite.open(url, busyTimeout: busyTimeout, step: step)
        try database.requireColumns(columns, in: "logs")
        // One snapshot, so the maximum id and the rows read agree.
        return try database.readTransaction {
            let newest = try database.query("SELECT MAX(id) FROM logs") { $0.integer(0) }.first ?? nil
            guard let newest else { return ([], afterID, nil) }  // an empty table
            let start = afterID > newest ? 0 : afterID
            let events = try database.query(
                """
                SELECT id, ts, ts_nanos, feedback_log_body FROM logs
                WHERE id > ? AND target = ? AND level = 'WARN' ORDER BY id
                """, [.integer(start), .text(target)]
            ) { row -> ConnectionEventRecord? in
                guard let id = row.integer(0), let at = time(row, 1) else { return nil }
                return event(id: id, source: name, at: at, body: try row.text(3) ?? "")
            }.compactMap { $0 }
            let oldest = try database.query("SELECT ts, ts_nanos FROM logs ORDER BY id LIMIT 1") { time($0, 0) }.first ?? nil
            return (events, newest, oldest)
        }
    }

    /// `ts` whole seconds plus `ts_nanos`, as columns `first` and `first + 1`.
    private static func time(_ row: ReadOnlySQLite.Row, _ first: Int32) -> Date? {
        guard let seconds = row.integer(first) else { return nil }
        return Date(timeIntervalSince1970: TimeInterval(seconds) + TimeInterval(row.integer(first + 1) ?? 0) / 1e9)
    }

    /// One `responses_retry` row as a connection event.
    public static func event(id: Int64, source: String, at: Date, body: String) -> ConnectionEventRecord {
        let (head, error) = split(body)
        return ConnectionEventRecord(
            provider: .codex, sourceID: "\(source):\(id)", at: at, kind: kind(of: error),
            detail: String(error.prefix(maximumDetail)),
            retries: token("retries=", in: head).flatMap { Int($0) },
            maxRetries: token("max_retries=", in: head).flatMap { Int($0) })
    }

    /// The websocket limit is routine; a drop or reset is a disconnect; anything else is a retry.
    /// The websocket limit is tested first: its text also says "stream disconnected".
    public static func kind(of error: String) -> ConnectionKind {
        let lowered = error.lowercased()
        if lowered.contains(websocketLimitText) { return .reconnect }
        if lowered.contains("stream disconnected") || lowered.contains("connection reset") { return .disconnect }
        return .retry
    }

    private static let errorKey = "sampling_error="

    /// The body before its first `sampling_error=` field, and the error text after it (to the end).
    private static func split(_ body: String) -> (head: Substring, error: String) {
        var from = body.startIndex
        while let range = body.range(of: errorKey, range: from..<body.endIndex) {
            if startsField(range.lowerBound, in: body[...]) {
                return (body[..<range.lowerBound], body[range.upperBound...].trimmingCharacters(in: .whitespacesAndNewlines))
            }
            from = range.upperBound
        }
        return (body[...], "")
    }

    /// The token after the last `key` in `head` that begins a field (`max_retries=` is not `retries=`).
    private static func token(_ key: String, in head: Substring) -> String? {
        var end = head.endIndex
        while let range = head.range(of: key, options: .backwards, range: head.startIndex..<end) {
            if startsField(range.lowerBound, in: head) {
                let value = head[range.upperBound...].prefix { !$0.isWhitespace }
                return value.isEmpty ? nil : String(value)
            }
            end = range.lowerBound
        }
        return nil
    }

    private static func startsField(_ index: String.Index, in text: Substring) -> Bool {
        index == text.startIndex || text[text.index(before: index)].isWhitespace
    }
}
