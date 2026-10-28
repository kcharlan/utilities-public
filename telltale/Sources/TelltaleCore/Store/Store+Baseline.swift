import Foundation

// Baseline storage (spec section 8): acceptances and their epochs, the throughput-qualifying
// response queries the baseline engine runs, and lasting-shift dismissals.

/// An acceptance's dated fields without its tables, cheap enough to read at every evaluation.
struct EpochMark: Sendable, Equatable {
    var id: Int64
    var since: LocalDay
    var createdAt: Date
    var undoneAt: Date?

    /// In effect at `instant`: accepted at or before it and not undone by then.
    func isLive(at instant: Date) -> Bool {
        createdAt <= instant && (undoneAt.map { $0 > instant } ?? true)
    }
}

extension Store {
    /// Responses with a throughput (spec section 6.1): enough output tokens and a positive duration.
    private static let hasThroughput = "output_tokens >= \(ResponseRecord.minimumThroughputTokens) AND end_at > start_at"

    /// SQLite's `PRAGMA data_version`: it changes when another connection commits.
    func dataVersion() throws -> Int {
        try query("PRAGMA data_version") { $0.int(0) }.first ?? 0
    }

    // MARK: Responses

    /// The end of the latest response with throughput ending before `before` and at or after
    /// `notBefore`. Walks the `(provider, model, end_at)` index backwards and stops at the first match.
    func latestThroughputEnd(provider: ProviderID, model: String, before: Date, notBefore: Date?) throws -> Date? {
        try query("""
            SELECT end_at FROM responses
            WHERE provider = ? AND model = ? AND end_at < ? AND end_at >= ? AND \(Self.hasThroughput)
            ORDER BY end_at DESC LIMIT 1
            """, [.text(provider.rawValue), .text(model), .date(before), .date(notBefore ?? .distantPast)]) { $0.date(0) }.first
    }

    /// Responses with throughput ending in `from..<before`, ordered by end time.
    func throughputResponses(provider: ProviderID, model: String, from: Date, before: Date) throws -> [ResponseRecord] {
        try query("""
            SELECT \(Self.responseColumns) FROM responses
            WHERE provider = ? AND model = ? AND end_at >= ? AND end_at < ? AND \(Self.hasThroughput)
            ORDER BY end_at, response_id
            """, [.text(provider.rawValue), .text(model), .date(from), .date(before)], Self.response)
    }

    /// Local days with at least one throughput response ending in `notBefore..<before`, newest
    /// first, at most `limit` of them. Each step is one indexed probe, so inactive days cost nothing.
    func activeDaysNewestFirst(
        provider: ProviderID, model: String, before: Date, notBefore: Date?, calendar: Calendar, limit: Int
    ) throws -> [LocalDay] {
        var days: [LocalDay] = []
        var bound = before
        while days.count < limit,
            let end = try latestThroughputEnd(provider: provider, model: model, before: bound, notBefore: notBefore) {
            let day = LocalDay(end, calendar: calendar)
            days.append(day)
            bound = day.start(in: calendar)
        }
        return days
    }

    // MARK: Epochs

    /// One model's acceptances, oldest first.
    func epochMarks(provider: ProviderID, model: String) throws -> [EpochMark] {
        try query("""
            SELECT id, since_day, created_at, undone_at FROM baseline_epochs
            WHERE provider = ? AND model = ? ORDER BY created_at, id
            """, [.text(provider.rawValue), .text(model)]) { row in
            guard let since = LocalDay(text: row.text(1)) else {
                throw StoreError.invalidData("Unreadable since day for baseline epoch \(row.int(0))")
            }
            return EpochMark(id: Int64(row.int(0)), since: since, createdAt: row.date(2), undoneAt: row.optionalDate(3))
        }
    }

    /// The newest acceptance not undone, with its tables.
    func latestLiveEpoch(provider: ProviderID, model: String) throws -> BaselineEpoch? {
        try epochs(where: "provider = ? AND model = ? AND undone_at IS NULL ORDER BY created_at DESC, id DESC LIMIT 1",
                   [.text(provider.rawValue), .text(model)]).first
    }

    func baselineEpoch(id: Int64) throws -> BaselineEpoch? {
        try epochs(where: "id = ?", [.int(id)]).first
    }

    func insertEpoch(provider: ProviderID, model: String, since: LocalDay, createdAt: Date, before: UsualTable) throws -> Int64 {
        try run("""
            INSERT INTO baseline_epochs (provider, model, since_day, created_at, before_json) VALUES (?, ?, ?, ?, ?)
            """, [.text(provider.rawValue), .text(model), .text(since.description), .date(createdAt), .text(try StoreJSON.encode(before))])
        return lastInsertedRowID
    }

    func setEpochAfter(id: Int64, _ after: UsualTable) throws {
        try run("UPDATE baseline_epochs SET after_json = ? WHERE id = ?", [.text(try StoreJSON.encode(after)), .int(id)])
    }

    /// Marks acceptances and their `baselineAccepted` events undone at `at`.
    func markAcceptancesUndone(_ ids: [Int64], at: Date) throws {
        let epochs = try prepare("UPDATE baseline_epochs SET undone_at = ? WHERE id = ? AND undone_at IS NULL")
        let events = try prepare("UPDATE events SET undone_at = ? WHERE kind = ? AND epoch_id = ? AND undone_at IS NULL")
        for id in ids {
            try epochs.run([.date(at), .int(id)])
            try events.run([.date(at), .text(EventKind.baselineAccepted), .int(id)])
        }
    }

    private func epochs(where clause: String, _ parameters: [SQLValue]) throws -> [BaselineEpoch] {
        try query("""
            SELECT id, provider, model, since_day, created_at, undone_at, before_json, after_json
            FROM baseline_epochs WHERE \(clause)
            """, parameters) { row in
            let id = Int64(row.int(0))
            guard let since = LocalDay(text: row.text(3)), let before = row.optionalText(6), let after = row.optionalText(7) else {
                throw StoreError.invalidData("Incomplete baseline epoch \(id)")
            }
            do {
                return BaselineEpoch(
                    id: id, provider: ProviderID(rawValue: row.text(1)), model: row.text(2), since: since,
                    createdAt: row.date(4), undoneAt: row.optionalDate(5),
                    before: try StoreJSON.decode(UsualTable.self, from: before),
                    after: try StoreJSON.decode(UsualTable.self, from: after))
            } catch {
                throw StoreError.invalidData("Unreadable tables for baseline epoch \(id)")
            }
        }
    }

    // MARK: Lasting-shift dismissals

    func insertShiftDismissal(provider: ProviderID, model: String, direction: Direction, firstDay: LocalDay, at: Date) throws {
        try run("""
            INSERT INTO shift_dismissals (provider, model, direction, first_day, dismissed_at) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (provider, model, direction, first_day) DO UPDATE SET dismissed_at = excluded.dismissed_at
            """, [.text(provider.rawValue), .text(model), .text(direction.rawValue), .text(firstDay.description), .date(at)])
    }

    /// When the latest dismissal of a `direction` run was made, if any.
    func latestShiftDismissal(provider: ProviderID, model: String, direction: Direction, atOrBefore instant: Date) throws -> Date? {
        try query("""
            SELECT MAX(dismissed_at) FROM shift_dismissals
            WHERE provider = ? AND model = ? AND direction = ? AND dismissed_at <= ?
            """, [.text(provider.rawValue), .text(model), .text(direction.rawValue), .date(instant)]) { $0.optionalDate(0) }.first ?? nil
    }
}
