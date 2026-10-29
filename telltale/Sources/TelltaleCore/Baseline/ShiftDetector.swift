import Foundation

/// A standing "Accept as usual?" prompt (spec section 8's lasting shift prompt).
public struct ShiftPrompt: Sendable, Equatable {
    public var provider: ProviderID
    public var model: String
    public var direction: Direction
    public var firstDay: LocalDay
    /// Consecutive active days in the run.
    public var days: Int
    /// The median of the run's episodes' worst deviations from usual, in percent.
    public var typicalPercent: Int
    /// The provider's status-page incidents that overlap the run, oldest first.
    public var incidentIDs: [String]
    /// The same incidents with their names and status-page links: the prompt links to them
    /// (spec section 8, ruling R31).
    public var incidents: [IncidentLink]
}

/// A status-page incident a prompt links to.
public struct IncidentLink: Sendable, Equatable, Hashable, Identifiable {
    public var id: String
    public var name: String
    public var link: URL

    public init(id: String, name: String, link: URL) {
        self.id = id
        self.name = name
        self.link = link
    }
}

/// Spec section 8: same-direction speed episodes that fired on `runDays` consecutive active
/// days prompt Kevin to accept the shift as usual or keep it as abnormal.
///
/// Plan calls where section 8 leaves detail open:
/// - Days without qualifying responses don't break a run. An active day breaks it unless an
///   episode of the run's direction fired that day and none of the opposite direction did,
///   except the day of the evaluation itself, which doesn't break the run until it ends.
/// - Only episodes fired after the effective acceptance count, so an accepted shift doesn't
///   prompt again.
/// - "Keep as abnormal" suppresses the direction until an episode of that direction clears
///   after the dismissal; only episodes fired after that clear then build a new run.
public enum ShiftDetector {
    public static let runDays = 3

    public static func prompt(
        provider: ProviderID, model: String, statusSourceID: String?, at instant: Date, store: Store, calendar: Calendar
    ) throws -> ShiftPrompt? {
        let acceptedAt = try store.epochMarks(provider: provider, model: model).last { $0.isLive(at: instant) }?.createdAt
        let episodes = try store.speedEpisodes(provider: provider, model: model).filter { $0.firedAt <= instant }
        let today = LocalDay(instant, calendar: calendar)

        for direction in Direction.allCases {
            var after = acceptedAt
            if let dismissed = try store.latestShiftDismissal(provider: provider, model: model, direction: direction, atOrBefore: instant) {
                let clear = episodes.compactMap { episode -> Date? in
                    guard episode.direction == direction, episode.endReason == EpisodeRow.EndReason.cleared,
                        let ended = episode.endedAt, ended > dismissed, ended <= instant else { return nil }
                    return ended
                }.min()
                guard let clear else { continue }
                after = max(after ?? clear, clear)
            }

            let counted = episodes.filter { episode in after.map { episode.firedAt > $0 } ?? true }
            var fired: [LocalDay: [EpisodeRow]] = [:]
            for episode in counted { fired[LocalDay(episode.firedAt, calendar: calendar), default: []].append(episode) }
            let active = try store.activeDaysNewestFirst(
                provider: provider, model: model, before: instant, notBefore: after.map { LocalDay($0, calendar: calendar).start(in: calendar) },
                calendar: calendar, limit: .max)
            let days = Set(active).union(fired.keys).sorted(by: >)

            var run: [LocalDay] = []
            for day in days {
                let directions = Set((fired[day] ?? []).compactMap(\.direction))
                if directions.contains(direction.opposite) { break }
                if directions.contains(direction) {
                    run.append(day)
                } else if day == today && run.isEmpty {
                    continue
                } else {
                    break
                }
            }
            guard run.count >= runDays, let firstDay = run.last else { continue }

            let runDaySet = Set(run)
            let deviations = counted
                .filter { $0.direction == direction && runDaySet.contains(LocalDay($0.firedAt, calendar: calendar)) }
                .map(\.worstValue)
            // The run spans its first day's start to its last day's end, never past the evaluation.
            let runStart = firstDay.start(in: calendar)
            let interval = DateInterval(start: runStart, end: max(runStart, min(instant, run[0].end(in: calendar))))
            // Only the provider's own status page (nil: none configured, so none).
            let incidents = try statusSourceID.map { source in
                try store.incidents(source: source, overlapping: interval).map { IncidentLink(id: $0.id, name: $0.name, link: $0.link) }
            } ?? []
            return ShiftPrompt(
                provider: provider, model: model, direction: direction, firstDay: firstDay, days: run.count,
                typicalPercent: median(deviations).flatMap(SpeedIndex.percent) ?? 0, incidentIDs: incidents.map(\.id), incidents: incidents)
        }
        return nil
    }

    /// "Keep as abnormal": dismisses this run until a clear in its direction and a new run.
    public static func keepAsAbnormal(_ prompt: ShiftPrompt, at instant: Date, store: Store) throws {
        try store.insertShiftDismissal(
            provider: prompt.provider, model: prompt.model, direction: prompt.direction, firstDay: prompt.firstDay, at: instant)
    }
}
