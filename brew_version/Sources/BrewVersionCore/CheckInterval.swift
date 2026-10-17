import Foundation

public struct CheckInterval: Codable, Hashable, Sendable {
    public let minutes: Int
    public init?(minutes: Int) {
        guard (10...1440).contains(minutes) else { return nil }
        self.minutes = minutes
    }
    public static let presets = [10, 15, 30, 60, 120, 360].map { CheckInterval(minutes: $0)! }
    public static let standard = CheckInterval(minutes: 30)!
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
