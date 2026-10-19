// Port: BrewVersion/Sources/BrewVersion/SettingsWindowController.swift, SettingsWindowController, 579ebb7.
// Adaptation: MonitorController and charger content replace BV watches/notifications; no custom interval.
import AppKit
import SwiftUI
import PrimeMonitorCore

@MainActor final class SettingsWindowController: NSObject, NSWindowDelegate {
    private let controller: MonitorController
    let login: LoginItem
    private let activate: () -> Void
    private let present: (NSWindow) -> Void
    private var ownedWindow: NSWindow?
    private var appearance: NSAppearance?
    init(controller: MonitorController, login: LoginItem = LoginItem(),
         activate: @escaping () -> Void = { NSApp.activate() },
         present: @escaping (NSWindow) -> Void = { $0.makeKeyAndOrderFront(nil) }) {
        self.controller = controller; self.login = login
        self.activate = activate; self.present = present
    }
    func show() {
        if ownedWindow == nil {
            let hosting = NSHostingController(rootView: SettingsView(monitor: controller, login: login))
            // A grouped Form is flexible vertically and reports only its footer
            // as intrinsic height. The actual AppKit window owns its viewport.
            hosting.sizingOptions = []
            let window = NSWindow(contentViewController: hosting)
            window.title = "\(PrimeMonitorRelease.displayName) Settings"
            window.styleMask = [.titled, .closable, .miniaturizable]
            window.isReleasedWhenClosed = false
            // The window is reused, so it keeps the Space it was first shown on.
            // Bring it to the current Space instead of switching the user there.
            window.collectionBehavior.insert(.moveToActiveSpace)
            window.titlebarAppearsTransparent = true
            window.toolbarStyle = .unifiedCompact
            window.setContentSize(NSSize(width: 460, height: 600))
            window.contentMinSize = NSSize(width: 460, height: 440)
            window.appearance = appearance
            window.delegate = self
            window.center()
            ownedWindow = window
        }
        activate()
        if let ownedWindow { present(ownedWindow) }
    }
    func setAppearance(_ appearance: NSAppearance?) {
        self.appearance = appearance
        ownedWindow?.appearance = appearance
    }
    func windowDidBecomeKey(_ notification: Notification) { login.refresh() }
}
