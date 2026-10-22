import Foundation

public enum PortControlPolicy {
    /// Time a restart holds the port off, counted from the reply confirming off.
    public static let restartPause: TimeInterval = 5
    /// Gap between confirmation requests; favors feedback over normal cadence.
    /// This is a request interval, not a bound on device or network latency.
    public static let confirmationInterval: TimeInterval = 1
    /// How long a switch change may go unconfirmed before it is reported.
    /// Reuses the app's existing "reply is late" threshold.
    public static let confirmationDeadline: TimeInterval = PollPolicy.replyDeadline
    /// Expiry for the confirming click; bounds how long an armed action remains.
    public static let confirmationWindow: TimeInterval = 5
    /// Budget for the ending attempt, including cancellation and draining.
    /// Bounds added lifecycle delay; does not guarantee power restoration.
    public static let exitAttemptTimeout: TimeInterval = 3
}

public enum PortOperationKind: CaseIterable, Hashable, Sendable {
    case turnOff, turnOn, restart

    /// The switch state the operation leaves the target in when it succeeds.
    public var wantedOn: Bool { self != .turnOff }
}

/// The account and charger an operation or outcome belongs to. `account` and
/// `charger` identify the origin; `chargerLabel` is the label shown when the
/// operation started, kept for presentation after the selection changes.
public struct PortOperationContext: Hashable, Sendable {
    /// The controller's account generation when the operation started.
    public let account: UUID
    /// The charger's identifier (its serial).
    public let charger: String
    public let chargerLabel: String

    public init(account: UUID, charger: String, chargerLabel: String) {
        self.account = account
        self.charger = charger
        self.chargerLabel = chargerLabel
    }

    /// Same account and charger; the label is presentation only.
    public func isSameOrigin(as other: PortOperationContext) -> Bool {
        account == other.account && charger == other.charger
    }
}

/// Context changes that end an operation ("Interrupted operations"). Every reason
/// except `terminalAuthentication` attempts "on" when it ends a restart.
public enum PortOperationEndingReason: CaseIterable, Hashable, Sendable {
    case quit
    case signOut
    case chargerChange
    case credentialSelectionEdit
    /// Retry, Reload Credentials or Sign In Again.
    case authenticationReplacement
    /// Session ended, sign-in failed or verification required: publishing is not
    /// possible, so the operation ends without an ending write.
    case terminalAuthentication
}

public enum PortOperationOutcomeKind: Hashable, Sendable {
    /// The final switch change was confirmed by fresh evidence.
    case confirmed
    /// An off phase (plain or restart) failed to confirm.
    case offNotConfirmed
    /// An on phase failed after a fresh report of the target still off.
    case stillOff
    /// An on phase failed without a fresh off report.
    case onNotConfirmed
    /// A restart ended under the interruption rules without confirmed restoration.
    case mayStillBeOff
}

/// The result of a finished operation. It blocks no action; it is cleared by a
/// new operation, by dismissal, or by `isCleared(by:mark:in:)` evidence.
public struct PortOperationOutcome: Hashable, Sendable {
    public let context: PortOperationContext
    public let operation: PortOperationKind
    public let target: PortSwitch
    /// The switch state that clears the outcome: on for every restart outcome (a
    /// restart is never resolved by the port reporting off) and for the plain turn-on
    /// outcomes; off for the plain turn-off outcomes.
    public let wantedOn: Bool
    public let kind: PortOperationOutcomeKind
    /// Clearing evidence must be newer than this on the same connection. It is the
    /// latest receipt, replacement fence or confirming reply the operation saw; nil
    /// when no publish completed, so nothing clears the outcome until a boundary is
    /// supplied through `replaceBoundary(with:in:)`.
    public private(set) var boundary: ReceiveMark?

    public init(context: PortOperationContext, operation: PortOperationKind, target: PortSwitch,
                wantedOn: Bool, kind: PortOperationOutcomeKind, boundary: ReceiveMark?) {
        self.context = context
        self.operation = operation
        self.target = target
        self.wantedOn = wantedOn
        self.kind = kind
        self.boundary = boundary
    }

    /// Whether a delivered snapshot is matching fresh evidence from this outcome's own
    /// account and charger: same origin, a mark past the boundary on its connection,
    /// and the target reporting the wanted state.
    public func isCleared(by snapshot: ChargerSnapshot, mark: ReceiveMark, in context: PortOperationContext) -> Bool {
        guard self.context.isSameOrigin(as: context), let boundary,
              mark.connection == boundary.connection, mark.sequence > boundary.sequence else { return false }
        return snapshot.details?.switches[target] == wantedOn
    }

    /// After a reconnect in this outcome's context, take the replacement connection's
    /// fence (`ChargerBackend.commandFence()`) before accepting clearing evidence.
    /// Returns false, changing nothing, for another context.
    @discardableResult
    public mutating func replaceBoundary(with receipt: PortCommandReceipt, in context: PortOperationContext) -> Bool {
        guard self.context.isSameOrigin(as: context) else { return false }
        boundary = receipt.fence
        return true
    }
}

/// Identifies one `publish` action of an operation; its result reports the same value.
public struct PortPublishID: Hashable, Sendable {
    public let value: UInt64
    public init(_ value: UInt64) { self.value = value }
}

public enum PortOperationPhase: Hashable, Sendable {
    /// Created, not yet requested.
    case idle
    case turningOff
    /// A restart holding the port off; the on phase begins at this time.
    case paused(until: Date)
    case turningOn
    case finished(PortOperationOutcome)
}

public enum PortOperationEvent: Equatable, Sendable {
    /// Start the operation: publishes its first phase.
    case requested
    /// The `publish` action with this id completed with this receipt. Only the result
    /// of the latest publish counts; others (superseded by a resend, or outstanding at
    /// `disconnected`) are ignored.
    case published(PortCommandReceipt, id: PortPublishID)
    /// The `publish` action with this id threw. A thrown publish is "not confirmed
    /// published", not "not transmitted". Ignored under the same rule as `published`.
    case publishFailed(id: PortPublishID)
    /// A delivered status reply with the backend's receive mark.
    case snapshot(ChargerSnapshot, ReceiveMark)
    case tick
    /// The connection was lost (sleep, network loss): publishing is suspended.
    case disconnected
    /// Reconnected in the same process; the receipt is the replacement connection's
    /// fence from `ChargerBackend.commandFence()`. Send it only after `disconnected`.
    case reconnected(PortCommandReceipt)
    case ending(PortOperationEndingReason)
}

/// Work the controller executes. The state machine schedules nothing.
public enum PortOperationAction: Hashable, Sendable {
    /// Publish a switch command and report `published` or `publishFailed` with this id.
    case publish(PortSwitch, on: Bool, id: PortPublishID)
    /// The bounded ending write ("Bounded ending"). The operation has already
    /// finished; its completion is not reported back and never claims restored power.
    case endingPublish(PortSwitch, on: Bool)
    /// Request a status reply now, independently of normal polling.
    case requestStatus
    case finish(PortOperationOutcome)
}

/// One port switch operation: a clock-free state machine driven by events, each
/// carrying the current time. Every event first applies the passage of time, as
/// `tick` does (confirmation deadline, restart pause end, repeated status
/// requests), then the event itself; `disconnected` and `ending` apply only an
/// expired confirmation deadline first, so they never start a phase publish.
/// Events before `requested` and after the finish are ignored. One operation per
/// instance; exclusion across ports belongs to the owner.
///
/// Confirmation freshness: a phase accepts evidence only after its publish
/// completed (or, when resumed after reconnection, from its replacement fence).
/// A snapshot then confirms the phase only when its mark is on the receipt's
/// connection with a greater sequence, its `receivedAt` is not earlier than the
/// phase's status request, and the target reports the wanted state. A fresh report
/// of another state never fails a phase early; the latest one picks the failure at
/// the deadline. Replies buffered before the command pass the fence and the receive
/// time alike (protocol reference §7), so only the reported value limits them.
public struct PortOperation: Hashable, Sendable {
    private struct Confirmation: Hashable, Sendable {
        let receipt: PortCommandReceipt
        let requestStart: Date
        let deadline: Date
        var nextRequest: Date
        var latestFresh: Bool?
    }

    public let kind: PortOperationKind
    public let target: PortSwitch
    public let context: PortOperationContext
    public private(set) var phase: PortOperationPhase = .idle
    /// Disconnected: no actions until `reconnected`; the confirmation deadline does
    /// not run, and a paused restart turns on only after reconnection.
    public private(set) var isSuspended = false
    private var publishCount: UInt64 = 0
    private var outstanding: PortPublishID?
    private var confirmation: Confirmation?
    private var boundary: ReceiveMark?

    public init(_ kind: PortOperationKind, target: PortSwitch, context: PortOperationContext) {
        self.kind = kind
        self.target = target
        self.context = context
    }

    public var outcome: PortOperationOutcome? {
        if case .finished(let outcome) = phase { outcome } else { nil }
    }

    public var isFinished: Bool { outcome != nil }

    /// The current phase's latest fresh, non-matching switch report, if any.
    public var latestFreshReport: Bool? { confirmation?.latestFresh }

    public var pauseEnd: Date? {
        if case .paused(let until) = phase { until } else { nil }
    }

    /// Whole seconds until a paused restart turns on, rounded up; nil when not paused.
    public func pauseSecondsRemaining(at now: Date) -> Int? {
        pauseEnd.map { Int(max(0, $0.timeIntervalSince(now)).rounded(.up)) }
    }

    /// The earliest time a tick can produce actions; nil when only an event can.
    public var nextDue: Date? {
        guard !isSuspended else { return nil }
        if let pauseEnd { return pauseEnd }
        return confirmation.map { min($0.nextRequest, $0.deadline) }
    }

    public mutating func handle(_ event: PortOperationEvent, at now: Date) -> [PortOperationAction] {
        switch phase {
        case .idle:
            guard case .requested = event else { return [] }
            return enter(kind == .turnOn ? .turningOn : .turningOff)
        case .finished:
            return []
        case .turningOff, .paused, .turningOn:
            break
        }
        let lifecycle: Bool
        switch event {
        case .disconnected, .ending: lifecycle = true
        default: lifecycle = false
        }
        var actions = lifecycle ? expireDeadline(at: now) : advance(to: now)
        guard !isFinished else { return actions }
        switch event {
        case .requested, .tick:
            break
        case .published(let receipt, let id):
            guard outstanding == id else { break }
            outstanding = nil
            actions += beginConfirmation(receipt, at: now)
        case .publishFailed(let id):
            guard outstanding == id else { break }
            outstanding = nil
            actions.append(finish(failure))
        case .snapshot(let snapshot, let mark):
            actions += accept(snapshot, mark, at: now)
        case .disconnected:
            isSuspended = true
            outstanding = nil
        case .reconnected(let receipt):
            isSuspended = false
            outstanding = nil
            actions += resume(receipt, at: now)
        case .ending(let reason):
            if kind == .restart {
                if reason != .terminalAuthentication, !isSuspended { actions.append(.endingPublish(target, on: true)) }
                actions.append(finish(.mayStillBeOff))
            } else {
                actions.append(finish(failure))
            }
        }
        return actions
    }

    private var wantedInPhase: Bool { phase == .turningOn }

    private var failure: PortOperationOutcomeKind {
        if phase == .turningOff { return .offNotConfirmed }
        return confirmation?.latestFresh == false ? .stillOff : .onNotConfirmed
    }

    private mutating func enter(_ next: PortOperationPhase) -> [PortOperationAction] {
        phase = next
        confirmation = nil
        publishCount += 1
        let id = PortPublishID(publishCount)
        outstanding = id
        return [.publish(target, on: next == .turningOn, id: id)]
    }

    private mutating func beginConfirmation(_ receipt: PortCommandReceipt, at now: Date) -> [PortOperationAction] {
        boundary = receipt.fence
        confirmation = Confirmation(receipt: receipt, requestStart: now,
                                    deadline: now.addingTimeInterval(PortControlPolicy.confirmationDeadline),
                                    nextRequest: now.addingTimeInterval(PortControlPolicy.confirmationInterval))
        return [.requestStatus]
    }

    private mutating func expireDeadline(at now: Date) -> [PortOperationAction] {
        guard !isSuspended, let current = confirmation, now >= current.deadline else { return [] }
        return [finish(failure)]
    }

    private mutating func advance(to now: Date) -> [PortOperationAction] {
        guard !isSuspended else { return [] }
        if let pauseEnd {
            return now >= pauseEnd ? enter(.turningOn) : []
        }
        guard let current = confirmation else { return [] }
        if now >= current.deadline { return [finish(failure)] }
        guard now >= current.nextRequest else { return [] }
        confirmation?.nextRequest = now.addingTimeInterval(PortControlPolicy.confirmationInterval)
        return [.requestStatus]
    }

    private mutating func accept(_ snapshot: ChargerSnapshot, _ mark: ReceiveMark, at now: Date) -> [PortOperationAction] {
        guard !isSuspended, let current = confirmation,
              mark.connection == current.receipt.fence.connection,
              mark.sequence > current.receipt.fence.sequence,
              snapshot.receivedAt >= current.requestStart,
              let reported = snapshot.details?.switches[target] else { return [] }
        guard reported == wantedInPhase else {
            confirmation?.latestFresh = reported
            return []
        }
        boundary = mark
        guard kind == .restart, phase == .turningOff else { return [finish(.confirmed)] }
        confirmation = nil
        phase = .paused(until: snapshot.receivedAt.addingTimeInterval(PortControlPolicy.restartPause))
        return advance(to: now)
    }

    private mutating func resume(_ fence: PortCommandReceipt, at now: Date) -> [PortOperationAction] {
        boundary = fence.fence
        switch phase {
        case .paused:
            return advance(to: now)
        case .turningOn where kind == .restart:
            return enter(.turningOn)
        case .turningOff, .turningOn:
            return beginConfirmation(fence, at: now)
        case .idle, .finished:
            return []
        }
    }

    private mutating func finish(_ outcomeKind: PortOperationOutcomeKind) -> PortOperationAction {
        // Every outcome is about the operation's final state: the plain turn-off kinds
        // are off; plain turn-on and every restart outcome, off-phase failure included,
        // are on, so a port left off never clears a restart's outcome.
        let outcome = PortOperationOutcome(context: context, operation: kind, target: target, wantedOn: kind.wantedOn,
                                           kind: outcomeKind, boundary: boundary)
        phase = .finished(outcome)
        confirmation = nil
        outstanding = nil
        return .finish(outcome)
    }
}
