import Foundation

/// One entry in the dashboard's Events list (spec section 9.2).
public struct FeedEvent: Sendable, Equatable, Identifiable {
    public enum Kind: String, Sendable, Hashable {
        case slowdown, speedup, largePrompts, compactions, failedTurns, disconnects, incident, usageLimit
        /// A rule's condition cleared (`ruleCleared`).
        case cleared
        /// An idle end or disabled rule end. Reversals write no event and are not listed.
        case ended
        case statusPost, baselineAccepted, baselineUndone
        /// A span the provider's connection log no longer covered (`connectionHistoryIncomplete`).
        case historyGap
        /// One or more collector runs in a row that failed.
        case collectorFailed
        /// An event kind this version doesn't know.
        case other
    }

    /// Unique across the list: the source row's table and id.
    public var id: String
    public var at: Date
    public var kind: Kind
    /// The lamp color the entry is marked with; nil is neutral.
    public var color: LampColor?
    public var title: String
    public var body: String
    public var link: URL?
    /// The acceptance Undo restores the baseline before; nil once undone, and for other kinds.
    public var undoableEpochID: Int64?
    /// When an acceptance was undone: the entry shows its undone state.
    public var undoneAt: Date?
    /// Set when a later acceptance for the same model is still live, so Undo restores more than this
    /// one and asks first (`Copy.undoEarlierAcceptanceConfirmation`).
    public var undoConfirmation: String?
    /// The end of an entry that spans time (a connection-history gap).
    public var endsAt: Date?
    /// Full model identifier for a model-scoped entry, used for its tooltip.
    public var modelID: String? = nil
}

/// Spec section 9.2's Events and section 8's Undo contract, newest first.
///
/// - Every row of `events`: rule transitions (worded by the collector), status posts, baseline
///   acceptances and undos, and connection-history gaps.
/// - Episode ends that write no event (spec section 7.2's silent idle end, and ruling R13's
///   `ruleDisabled`), read from `episodes`. Reversals are excluded.
/// - Collector problems: each streak of failed runs (skipped runs don't break or count) as one
///   entry at its last failure, from the run records still kept (30 days).
///
/// Every live acceptance offers Undo; an undone one shows when it was undone. Baseline events carry
/// the raw model id the collector wrote, so `naming` supplies display names.
public enum EventFeed {
    public static func load(
        store: Store, limit: Int, naming: (ProviderID, String) -> String = { $1 }, calendar: Calendar = .current,
        sources: [SourceSummary] = []
    ) throws -> [FeedEvent] {
        guard limit > 0 else { return [] }
        return try store.transaction {
            let rows = try store.feedEvents(limit: limit)
            var entries = try rows.map { try entry($0, store: store, naming: naming) }
            entries += try store.silentEpisodeEnds(limit: limit).map { episode in
                let name: String
                if episode.rule == RuleID.incident.rawValue {
                    name = sources.first { $0.statusSourceID == episode.provider }?.statusName ?? episode.provider
                } else {
                    name = sources.first { $0.provider.rawValue == episode.provider }?.name ?? episode.provider
                }
                let body = episode.endReason == EpisodeRow.EndReason.ruleDisabled ? Copy.episodeEndedRuleOff : Copy.episodeEndedIdle
                return FeedEvent(
                    id: "episode-\(episode.id ?? 0)", at: episode.endedAt ?? episode.firedAt, kind: .ended, color: nil,
                    title: RuleID(rawValue: episode.rule)?.title ?? episode.rule,
                    body: "\(name): \(body)")
            }
            entries += try collectorFailures(store: store, limit: limit, calendar: calendar)
            let visible = Array(entries.sorted { ($0.at, $0.id) > ($1.at, $1.id) }.prefix(limit))
            let visibleIDs = Set(visible.map(\.id))
            let shownRows = rows.filter { visibleIDs.contains("event-\($0.id)") }
            var names: [String: [String: String]] = [:]
            for source in sources {
                let ids = shownRows.filter { row in
                    row.event.provider == source.provider.rawValue && row.event.scope != "*" &&
                    ([EventKind.baselineAccepted, EventKind.baselineUndone].contains(row.event.kind) ||
                     [RuleID.slower.rawValue, RuleID.faster.rawValue].contains(row.rule ?? ""))
                }.map { $0.event.scope }
                names[source.provider.rawValue] = DisplayNames.disambiguated(ids, naming: source.naming)
            }
            let byID = Dictionary(uniqueKeysWithValues: shownRows.map { ("event-\($0.id)", $0) })
            return try visible.map { original in
                guard let row = byID[original.id] else { return original }
                let provider = ProviderID(rawValue: row.event.provider)
                let base = sources.first { $0.provider == provider }?.naming.displayName(model: row.event.scope)
                let name = names[provider.rawValue]?[row.event.scope]
                var rendered = try entry(row, store: store, naming: { p, m in names[p.rawValue]?[m] ?? naming(p, m) })
                if let base, let name, [RuleID.slower.rawValue, RuleID.faster.rawValue].contains(row.rule ?? "") {
                    rendered.body = DisplayNames.speedText(rendered.body, base: base, name: name, provider: sources.first { $0.provider == provider }?.name ?? "")
                }
                if [EventKind.ruleFired, EventKind.ruleEscalated, EventKind.ruleCleared].contains(row.event.kind),
                   let source = sources.first(where: { $0.provider == provider }), !rendered.body.hasPrefix("\(source.name): ") {
                    rendered.body = "\(source.name): \(rendered.body)"
                }
                return rendered
            }
        }
    }

    private static func entry(_ row: FeedRow, store: Store, naming: (ProviderID, String) -> String) throws -> FeedEvent {
        var event = FeedEvent(
            id: "event-\(row.id)", at: row.event.at, kind: .other, color: nil, title: row.event.title, body: row.event.body,
            link: row.event.link, undoneAt: row.event.undoneAt, endsAt: row.event.endsAt)
        if [EventKind.baselineAccepted, EventKind.baselineUndone].contains(row.event.kind) ||
            [RuleID.slower.rawValue, RuleID.faster.rawValue].contains(row.rule ?? "") {
            event.modelID = row.event.scope
        }
        switch row.event.kind {
        case EventKind.ruleFired, EventKind.ruleEscalated:
            let rule = row.rule.flatMap(RuleID.init(rawValue:)) ?? RuleID.allCases.first { $0.title == row.event.title }
            event.kind = rule.map(kind) ?? .other
            event.color = row.severity.flatMap(LampColor.init(rawValue:)) ?? (rule == .faster ? .blue : .amber)
            if rule == .faster { event.color = .blue }
        case EventKind.ruleCleared:
            event.kind = .cleared
        case EventKind.statusPost:
            event.kind = .statusPost
        case EventKind.connectionHistoryIncomplete:
            event.kind = .historyGap
        case EventKind.baselineAccepted, EventKind.baselineUndone:
            let provider = ProviderID(rawValue: row.event.provider)
            let model = row.event.scope
            let name = naming(provider, model)
            event.title = row.event.title.replacingOccurrences(of: model, with: name)
            event.body = row.event.body.replacingOccurrences(of: model, with: name)
            guard row.event.kind == EventKind.baselineAccepted else {
                event.kind = .baselineUndone
                break
            }
            event.kind = .baselineAccepted
            if row.event.undoneAt == nil, let epochID = row.event.epochID {
                let marks = try store.epochMarks(provider: provider, model: model)
                if let position = marks.firstIndex(where: { $0.id == epochID }), marks[position].undoneAt == nil {
                    event.undoableEpochID = epochID
                    if marks[(position + 1)...].contains(where: { $0.undoneAt == nil }) {
                        event.undoConfirmation = Copy.undoEarlierAcceptanceConfirmation(model: name)
                    }
                }
            }
        default:
            break
        }
        return event
    }

    private static func kind(_ rule: RuleID) -> FeedEvent.Kind {
        switch rule {
        case .slower: .slowdown
        case .faster: .speedup
        case .largePrompts: .largePrompts
        case .compactions: .compactions
        case .failedTurns: .failedTurns
        case .disconnects: .disconnects
        case .incident: .incident
        case .usageLimit: .usageLimit
        }
    }

    /// Runs read per page while looking for failure streaks.
    static let runPage = 200

    /// Failure streaks, newest first, read a page at a time back from the newest run and only until
    /// `limit` whole streaks are found: an older streak would fall past the list's end anyway.
    private static func collectorFailures(store: Store, limit: Int, calendar: Calendar) throws -> [FeedEvent] {
        var entries: [FeedEvent] = []
        // Newest first: the streak's newest run is its first element.
        var streak: [CollectorRunRecord] = []
        func close() {
            guard let newest = streak.first, let oldest = streak.last else { return }
            let from = oldest.finishedAt ?? oldest.startedAt
            let to = newest.finishedAt ?? newest.startedAt
            entries.append(FeedEvent(
                id: "runs-\(oldest.id)", at: to, kind: .collectorFailed, color: .red, title: CollectorHealth.title,
                body: Copy.collectorRunsFailed(count: streak.count, from: from, to: to, reason: newest.detail, calendar: calendar)))
            streak = []
        }
        var cursor: CollectorRunRecord?
        pages: while true {
            let page = try store.finishedRuns(before: cursor, limit: runPage)
            for run in page {
                if run.outcome == .failed {
                    streak.append(run)
                } else {
                    close()
                    if entries.count >= limit { break pages }
                }
            }
            guard page.count == runPage, let last = page.last else { break }
            cursor = last
        }
        close()
        return entries
    }
}

/// An `events` row with its id and, for rule events, the episode's rule and severity.
struct FeedRow {
    var id: Int64
    var event: EventRow
    var rule: String?
    var severity: String?
}

extension Store {
    /// The newest `limit` events, newest first, joined to their episodes.
    func feedEvents(limit: Int) throws -> [FeedRow] {
        try query("""
            SELECT e.id, e.at, e.kind, e.provider, e.scope, e.title, e.body, e.episode_id, e.epoch_id, e.link, e.undone_at, e.ends_at,
                   p.rule, p.severity
            FROM events e LEFT JOIN episodes p ON p.id = e.episode_id
            ORDER BY e.at DESC, e.id DESC LIMIT ?
            """, [.integer(limit)]) { row in
            FeedRow(
                id: Int64(row.int(0)),
                event: EventRow(
                    at: row.date(1), kind: row.text(2), provider: row.text(3), scope: row.text(4), title: row.text(5), body: row.text(6),
                    episodeID: row.optionalInt(7).map(Int64.init), epochID: row.optionalInt(8).map(Int64.init),
                    link: row.optionalText(9).flatMap(URL.init(string:)), undoneAt: row.optionalDate(10), endsAt: row.optionalDate(11)),
                rule: row.optionalText(12), severity: row.optionalText(13))
        }
    }

    /// Finished and failed runs (no skipped or running ones), newest first, older than `cursor`.
    func finishedRuns(before cursor: CollectorRunRecord?, limit: Int) throws -> [CollectorRunRecord] {
        try query("""
            SELECT id, started_at, finished_at, outcome, detail FROM collector_runs
            WHERE outcome NOT IN (?, ?) AND (? IS NULL OR started_at < ? OR (started_at = ? AND id < ?))
            ORDER BY started_at DESC, id DESC LIMIT ?
            """, [
                .text(RunOutcome.skipped.rawValue), .text(RunOutcome.running.rawValue), cursor.map { .date($0.startedAt) } ?? .null,
                cursor.map { .date($0.startedAt) } ?? .null, cursor.map { .date($0.startedAt) } ?? .null, cursor.map { .int($0.id) } ?? .null,
                .integer(limit),
            ]) { row in
            CollectorRunRecord(
                id: Int64(row.int(0)), startedAt: row.date(1), finishedAt: row.optionalDate(2),
                outcome: RunOutcome(rawValue: row.text(3)) ?? .failed, detail: row.text(4))
        }
    }

    /// The newest `limit` idle or rule-disabled episode ends (not reversals),
    /// newest end first.
    func silentEpisodeEnds(limit: Int) throws -> [EpisodeRow] {
        try query("""
            SELECT \(Self.episodeColumns) FROM episodes
            WHERE ended_at IS NOT NULL AND end_reason IN (?, ?) ORDER BY ended_at DESC, id DESC LIMIT ?
            """, [.text(EpisodeRow.EndReason.idleEnded), .text(EpisodeRow.EndReason.ruleDisabled), .integer(limit)], Self.episode)
    }
}
