import Foundation

public enum ClosedInterval: Int, CaseIterable, Codable, Sendable {
    case s30 = 30, m1 = 60, m2 = 120, m5 = 300
    public static let `default`: ClosedInterval = .m1
}

public enum PollPolicy {
    public static let openInterval: TimeInterval = 5
    public static let replyDeadline: TimeInterval = 10

    public static func interval(panelOpen: Bool, closed: ClosedInterval, asleep: Bool) -> TimeInterval? {
        guard !asleep else { return nil }
        return panelOpen ? openInterval : TimeInterval(closed.rawValue)
    }
}
