import AppKit
import BrewVersionCore

@main struct Prototype {
    @MainActor static func main() {
        let app = NSApplication.shared
        ApplicationMenu.install()
        let delegate = PrototypeDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
@MainActor final class PrototypeDelegate: NSObject, NSApplicationDelegate {
    let notifier = UserNotifier()
    private var settings: SettingsWindowController?
    func applicationDidFinishLaunching(_ notification: Notification) {
        let controller = SyntheticEnvironment.makeController(service: SyntheticTransport(), notifier: notifier)
        let settings = SettingsWindowController(controller: controller, notifier: notifier)
        self.settings = settings
        settings.show()
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        settings?.show(); return true
    }
}
