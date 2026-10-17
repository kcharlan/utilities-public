import AppKit

@main struct BrewVersionApp {
    @MainActor static func main() {
        let app = NSApplication.shared
        ApplicationMenu.install()
        let delegate = AppDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
