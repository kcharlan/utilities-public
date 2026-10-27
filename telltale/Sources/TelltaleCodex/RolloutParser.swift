import Foundation
import TelltaleCore

/// What one read of a rollout found.
public struct RolloutParse: Sendable, Equatable {
    /// Responses completed since the cursor, in file order.
    public var responses: [ResponseRecord]
    /// The latest `token_count` rate-limit snapshot read in this pass (spec section 6.4).
    public var usageLimit: UsageLimitSnapshot?
    /// `session_meta.payload.cli_version` from the first `session_meta` read in this pass (normally
    /// ordinal 0, so nil on resumed reads).
    public var cliVersion: String?
    /// Where to continue next time. Persist it only when the parse succeeded.
    public var cursor: SessionCursor
    /// A format problem (spec section 6.5) in plain words, without any line content.
    public var problem: String?

    public init(
        responses: [ResponseRecord], usageLimit: UsageLimitSnapshot?, cliVersion: String?, cursor: SessionCursor,
        problem: String?
    ) {
        self.responses = responses
        self.usageLimit = usageLimit
        self.cliVersion = cliVersion
        self.cursor = cursor
        self.problem = problem
    }
}

/// Turns Codex rollout lines into response records (spec section 6.1).
///
/// Each line is decoded only as far as the fields section 6.1 lists, so message text, reasoning,
/// tool arguments and tool output are never turned into values, and each line is dropped once
/// handled ("Never read").
public enum RolloutParser {
    /// Shorter responses are dropped: copied subagent history shows near-zero durations.
    public static let minimumDuration: TimeInterval = 0.3
    /// A session that ran a turn and reached this many lines without a `token_usage_record` has a
    /// format problem (plan call on the threshold).
    public static let missingUsageLineThreshold = 50

    /// False for a `.jsonl.zst` whose size and modification date match the cursor's, and for a
    /// plain file whose size equals the cursor's byte offset: nothing new to read.
    public static func needsRead(_ file: RolloutFile, cursor: SessionCursor?) -> Bool {
        guard let cursor else { return true }
        if file.compressed {
            return cursor.compressedSize != file.size || cursor.compressedModified != file.modified
        }
        return cursor.byteOffset != file.size
    }

    /// Reads the lines after `cursor` (from the start when nil).
    ///
    /// - A plain file is read from the cursor's byte offset, and only lines ending in a newline are
    ///   processed; a partial last line waits for the next run. If the file is now shorter than
    ///   the offset, it is read from the start and ordinals keep processed lines out.
    /// - A compressed file is read in full. Lines whose ordinal is at or below the cursor's are
    ///   skipped, so a plain file's cursor resumes on its compressed replacement.
    ///
    /// Throws when the file cannot be read (for `.zst`, `ZstdError`); nothing is emitted then and
    /// the cursor should stay as it was. Format problems do not throw: they are in `problem`.
    public static func parse(file: RolloutFile, cursor: SessionCursor?) throws -> RolloutParse {
        var reader = LineConsumer(sessionID: file.sessionID, cursor: cursor ?? SessionCursor())
        if file.compressed {
            try ZstdReader.lines(of: file.url, expectedSize: file.size) { _, line in reader.consume(line) }
            reader.cursor.byteOffset = nil
            reader.cursor.compressedSize = file.size
            reader.cursor.compressedModified = file.modified
        } else {
            let offset = try completeLines(of: file.url, from: reader.cursor.byteOffset ?? 0) { reader.consume($0) }
            reader.cursor.byteOffset = offset
            reader.cursor.compressedSize = nil
            reader.cursor.compressedModified = nil
        }
        reader.finish()
        return RolloutParse(
            responses: reader.responses, usageLimit: reader.usageLimit, cliVersion: reader.cliVersion,
            cursor: reader.cursor, problem: reader.problem)
    }

    private static let readChunkSize = 1 << 20

    /// Calls `body` with each newline-terminated line from `offset` on, without its newline, and
    /// returns the offset just after the last one.
    private static func completeLines(of url: URL, from offset: Int, _ body: (Data) -> Void) throws -> Int {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        let size = try handle.seekToEnd()
        var consumed = UInt64(offset) <= size ? offset : 0
        try handle.seek(toOffset: UInt64(consumed))
        var buffer = Data()
        while let chunk = try handle.read(upToCount: readChunkSize), !chunk.isEmpty {
            buffer.append(chunk)
            var lineStart = buffer.startIndex
            while let newline = buffer[lineStart...].firstIndex(of: 0x0A) {
                body(buffer[lineStart..<newline])
                consumed += newline - lineStart + 1
                lineStart = newline + 1
            }
            buffer.removeSubrange(buffer.startIndex..<lineStart)
        }
        return consumed
    }

    /// Codex timestamps are UTC with milliseconds; whole seconds are accepted too.
    static func date(_ text: String) -> Date? {
        if let date = try? Date.ISO8601FormatStyle(includingFractionalSeconds: true).parse(text) { return date }
        return try? Date.ISO8601FormatStyle().parse(text)
    }
}

/// Applies lines to a cursor and collects what they produce.
private struct LineConsumer {
    let sessionID: String
    var cursor: SessionCursor
    var responses: [ResponseRecord] = []
    var usageLimit: UsageLimitSnapshot?
    var cliVersion: String?
    var problem: String?
    private let decoder = JSONDecoder()

    init(sessionID: String, cursor: SessionCursor) {
        self.sessionID = sessionID
        self.cursor = cursor
    }

    mutating func consume(_ data: Data) {
        guard data.contains(where: { $0 != 0x20 && $0 != 0x09 && $0 != 0x0D }) else { return }  // blank
        guard let line = try? decoder.decode(RolloutLine.self, from: data), let ordinal = line.ordinal else {
            let after = cursor.lastOrdinal.map { "after ordinal \($0)" } ?? "at the start"
            note("a line \(after) is not a rollout record")
            return
        }
        if let last = cursor.lastOrdinal, ordinal <= last { return }  // already processed
        cursor.lastOrdinal = ordinal
        if let start = cursor.historyStartOrdinal, ordinal < start { return }  // copied parent history

        switch line.record {
        case .sessionMeta(let meta):
            if meta.isSubagent { cursor.isSubagent = true }
            if cursor.historyStartOrdinal == nil { cursor.historyStartOrdinal = meta.historyStartOrdinal }
            if cliVersion == nil { cliVersion = meta.cliVersion }
        case .turnContext(let model, let effort):
            cursor.model = model
            cursor.effort = effort
            cursor.sawTurn = true
        case .serviceTier(let tier):
            cursor.serviceTier = tier
        case .input(let startsTurn):
            if startsTurn { cursor.sawTurn = true }
            if let at = line.date { cursor.pendingStart = at }
        case .rateLimit(let limit):
            guard let at = line.date else { return }
            usageLimit = UsageLimitSnapshot(
                provider: .codex, at: at, usedPercent: limit.usedPercent, windowMinutes: limit.windowMinutes,
                resetsAt: limit.resetsAt)
        case .usage(let usage):
            record(usage, ordinal: ordinal, at: line.date)
        case .other:
            break
        }
    }

    /// Ends a response at a `token_usage_record` (spec section 6.1, Response start rule).
    private mutating func record(_ usage: UsageFields, ordinal: Int, at end: Date?) {
        cursor.sawUsage = true
        let start = cursor.pendingStart ?? cursor.lastUsageEnd
        cursor.pendingStart = nil
        guard let end else { return note("token_usage_record at ordinal \(ordinal) has no valid timestamp") }
        cursor.lastUsageEnd = end
        guard let responseID = usage.responseID else { return note("token_usage_record at ordinal \(ordinal) has no response_id") }
        guard let outputTokens = usage.outputTokens else {
            return note("token_usage_record at ordinal \(ordinal) has no usage.output_tokens")
        }
        guard let model = cursor.model, let start else { return }
        // Timestamps carry milliseconds; compare in whole milliseconds so 0.3 s is kept.
        let duration = end.timeIntervalSince(start)
        guard (duration * 1000).rounded() >= (RolloutParser.minimumDuration * 1000).rounded() else { return }
        responses.append(ResponseRecord(
            provider: .codex, model: model, effort: cursor.effort, serviceTier: cursor.serviceTier,
            sessionID: sessionID, isSubagent: cursor.isSubagent, turnID: usage.turnID, responseID: responseID,
            start: start, end: end, inputTokens: usage.inputTokens ?? 0, cachedInputTokens: usage.cachedInputTokens ?? 0,
            outputTokens: outputTokens, reasoningTokens: usage.reasoningTokens))
    }

    /// The 50-line check runs on the cursor, so it spans runs.
    mutating func finish() {
        let lines = (cursor.lastOrdinal ?? -1) + 1
        if cursor.sawTurn && !cursor.sawUsage && lines >= RolloutParser.missingUsageLineThreshold {
            note("session ran turns for \(lines) lines without a token_usage_record")
        }
    }

    /// Keeps the first problem found.
    private mutating func note(_ detail: String) {
        if problem == nil { problem = "Codex rollout \(sessionID): \(detail)" }
    }
}

// MARK: - Line decoding

/// One rollout line, decoded only as far as spec section 6.1's Records used table needs. Fields of
/// the wrong type read as absent.
private struct RolloutLine: Decodable {
    enum Record {
        case sessionMeta(SessionMetaFields)
        case turnContext(model: String?, effort: String?)
        /// A `thread_settings_applied` naming a tier, or null to clear it.
        case serviceTier(String?)
        case input(startsTurn: Bool)
        case rateLimit(RateLimitFields)
        case usage(UsageFields)
        case other
    }

    var ordinal: Int?
    var timestamp: String?
    var record: Record

    var date: Date? { timestamp.flatMap(RolloutParser.date) }

    init(from decoder: any Decoder) throws {
        let root = try decoder.container(keyedBy: AnyKey.self)
        ordinal = root.value("ordinal")
        timestamp = root.value("timestamp")
        let type: String? = root.value("type")
        guard let payload = root.object("payload") else {
            record = .other
            return
        }
        let payloadType: String? = payload.value("type")
        switch type {
        case "session_meta":
            record = .sessionMeta(SessionMetaFields(payload))
        case "turn_context":
            record = .turnContext(model: payload.value("model"), effort: payload.value("effort"))
        case "token_usage_record":
            record = .usage(UsageFields(payload))
        case "response_item":
            switch payloadType {
            case "function_call_output", "custom_tool_call_output": record = .input(startsTurn: false)
            case "message" where payload.value("role") as String? == "user": record = .input(startsTurn: false)
            default: record = .other
            }
        case "event_msg":
            switch payloadType {
            case "task_started":
                record = .input(startsTurn: true)
            case "thread_settings_applied":
                record = Self.serviceTier(payload.object("thread_settings"))
            case "token_count":
                record = RateLimitFields(payload.object("rate_limits")?.object("primary")).map(Record.rateLimit) ?? .other
            default:
                record = .other
            }
        default:
            record = .other
        }
    }

    /// A string tier sets it, an explicit null clears it, and anything else leaves it alone.
    private static func serviceTier(_ settings: KeyedDecodingContainer<AnyKey>?) -> Record {
        guard let settings, settings.contains(AnyKey("service_tier")) else { return .other }
        if let tier: String = settings.value("service_tier") { return .serviceTier(tier) }
        if (try? settings.decodeNil(forKey: AnyKey("service_tier"))) == true { return .serviceTier(nil) }
        return .other
    }
}

private struct SessionMetaFields {
    var isSubagent: Bool
    var historyStartOrdinal: Int?
    var cliVersion: String?

    init(_ payload: KeyedDecodingContainer<AnyKey>) {
        let parent: String? = payload.value("parent_thread_id")
        let forked: String? = payload.value("forked_from_id")
        isSubagent = parent != nil || forked != nil
        historyStartOrdinal = payload.value("subagent_history_start_ordinal")
        cliVersion = payload.value("cli_version")
    }
}

private struct UsageFields {
    var responseID: String?
    var turnID: String?
    var inputTokens: Int?
    var cachedInputTokens: Int?
    var outputTokens: Int?
    var reasoningTokens: Int?

    init(_ payload: KeyedDecodingContainer<AnyKey>) {
        responseID = payload.value("response_id")
        turnID = payload.value("turn_id")
        let usage = payload.object("usage")
        inputTokens = usage?.value("input_tokens")
        cachedInputTokens = usage?.value("cached_input_tokens")
        outputTokens = usage?.value("output_tokens")
        reasoningTokens = usage?.value("reasoning_output_tokens")
    }
}

private struct RateLimitFields {
    var usedPercent: Double
    var windowMinutes: Int
    var resetsAt: Date?

    /// Nil unless `used_percent` and `window_minutes` are present. `resets_at` is epoch seconds.
    init?(_ primary: KeyedDecodingContainer<AnyKey>?) {
        guard let primary, let usedPercent: Double = primary.value("used_percent"),
            let windowMinutes: Int = primary.value("window_minutes")
        else { return nil }
        self.usedPercent = usedPercent
        self.windowMinutes = windowMinutes
        resetsAt = (primary.value("resets_at") as Double?).map { Date(timeIntervalSince1970: $0) }
    }
}

private struct AnyKey: CodingKey {
    var stringValue: String
    var intValue: Int? { nil }

    init(_ name: String) { stringValue = name }
    init?(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { nil }
}

private extension KeyedDecodingContainer where Key == AnyKey {
    /// The value at `name`, or nil when it is absent, null or of another type.
    func value<T: Decodable>(_ name: String) -> T? {
        (try? decodeIfPresent(T.self, forKey: AnyKey(name))) ?? nil
    }

    func object(_ name: String) -> KeyedDecodingContainer<AnyKey>? {
        try? nestedContainer(keyedBy: AnyKey.self, forKey: AnyKey(name))
    }
}
