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
    private var appearance: NSAppearance?
    private let focus = SettingsFocus()
    init(controller: WatchController, notifier: UserNotifier, login: LoginItem = LoginItem(),
         activate: @escaping () -> Void = { NSApp.activate(ignoringOtherApps: true) },
         present: @escaping (NSWindow) -> Void = { $0.makeKeyAndOrderFront(nil) }) {
        self.controller = controller; self.notifier = notifier; self.login = login
        self.activate = activate; self.present = present
    }
    func show() {
        if ownedWindow == nil {
            let hosting = NSHostingController(rootView: SettingsView(controller: controller, notifier: notifier, login: login, focus: focus))
            // A grouped Form is flexible vertically and reports only its footer
            // as intrinsic height. The actual AppKit window owns its viewport.
            hosting.sizingOptions = []
            let window = NSWindow(contentViewController: hosting)
            window.title = "Brew Version Settings"
            window.styleMask = [.titled, .closable, .miniaturizable]
            window.isReleasedWhenClosed = false
            window.titlebarAppearsTransparent = true
            window.toolbarStyle = .unifiedCompact
            window.setContentSize(NSSize(width: 460, height: 440))
            window.contentMinSize = NSSize(width: 460, height: 440)
            window.appearance = appearance
            window.delegate = self
            window.center()
            ownedWindow = window
        }
        activate()
        if let ownedWindow { present(ownedWindow) }
    }
    func showCustomInterval() { focus.requestInterval(); show() }
    func setAppearance(_ appearance: NSAppearance?) {
        self.appearance = appearance
        ownedWindow?.appearance = appearance
    }
    func windowDidBecomeKey(_ notification: Notification) { login.refresh() }
}
