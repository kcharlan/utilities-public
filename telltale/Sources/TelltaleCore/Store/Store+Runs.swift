import Foundation

public enum RunOutcome: String, Sendable, Equatable, Hashable, Codable, CaseIterable {
    case running, succeeded, failed, skipped
}

/// One collector run (spec section 9.3: the truth about the collector comes from these records).
public struct CollectorRunRecord: Sendable, Equatable, Hashable, Codable {
    public var id: Int64
    public var startedAt: Date
    public var finishedAt: Date?
    public var outcome: RunOutcome
    public var detail: String

    public init(id: Int64, startedAt: Date, finishedAt: Date? = nil, outcome: RunOutcome, detail: String) {
        self.id = id
        self.startedAt = startedAt
        self.finishedAt = finishedAt
        self.outcome = outcome
        self.detail = detail
    }
}

extension Store {
    /// Records the start of a run, outcome `running`, and returns its id.
    public func beginRun(at start: Date) throws -> Int64 {
        try transaction {
            try run("INSERT INTO collector_runs (started_at, outcome, detail) VALUES (?, ?, '')", [.date(start), .text(RunOutcome.running.rawValue)])
            return lastInsertedRowID
        }
    }

    public func finishRun(_ id: Int64, at finish: Date, outcome: RunOutcome, detail: String = "") throws {
        let changed = try run(
            "UPDATE collector_runs SET finished_at = ?, outcome = ?, detail = ? WHERE id = ?",
            [.date(finish), .text(outcome.rawValue), .text(detail), .int(id)])
        if changed == 0 { throw StoreError.invalidData("No collector run \(id) to finish") }
    }

    /// The latest runs, newest first. Collector health passes `includingSkipped: false`: skipped runs
    /// count for nothing there, so they mustn't use up the limit.
    public func recentRuns(limit: Int, includingSkipped: Bool = true) throws -> [CollectorRunRecord] {
        try query("""
            SELECT id, started_at, finished_at, outcome, detail FROM collector_runs
            WHERE ? OR outcome <> ?
            ORDER BY started_at DESC, id DESC LIMIT ?
            """, [.bool(includingSkipped), .text(RunOutcome.skipped.rawValue), .integer(max(0, limit))]) { row in
            CollectorRunRecord(
                id: Int64(row.int(0)), startedAt: row.date(1), finishedAt: row.optionalDate(2),
                outcome: RunOutcome(rawValue: row.text(3)) ?? .failed, detail: row.text(4))
        }
    }
}
