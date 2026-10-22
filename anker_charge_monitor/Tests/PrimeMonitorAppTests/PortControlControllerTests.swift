import Foundation
import Testing
import PrimeMonitorCore
@testable import PrimeMonitor

/// Synthetic switch detail: only the reported switches, no faults or identities.
func switchDetails(_ switches: [PortSwitch: Bool]) -> ChargerDetails {
    ChargerDetails(faultBits: nil, identitySupport: nil, identities: [:], rawFields: [:], switches: switches)
}
let otherCharger = ChargerInfo(serial: "synthetic-other-charger", model: "A2345", alias: "", name: "Synthetic Prime")

@MainActor extension ControllerRig {
    /// Connected with a fresh reading, so port controls are available.
    func ready() async { await start(); await reply() }
    func switchSnapshot(_ target: PortSwitch, _ on: Bool) -> ChargerSnapshot {
        ChargerSnapshot(receivedAt: clock.date, readings: [], details: switchDetails([target: on]))
    }
    /// Delivers a reply reporting the switch at the next receive position.
    @discardableResult func switchReply(_ target: PortSwitch, _ on: Bool) async -> ReceiveMark {
        let mark = backend.output.snapshot(switchSnapshot(target, on)); await settle(); return mark
    }
    func count(_ entry: String) async -> Int { await backend.log.filter { $0 == entry }.count }
    func commands() async -> [String] { await backend.switchCommands.map { "\($0.target) \($0.on ? "on" : "off")" } }
    /// Index of the first log entry at or after `start` equal to `entry`.
    func logIndex(_ entry: String, after start: Int = 0) async -> Int? {
        let log = await backend.log
        return log.indices.first { $0 >= start && log[$0] == entry }
    }
    /// A restart of `target` in its pause: off published and confirmed.
    func pausedRestart(_ target: PortSwitch = .c2) async {
        controller.restartPort(target); await settle()
        await switchReply(target, false)
    }
}

@MainActor func operationPhase(_ controller: MonitorController) -> PortOperationPhase? { controller.portOperation?.phase }

@Suite @MainActor struct PortControlSequenceTests {
    @Test func turnOffPublishesThenRequestsStatusAndConfirmsOnAFreshReport() async throws {
        let rig = try ControllerRig(); await rig.ready()
        let requests = await rig.count("request")
        #expect(rig.controller.portControlBlock == nil)
        #expect(rig.controller.turnPort(.c2, on: false))
        #expect(operationPhase(rig.controller) == .turningOff)
        await settle()
        #expect(await rig.commands() == ["c2 off"])
        #expect(await rig.count("request") == requests + 1)
        await rig.switchReply(.c2, false)
        #expect(rig.controller.portOperation == nil); #expect(rig.controller.portOutcome == nil)
        await rig.finish()
    }
    @Test func turnOnPublishesOnAndConfirms() async throws {
        let rig = try ControllerRig(); await rig.ready()
        #expect(rig.controller.turnPort(.usbA, on: true)); await settle()
        #expect(operationPhase(rig.controller) == .turningOn)
        #expect(await rig.commands() == ["usbA on"])
        await rig.switchReply(.usbA, true)
        #expect(rig.controller.portOperation == nil); #expect(rig.controller.portOutcome == nil)
        await rig.finish()
    }
    @Test func restartTurnsOffPausesFromTheConfirmingReplyThenTurnsOn() async throws {
        let rig = try ControllerRig(); await rig.ready()
        #expect(rig.controller.restartPort(.c3)); await settle()
        #expect(await rig.commands() == ["c3 off"])
        let confirmedAt = rig.clock.date
        await rig.switchReply(.c3, false)
        #expect(operationPhase(rig.controller) == .paused(until: confirmedAt.addingTimeInterval(PortControlPolicy.restartPause)))
        await rig.clock.advance(4)
        #expect(await rig.commands() == ["c3 off"])
        let requests = await rig.count("request")
        await rig.clock.advance(1)
        #expect(await rig.commands() == ["c3 off", "c3 on"])
        #expect(operationPhase(rig.controller) == .turningOn)
        #expect(await rig.count("request") == requests + 1)
        await rig.switchReply(.c3, true)
        #expect(rig.controller.portOperation == nil); #expect(rig.controller.portOutcome == nil)
        await rig.finish()
    }
    @Test func operationStatusRequestsRunBesideAnInFlightPoll() async throws {
        let rig = try ControllerRig(); await rig.ready()
        await rig.backend.blockRequest()
        rig.controller.refreshNow(); await settle()
        let requests = await rig.count("request")
        rig.controller.turnPort(.c1, on: false); await settle()
        // The poll is still held, yet the operation's request was published.
        #expect(await rig.count("request") == requests + 1)
        await rig.backend.releaseRequest(); await settle()
        await rig.switchReply(.c1, false)
        #expect(rig.controller.portOperation == nil)
        await rig.finish()
    }
    @Test func operationStatusRequestsCountTowardStaleness() async throws {
        let rig = try ControllerRig(); await rig.ready()
        rig.controller.turnPort(.c1, on: false); await settle()
        // Unanswered operation requests are missed replies, as polls are.
        await rig.clock.advance(PortControlPolicy.confirmationDeadline + 1)
        #expect(rig.controller.isStale)
        await rig.finish()
    }
}

@Suite @MainActor struct PortControlExclusionTests {
    @Test func operationsCarryTheChargerLabelShownAtStart() async throws {
        #expect(appCharger.label == "Desk"); #expect(otherCharger.label == "Synthetic Prime")
        let rig = try ControllerRig(); await rig.ready()
        rig.controller.turnPort(.c1, on: true)
        #expect(rig.controller.portOperation?.context.chargerLabel == "Desk")
        #expect(rig.controller.portOperation?.context.charger == appCharger.serial)
        await rig.finish()
    }
    @Test func oneOperationAtATimeIncludingTheActiveTarget() async throws {
        let rig = try ControllerRig(); await rig.ready()
        #expect(rig.controller.restartPort(.c2)); await settle()
        #expect(rig.controller.portControlBlock == .anotherPortChanging)
        #expect(!rig.controller.turnPort(.c1, on: false))
        #expect(!rig.controller.restartPort(.c2))
        #expect(!rig.controller.turnPort(.c2, on: true))
        #expect(await rig.commands() == ["c2 off"])
        await rig.finish()
    }
    @Test func controlsAreUnavailableWhileDisconnectedOrStale() async throws {
        let stale = try ControllerRig(); await stale.start()
        #expect(stale.controller.portControlBlock == .stale)
        #expect(!stale.controller.turnPort(.c1, on: true))
        await stale.finish()
        let offline = try ControllerRig(); await offline.ready()
        await offline.events.send(.network(false))
        #expect(offline.controller.portControlBlock == .disconnected)
        #expect(!offline.controller.restartPort(.c1))
        #expect(await stale.commands().isEmpty); #expect(await offline.commands().isEmpty)
        await offline.finish()
    }
}

@Suite @MainActor struct PortOutcomeTests {
    @Test func unconfirmedPhasesFinishWithTheirOutcome() async throws {
        let rig = try ControllerRig(); await rig.ready()
        rig.controller.turnPort(.c2, on: false); await settle()
        await rig.clock.advance(PortControlPolicy.confirmationDeadline)
        #expect(rig.controller.portOperation == nil)
        #expect(rig.controller.portOutcome?.kind == .offNotConfirmed)
        #expect(rig.controller.portOutcome?.context.chargerLabel == "Desk")
        rig.controller.dismissPortOutcome(); #expect(rig.controller.portOutcome == nil)
        await rig.reply()
        rig.controller.turnPort(.c4, on: true); await settle()
        await rig.switchReply(.c4, false)
        await rig.clock.advance(PortControlPolicy.confirmationDeadline)
        #expect(rig.controller.portOutcome?.kind == .stillOff)
        await rig.reply()
        // A new operation clears the previous outcome.
        rig.controller.turnPort(.c4, on: true); await settle()
        #expect(rig.controller.portOutcome == nil)
        await rig.clock.advance(PortControlPolicy.confirmationDeadline)
        #expect(rig.controller.portOutcome?.kind == .onNotConfirmed)
        await rig.finish()
    }
    @Test func freshMatchingEvidenceFromItsOwnContextClearsAnOutcome() async throws {
        let rig = try ControllerRig(); await rig.ready()
        rig.controller.turnPort(.c2, on: false); await settle()
        await rig.clock.advance(PortControlPolicy.confirmationDeadline)
        #expect(rig.controller.portOutcome?.kind == .offNotConfirmed)
        await rig.switchReply(.c2, true); #expect(rig.controller.portOutcome != nil)
        await rig.switchReply(.c3, false); #expect(rig.controller.portOutcome != nil)
        await rig.switchReply(.c2, false); #expect(rig.controller.portOutcome == nil)
        await rig.finish()
    }
    @Test func failedPublishTakesAFenceBeforeAcceptingClearingEvidence() async throws {
        let rig = try ControllerRig(); await rig.ready()
        await rig.backend.failSwitchWrites()
        rig.controller.turnPort(.c2, on: false); await settle()
        #expect(rig.controller.portOutcome?.kind == .offNotConfirmed)
        #expect(await rig.count("fence") == 1)
        #expect(rig.controller.portOutcome?.boundary == rig.backend.output.fence)
        await rig.switchReply(.c2, false); #expect(rig.controller.portOutcome == nil)
        await rig.finish()
    }
    @Test func outcomeSurvivesContextChangesAndClearsOnlyInItsOwnContext() async throws {
        let rig = try ControllerRig(); await rig.ready()
        rig.controller.turnPort(.c2, on: false); await settle()
        await rig.clock.advance(PortControlPolicy.confirmationDeadline)
        let outcome = try #require(rig.controller.portOutcome)
        await rig.controller.select(otherCharger); await settle()
        #expect(rig.controller.portOutcome == outcome)
        // Evidence from the newly selected charger never clears it.
        await rig.switchReply(.c2, false); #expect(rig.controller.portOutcome == outcome)
        await rig.controller.signIn(appCredentials); await settle()
        #expect(rig.controller.portOutcome == outcome)
        await rig.controller.signOut()
        #expect(rig.controller.portOutcome == outcome)
        rig.controller.dismissPortOutcome(); #expect(rig.controller.portOutcome == nil)
        await rig.finish()
    }
    /// A restart whose off phase is never confirmed must not leave the port off.
    @Test func restartWithAnUnconfirmedOffStillTurnsOn() async throws {
        let rig = try ControllerRig(); await rig.ready()
        rig.controller.restartPort(.c2); await settle()
        await rig.clock.advance(PortControlPolicy.confirmationDeadline)
        #expect(await rig.commands() == ["c2 off", "c2 on"])
        #expect(operationPhase(rig.controller) == .turningOn)
        #expect(rig.controller.portOutcome == nil)
        await rig.switchReply(.c2, true)
        #expect(rig.controller.portOperation == nil)
        let outcome = try #require(rig.controller.portOutcome)
        #expect(outcome.kind == .offNotConfirmed && outcome.operation == .restart && outcome.wantedOn)
        // An off report never clears it; a later on report does.
        await rig.switchReply(.c2, false); #expect(rig.controller.portOutcome == outcome)
        await rig.switchReply(.c2, true); #expect(rig.controller.portOutcome == nil)
        await rig.finish()
    }
    @Test func reconnectionReplacesTheOutcomeBoundaryBeforeClearing() async throws {
        let rig = try ControllerRig(); await rig.ready()
        rig.controller.turnPort(.c2, on: false); await settle()
        await rig.clock.advance(PortControlPolicy.confirmationDeadline)
        let before = try #require(rig.controller.portOutcome?.boundary)
        await rig.events.send(.sleep); await rig.events.send(.wake); await settle()
        let after = try #require(rig.controller.portOutcome?.boundary)
        #expect(after.connection != before.connection)
        #expect(after == rig.backend.output.fence)
        await rig.switchReply(.c2, false); #expect(rig.controller.portOutcome == nil)
        await rig.finish()
    }
}

@Suite @MainActor struct PortInterruptionTests {
    @Test func sleepDuringTurningOffResumesConfirmationWithoutResending() async throws {
        let rig = try ControllerRig(); await rig.ready()
        rig.controller.restartPort(.c2); await settle()
        await rig.events.send(.sleep)
        #expect(rig.controller.portOperation?.isSuspended == true)
        await rig.clock.advance(30)
        #expect(rig.controller.portOutcome == nil)
        let requests = await rig.count("request")
        await rig.events.send(.wake); await settle()
        #expect(rig.controller.portOperation?.isSuspended == false)
        #expect(await rig.count("fence") == 1)
        #expect(await rig.commands() == ["c2 off"])
        #expect(await rig.count("request") >= requests + 1)
        await rig.switchReply(.c2, false)
        if case .paused = operationPhase(rig.controller) {} else { Issue.record("Expected the pause") }
        await rig.finish()
    }
    @Test func pausedRestartKeepsItsOriginalEndAcrossReconnection() async throws {
        let rig = try ControllerRig(); await rig.ready()
        await rig.pausedRestart()
        let end = try #require(rig.controller.portOperation?.pauseEnd)
        await rig.clock.advance(2); await rig.events.send(.sleep)
        await rig.clock.advance(5)
        #expect(await rig.commands() == ["c2 off"])
        await rig.events.send(.wake); await settle()
        #expect(rig.clock.date > end)
        #expect(await rig.commands() == ["c2 off", "c2 on"])
        #expect(operationPhase(rig.controller) == .turningOn)
        await rig.switchReply(.c2, true); #expect(rig.controller.portOperation == nil)
        await rig.finish()
    }
    @Test func turningOnResendsOnAfterReconnection() async throws {
        let rig = try ControllerRig(); await rig.ready()
        await rig.pausedRestart(); await rig.clock.advance(PortControlPolicy.restartPause)
        #expect(await rig.commands() == ["c2 off", "c2 on"])
        await rig.events.send(.network(false)); await rig.events.send(.network(true)); await settle()
        #expect(await rig.commands() == ["c2 off", "c2 on", "c2 on"])
        await rig.switchReply(.c2, true)
        #expect(rig.controller.portOperation == nil); #expect(rig.controller.portOutcome == nil)
        await rig.finish()
    }
    @Test func backendLinkDropSuspendsAndResumesFromAFence() async throws {
        let rig = try ControllerRig(); await rig.ready()
        rig.controller.turnPort(.c1, on: false); await settle()
        rig.backend.output.yield(.status(.error("dropped"))); await settle()
        #expect(rig.controller.portOperation?.isSuspended == true)
        rig.backend.output.yield(.status(.connected)); await settle()
        #expect(rig.controller.portOperation?.isSuspended == false)
        #expect(await rig.count("fence") == 1); #expect(await rig.commands() == ["c1 off"])
        await rig.switchReply(.c1, false); #expect(rig.controller.portOperation == nil)
        await rig.finish()
    }
    @Test func terminalAuthenticationEndsARestartWithoutPublishing() async throws {
        for terminal in [ConnectionStatus.sessionEnded, .signInFailed("Invalid credentials"), .verificationRequired] {
            let rig = try ControllerRig(); await rig.ready()
            await rig.pausedRestart()
            rig.backend.output.yield(.status(terminal)); await settle()
            #expect(rig.controller.portOperation == nil)
            #expect(rig.controller.portOutcome?.kind == .mayStillBeOff)
            #expect(await rig.commands() == ["c2 off"])
            await rig.finish()
        }
    }
    @Test func credentialEditEndsSynchronouslyAndRestoresBeforeDisconnecting() async throws {
        let rig = try ControllerRig(); await rig.ready()
        await rig.pausedRestart()
        let start = await rig.backend.log.count
        rig.controller.setCredentialSelection(CredentialSelection(provider: "synthetic", settings: ["account": "edited"]))
        // Acceptance ends before any await.
        #expect(rig.controller.portOperation == nil)
        #expect(rig.controller.portOutcome?.kind == .mayStillBeOff)
        #expect(rig.controller.portControlBlock != nil)
        await settle()
        #expect(await rig.commands() == ["c2 off", "c2 on"])
        let restore = try #require(await rig.logIndex("switch", after: start))
        let disconnect = try #require(await rig.logIndex("disconnect", after: start))
        #expect(restore < disconnect)
        await rig.finish()
    }
    @Test func authenticationReplacementRestoresAgainstTheOldContextFirst() async throws {
        for path in ["retry", "reauthenticate"] {
            let rig = try ControllerRig(); await rig.ready()
            await rig.pausedRestart()
            let start = await rig.backend.log.count
            switch path {
            case "retry": await rig.controller.connect(using: CredentialSelection(provider: "synthetic", settings: [:]))
            default: await rig.controller.signIn(appCredentials)
            }
            await settle()
            #expect(rig.controller.portOutcome?.kind == .mayStillBeOff)
            #expect(await rig.commands() == ["c2 off", "c2 on"])
            let restore = try #require(await rig.logIndex("switch", after: start))
            let disconnect = try #require(await rig.logIndex("disconnect", after: start))
            #expect(restore < disconnect)
            #expect(await rig.backend.switchChargers.allSatisfy { $0 == appCharger.serial })
            await rig.finish()
        }
    }
    @Test func reloadingTheSameSelectionEndsTheOperation() async throws {
        let rig = try ControllerRig(configured: false), store = MemorySessionStore(), provider = SyntheticProvider()
        let selection = CredentialSelection(provider: "synthetic", settings: ["account": "first"])
        let state = StateStore(fileURL: rig.directory.appending(path: "state.json"))
        try state.save(.init(charger: appCharger, closedInterval: .m1, credentials: selection))
        let controller = MonitorController(backend: rig.backend, secrets: store, state: state, events: SystemEvents(sources: [rig.events]), now: { rig.clock.date }, scheduler: rig.clock, makeProvider: { _ in provider })
        controller.start(); await rig.events.send(.network(true)); await settle()
        rig.backend.output.snapshot(.init(receivedAt: rig.clock.date, readings: [])); await settle()
        #expect(controller.restartPort(.c2)); await settle()
        await rig.switchReply(.c2, false)
        let start = await rig.backend.log.count
        await controller.connect(using: selection, reload: true); await settle()
        #expect(controller.portOperation == nil)
        #expect(controller.portOutcome?.kind == .mayStillBeOff)
        let restore = try #require(await rig.logIndex("switch", after: start))
        let disconnect = try #require(await rig.logIndex("disconnect", after: start))
        #expect(restore < disconnect)
        #expect(await rig.logIndex("connect", after: disconnect) != nil)
        await controller.stop(); await rig.finish()
    }
    @Test func plainTurnOffIsNotReversedBySignOut() async throws {
        let rig = try ControllerRig(); await rig.ready()
        rig.controller.turnPort(.c2, on: false); await settle()
        await rig.controller.signOut()
        #expect(await rig.commands() == ["c2 off"])
        #expect(rig.controller.portOutcome?.kind == .offNotConfirmed)
        await rig.finish()
    }
}

@Suite @MainActor struct PortFreshnessTests {
    @Test func publishResultClosedByADisconnectIsIgnored() async throws {
        let rig = try ControllerRig(); await rig.ready()
        await rig.backend.blockSwitches()
        rig.controller.turnPort(.c2, on: false); await settle()
        // Disconnect closes the held write; its failure belongs to the old connection.
        await rig.events.send(.sleep); await settle()
        #expect(rig.controller.portOutcome == nil)
        #expect(rig.controller.portOperation?.isSuspended == true)
        await rig.events.send(.wake); await settle()
        await rig.switchReply(.c2, false)
        #expect(rig.controller.portOperation == nil); #expect(rig.controller.portOutcome == nil)
        await rig.backend.releaseSwitches(); await rig.finish()
    }
    @Test func queuedPreCommandSnapshotCannotConfirm() async throws {
        let rig = try ControllerRig(); await rig.ready()
        let queued = rig.backend.output.fence
        rig.controller.turnPort(.c2, on: false); await settle()
        rig.backend.output.yield(.snapshot(rig.switchSnapshot(.c2, false), queued)); await settle()
        #expect(operationPhase(rig.controller) == .turningOff)
        await rig.switchReply(.c2, false)
        #expect(rig.controller.portOperation == nil)
        await rig.finish()
    }
    @Test func replyBeforePublishCompletionCannotConfirm() async throws {
        let rig = try ControllerRig(); await rig.ready()
        await rig.backend.blockSwitches()
        rig.controller.turnPort(.c2, on: false); await settle()
        await rig.switchReply(.c2, false)
        #expect(operationPhase(rig.controller) == .turningOff)
        await rig.backend.releaseSwitches(); await settle()
        #expect(operationPhase(rig.controller) == .turningOff)
        await rig.switchReply(.c2, false)
        #expect(rig.controller.portOperation == nil)
        await rig.finish()
    }
    @Test func priorPhaseReplyCannotDecideTheOnPhase() async throws {
        let rig = try ControllerRig(); await rig.ready()
        await rig.pausedRestart(); await rig.clock.advance(PortControlPolicy.restartPause)
        #expect(operationPhase(rig.controller) == .turningOn)
        // An off report the backend received before the on write completed.
        rig.backend.output.yield(.snapshot(rig.switchSnapshot(.c2, false), rig.backend.output.fence)); await settle()
        await rig.clock.advance(PortControlPolicy.confirmationDeadline)
        #expect(rig.controller.portOutcome?.kind == .onNotConfirmed)
        await rig.finish()
    }
}

@Suite @MainActor struct PortEndingTests {
    @Test func overlappingEndingsShareOneAttemptAndConnectOnlyTheLatestSelection() async throws {
        let rig = try ControllerRig(); await rig.ready()
        await rig.pausedRestart(); await rig.backend.blockSwitches()
        let a = ChargerInfo(serial: "synthetic-A", model: "A2345", alias: "A", name: "Prime")
        let b = ChargerInfo(serial: "synthetic-B", model: "A2345", alias: "B", name: "Prime")
        let first = Task { await rig.controller.select(a) }; await settle()
        let second = Task { await rig.controller.select(b) }; await settle()
        #expect(await rig.commands() == ["c2 off", "c2 on"])
        #expect(await rig.backend.heldSwitchWrites == 1)
        #expect(await rig.count("connect") == 1)
        await rig.clock.advance(PortControlPolicy.exitAttemptTimeout)
        await first.value; await second.value; await settle()
        #expect(await rig.count("abort") == 1)
        #expect(await rig.backend.connectedChargers.last == b)
        #expect(await !rig.backend.connectedChargers.contains(a))
        #expect(rig.controller.portOutcome?.kind == .mayStillBeOff)
        #expect(rig.controller.portOutcome?.context.chargerLabel == "Desk")
        await rig.finish()
    }
    @Test func olderCompletionAfterReplacementSelectionNeverReachesTheReplacement() async throws {
        let rig = try ControllerRig(); await rig.ready()
        await rig.backend.blockSwitches()
        rig.controller.restartPort(.c2); await settle()
        let start = await rig.backend.log.count
        let selecting = Task { await rig.controller.select(otherCharger) }; await settle()
        #expect(await rig.count("connect") == 1)
        // The held off write completes; the ending write follows it on the old link.
        await rig.backend.releaseSwitches(); await selecting.value; await settle()
        #expect(await rig.commands() == ["c2 off", "c2 on"])
        #expect(await rig.backend.switchChargers.allSatisfy { $0 == appCharger.serial })
        let lastSwitch = try #require(await rig.backend.log.lastIndex(of: "switch"))
        let replacement = try #require(await rig.logIndex("connect", after: start))
        #expect(lastSwitch < replacement)
        #expect(await rig.backend.connectedChargers.last == otherCharger)
        #expect(await rig.count("abort") == 0)
        #expect(rig.controller.portOutcome?.kind == .mayStillBeOff)
        await rig.finish()
    }
    @Test func writeHeldPastItsBudgetAbortsEarlyAndTheReplacementWaitsForTheDrain() async throws {
        let rig = try ControllerRig(); await rig.ready()
        await rig.backend.blockSwitches()
        rig.controller.restartPort(.c2); await settle()
        let start = await rig.backend.log.count
        let selecting = Task { await rig.controller.select(otherCharger) }; await settle()
        let began = rig.clock.date
        await rig.clock.advance(MonitorController.portEndingWriteBudget - 0.5)
        #expect(await rig.logIndex("abort", after: start) == nil)
        #expect(await rig.logIndex("disconnect", after: start) == nil)
        #expect(await rig.count("connect") == 1)
        #expect(rig.controller.portControlBlock == .anotherPortChanging)
        await rig.clock.advance(0.5)
        // The abort starts with the reserve still left, and its drain finished within the budget.
        let abort = try #require(await rig.logIndex("abort", after: start))
        #expect(rig.clock.date.timeIntervalSince(began) == MonitorController.portEndingWriteBudget)
        #expect(MonitorController.portEndingWriteBudget < PortControlPolicy.exitAttemptTimeout)
        await selecting.value; await settle()
        let disconnect = try #require(await rig.logIndex("disconnect", after: start))
        let connect = try #require(await rig.logIndex("connect", after: start))
        #expect(abort < disconnect && disconnect < connect)
        // The ending write never followed the aborted one.
        #expect(await rig.commands() == ["c2 off"])
        #expect(await rig.backend.connectedChargers.last == otherCharger)
        await rig.finish()
    }
    @Test func abortWithoutAContextChangeReconnectsTheSameCharger() async throws {
        let rig = try ControllerRig(configured: false), store = MemorySessionStore(), provider = SyntheticProvider()
        let selection = CredentialSelection(provider: "synthetic", settings: ["account": "first"])
        let state = StateStore(fileURL: rig.directory.appending(path: "state.json"))
        try state.save(.init(charger: appCharger, closedInterval: .m1, credentials: selection))
        let controller = MonitorController(backend: rig.backend, secrets: store, state: state, events: SystemEvents(sources: [rig.events]), now: { rig.clock.date }, scheduler: rig.clock, makeProvider: { _ in provider })
        controller.start(); await rig.events.send(.network(true)); await settle()
        rig.backend.output.snapshot(.init(receivedAt: rig.clock.date, readings: [])); await settle()
        await rig.backend.blockSwitches()
        controller.restartPort(.c2); await settle()
        // Reload fails, so nothing replaces the connection the abort closes.
        await provider.fail(); await controller.connect(using: selection, reload: true)
        let start = await rig.backend.log.count
        await rig.clock.advance(PortControlPolicy.exitAttemptTimeout); await settle()
        let abort = try #require(await rig.logIndex("abort", after: start))
        let disconnect = try #require(await rig.logIndex("disconnect", after: abort))
        #expect(await rig.logIndex("connect", after: disconnect) != nil)
        #expect(await rig.backend.connectedChargers.last == appCharger)
        await controller.stop(); await rig.finish()
    }
    @Test func quitWaitsForTheBoundedEndingWrite() async throws {
        let rig = try ControllerRig(); await rig.ready()
        await rig.pausedRestart(); await rig.backend.blockSwitches()
        var ended = false
        let ending = Task { await rig.controller.endPortOperation(); ended = true }; await settle()
        #expect(await rig.commands() == ["c2 off", "c2 on"]); #expect(!ended)
        await rig.clock.advance(PortControlPolicy.exitAttemptTimeout); await ending.value
        #expect(ended); #expect(await rig.count("abort") == 1)
        await rig.finish()
    }
}

/// A backend-detected link drop reaches the controller twice: the held write throws
/// `linkClosed` and the backend reports `.error`, then `.connected` on the replacement
/// link. Either may arrive first; the operation suspends and resumes either way.
@Suite @MainActor struct PortLinkDropTests {
    private func lose(_ rig: ControllerRig) async { rig.backend.output.yield(.status(.error("dropped"))); await settle() }
    private func recover(_ rig: ControllerRig) async {
        rig.backend.output.connected(); rig.backend.output.yield(.status(.connected)); await settle()
    }
    @Test func throwBeforeTheLossStatusSuspendsThenResumesWithoutResending() async throws {
        let rig = try ControllerRig(); await rig.ready()
        await rig.backend.blockSwitches()
        rig.controller.turnPort(.c2, on: false); await settle()
        await rig.backend.dropHeldSwitches(); await settle()
        // Not a publish failure: the loss status is still on its way.
        #expect(operationPhase(rig.controller) == .turningOff); #expect(rig.controller.portOutcome == nil)
        await lose(rig)
        #expect(rig.controller.portOperation?.isSuspended == true)
        await recover(rig)
        #expect(rig.controller.portOperation?.isSuspended == false)
        #expect(await rig.commands() == ["c2 off"])
        await rig.switchReply(.c2, false)
        #expect(rig.controller.portOperation == nil); #expect(rig.controller.portOutcome == nil)
        await rig.finish()
    }
    @Test func throwBeforeTheLossStatusInTheOnPhaseResendsOnce() async throws {
        let rig = try ControllerRig(); await rig.ready()
        await rig.pausedRestart(); await rig.backend.blockSwitches()
        await rig.clock.advance(PortControlPolicy.restartPause)
        #expect(await rig.backend.heldSwitchWrites == 1)
        await rig.backend.dropHeldSwitches(); await settle()
        #expect(operationPhase(rig.controller) == .turningOn); #expect(rig.controller.portOutcome == nil)
        await lose(rig); await recover(rig)
        await rig.backend.releaseSwitches(); await settle()
        #expect(await rig.commands() == ["c2 off", "c2 on", "c2 on"])
        await rig.switchReply(.c2, true)
        #expect(rig.controller.portOperation == nil); #expect(rig.controller.portOutcome == nil)
        await rig.finish()
    }
    @Test func throwAfterTheReplacementConnectedIsObsolete() async throws {
        for restart in [false, true] {
            let rig = try ControllerRig(); await rig.ready()
            if restart { await rig.pausedRestart() }
            await rig.backend.blockSwitches()
            if restart { await rig.clock.advance(PortControlPolicy.restartPause) } else { rig.controller.turnPort(.c2, on: false); await settle() }
            let published = await rig.commands()
            await lose(rig); await recover(rig)
            // Resumed already: a restart's on phase resent once; a plain turn-off did not.
            #expect(await rig.commands().count == published.count + (restart ? 1 : 0))
            await rig.backend.dropHeldSwitches(1); await settle()
            #expect(rig.controller.portOperation?.isSuspended == false)
            #expect(rig.controller.portOutcome == nil)
            await rig.backend.releaseSwitches(); await settle()
            #expect(await rig.commands().count == published.count + (restart ? 1 : 0))
            await rig.switchReply(.c2, restart)
            #expect(rig.controller.portOperation == nil); #expect(rig.controller.portOutcome == nil)
            await rig.finish()
        }
    }
    @Test func closedLinkWithoutALossStatusFailsAtTheConfirmationDeadline() async throws {
        let rig = try ControllerRig(); await rig.ready()
        await rig.backend.blockSwitches()
        rig.controller.turnPort(.c2, on: false); await settle()
        await rig.backend.dropHeldSwitches(); await settle()
        await rig.clock.advance(PortControlPolicy.confirmationDeadline - 1)
        #expect(operationPhase(rig.controller) == .turningOff)
        await rig.clock.advance(1)
        #expect(rig.controller.portOperation == nil)
        #expect(rig.controller.portOutcome?.kind == .offNotConfirmed)
        await rig.finish()
    }
    @Test func aPublishErrorOnALiveLinkFailsAtOnce() async throws {
        let rig = try ControllerRig(); await rig.ready()
        await rig.backend.failSwitchWrites()
        rig.controller.turnPort(.c2, on: false); await settle()
        #expect(rig.controller.portOperation == nil)
        #expect(rig.controller.portOutcome?.kind == .offNotConfirmed)
        await rig.finish()
    }
    /// A restart's rejected off write moves straight to "on"; when that is rejected
    /// too, the on failure is reported.
    @Test func aRestartWhoseWritesAreRejectedStillTriesOn() async throws {
        let rig = try ControllerRig(); await rig.ready()
        await rig.backend.failSwitchWrites()
        rig.controller.restartPort(.c2); await settle()
        #expect(await rig.commands() == ["c2 off", "c2 on"])
        #expect(rig.controller.portOperation == nil)
        #expect(rig.controller.portOutcome?.kind == .onNotConfirmed)
        #expect(rig.controller.portOutcome?.wantedOn == true)
        await rig.finish()
    }
}
