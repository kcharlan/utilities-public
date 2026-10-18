import Foundation

public struct CheckInterval: Codable, Hashable, Sendable {
    public static let allowedMinutes = 10...1440
    public static func validationMessage(locale: Locale = .current) -> String {
        let format = IntegerFormatStyle<Int>.number.grouping(.automatic).locale(locale)
        return "Enter \(allowedMinutes.lowerBound.formatted(format)) to \(allowedMinutes.upperBound.formatted(format)) minutes."
    }
    public let minutes: Int
    public init?(minutes: Int) {
        guard Self.allowedMinutes.contains(minutes) else { return nil }
        self.minutes = minutes
    }
    public static let presets = [10, 15, 30, 60, 120, 360].map { CheckInterval(minutes: $0)! }
    public static let standard = CheckInterval(minutes: 30)!
    /// Other updates downloads Homebrew's full catalog, so it offers longer choices.
    public static let catalogPresets = [30, 60, 120, 240, 720, 1440].map { CheckInterval(minutes: $0)! }
    public static let catalogStandard = CheckInterval(minutes: 60)!
    /// A manual refresh skips the catalog when it is newer than Homebrew's own API cache lifetime.
    public static let manualCatalogFreshness: TimeInterval = 600
    public var label: String {
        minutes % 60 == 0 ? (minutes == 60 ? "1 hour" : "\(minutes / 60) hours") : "\(minutes) minutes"
    }
    private enum CodingKeys: String, CodingKey { case minutes }
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let minutes = try container.decode(Int.self, forKey: .minutes)
        guard let interval = Self(minutes: minutes) else {
            throw DecodingError.dataCorruptedError(forKey: .minutes, in: container, debugDescription: "Invalid check interval")
        }
        self = interval
    }
}

public enum CheckSchedule {
    public static func nextDue(lastCheck: Date?, interval: CheckInterval) -> Date? {
        lastCheck?.addingTimeInterval(TimeInterval(interval.minutes * 60))
    }
    public static func isDue(lastCheck: Date?, interval: CheckInterval, now: Date) -> Bool {
        nextDue(lastCheck: lastCheck, interval: interval).map { $0 <= now } ?? true
    }
}
