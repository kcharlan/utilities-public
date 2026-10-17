import AppKit
import SwiftUI
import BrewVersionCore

@MainActor final class SettingsWindowController: NSObject, NSWindowDelegate {
    private let controller: WatchController
    private let notifier: UserNotifier
    let login: LoginItem
    private let activate: () -> Void
    private let present: (NSWindow) -> Void
    private var ownedWindow: NSWindow?
    init(controller: WatchController, notifier: UserNotifier, login: LoginItem = LoginItem(),
         activate: @escaping () -> Void = { NSApp.activate(ignoringOtherApps: true) },
         present: @escaping (NSWindow) -> Void = { $0.makeKeyAndOrderFront(nil) }) {
        self.controller = controller; self.notifier = notifier; self.login = login
        self.activate = activate; self.present = present
    }
    func show() {
        if ownedWindow == nil {
            let window = NSWindow(contentViewController: NSHostingController(rootView: SettingsView(controller: controller, notifier: notifier, login: login)))
            window.title = "Brew Version Settings"
            window.styleMask = [.titled, .closable, .miniaturizable]
            window.isReleasedWhenClosed = false
            window.delegate = self
            window.center()
            ownedWindow = window
        }
        activate()
        if let ownedWindow { present(ownedWindow) }
    }
    func windowDidBecomeKey(_ notification: Notification) { login.refresh() }
}
