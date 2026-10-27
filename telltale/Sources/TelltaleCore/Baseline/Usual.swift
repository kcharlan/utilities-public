import Foundation

/// A local calendar day in the injected calendar (spec section 8's active days).
public struct LocalDay: Sendable, Hashable, Codable, Comparable, CustomStringConvertible {
    public var year: Int
    public var month: Int
    public var day: Int

    public init(year: Int, month: Int, day: Int) {
        self.year = year
        self.month = month
        self.day = day
    }

    /// The local day containing `date`.
    public init(_ date: Date, calendar: Calendar) {
        let components = calendar.dateComponents([.year, .month, .day], from: date)
        self.init(year: components.year ?? 0, month: components.month ?? 0, day: components.day ?? 0)
    }

    /// `yyyy-MM-dd`, as stored in `baseline_epochs.since_day` and `shift_dismissals.first_day`.
    init?(text: String) {
        let parts = text.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return nil }
        self.init(year: parts[0], month: parts[1], day: parts[2])
    }

    /// The first instant of the day in `calendar`'s time zone.
    public func start(in calendar: Calendar) -> Date {
        let midnight = DateComponents(year: year, month: month, day: day)
        guard let date = calendar.date(from: midnight) else {
            preconditionFailure("Invalid local day \(self) in \(calendar.timeZone.identifier)")
        }
        return calendar.startOfDay(for: date)
    }

    /// The first instant of the following day: the end of this one.
    public func end(in calendar: Calendar) -> Date {
        let first = start(in: calendar)
        guard let next = calendar.date(byAdding: .day, value: 1, to: first) else {
            preconditionFailure("No day after \(self) in \(calendar.timeZone.identifier)")
        }
        return calendar.startOfDay(for: next)
    }

    public var description: String { String(format: "%04ld-%02ld-%02ld", year, month, day) }

    public static func < (lhs: LocalDay, rhs: LocalDay) -> Bool {
        (lhs.year, lhs.month, lhs.day) < (rhs.year, rhs.month, rhs.day)
    }
}

/// A baseline key (spec section 8): model (implicit in the table), effort, service tier and
/// input-size bucket. A response with no recorded tier keys as "none".
public struct UsualKey: Sendable, Hashable, Codable {
    public static let noTier = "none"

    public var effort: String?
    public var serviceTier: String?
    public var bucket: InputBucket

    public init(effort: String?, serviceTier: String?, bucket: InputBucket) {
        self.effort = effort
        self.serviceTier = serviceTier
        self.bucket = bucket
    }

    /// The key a response's throughput is judged by.
    public init(_ response: ResponseRecord) {
        self.init(
            effort: response.effort, serviceTier: response.serviceTier ?? Self.noTier,
            bucket: InputBucket(inputTokens: response.inputTokens))
    }
}

/// One model's usual speed: the median throughput per key, from the active days and epoch it
/// was computed for. `samples` counts every key seen; `medians` holds only keys with at least
/// `BaselineEngine.bucketMinimum` samples.
public struct UsualTable: Sendable, Equatable {
    public var medians: [UsualKey: Double]
    public var samples: [UsualKey: Int]
    /// Active days the table was computed from, at most `BaselineEngine.activeDayCount`.
    public var activeDays: Int
    /// The baseline epoch in effect, or nil before any (live) acceptance.
    public var epochID: Int64?

    public init(medians: [UsualKey: Double], samples: [UsualKey: Int], activeDays: Int, epochID: Int64?) {
        self.medians = medians
        self.samples = samples
        self.activeDays = activeDays
        self.epochID = epochID
    }

    /// The response's usual throughput, or nil when its key is below the bucket minimum.
    public func usual(for response: ResponseRecord) -> Double? { medians[UsualKey(response)] }
}

extension UsualTable: Codable {
    /// Stored as a flat, sorted list of keys so `before_json`/`after_json` stay readable.
    private struct Entry: Codable {
        var effort: String?
        var serviceTier: String?
        var bucket: InputBucket
        var samples: Int
        var median: Double?
    }

    private enum CodingKeys: String, CodingKey { case entries, activeDays, epochID }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        var medians: [UsualKey: Double] = [:]
        var samples: [UsualKey: Int] = [:]
        for entry in try container.decode([Entry].self, forKey: .entries) {
            let key = UsualKey(effort: entry.effort, serviceTier: entry.serviceTier, bucket: entry.bucket)
            samples[key] = entry.samples
            medians[key] = entry.median
        }
        self.init(
            medians: medians, samples: samples, activeDays: try container.decode(Int.self, forKey: .activeDays),
            epochID: try container.decodeIfPresent(Int64.self, forKey: .epochID))
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        let entries = samples.map { key, count in
            Entry(effort: key.effort, serviceTier: key.serviceTier, bucket: key.bucket, samples: count, median: medians[key])
        }.sorted { ($0.effort ?? "", $0.serviceTier ?? "", $0.bucket.rawValue) < ($1.effort ?? "", $1.serviceTier ?? "", $1.bucket.rawValue) }
        try container.encode(entries, forKey: .entries)
        try container.encode(activeDays, forKey: .activeDays)
        try container.encodeIfPresent(epochID, forKey: .epochID)
    }
}

/// Spec section 8's mix-matched usual: the median, over `responses`, of each response's own
/// usual. Responses whose key has no usual are left out; nil when none has one.
public func mixUsual(_ responses: [ResponseRecord], table: UsualTable) -> Double? {
    median(responses.compactMap(table.usual(for:)))
}

/// The median; the mean of the middle two for an even count; nil when empty.
func median(_ values: [Double]) -> Double? {
    guard !values.isEmpty else { return nil }
    let sorted = values.sorted()
    let middle = sorted.count / 2
    return sorted.count.isMultiple(of: 2) ? (sorted[middle - 1] + sorted[middle]) / 2 : sorted[middle]
}
