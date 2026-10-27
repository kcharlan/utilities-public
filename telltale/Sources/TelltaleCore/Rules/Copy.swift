import Foundation

/// User-facing wording (visual design doc, "Copy rules"). Callers use these
/// functions rather than literals. Later tasks add the rule and panel rows.
public enum Copy {
    public static let notificationCheckTitle = "Telltale notification check"
    public static func notificationCheckBody(mode: String) -> String { "Notification check: \(mode)" }
    /// Reported when a check's request posted but never appeared among delivered notifications.
    public static func notificationCheckNotDelivered(seconds: Int) -> String {
        "The notification was posted but not delivered within \(seconds) seconds."
    }

    public static let notificationsDenied = "Notifications are off. Allow Telltale in System Settings, then retry notifications."
    public static func notificationAuthorizationFailure(error: any Error) -> String {
        failureMessage("Notification authorization failed", error: error)
    }
    public static func notificationPostFailure(error: any Error) -> String {
        failureMessage("Couldn't post notification", error: error)
    }

    public static let collectorNotBuilt = "Collector not built yet"

    public static func statusPost(source: String, title: String) -> String { "\(source) posted: \(title)." }

    public static func intervalError(min: Int, max: Int) -> String { "Choose an interval from \(min) to \(max) minutes" }
    public static let clearBandError = "The clear band must be stricter than the trigger"
    public static func invalidRuleParameter(field: String) -> String { "Choose a valid value for \(field)." }

    // Port: brew_version/Sources/BrewVersion/UserNotifier.swift, failureMessage, fbd3e03.
    private static func failureMessage(_ context: String, error: any Error) -> String {
        let detail = error.localizedDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        let separator = detail.last.map { ".!?…。！？".contains($0) } == true ? " " : ". "
        return "\(context): \(detail)\(separator)Retry notifications."
    }
}
