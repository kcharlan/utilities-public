import SwiftUI

@main struct BrewVersionApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    var body: some Scene { Settings { SettingsView(controller: delegate.controller) } }
}
