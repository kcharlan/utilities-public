import Foundation

/// One model's "Prompt sizes" and "Workload" sections (spec section 9.2): the last 3 hours against
/// usual. Workload describes the user's own behavior, so it excludes nothing and isn't gated by
/// acceptance.
///
/// - **Now** is the window `(now − 3 h, now]`, cut into three one-hour slices ending at now; an
///   active hour is a slice with a response. Responses an hour and active sessions are averaged over
///   the active hours only. Median prompt is over every response in the window, and the shares are
///   ratios of sums over it.
/// - **Usual** is over the same 14 active days as usual speed (days with a response that has a
///   throughput), before the window. Each scalar measure is computed per active clock hour and
///   usual is the median of those hourly values, not matched to hour of day. The two
///   distributions, effort mix and the prompt-size histogram, are pooled shares over those days, so
///   each side sums to one **(plan call)**.
/// - `usageLimit` is the provider's latest usage-limit snapshot (spec section 6.4).
public struct Workload: Sendable, Equatable {
    public struct CompactionReadout: Sendable, Equatable {
        public var lastThreeHours: Int
        public var blocked: TimeInterval
        public var latestPoint: Int?
    }
    public struct LimitReached: Sendable, Equatable {
        public var at: Date
        public var resetsAt: Date?
    }
    public struct Measure: Sendable, Equatable {
        public var now: Double?
        public var usual: Double?

        public init(now: Double?, usual: Double?) {
            self.now = now
            self.usual = usual
        }
    }

    public struct EffortShare: Sendable, Equatable, Hashable {
        /// nil when the provider recorded no effort.
        public var effort: String?
        public var now: Double
        public var usual: Double
    }

    public struct BucketShare: Sendable, Equatable, Hashable {
        public var bucket: InputBucket
        public var now: Double
        public var usual: Double
    }

    /// Spec section 9.2: the last 3 hours.
    public static let windowLength: TimeInterval = PanelSnapshot.activeWindow
    static let hour: TimeInterval = 3_600

    public var window: DateInterval
    /// Active days usual was computed from, at most `BaselineEngine.activeDayCount`.
    public var usualActiveDays: Int
    public var medianPrompt: Measure
    public var responsesPerHour: Measure
    public var activeSessions: Measure
    public var cachedShare: Measure
    public var reasoningShare: Measure
    public var subagentShare: Measure
    /// Efforts seen on either side, most used now first.
    public var effortMix: [EffortShare]
    /// Every input-size bucket in order.
    public var histogram: [BucketShare]
    public var usageLimit: UsageLimitSnapshot?
    public var compactions: CompactionReadout?
    public var limitReached: LimitReached?
    public var hasFastMode: Bool

    public static func load(store: Store, provider: ProviderID, model: String, now: Date, calendar: Calendar, supportedRules: Set<RuleID> = []) throws -> Workload {
        try store.transaction {
            let window = DateInterval(start: now.addingTimeInterval(-windowLength), end: now)
            let current = try store.responses(provider: provider, model: model, endingIn: window.start...now).filter { $0.end > window.start }

            let days = try store.activeDaysNewestFirst(
                provider: provider, model: model, before: window.start, notBefore: nil, calendar: calendar, limit: BaselineEngine.activeDayCount)
            var past: [ResponseRecord] = []
            if let oldest = days.last {
                past = try store.responses(provider: provider, model: model, endingIn: oldest.start(in: calendar)...window.start)
                    .filter { $0.end < window.start }
            }
            // Slices of the window: 0 is the oldest hour, 2 the newest; a response ending exactly at now is in the newest.
            let slices = Dictionary(grouping: current) { min(2, Int(($0.end.timeIntervalSince(window.start)) / hour)) }.values.map(Array.init)
            let hours = Dictionary(grouping: past) { calendar.dateInterval(of: .hour, for: $0.end)?.start ?? $0.end }.values.map(Array.init)

            func measure(now: Double?, perHour: ([ResponseRecord]) -> Double?) -> Measure {
                Measure(now: current.isEmpty ? nil : now, usual: median(hours.compactMap(perHour)))
            }
            let limit = try store.usageLimit(provider: provider)
            let reached = limit.flatMap { item -> LimitReached? in
                guard provider == .claude, item.usedPercent == 100, now >= item.at, now.timeIntervalSince(item.at) <= 5 * hour else { return nil }
                return LimitReached(at: item.at, resetsAt: item.resetsAt)
            }
            let automatic = supportedRules.contains(.compactions) ? try store.compactions(provider: provider, in: Date.distantPast...now).filter { $0.trigger == .auto } : []
            let recent = automatic.filter { $0.at > window.start }
            let compact = supportedRules.contains(.compactions) ? CompactionReadout(
                lastThreeHours: recent.count, blocked: recent.reduce(0) { $0 + ($1.duration ?? 0) },
                latestPoint: median(automatic.suffix(5).map { Double($0.tokensBefore) }).map { Int($0) }) : nil
            return Workload(
                window: window, usualActiveDays: days.count,
                medianPrompt: measure(now: medianInput(current), perHour: medianInput),
                responsesPerHour: measure(now: mean(slices.map { Double($0.count) })) { Double($0.count) },
                activeSessions: measure(now: mean(slices.map(sessionCount)), perHour: sessionCount),
                cachedShare: measure(now: cachedShare(current), perHour: cachedShare),
                reasoningShare: measure(now: reasoningShare(current), perHour: reasoningShare),
                subagentShare: measure(now: subagentShare(current), perHour: subagentShare),
                effortMix: effortMix(now: current, usual: past),
                histogram: histogram(now: current, usual: past),
                usageLimit: provider == .claude ? nil : limit, compactions: compact, limitReached: reached,
                hasFastMode: try store.query("SELECT 1 FROM responses WHERE provider = ? AND model = ? AND service_tier = 'fast' AND end_at <= ? LIMIT 1", [.text(provider.rawValue), .text(model), .date(now)]) { _ in true }.first ?? false)
        }
    }

    // MARK: Measures

    private static func medianInput(_ responses: [ResponseRecord]) -> Double? { median(responses.map { Double($0.inputTokens) }) }

    private static func sessionCount(_ responses: [ResponseRecord]) -> Double? {
        responses.isEmpty ? nil : Double(Set(responses.map(\.sessionID)).count)
    }

    private static func cachedShare(_ responses: [ResponseRecord]) -> Double? {
        ratio(responses.reduce(0) { $0 + $1.cachedInputTokens }, responses.reduce(0) { $0 + $1.inputTokens })
    }

    /// Over the responses that record reasoning tokens.
    private static func reasoningShare(_ responses: [ResponseRecord]) -> Double? {
        let recorded = responses.filter { $0.reasoningTokens != nil }
        return ratio(recorded.reduce(0) { $0 + ($1.reasoningTokens ?? 0) }, recorded.reduce(0) { $0 + $1.outputTokens })
    }

    private static func subagentShare(_ responses: [ResponseRecord]) -> Double? {
        ratio(responses.filter(\.isSubagent).count, responses.count)
    }

    private static func effortMix(now current: [ResponseRecord], usual past: [ResponseRecord]) -> [EffortShare] {
        let nowCounts = Dictionary(grouping: current, by: \.effort).mapValues(\.count)
        let usualCounts = Dictionary(grouping: past, by: \.effort).mapValues(\.count)
        let efforts = Set(nowCounts.keys).union(usualCounts.keys)
        return efforts.map { effort in
            EffortShare(
                effort: effort, now: ratio(nowCounts[effort] ?? 0, current.count) ?? 0, usual: ratio(usualCounts[effort] ?? 0, past.count) ?? 0)
        }.sorted { ($0.now, $0.usual, $0.effort ?? "") > ($1.now, $1.usual, $1.effort ?? "") }
    }

    private static func histogram(now current: [ResponseRecord], usual past: [ResponseRecord]) -> [BucketShare] {
        let nowCounts = Dictionary(grouping: current) { InputBucket(inputTokens: $0.inputTokens) }.mapValues(\.count)
        let usualCounts = Dictionary(grouping: past) { InputBucket(inputTokens: $0.inputTokens) }.mapValues(\.count)
        return InputBucket.allCases.map { bucket in
            BucketShare(bucket: bucket, now: ratio(nowCounts[bucket] ?? 0, current.count) ?? 0, usual: ratio(usualCounts[bucket] ?? 0, past.count) ?? 0)
        }
    }

    private static func ratio(_ part: Int, _ whole: Int) -> Double? { whole > 0 ? Double(part) / Double(whole) : nil }

    private static func mean(_ values: [Double?]) -> Double? {
        let known = values.compactMap { $0 }
        return known.isEmpty ? nil : known.reduce(0, +) / Double(known.count)
    }
}
