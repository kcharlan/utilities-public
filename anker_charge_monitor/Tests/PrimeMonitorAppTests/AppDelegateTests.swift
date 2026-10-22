import AppKit
import Testing
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
