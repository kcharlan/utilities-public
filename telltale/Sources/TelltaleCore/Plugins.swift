import Foundation

/// Display names and incident-title matching for a provider's models (spec sections 5 and 6.1).
public protocol ModelNaming: Sendable {
    func displayName(model: String) -> String
    func incidentTitle(_ title: String, names model: String) -> Bool
    func incidentTitleIsModelSpecific(_ title: String) -> Bool
}

extension ModelNaming {
    public func incidentTitleIsModelSpecific(_ title: String) -> Bool { false }
}

/// What one ingest run found.
public struct IngestBatch: Sendable {
    public var responses: [ResponseRecord]
    public var compactions: [CompactionRecord]
    public var failedTurns: [FailedTurnRecord]
    public var connectionEvents: [ConnectionEventRecord]
    public var connectionGaps: [DateInterval]
    public var usageLimit: UsageLimitSnapshot?
    public var sourceVersion: String?
    public var excludedServerToolResponses: Int
    public var excludedClientErrors = 0
    public var invalidCompactions = 0

    public init(
        responses: [ResponseRecord] = [], compactions: [CompactionRecord] = [], failedTurns: [FailedTurnRecord] = [],
        connectionEvents: [ConnectionEventRecord] = [], connectionGaps: [DateInterval] = [],
        usageLimit: UsageLimitSnapshot? = nil, sourceVersion: String? = nil, excludedServerToolResponses: Int = 0
    ) {
        self.responses = responses
        self.compactions = compactions
        self.failedTurns = failedTurns
        self.connectionEvents = connectionEvents
        self.connectionGaps = connectionGaps
        self.usageLimit = usageLimit
        self.sourceVersion = sourceVersion
        self.excludedServerToolResponses = excludedServerToolResponses
    }
}

extension IngestBatch {
    public func droppingBefore(_ cutoff: Date) -> (batch: IngestBatch, dropped: Int) {
        var batch = self
        batch.responses = responses.filter { $0.end >= cutoff }
        batch.compactions = compactions.filter { $0.at >= cutoff }
        batch.connectionEvents = connectionEvents.filter { $0.at >= cutoff }
        let dropped = responses.count - batch.responses.count + compactions.count - batch.compactions.count
            + connectionEvents.count - batch.connectionEvents.count
        return (batch, dropped)
    }
}

public struct IngestResult: Sendable {
    public var batch: IngestBatch
    public var cursor: Data
    public var state: SetupState

    public init(batch: IngestBatch, cursor: Data, state: SetupState) {
        self.batch = batch
        self.cursor = cursor
        self.state = state
    }
}

/// A provider whose usage the collector reads (spec section 5).
public protocol UsageSource: ModelNaming {
    var provider: ProviderID { get }
    var dataFolder: URL { get }
    var displayName: String { get }
    var statusSourceID: String { get }
    var signals: Set<Signal> { get }
    var failureNoun: String { get }
    var supportedRules: Set<RuleID> { get }
    /// Problems go in the result's `state`, not out as thrown errors.
    func ingest(cursor: Data?, backfillFrom: Date, now: Date) -> IngestResult
}

extension UsageSource {
    public var failureNoun: String { "turn" }
    public var supportedRules: Set<RuleID> { Set(RuleID.allCases).subtracting([.compactions]) }
}

public enum StatusFetch: Sendable {
    case full(components: [StatusComponent], incidents: [IncidentRecord])
    /// The summary failed but RSS answered (Task 6).
    case rssOnly([RSSItem])
}

public protocol StatusSource: Sendable {
    var id: String { get }
    var displayName: String { get }
    var defaultWatchedComponents: [String] { get }
    func fetch(known: [IncidentRecord]) async throws -> StatusFetch
}

extension StatusSource {
    public var defaultWatchedComponents: [String] { [] }
}
