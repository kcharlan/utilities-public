import Foundation
import UserNotifications
import BrewVersionCore

@MainActor final class UserNotifier: NSObject, Notifier, UNUserNotificationCenterDelegate {
    var showPopover: (() -> Void)?
    private let center: UNUserNotificationCenter
    private(set) var lastError: String?
    override init() { center = .current(); super.init(); center.delegate = self }
    func requestAuthorization() async {
        guard await center.notificationSettings().authorizationStatus == .notDetermined else { return }
        do { _ = try await center.requestAuthorization(options: [.alert, .sound]) }
        catch { lastError = error.localizedDescription }
    }
    func post(_ notice: Notice) async {
        let content = UNMutableNotificationContent()
        content.title = notice.title; content.body = notice.body; content.sound = .default
        do { try await center.add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)) }
        catch { lastError = error.localizedDescription }
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        await MainActor.run { self.showPopover?() }
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        [.banner, .sound, .list]
    }
}
