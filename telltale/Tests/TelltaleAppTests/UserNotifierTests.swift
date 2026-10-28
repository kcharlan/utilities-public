// Port: brew_version/Tests/BrewVersionAppTests/NativeActionsTests.swift, notification cases and their helpers, 5e1e642.
// Adaptation: Telltale's PendingNotification and Copy rows replace Notice, PackageName and the
// Brew Version wording; a package notice is an alert notification here.
//
// Source tests at 5e1e642 -> destination tests:
// - successfulTestKeepsAuthorizationBlockedPackageRetryVisible -> successfulTestKeepsAuthorizationBlockedAlertRetryVisible
// - testNotificationPreservesFailedPackageRecoveryForEveryOutcome -> testNotificationPreservesFailedAlertRecoveryForEveryOutcome
// - completedTestNotificationCannotEraseOverlappingPackageFailure -> completedTestNotificationCannotEraseOverlappingAlertFailure
// - successfulPackageNotificationPreservesFailedTestRecovery -> successfulAlertNotificationPreservesFailedTestRecovery
// - olderPackageCompletionCannotEraseNewerPackageFailure -> olderAlertCompletionCannotEraseNewerAlertFailure
// - testNotificationUsesAuthorizationAndKeepsFailedRequestRetryable -> testNotificationUsesAuthorizationAndKeepsFailedRequestRetryable
// - testNotificationIgnoresDuplicateSendWhilePosting -> testNotificationIgnoresDuplicateSendWhilePosting
// - notificationFailuresKeepOneSentenceBoundary -> notificationFailuresKeepOneSentenceBoundary
// - notificationDenialErrorAndPostingRetryAreObservable -> notificationDenialErrorAndPostingRetryAreObservable
// - longNotificationWarningWrapsWithinMaintainedPopover -> longNotificationWarningWrapsWithinPanel
// Helpers: NotificationServiceStub (with Telltale's delivered()), SyntheticAuthorizationFailure, ChangeFlag.
// Telltale additions: alertRequestsKeepTheirIdentity.
import AppKit
import Observation
import SwiftUI
import Testing
import UserNotifications
import TelltaleCore
import TelltaleTestSupport
@testable import Telltale

@MainActor final class NotificationServiceStub: NotificationService {
    var status: UNAuthorizationStatus = .notDetermined
    var allowed = false
    var fail = false
    var authorizationFailure: String?
    var postingFailure: String?
    var deliveredTitles: [String] = []
    var requests: [UNNotificationRequest] = []
    var authorizationRequests = 0
    var postingGate: (@MainActor () async -> Void)?
    func authorizationStatus() async -> UNAuthorizationStatus { status }
    func requestAuthorization() async throws -> Bool {
        authorizationRequests += 1
        if let authorizationFailure { throw SyntheticAuthorizationFailure(message: authorizationFailure) }
        if fail { throw CocoaError(.fileReadUnknown) }
        status = allowed ? .authorized : .denied
        return allowed
    }
    func post(_ request: UNNotificationRequest) async throws {
        requests.append(request)
        await postingGate?()
        if let postingFailure { throw SyntheticAuthorizationFailure(message: postingFailure) }
        if fail { throw CocoaError(.fileWriteUnknown) }
        deliveredTitles.append(request.content.title)
    }
    func delivered() async -> [UNNotification] { [] }
}
private struct SyntheticAuthorizationFailure: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}
@MainActor private final class ChangeFlag { var changed = false }

private func alert(_ number: Int, title: String, body: String) -> PendingNotification {
    PendingNotification(id: "synthetic-alert-\(number)", title: title, body: body, threadID: "synthetic.alerts")
}

@MainActor struct UserNotifierTests {
    @Test func successfulTestKeepsAuthorizationBlockedAlertRetryVisible() async {
        let service = NotificationServiceStub(); service.status = .denied
        let notifier = UserNotifier(service: service)
        let blocked = alert(1, title: "Synthetic authorization-blocked alert", body: "Synthetic authorization retry body.")
        await notifier.post(blocked)
        service.status = .authorized
        await notifier.sendTestNotification()
        #expect(notifier.lastError != nil)
        await notifier.retry()
        #expect(service.requests.filter { $0.content.title == blocked.title && $0.content.body == blocked.body }.count == 1)
        #expect(notifier.lastError == nil)
    }
    @Test func testNotificationPreservesFailedAlertRecoveryForEveryOutcome() async {
        for outcome in ["success", "denied", "posting-failure"] {
            let service = NotificationServiceStub(); service.status = .authorized
            let notifier = UserNotifier(service: service)
            let failed = alert(2, title: "Synthetic slower alert", body: "Example is 25% slower than usual.")
            service.postingFailure = "Synthetic alert posting failed"
            await notifier.post(failed)
            service.postingFailure = outcome == "posting-failure" ? "Synthetic test posting failed" : nil
            service.status = outcome == "denied" ? .denied : .authorized
            await notifier.sendTestNotification()
            #expect(notifier.lastError?.contains("Synthetic alert posting failed") == true)
            service.postingFailure = nil; service.status = .authorized
            await notifier.retry()
            let alertRequests = service.requests.filter { $0.content.title == failed.title }
            #expect(alertRequests.count == 2)
            #expect(alertRequests.last?.content.body == failed.body)
            #expect(notifier.lastError == nil)
        }
    }
    @Test func completedTestNotificationCannotEraseOverlappingAlertFailure() async {
        let service = NotificationServiceStub(); service.status = .authorized
        let notifier = UserNotifier(service: service)
        let overlapping = alert(3, title: "Synthetic overlapping alert", body: "Synthetic alert retry body.")
        service.postingGate = {
            service.postingGate = nil
            service.postingFailure = "Synthetic overlapping alert failure"
            await notifier.post(overlapping)
            service.postingFailure = nil
        }
        await notifier.sendTestNotification()
        #expect(notifier.lastError?.contains("Synthetic overlapping alert failure") == true)
        await notifier.retry()
        #expect(service.requests.filter { $0.content.title == overlapping.title && $0.content.body == overlapping.body }.count == 2)
        #expect(notifier.lastError == nil)
    }
    @Test func successfulAlertNotificationPreservesFailedTestRecovery() async {
        let service = NotificationServiceStub(); service.status = .authorized
        let notifier = UserNotifier(service: service)
        service.postingFailure = "Synthetic test failure"
        await notifier.sendTestNotification()
        service.postingFailure = nil
        await notifier.post(alert(4, title: "Synthetic other alert", body: "Synthetic other body."))
        #expect(notifier.lastError?.contains("Synthetic test failure") == true)
        await notifier.retry()
        #expect(service.requests.filter { $0.content.title == "Telltale notification check" }.count == 2)
        #expect(notifier.lastError == nil)
    }
    @Test func olderAlertCompletionCannotEraseNewerAlertFailure() async {
        let service = NotificationServiceStub(); service.status = .authorized
        let notifier = UserNotifier(service: service)
        let newer = alert(5, title: "Synthetic newer alert", body: "Synthetic newer retry body.")
        service.postingGate = {
            service.postingGate = nil
            service.postingFailure = "Synthetic newer alert failure"
            await notifier.post(newer)
            service.postingFailure = nil
        }
        await notifier.post(alert(6, title: "Synthetic older alert", body: "Synthetic older body."))
        #expect(notifier.lastError?.contains("Synthetic newer alert failure") == true)
        await notifier.retry()
        #expect(service.requests.filter { $0.content.title == newer.title && $0.content.body == newer.body }.count == 2)
        #expect(notifier.lastError == nil)
    }
    @Test func testNotificationUsesAuthorizationAndKeepsFailedRequestRetryable() async throws {
        let service = NotificationServiceStub()
        let notifier = UserNotifier(service: service)
        await notifier.sendTestNotification()
        #expect(service.authorizationRequests == 1)
        #expect(service.requests.isEmpty)
        #expect(notifier.lastError?.contains("Notifications are off") == true)
        service.status = .authorized
        service.postingFailure = "Synthetic test posting failed"
        await notifier.retry()
        let failed = try #require(service.requests.first)
        #expect(failed.content.title == "Telltale notification check")
        #expect(failed.content.body == "This is a test notification from Telltale. Click to open the panel.")
        #expect(failed.trigger == nil)
        #expect(notifier.lastError?.contains("Synthetic test posting failed") == true)
        service.postingFailure = nil
        await notifier.retry()
        #expect(service.requests.count == 2)
        #expect(service.requests.last?.content.title == failed.content.title)
        #expect(service.requests.last?.content.body == failed.content.body)
        #expect(notifier.lastError == nil)
        #expect(!notifier.isSendingTestNotification)
    }
    @Test func testNotificationIgnoresDuplicateSendWhilePosting() async {
        let service = NotificationServiceStub(); service.status = .authorized
        let notifier = UserNotifier(service: service)
        service.postingGate = { await notifier.sendTestNotification() }
        await notifier.sendTestNotification()
        #expect(service.requests.count == 1)
        #expect(!notifier.isSendingTestNotification)
    }
    @Test func notificationFailuresKeepOneSentenceBoundary() async {
        for (description, sentence) in [("Synthetic failure", "Synthetic failure."), ("Synthetic failure.", "Synthetic failure."), ("Synthetic failure!", "Synthetic failure!"), ("Synthetic failure?", "Synthetic failure?"), ("Synthetic failure.\n", "Synthetic failure.")] {
            let service = NotificationServiceStub()
            service.authorizationFailure = description
            let notifier = UserNotifier(service: service)
            await notifier.requestAuthorization()
            #expect(notifier.lastError == "Notification authorization failed: \(sentence) Retry notifications.")
            service.authorizationFailure = nil; service.status = .authorized
            service.postingFailure = description
            await notifier.post(alert(7, title: "Synthetic notice", body: "Synthetic retry"))
            #expect(notifier.lastError == "Couldn't post notification: \(sentence) Retry notifications.")
        }
    }
    @Test func notificationDenialErrorAndPostingRetryAreObservable() async {
        let service = NotificationServiceStub()
        let notifier = UserNotifier(service: service)
        let observed = ChangeFlag()
        withObservationTracking { _ = notifier.lastError } onChange: { Task { @MainActor in observed.changed = true } }
        await notifier.requestAuthorization()
        await Task.yield()
        #expect(notifier.lastError == "Notifications are off. Allow Telltale in System Settings, then retry notifications.")
        #expect(observed.changed)
        service.status = .authorized
        await notifier.requestAuthorization()
        #expect(notifier.lastError == nil)
        service.fail = true
        await notifier.post(alert(8, title: "synthetic notice", body: "synthetic body"))
        #expect(notifier.lastError != nil)
        service.fail = false
        await notifier.retry()
        #expect(notifier.lastError == nil)
        #expect(service.deliveredTitles == ["synthetic notice"])
        service.status = .notDetermined; service.fail = true
        await notifier.requestAuthorization()
        #expect(notifier.lastError?.contains("authorization") == true)
    }
    @Test func longNotificationWarningWrapsWithinPanel() async throws {
        try await withAsyncScratchDirectory { directory in
            let service = NotificationServiceStub()
            service.authorizationFailure = "Synthetic authorization was refused. Open System Settings, choose Notifications, select Telltale, enable notifications, then retry."
            let notifier = UserNotifier(service: service)
            await notifier.requestAuthorization()
            let warning = try #require(notifier.lastError)
            #expect(warning.contains("enable notifications"))
            let paths = PanelWorld.paths(directory)
            try PanelWorld.seed(paths, alerting: true)
            let model = PanelModel(store: PanelWorld.live(paths), actions: PanelWorld.actions(paths), notifier: notifier, calendar: Synth.newYork)
            let quiet = PanelModel(store: PanelWorld.live(paths), actions: PanelWorld.actions(paths), notifier: UserNotifier(service: NotificationServiceStub()), calendar: Synth.newYork)
            let warned = NSHostingView(rootView: PanelView(model: model, openSettings: {}, openDashboard: nil))
            let plain = NSHostingView(rootView: PanelView(model: quiet, openSettings: {}, openDashboard: nil))
            #expect(warned.fittingSize.width == 340 && plain.fittingSize.width == 340)
            // The warning wraps onto several lines instead of widening the panel.
            #expect(warned.fittingSize.height > plain.fittingSize.height + 40)
        }
    }
    @Test func alertRequestsKeepTheirIdentity() async throws {
        let service = NotificationServiceStub(); service.status = .authorized
        let notifier = UserNotifier(service: service)
        await notifier.post(alert(9, title: "Slower than usual", body: "Example is 25% slower than usual."))
        let request = try #require(service.requests.first)
        #expect(request.identifier == "synthetic-alert-9")
        #expect(request.content.threadIdentifier == "synthetic.alerts")
    }
}
