import Foundation
import TelltaleCore

private struct DataUpdating: LocalizedError {
    var errorDescription: String? { Copy.settingsAfterUpgrade }
}

/// The app's narrow read-write path (spec section 4): settings, baseline acceptance and undo,
/// "Keep as abnormal", a rebuild request, and Check now. Each write opens a short-lived
/// `.readWriteExisting` connection, which refuses a missing or unmigrated file, so the app never
/// creates or initializes the database: before the collector's first run every write throws
/// `StoreError.notInitialized`.
@MainActor final class UserActions {
    private let paths: TelltalePaths
    private let calendar: Calendar
    private let now: @MainActor () -> Date
    private let kickstart: @Sendable () throws -> Void
    private let changed: @MainActor () -> Void
    private let sourceNames: [ProviderID: String]

    /// `kickstart` starts the collector job once (`LaunchAgentManager.kickstart`); `changed` runs
    /// after each successful write so the panel rereads at once.
    init(
        paths: TelltalePaths, calendar: Calendar = .current, now: @escaping @MainActor () -> Date = Date.init,
        kickstart: @escaping @Sendable () throws -> Void, changed: @escaping @MainActor () -> Void = {}, sourceNames: [ProviderID: String] = [:]
    ) {
        self.paths = paths
        self.calendar = calendar
        self.now = now
        self.kickstart = kickstart
        self.changed = changed
        self.sourceNames = sourceNames
    }

    /// "Check now": one collector run outside its schedule. launchctl runs off the main actor.
    func checkNow() async throws {
        let kickstart = kickstart
        try await Task.detached { try kickstart() }.value
    }

    /// Spec section 8's "Accept as usual…" from `since`.
    func accept(provider: ProviderID, model: String, since: LocalDay) throws -> Acceptance {
        try write { store in
            try BaselineEngine(store: store, calendar: calendar).accept(provider: provider, providerName: sourceName(provider), model: model, since: since, at: now())
        }
    }

    func undo(epochID: Int64) throws {
        try write { store in
            let name = try store.baselineEpoch(id: epochID).map { sourceName($0.provider) }
            try BaselineEngine(store: store, calendar: calendar).undo(epochID: epochID, providerName: name, at: now())
        }
    }

    private func sourceName(_ provider: ProviderID) -> String {
        sourceNames[provider] ?? provider.rawValue
    }

    func keepAsAbnormal(_ prompt: ShiftPrompt) throws {
        try write { store in try ShiftDetector.keepAsAbnormal(prompt, at: now(), store: store) }
    }

    /// Stores a setting. Callers validate first (`RuleSettings.validationErrors()`, `Settings.intervalError`).
    func set<V>(_ key: SettingKey<V>, _ value: V) throws {
        try write { store in try store.set(key, value) }
    }

    func setWatched(_ list: [String], sources: [StatusSourceSummary]) throws {
        try write { store in
            try store.transaction {
                try store.set(.watchedComponents, list)
                var applied = try store.value(.watchedDefaultsApplied) ?? ["openai"]
                for source in sources where !applied.contains(source.id) { applied.append(source.id) }
                try store.set(.watchedDefaultsApplied, applied)
            }
        }
    }

    /// Asks the collector to rebuild derived data on its next run (spec section 7.3).
    func requestRebuild() throws {
        try write { store in try store.set(.rebuildRequestedAt, now()) }
    }

    func requestRebuild(provider: ProviderID) throws {
        try write { store in
            try store.transaction {
                var requests = try store.value(.providerRebuildRequests)
                requests[provider.rawValue] = now()
                try store.set(.providerRebuildRequests, requests)
            }
        }
    }

    func dismissArrival(provider: ProviderID) throws {
        try write { store in
            try store.transaction {
                var pending = try store.value(.pendingArrivals)
                pending.removeAll { $0 == provider.rawValue }
                var dismissed = try store.value(.dismissedArrivals)
                if !dismissed.contains(provider.rawValue) { dismissed.append(provider.rawValue) }
                try store.set(.pendingArrivals, pending)
                try store.set(.dismissedArrivals, dismissed)
            }
        }
    }

    /// Writes only into the database the collector created (ruling R27): a missing or uninitialized
    /// database throws `StoreError.notInitialized` and nothing is created.
    private func write<T>(_ body: (Store) throws -> T) throws -> T {
        let store: Store
        do {
            store = try Store.open(paths.database, mode: .readWriteExisting)
        } catch StoreError.unsupportedSchemaVersion(let version) where version < Store.currentSchemaVersion {
            throw DataUpdating()
        }
        let result = try body(store)
        changed()
        return result
    }
}
