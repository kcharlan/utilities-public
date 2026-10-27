import Foundation

// Episodes and events (spec sections 7.2 and 7.3). Rows are written once as evaluated; later
// changes only end an episode or mark an event undone. Task 8 extends this file.

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

    public init(
        at: Date, kind: String, provider: String, scope: String, title: String, body: String,
        episodeID: Int64? = nil, epochID: Int64? = nil, link: URL? = nil, undoneAt: Date? = nil
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
    }
}

extension Store {
    private static let episodeColumns = """
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
            INSERT INTO events (at, kind, provider, scope, title, body, episode_id, epoch_id, link, undone_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
            .date(event.at), .text(event.kind), .text(event.provider), .text(event.scope), .text(event.title),
            .text(event.body), event.episodeID.map(SQLValue.int) ?? .null, event.epochID.map(SQLValue.int) ?? .null,
            .string(event.link?.absoluteString), .date(event.undoneAt),
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

    private static func episode(_ row: Row) throws -> EpisodeRow {
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
