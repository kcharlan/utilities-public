import Foundation

/// The speed chart's range control (spec section 9.2: 6h, 24h, 7d, 14d).
public enum ChartRange: String, Sendable, Hashable, CaseIterable, Identifiable {
    case sixHours, day, week, twoWeeks

    public var id: String { rawValue }

    public var label: String {
        switch self {
        case .sixHours: "6h"
        case .day: "24h"
        case .week: "7d"
        case .twoWeeks: "14d"
        }
    }

    public var duration: TimeInterval {
        switch self {
        case .sixHours: 6 * 3_600
        case .day: 86_400
        case .week: 7 * 86_400
        case .twoWeeks: 14 * 86_400
        }
    }
}

/// One model's "Speed against usual" section (spec section 9.2), read in one read transaction.
///
/// - `lastHour`: the readouts. tok/s is the median throughput of the responses that ended in the
///   last hour and usual is their mix-matched usual (spec section 8), as in the panel row. The
///   median response time is over the same responses; its usual is the median of the time each
///   would have taken at its own usual speed (output tokens over usual tok/s), so it is
///   mix-matched too **(plan call)**.
/// - `dots`: one per clock hour, the median speed index of the stored known evaluation points in
///   it, colored by the most severe speed episode in effect during that hour (slower episodes take
///   their severity, faster ones blue); nil is usual.
/// - `incidents`: every stored status-page incident, from publication to resolution (or now while
///   open), clipped to the range. `failures`: the model's failed turns (completion, else start).
/// - `bucketGaps`: input-size buckets with responses in the last 3 hours that have no usual yet
///   ("Not enough history yet for 300k+ prompts"), once the model is past cold start.
public struct ModelDetail: Sendable, Equatable {
    public struct Readout: Sendable, Equatable {
        public var tps: Double?
        public var usualTPS: Double?
        public var medianSeconds: Double?
        public var usualMedianSeconds: Double?

        public init(tps: Double?, usualTPS: Double?, medianSeconds: Double?, usualMedianSeconds: Double?) {
            self.tps = tps
            self.usualTPS = usualTPS
            self.medianSeconds = medianSeconds
            self.usualMedianSeconds = usualMedianSeconds
        }
    }

    public struct SpeedDot: Sendable, Equatable, Hashable {
        /// The start of the clock hour.
        public var hour: Date
        public var index: Double
        public var color: LampColor?

        public init(hour: Date, index: Double, color: LampColor?) {
            self.hour = hour
            self.index = index
            self.color = color
        }
    }

    /// The readout window.
    public static let readoutWindow: TimeInterval = PanelSnapshot.rateWindow
    /// The window bucket gaps are judged over (the workload window).
    public static let gapWindow: TimeInterval = PanelSnapshot.activeWindow

    public var range: ChartRange
    /// The chart's time domain: the range ending now.
    public var interval: DateInterval
    public var lastHour: Readout
    public var dots: [SpeedDot]
    public var incidents: [DateInterval]
    public var failures: [Date]
    public var learning: Learning
    public var drift: Drift?
    public var shift: ShiftPrompt?
    public var bucketGaps: [InputBucket]

    public static func load(
        store: Store, baseline: BaselineEngine, provider: ProviderID, model: String, range: ChartRange, now: Date, calendar: Calendar
    ) throws -> ModelDetail {
        try store.transaction {
            let interval = DateInterval(start: now.addingTimeInterval(-range.duration), end: now)
            let table = try baseline.usual(provider: provider, model: model, at: now)

            let recent = try store.responses(provider: provider, model: model, endingIn: now.addingTimeInterval(-readoutWindow)...now)
                .filter { $0.throughput != nil }
            let usualSeconds = recent.compactMap { response in table.usual(for: response).map { Double(response.outputTokens) / $0 } }
            let readout = Readout(
                tps: median(recent.compactMap(\.throughput)), usualTPS: mixUsual(recent, table: table),
                medianSeconds: median(recent.map(\.duration)), usualMedianSeconds: median(usualSeconds))

            let learning = try baseline.learning(provider: provider, model: model, at: now)
            var gaps: [InputBucket] = []
            if case .cold = learning {} else {
                let judged = try store.responses(provider: provider, model: model, endingIn: now.addingTimeInterval(-gapWindow)...now)
                    .filter { $0.throughput != nil }
                let missing = Set(judged.filter { table.usual(for: $0) == nil }.map { InputBucket(inputTokens: $0.inputTokens) })
                gaps = InputBucket.allCases.filter(missing.contains)
            }

            return ModelDetail(
                range: range, interval: interval, lastHour: readout,
                dots: try dots(store: store, provider: provider, model: model, interval: interval, calendar: calendar),
                incidents: try incidentBands(store: store, interval: interval),
                failures: try store.failureTimes(provider: provider, model: model, in: interval),
                learning: learning, drift: try baseline.drift(provider: provider, model: model, at: now),
                shift: try ShiftDetector.prompt(provider: provider, model: model, at: now, store: store, calendar: calendar),
                bucketGaps: gaps)
        }
    }

    /// Every model with stored responses for `provider`, sorted: the dashboard sidebar.
    public static func models(store: Store, provider: ProviderID) throws -> [String] {
        try store.models(provider: provider)
    }

    private static func dots(store: Store, provider: ProviderID, model: String, interval: DateInterval, calendar: Calendar) throws -> [SpeedDot] {
        let points = try store.evalPoints(provider: provider, model: model, in: interval.start...interval.end)
            .filter { $0.state == .known && $0.speedIndex != nil }
        var hours: [Date: [Double]] = [:]
        for point in points {
            let hour = calendar.dateInterval(of: .hour, for: point.at)?.start ?? point.at
            hours[hour, default: []].append(point.speedIndex ?? 1)
        }
        let episodes = try store.speedEpisodes(provider: provider, model: model)
        return hours.keys.sorted().compactMap { hour in
            guard let index = median(hours[hour] ?? []) else { return nil }
            let end = calendar.date(byAdding: .hour, value: 1, to: hour) ?? hour.addingTimeInterval(3_600)
            let color = episodes.filter { $0.onset < end && ($0.endedAt ?? .distantFuture) > hour }
                .map { $0.direction == .faster ? LampColor.blue : LampColor(rawValue: $0.severity) ?? .amber }
                .max()
            return SpeedDot(hour: hour, index: index, color: color)
        }
    }

    private static func incidentBands(store: Store, interval: DateInterval) throws -> [DateInterval] {
        var bands: [DateInterval] = []
        for source in try store.incidentSources() {
            for incident in try store.incidents(source: source, overlapping: interval) {
                let start = max(incident.publishedAt, interval.start)
                let end = min(incident.isResolved ? incident.updatedAt : interval.end, interval.end)
                guard start < end else { continue }
                bands.append(DateInterval(start: start, end: end))
            }
        }
        return bands.sorted { $0.start < $1.start }
    }
}

extension Store {
    /// When the model's failed turns happened (completion, else start) within `interval`, oldest
    /// first. A turn stored without a model takes the model of a response in the same turn (spec
    /// section 6.2), as the rule engine does.
    func failureTimes(provider: ProviderID, model: String, in interval: DateInterval) throws -> [Date] {
        try query("""
            SELECT COALESCE(f.completed_at, f.started_at) AS at FROM failed_turns f
            WHERE f.provider = ? AND at BETWEEN ? AND ?
              AND COALESCE(f.model, (SELECT r.model FROM responses r WHERE r.provider = f.provider AND r.turn_id = f.turn_id
                                     ORDER BY r.end_at DESC LIMIT 1)) = ?
            ORDER BY at, f.turn_id
            """, [.text(provider.rawValue), .date(interval.start), .date(interval.end), .text(model)]) { $0.date(0) }
    }
}
