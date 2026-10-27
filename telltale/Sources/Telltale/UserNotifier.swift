// Port: brew_version/Sources/BrewVersion/UserNotifier.swift, NotificationService and NativeNotificationService, fbd3e03.
// Adaptation: `delivered()` added so a notification check can confirm delivery.
// Task 11 ports the UserNotifier class that uses this service.
import UserNotifications

@MainActor protocol NotificationService {
    func authorizationStatus() async -> UNAuthorizationStatus
    func requestAuthorization() async throws -> Bool
    func post(_ request: UNNotificationRequest) async throws
    func delivered() async -> [UNNotification]
}
@MainActor final class NativeNotificationService: NotificationService {
    let center = UNUserNotificationCenter.current()
    func authorizationStatus() async -> UNAuthorizationStatus { await center.notificationSettings().authorizationStatus }
    func requestAuthorization() async throws -> Bool { try await center.requestAuthorization(options: [.alert, .sound]) }
    func post(_ request: UNNotificationRequest) async throws { try await center.add(request) }
    func delivered() async -> [UNNotification] { await center.deliveredNotifications() }
}
