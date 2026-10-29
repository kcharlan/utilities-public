// Port: brew_version/Sources/BrewVersion/UserNotifier.swift, NotificationService, NativeNotificationService and UserNotifier, fbd3e03.
// Adaptation: `delivered()` added so a notification check can confirm delivery. Telltale's
// PendingNotification replaces Notifier, Notice and PackageName (an alert notification takes the
// package notice's place), the wording comes from Copy, and a click opens Telltale's panel.
// NativeNotificationPoster moved here from CollectorEntry.swift, since CollectorMonitor posts
// through it and the harness builders exclude CollectorEntry.swift.
import Foundation
import Observation
import UserNotifications
import TelltaleCore

@MainActor protocol NotificationService {
    func authorizationStatus() async -> UNAuthorizationStatus
    func requestAuthorization() async throws -> Bool
    func post(_ request: UNNotificationRequest) async throws
    func delivered() async -> [UNNotification]
    func removeDelivered(identifiers: [String])
}
@MainActor final class NativeNotificationService: NotificationService {
    let center = UNUserNotificationCenter.current()
    func authorizationStatus() async -> UNAuthorizationStatus { await center.notificationSettings().authorizationStatus }
    func requestAuthorization() async throws -> Bool { try await center.requestAuthorization(options: [.alert, .sound]) }
    func post(_ request: UNNotificationRequest) async throws { try await center.add(request) }
    func delivered() async -> [UNNotification] { await center.deliveredNotifications() }
    func removeDelivered(identifiers: [String]) { center.removeDeliveredNotifications(withIdentifiers: identifiers) }
}

/// The UI's notifications: it owns authorization, sends the Settings test notification, keeps a
/// failed post for Retry, and opens the panel when a notification is clicked. The collector's
/// own posts carry the same bundle identity (`NativeNotificationPoster`), so their clicks land here.
@MainActor @Observable final class UserNotifier: NSObject, UNUserNotificationCenterDelegate {
    var showPopover: (() -> Void)?
    private(set) var isSendingTestNotification = false
    func sendTestNotification() async {
        guard !isSendingTestNotification else { return }
        isSendingTestNotification = true
        defer { isSendingTestNotification = false }
        await post(PendingNotification(id: "test-\(UUID().uuidString)", title: Copy.testNotificationTitle,
                                       body: Copy.testNotificationBody, threadID: "test"), kind: .test)
    }
    private let service: any NotificationService
    private var authorizationError: String?
    private enum NoticeKind: Hashable { case alert, test }
    private struct FailedNotice { let notification: PendingNotification; let postingError: String? }
    // Diagnostics cannot replace or resolve an alert's retry payload.
    private var failures: [NoticeKind: FailedNotice] = [:]
    private var latestPosts: [NoticeKind: UUID] = [:]
    var lastError: String? {
        let errors = [authorizationError, failures[.alert]?.postingError, failures[.test]?.postingError].compactMap { $0 }
        if errors.isEmpty, !failures.isEmpty { return Copy.notificationRetryPending }
        return errors.joined(separator: " ").nilIfEmpty
    }
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
            authorizationError = status == .denied ? Copy.notificationsDenied : nil
        } catch { authorizationError = Copy.notificationAuthorizationFailure(error: error) }
    }
    func post(_ notification: PendingNotification) async {
        await post(notification, kind: .alert)
    }
    func removeDelivered(threadIDs: Set<String>) async {
        let identifiers = await service.delivered().filter { threadIDs.contains($0.request.content.threadIdentifier) }.map(\.request.identifier)
        service.removeDelivered(identifiers: identifiers)
    }
    private func post(_ notification: PendingNotification, kind: NoticeKind) async {
        // A late completion must not resolve a newer failure of the same kind.
        let request = UUID()
        latestPosts[kind] = request
        await requestAuthorization()
        guard latestPosts[kind] == request else { return }
        guard authorizationError == nil else {
            failures[kind] = FailedNotice(notification: notification, postingError: failures[kind]?.postingError)
            return
        }
        do {
            try await service.post(NativeNotificationPoster.request(for: notification))
            if latestPosts[kind] == request { failures[kind] = nil }
        } catch {
            if latestPosts[kind] == request {
                failures[kind] = FailedNotice(notification: notification, postingError: Copy.notificationPostFailure(error: error))
            }
        }
    }
    func retry() async {
        await requestAuthorization()
        guard authorizationError == nil else { return }
        for kind in [NoticeKind.alert, .test] {
            if let failure = failures[kind] { await post(failure.notification, kind: kind) }
        }
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        await MainActor.run { self.showPopover?() }
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions { [.banner, .sound, .list] }
}
private extension String { var nilIfEmpty: String? { isEmpty ? nil : self } }

/// Posts the collector's notifications through `NativeNotificationService`, so they carry
/// Telltale's bundle identity (the section 4 spike). Authorization is the UI's to request; a
/// refused post is logged by the run.
struct NativeNotificationPoster: NotificationPosting {
    func post(_ notification: PendingNotification) async throws {
        try await Self.deliver(notification)
    }

    @MainActor private static func deliver(_ notification: PendingNotification) async throws {
        try await NativeNotificationService().post(request(for: notification))
    }

    static func request(for notification: PendingNotification) -> UNNotificationRequest {
        let content = UNMutableNotificationContent()
        content.title = notification.title
        content.body = notification.body
        content.threadIdentifier = notification.threadID
        content.sound = .default
        return UNNotificationRequest(identifier: notification.id, content: content, trigger: nil)
    }
}
