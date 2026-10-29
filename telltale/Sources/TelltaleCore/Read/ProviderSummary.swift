import Foundation

/// A usage provider's stored state and history, read together from one snapshot.
public struct ProviderSummary: Sendable, Equatable, Identifiable {
    public enum State: Sendable, Equatable {
        case normal, notSetUp(String), formatProblem(since: Date), backfilling(started: Date), rebuildRequested(at: Date)
    }
    public var provider: ProviderID
    public var name: String
    public var state: State
    public var sourceVersion: String?
    public var lastIngestAt: Date?
    public var oldestResponse: Date?
    public var lastBackfillFinished: Date?
    public var dataFolder: URL?
    public var id: ProviderID { provider }

    public static func load(store: Store, sources: [SourceSummary]) throws -> [ProviderSummary] {
        try store.transaction {
            let requests = try store.value(.providerRebuildRequests)
            let global = try store.value(.rebuildRequestedAt)
            return try sources.map { source in
                let key = source.provider.rawValue
                let row = try store.sourceState(key)
                let backfill = try store.backfill(unit: key)
                let state: State
                if let at = requests[key] ?? global { state = .rebuildRequested(at: at) }
                else if let backfill, backfill.finishedAt == nil { state = .backfilling(started: backfill.startedAt) }
                else if let row, case .formatProblem = row.state { state = .formatProblem(since: row.unavailableSince ?? row.updatedAt) }
                else if let row, case .notSetUp(let reason) = row.state { state = .notSetUp(reason) }
                else { state = .normal }
                let oldest = try store.query("SELECT MIN(end_at) FROM responses WHERE provider = ?", [.text(key)]) { $0.optionalDate(0) }.first ?? nil
                return ProviderSummary(provider: source.provider, name: source.name, state: state, sourceVersion: row?.version,
                    lastIngestAt: row?.updatedAt, oldestResponse: oldest, lastBackfillFinished: backfill?.finishedAt, dataFolder: source.dataFolder)
            }
        }
    }
}
