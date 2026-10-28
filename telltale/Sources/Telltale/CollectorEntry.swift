import Foundation
import TelltaleCore
import UserNotifications

/// `Telltale --collect`: one collector run for the real user, with the registered plugins.
/// launchd starts it every N minutes (spec section 9.3); its exit code is the run's.
enum CollectorEntry {
    static func run() async -> Int32 {
        let paths = TelltalePaths.live()
        let report = await CollectorRun(
            paths: paths, sources: Registry.usageSources(paths: paths), statusSources: Registry.statusSources(),
            notifier: NativeNotificationPoster(), calendar: .current, now: Date()
        ).run()
        return report.exitCode
    }
}

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
