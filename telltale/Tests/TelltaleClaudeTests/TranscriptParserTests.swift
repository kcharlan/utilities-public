import Foundation
import Testing
import TelltaleCore
import TelltaleTestSupport
@testable import TelltaleClaude

@Suite struct TranscriptParserTests {
    private let t0 = "2026-01-01T00:00:00Z"
    private let t1 = "2026-01-01T00:00:01Z"
    private let t2 = "2026-01-01T00:00:02Z"
    private let t3 = "2026-01-01T00:00:03Z"
    private func ingest(_ root: URL, _ text: String) throws -> IngestResult {
        _ = try TranscriptBuilder.file(root: root, text: text)
        return ClaudeUsageSource(roots: [root]).ingest(cursor: nil, backfillFrom: .distantPast, now: Date().addingTimeInterval(180))
    }
    @Test func multiLineMessageTakesLargestOutputAndFinalUsage() throws {
        try withScratchDirectory { root in
            let text = try TranscriptBuilder.user(t0) + TranscriptBuilder.assistant(t1, output: 500) +
                TranscriptBuilder.assistant(t2, output: 400, usageExtra: ["input_tokens": 20, "cache_read_input_tokens": 3, "cache_creation_input_tokens": 4])
            let result = try ingest(root, text)
            let response = try #require(result.batch.responses.first)
            #expect(result.batch.responses.count == 1)
            #expect(response.outputTokens == 500)
            #expect(response.inputTokens == 27)
            #expect(response.cachedInputTokens == 3)
        }
    }
    @Test func startIsLatestUserLineBetweenResponses() throws {
        try withScratchDirectory { root in
            let text = try TranscriptBuilder.user(t0) + TranscriptBuilder.assistant(t1) + TranscriptBuilder.user(t2) + TranscriptBuilder.assistant(t3, id: "msg_synthetic_02")
            let result = try ingest(root, text)
            #expect(result.batch.responses.count == 2)
            #expect(result.batch.responses.last?.start == ISO8601Time.date(t2))
        }
    }
    @Test func startFallsBackToPreviousEnd() throws {
        try withScratchDirectory { root in
            let text = try TranscriptBuilder.user(t0) + TranscriptBuilder.assistant(t1) + TranscriptBuilder.assistant(t3, id: "msg_synthetic_02")
            let result = try ingest(root, text)
            #expect(result.batch.responses.last?.start == ISO8601Time.date(t1))
        }
    }
    @Test func firstResponseWithoutStartIsDropped() throws {
        try withScratchDirectory { root in
            let result = try ingest(root, TranscriptBuilder.assistant(t1))
            #expect(result.batch.responses.isEmpty)
        }
    }
    @Test func fastModeKeysAsFastTier() throws {
        try withScratchDirectory { root in
            let result = try ingest(root, TranscriptBuilder.user(t0) + TranscriptBuilder.assistant(t1, usageExtra: ["speed": "fast", "service_tier": "standard"]))
            #expect(result.batch.responses.first?.serviceTier == "fast")
            #expect(result.batch.responses.first?.effort == nil)
        }
    }
    @Test func serverToolUseIsExcludedAndCounted() throws {
        try withScratchDirectory { root in
            let result = try ingest(root, TranscriptBuilder.user(t0) + TranscriptBuilder.assistant(t1, usageExtra: ["server_tool_use": ["web_search_requests": 1]]))
            #expect(result.batch.responses.isEmpty)
            #expect(result.batch.excludedServerToolResponses == 1)
        }
    }
    @Test func contentNeverReachesRecords() throws {
        try withScratchDirectory { root in
            let result = try ingest(root, TranscriptBuilder.user(t0) + TranscriptBuilder.assistant(t1))
            let encoded = try JSONEncoder().encode(result.batch.responses)
            #expect(!String(decoding: encoded, as: UTF8.self).contains(TranscriptBuilder.placeholder))
            #expect(!String(decoding: result.cursor, as: UTF8.self).contains(TranscriptBuilder.placeholder))
        }
    }
    @Test func partialTrailingLineWaits() throws {
        try withScratchDirectory { root in
            let prefix = try TranscriptBuilder.user(t0) + TranscriptBuilder.assistant(t1)
            let line = try TranscriptBuilder.assistant(t3, output: 600, usageExtra: ["input_tokens": 42])
            let file = try TranscriptBuilder.file(root: root, text: prefix + String(line.dropLast()))
            let source = ClaudeUsageSource(roots: [root])
            let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Date().addingTimeInterval(180))
            #expect(first.batch.responses.isEmpty)
            let handle = try FileHandle(forWritingTo: file)
            try handle.seekToEnd()
            try handle.write(contentsOf: Data("\n".utf8))
            try handle.close()
            let second = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Date().addingTimeInterval(180))
            #expect(second.batch.responses.count == 1)
            let response = try #require(second.batch.responses.first)
            #expect(response.start == ISO8601Time.date(t0))
            #expect(response.end == ISO8601Time.date(t3))
            #expect(response.outputTokens == 600)
            #expect(response.inputTokens == 42)
        }
    }
    @Test func subagentFilesHaveTheirOwnSession() throws {
        try withScratchDirectory { root in
            let text = try TranscriptBuilder.user(t0) + TranscriptBuilder.assistant(t1)
            _ = try TranscriptBuilder.file(root: root, text: text)
            let dir = root.appending(path: "projects/-Users-example-project/00000000-0000-4000-8000-000000000001/subagents")
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            try text.write(to: dir.appending(path: "agent-synthetic-01.jsonl"), atomically: true, encoding: .utf8)
            let result = ClaudeUsageSource(roots: [root]).ingest(cursor: nil, backfillFrom: .distantPast, now: Date().addingTimeInterval(180))
            #expect(result.batch.responses.count == 2)
            #expect(result.batch.responses.contains { $0.isSubagent && $0.sessionID.hasSuffix("/agent-synthetic-01") })
        }
    }
    @Test func messageStartsBeforeItsFirstUsageLine() throws {
        try withScratchDirectory { root in
            let early = try TranscriptBuilder.line(["type": "assistant", "timestamp": t1, "requestId": "req_synthetic_01", "message": ["id": "msg_synthetic_01", "model": "claude-opus-5-5"]])
            let text = try TranscriptBuilder.user(t0) + early + TranscriptBuilder.user(t2) + TranscriptBuilder.assistant(t3)
            let result = try ingest(root, text)
            #expect(result.batch.responses.count == 1)
            #expect(result.batch.responses.first?.start == ISO8601Time.date(t0))
        }
    }
    @Test func largeAttachmentLineIsNotDecoded() throws {
        try withScratchDirectory { root in
            let attachment = try TranscriptBuilder.line(["type": "attachment", "attachment": String(repeating: TranscriptBuilder.placeholder, count: 100_000), "nested": ["type": "user"]])
            let result = try ingest(root, attachment + TranscriptBuilder.user(t0) + TranscriptBuilder.assistant(t1))
            #expect(result.batch.responses.count == 1)
            #expect(!String(decoding: result.cursor, as: UTF8.self).contains(TranscriptBuilder.placeholder))
        }
    }
    @Test func toolResultInsideMessageDoesNotChangeStart() throws {
        try withScratchDirectory { root in
            let text = try TranscriptBuilder.user(t0) + TranscriptBuilder.assistant(t1) + TranscriptBuilder.user(t2) + TranscriptBuilder.assistant(t3)
            let result = try ingest(root, text)
            #expect(result.batch.responses.count == 1)
            #expect(result.batch.responses.first?.start == ISO8601Time.date(t0))
        }
    }
}

@Suite struct ClaudeEventTests {
    private let time = "2026-01-01T00:00:05Z"
    private func run(_ lines: [[String: Any]]) throws -> IngestResult {
        try withScratchDirectory { root in
            let text = try lines.map { try TranscriptBuilder.line($0) }.joined()
            _ = try TranscriptBuilder.file(root: root, text: text)
            return ClaudeUsageSource(roots: [root]).ingest(cursor: nil, backfillFrom: .distantPast, now: Date().addingTimeInterval(180))
        }
    }
    private func error(_ code: String, status: Int? = nil, id: String = "error-synthetic-01") -> [String: Any] {
        var line: [String: Any] = ["type": "assistant", "timestamp": time, "uuid": id, "isApiErrorMessage": true, "error": code, "message": ["model": "<synthetic>", "content": TranscriptBuilder.placeholder]]
        if let status { line["apiErrorStatus"] = status }
        return line
    }
    @Test func retryLinesBecomeRetryEvents() throws {
        let result = try run([["type": "system", "subtype": "api_error", "timestamp": time, "uuid": "retry-synthetic-01", "retryAttempt": 2, "maxRetries": 5, "error": ["status": 529]]])
        let event = try #require(result.batch.connectionEvents.first)
        #expect(event.kind == .retry && event.retries == 2 && event.maxRetries == 5 && event.detail.contains("529"))
    }
    @Test func exhaustedRetriesEndInOneFailedRequest() throws {
        let first: [String: Any] = ["type": "system", "subtype": "api_error", "timestamp": time, "uuid": "retry-synthetic-01", "retryAttempt": 1, "maxRetries": 2, "error": ["status": 529]]
        var second = first
        second["uuid"] = "retry-synthetic-02"
        second["retryAttempt"] = 2
        let result = try run([first, second, error("overloaded_error", status: 529)])
        #expect(result.batch.connectionEvents.count == 2)
        #expect(result.batch.failedTurns.count == 1)
    }
    @Test func providerFailuresHaveNormalizedCodesAndInstantTime() throws {
        let codes = [("overloaded_error", 529, "overloaded"), ("server_error", 500, "serverError"), ("timeout", 0, "timeout"), ("connection_error", 0, "connection")]
        for (code, status, expected) in codes {
            let result = try run([error(code, status: status == 0 ? nil : status)])
            let failure = try #require(result.batch.failedTurns.first)
            #expect(failure.errorCode == expected)
            #expect(failure.startedAt == ISO8601Time.date(time) && failure.completedAt == failure.startedAt)
            #expect(!failure.message.contains(TranscriptBuilder.placeholder))
        }
    }
    @Test func clientErrorsAreCountedNotRecorded() throws {
        let result = try run([error("authentication_error", status: 401)])
        #expect(result.batch.failedTurns.isEmpty)
        #expect(result.batch.excludedClientErrors == 1)
    }
    @Test func rateLimitBecomesFullUsageSnapshot() throws {
        var line = error("rate_limit", status: 429)
        line["quotaLimits"] = ["rateLimitType": "five_hour", "resetsAt": 1767229200, "status": "rejected"]
        let result = try run([line])
        #expect(result.batch.usageLimit?.usedPercent == 100 && result.batch.usageLimit?.windowMinutes == 300)
        #expect(result.batch.usageLimit?.resetsAt == Date(timeIntervalSince1970: 1767229200))
        #expect(result.batch.failedTurns.isEmpty)
    }
    @Test func compactionRequiresMetadata() throws {
        let good: [String: Any] = ["type": "system", "subtype": "compact_boundary", "uuid": "compact-synthetic-01", "timestamp": time, "compactMetadata": ["trigger": "auto", "preTokens": 1234, "postTokens": 200, "durationMs": 2500, "precomputed": true]]
        var bad = good
        bad["compactMetadata"] = ["preTokens": 100]
        let result = try run([good, bad])
        let record = try #require(result.batch.compactions.first)
        #expect(result.batch.compactions.count == 1 && record.tokensBefore == 1234 && record.tokensAfter == 200 && record.duration == 2.5 && record.precomputed)
        #expect(result.batch.invalidCompactions == 1)
    }
    @Test func missingUsageIsFormatProblem() throws {
        let result = try run([["type": "assistant", "timestamp": time, "message": ["id": "msg_synthetic_01", "model": "claude-opus-5-5"]]])
        if case .formatProblem = result.state {} else { Issue.record("Expected format problem") }
    }
    @Test func newestVersionIsSemantic() throws {
        let result = try run([["type": "system", "version": "2.10.0"], ["type": "system", "version": "2.9.0"]])
        #expect(result.batch.sourceVersion == "2.10.0")
        let prerelease = try run([["type": "system", "version": "2.10.0"], ["type": "system", "version": "2.10.0-beta.2"]])
        #expect(prerelease.batch.sourceVersion == "2.10.0")
    }
    @Test func noParsableTimestampIsFormatProblem() throws {
        let result = try run([["type": "user", "timestamp": "invalid"], ["type": "assistant", "timestamp": "invalid", "message": ["id": "msg_synthetic_01", "model": "claude-opus-5-5", "usage": ["output_tokens": 42]]]])
        if case .formatProblem = result.state {} else { Issue.record("Expected format problem") }
    }
    @Test func usageWithoutTimestampStillCountsAsUsage() throws {
        let result = try run([["type": "assistant", "message": ["id": "msg_synthetic_01", "model": "claude-opus-5-5", "usage": ["output_tokens": 42]]]])
        #expect(result.state == .ready)
    }
    @Test func duplicateFailureUUIDIsEmittedOnce() throws {
        let result = try run([error("server_error", status: 500), error("server_error", status: 500)])
        #expect(result.batch.failedTurns.count == 1)
    }
    @Test func eventsAfterDeferredResponseWaitForCursor() throws {
        try withScratchDirectory { root in
            let text = try TranscriptBuilder.user("2026-01-01T00:00:00Z") + TranscriptBuilder.assistant(time) + TranscriptBuilder.line(error("server_error", status: 500))
            _ = try TranscriptBuilder.file(root: root, text: text)
            let source = ClaudeUsageSource(roots: [root])
            let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Date())
            #expect(first.batch.failedTurns.isEmpty)
            let second = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Date().addingTimeInterval(180))
            #expect(second.batch.failedTurns.count == 1 && second.batch.failedTurns.first?.model == "claude-opus-5-5")
            let third = source.ingest(cursor: second.cursor, backfillFrom: .distantPast, now: Date().addingTimeInterval(180))
            #expect(third.batch.failedTurns.isEmpty)
        }
    }
}
