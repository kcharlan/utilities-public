import Foundation
import TelltaleCore

/// A `NotificationPosting` fake for collector tests: records each posted notification, or
/// refuses every post once `refuseAll()` is called.
public actor RecordingNotifier: NotificationPosting {
    public struct Refused: Error, LocalizedError {
        public var errorDescription: String? { "synthetic notification refusal" }
    }

    public private(set) var posted: [PendingNotification] = []
    private var refuses = false

    public init() {}

    public func refuseAll() { refuses = true }

    public func post(_ notification: PendingNotification) async throws {
        if refuses { throw Refused() }
        posted.append(notification)
    }
}
