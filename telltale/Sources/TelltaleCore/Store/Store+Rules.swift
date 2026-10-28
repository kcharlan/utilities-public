import Foundation

// Episodes, events, evaluation points and rule state (spec sections 7.2 and 7.3). Rows are
// written once as evaluated; later changes only end an episode, update an open episode's
// severity or worst value, or mark an event undone.

/// A speed rule's direction.
public enum Direction: String, Codable, Sendable, CaseIterable {
    case slower, faster

    public var opposite: Direction { self == .slower ? .faster : .slower }
}

/// One row of `episodes`. `provider` is a usage provider id or a status source id; `scope` is
/// a model id for model rules. Speed episodes carry a `direction`, and `worstValue` holds the
/// episode's most extreme speed index.
public struct EpisodeRow: Sendable, Equatable, Hashable {
    /// The speed rules' names in `episodes.rule`; Task 8's rule ids use the same strings.
    public static let slowerRule = "slower"
    public static let fasterRule = "faster"

    public static func speedRule(_ direction: Direction) -> String {
        direction == .slower ? slowerRule : fasterRule
    }

    /// Values of `endReason`.
    public enum EndReason {
        /// Back within the rule's clear band for its clear duration (spec section 7.2).
        public static let cleared = "cleared"
        /// No qualifying responses for the idle period; the episode ended silently.
        public static let idleEnded = "idleEnded"
        /// The rule was turned off while the episode was open; it ended silently at the first point
        /// evaluated with the rule off. Not a clear, so it never lifts a shift dismissal.
        public static let ruleDisabled = "ruleDisabled"
    }

    public var id: Int64?
    public var rule: String
    public var provider: String
    public var scope: String
    public var direction: Direction?
    public var onset: Date
    public var firedAt: Date
    public var endedAt: Date?
    public var endReason: String?
    public var severity: String
    public var worstValue: Double
    public var detail: Data?

    public init(
        id: Int64? = nil, rule: String, provider: String, scope: String, direction: Direction?, onset: Date,
        firedAt: Date, endedAt: Date? = nil, endReason: String? = nil, severity: String, worstValue: Double,
        detail: Data? = nil
    ) {
        self.id = id
        self.rule = rule
        self.provider = provider
        self.scope = scope
        self.direction = direction
        self.onset = onset
        self.firedAt = firedAt
        self.endedAt = endedAt
        self.endReason = endReason
        self.severity = severity
        self.worstValue = worstValue
        self.detail = detail
    }
}

/// `events.kind` values.
public enum EventKind {
    public static let statusPost = "statusPost"
    public static let baselineAccepted = "baselineAccepted"
    public static let baselineUndone = "baselineUndone"
    /// Rule transitions (Task 8). An idle end is silent and writes no event.
    public static let ruleFired = "ruleFired"
    public static let ruleEscalated = "ruleEscalated"
    public static let ruleCleared = "ruleCleared"
    /// The kinds Rebuild discards as "rule events" (spec section 7.3).
    public static let ruleKinds = [ruleFired, ruleEscalated, ruleCleared]
    /// A span the provider's connection log no longer covered (spec section 6.3); `endsAt` holds
    /// its end. Kept on Rebuild, since the log it came from is gone.
    public static let connectionHistoryIncomplete = "connectionHistoryIncomplete"
}

/// How an evaluation point judged a model's speed.
public enum EvalPointState: String, Sendable, Hashable, Codable {
    /// Enough samples, and the model is past cold start.
    case known
    /// Fewer than `SpeedIndex.minimumSamples` judged responses (spec section 7.1).
    case thin
    /// Fewer than `BaselineEngine.coldStartDays` active days: speed rules stay quiet (spec section 8).
    case cold
}

/// One row of `eval_points`: a model's speed at an evaluation point and the mix-matched usual
/// it was judged against, stored once so history never changes color (spec section 7.3).
public struct EvalPointRow: Sendable, Equatable, Hashable {
    public var provider: ProviderID
    public var model: String
    public var at: Date
    public var speedIndex: Double?
    public var mixUsual: Double?
    public var medianTPS: Double?
    public var samples: Int
    public var state: EvalPointState

    public init(
        provider: ProviderID, model: String, at: Date, speedIndex: Double?, mixUsual: Double?, medianTPS: Double?,
        samples: Int, state: EvalPointState
    ) {
        self.provider = provider
        self.model = model
        self.at = at
        self.speedIndex = speedIndex
        self.mixUsual = mixUsual
        self.medianTPS = medianTPS
        self.samples = samples
        self.state = state
    }
}

/// One row of `events`, the user-visible history (spec section 9.2).
public struct EventRow: Sendable, Equatable, Hashable {
    public var at: Date
    public var kind: String
    public var provider: String
    public var scope: String
    public var title: String
    public var body: String
    public var episodeID: Int64?
    public var epochID: Int64?
    public var link: URL?
    public var undoneAt: Date?
    /// The end of an event that spans time (a connection-history gap).
    public var endsAt: Date?

    public init(
        at: Date, kind: String, provider: String, scope: String, title: String, body: String,
        episodeID: Int64? = nil, epochID: Int64? = nil, link: URL? = nil, undoneAt: Date? = nil, endsAt: Date? = nil
    ) {
        self.at = at
        self.kind = kind
        self.provider = provider
        self.scope = scope
        self.title = title
        self.body = body
        self.episodeID = episodeID
        self.epochID = epochID
        self.link = link
        self.undoneAt = undoneAt
        self.endsAt = endsAt
    }
}

extension Store {
    static let episodeColumns = """
        id, rule, provider, scope, direction, onset_at, fired_at, ended_at, end_reason, severity, worst_value, detail_json
        """

    /// Inserts an episode (its `id` is ignored) and returns the new id.
    @discardableResult
    public func insertEpisode(_ episode: EpisodeRow) throws -> Int64 {
        try run("""
            INSERT INTO episodes (rule, provider, scope, direction, onset_at, fired_at, ended_at, end_reason, severity, worst_value, detail_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, Self.episodeValues(episode))
        return lastInsertedRowID
    }

    /// Replaces a stored episode's fields by `id`.
    public func updateEpisode(_ episode: EpisodeRow) throws {
        guard let id = episode.id else { throw StoreError.invalidData("Can't update an episode without an id") }
        let changed = try run("""
            UPDATE episodes SET rule = ?, provider = ?, scope = ?, direction = ?, onset_at = ?, fired_at = ?,
                ended_at = ?, end_reason = ?, severity = ?, worst_value = ?, detail_json = ?
            WHERE id = ?
            """, Self.episodeValues(episode) + [.int(id)])
        guard changed == 1 else { throw StoreError.invalidData("No episode \(id)") }
    }

    /// One model's speed episodes (both directions), ordered by onset.
    public func speedEpisodes(provider: ProviderID, model: String) throws -> [EpisodeRow] {
        try query("""
            SELECT \(Self.episodeColumns) FROM episodes
            WHERE rule IN (?, ?) AND provider = ? AND scope = ?
            ORDER BY onset_at, id
            """, [.text(EpisodeRow.slowerRule), .text(EpisodeRow.fasterRule), .text(provider.rawValue), .text(model)],
            Self.episode)
    }

    /// Inserts an event and returns its id.
    @discardableResult
    public func insertEvent(_ event: EventRow) throws -> Int64 {
        try run("""
            INSERT INTO events (at, kind, provider, scope, title, body, episode_id, epoch_id, link, undone_at, ends_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
            .date(event.at), .text(event.kind), .text(event.provider), .text(event.scope), .text(event.title),
            .text(event.body), event.episodeID.map(SQLValue.int) ?? .null, event.epochID.map(SQLValue.int) ?? .null,
            .string(event.link?.absoluteString), .date(event.undoneAt), .date(event.endsAt),
        ])
        return lastInsertedRowID
    }

    private static func episodeValues(_ episode: EpisodeRow) -> [SQLValue] {
        [
            .text(episode.rule), .text(episode.provider), .text(episode.scope), .string(episode.direction?.rawValue),
            .date(episode.onset), .date(episode.firedAt), .date(episode.endedAt), .string(episode.endReason),
            .text(episode.severity), .double(episode.worstValue),
            .string(episode.detail.map { String(decoding: $0, as: UTF8.self) }),
        ]
    }

    static func episode(_ row: Row) throws -> EpisodeRow {
        var direction: Direction?
        if let raw = row.optionalText(4) {
            guard let parsed = Direction(rawValue: raw) else {
                throw StoreError.invalidData("Unknown direction \(raw) for episode \(row.int(0))")
            }
            direction = parsed
        }
        return EpisodeRow(
            id: Int64(row.int(0)), rule: row.text(1), provider: row.text(2), scope: row.text(3), direction: direction,
            onset: row.date(5), firedAt: row.date(6), endedAt: row.optionalDate(7), endReason: row.optionalText(8),
            severity: row.text(9), worstValue: row.double(10), detail: row.optionalText(11).map { Data($0.utf8) })
    }
}

// MARK: - Rule engine storage (Task 8)

extension Store {
    /// `rule_state` rows that aren't a rule's own state.
    private static let engineRule = "engine"
    private static let notificationsRule = "notifications"

    // MARK: Episodes

    /// Episodes not yet ended, ordered by fire time.
    public func openEpisodes() throws -> [EpisodeRow] {
        try query("SELECT \(Self.episodeColumns) FROM episodes WHERE ended_at IS NULL ORDER BY fired_at, id", [], Self.episode)
    }

    /// Every episode of one rule (a `RuleID` raw value), ordered by fire time.
    public func episodes(rule: String) throws -> [EpisodeRow] {
        try query("SELECT \(Self.episodeColumns) FROM episodes WHERE rule = ? ORDER BY fired_at, id", [.text(rule)], Self.episode)
    }

    // MARK: Evaluation points

    /// Inserts points; a point already stored for the same provider, model and time is an error,
    /// since history is written once.
    public func insertEvalPoints(_ points: [EvalPointRow]) throws {
        guard !points.isEmpty else { return }
        try transaction {
            let statement = try prepare("""
                INSERT INTO eval_points (provider, model, at, speed_index, mix_usual_tps, median_tps, samples, state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """)
            for point in points {
                try statement.run([
                    .text(point.provider.rawValue), .text(point.model), .date(point.at),
                    point.speedIndex.map(SQLValue.double) ?? .null, point.mixUsual.map(SQLValue.double) ?? .null,
                    point.medianTPS.map(SQLValue.double) ?? .null, .integer(point.samples), .text(point.state.rawValue),
                ])
            }
        }
    }

    /// One model's points in `range` (both ends inclusive), oldest first.
    public func evalPoints(provider: ProviderID, model: String, in range: ClosedRange<Date>) throws -> [EvalPointRow] {
        try query("""
            SELECT at, speed_index, mix_usual_tps, median_tps, samples, state FROM eval_points
            WHERE provider = ? AND model = ? AND at BETWEEN ? AND ? ORDER BY at
            """, [.text(provider.rawValue), .text(model), .date(range.lowerBound), .date(range.upperBound)]) { row in
            guard let state = EvalPointState(rawValue: row.text(5)) else {
                throw StoreError.invalidData("Unknown evaluation point state \(row.text(5))")
            }
            return EvalPointRow(
                provider: provider, model: model, at: row.date(0), speedIndex: row.optionalDouble(1),
                mixUsual: row.optionalDouble(2), medianTPS: row.optionalDouble(3), samples: row.int(4), state: state)
        }
    }

    // MARK: Rule state

    /// The latest evaluation point the rule engine finished, or nil before the first.
    public func lastEvaluatedPoint() throws -> Date? {
        guard let json = try ruleState(rule: Self.engineRule, provider: "*", scope: "lastPoint") else { return nil }
        do {
            return try StoreJSON.decode(Date.self, from: json)
        } catch {
            throw StoreError.invalidData("Unreadable last evaluation point")
        }
    }

    func setLastEvaluatedPoint(_ point: Date) throws {
        try setRuleState(rule: Self.engineRule, provider: "*", scope: "lastPoint", json: try StoreJSON.encode(point))
    }

    /// The failed-turn notice state `NotificationPolicy` carries between runs.
    public func failureNotices() throws -> FailureNotices {
        guard let json = try ruleState(rule: Self.notificationsRule, provider: "*", scope: "failedTurns") else { return FailureNotices() }
        do {
            return try StoreJSON.decode(FailureNotices.self, from: json)
        } catch {
            throw StoreError.invalidData("Unreadable failed-turn notice state")
        }
    }

    public func setFailureNotices(_ notices: FailureNotices) throws {
        try setRuleState(rule: Self.notificationsRule, provider: "*", scope: "failedTurns", json: try StoreJSON.encode(notices))
    }

    /// One rule's stored states.
    func ruleStates(rule: String) throws -> [(provider: String, scope: String, json: String)] {
        try query("SELECT provider, scope, json FROM rule_state WHERE rule = ? ORDER BY provider, scope", [.text(rule)]) {
            (provider: $0.text(0), scope: $0.text(1), json: $0.text(2))
        }
    }

    func ruleState(rule: String, provider: String, scope: String) throws -> String? {
        try query("SELECT json FROM rule_state WHERE rule = ? AND provider = ? AND scope = ?", [.text(rule), .text(provider), .text(scope)]) {
            $0.text(0)
        }.first
    }

    func setRuleState(rule: String, provider: String, scope: String, json: String) throws {
        try run("""
            INSERT INTO rule_state (rule, provider, scope, json) VALUES (?, ?, ?, ?)
            ON CONFLICT (rule, provider, scope) DO UPDATE SET json = excluded.json
            """, [.text(rule), .text(provider), .text(scope), .text(json)])
    }

    func deleteRuleState(rule: String, provider: String, scope: String) throws {
        try run("DELETE FROM rule_state WHERE rule = ? AND provider = ? AND scope = ?", [.text(rule), .text(provider), .text(scope)])
    }

    // MARK: Rule inputs

    /// Failed turns the rule engine hasn't counted yet whose time (completion, else start) is at
    /// or before `through`, oldest first. A turn stored without a model takes the model of a
    /// response in the same turn (spec section 6.2), or stays nil.
    public func unevaluatedFailedTurns(through: Date) throws -> [FailedTurnRecord] {
        try query("""
            SELECT f.provider, f.thread_id, f.turn_id, f.started_at, f.completed_at,
                COALESCE(f.model, (SELECT r.model FROM responses r WHERE r.provider = f.provider AND r.turn_id = f.turn_id
                                   ORDER BY r.end_at DESC LIMIT 1)),
                f.error_code, f.message
            FROM failed_turns f
            WHERE f.evaluated_at IS NULL AND COALESCE(f.completed_at, f.started_at) <= ?
            ORDER BY COALESCE(f.completed_at, f.started_at), f.provider, f.turn_id
            """, [.date(through)]) { row in
            FailedTurnRecord(
                provider: ProviderID(rawValue: row.text(0)), threadID: row.text(1), turnID: row.text(2),
                startedAt: row.date(3), completedAt: row.optionalDate(4), model: row.optionalText(5),
                errorCode: row.text(6), message: row.text(7))
        }
    }

    /// Marks the uncounted failed turns whose time (completion, else start) is before `start`, the
    /// lookback start, as evaluated at `start` without counting them, and returns how many. No
    /// evaluation point reaches before the lookback (spec sections 7.3 and 8), so such a turn, kept
    /// through a Rebuild or ingested after more than the lookback with the collector off, would
    /// otherwise be counted at the first point as a failure there.
    func settleFailedTurns(before start: Date) throws -> Int {
        try run(
            "UPDATE failed_turns SET evaluated_at = ? WHERE evaluated_at IS NULL AND COALESCE(completed_at, started_at) < ?",
            [.date(start), .date(start)])
    }

    /// Marks failed turns counted at the evaluation point `at`.
    public func markEvaluated(_ turns: [FailedTurnRecord], at: Date) throws {
        guard !turns.isEmpty else { return }
        let statement = try prepare("UPDATE failed_turns SET evaluated_at = ? WHERE provider = ? AND turn_id = ?")
        for turn in turns {
            try statement.run([.date(at), .text(turn.provider.rawValue), .text(turn.turnID)])
        }
    }

    /// Records a span the provider's connection log no longer covered as a
    /// `connectionHistoryIncomplete` event: `at` is the gap's start and `endsAt` its end.
    @discardableResult
    public func recordConnectionGap(provider: ProviderID, gap: DateInterval, calendar: Calendar) throws -> Int64 {
        try insertEvent(EventRow(
            at: gap.start, kind: EventKind.connectionHistoryIncomplete, provider: provider.rawValue, scope: "*",
            title: "Disconnects", body: Copy.connectionGap(from: gap.start, to: gap.end, calendar: calendar), endsAt: gap.end))
    }

    /// One provider's recorded connection-history gaps that overlap `interval`, oldest first.
    public func connectionGaps(provider: ProviderID, overlapping interval: DateInterval) throws -> [DateInterval] {
        try query("""
            SELECT at, ends_at FROM events
            WHERE kind = ? AND provider = ? AND ends_at IS NOT NULL AND at < ? AND ends_at > ? ORDER BY at, id
            """, [.text(EventKind.connectionHistoryIncomplete), .text(provider.rawValue), .date(interval.end), .date(interval.start)]) { row in
            DateInterval(start: row.date(0), end: max(row.date(0), row.date(1)))
        }
    }

    /// One provider's connection events in `range` (both ends inclusive), oldest first.
    public func connectionEvents(provider: ProviderID, in range: ClosedRange<Date>) throws -> [ConnectionEventRecord] {
        try query("""
            SELECT source_id, at, kind, detail, retries, max_retries FROM connection_events
            WHERE provider = ? AND at BETWEEN ? AND ? ORDER BY at, source_id
            """, [.text(provider.rawValue), .date(range.lowerBound), .date(range.upperBound)]) { row in
            guard let kind = ConnectionKind(rawValue: row.text(2)) else {
                throw StoreError.invalidData("Unknown connection event kind \(row.text(2))")
            }
            return ConnectionEventRecord(
                provider: provider, sourceID: row.text(0), at: row.date(1), kind: kind, detail: row.text(3),
                retries: row.optionalInt(4), maxRetries: row.optionalInt(5))
        }
    }

    /// Every model with stored responses for `provider`, sorted. Each step is one seek on the
    /// `(provider, model, end_at)` index.
    func models(provider: ProviderID) throws -> [String] {
        try query("""
            WITH RECURSIVE m(model) AS (
                SELECT (SELECT MIN(model) FROM responses WHERE provider = ?1)
                UNION ALL
                SELECT (SELECT MIN(model) FROM responses WHERE provider = ?1 AND model > m.model) FROM m WHERE m.model IS NOT NULL
            )
            SELECT model FROM m WHERE model IS NOT NULL
            """, [.text(provider.rawValue)]) { $0.text(0) }
    }

    /// The model's last `limit` responses ending before `before`, oldest first.
    func responses(provider: ProviderID, model: String, before: Date, limit: Int) throws -> [ResponseRecord] {
        try query("""
            SELECT \(Self.responseColumns) FROM responses
            WHERE provider = ? AND model = ? AND end_at < ? ORDER BY end_at DESC, response_id DESC LIMIT ?
            """, [.text(provider.rawValue), .text(model), .date(before), .integer(limit)], Self.response).reversed()
    }
}
