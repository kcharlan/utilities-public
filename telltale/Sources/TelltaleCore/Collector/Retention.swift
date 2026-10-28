import Foundation

/// Spec section 4's retention table. Events, episodes, incidents and baseline acceptances are
/// kept indefinitely (small); only response rows and collector run records expire. The table
/// names nothing else, so evaluation points, failed turns and connection events are kept too.
public enum Retention {
    /// Response rows.
    public static let responseDays = 180
    /// Collector run records.
    public static let runDays = 30

    /// Deletes expired rows at most once per local day of `calendar`, recorded in `lastPrunedDay`.
    /// Returns whether it pruned.
    @discardableResult
    public static func prune(store: Store, now: Date, calendar: Calendar) throws -> Bool {
        let today = LocalDay(now, calendar: calendar).description
        return try store.transaction {
            if try store.value(.lastPrunedDay) == today { return false }
            try store.run("DELETE FROM responses WHERE end_at < ?", [.date(cutoff(days: responseDays, before: now, calendar: calendar))])
            try store.run("DELETE FROM collector_runs WHERE started_at < ?", [.date(cutoff(days: runDays, before: now, calendar: calendar))])
            try store.set(.lastPrunedDay, today)
            return true
        }
    }

    private static func cutoff(days: Int, before now: Date, calendar: Calendar) -> Date {
        calendar.date(byAdding: .day, value: -days, to: now) ?? now.addingTimeInterval(-TimeInterval(days) * 86_400)
    }
}
