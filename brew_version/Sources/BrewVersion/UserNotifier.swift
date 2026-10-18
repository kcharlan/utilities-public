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
    private(set) var isSendingTestNotification = false
    func sendTestNotification() async {
        guard !isSendingTestNotification else { return }
        isSendingTestNotification = true
        defer { isSendingTestNotification = false }
        await post(Notice(name: PackageName("brew-version")!, title: "Brew Version test notification",
                          body: "This is a test notification from Brew Version. Click to open the popover."), kind: .test)
    }
    private let service: any NotificationService
    private var authorizationError: String?
    private enum NoticeKind: Hashable { case package, test }
    private struct FailedNotice { let notice: Notice; let postingError: String? }
    // Diagnostics cannot replace or resolve a package alert's retry payload.
    private var failures: [NoticeKind: FailedNotice] = [:]
    private var latestPosts: [NoticeKind: UUID] = [:]
    var lastError: String? {
        let errors = [authorizationError, failures[.package]?.postingError, failures[.test]?.postingError].compactMap { $0 }
        if errors.isEmpty, !failures.isEmpty { return "A notification is waiting to be retried. Retry notifications." }
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
            authorizationError = status == .denied ? "Notifications are off. Allow Brew Version in System Settings, then retry notifications." : nil
        } catch { authorizationError = failureMessage("Notification authorization failed", error: error) }
    }
    func post(_ notice: Notice) async {
        await post(notice, kind: .package)
    }
    private func post(_ notice: Notice, kind: NoticeKind) async {
        // A late completion must not resolve a newer failure of the same kind.
        let request = UUID()
        latestPosts[kind] = request
        await requestAuthorization()
        guard latestPosts[kind] == request else { return }
        guard authorizationError == nil else {
            failures[kind] = FailedNotice(notice: notice, postingError: failures[kind]?.postingError)
            return
        }
        let content = UNMutableNotificationContent()
        content.title = notice.title; content.body = notice.body; content.sound = .default
        do {
            try await service.post(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
            if latestPosts[kind] == request { failures[kind] = nil }
        } catch {
            if latestPosts[kind] == request {
                failures[kind] = FailedNotice(notice: notice, postingError: failureMessage("Couldn't post notification", error: error))
            }
        }
    }
    func retry() async {
        await requestAuthorization()
        guard authorizationError == nil else { return }
        for kind in [NoticeKind.package, .test] {
            if let failure = failures[kind] { await post(failure.notice, kind: kind) }
        }
    }
    private func failureMessage(_ context: String, error: any Error) -> String {
        let detail = error.localizedDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        let separator = detail.last.map { ".!?…。！？".contains($0) } == true ? " " : ". "
        return "\(context): \(detail)\(separator)Retry notifications."
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        await MainActor.run { self.showPopover?() }
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions { [.banner, .sound, .list] }
}
private extension String { var nilIfEmpty: String? { isEmpty ? nil : self } }
