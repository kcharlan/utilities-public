import Foundation

/// Display names and incident-title matching for a provider's models (spec sections 5 and 6.1).
public protocol ModelNaming: Sendable {
    func displayName(model: String) -> String
    func incidentTitle(_ title: String, names model: String) -> Bool
}

/// What one ingest run found.
public struct IngestBatch: Sendable {
    public var responses: [ResponseRecord]
    public var failedTurns: [FailedTurnRecord]
    public var connectionEvents: [ConnectionEventRecord]
    public var connectionGaps: [DateInterval]
    public var usageLimit: UsageLimitSnapshot?
    public var sourceVersion: String?

    public init(
        responses: [ResponseRecord] = [], failedTurns: [FailedTurnRecord] = [],
        connectionEvents: [ConnectionEventRecord] = [], connectionGaps: [DateInterval] = [],
        usageLimit: UsageLimitSnapshot? = nil, sourceVersion: String? = nil
    ) {
        self.responses = responses
        self.failedTurns = failedTurns
        self.connectionEvents = connectionEvents
        self.connectionGaps = connectionGaps
        self.usageLimit = usageLimit
        self.sourceVersion = sourceVersion
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
    var displayName: String { get }
    var statusSourceID: String { get }
    var signals: Set<Signal> { get }
    /// Problems go in the result's `state`, not out as thrown errors.
    func ingest(cursor: Data?, backfillFrom: Date, now: Date) -> IngestResult
}

public enum StatusFetch: Sendable {
    case full(components: [StatusComponent], incidents: [IncidentRecord])
    /// The summary failed but RSS answered (Task 6).
    case rssOnly([RSSItem])
}

public protocol StatusSource: Sendable {
    var id: String { get }
    var displayName: String { get }
    func fetch(known: [IncidentRecord]) async throws -> StatusFetch
}
