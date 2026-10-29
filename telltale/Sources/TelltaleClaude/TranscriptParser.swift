import Foundation
import TelltaleCore

private struct Line: Decodable {
    struct ErrorInfo: Decodable { var status: Int?; var type: String? }
    struct Quota: Decodable { var rateLimitType: String?; var resetsAt: Double?; var status: String? }
    struct Compact: Decodable { var trigger: CompactionTrigger?; var preTokens: Int?; var postTokens: Int?; var durationMs: Double?; var precomputed: Bool? }
    struct Message: Decodable {
        struct Usage: Decodable {
            struct Server: Decodable { var web_search_requests: Int?; var web_fetch_requests: Int? }
            struct Detail: Decodable { var thinking_tokens: Int? }
            var input_tokens: Int?; var cache_creation_input_tokens: Int?; var cache_read_input_tokens: Int?
            var output_tokens: Int?; var speed: String?; var service_tier: String?
            var server_tool_use: Server?; var output_tokens_details: Detail?
            var iterations: [Iteration]?
            struct Iteration: Decodable { var type: String? }
        }
        var id: String?; var model: String?; var usage: Usage?
        enum CodingKeys: String, CodingKey { case id, model, usage }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            id = try c.decodeIfPresent(String.self, forKey: .id)
            model = try c.decodeIfPresent(String.self, forKey: .model)
            usage = try? c.decodeIfPresent(Usage.self, forKey: .usage)
        }
    }
    var type: String?; var timestamp: String?; var requestId: String?; var effort: String?
    var isSidechain: Bool?; var version: String?; var message: Message?
    var subtype: String?; var uuid: String?; var isApiErrorMessage: Bool?
    var apiErrorStatus: Int?; var retryAttempt: Int?; var maxRetries: Int?
    var quotaLimits: Quota?; var compactMetadata: Compact?
    var error: String?; var errorInfo: ErrorInfo?
    enum CodingKeys: String, CodingKey { case type, timestamp, requestId, effort, isSidechain, version, message, subtype, uuid, isApiErrorMessage, apiErrorStatus, retryAttempt, maxRetries, quotaLimits, compactMetadata, error }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        type = try c.decodeIfPresent(String.self, forKey: .type); timestamp = try c.decodeIfPresent(String.self, forKey: .timestamp)
        requestId = try c.decodeIfPresent(String.self, forKey: .requestId); effort = try c.decodeIfPresent(String.self, forKey: .effort)
        isSidechain = try c.decodeIfPresent(Bool.self, forKey: .isSidechain); version = try c.decodeIfPresent(String.self, forKey: .version)
        message = try c.decodeIfPresent(Message.self, forKey: .message); subtype = try c.decodeIfPresent(String.self, forKey: .subtype)
        uuid = try c.decodeIfPresent(String.self, forKey: .uuid); isApiErrorMessage = try c.decodeIfPresent(Bool.self, forKey: .isApiErrorMessage)
        apiErrorStatus = try c.decodeIfPresent(Int.self, forKey: .apiErrorStatus); retryAttempt = try c.decodeIfPresent(Int.self, forKey: .retryAttempt)
        maxRetries = try c.decodeIfPresent(Int.self, forKey: .maxRetries); quotaLimits = try c.decodeIfPresent(Quota.self, forKey: .quotaLimits)
        compactMetadata = try? c.decodeIfPresent(Compact.self, forKey: .compactMetadata)
        error = try? c.decodeIfPresent(String.self, forKey: .error); errorInfo = try? c.decodeIfPresent(ErrorInfo.self, forKey: .error)
    }
}

struct TranscriptParse {
    var cursor: FileCursor
    var responses: [ResponseRecord] = []
    var excluded = 0
    var version: String?
    var failed: [FailedTurnRecord] = []
    var retries: [ConnectionEventRecord] = []
    var compactions: [CompactionRecord] = []
    var limit: UsageLimitSnapshot?
    var clientErrors = 0
    var invalidCompactions = 0
}

enum TranscriptParser {
    static func newer(_ a: String, than b: String?) -> Bool {
        guard !a.isEmpty else { return false }
        guard let b else { return true }
        guard !b.isEmpty else { return true }
        let left = a.split(separator: "+", maxSplits: 1, omittingEmptySubsequences: false)[0].split(separator: "-", maxSplits: 1, omittingEmptySubsequences: false)
        let right = b.split(separator: "+", maxSplits: 1, omittingEmptySubsequences: false)[0].split(separator: "-", maxSplits: 1, omittingEmptySubsequences: false)
        let base = String(left[0]).compare(String(right[0]), options: .numeric)
        if base != .orderedSame { return base == .orderedDescending }
        if left.count != right.count { return left.count == 1 }
        guard left.count == 2 else { return false }
        let l = left[1].split(separator: "."), r = right[1].split(separator: ".")
        for (x, y) in zip(l, r) where x != y {
            if let xi = Int(x), let yi = Int(y) { return xi > yi }
            if Int(x) != nil { return false }
            if Int(y) != nil { return true }
            return x > y
        }
        return l.count > r.count
    }
    private struct Pending {
        var id: String
        var model: String
        var start: Date?
        var end: Date
        var effort: String?
        var tier: String?
        var usage: Line.Message.Usage?
        var output: Int?
        var subagent: Bool
        var excluded: Bool
    }
    private static func eligible(_ data: Data) -> Bool {
        var depth = 0, index = data.startIndex
        while index < data.endIndex {
            let byte = data[index]
            if byte == 123 || byte == 91 { depth += 1; index += 1; continue }
            if byte == 125 || byte == 93 { depth -= 1; index += 1; continue }
            guard byte == 34 else { index += 1; continue }
            let start = index + 1
            index += 1
            var escaped = false
            while index < data.endIndex {
                let value = data[index]
                if escaped { escaped = false }
                else if value == 92 { escaped = true }
                else if value == 34 { break }
                index += 1
            }
            guard index < data.endIndex else { return false }
            let isType = depth == 1 && data[start..<index].elementsEqual("type".utf8)
            index += 1
            guard isType else { continue }
            while index < data.endIndex && [32, 9, 10, 13].contains(data[index]) { index += 1 }
            guard index < data.endIndex, data[index] == 58 else { continue }
            index += 1
            while index < data.endIndex && [32, 9, 10, 13].contains(data[index]) { index += 1 }
            guard index < data.endIndex, data[index] == 34 else { return false }
            index += 1
            let valueStart = index
            while index < data.endIndex && data[index] != 34 { index += 1 }
            guard index < data.endIndex else { return false }
            let value = data[valueStart..<index]
            return ["assistant", "user", "system"].contains { value.elementsEqual($0.utf8) }
        }
        return false
    }
    static func parse(file: TranscriptFile, cursor: FileCursor, now: Date) throws -> TranscriptParse {
        var result = TranscriptParse(cursor: cursor)
        var position = cursor.offset
        var pending: Pending?
        var checkpoint = cursor
        var checkpointResult = result
        let decoder = JSONDecoder()
        func excluded(_ usage: Line.Message.Usage) -> Bool {
            (usage.server_tool_use?.web_search_requests ?? 0) > 0 || (usage.server_tool_use?.web_fetch_requests ?? 0) > 0 ||
                (usage.iterations?.contains { $0.type == "advisor_message" } ?? false)
        }
        func finish() {
            guard let p = pending else { return }
            result.cursor.previousEnd = p.end
            result.cursor.model = p.model
            if p.excluded { result.excluded += 1; return }
            guard let start = p.start, let usage = p.usage, let output = p.output, (p.end.timeIntervalSince(start) * 1000).rounded() >= 300 else { return }
            result.responses.append(ResponseRecord(provider: .claude, model: p.model, effort: p.effort, serviceTier: p.tier,
                sessionID: file.sessionID, isSubagent: p.subagent, responseID: p.id, start: start, end: p.end,
                inputTokens: (usage.input_tokens ?? 0) + (usage.cache_creation_input_tokens ?? 0) + (usage.cache_read_input_tokens ?? 0),
                cachedInputTokens: usage.cache_read_input_tokens ?? 0, outputTokens: output,
                reasoningTokens: usage.output_tokens_details?.thinking_tokens))
        }
        let end = try LineReader.completeLines(of: file.url, from: cursor.offset) { data in
            let lineStart = position
            position += data.count + 1
            let beforeLine = result
            // Reject large unrelated records before decoding, without retaining their payloads.
            guard eligible(data),
                  let line = try? decoder.decode(Line.self, from: data) else { return }
            if let version = line.version, newer(version, than: result.cursor.version) { result.cursor.version = version; result.version = version }
            let at = line.timestamp.flatMap(ISO8601Time.date)
            if at != nil { result.cursor.sawTimestamp = true }
            if line.type == "user" { result.cursor.sawUser = true }
            if line.type == "assistant", line.isApiErrorMessage != true, line.message?.id != nil { result.cursor.sawAssistant = true }
            if line.type == "assistant", line.isApiErrorMessage != true, line.message?.usage?.output_tokens != nil { result.cursor.sawUsage = true }
            if line.type == "system", line.subtype == "compact_boundary" {
                if let id = line.uuid, let at, let compact = line.compactMetadata, let trigger = compact.trigger, let tokens = compact.preTokens {
                    result.compactions.append(CompactionRecord(provider: .claude, lineID: id, sessionID: file.sessionID, agentID: file.subagent ? file.url.deletingPathExtension().lastPathComponent : nil, at: at, trigger: trigger, tokensBefore: tokens, tokensAfter: compact.postTokens, duration: compact.durationMs.map { $0 / 1000 }, precomputed: compact.precomputed ?? false))
                } else { result.invalidCompactions += 1; result.cursor.sawInvalidCompaction = true }
                return
            }
            if line.type == "system", line.subtype == "api_error", let id = line.uuid, let at {
                let detail = line.errorInfo?.status.map { "HTTP \($0)" + ($0 == 529 ? " overloaded" : "") } ?? "connection error"
                result.retries.append(ConnectionEventRecord(provider: .claude, sourceID: id, at: at, kind: .retry, detail: detail, retries: line.retryAttempt, maxRetries: line.maxRetries)); return
            }
            if line.type == "assistant", line.isApiErrorMessage == true {
                let code = (line.error ?? line.errorInfo?.type ?? "").lowercased()
                let status = line.apiErrorStatus
                if status == 429 || code.contains("rate_limit") {
                    if let at, let quota = line.quotaLimits, let minutes = ["five_hour": 300, "seven_day": 10080][quota.rateLimitType ?? ""] {
                        let snapshot = UsageLimitSnapshot(provider: .claude, at: at, usedPercent: 100, windowMinutes: minutes, resetsAt: quota.resetsAt.map(Date.init(timeIntervalSince1970:)))
                        if result.limit == nil || at > result.limit!.at { result.limit = snapshot }
                    }
                } else {
                    let normalized: String?
                    if code.contains("overload") || status == 529 { normalized = "overloaded" }
                    else if code.contains("timeout") || code.contains("timed_out") { normalized = "timeout" }
                    else if code.contains("connection") { normalized = "connection" }
                    else if code.contains("server_error") || (status.map { (500...599).contains($0) } ?? false) { normalized = "serverError" }
                    else { normalized = nil }
                    if let normalized, let at, let id = line.uuid {
                        let message = ["overloaded": "model overloaded", "serverError": "server error", "timeout": "request timed out", "connection": "connection failed"][normalized]!
                        result.failed.append(FailedTurnRecord(provider: .claude, threadID: file.sessionID, turnID: id, startedAt: at, completedAt: at, model: pending?.model ?? result.cursor.model, errorCode: normalized, message: message))
                    } else if normalized == nil { result.clientErrors += 1 }
                }
                return
            }
            if line.type == "user", let at { result.cursor.pendingInput = at; return }
            guard line.type == "assistant", let message = line.message, let msg = message.id,
                  let model = message.model, model != "<synthetic>", let at else { return }
            let usage = message.usage
            let id = line.requestId.map { "\(msg)/\($0)" } ?? msg
            if var current = pending, current.id == id {
                current.end = at
                if let usage {
                    if let output = usage.output_tokens { current.output = max(current.output ?? output, output) }
                    current.usage = usage
                    current.excluded = current.excluded || excluded(usage)
                    current.tier = usage.speed == "fast" ? "fast" : usage.service_tier
                }
                current.subagent = current.subagent || (line.isSidechain ?? false)
                pending = current
                result.cursor.pendingInput = nil
            } else {
                finish()
                checkpoint = beforeLine.cursor
                checkpoint.previousEnd = result.cursor.previousEnd
                checkpoint.model = result.cursor.model
                checkpoint.offset = lineStart
                checkpointResult = result
                checkpointResult.version = beforeLine.version
                let start = result.cursor.pendingInput ?? result.cursor.previousEnd
                result.cursor.pendingInput = nil
                pending = Pending(id: id, model: model, start: start, end: at, effort: line.effort,
                    tier: usage?.speed == "fast" ? "fast" : usage?.service_tier, usage: usage, output: usage?.output_tokens,
                    subagent: file.subagent || (line.isSidechain ?? false), excluded: usage.map(excluded) ?? false)
            }
        }
        // A partial last line may be another block of the pending message, even in a quiet file.
        // Recheck size after reading so bytes appended during the read are also deferred.
        let attributes = try FileManager.default.attributesOfItem(atPath: file.url.path)
        let observedSize = (attributes[.size] as? NSNumber)?.intValue ?? file.size
        if pending != nil && (now.timeIntervalSince(file.modified) < 120 || end < max(file.size, observedSize)) {
            result = checkpointResult
            result.cursor = checkpoint
        } else {
            finish()
            result.cursor.offset = end
        }
        result.cursor.inode = file.inode
        result.cursor.size = observedSize
        return result
    }
}
