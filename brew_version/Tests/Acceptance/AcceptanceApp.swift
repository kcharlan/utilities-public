import AppKit
import SwiftUI
import BrewVersionCore
import UserNotifications

// Compiled only by build.sh into a distinct bundle. No production simulation path.
@main struct AcceptanceApp {
    @MainActor static func main() {
        let app = NSApplication.shared
        ApplicationMenu.install()
        let delegate = AcceptanceDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
@MainActor final class AcceptanceDelegate: NSObject, NSApplicationDelegate {
    let service = SyntheticTransport()
    let notificationService = SyntheticNotificationService()
    let notifier: UserNotifier
    let controller: WatchController
    private var status: StatusItemController?
    override init() {
        notifier = UserNotifier(service: notificationService)
        controller = SyntheticEnvironment.makeController(service: service, notifier: notifier)
        super.init()
        notificationService.native.center.delegate = notifier
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        let controls = AnyView(VStack {
            Text("Synthetic acceptance only").font(.caption)
            HStack {
                Button("Advance release and check") { Task { await self.service.advance(); await self.controller.checkNow() } }
                Button("Light") { self.status?.setAppearance(NSAppearance(named: .aqua)) }
                Button("Dark") { self.status?.setAppearance(NSAppearance(named: .darkAqua)) }
            }
            HStack {
                Button("Delay next lookup") { Task { await self.service.delayNextLookup() } }
                Button("Test posting failure") {
                    self.notificationService.failNext = true
                    Task { await self.notifier.post(Notice(name: PackageName("synthetic-notice")!, title: "Synthetic retry notice", body: "Synthetic notification retry acceptance.")) }
                }
            }
        }.padding(10))
        let status = StatusItemController(controller: controller, notifier: notifier, accessory: controls)
        self.status = status
        notifier.showPopover = { [weak status] in status?.showPopover() }
        status.showPopover()
        Task { await controller.hydrateCatalog(); await controller.scheduledTick() }
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        status?.showPopover(); return true
    }
}

// A harness-only fault at the maintained notifier's system-service boundary.
@MainActor final class SyntheticNotificationService: NotificationService {
    let native = NativeNotificationService()
    var failNext = false
    func authorizationStatus() async -> UNAuthorizationStatus { await native.authorizationStatus() }
    func requestAuthorization() async throws -> Bool { try await native.requestAuthorization() }
    func post(_ request: UNNotificationRequest) async throws {
        if failNext { failNext = false; throw SyntheticPostingError() }
        try await native.post(request)
    }
}
private struct SyntheticPostingError: LocalizedError {
    var errorDescription: String? { "Synthetic posting failure for acceptance" }
}
