import Foundation
import UserNotifications
import TelltaleCore

/// Time source for a check. Tests inject controlled elapsed time and pauses;
/// `.live` starts a fresh monotonic clock each time it is evaluated.
struct CheckTiming: Sendable {
    /// Monotonic seconds since the check began.
    var elapsed: @Sendable () -> TimeInterval
    var pause: @Sendable (TimeInterval) async -> Void
    /// Stop polling for delivery once `elapsed` reaches this many seconds.
    var deliveryTimeout: TimeInterval
    var pollInterval: TimeInterval

    /// The runner script waits 20 s for the result; the rest is left for launch and writing it.
    static var live: CheckTiming {
        let clock = ContinuousClock()
        let start = clock.now
        return CheckTiming(
            elapsed: {
                let parts = start.duration(to: clock.now).components
                return TimeInterval(parts.seconds) + TimeInterval(parts.attoseconds) / 1e18
            },
            pause: { try? await Task.sleep(for: .seconds($0)) },
            deliveryTimeout: 14,
            pollInterval: 0.25)
    }
}

/// `--notification-check`: posts one notification and reports whether macOS delivered it
/// under this process's own bundle identity (spec section 4's required spike).
enum NotificationCheck {
    private struct Result: Encodable {
        var authorization: String
        var posted = false
        var delivered = false
        var bundle: String?
        var error: String?

        // JSON keeps `bundle` and `error` as explicit nulls so the shape never varies.
        enum CodingKeys: String, CodingKey { case authorization, posted, delivered, bundle, error }
        func encode(to encoder: any Encoder) throws {
            var container = encoder.container(keyedBy: CodingKeys.self)
            try container.encode(authorization, forKey: .authorization)
            try container.encode(posted, forKey: .posted)
            try container.encode(delivered, forKey: .delivered)
            try container.encode(bundle, forKey: .bundle)
            try container.encode(error, forKey: .error)
        }
    }

    /// Returns 0 only when the request posted by this invocation is among `delivered()`,
    /// matched by its fresh identifier so an earlier check's notification cannot satisfy it.
    @MainActor static func run(service: any NotificationService, resultURL: URL, mode: String, timing: CheckTiming = .live) async -> Int32 {
        var result = Result(authorization: "unknown", bundle: Bundle.main.bundleIdentifier)
        defer { write(result, to: resultURL) }

        var status = await service.authorizationStatus()
        if status == .notDetermined {
            do { status = try await service.requestAuthorization() ? .authorized : .denied }
            catch {
                result.authorization = name(of: status)
                result.error = Copy.notificationAuthorizationFailure(error: error)
                return 1
            }
        }
        result.authorization = name(of: status)
        guard status == .authorized || status == .provisional else {
            result.error = Copy.notificationsDenied
            return 1
        }

        let content = UNMutableNotificationContent()
        content.title = Copy.notificationCheckTitle
        content.body = Copy.notificationCheckBody(mode: mode)
        content.sound = .default
        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        do { try await service.post(request) }
        catch {
            result.error = Copy.notificationPostFailure(error: error)
            return 1
        }
        result.posted = true

        // Delivery can complete after `add` returns, so poll until the deadline.
        while true {
            if await service.delivered().contains(where: { $0.request.identifier == request.identifier }) {
                result.delivered = true
                return 0
            }
            guard timing.elapsed() < timing.deliveryTimeout else { break }
            await timing.pause(timing.pollInterval)
        }
        result.error = Copy.notificationCheckNotDelivered(seconds: Int(timing.deliveryTimeout.rounded()))
        return 1
    }

    private static func name(of status: UNAuthorizationStatus) -> String {
        switch status {
        case .notDetermined: "notDetermined"
        case .denied: "denied"
        case .authorized: "authorized"
        case .provisional: "provisional"
        case .ephemeral: "ephemeral"
        @unknown default: "unknown"
        }
    }

    private static func write(_ result: Result, to url: URL) {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        do { try encoder.encode(result).write(to: url, options: .atomic) }
        catch { FileHandle.standardError.write(Data("Couldn't write \(url.lastPathComponent): \(error.localizedDescription)\n".utf8)) }
    }
}
