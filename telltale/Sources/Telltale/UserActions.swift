import Foundation
import TelltaleCore

/// The app's narrow read-write path (spec section 4): settings, baseline acceptance and undo,
/// "Keep as abnormal", a rebuild request, and Check now. Each write opens a short-lived read-write
/// connection, but only after a read-only open succeeds, so the app never creates or initializes
/// the database: before the collector's first run every write throws `StoreError.notInitialized`.
@MainActor final class UserActions {
    private let paths: TelltalePaths
    private let calendar: Calendar
    private let now: @MainActor () -> Date
    private let kickstart: @Sendable () throws -> Void
    private let changed: @MainActor () -> Void

    /// `kickstart` starts the collector job once (`LaunchAgentManager.kickstart`); `changed` runs
    /// after each successful write so the panel rereads at once.
    init(
        paths: TelltalePaths, calendar: Calendar = .current, now: @escaping @MainActor () -> Date = Date.init,
        kickstart: @escaping @Sendable () throws -> Void, changed: @escaping @MainActor () -> Void = {}
    ) {
        self.paths = paths
        self.calendar = calendar
        self.now = now
        self.kickstart = kickstart
        self.changed = changed
    }

    /// "Check now": one collector run outside its schedule. launchctl runs off the main actor.
    func checkNow() async throws {
        let kickstart = kickstart
        try await Task.detached { try kickstart() }.value
    }

    /// Spec section 8's "Accept as usual…" from `since`.
    func accept(provider: ProviderID, model: String, since: LocalDay) throws -> Acceptance {
        try write { store in
            try BaselineEngine(store: store, calendar: calendar).accept(provider: provider, model: model, since: since, at: now())
        }
    }

    func undo(epochID: Int64) throws {
        try write { store in try BaselineEngine(store: store, calendar: calendar).undo(epochID: epochID, at: now()) }
    }

    func keepAsAbnormal(_ prompt: ShiftPrompt) throws {
        try write { store in try ShiftDetector.keepAsAbnormal(prompt, at: now(), store: store) }
    }

    /// Stores a setting. Callers validate first (`RuleSettings.validationErrors()`, `Settings.intervalError`).
    func set<V>(_ key: SettingKey<V>, _ value: V) throws {
        try write { store in try store.set(key, value) }
    }

    /// Asks the collector to rebuild derived data on its next run (spec section 7.3).
    func requestRebuild() throws {
        try write { store in try store.set(.rebuildRequestedAt, now()) }
    }

    private func write<T>(_ body: (Store) throws -> T) throws -> T {
        _ = try Store.open(paths.database, mode: .readOnly)
        let result = try body(try Store.open(paths.database, mode: .readWrite))
        changed()
        return result
    }
}
