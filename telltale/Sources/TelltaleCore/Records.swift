import Foundation

// Normalized records shared by the provider plugins, the store, the rule engine and the UI
// (spec sections 4 to 6). All are plain values.

/// A usage provider's identifier. A string wrapper rather than an enum so later plugins can add ids.
public struct ProviderID: RawRepresentable, Sendable, Hashable, Codable {
    public let rawValue: String

    public init(rawValue: String) { self.rawValue = rawValue }

    public static let codex = ProviderID(rawValue: "codex")
    public static let claude = ProviderID(rawValue: "claude")

    public init(from decoder: any Decoder) throws {
        rawValue = try decoder.singleValueContainer().decode(String.self)
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }
}

public enum CompactionTrigger: String, Sendable, Codable { case auto, manual }

public struct CompactionRecord: Sendable, Equatable, Hashable, Codable {
    public var provider: ProviderID
    public var lineID: String
    public var sessionID: String
    public var agentID: String?
    public var at: Date
    public var trigger: CompactionTrigger
    public var tokensBefore: Int
    public var tokensAfter: Int?
    public var duration: TimeInterval?
    public var precomputed: Bool

    public init(provider: ProviderID, lineID: String, sessionID: String, agentID: String?, at: Date,
                trigger: CompactionTrigger, tokensBefore: Int, tokensAfter: Int?, duration: TimeInterval?, precomputed: Bool) {
        self.provider = provider; self.lineID = lineID; self.sessionID = sessionID; self.agentID = agentID
        self.at = at; self.trigger = trigger; self.tokensBefore = tokensBefore; self.tokensAfter = tokensAfter
        self.duration = duration; self.precomputed = precomputed
    }
}

/// One model response (spec section 6.1).
public struct ResponseRecord: Sendable, Equatable, Hashable, Codable {
    /// Throughput is computed only from this many output tokens up (spec section 6.1).
    public static let minimumThroughputTokens = 300

    public var provider: ProviderID
    public var model: String
    public var effort: String?
    public var serviceTier: String?
    public var sessionID: String
    public var isSubagent: Bool
    public var turnID: String?
    public var responseID: String
    public var start: Date
    public var end: Date
    public var inputTokens: Int
    public var cachedInputTokens: Int
    public var outputTokens: Int
    public var reasoningTokens: Int?

    public init(
        provider: ProviderID, model: String, effort: String? = nil, serviceTier: String? = nil,
        sessionID: String, isSubagent: Bool, turnID: String? = nil, responseID: String,
        start: Date, end: Date, inputTokens: Int, cachedInputTokens: Int, outputTokens: Int,
        reasoningTokens: Int? = nil
    ) {
        self.provider = provider
        self.model = model
        self.effort = effort
        self.serviceTier = serviceTier
        self.sessionID = sessionID
        self.isSubagent = isSubagent
        self.turnID = turnID
        self.responseID = responseID
        self.start = start
        self.end = end
        self.inputTokens = inputTokens
        self.cachedInputTokens = cachedInputTokens
        self.outputTokens = outputTokens
        self.reasoningTokens = reasoningTokens
    }

    /// End minus start: how long the user waited (queueing, first token and decoding).
    public var duration: TimeInterval { end.timeIntervalSince(start) }

    /// Output tokens per second, only for responses with at least 300 output tokens and a
    /// positive duration; shorter ones are dominated by fixed latency (spec section 6.1).
    public var throughput: Double? {
        guard outputTokens >= Self.minimumThroughputTokens, duration > 0 else { return nil }
        return Double(outputTokens) / duration
    }
}

/// A turn that ended in an error (spec section 6.2).
public struct FailedTurnRecord: Sendable, Equatable, Hashable, Codable {
    public var provider: ProviderID
    public var threadID: String
    public var turnID: String
    public var startedAt: Date
    public var completedAt: Date?
    public var model: String?
    public var errorCode: String
    public var message: String

    public init(
        provider: ProviderID, threadID: String, turnID: String, startedAt: Date, completedAt: Date? = nil,
        model: String? = nil, errorCode: String, message: String
    ) {
        self.provider = provider
        self.threadID = threadID
        self.turnID = turnID
        self.startedAt = startedAt
        self.completedAt = completedAt
        self.model = model
        self.errorCode = errorCode
        self.message = message
    }
}

public enum ConnectionKind: String, Sendable, Equatable, Hashable, Codable, CaseIterable {
    case disconnect, retry, reconnect
}

/// A disconnect, retry or reconnect seen in the provider's logs (spec section 6.3).
public struct ConnectionEventRecord: Sendable, Equatable, Hashable, Codable {
    public var provider: ProviderID
    public var sourceID: String
    public var at: Date
    public var kind: ConnectionKind
    public var detail: String
    public var retries: Int?
    public var maxRetries: Int?

    public init(
        provider: ProviderID, sourceID: String, at: Date, kind: ConnectionKind, detail: String,
        retries: Int? = nil, maxRetries: Int? = nil
    ) {
        self.provider = provider
        self.sourceID = sourceID
        self.at = at
        self.kind = kind
        self.detail = detail
        self.retries = retries
        self.maxRetries = maxRetries
    }
}

/// The provider's primary usage-limit window (spec section 6.4).
public struct UsageLimitSnapshot: Sendable, Equatable, Hashable, Codable {
    public var provider: ProviderID
    public var at: Date
    public var usedPercent: Double
    public var windowMinutes: Int
    public var resetsAt: Date?

    public init(provider: ProviderID, at: Date, usedPercent: Double, windowMinutes: Int, resetsAt: Date? = nil) {
        self.provider = provider
        self.at = at
        self.usedPercent = usedPercent
        self.windowMinutes = windowMinutes
        self.resetsAt = resetsAt
    }
}

/// Whether a usage source can read its data. Problems travel here rather than as thrown errors.
public enum SetupState: Sendable, Equatable, Hashable, Codable {
    case ready
    case notSetUp(String)
    case formatProblem(String)
    case readProblem(String)
}

/// The lamps. The UI labels `provider` with the status source's name.
public enum Signal: String, Sendable, Equatable, Hashable, Codable, CaseIterable {
    case speed, errors, link, provider, load, collector
}

public struct StatusComponent: Sendable, Equatable, Hashable, Codable {
    public var id: String
    public var name: String

    public init(id: String, name: String) {
        self.id = id
        self.name = name
    }
}

public struct ComponentImpact: Sendable, Equatable, Hashable, Codable {
    public var componentID: String
    public var status: String
    public var start: Date
    public var end: Date?

    public init(componentID: String, status: String, start: Date, end: Date? = nil) {
        self.componentID = componentID
        self.status = status
        self.start = start
        self.end = end
    }
}

public struct StatusChange: Sendable, Equatable, Hashable, Codable {
    public var at: Date
    public var status: String

    public init(at: Date, status: String) {
        self.at = at
        self.status = status
    }
}

/// A status-page incident (spec section 10).
public struct IncidentRecord: Sendable, Equatable, Hashable, Codable {
    public var source: String
    public var id: String
    public var name: String
    public var status: String
    public var publishedAt: Date
    public var updatedAt: Date
    public var link: URL
    public var history: [StatusChange]
    public var impacts: [ComponentImpact]

    public init(
        source: String, id: String, name: String, status: String, publishedAt: Date, updatedAt: Date,
        link: URL, history: [StatusChange], impacts: [ComponentImpact]
    ) {
        self.source = source
        self.id = id
        self.name = name
        self.status = status
        self.publishedAt = publishedAt
        self.updatedAt = updatedAt
        self.link = link
        self.history = history
        self.impacts = impacts
    }

    /// True for status `resolved` or `postmortem`.
    public var isResolved: Bool { status == "resolved" || status == "postmortem" }

    /// When the incident ended: the start of the final run of resolved or postmortem statuses in
    /// its history, or its last update when the history doesn't say. Nil while it is open. The one
    /// definition the rule engine, the store's overlap query and the dashboard's bands share, so a
    /// later postmortem update doesn't move the end.
    public var resolvedAt: Date? {
        guard isResolved else { return nil }
        var start: Date?
        for change in history.sorted(by: { $0.at < $1.at }) {
            if change.status == "resolved" || change.status == "postmortem" {
                start = start ?? change.at
            } else {
                start = nil
            }
        }
        return start ?? updatedAt
    }
}

public struct RSSItem: Sendable, Equatable, Hashable, Codable {
    public var title: String
    public var link: URL
    public var publishedAt: Date

    public init(title: String, link: URL, publishedAt: Date) {
        self.title = title
        self.link = link
        self.publishedAt = publishedAt
    }
}
