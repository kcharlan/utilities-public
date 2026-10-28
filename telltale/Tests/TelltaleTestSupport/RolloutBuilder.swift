import Foundation

/// Builds conspicuously synthetic Codex rollouts (spec section 6.1) and writes them into a
/// scratch `codexHome` tree, plain or compressed. Each added line gets the next ordinal, starting
/// at 0, and a timestamp `seconds` after `origin`. Content-bearing fields hold only what the test
/// passes, so tests can plant markers in them.
public struct RolloutBuilder {
    /// 2026-01-01 00:00:00 UTC, an arbitrary fixed origin.
    public static let defaultOrigin = Date(timeIntervalSince1970: 1_767_225_600)

    public let sessionID: String
    public let origin: Date
    /// The JSON lines added so far, without newlines. `lines[n]` has ordinal `n`.
    public private(set) var lines: [String] = []

    /// A builder for session `00000000-0000-4000-8000-0000000000NN`, NN = `session`.
    public init(session: Int = 1, origin: Date = RolloutBuilder.defaultOrigin) {
        self.sessionID = RolloutBuilder.sessionID(session)
        self.origin = origin
    }

    public static func sessionID(_ number: Int) -> String {
        String(format: "00000000-0000-4000-8000-%012ld", number)
    }

    public static func responseID(_ number: Int) -> String {
        String(format: "resp_synthetic_%02ld", number)
    }

    /// The ordinal the next added line will get.
    public var nextOrdinal: Int { lines.count }

    public func date(_ seconds: TimeInterval) -> Date { origin.addingTimeInterval(seconds) }

    // MARK: Lines

    public mutating func sessionMeta(
        at seconds: TimeInterval = 0, cliVersion: String? = "0.0.0-synthetic", parentThreadID: String? = nil,
        forkedFromID: String? = nil, historyStartOrdinal: Int? = nil, instructions: String = "synthetic instructions"
    ) {
        var payload: [String: Any] = ["id": sessionID, "cwd": "/synthetic/project", "base_instructions": ["text": instructions]]
        payload["cli_version"] = cliVersion
        payload["parent_thread_id"] = parentThreadID
        payload["forked_from_id"] = forkedFromID
        payload["subagent_history_start_ordinal"] = historyStartOrdinal
        add("session_meta", at: seconds, payload)
    }

    public mutating func turnContext(at seconds: TimeInterval, model: String?, effort: String? = "medium", turn: String = "turn_synthetic_01") {
        var payload: [String: Any] = ["turn_id": turn, "cwd": "/synthetic/project"]
        payload["model"] = model
        payload["effort"] = effort
        add("turn_context", at: seconds, payload)
    }

    /// An `event_msg` `thread_settings_applied`. A nil tier omits the key.
    public mutating func threadSettings(at seconds: TimeInterval, serviceTier: String?) {
        var settings: [String: Any] = [:]
        settings["service_tier"] = serviceTier
        add("event_msg", at: seconds, ["type": "thread_settings_applied", "thread_settings": settings])
    }

    /// An input event: a `response_item` user `message`.
    public mutating func userMessage(at seconds: TimeInterval, text: String = "synthetic prompt") {
        add("response_item", at: seconds, [
            "type": "message", "role": "user", "content": [["type": "input_text", "text": text]]
        ])
    }

    /// An input event: `event_msg` `task_started`.
    public mutating func taskStarted(at seconds: TimeInterval, turn: String = "turn_synthetic_01") {
        add("event_msg", at: seconds, ["type": "task_started", "turn_id": turn])
    }

    /// An input event: a `function_call_output` (or `custom_tool_call_output` when `custom`).
    public mutating func toolOutput(at seconds: TimeInterval, custom: Bool = false, output: String = "synthetic output") {
        add("response_item", at: seconds, [
            "type": custom ? "custom_tool_call_output" : "function_call_output", "call_id": "call_synthetic", "output": output
        ])
    }

    /// Not an input event: a tool call with arguments.
    public mutating func toolCall(at seconds: TimeInterval, arguments: String = "{}") {
        add("response_item", at: seconds, [
            "type": "function_call", "name": "synthetic_tool", "call_id": "call_synthetic", "arguments": arguments
        ])
    }

    /// Not an input event: an assistant `message`.
    public mutating func assistantMessage(at seconds: TimeInterval, text: String = "synthetic answer") {
        add("response_item", at: seconds, [
            "type": "message", "role": "assistant", "content": [["type": "output_text", "text": text]]
        ])
    }

    /// Not an input event: a `reasoning` item.
    public mutating func reasoning(at seconds: TimeInterval, text: String = "synthetic reasoning") {
        add("response_item", at: seconds, [
            "type": "reasoning", "summary": [["type": "summary_text", "text": text]], "encrypted_content": text
        ])
    }

    /// A `token_usage_record` for `resp_synthetic_NN`. Its timestamp is the response end.
    public mutating func usage(
        at seconds: TimeInterval, response: Int, turn: String = "turn_synthetic_01", input: Int = 1_000,
        cached: Int = 200, output: Int = 500, reasoning: Int? = 50
    ) {
        var usage: [String: Any] = ["input_tokens": input, "cached_input_tokens": cached, "output_tokens": output]
        usage["reasoning_output_tokens"] = reasoning
        add("token_usage_record", at: seconds, [
            "response_id": RolloutBuilder.responseID(response), "turn_id": turn, "thread_id": sessionID,
            "session_id": sessionID, "usage": usage
        ])
    }

    /// An `event_msg` `token_count` carrying `rate_limits.primary`; `resetsAt` is epoch seconds.
    public mutating func tokenCount(at seconds: TimeInterval, usedPercent: Double, windowMinutes: Int, resetsAt: Date) {
        add("event_msg", at: seconds, [
            "type": "token_count",
            "info": ["last_token_usage": ["input_tokens": 1, "output_tokens": 1]],
            "rate_limits": ["primary": [
                "used_percent": usedPercent, "window_minutes": windowMinutes,
                "resets_at": Int(resetsAt.timeIntervalSince1970)
            ]]
        ])
    }

    /// Any other record, for drift and malformed-record cases.
    public mutating func record(_ type: String, at seconds: TimeInterval, payload: [String: Any]) {
        add(type, at: seconds, payload)
    }

    private mutating func add(_ type: String, at seconds: TimeInterval, _ payload: [String: Any]) {
        let line: [String: Any] = [
            "timestamp": RolloutBuilder.timestamp(date(seconds)), "ordinal": lines.count, "type": type, "payload": payload
        ]
        let data = try! JSONSerialization.data(withJSONObject: line, options: [.sortedKeys, .withoutEscapingSlashes])
        lines.append(String(decoding: data, as: UTF8.self))
    }

    /// Codex's timestamp form: UTC with milliseconds, e.g. `2026-01-01T00:00:00.000Z`. Rounded
    /// to the nearest millisecond (the formatter alone truncates, turning 2.3 s into 2.299).
    public static func timestamp(_ date: Date) -> String {
        let milliseconds = Int((date.timeIntervalSince1970 * 1000).rounded())
        let seconds = Date(timeIntervalSince1970: TimeInterval(milliseconds.quotientAndRemainder(dividingBy: 1000).quotient))
        let whole = Date.ISO8601FormatStyle().format(seconds)  // ...T00:00:02Z
        return String(whole.dropLast()) + String(format: ".%03ldZ", milliseconds % 1000)
    }

    // MARK: Files

    /// Lines `range` (all by default), each ending in a newline.
    public func encoded(_ range: Range<Int>? = nil) -> Data {
        let selected = range.map { Array(lines[$0]) } ?? lines
        return Data(selected.map { $0 + "\n" }.joined().utf8)
    }

    /// `rollout-<origin, UTC>-<session id>.jsonl`.
    public var plainFileName: String {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        let parts = calendar.dateComponents([.year, .month, .day, .hour, .minute, .second], from: origin)
        let stamp = String(
            format: "%04ld-%02ld-%02ldT%02ld-%02ld-%02ld", parts.year!, parts.month!, parts.day!, parts.hour!,
            parts.minute!, parts.second!)
        return "rollout-\(stamp)-\(sessionID).jsonl"
    }

    /// `sessions/YYYY/MM/DD` (origin's UTC date) or `archived_sessions` under `codexHome`.
    public func directory(codexHome: URL, archived: Bool = false) -> URL {
        if archived { return codexHome.appending(path: "archived_sessions", directoryHint: .isDirectory) }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        let parts = calendar.dateComponents([.year, .month, .day], from: origin)
        return codexHome.appending(
            path: String(format: "sessions/%04ld/%02ld/%02ld", parts.year!, parts.month!, parts.day!),
            directoryHint: .isDirectory)
    }

    /// Writes `data` (all lines by default) as the plain `.jsonl` and returns its URL.
    @discardableResult
    public func writePlain(_ data: Data? = nil, codexHome: URL, archived: Bool = false) throws -> URL {
        try write(data ?? encoded(), named: plainFileName, codexHome: codexHome, archived: archived)
    }

    /// Writes `data` (all lines by default) as a `.jsonl.zst` of stored zstd blocks and returns its URL.
    @discardableResult
    public func writeCompressed(_ data: Data? = nil, codexHome: URL, archived: Bool = false) throws -> URL {
        let frame = StoredZstdFrame.encode(data ?? encoded(), blockSize: StoredZstdFrame.maxBlockSize)
        return try write(frame, named: plainFileName + ".zst", codexHome: codexHome, archived: archived)
    }

    private func write(_ data: Data, named name: String, codexHome: URL, archived: Bool) throws -> URL {
        let directory = directory(codexHome: codexHome, archived: archived)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let url = directory.appending(path: name)
        try data.write(to: url)
        return url
    }
}
