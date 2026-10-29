import Foundation

/// A usage or status source's setup state as last recorded by the collector.
public struct SourceStateRow: Sendable, Equatable, Hashable, Codable {
    public var source: String
    public var state: SetupState
    public var version: String?
    public var unavailableSince: Date?
    public var updatedAt: Date

    public init(source: String, state: SetupState, version: String? = nil, unavailableSince: Date? = nil, updatedAt: Date) {
        self.source = source
        self.state = state
        self.version = version
        self.unavailableSince = unavailableSince
        self.updatedAt = updatedAt
    }
}

extension Store {
    @discardableResult
    public func upsert(compactions: [CompactionRecord]) throws -> Int {
        try transaction {
            let statement = try prepare("""
                INSERT INTO compactions (provider, line_id, session_id, agent_id, at, trigger, tokens_before, tokens_after, duration, precomputed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (provider, line_id) DO NOTHING
                """)
            var changed = 0
            for item in compactions {
                changed += try statement.run([.text(item.provider.rawValue), .text(item.lineID), .text(item.sessionID),
                    .string(item.agentID), .date(item.at), .text(item.trigger.rawValue), .integer(item.tokensBefore),
                    .integer(item.tokensAfter), item.duration.map { .double($0) } ?? .null, .bool(item.precomputed)])
            }
            return changed
        }
    }

    public func compactions(provider: ProviderID, in range: ClosedRange<Date>) throws -> [CompactionRecord] {
        guard schemaVersion >= 2 else { return [] }
        return try query("""
            SELECT line_id, session_id, agent_id, at, trigger, tokens_before, tokens_after, duration, precomputed
            FROM compactions WHERE provider = ? AND at BETWEEN ? AND ? ORDER BY at, line_id
            """, [.text(provider.rawValue), .date(range.lowerBound), .date(range.upperBound)]) { row in
                guard let trigger = CompactionTrigger(rawValue: row.text(4)) else { throw StoreError.invalidData("Invalid compaction trigger") }
                return CompactionRecord(provider: provider, lineID: row.text(0), sessionID: row.text(1), agentID: row.optionalText(2),
                    at: row.date(3), trigger: trigger, tokensBefore: row.int(5), tokensAfter: row.optionalInt(6),
                    duration: row.optionalDouble(7), precomputed: row.bool(8))
            }
    }
    static let responseColumns = """
        provider, response_id, model, effort, service_tier, session_id, is_subagent, turn_id, \
        start_at, end_at, input_tokens, cached_input_tokens, output_tokens, reasoning_tokens
        """

    /// Inserts responses, applying spec section 6.1's duplicate rule: when a `response_id` is
    /// already stored, the copy with the longer duration wins, whichever is ingested first
    /// (forked subagent files copy a parent's records with near-zero durations). Returns the
    /// number of rows inserted or replaced.
    @discardableResult
    public func upsert(responses: [ResponseRecord]) throws -> Int {
        try transaction {
            let statement = try prepare("""
                INSERT INTO responses (\(Self.responseColumns))
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (provider, response_id) DO UPDATE SET
                    model = excluded.model, effort = excluded.effort, service_tier = excluded.service_tier,
                    session_id = excluded.session_id, is_subagent = excluded.is_subagent, turn_id = excluded.turn_id,
                    start_at = excluded.start_at, end_at = excluded.end_at, input_tokens = excluded.input_tokens,
                    cached_input_tokens = excluded.cached_input_tokens, output_tokens = excluded.output_tokens,
                    reasoning_tokens = excluded.reasoning_tokens
                WHERE (excluded.end_at - excluded.start_at) > (responses.end_at - responses.start_at)
                """)
            var changed = 0
            for response in responses {
                changed += try statement.run([
                    .text(response.provider.rawValue), .text(response.responseID), .text(response.model),
                    .string(response.effort), .string(response.serviceTier), .text(response.sessionID),
                    .bool(response.isSubagent), .string(response.turnID), .date(response.start), .date(response.end),
                    .integer(response.inputTokens), .integer(response.cachedInputTokens), .integer(response.outputTokens),
                    .integer(response.reasoningTokens),
                ])
            }
            return changed
        }
    }

    /// Responses of one model ending inside `range` (both ends inclusive), ordered by end time.
    public func responses(provider: ProviderID, model: String, endingIn range: ClosedRange<Date>) throws -> [ResponseRecord] {
        try query("""
            SELECT \(Self.responseColumns) FROM responses
            WHERE provider = ? AND model = ? AND end_at BETWEEN ? AND ?
            ORDER BY end_at, response_id
            """, [.text(provider.rawValue), .text(model), .date(range.lowerBound), .date(range.upperBound)], Self.response)
    }

    /// Maps a row selected with `responseColumns`.
    static func response(_ row: Row) -> ResponseRecord {
        ResponseRecord(
            provider: ProviderID(rawValue: row.text(0)), model: row.text(2), effort: row.optionalText(3),
            serviceTier: row.optionalText(4), sessionID: row.text(5), isSubagent: row.bool(6), turnID: row.optionalText(7),
            responseID: row.text(1), start: row.date(8), end: row.date(9), inputTokens: row.int(10),
            cachedInputTokens: row.int(11), outputTokens: row.int(12), reasoningTokens: row.optionalInt(13))
    }

    /// Inserts failed turns; a later update to a stored turn replaces it. `evaluated_at`
    /// (set by the rule engine, Task 8) is never touched. Returns the rows inserted or changed.
    @discardableResult
    public func upsert(failedTurns: [FailedTurnRecord]) throws -> Int {
        try transaction {
            let statement = try prepare("""
                INSERT INTO failed_turns (provider, turn_id, thread_id, started_at, completed_at, model, error_code, message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (provider, turn_id) DO UPDATE SET
                    thread_id = excluded.thread_id, started_at = excluded.started_at,
                    completed_at = excluded.completed_at, model = excluded.model,
                    error_code = excluded.error_code, message = excluded.message
                WHERE failed_turns.thread_id IS NOT excluded.thread_id OR failed_turns.started_at IS NOT excluded.started_at
                    OR failed_turns.completed_at IS NOT excluded.completed_at OR failed_turns.model IS NOT excluded.model
                    OR failed_turns.error_code IS NOT excluded.error_code OR failed_turns.message IS NOT excluded.message
                """)
            var changed = 0
            for turn in failedTurns {
                changed += try statement.run([
                    .text(turn.provider.rawValue), .text(turn.turnID), .text(turn.threadID), .date(turn.startedAt),
                    .date(turn.completedAt), .string(turn.model), .text(turn.errorCode), .text(turn.message),
                ])
            }
            return changed
        }
    }

    /// Inserts connection events keyed by provider and source id; a re-ingested event
    /// replaces the stored one. Returns the rows inserted or changed.
    @discardableResult
    public func upsert(connectionEvents: [ConnectionEventRecord]) throws -> Int {
        try transaction {
            let statement = try prepare("""
                INSERT INTO connection_events (provider, source_id, at, kind, detail, retries, max_retries)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (provider, source_id) DO UPDATE SET
                    at = excluded.at, kind = excluded.kind, detail = excluded.detail,
                    retries = excluded.retries, max_retries = excluded.max_retries
                WHERE connection_events.at IS NOT excluded.at OR connection_events.kind IS NOT excluded.kind
                    OR connection_events.detail IS NOT excluded.detail OR connection_events.retries IS NOT excluded.retries
                    OR connection_events.max_retries IS NOT excluded.max_retries
                """)
            var changed = 0
            for event in connectionEvents {
                changed += try statement.run([
                    .text(event.provider.rawValue), .text(event.sourceID), .date(event.at), .text(event.kind.rawValue),
                    .text(event.detail), .integer(event.retries), .integer(event.maxRetries),
                ])
            }
            return changed
        }
    }

    // MARK: Usage limit

    public func setUsageLimit(_ snapshot: UsageLimitSnapshot) throws {
        try run("""
            INSERT INTO usage_limits (provider, at, used_percent, window_minutes, resets_at) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (provider) DO UPDATE SET at = excluded.at, used_percent = excluded.used_percent,
                window_minutes = excluded.window_minutes, resets_at = excluded.resets_at
            WHERE excluded.at >= usage_limits.at
            """, [
            .text(snapshot.provider.rawValue), .date(snapshot.at), .double(snapshot.usedPercent),
            .integer(snapshot.windowMinutes), .date(snapshot.resetsAt),
        ])
    }

    public func usageLimit(provider: ProviderID) throws -> UsageLimitSnapshot? {
        try query("SELECT at, used_percent, window_minutes, resets_at FROM usage_limits WHERE provider = ?", [.text(provider.rawValue)]) { row in
            UsageLimitSnapshot(provider: provider, at: row.date(0), usedPercent: row.double(1), windowMinutes: row.int(2), resetsAt: row.optionalDate(3))
        }.first
    }

    // MARK: Cursors and source state

    /// The opaque resume cursor a source returned last run.
    public func cursor(_ source: String) throws -> Data? {
        try query("SELECT data FROM cursors WHERE source = ?", [.text(source)]) { $0.blob(0) }.first
    }

    public func setCursor(_ source: String, _ data: Data) throws {
        try run("""
            INSERT INTO cursors (source, data) VALUES (?, ?)
            ON CONFLICT (source) DO UPDATE SET data = excluded.data
            """, [.text(source), .blob(data)])
    }

    public func sourceState(_ source: String) throws -> SourceStateRow? {
        try sourceStateRows(where: "WHERE source = ?", [.text(source)]).first
    }

    /// Every source's state, by source name (collector health reads them for format problems).
    public func sourceStates() throws -> [SourceStateRow] {
        try sourceStateRows(where: "", [])
    }

    private func sourceStateRows(where clause: String, _ values: [SQLValue]) throws -> [SourceStateRow] {
        let rows = try query(
            "SELECT source, state_json, version, unavailable_since, updated_at FROM source_state \(clause) ORDER BY source", values
        ) { row in
            (source: row.text(0), state: row.text(1), version: row.optionalText(2), unavailableSince: row.optionalDate(3), updatedAt: row.date(4))
        }
        return try rows.map { stored in
            let state: SetupState
            do {
                state = try StoreJSON.decode(SetupState.self, from: stored.state)
            } catch {
                throw StoreError.invalidData("Unreadable setup state for source \(stored.source)")
            }
            return SourceStateRow(
                source: stored.source, state: state, version: stored.version, unavailableSince: stored.unavailableSince, updatedAt: stored.updatedAt)
        }
    }

    public func setSourceState(_ row: SourceStateRow) throws {
        try run("""
            INSERT INTO source_state (source, state_json, version, unavailable_since, updated_at) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (source) DO UPDATE SET state_json = excluded.state_json, version = excluded.version,
                unavailable_since = excluded.unavailable_since, updated_at = excluded.updated_at
            """, [
            .text(row.source), .text(try StoreJSON.encode(row.state)), .string(row.version),
            .date(row.unavailableSince), .date(row.updatedAt),
        ])
    }
}
