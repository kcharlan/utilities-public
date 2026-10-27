import Foundation

/// Live runs notify; backfill and rebuild never do (spec section 7.3).
public enum EvalMode: String, Sendable, Hashable {
    case live, backfill
}

/// A notification to post. `id` is stable for the same transition; `threadID` groups one rule's
/// notices for one scope.
public struct PendingNotification: Sendable, Equatable, Hashable {
    public var id: String
    public var title: String
    public var body: String
    public var threadID: String

    public init(id: String, title: String, body: String, threadID: String) {
        self.id = id
        self.title = title
        self.body = body
        self.threadID = threadID
    }
}

/// Failed-turn coalescing state carried between runs in `rule_state` (`Store.failureNotices`):
/// when the last failed-turn notice went out, and the failures waiting for the next one.
public struct FailureNotices: Sendable, Equatable, Hashable, Codable {
    public var lastNoticeAt: Date?
    public var waiting: [FailedTurnRecord]

    public init(lastNoticeAt: Date? = nil, waiting: [FailedTurnRecord] = []) {
        self.lastNoticeAt = lastNoticeAt
        self.waiting = waiting
    }
}

/// Chooses the notifications for one run's outcomes (spec sections 7.2 to 7.4).
///
/// An outcome is fresh when `latestPoint − at ≤ intervalMinutes`. Fresh fires, escalations and
/// clears notify, subject to the rule's Notify and Notify-when-it-clears settings. An episode
/// that fired inside the gap and is still open at the end notifies once with its catch-up
/// wording (the latest it has); anything else stale is recorded only. Idle ends never notify.
///
/// Failed turns notify through coalescing rather than per fire: fresh failures join the waiting
/// list, which goes out as one notice when no failed-turn notice went out in the last
/// `coalesceMinutes`, otherwise at the first run after that window. A failed-turn episode that
/// fired inside the gap and is still open sends its failures with the catch-up wording.
public enum NotificationPolicy {
    public static func select(
        _ outcomes: [RuleOutcome], latestPoint: Date, intervalMinutes: Int, settings: RuleSettings, mode: EvalMode,
        failureNotices: inout FailureNotices, calendar: Calendar
    ) -> [PendingNotification] {
        guard mode == .live else { return [] }
        let freshness = TimeInterval(intervalMinutes * 60)
        func isFresh(_ outcome: RuleOutcome) -> Bool { latestPoint.timeIntervalSince(outcome.at) <= freshness }

        var ended: Set<Int64> = []
        var latestCatchUp: [Int64: String] = [:]
        var staleFires: Set<Int64> = []
        for outcome in outcomes {
            switch outcome.transition {
            case .cleared?, .idleEnded?: ended.insert(outcome.episodeID)
            case .fired?:
                if !isFresh(outcome) { staleFires.insert(outcome.episodeID) }
                fallthrough
            case .escalated?:
                if let catchUp = outcome.catchUpMessage { latestCatchUp[outcome.episodeID] = catchUp }
            case nil: break
            }
        }
        let caughtUp = staleFires.subtracting(ended)

        var notices: [PendingNotification] = []
        for outcome in outcomes where outcome.rule != .failedTurns || outcome.transition == .cleared {
            guard let transition = outcome.transition else { continue }
            let rule = settings.notifications(for: outcome.rule)
            guard rule.enabled else { continue }
            switch transition {
            case .fired:
                guard rule.notify else { continue }
                if isFresh(outcome) {
                    notices.append(notice(outcome, kind: "fired", body: outcome.message))
                } else if caughtUp.contains(outcome.episodeID) {
                    notices.append(notice(outcome, kind: "catchUp", body: latestCatchUp[outcome.episodeID] ?? outcome.message))
                }
            case .escalated:
                if rule.notify, isFresh(outcome), !caughtUp.contains(outcome.episodeID) {
                    notices.append(notice(outcome, kind: "escalated", body: outcome.message))
                }
            case .cleared:
                if rule.notifyOnClear, isFresh(outcome) { notices.append(notice(outcome, kind: "cleared", body: outcome.message)) }
            case .idleEnded:
                continue
            }
        }

        notices += failedTurnNotices(
            outcomes.filter { $0.rule == .failedTurns }, caughtUp: caughtUp, isFresh: isFresh, latestPoint: latestPoint,
            rule: settings.failedTurns, failureNotices: &failureNotices, calendar: calendar)
        return notices
    }

    private static func failedTurnNotices(
        _ outcomes: [RuleOutcome], caughtUp: Set<Int64>, isFresh: (RuleOutcome) -> Bool, latestPoint: Date,
        rule: FailedTurnRule, failureNotices: inout FailureNotices, calendar: Calendar
    ) -> [PendingNotification] {
        guard rule.enabled, rule.notify else {
            failureNotices.waiting = []
            return []
        }
        var catchUp: [FailedTurnRecord] = []
        for outcome in outcomes where !outcome.failures.isEmpty {
            if caughtUp.contains(outcome.episodeID) {
                catchUp += outcome.failures
            } else if isFresh(outcome) {
                failureNotices.waiting += outcome.failures
            }
            // Other stale failures belong to an episode that ended in the gap, or one already
            // announced: recorded only.
        }
        let all = failureNotices.waiting + catchUp
        guard !all.isEmpty else { return [] }
        let windowOver = failureNotices.lastNoticeAt.map {
            latestPoint.timeIntervalSince($0) >= TimeInterval(rule.coalesceMinutes * 60)
        } ?? true
        guard windowOver else {
            failureNotices.waiting = all
            return []
        }

        let reasons = all.map { Copy.failedTurnReason(code: $0.errorCode) }
        let body: String
        if !catchUp.isEmpty, let since = all.map(\.startedAt).min() {
            body = Copy.failedTurnsCatchUp(count: all.count, reasons: reasons, since: since, calendar: calendar)
        } else {
            body = Copy.failedTurns(count: all.count, reasons: reasons)
        }
        failureNotices = FailureNotices(lastNoticeAt: latestPoint, waiting: [])
        return [PendingNotification(
            id: "failedTurns-\(Int(latestPoint.timeIntervalSince1970))", title: RuleID.failedTurns.title, body: body,
            threadID: "failedTurns")]
    }

    private static func notice(_ outcome: RuleOutcome, kind: String, body: String) -> PendingNotification {
        PendingNotification(
            id: "\(outcome.rule.rawValue)-\(outcome.episodeID)-\(kind)", title: outcome.title, body: body,
            threadID: "\(outcome.rule.rawValue).\(outcome.provider).\(outcome.scope)")
    }
}

/// A rule's on/off and notification switches.
struct NotificationSwitches {
    var enabled: Bool
    var notify: Bool
    var notifyOnClear: Bool
}

extension RuleSettings {
    func notifications(for rule: RuleID) -> NotificationSwitches {
        switch rule {
        case .slower: NotificationSwitches(enabled: slower.enabled, notify: slower.notify, notifyOnClear: slower.notifyOnClear)
        case .faster: NotificationSwitches(enabled: faster.enabled, notify: faster.notify, notifyOnClear: faster.notifyOnClear)
        case .largePrompts: NotificationSwitches(enabled: largePrompts.enabled, notify: largePrompts.notify, notifyOnClear: largePrompts.notifyOnClear)
        case .failedTurns: NotificationSwitches(enabled: failedTurns.enabled, notify: failedTurns.notify, notifyOnClear: failedTurns.notifyOnClear)
        case .disconnects: NotificationSwitches(enabled: disconnects.enabled, notify: disconnects.notify, notifyOnClear: disconnects.notifyOnClear)
        case .incident: NotificationSwitches(enabled: incident.enabled, notify: incident.notify, notifyOnClear: incident.notifyOnClear)
        case .usageLimit: NotificationSwitches(enabled: usageLimit.enabled, notify: usageLimit.notify, notifyOnClear: usageLimit.notifyOnClear)
        }
    }
}
