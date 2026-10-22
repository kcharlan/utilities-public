import AppKit
import Testing
import PrimeMonitorCore
@testable import PrimeMonitor

@Suite @MainActor struct AppDelegateTests {
    @Test func rejectedConcurrentLaunchDoesNotStartControllerOrShowWindow() async throws {
        let rig = try ControllerRig()
        var reported = false, shown = false
        let delegate = AppDelegate(controller: rig.controller, acquireLease: { throw AppInstanceGateError.alreadyRunning }, show: { shown = true }, reportFailure: { _ in reported = true })
        delegate.applicationDidFinishLaunching(Notification(name: NSApplication.didFinishLaunchingNotification))
        await delegate.startupTask?.value
        #expect(reported); #expect(!shown)
        #expect(await rig.backend.log.isEmpty); #expect(rig.events.handler == nil)
        await rig.finish()
    }
    @Test func terminationWaitsForBackendCleanup() async throws {
        let rig = try ControllerRig(); var released = false, replies = 0
        let delegate = AppDelegate(controller: rig.controller, acquireLease: { AppInstanceLease { released = true } }, statusFactory: { RetainedStatusStub() }, reply: { _ in #expect(released); replies += 1 })
        delegate.applicationDidFinishLaunching(Notification(name: NSApplication.didFinishLaunchingNotification)); await delegate.startupTask?.value
        await rig.backend.blockDisconnection()
        #expect(delegate.applicationShouldTerminate(NSApplication.shared) == .terminateLater)
        #expect(delegate.applicationShouldTerminate(NSApplication.shared) == .terminateLater)
        await settle(); #expect(!released); #expect(replies == 0)
        await rig.backend.releaseDisconnection(); await delegate.terminationTask?.value
        #expect(replies == 1); await rig.finish()
    }
    @Test func quittingSettlesAPendingNameOnceBeforeShutdown() async throws {
        let rig = try ControllerRig(); var replies = 0
        let status = RetainedStatusStub()
        let delegate = AppDelegate(controller: rig.controller, acquireLease: { AppInstanceLease {} }, statusFactory: { status }, reply: { _ in replies += 1 })
        delegate.applicationDidFinishLaunching(Notification(name: NSApplication.didFinishLaunchingNotification)); await delegate.startupTask?.value
        var repliesAtSettle: Int?
        status.onSettle = { repliesAtSettle = replies }
        #expect(delegate.applicationShouldTerminate(NSApplication.shared) == .terminateLater)
        #expect(delegate.applicationShouldTerminate(NSApplication.shared) == .terminateLater)
        // Settled synchronously, once, before shutdown replies; quitting continues.
        #expect(status.settlements == 1 && repliesAtSettle == 0)
        await delegate.terminationTask?.value
        #expect(replies == 1 && status.settlements == 1)
        await rig.finish()
    }
}

@MainActor private final class RetainedStatusStub: PopoverPresenting {
    var openings = 0
    var settlements = 0
    var onSettle: () -> Void = {}
    func showPopover() { openings += 1 }
    func settlePendingEdits() { settlements += 1; onSettle() }
}
extension AppDelegateTests {
    @Test func launchRetainsStatusItemAndReopenUsesIt() async throws {
        let rig = try ControllerRig(configured: false)
        weak var retained: RetainedStatusStub?
        var factories = 0
        let delegate = AppDelegate(controller: rig.controller, acquireLease: { AppInstanceLease {} }, statusFactory: {
            factories += 1
            let result = RetainedStatusStub(); retained = result; return result
        })
        delegate.applicationDidFinishLaunching(Notification(name: NSApplication.didFinishLaunchingNotification))
        await delegate.startupTask?.value
        #expect(retained != nil && factories == 1)
        #expect(retained?.openings == 0)
        #expect(delegate.applicationShouldHandleReopen(NSApplication.shared, hasVisibleWindows: false))
        #expect(retained?.openings == 1 && factories == 1)
        await rig.finish()
    }
}
extension AppDelegateTests {
    private enum RestartPhase: CaseIterable { case turningOff, paused, turningOn }
    /// Launches through the delegate and leaves a fresh reading, so controls are available.
    private func launched(_ rig: ControllerRig, replies: @escaping () -> Void) async -> AppDelegate {
        let delegate = AppDelegate(controller: rig.controller, acquireLease: { AppInstanceLease {} }, statusFactory: { RetainedStatusStub() }, reply: { _ in replies() })
        delegate.applicationDidFinishLaunching(Notification(name: NSApplication.didFinishLaunchingNotification)); await delegate.startupTask?.value
        await rig.events.send(.network(true)); await settle(); await rig.reply()
        return delegate
    }
    @Test func terminationDuringEachRestartPhaseRestoresOnBeforeStopping() async throws {
        for phase in RestartPhase.allCases {
            let rig = try ControllerRig(); var replies = 0
            let delegate = await launched(rig) { replies += 1 }
            #expect(rig.controller.restartPort(.c3)); await settle()
            if phase != .turningOff { await rig.switchReply(.c3, false) }
            if phase == .turningOn { await rig.clock.advance(PortControlPolicy.restartPause) }
            let start = await rig.backend.log.count
            #expect(delegate.applicationShouldTerminate(NSApplication.shared) == .terminateLater)
            await delegate.terminationTask?.value
            #expect(replies == 1)
            #expect(await rig.commands().last == "c3 on")
            let restore = try #require(await rig.logIndex("switch", after: start))
            let stop = try #require(await rig.logIndex("disconnect", after: start))
            #expect(restore < stop)
            #expect(rig.controller.portOutcome?.kind == .mayStillBeOff)
            await rig.finish()
        }
    }
    @Test func terminationWithABlockedPublishAbortsAtTheWriteBudgetBeforeStopping() async throws {
        let rig = try ControllerRig(); var replies = 0
        let delegate = await launched(rig) { replies += 1 }
        await rig.backend.blockSwitches()
        rig.controller.restartPort(.c3); await settle()
        let start = await rig.backend.log.count
        #expect(delegate.applicationShouldTerminate(NSApplication.shared) == .terminateLater)
        await settle()
        #expect(replies == 0)
        #expect(await rig.logIndex("disconnect", after: start) == nil)
        // The ending attempt runs before stop(): the controller is still running.
        #expect(!rig.events.stopped)
        let began = rig.clock.date
        await rig.clock.advance(MonitorController.portEndingWriteBudget - 0.5)
        #expect(await rig.logIndex("abort", after: start) == nil)
        await rig.clock.advance(0.5)
        #expect(await rig.logIndex("abort", after: start) != nil)
        // Abort, drain, stop and reply complete without the clock reaching the budget.
        await delegate.terminationTask?.value
        #expect(rig.clock.date.timeIntervalSince(began) == MonitorController.portEndingWriteBudget)
        #expect(rig.clock.date.timeIntervalSince(began) < PortControlPolicy.exitAttemptTimeout)
        #expect(replies == 1)
        let abort = try #require(await rig.logIndex("abort", after: start))
        let stop = try #require(await rig.logIndex("disconnect", after: start))
        #expect(abort < stop)
        #expect(await rig.commands() == ["c3 off"])
        await rig.finish()
    }
}
