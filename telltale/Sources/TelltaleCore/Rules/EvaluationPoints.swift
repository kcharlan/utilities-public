import Foundation

/// Spec section 7.1's evaluation points: every 5 minutes on wall-clock boundaries. Points are
/// multiples of 300 Unix seconds; every time zone Telltale meets is offset by whole quarter
/// hours, so they fall on local :00, :05, … and stay contiguous across DST changes.
public enum EvaluationPoints {
    public static let cadenceMinutes = 5
    public static let cadence: TimeInterval = TimeInterval(cadenceMinutes * 60)

    /// Points strictly after `last` (when given), at or after `earliest`, and at or before `now`,
    /// oldest first.
    public static func after(_ last: Date?, through now: Date, earliest: Date) -> [Date] {
        var first = (earliest.timeIntervalSince1970 / cadence).rounded(.up) * cadence
        if let last {
            first = max(first, ((last.timeIntervalSince1970 / cadence).rounded(.down) + 1) * cadence)
        }
        let end = now.timeIntervalSince1970
        guard first <= end else { return [] }
        let count = Int(((end - first) / cadence).rounded(.down)) + 1
        return (0..<count).map { Date(timeIntervalSince1970: first + Double($0) * cadence) }
    }

    /// Consecutive points a rule duration needs: `minutes / 5` rounded up, at least 1 (plan call
    /// for durations between grid boundaries), so a rule never fires before its duration.
    public static func count(forMinutes minutes: Int) -> Int {
        max(1, (minutes + cadenceMinutes - 1) / cadenceMinutes)
    }
}
