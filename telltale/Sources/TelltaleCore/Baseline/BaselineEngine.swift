import Foundation

/// A model's cold-start state (spec section 8).
public enum Learning: Sendable, Equatable, Hashable {
    /// Fewer than `BaselineEngine.coldStartDays` active days: speed rules stay quiet.
    case cold(days: Int)
    /// Enough to judge speed, not yet `of` active days: "Learning usual: 5 of 14 days".
    case learning(days: Int, of: Int)
    case ready
}

/// An acceptance: usual is computed only from responses on or after `since` (spec section 8).
public struct BaselineEpoch: Sendable, Equatable {
    public var id: Int64
    public var provider: ProviderID
    public var model: String
    public var since: LocalDay
    public var createdAt: Date
    public var undoneAt: Date?
    /// The effective table immediately before and after the acceptance.
    public var before: UsualTable
    public var after: UsualTable
}

public struct Acceptance: Sendable, Equatable {
    public var epochID: Int64
    /// The signed change in usual, in percent: −24 is "24% lower than before".
    public var percentChange: Int
}

/// The current usual against the usual at the last acceptance (spec section 8's small drift).
public struct Drift: Sendable, Equatable {
    public var percent: Int
    public var direction: Direction
    public var acceptedOn: LocalDay

    public init(percent: Int, direction: Direction, acceptedOn: LocalDay) {
        self.percent = percent
        self.direction = direction
        self.acceptedOn = acceptedOn
    }
}

/// Spec section 8's per-model "usual" speed, with accepted baseline epochs. Times and active
/// days use the injected calendar. Not thread-safe: one engine per `Store`.
///
/// `usual` implements the task's normative algorithm: at evaluation instant P it uses data
/// ending before `cutoff = max(start of P's hour, latest acceptance or undo at or before P)`,
/// from the most recent active days (on or after the effective epoch's since day), excluding
/// responses inside speed episodes that had fired by the cutoff, except episodes the
/// effective acceptance took in. Every input is a dated database record, so a new engine
/// computes the same table for the same instant.
public final class BaselineEngine {
    /// Active days usual is computed from.
    public static let activeDayCount = 14
    /// Active days before speed rules may judge a model.
    public static let coldStartDays = 3
    /// Samples a key needs before it has a usual.
    public static let bucketMinimum = 20
    /// Active days in the comparison sample for acceptance percentages and drift (plan call).
    public static let comparisonDays = 3
    /// Drift smaller than this fraction isn't reported (plan call).
    public static let driftThreshold = 0.05

    private struct CacheKey: Hashable {
        var provider: ProviderID
        var model: String
        var cutoff: Date
        var epochID: Int64?
    }

    private let store: Store
    private let calendar: Calendar
    private var cache: [CacheKey: UsualTable] = [:]
    /// The store's `PRAGMA data_version` when the cache was last checked; another
    /// connection's commit changes it.
    private var cachedDataVersion: Int?

    public init(store: Store, calendar: Calendar) {
        self.store = store
        self.calendar = calendar
    }

    /// Forgets cached tables, for example at the start of a collector run.
    public func discardCache() {
        cache.removeAll()
        cachedDataVersion = nil
    }

    // MARK: Usual

    /// The usual table in effect at `instant`, cached by provider, model, cutoff and epoch.
    ///
    /// The cache is dropped whenever another connection has committed since it was filled
    /// (late-ingested responses or catch-up episodes before a cached cutoff would otherwise be
    /// missed by a long-lived engine). Writes through this engine's own connection don't change
    /// `data_version`; the collector calls `discardCache()` after ingesting, and Accept and Undo
    /// clear it themselves.
    public func usual(provider: ProviderID, model: String, at instant: Date) throws -> UsualTable {
        let version = try store.dataVersion()
        if version != cachedDataVersion {
            cache.removeAll()
            cachedDataVersion = version
        }
        let marks = try store.epochMarks(provider: provider, model: model)
        let hour = calendar.dateInterval(of: .hour, for: instant)?.start ?? instant
        let lastAction = marks.flatMap { [$0.createdAt, $0.undoneAt].compactMap { $0 } }.filter { $0 <= instant }.max()
        let cutoff = max(hour, lastAction ?? hour)
        let epoch = marks.last { $0.isLive(at: instant) }

        let key = CacheKey(provider: provider, model: model, cutoff: cutoff, epochID: epoch?.id)
        if let cached = cache[key] { return cached }
        let table = try computeUsual(provider: provider, model: model, cutoff: cutoff, epoch: epoch)
        cache[key] = table
        return table
    }

    private func computeUsual(provider: ProviderID, model: String, cutoff: Date, epoch: EpochMark?) throws -> UsualTable {
        let epochStart = epoch.map { $0.since.start(in: calendar) }
        let days = try store.activeDaysNewestFirst(
            provider: provider, model: model, before: cutoff, notBefore: epochStart, calendar: calendar, limit: Self.activeDayCount)
        guard let oldest = days.last else {
            return UsualTable(medians: [:], samples: [:], activeDays: 0, epochID: epoch?.id)
        }
        let responses = try store.throughputResponses(provider: provider, model: model, from: oldest.start(in: calendar), before: cutoff)

        // Excluded spans: speed episodes that had fired by the cutoff, minus those the effective
        // acceptance took in (fired before it), which count as normal from its since day.
        let spans = try store.speedEpisodes(provider: provider, model: model)
            .filter { $0.firedAt <= cutoff }
            .map { episode in
                (start: episode.onset, end: episode.endedAt ?? cutoff, accepted: epoch.map { episode.firedAt < $0.createdAt } ?? false)
            }
        func excluded(_ response: ResponseRecord) -> Bool {
            spans.contains { span in
                guard span.start <= response.end, response.end < span.end else { return false }
                if span.accepted, let epochStart, response.end >= epochStart { return false }
                return true
            }
        }

        var throughputs: [UsualKey: [Double]] = [:]
        for response in responses where !excluded(response) {
            guard let throughput = response.throughput else { continue }
            throughputs[UsualKey(response), default: []].append(throughput)
        }
        var medians: [UsualKey: Double] = [:]
        for (key, values) in throughputs where values.count >= Self.bucketMinimum {
            medians[key] = median(values)
        }
        return UsualTable(medians: medians, samples: throughputs.mapValues(\.count), activeDays: days.count, epochID: epoch?.id)
    }

    // MARK: Active days and cold start

    /// Local days with at least one response with throughput ending before `before`, on or
    /// after `from` when given, oldest first.
    public func activeDays(provider: ProviderID, model: String, before: Date, from: LocalDay?) throws -> [LocalDay] {
        try store.activeDaysNewestFirst(
            provider: provider, model: model, before: before, notBefore: from.map { $0.start(in: calendar) },
            calendar: calendar, limit: .max
        ).reversed()
    }

    /// Spec section 8's cold start, counting the active days of the effective table (after an
    /// acceptance, only the new epoch's days).
    public func learning(provider: ProviderID, model: String, at instant: Date) throws -> Learning {
        let days = try usual(provider: provider, model: model, at: instant).activeDays
        if days < Self.coldStartDays { return .cold(days: days) }
        if days < Self.activeDayCount { return .learning(days: days, of: Self.activeDayCount) }
        return .ready
    }

    // MARK: Epochs

    /// The newest acceptance not undone.
    public func currentEpoch(provider: ProviderID, model: String) throws -> BaselineEpoch? {
        try store.latestLiveEpoch(provider: provider, model: model)
    }

    /// Starts a baseline epoch from `since`, records its before and after tables and a
    /// `baselineAccepted` event, all in one transaction.
    @discardableResult
    public func accept(provider: ProviderID, providerName: String? = nil, model: String, since: LocalDay, at instant: Date) throws -> Acceptance {
        guard since <= LocalDay(instant, calendar: calendar) else {
            throw StoreError.invalidData("A baseline can't start after the day it is accepted (\(since))")
        }
        do {
            return try store.transaction {
                // `before` becomes permanent history, so it is computed from the database as it is now.
                discardCache()
                let before = try usual(provider: provider, model: model, at: instant)
                let epochID = try store.insertEpoch(provider: provider, model: model, since: since, createdAt: instant, before: before)
                let after = try usual(provider: provider, model: model, at: instant)
                try store.setEpochAfter(id: epochID, after)

                let sample = try comparisonSample(provider: provider, model: model, before: instant)
                let ratios = sample.compactMap { response -> Double? in
                    guard let old = before.usual(for: response), let new = after.usual(for: response), old > 0 else { return nil }
                    return new / old - 1
                }
                let percent = median(ratios).map { Int(($0 * 100).rounded()) } ?? 0
                let text = (providerName.map { "\($0): " } ?? "") + Copy.acceptance(model: model, percent: percent)
                try store.insertEvent(EventRow(
                    at: instant, kind: EventKind.baselineAccepted, provider: provider.rawValue, scope: model,
                    title: text, body: text, epochID: epochID))
                return Acceptance(epochID: epochID, percentChange: percent)
            }
        } catch {
            // A rolled-back epoch id may be reused, so tables cached under it are unsafe.
            cache.removeAll()
            throw error
        }
    }

    /// Undoes an acceptance, restoring the epoch that preceded it. Later live acceptances for
    /// the same model are undone too (plan call); other models are untouched. History stays:
    /// rows are marked undone at `instant`, and a `baselineUndone` event is appended.
    public func undo(epochID: Int64, providerName: String? = nil, at instant: Date) throws {
        try store.transaction {
            guard let selected = try store.baselineEpoch(id: epochID) else {
                throw StoreError.invalidData("No baseline acceptance \(epochID)")
            }
            guard selected.undoneAt == nil else { throw StoreError.invalidData("Baseline acceptance \(epochID) is already undone") }
            guard instant >= selected.createdAt else {
                throw StoreError.invalidData("Baseline acceptance \(epochID) can't be undone before it was made")
            }
            discardCache()
            let marks = try store.epochMarks(provider: selected.provider, model: selected.model)
            guard let position = marks.firstIndex(where: { $0.id == epochID }) else {
                throw StoreError.invalidData("No baseline acceptance \(epochID)")
            }
            let undone = marks[position...].filter { $0.undoneAt == nil }.map(\.id)
            try store.markAcceptancesUndone(undone, at: instant)
            let text = (providerName.map { "\($0): " } ?? "") + Copy.baselineRestored(model: selected.model)
            try store.insertEvent(EventRow(
                at: instant, kind: EventKind.baselineUndone, provider: selected.provider.rawValue, scope: selected.model,
                title: text, body: text, epochID: epochID))
        }
    }

    // MARK: Drift

    /// The current usual against the effective acceptance's `after` table, mix-matched over the
    /// comparison sample. Nil without an acceptance, or when smaller than `driftThreshold`.
    public func drift(provider: ProviderID, model: String, at instant: Date) throws -> Drift? {
        let current = try usual(provider: provider, model: model, at: instant)
        guard let epochID = current.epochID, let epoch = try store.baselineEpoch(id: epochID) else { return nil }
        // Compare over responses both tables can judge, so a key new since acceptance doesn't skew it.
        let sample = try comparisonSample(provider: provider, model: model, before: instant)
            .filter { current.usual(for: $0) != nil && epoch.after.usual(for: $0) != nil }
        guard let now = mixUsual(sample, table: current), let accepted = mixUsual(sample, table: epoch.after), accepted > 0 else {
            return nil
        }
        let change = now / accepted - 1
        guard abs(change) >= Self.driftThreshold else { return nil }
        return Drift(
            percent: Int((abs(change) * 100).rounded()), direction: change < 0 ? .slower : .faster,
            acceptedOn: LocalDay(epoch.createdAt, calendar: calendar))
    }

    /// The model's responses with throughput from its most recent `comparisonDays` active days,
    /// ending before `before`.
    private func comparisonSample(provider: ProviderID, model: String, before: Date) throws -> [ResponseRecord] {
        let days = try store.activeDaysNewestFirst(
            provider: provider, model: model, before: before, notBefore: nil, calendar: calendar, limit: Self.comparisonDays)
        guard let oldest = days.last else { return [] }
        return try store.throughputResponses(provider: provider, model: model, from: oldest.start(in: calendar), before: before)
    }
}
