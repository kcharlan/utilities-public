import AppKit
import PrimeMonitorCore

/// Lifecycle adapted from BrewVersion/AppDelegate.swift at 579ebb7;
/// async shutdown and lease ownership are Prime Monitor's checkpoint contract.
@MainActor final class AppDelegate: NSObject, NSApplicationDelegate {
    let controller: MonitorController
    private let acquireLease: () throws -> AppInstanceLease
    private let reply: (NSApplication) -> Void
    private let reportFailure: (String) -> Void
    private let show: () -> Void
    private let statusFactory: () -> any PopoverPresenting
    private var status: (any PopoverPresenting)?
    private var lease: AppInstanceLease?
    private(set) var startupTask: Task<Void, Never>?
    private(set) var terminationTask: Task<Void, Never>?
    init(controller: MonitorController, acquireLease: @escaping () throws -> AppInstanceLease,
         statusFactory: (() -> any PopoverPresenting)? = nil,
         show: @escaping () -> Void = {},
         reportFailure: @escaping (String) -> Void = { message in let alert = NSAlert(); alert.messageText = message; alert.runModal() },
         reply: @escaping (NSApplication) -> Void = { $0.reply(toApplicationShouldTerminate: true) }) {
        self.controller = controller; self.acquireLease = acquireLease
        self.statusFactory = statusFactory ?? { StatusItemController(controller: controller) }
        self.show = show; self.reportFailure = reportFailure; self.reply = reply
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        guard startupTask == nil else { return }
        startupTask = Task {
            do { lease = try acquireLease() }
            catch { reportFailure("\(PrimeMonitorRelease.displayName) could not acquire its instance gate."); return }
            let needsSetup = controller.needsSetup
            controller.start(); status = statusFactory()
            if needsSetup { status?.showSettings() }
            show()
        }
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if terminationTask == nil {
            terminationTask = Task {
                await startupTask?.value
                await controller.stop(); lease?.release(); lease = nil
                reply(sender)
            }
        }
        return .terminateLater
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool { status?.showPopover(); return true }
    func applicationWillTerminate(_ notification: Notification) { lease?.release(); lease = nil }
}
