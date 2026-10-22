import Foundation
import Testing
import PrimeMonitorCore

// Ordinary (non-@testable) import: every construction path here must compile
// against the public Core API, as the controller and UI targets use it.
// Identifiers below are synthetic.

private func at(_ seconds: TimeInterval) -> Date { Date(timeIntervalSince1970: 1_000 + seconds) }
private func mark(_ connection: UInt64, _ sequence: UInt64) -> ReceiveMark {
    ReceiveMark(connection: ConnectionEpoch(connection), sequence: sequence)
}
private func receipt(_ connection: UInt64, _ sequence: UInt64) -> PortCommandReceipt {
    PortCommandReceipt(fence: mark(connection, sequence))
}
private func report(_ target: PortSwitch, on: Bool?, receivedAt: Date) -> ChargerSnapshot {
    let switches: [PortSwitch: Bool] = on.map { [target: $0] } ?? [:]
    return ChargerSnapshot(receivedAt: receivedAt, readings: [],
                           details: ChargerDetails(faultBits: nil, identitySupport: nil, identities: [:],
                                                   rawFields: [:], switches: switches))
}

private let accountA = UUID(uuidString: "00000000-0000-0000-0000-00000000000A")!
private let accountB = UUID(uuidString: "00000000-0000-0000-0000-00000000000B")!
private let context = PortOperationContext(account: accountA, charger: "SYNTHETIC-CHARGER-1", chargerLabel: "Test Charger")

private func outcome(_ actions: [PortOperationAction]) -> PortOperationOutcome? {
    guard actions.count == 1, case .finish(let value) = actions[0] else { return nil }
    return value
}

/// A started operation whose phase publish completed at `published` with receipt (1, 10).
private func confirming(_ kind: PortOperationKind, _ target: PortSwitch = .c2,
                        published: TimeInterval = 1) -> PortOperation {
    var operation = PortOperation(kind, target: target, context: context)
    _ = operation.handle(.requested, at: at(0))
    _ = operation.handle(.published(receipt(1, 10)), at: at(published))
    return operation
}

/// A restart that confirmed off with a reply received at `confirmedAt` (pause until +5 s).
private func paused(confirmedAt: TimeInterval = 2) -> PortOperation {
    var operation = confirming(.restart)
    _ = operation.handle(.snapshot(report(.c2, on: false, receivedAt: at(confirmedAt)), mark(1, 11)), at: at(confirmedAt))
    return operation
}

/// A restart in its on phase whose "on" publish completed at 8 s with receipt (1, 20).
private func turningOnRestart() -> PortOperation {
    var operation = paused()
    _ = operation.handle(.tick, at: at(7))
    _ = operation.handle(.published(receipt(1, 20)), at: at(8))
    return operation
}

// MARK: - Policy

@Test func policyValuesMatchThePlanDeclaration() {
    #expect(PortControlPolicy.restartPause == 5)
    #expect(PortControlPolicy.confirmationInterval == 1)
    #expect(PortControlPolicy.confirmationDeadline == PollPolicy.replyDeadline)
    #expect(PortControlPolicy.confirmationWindow == 5)
    #expect(PortControlPolicy.exitAttemptTimeout == 3)
}

// MARK: - Success sequences

@Test(arguments: [(PortOperationKind.turnOff, false), (.turnOn, true)])
func plainOperationPublishesRequestsAndConfirms(kind: PortOperationKind, wanted: Bool) throws {
    var operation = PortOperation(kind, target: .usbA, context: context)
    #expect(operation.phase == .idle)
    #expect(operation.handle(.requested, at: at(0)) == [.publish(.usbA, on: wanted)])
    #expect(operation.phase == (wanted ? .turningOn : .turningOff))
    #expect(operation.handle(.published(receipt(1, 10)), at: at(1)) == [.requestStatus])
    let result = try #require(outcome(operation.handle(
        .snapshot(report(.usbA, on: wanted, receivedAt: at(1.5)), mark(1, 12)), at: at(1.5))))
    #expect(result == PortOperationOutcome(context: context, operation: kind, target: .usbA, wantedOn: wanted,
                                           kind: .confirmed, boundary: mark(1, 12)))
    #expect(operation.phase == .finished(result))
    #expect(operation.outcome == result && operation.isFinished)
}

@Test func restartTurnsOffPausesFromTheConfirmingReplyThenTurnsOn() throws {
    var operation = PortOperation(.restart, target: .c3, context: context)
    #expect(operation.handle(.requested, at: at(0)) == [.publish(.c3, on: false)])
    #expect(operation.phase == .turningOff)
    #expect(operation.handle(.published(receipt(1, 10)), at: at(1)) == [.requestStatus])
    // Reply received at 1.5 s, delivered at 1.9 s: the pause counts from the reply.
    #expect(operation.handle(.snapshot(report(.c3, on: false, receivedAt: at(1.5)), mark(1, 11)), at: at(1.9)) == [])
    #expect(operation.phase == .paused(until: at(6.5)))
    #expect(operation.pauseEnd == at(6.5))
    #expect(operation.pauseSecondsRemaining(at: at(1.9)) == 5)
    #expect(operation.pauseSecondsRemaining(at: at(5.7)) == 1)
    #expect(operation.nextDue == at(6.5))
    #expect(operation.handle(.tick, at: at(6.4)) == [])
    #expect(operation.handle(.tick, at: at(6.5)) == [.publish(.c3, on: true)])
    #expect(operation.phase == .turningOn && operation.pauseEnd == nil)
    #expect(operation.handle(.published(receipt(1, 20)), at: at(8)) == [.requestStatus])
    let result = try #require(outcome(operation.handle(
        .snapshot(report(.c3, on: true, receivedAt: at(8.5)), mark(1, 21)), at: at(8.5))))
    #expect(result.kind == .confirmed && result.wantedOn && result.operation == .restart)
    #expect(result.boundary == mark(1, 21) && result.target == .c3 && result.context == context)
}

@Test func confirmedOffAfterThePauseAlreadyElapsedTurnsOnImmediately() {
    var operation = confirming(.restart)
    // Delivered 5.5 s after it was received: the overdue status request comes first.
    let actions = operation.handle(.snapshot(report(.c2, on: false, receivedAt: at(2)), mark(1, 11)), at: at(7.5))
    #expect(actions == [.requestStatus, .publish(.c2, on: true)])
    #expect(operation.phase == .turningOn)
}

// MARK: - Status requests and deadline

@Test func statusRequestsRepeatEveryIntervalUntilTheDeadlineFromPublishCompletion() throws {
    var operation = confirming(.turnOff, published: 1)
    #expect(operation.nextDue == at(2))
    #expect(operation.handle(.tick, at: at(1.5)) == [])
    #expect(operation.handle(.tick, at: at(2)) == [.requestStatus])
    #expect(operation.handle(.tick, at: at(2.5)) == [])
    for second in 3...10 {
        #expect(operation.handle(.tick, at: at(TimeInterval(second))) == [.requestStatus])
    }
    #expect(operation.nextDue == at(11))
    let result = try #require(outcome(operation.handle(.tick, at: at(11))))
    #expect(result.kind == .offNotConfirmed && result.wantedOn == false)
    #expect(result.boundary == mark(1, 10))
    #expect(operation.handle(.tick, at: at(12)).isEmpty)
}

@Test func deadlineChoosesTheFailureFromTheLatestFreshReport() throws {
    // On phase with a fresh off report: still off.
    var stillOff = confirming(.turnOn)
    #expect(stillOff.handle(.snapshot(report(.c2, on: false, receivedAt: at(1.5)), mark(1, 11)), at: at(1.5)) == [])
    #expect(stillOff.latestFreshReport == false)
    #expect(try #require(outcome(stillOff.handle(.tick, at: at(11)))).kind == .stillOff)

    // No fresh report at all: couldn't confirm.
    var silent = confirming(.turnOn)
    #expect(try #require(outcome(silent.handle(.tick, at: at(11)))).kind == .onNotConfirmed)

    // Off reports that are not fresh do not count.
    var stale = confirming(.turnOn)
    _ = stale.handle(.snapshot(report(.c2, on: false, receivedAt: at(2)), mark(1, 10)), at: at(2))
    _ = stale.handle(.snapshot(report(.c2, on: false, receivedAt: at(2)), mark(2, 99)), at: at(2))
    _ = stale.handle(.snapshot(report(.c2, on: false, receivedAt: at(0.5)), mark(1, 12)), at: at(2))
    #expect(stale.latestFreshReport == nil)
    #expect(try #require(outcome(stale.handle(.tick, at: at(11)))).kind == .onNotConfirmed)

    // A restart's on phase uses the same rule.
    var restart = turningOnRestart()
    _ = restart.handle(.snapshot(report(.c2, on: false, receivedAt: at(9)), mark(1, 21)), at: at(9))
    let result = try #require(outcome(restart.handle(.tick, at: at(18))))
    #expect(result.kind == .stillOff && result.wantedOn && result.operation == .restart)

    // An off phase reports couldn't confirm even after a fresh on report.
    var off = confirming(.turnOff)
    _ = off.handle(.snapshot(report(.c2, on: true, receivedAt: at(2)), mark(1, 11)), at: at(2))
    #expect(off.latestFreshReport == true)
    #expect(try #require(outcome(off.handle(.tick, at: at(11)))).kind == .offNotConfirmed)
}

@Test func timeIsAppliedBeforeTheEventItArrivesWith() throws {
    var operation = confirming(.turnOff)
    let result = try #require(outcome(operation.handle(
        .snapshot(report(.c2, on: false, receivedAt: at(11)), mark(1, 30)), at: at(11))))
    #expect(result.kind == .offNotConfirmed)
}

// MARK: - Confirmation freshness

@Test func onlyFreshMatchingReportsConfirm() throws {
    var operation = confirming(.turnOff, published: 1)
    let rejected: [(ChargerSnapshot, ReceiveMark)] = [
        (report(.c2, on: false, receivedAt: at(1.5)), mark(2, 50)),   // other connection
        (report(.c2, on: false, receivedAt: at(1.5)), mark(1, 10)),   // not past the fence
        (report(.c2, on: false, receivedAt: at(1.5)), mark(1, 9)),    // before the fence
        (report(.c2, on: false, receivedAt: at(0.9)), mark(1, 11)), // before the status request
        (report(.c2, on: true, receivedAt: at(1.5)), mark(1, 12)),    // fresh but not the wanted value
        (report(.c2, on: nil, receivedAt: at(1.5)), mark(1, 13)),     // switch not reported
        (report(.c3, on: false, receivedAt: at(1.5)), mark(1, 14)),   // another target
        (ChargerSnapshot(receivedAt: at(1.5), readings: []), mark(1, 15)) // no details
    ]
    for (snapshot, mark) in rejected {
        #expect(operation.handle(.snapshot(snapshot, mark), at: at(1.5)) == [])
        #expect(operation.phase == .turningOff)
    }
    // A fresh mismatching report is remembered, never an early failure.
    #expect(operation.latestFreshReport == true)
    // Receive time equal to the request start, past the fence, matching: confirms.
    let result = try #require(outcome(operation.handle(
        .snapshot(report(.c2, on: false, receivedAt: at(1)), mark(1, 16)), at: at(1.5))))
    #expect(result.kind == .confirmed && result.boundary == mark(1, 16))
}

@Test func repliesBeforePublishCompletionCannotConfirm() throws {
    var operation = PortOperation(.turnOff, target: .c1, context: context)
    _ = operation.handle(.requested, at: at(0))
    // Matching report with a large sequence while the publish is still in flight.
    #expect(operation.handle(.snapshot(report(.c1, on: false, receivedAt: at(0.5)), mark(1, 40)), at: at(0.5)) == [])
    #expect(operation.phase == .turningOff && operation.latestFreshReport == nil)
    #expect(operation.nextDue == nil)
    #expect(operation.handle(.tick, at: at(60)) == [])
    #expect(operation.handle(.published(receipt(1, 40)), at: at(61)) == [.requestStatus])
    // Its replay (same mark) is not newer than the receipt, nor received after the request.
    #expect(operation.handle(.snapshot(report(.c1, on: false, receivedAt: at(0.5)), mark(1, 40)), at: at(61)) == [])
    let result = try #require(outcome(operation.handle(
        .snapshot(report(.c1, on: false, receivedAt: at(61.2)), mark(1, 41)), at: at(61.2))))
    #expect(result.kind == .confirmed)
}

@Test func priorPhaseEvidenceCannotConfirmTheOnPhase() throws {
    var operation = paused()
    _ = operation.handle(.tick, at: at(7))
    // On-phase publish in flight: an "on" reply from before cannot confirm.
    #expect(operation.handle(.snapshot(report(.c2, on: true, receivedAt: at(7.5)), mark(1, 15)), at: at(7.5)) == [])
    _ = operation.handle(.published(receipt(1, 20)), at: at(8))
    // Past the off phase's fence but not the on phase's: ignored.
    #expect(operation.handle(.snapshot(report(.c2, on: true, receivedAt: at(8.5)), mark(1, 19)), at: at(8.5)) == [])
    // Received before this phase's status request: ignored.
    #expect(operation.handle(.snapshot(report(.c2, on: true, receivedAt: at(7.9)), mark(1, 21)), at: at(8.5)) == [])
    #expect(operation.phase == .turningOn)
    let result = try #require(outcome(operation.handle(
        .snapshot(report(.c2, on: true, receivedAt: at(8.6)), mark(1, 22)), at: at(8.6))))
    #expect(result.kind == .confirmed)
}

// MARK: - Publish failure

@Test func publishFailureFinishesWithThePhaseFailure() throws {
    var off = PortOperation(.turnOff, target: .c4, context: context)
    _ = off.handle(.requested, at: at(0))
    let offResult = try #require(outcome(off.handle(.publishFailed, at: at(1))))
    #expect(offResult.kind == .offNotConfirmed && !offResult.wantedOn && offResult.boundary == nil)

    var on = PortOperation(.turnOn, target: .c4, context: context)
    _ = on.handle(.requested, at: at(0))
    #expect(try #require(outcome(on.handle(.publishFailed, at: at(1)))).kind == .onNotConfirmed)

    var restartOff = PortOperation(.restart, target: .c4, context: context)
    _ = restartOff.handle(.requested, at: at(0))
    let restartOffResult = try #require(outcome(restartOff.handle(.publishFailed, at: at(1))))
    #expect(restartOffResult.kind == .offNotConfirmed && restartOffResult.operation == .restart)

    // A restart's on phase failing to publish after a confirmed off: couldn't confirm on,
    // keeping the off confirmation as its boundary.
    var restartOn = paused()
    _ = restartOn.handle(.tick, at: at(7))
    let restartOnResult = try #require(outcome(restartOn.handle(.publishFailed, at: at(7.5))))
    #expect(restartOnResult.kind == .onNotConfirmed && restartOnResult.wantedOn)
    #expect(restartOnResult.boundary == mark(1, 11))
}

@Test func publishResultsWithoutAPublishInFlightAreIgnored() {
    var operation = confirming(.turnOff)
    #expect(operation.handle(.publishFailed, at: at(1.5)) == [])
    #expect(operation.handle(.published(receipt(1, 30)), at: at(1.5)) == [])
    #expect(operation.phase == .turningOff)
    var waiting = paused()
    #expect(waiting.handle(.publishFailed, at: at(3)) == [])
    #expect(waiting.handle(.published(receipt(1, 30)), at: at(3)) == [])
    #expect(waiting.phase == .paused(until: at(7)))
}

// MARK: - Interruptions

@Test func disconnectionSuspendsEverything() {
    var operation = confirming(.turnOff)
    #expect(operation.handle(.disconnected, at: at(1.5)) == [])
    #expect(operation.isSuspended && operation.nextDue == nil)
    #expect(operation.handle(.tick, at: at(30)) == [])
    #expect(operation.handle(.snapshot(report(.c2, on: false, receivedAt: at(31)), mark(1, 40)), at: at(31)) == [])
    #expect(operation.phase == .turningOff)

    // A publish outstanding at disconnection: its late result is ignored.
    var inFlight = PortOperation(.turnOn, target: .c1, context: context)
    _ = inFlight.handle(.requested, at: at(0))
    _ = inFlight.handle(.disconnected, at: at(0.5))
    #expect(inFlight.handle(.published(receipt(1, 5)), at: at(0.6)) == [])
    #expect(inFlight.handle(.publishFailed, at: at(0.7)) == [])
    #expect(inFlight.phase == .turningOn && inFlight.isSuspended)

    // A paused restart does not turn on while suspended.
    var waiting = paused()
    _ = waiting.handle(.disconnected, at: at(3))
    #expect(waiting.handle(.tick, at: at(8)) == [])
    #expect(waiting.phase == .paused(until: at(7)))
}

@Test(arguments: [PortOperationKind.turnOff, .turnOn, .restart])
func reconnectionInAConfirmingPhaseRequestsStatusWithTheReplacementFence(kind: PortOperationKind) throws {
    // turnOn's phase is "turning on"; restart's and turnOff's are "turning off".
    var operation = confirming(kind)
    _ = operation.handle(.disconnected, at: at(5))
    #expect(operation.handle(.reconnected(receipt(2, 30)), at: at(40)) == [.requestStatus])
    #expect(!operation.isSuspended)
    let wanted = kind == .turnOn
    // Old-connection evidence and replies received before the resumed request: ignored.
    #expect(operation.handle(.snapshot(report(.c2, on: wanted, receivedAt: at(40.5)), mark(1, 40)), at: at(40.5)) == [])
    #expect(operation.handle(.snapshot(report(.c2, on: wanted, receivedAt: at(39)), mark(2, 31)), at: at(40.5)) == [])
    #expect(operation.handle(.snapshot(report(.c2, on: wanted, receivedAt: at(40.5)), mark(2, 30)), at: at(40.5)) == [])
    // Fresh deadline from the replacement fence.
    #expect(operation.handle(.tick, at: at(41)) == [.requestStatus])
    #expect(operation.nextDue == at(42))
    if kind == .restart {
        #expect(operation.handle(.snapshot(report(.c2, on: false, receivedAt: at(41.5)), mark(2, 32)), at: at(41.5)) == [])
        #expect(operation.phase == .paused(until: at(46.5)))
    } else {
        let result = try #require(outcome(operation.handle(
            .snapshot(report(.c2, on: wanted, receivedAt: at(41.5)), mark(2, 32)), at: at(41.5))))
        #expect(result.kind == .confirmed && result.boundary == mark(2, 32))
    }
}

@Test func resumedConfirmationGetsAFreshDeadline() throws {
    var operation = confirming(.turnOff, published: 1)
    _ = operation.handle(.disconnected, at: at(5))
    _ = operation.handle(.reconnected(receipt(2, 30)), at: at(40))
    #expect(operation.handle(.tick, at: at(49)) == [.requestStatus])
    let result = try #require(outcome(operation.handle(.tick, at: at(50))))
    #expect(result.kind == .offNotConfirmed && result.boundary == mark(2, 30))
}

@Test func reconnectionDropsFreshReportsFromTheOldConnection() throws {
    var operation = confirming(.turnOn)
    _ = operation.handle(.snapshot(report(.c2, on: false, receivedAt: at(2)), mark(1, 11)), at: at(2))
    #expect(operation.latestFreshReport == false)
    _ = operation.handle(.disconnected, at: at(3))
    _ = operation.handle(.reconnected(receipt(2, 30)), at: at(4))
    #expect(operation.latestFreshReport == nil)
    #expect(try #require(outcome(operation.handle(.tick, at: at(14)))).kind == .onNotConfirmed)
}

@Test func turningOffInterruptedBeforePublishCompletionResumesWithoutResending() {
    var operation = PortOperation(.restart, target: .c1, context: context)
    _ = operation.handle(.requested, at: at(0))
    _ = operation.handle(.disconnected, at: at(0.5))
    #expect(operation.handle(.reconnected(receipt(2, 3)), at: at(9)) == [.requestStatus])
    #expect(operation.phase == .turningOff)
}

@Test func pausedRestartKeepsItsOriginalEndAcrossReconnection() {
    var early = paused()
    _ = early.handle(.disconnected, at: at(3))
    #expect(early.handle(.reconnected(receipt(2, 30)), at: at(5)) == [])
    #expect(early.phase == .paused(until: at(7)))
    #expect(early.handle(.tick, at: at(7)) == [.publish(.c2, on: true)])

    var late = paused()
    _ = late.handle(.disconnected, at: at(3))
    #expect(late.handle(.reconnected(receipt(2, 30)), at: at(20)) == [.publish(.c2, on: true)])
    #expect(late.phase == .turningOn)
}

@Test func restartTurningOnResendsOnAndTakesTheNewReceipt() throws {
    var operation = turningOnRestart()
    _ = operation.handle(.disconnected, at: at(9))
    #expect(operation.handle(.reconnected(receipt(2, 30)), at: at(20)) == [.publish(.c2, on: true)])
    // Before the resend completes, nothing confirms, not even fresh-connection replies.
    #expect(operation.handle(.snapshot(report(.c2, on: true, receivedAt: at(20.5)), mark(2, 31)), at: at(20.5)) == [])
    #expect(operation.handle(.published(receipt(2, 31)), at: at(21)) == [.requestStatus])
    #expect(operation.handle(.snapshot(report(.c2, on: true, receivedAt: at(21.5)), mark(2, 31)), at: at(21.5)) == [])
    let result = try #require(outcome(operation.handle(
        .snapshot(report(.c2, on: true, receivedAt: at(21.5)), mark(2, 32)), at: at(21.5))))
    #expect(result.kind == .confirmed)
}

@Test func outcomesAfterReconnectionCarryTheReplacementFence() throws {
    var operation = paused()
    _ = operation.handle(.disconnected, at: at(3))
    #expect(operation.handle(.reconnected(receipt(2, 30)), at: at(20)) == [.publish(.c2, on: true)])
    let result = try #require(outcome(operation.handle(.publishFailed, at: at(21))))
    #expect(result.kind == .onNotConfirmed && result.boundary == mark(2, 30))
    #expect(result.isCleared(by: report(.c2, on: true, receivedAt: at(22)), mark: mark(2, 31), in: context))
}

@Test func plainTurnOnResumesConfirmationOnlyEvenWithAPublishInFlight() {
    var operation = PortOperation(.turnOn, target: .c1, context: context)
    _ = operation.handle(.requested, at: at(0))
    _ = operation.handle(.disconnected, at: at(0.5))
    #expect(operation.handle(.reconnected(receipt(2, 3)), at: at(9)) == [.requestStatus])
}

// MARK: - Ending

@Test(arguments: PortOperationEndingReason.allCases.filter { $0 != .terminalAuthentication })
func endingARestartInAnyPhaseAttemptsOnThenReportsMayStillBeOff(reason: PortOperationEndingReason) throws {
    var operations: [(PortOperation, Date)] = []
    var publishing = PortOperation(.restart, target: .c1, context: context)
    _ = publishing.handle(.requested, at: at(0))
    operations.append((publishing, at(0.5)))
    var confirmingOff = PortOperation(.restart, target: .c1, context: context)
    _ = confirmingOff.handle(.requested, at: at(0))
    _ = confirmingOff.handle(.published(receipt(1, 10)), at: at(1))
    operations.append((confirmingOff, at(1.5)))
    var waiting = confirmingOff
    _ = waiting.handle(.snapshot(report(.c1, on: false, receivedAt: at(2)), mark(1, 11)), at: at(2))
    operations.append((waiting, at(2.5)))
    var on = waiting
    _ = on.handle(.tick, at: at(7))
    operations.append((on, at(7.5)))
    _ = on.handle(.published(receipt(1, 20)), at: at(8))
    operations.append((on, at(8.5)))

    for (start, now) in operations {
        var operation = start
        let actions = operation.handle(.ending(reason), at: now)
        #expect(actions.count == 2)
        #expect(actions.first == .endingPublish(.c1, on: true))
        guard case .finish(let result) = actions.last else { Issue.record("no finish"); continue }
        #expect(result.kind == .mayStillBeOff && result.wantedOn && result.operation == .restart)
        #expect(operation.outcome == result)
        #expect(operation.handle(.published(receipt(1, 30)), at: now + 0.1) == [])
        #expect(operation.handle(.snapshot(report(.c1, on: true, receivedAt: now), mark(1, 31)), at: now + 0.1) == [])
    }
}

@Test func terminalAuthenticationEndsARestartWithoutPublishing() throws {
    var operation = paused()
    let result = try #require(outcome(operation.handle(.ending(.terminalAuthentication), at: at(3))))
    #expect(result.kind == .mayStillBeOff)
}

@Test func endingASuspendedRestartDoesNotPublish() throws {
    var operation = paused()
    _ = operation.handle(.disconnected, at: at(3))
    let result = try #require(outcome(operation.handle(.ending(.quit), at: at(4))))
    #expect(result.kind == .mayStillBeOff)
}

@Test(arguments: PortOperationEndingReason.allCases)
func endingAPlainOperationIsNotReversed(reason: PortOperationEndingReason) throws {
    var off = confirming(.turnOff)
    #expect(try #require(outcome(off.handle(.ending(reason), at: at(1.5)))).kind == .offNotConfirmed)

    var on = confirming(.turnOn)
    #expect(try #require(outcome(on.handle(.ending(reason), at: at(1.5)))).kind == .onNotConfirmed)

    var stillOff = confirming(.turnOn)
    _ = stillOff.handle(.snapshot(report(.c2, on: false, receivedAt: at(1.5)), mark(1, 11)), at: at(1.5))
    #expect(try #require(outcome(stillOff.handle(.ending(reason), at: at(1.8)))).kind == .stillOff)
}

@Test func endingReasonsCoverThePlan() {
    #expect(Set(PortOperationEndingReason.allCases) == [
        .quit, .signOut, .chargerChange, .credentialSelectionEdit, .authenticationReplacement, .terminalAuthentication
    ])
}

// MARK: - Lifecycle

@Test func eventsBeforeTheRequestAndAfterTheFinishAreIgnored() throws {
    var idle = PortOperation(.restart, target: .c1, context: context)
    for event: PortOperationEvent in [.published(receipt(1, 1)), .publishFailed, .tick, .disconnected,
                                      .reconnected(receipt(1, 1)), .ending(.quit),
                                      .snapshot(report(.c1, on: false, receivedAt: at(1)), mark(1, 2))] {
        #expect(idle.handle(event, at: at(1)) == [])
    }
    #expect(idle.phase == .idle && !idle.isSuspended)

    var done = confirming(.turnOff)
    let result = try #require(outcome(done.handle(.snapshot(report(.c2, on: false, receivedAt: at(1.5)), mark(1, 11)), at: at(1.5))))
    for event: PortOperationEvent in [.requested, .published(receipt(1, 1)), .publishFailed, .tick, .disconnected,
                                      .reconnected(receipt(1, 1)), .ending(.quit)] {
        #expect(done.handle(event, at: at(30)) == [])
    }
    #expect(done.phase == .finished(result))

    var twice = PortOperation(.turnOn, target: .c1, context: context)
    _ = twice.handle(.requested, at: at(0))
    #expect(twice.handle(.requested, at: at(0.1)) == [])
}

@Test func inspectionExposesKindTargetContextAndWantedState() {
    let operation = PortOperation(.restart, target: .usbA, context: context)
    #expect(operation.kind == .restart && operation.target == .usbA && operation.context == context)
    #expect(PortOperationKind.turnOff.wantedOn == false)
    #expect(PortOperationKind.turnOn.wantedOn && PortOperationKind.restart.wantedOn)
    #expect(operation.pauseEnd == nil && operation.pauseSecondsRemaining(at: at(0)) == nil)
}

// MARK: - Outcome clearing

@Test func matchingFreshEvidenceFromTheOutcomesOwnContextClearsIt() {
    let failed = PortOperationOutcome(context: context, operation: .restart, target: .c1, wantedOn: true,
                                      kind: .mayStillBeOff, boundary: mark(1, 20))
    let on = report(.c1, on: true, receivedAt: at(5))
    #expect(failed.isCleared(by: on, mark: mark(1, 21), in: context))
    // The charger label is presentation only: a renamed charger still matches.
    let renamed = PortOperationContext(account: accountA, charger: "SYNTHETIC-CHARGER-1", chargerLabel: "Renamed")
    #expect(failed.isCleared(by: on, mark: mark(1, 21), in: renamed))
    #expect(!failed.isCleared(by: on, mark: mark(1, 20), in: context))
    #expect(!failed.isCleared(by: on, mark: mark(2, 99), in: context))
    #expect(!failed.isCleared(by: report(.c1, on: false, receivedAt: at(5)), mark: mark(1, 21), in: context))
    #expect(!failed.isCleared(by: report(.c1, on: nil, receivedAt: at(5)), mark: mark(1, 21), in: context))
    #expect(!failed.isCleared(by: report(.c2, on: true, receivedAt: at(5)), mark: mark(1, 21), in: context))
    let otherAccount = PortOperationContext(account: accountB, charger: "SYNTHETIC-CHARGER-1", chargerLabel: "Test Charger")
    let otherCharger = PortOperationContext(account: accountA, charger: "SYNTHETIC-CHARGER-2", chargerLabel: "Test Charger")
    #expect(!failed.isCleared(by: on, mark: mark(1, 21), in: otherAccount))
    #expect(!failed.isCleared(by: on, mark: mark(1, 21), in: otherCharger))

    let off = PortOperationOutcome(context: context, operation: .turnOff, target: .c1, wantedOn: false,
                                   kind: .offNotConfirmed, boundary: mark(1, 20))
    #expect(off.isCleared(by: report(.c1, on: false, receivedAt: at(5)), mark: mark(1, 21), in: context))
}

@Test func anOutcomeAcquiresAReplacementBoundaryOnlyInItsOwnContext() {
    var outcome = PortOperationOutcome(context: context, operation: .turnOn, target: .c1, wantedOn: true,
                                       kind: .onNotConfirmed, boundary: nil)
    let on = report(.c1, on: true, receivedAt: at(5))
    #expect(!outcome.isCleared(by: on, mark: mark(1, 21), in: context))
    let otherAccount = PortOperationContext(account: accountB, charger: "SYNTHETIC-CHARGER-1", chargerLabel: "Test Charger")
    let rejected = outcome.replaceBoundary(with: receipt(3, 40), in: otherAccount)
    #expect(!rejected)
    #expect(outcome.boundary == nil)
    let replaced = outcome.replaceBoundary(with: receipt(3, 40), in: context)
    #expect(replaced)
    #expect(outcome.boundary == mark(3, 40))
    #expect(!outcome.isCleared(by: on, mark: mark(1, 41), in: context))
    #expect(!outcome.isCleared(by: on, mark: mark(3, 40), in: context))
    #expect(outcome.isCleared(by: on, mark: mark(3, 41), in: context))
}

@Test func contextsMatchOnAccountAndChargerOnly() {
    let renamed = PortOperationContext(account: accountA, charger: "SYNTHETIC-CHARGER-1", chargerLabel: "Renamed")
    #expect(context.isSameOrigin(as: renamed) && context != renamed)
    #expect(!context.isSameOrigin(as: PortOperationContext(account: accountB, charger: "SYNTHETIC-CHARGER-1", chargerLabel: "Test Charger")))
}
