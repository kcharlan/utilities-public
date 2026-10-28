import Foundation

/// A lamp's color, ordered by spec section 7.4's severity order (red, amber, blue): the most
/// severe compares greatest, so `max()` picks the color a lamp shows.
public enum LampColor: String, Sendable, Hashable, Codable, CaseIterable, Comparable {
    case red, amber, blue

    private var rank: Int {
        switch self {
        case .red: 2
        case .amber: 1
        case .blue: 0
        }
    }

    public static func < (lhs: LampColor, rhs: LampColor) -> Bool { lhs.rank < rhs.rank }
}

/// A condition at one evaluation point: true, false, or unknown (thin data, cold start, or no
/// sample). Unknown neither advances nor resets anything (spec section 7.1).
public enum Tri: String, Sendable, Hashable, Codable {
    case `true`, `false`, unknown

    public init(_ value: Bool?) {
        switch value {
        case true?: self = .true
        case false?: self = .false
        case nil: self = .unknown
        }
    }
}

public enum Transition: Sendable, Equatable, Hashable {
    /// The condition held for the rule's duration. `severity` is red when the red condition held
    /// for the same duration, otherwise the machine's color.
    case fired(onset: Date, severity: LampColor)
    /// A red streak of the rule's duration arrived after an amber fire; at most once per episode.
    case escalated
    /// Inside the clear band for the clear duration.
    case cleared
    /// No qualifying activity for the idle period: the episode ends silently.
    case idleEnded
}

/// Spec sections 7.1 and 7.2's episode logic for one rule and scope, stored as JSON in
/// `rule_state`. Durations are counted in evaluation points (`EvaluationPoints.count`):
/// count-based rules use one point to fire and one to clear.
///
/// - Not open: a true trigger extends the streak (its first point dates the onset), false resets
///   it, unknown holds it. `firePoints` true points fire.
/// - Open: a true clear extends the clear streak, false resets it, unknown holds it.
///   `clearPoints` clear it. The trigger is ignored, so flapping produces one episode.
/// - A separate red streak, also `firePoints` long, sets the severity at fire or escalates once.
/// - Idle resets everything; an open episode ends with `idleEnded`.
public struct EpisodeMachine: Codable, Sendable, Equatable, Hashable {
    public var firePoints: Int
    public var clearPoints: Int
    /// Onset is the first true point minus this window (the speed index's trailing window).
    public var windowMinutes: Int
    /// The severity of a fire without a red streak: amber, or blue for "Faster than usual".
    public var color: LampColor

    public private(set) var isOpen = false
    /// The open episode's severity, nil when closed.
    public private(set) var severity: LampColor?
    private var triggerStreak = 0
    private var firstTrue: Date?
    private var redStreak = 0
    private var clearStreak = 0

    public init(firePoints: Int, clearPoints: Int, windowMinutes: Int, color: LampColor = .amber) {
        self.firePoints = max(1, firePoints)
        self.clearPoints = max(1, clearPoints)
        self.windowMinutes = windowMinutes
        self.color = color
    }

    /// Closed with no streak in progress: nothing worth storing.
    public var isAtRest: Bool { !isOpen && triggerStreak == 0 && redStreak == 0 }

    public mutating func step(at point: Date, trigger: Tri, clear: Tri, red: Tri, idle: Bool) -> [Transition] {
        if idle {
            let wasOpen = isOpen
            reset()
            return wasOpen ? [.idleEnded] : []
        }
        if isOpen {
            Self.advance(&clearStreak, clear)
            if clearStreak >= clearPoints {
                reset()
                return [.cleared]
            }
            guard severity != .red else { return [] }
            Self.advance(&redStreak, red)
            guard redStreak >= firePoints else { return [] }
            severity = .red
            return [.escalated]
        }

        switch trigger {
        case .true:
            if triggerStreak == 0 { firstTrue = point }
            triggerStreak += 1
        case .false:
            triggerStreak = 0
            firstTrue = nil
        case .unknown:
            break
        }
        Self.advance(&redStreak, trigger == .false ? .false : red)
        guard triggerStreak >= firePoints, let firstTrue else { return [] }
        let fired = redStreak >= firePoints ? LampColor.red : color
        isOpen = true
        severity = fired
        triggerStreak = 0
        self.firstTrue = nil
        clearStreak = 0
        return [.fired(onset: firstTrue.addingTimeInterval(-TimeInterval(windowMinutes * 60)), severity: fired)]
    }

    private mutating func reset() {
        isOpen = false
        severity = nil
        triggerStreak = 0
        firstTrue = nil
        redStreak = 0
        clearStreak = 0
    }

    private static func advance(_ streak: inout Int, _ value: Tri) {
        switch value {
        case .true: streak += 1
        case .false: streak = 0
        case .unknown: break
        }
    }
}
