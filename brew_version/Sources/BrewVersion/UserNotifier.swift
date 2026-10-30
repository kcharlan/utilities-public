import Foundation
import Observation
import UserNotifications
import BrewVersionCore

@MainActor protocol NotificationService {
    func authorizationStatus() async -> UNAuthorizationStatus
    func requestAuthorization() async throws -> Bool
    func post(_ request: UNNotificationRequest) async throws
    func deliveredIdentifiers() async -> Set<String>
    func listsInNotificationCenter() async -> Bool
    func removeDelivered(_ identifiers: [String])
}
@MainActor final class NativeNotificationService: NotificationService {
    let center = UNUserNotificationCenter.current()
    init() {
        center.setNotificationCategories([UNNotificationCategory(identifier: UserNotifier.alertIdentifier, actions: [], intentIdentifiers: [], options: [.customDismissAction])])
    }
    func authorizationStatus() async -> UNAuthorizationStatus { await center.notificationSettings().authorizationStatus }
    func requestAuthorization() async throws -> Bool { try await center.requestAuthorization(options: [.alert, .sound]) }
    func post(_ request: UNNotificationRequest) async throws { try await center.add(request) }
    func deliveredIdentifiers() async -> Set<String> { Set(await center.deliveredNotifications().map { $0.request.identifier }) }
    func listsInNotificationCenter() async -> Bool { await center.notificationSettings().notificationCenterSetting == .enabled }
    func removeDelivered(_ identifiers: [String]) { center.removeDeliveredNotifications(withIdentifiers: identifiers) }
}
@MainActor @Observable final class UserNotifier: NSObject, Notifier, UNUserNotificationCenterDelegate {
    static let alertIdentifier = "brew-version.updates"
    static let deliveryGrace: TimeInterval = 5
    var showPopover: (() -> Void)?
    var acknowledgeAlert: (() -> Void)?
    private(set) var isSendingTestNotification = false
    private(set) var lastAlertPost: Date?
    func sendTestNotification() async {
        guard !isSendingTestNotification else { return }
        isSendingTestNotification = true
        defer { isSendingTestNotification = false }
        await postTest(PendingPost(identifier: UUID().uuidString, title: "Brew Version test notification", body: "This is a test notification from Brew Version. Click to open the popover.", sound: true, category: nil))
    }
    private let service: any NotificationService
    private let now: () -> Date
    private var authorizationError: String?
    private enum NoticeKind: Hashable { case package, test }
    private struct PendingPost { let identifier: String; var title: String; var body: String; var sound: Bool; let category: String? }
    private struct Failure { var post: PendingPost; let postingError: String? }
    private var currentPackage: PendingPost?
    private var packageEpisode = UUID()
    private var packageDeliveryNeeded = false
    private var packageWorker: Task<Void, Never>?
    private var failures: [NoticeKind: Failure] = [:]
    private var latestPosts: [NoticeKind: UUID] = [:]
    var lastError: String? {
        let errors = [authorizationError, failures[.package]?.postingError, failures[.test]?.postingError].compactMap { $0 }
        if errors.isEmpty, !failures.isEmpty { return "A notification is waiting to be retried. Retry notifications." }
        return errors.joined(separator: " ").nilIfEmpty
    }
    init(service: any NotificationService, now: @escaping () -> Date = Date.init) { self.service = service; self.now = now; super.init() }
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
    func syncAlert(_ digest: AlertDigest?, delivery: AlertDelivery) async {
        await publishAlert(digest, delivery: delivery).value
    }
    func publishAlert(_ digest: AlertDigest?, delivery: AlertDelivery) -> Task<Void, Never> {
        guard let digest else {
            packageEpisode = UUID(); currentPackage = nil; failures[.package] = nil; lastAlertPost = nil
            packageDeliveryNeeded = false
            service.removeDelivered([Self.alertIdentifier])
            return Task {}
        }
        let sound = delivery == .withSound || failures[.package]?.post.sound == true
            || currentPackage?.sound == true
        let payload = PendingPost(identifier: Self.alertIdentifier, title: digest.title, body: digest.body, sound: sound, category: Self.alertIdentifier)
        currentPackage = payload
        if delivery == .keepCurrent {
            if var failure = failures[.package] { failure.post.title = digest.title; failure.post.body = digest.body; failures[.package] = failure }
            return Task {}
        }
        packageDeliveryNeeded = true
        return startPackageWorker()
    }
    private func startPackageWorker() -> Task<Void, Never> {
        if let packageWorker { return packageWorker }
        let worker = Task { await self.deliverPackages() }
        packageWorker = worker
        return worker
    }
    private func deliverPackages() async {
        while packageDeliveryNeeded, currentPackage != nil {
            packageDeliveryNeeded = false
            let episode = packageEpisode
            await requestAuthorization()
            guard episode == packageEpisode, let current = currentPackage else { continue }
            guard authorizationError == nil else {
                failures[.package] = Failure(post: current, postingError: failures[.package]?.postingError)
                continue
            }
            // This snapshot includes every publication made while authorization was suspended.
            packageDeliveryNeeded = false
            let content = UNMutableNotificationContent()
            content.title = current.title; content.body = current.body
            if current.sound { content.sound = .default }
            if let category = current.category { content.categoryIdentifier = category }
            do {
                try await service.post(UNNotificationRequest(identifier: current.identifier, content: content, trigger: nil))
                guard episode == packageEpisode, currentPackage != nil else {
                    service.removeDelivered([Self.alertIdentifier]); continue
                }
                failures[.package] = nil; lastAlertPost = now()
                currentPackage?.sound = false
            } catch {
                if episode == packageEpisode, let latest = currentPackage {
                    failures[.package] = Failure(post: latest, postingError: failureMessage("Couldn't post notification", error: error))
                }
            }
        }
        packageWorker = nil
    }
    private func postTest(_ payload: PendingPost) async {
        let token = UUID()
        latestPosts[.test] = token
        await requestAuthorization()
        guard latestPosts[.test] == token else { return }
        guard authorizationError == nil else {
            failures[.test] = Failure(post: payload, postingError: failures[.test]?.postingError)
            return
        }
        let content = UNMutableNotificationContent()
        content.title = payload.title; content.body = payload.body
        if payload.sound { content.sound = .default }
        if let category = payload.category { content.categoryIdentifier = category }
        do {
            try await service.post(UNNotificationRequest(identifier: payload.identifier, content: content, trigger: nil))
            if latestPosts[.test] == token { failures[.test] = nil }
        } catch {
            if latestPosts[.test] == token {
                failures[.test] = Failure(post: payload, postingError: failureMessage("Couldn't post notification", error: error))
            }
        }
    }
    func retry() async {
        await requestAuthorization()
        guard authorizationError == nil else { return }
        if failures[.package] != nil {
            if let packageWorker { await packageWorker.value }
            else { packageDeliveryNeeded = true; await startPackageWorker().value }
        }
        if let failure = failures[.test] { await postTest(failure.post) }
    }
    func alertWasCleared() async -> Bool {
        guard await service.authorizationStatus() == .authorized, await service.listsInNotificationCenter(), failures[.package] == nil,
              lastAlertPost.map({ now().timeIntervalSince($0) > Self.deliveryGrace }) ?? true else { return false }
        return !(await service.deliveredIdentifiers()).contains(Self.alertIdentifier)
    }
    func removeLegacyAlerts() async {
        let legacy = await service.deliveredIdentifiers().filter { $0 != Self.alertIdentifier }
        service.removeDelivered(Array(legacy))
    }
    func handleResponse(actionIdentifier: String, requestIdentifier: String) {
        if requestIdentifier == Self.alertIdentifier { acknowledgeAlert?() }
        if actionIdentifier != UNNotificationDismissActionIdentifier { showPopover?() }
    }
    private func failureMessage(_ context: String, error: any Error) -> String {
        let detail = error.localizedDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        let separator = detail.last.map { ".!?…。！？".contains($0) } == true ? " " : ". "
        return "\(context): \(detail)\(separator)Retry notifications."
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        let action = response.actionIdentifier, identifier = response.notification.request.identifier
        await MainActor.run { self.handleResponse(actionIdentifier: action, requestIdentifier: identifier) }
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions { [.banner, .sound, .list] }
}
private extension String { var nilIfEmpty: String? { isEmpty ? nil : self } }
