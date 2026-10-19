import Foundation

public struct StalenessTracker: Sendable {
    private struct AgeGrace: Sendable {
        let previousLimit: TimeInterval
        let deadline: Date
    }

    private var closed: ClosedInterval
    private var pendingDeadlines: [Date] = []
    private var finalizedMisses = 0
    private var ageGraces: [AgeGrace] = []

    public init(closed: ClosedInterval) { self.closed = closed }

    /// Call with chronological event times from the scheduler's clock.
    public mutating func requestSent(at: Date) {
        settleDeadlines(at: at)
        pendingDeadlines.append(at.addingTimeInterval(PollPolicy.replyDeadline))
    }

    /// A status reply refreshes the whole snapshot, satisfying all outstanding
    /// status requests. Other MQTT messages must not call this method.
    public mutating func replyReceived(at: Date) {
        pendingDeadlines.removeAll(keepingCapacity: true)
        finalizedMisses = 0
        ageGraces.removeAll(keepingCapacity: true)
    }

    /// The caller also sends an immediate request at this time. Preserve the
    /// previous age limit only through that request's deadline, so an existing
    /// age warning or two missed replies remain visible during grace.
    public mutating func setClosedInterval(_ closed: ClosedInterval, at: Date) {
        settleDeadlines(at: at)
        if closed.rawValue < self.closed.rawValue {
            ageGraces.append(AgeGrace(previousLimit: ageLimit,
                                      deadline: at.addingTimeInterval(PollPolicy.replyDeadline)))
        }
        self.closed = closed
        let currentLimit = ageLimit
        ageGraces.removeAll { $0.previousLimit <= currentLimit }
    }

    public func isStale(snapshotAt: Date?, now: Date) -> Bool {
        guard let snapshotAt else { return true }
        let misses = pendingDeadlines.reduce(finalizedMisses) { count, deadline in
            min(2, count + (deadline <= now ? 1 : 0))
        }
        if misses >= 2 { return true }
        let effectiveAgeLimit = ageGraces.reduce(ageLimit) { limit, grace in
            grace.deadline > now ? max(limit, grace.previousLimit) : limit
        }
        return now.timeIntervalSince(snapshotAt) > effectiveAgeLimit
    }

    private var ageLimit: TimeInterval { 2 * TimeInterval(closed.rawValue) + PollPolicy.replyDeadline }

    private mutating func settleDeadlines(at: Date) {
        for deadline in pendingDeadlines where deadline <= at {
            finalizedMisses = min(2, finalizedMisses + 1)
        }
        pendingDeadlines.removeAll { $0 <= at }
        ageGraces.removeAll { $0.deadline <= at }
    }
}
