import Foundation
import Observation
import UserNotifications
import BrewVersionCore

@MainActor protocol NotificationService {
    func authorizationStatus() async -> UNAuthorizationStatus
    func requestAuthorization() async throws -> Bool
    func post(_ request: UNNotificationRequest) async throws
}
@MainActor final class NativeNotificationService: NotificationService {
    let center = UNUserNotificationCenter.current()
    func authorizationStatus() async -> UNAuthorizationStatus { await center.notificationSettings().authorizationStatus }
    func requestAuthorization() async throws -> Bool { try await center.requestAuthorization(options: [.alert, .sound]) }
    func post(_ request: UNNotificationRequest) async throws { try await center.add(request) }
}
@MainActor @Observable final class UserNotifier: NSObject, Notifier, UNUserNotificationCenterDelegate {
    var showPopover: (() -> Void)?
    private let service: any NotificationService
    private var authorizationError: String?
    private var postingError: String?
    private var failedNotice: Notice?
    var lastError: String? { [authorizationError, postingError].compactMap { $0 }.joined(separator: " ").nilIfEmpty }
    init(service: any NotificationService) { self.service = service; super.init() }
    override convenience init() {
        let service = NativeNotificationService()
        self.init(service: service)
        service.center.delegate = self
    }
    func requestAuthorization() async {
        do {
            var status = await service.authorizationStatus()
            if status == .notDetermined {
                let granted = try await service.requestAuthorization()
                status = granted ? .authorized : .denied
            }
            authorizationError = status == .denied ? "Notifications are off. Allow Brew Version in System Settings, then retry notifications." : nil
        } catch { authorizationError = "Notification authorization failed: \(error.localizedDescription). Retry notifications." }
    }
    func post(_ notice: Notice) async {
        await requestAuthorization()
        guard authorizationError == nil else { failedNotice = notice; return }
        let content = UNMutableNotificationContent()
        content.title = notice.title; content.body = notice.body; content.sound = .default
        do {
            try await service.post(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
            postingError = nil; failedNotice = nil
        } catch {
            failedNotice = notice
            postingError = "Couldn't post notification: \(error.localizedDescription). Retry notifications."
        }
    }
    func retry() async {
        await requestAuthorization()
        if authorizationError == nil, let notice = failedNotice { await post(notice) }
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        await MainActor.run { self.showPopover?() }
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions { [.banner, .sound, .list] }
}
private extension String { var nilIfEmpty: String? { isEmpty ? nil : self } }
