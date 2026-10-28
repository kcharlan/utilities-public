import Foundation

/// Where reading one Codex session stopped, and the state a later run needs to continue it
/// (spec section 6.1, Identity and resume). It is keyed by session id, not path, so a plain
/// file's cursor carries over to its `.jsonl.zst` replacement.
public struct SessionCursor: Codable, Equatable, Sendable {
    /// The last ordinal processed; nil when nothing has been processed yet.
    public var lastOrdinal: Int?
    /// Plain files: the byte just after the last complete line processed.
    public var byteOffset: Int?
    /// Compressed files: the size and modification date of the file last read in full.
    public var compressedSize: Int?
    public var compressedModified: Date?
    /// The latest input event since the previous `token_usage_record`, if any.
    public var pendingStart: Date?
    /// The previous `token_usage_record`'s time: the start when no input event followed it.
    public var lastUsageEnd: Date?
    /// The latest `turn_context` model and effort, and the latest applied service tier.
    public var model: String?
    public var effort: String?
    public var serviceTier: String?
    public var isSubagent: Bool
    /// `session_meta.payload.subagent_history_start_ordinal`: ordinals below it are copied history.
    public var historyStartOrdinal: Int?
    /// A turn ran (`turn_context` or `task_started`), and a `token_usage_record` was seen.
    public var sawTurn: Bool
    public var sawUsage: Bool

    public init(
        lastOrdinal: Int? = nil, byteOffset: Int? = nil, compressedSize: Int? = nil, compressedModified: Date? = nil,
        pendingStart: Date? = nil, lastUsageEnd: Date? = nil, model: String? = nil, effort: String? = nil,
        serviceTier: String? = nil, isSubagent: Bool = false, historyStartOrdinal: Int? = nil,
        sawTurn: Bool = false, sawUsage: Bool = false
    ) {
        self.lastOrdinal = lastOrdinal
        self.byteOffset = byteOffset
        self.compressedSize = compressedSize
        self.compressedModified = compressedModified
        self.pendingStart = pendingStart
        self.lastUsageEnd = lastUsageEnd
        self.model = model
        self.effort = effort
        self.serviceTier = serviceTier
        self.isSubagent = isSubagent
        self.historyStartOrdinal = historyStartOrdinal
        self.sawTurn = sawTurn
        self.sawUsage = sawUsage
    }
}
