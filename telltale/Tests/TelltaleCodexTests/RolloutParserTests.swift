import Foundation
import Testing
import TelltaleCodex
import TelltaleCore
import TelltaleTestSupport

@Suite struct RolloutParserTests {
    static let sol = "gpt-6.1-sol"

    // MARK: Helpers

    /// The one rollout discovered under `home`.
    static func onlyFile(_ home: URL) throws -> RolloutFile {
        let files = RolloutDiscovery.files(codexHome: home)
        try #require(files.count == 1)
        return files[0]
    }

    static func parse(_ home: URL, cursor: SessionCursor? = nil) throws -> RolloutParse {
        try RolloutParser.parse(file: onlyFile(home), cursor: cursor)
    }

    static func ids(_ parse: RolloutParse) -> [String] { parse.responses.map(\.responseID) }

    static func ids(_ numbers: Int...) -> [String] { numbers.map(RolloutBuilder.responseID) }

    /// A started session: `session_meta` at ordinal 0, then Sol's `turn_context` at ordinal 1.
    static func session(_ number: Int = 1) -> RolloutBuilder {
        var builder = RolloutBuilder(session: number)
        builder.sessionMeta()
        builder.turnContext(at: 0.5, model: sol)
        return builder
    }

    // MARK: Response start rule

    @Test func responseStartIsLatestInputEventSincePreviousUsage() throws {
        try withScratchDirectory { home in
            var builder = Self.session()
            builder.taskStarted(at: 2)
            builder.userMessage(at: 3)
            builder.reasoning(at: 4)
            builder.usage(at: 10, response: 1)
            builder.toolOutput(at: 12)
            builder.toolCall(at: 13)  // not an input event
            builder.toolOutput(at: 14, custom: true)
            builder.assistantMessage(at: 15)  // not an input event
            builder.reasoning(at: 15.5)  // not an input event
            builder.usage(at: 20, response: 2)
            builder.userMessage(at: 21)
            builder.taskStarted(at: 22)
            builder.usage(at: 30, response: 3)
            try builder.writePlain(codexHome: home)

            let parse = try Self.parse(home)
            #expect(Self.ids(parse) == Self.ids(1, 2, 3))
            #expect(parse.responses.map(\.start) == [builder.date(3), builder.date(14), builder.date(22)])
            #expect(parse.responses.map(\.end) == [builder.date(10), builder.date(20), builder.date(30)])
            #expect(parse.problem == nil)
        }
    }

    @Test func firstUsageWithoutInputOrPreviousUsageEmitsNothing() throws {
        try withScratchDirectory { home in
            var builder = Self.session()
            builder.assistantMessage(at: 2)
            builder.usage(at: 5, response: 1)
            try builder.writePlain(codexHome: home)

            let parse = try Self.parse(home)
            #expect(parse.responses.isEmpty)
            #expect(parse.cursor.lastUsageEnd == builder.date(5))
            #expect(parse.cursor.sawUsage)
            #expect(parse.problem == nil)
        }
    }

    @Test func startFallsBackToPreviousUsageEnd() throws {
        try withScratchDirectory { home in
            var builder = Self.session()
            builder.userMessage(at: 1)
            builder.usage(at: 5, response: 1)
            builder.reasoning(at: 6)
            builder.usage(at: 9, response: 2)  // no input since response 1: starts at its end
            try builder.writePlain(codexHome: home)

            let parse = try Self.parse(home)
            #expect(Self.ids(parse) == Self.ids(1, 2))
            #expect(parse.responses.map(\.start) == [builder.date(1), builder.date(5)])
        }
    }

    @Test func subThresholdDurationsAreDropped() throws {
        try withScratchDirectory { home in
            #expect(RolloutParser.minimumDuration == 0.3)
            var builder = Self.session()
            builder.userMessage(at: 1)
            builder.usage(at: 1.299, response: 1)  // 0.299 s: dropped
            builder.userMessage(at: 2)
            builder.usage(at: 2.3, response: 2)  // exactly 0.3 s: kept
            builder.userMessage(at: 3)
            builder.usage(at: 3, response: 3)  // zero: dropped
            try builder.writePlain(codexHome: home)

            let parse = try Self.parse(home)
            #expect(Self.ids(parse) == Self.ids(2))
            #expect(parse.cursor.lastUsageEnd == builder.date(3))
        }
    }

    @Test func throughputOnlyFromThreeHundredOutputTokens() throws {
        try withScratchDirectory { home in
            var builder = Self.session()
            builder.userMessage(at: 10)
            builder.usage(at: 20, response: 1, output: 299)
            builder.userMessage(at: 30)
            builder.usage(at: 40, response: 2, output: 300)
            try builder.writePlain(codexHome: home)

            let parse = try Self.parse(home)
            // Both count as responses; only the second has a throughput.
            #expect(Self.ids(parse) == Self.ids(1, 2))
            #expect(parse.responses.map(\.throughput) == [nil, 30])
        }
    }

    // MARK: Model, effort, tier, identity

    @Test func modelAndEffortFollowLatestTurnContext() throws {
        try withScratchDirectory { home in
            var builder = RolloutBuilder(session: 1)
            builder.sessionMeta()
            builder.turnContext(at: 1, model: Self.sol, effort: "medium")
            builder.userMessage(at: 2)
            builder.usage(at: 5, response: 1, turn: "turn_synthetic_01", input: 10, cached: 4, output: 400, reasoning: 30)
            builder.turnContext(at: 6, model: "gpt-6-astra", effort: "high", turn: "turn_synthetic_02")
            builder.userMessage(at: 7)
            builder.usage(at: 9, response: 2, turn: "turn_synthetic_02", reasoning: nil)
            try builder.writePlain(codexHome: home)

            let parse = try Self.parse(home)
            #expect(parse.responses.map(\.model) == [Self.sol, "gpt-6-astra"])
            #expect(parse.responses.map(\.effort) == ["medium", "high"])
            #expect(parse.responses.map(\.turnID) == ["turn_synthetic_01", "turn_synthetic_02"])
            #expect(parse.cursor.model == "gpt-6-astra")
            #expect(parse.cursor.effort == "high")
            let first = try #require(parse.responses.first)
            #expect(first == ResponseRecord(
                provider: .codex, model: Self.sol, effort: "medium", serviceTier: nil,
                sessionID: RolloutBuilder.sessionID(1), isSubagent: false, turnID: "turn_synthetic_01",
                responseID: RolloutBuilder.responseID(1), start: builder.date(2), end: builder.date(5),
                inputTokens: 10, cachedInputTokens: 4, outputTokens: 400, reasoningTokens: 30))
            #expect(parse.responses.last?.reasoningTokens == nil)
        }
    }

    @Test func modelRequiredBeforeEmitting() throws {
        try withScratchDirectory { home in
            var builder = RolloutBuilder(session: 1)
            builder.sessionMeta()
            builder.userMessage(at: 1)
            builder.usage(at: 5, response: 1)  // no turn_context yet
            builder.turnContext(at: 6, model: Self.sol)
            builder.userMessage(at: 7)
            builder.usage(at: 9, response: 2)
            try builder.writePlain(codexHome: home)

            let parse = try Self.parse(home)
            #expect(Self.ids(parse) == Self.ids(2))
            #expect(parse.responses.first?.start == builder.date(7))
        }
    }

    @Test func serviceTierFollowsThreadSettingsApplied() throws {
        try withScratchDirectory { home in
            var builder = Self.session(1)
            builder.userMessage(at: 2)
            builder.usage(at: 4, response: 1)
            builder.threadSettings(at: 5, serviceTier: "priority")
            builder.userMessage(at: 6)
            builder.usage(at: 8, response: 2)
            builder.threadSettings(at: 9, serviceTier: "default")
            builder.userMessage(at: 10)
            builder.usage(at: 12, response: 3)
            try builder.writePlain(codexHome: home)

            let parse = try Self.parse(home)
            #expect(Self.ids(parse) == Self.ids(1, 2, 3))
            #expect(parse.responses.map(\.serviceTier) == [nil, "priority", "default"])
            #expect(parse.cursor.serviceTier == "default")
        }
        try withScratchDirectory { home in
            var builder = Self.session(2)
            builder.userMessage(at: 2)
            builder.usage(at: 4, response: 4)
            try builder.writePlain(codexHome: home)

            let parse = try Self.parse(home)
            #expect(Self.ids(parse) == Self.ids(4))
            #expect(parse.responses.map(\.serviceTier) == [nil])
            #expect(parse.cursor.serviceTier == nil)
        }
    }

    @Test func ordinalZeroSessionMetaIsRead() throws {
        try withScratchDirectory { home in
            var builder = RolloutBuilder(session: 1)
            builder.sessionMeta(cliVersion: "0.0.0-synthetic.7", parentThreadID: RolloutBuilder.sessionID(90))
            builder.turnContext(at: 1, model: Self.sol)
            builder.userMessage(at: 2)
            builder.usage(at: 5, response: 1)
            try builder.writePlain(codexHome: home)

            let parse = try Self.parse(home, cursor: nil)
            #expect(parse.cliVersion == "0.0.0-synthetic.7")
            #expect(parse.cursor.isSubagent)
            #expect(parse.responses.map(\.isSubagent) == [true])
            #expect(parse.responses.map(\.sessionID) == [RolloutBuilder.sessionID(1)])
            #expect(parse.cursor.lastOrdinal == 3)
        }
    }

    @Test func subagentFromParentThreadOrForkedFrom() throws {
        let cases: [(parent: String?, forked: String?, subagent: Bool)] = [
            (RolloutBuilder.sessionID(90), nil, true),
            (nil, RolloutBuilder.sessionID(91), true),
            (nil, nil, false)
        ]
        for (index, entry) in cases.enumerated() {
            try withScratchDirectory { home in
                var builder = RolloutBuilder(session: index + 1)
                builder.sessionMeta(parentThreadID: entry.parent, forkedFromID: entry.forked)
                builder.turnContext(at: 1, model: Self.sol)
                builder.userMessage(at: 2)
                builder.usage(at: 5, response: index + 1)
                try builder.writePlain(codexHome: home)

                let parse = try Self.parse(home)
                #expect(parse.cursor.isSubagent == entry.subagent)
                #expect(parse.responses.map(\.isSubagent) == [entry.subagent])
            }
        }
    }

    @Test func historyStartOrdinalSkipsCopiedPrefix() throws {
        try withScratchDirectory { home in
            var builder = RolloutBuilder(session: 2)
            builder.sessionMeta(forkedFromID: RolloutBuilder.sessionID(1), historyStartOrdinal: 5)  // ordinal 0
            // Ordinals 1-4: the parent's copied history, with rewritten timestamps.
            builder.turnContext(at: 1, model: "gpt-6-copied", effort: "low")  // 1
            builder.threadSettings(at: 1, serviceTier: "priority")  // 2
            builder.userMessage(at: 1)  // 3
            builder.usage(at: 1.5, response: 1)  // 4: copied, never emitted
            // The subagent's own records.
            builder.turnContext(at: 2, model: Self.sol, effort: "high")  // 5
            builder.usage(at: 3, response: 2)  // 6: no own input or own previous usage: nothing
            builder.userMessage(at: 4)  // 7
            builder.usage(at: 8, response: 3)  // 8
            try builder.writePlain(codexHome: home)

            let parse = try Self.parse(home)
            #expect(parse.cursor.historyStartOrdinal == 5)
            #expect(Self.ids(parse) == Self.ids(3))
            let response = try #require(parse.responses.first)
            #expect(response.model == Self.sol)
            #expect(response.effort == "high")
            #expect(response.serviceTier == nil)
            #expect(response.start == builder.date(4))
            #expect(response.isSubagent)
            #expect(parse.cursor.lastOrdinal == 8)
        }
    }

    // MARK: Cursors

    @Test func cursorResumesMidResponse() throws {
        try withScratchDirectory { home in
            var builder = Self.session()
            builder.threadSettings(at: 1, serviceTier: "priority")  // 2
            builder.userMessage(at: 2)  // 3: the response starts here, then the run stops
            builder.reasoning(at: 4)  // 4
            builder.usage(at: 9, response: 1)  // 5
            let firstPart = builder.encoded(0..<4)
            try builder.writePlain(firstPart, codexHome: home)

            let first = try Self.parse(home)
            #expect(first.responses.isEmpty)
            #expect(first.cursor.lastOrdinal == 3)
            #expect(first.cursor.byteOffset == firstPart.count)
            #expect(first.cursor.pendingStart == builder.date(2))
            #expect(first.cursor.model == Self.sol)
            #expect(first.cursor.serviceTier == "priority")

            try builder.writePlain(codexHome: home)
            let second = try Self.parse(home, cursor: first.cursor)
            #expect(Self.ids(second) == Self.ids(1))
            #expect(second.responses.first?.start == builder.date(2))
            #expect(second.responses.first?.model == Self.sol)
            #expect(second.responses.first?.serviceTier == "priority")
            #expect(second.cursor.pendingStart == nil)
            #expect(second.cursor.lastOrdinal == 5)
            #expect(second.cursor.byteOffset == builder.encoded().count)
            // Nothing new: nothing emitted again.
            let third = try Self.parse(home, cursor: second.cursor)
            #expect(third.responses.isEmpty)
            #expect(third.cursor == second.cursor)
        }
    }

    @Test func partialTrailingLineIsDeferredNotFailed() throws {
        try withScratchDirectory { home in
            var builder = Self.session()
            builder.userMessage(at: 1)  // 2
            builder.usage(at: 5, response: 1)  // 3
            builder.userMessage(at: 6)  // 4
            builder.usage(at: 10, response: 2)  // 5: being appended
            builder.userMessage(at: 11)  // 6
            builder.usage(at: 15, response: 3)  // 7
            let complete = builder.encoded(0..<5)
            let line5 = Data(builder.lines[5].utf8)

            // Codex is mid-write: half of ordinal 5's JSON, no newline.
            try builder.writePlain(complete + line5.prefix(line5.count / 2), codexHome: home)
            let first = try Self.parse(home)
            #expect(Self.ids(first) == Self.ids(1))
            #expect(first.problem == nil)
            #expect(first.cursor.lastOrdinal == 4)
            #expect(first.cursor.byteOffset == complete.count)
            #expect(first.cursor.pendingStart == builder.date(6))

            // The whole JSON object but still no newline: still deferred.
            try builder.writePlain(complete + line5, codexHome: home)
            let second = try Self.parse(home, cursor: first.cursor)
            #expect(Self.ids(second) == [])
            #expect(second.problem == nil)
            #expect(second.cursor == first.cursor)

            // The line completes and more follow: each response exactly once.
            try builder.writePlain(codexHome: home)
            let third = try Self.parse(home, cursor: second.cursor)
            #expect(Self.ids(third) == Self.ids(2, 3))
            #expect(third.responses.first?.start == builder.date(6))
            #expect(third.problem == nil)
            #expect(third.cursor.lastOrdinal == 7)
            #expect(third.cursor.byteOffset == builder.encoded().count)
        }
    }

    @Test func plainToCompressedHandoffResumesByOrdinal() throws {
        try withScratchDirectory { home in
            var builder = RolloutBuilder(session: 3)
            builder.sessionMeta(parentThreadID: RolloutBuilder.sessionID(90))  // 0
            builder.turnContext(at: 1, model: Self.sol, effort: "high")  // 1
            builder.threadSettings(at: 1.5, serviceTier: "priority")  // 2
            builder.userMessage(at: 2)  // 3
            builder.usage(at: 5, response: 1)  // 4
            builder.userMessage(at: 6)  // 5: last ordinal the plain file's run processes
            builder.usage(at: 10, response: 2)  // 6: half-written when the plain file was read
            builder.userMessage(at: 11)  // 7
            builder.usage(at: 15, response: 3)  // 8

            let processed = builder.encoded(0..<6)
            let line6 = Data(builder.lines[6].utf8)
            let plain = try builder.writePlain(processed + line6.prefix(10), codexHome: home)
            let first = try Self.parse(home)
            #expect(Self.ids(first) == Self.ids(1))
            #expect(first.cursor.lastOrdinal == 5)
            #expect(first.cursor.byteOffset == processed.count)
            #expect(first.cursor.pendingStart == builder.date(6))

            // Codex finishes the session, compresses it and deletes the plain file.
            try FileManager.default.removeItem(at: plain)
            try builder.writeCompressed(codexHome: home)
            let compressed = try Self.onlyFile(home)
            #expect(compressed.compressed)
            #expect(RolloutParser.needsRead(compressed, cursor: first.cursor))

            let second = try RolloutParser.parse(file: compressed, cursor: first.cursor)
            // Ordinals 0-5 are skipped by ordinal; responses 2 and 3 appear once each.
            #expect(Self.ids(second) == Self.ids(2, 3))
            let resumed = try #require(second.responses.first)
            #expect(resumed.start == builder.date(6))  // the pending start carried across files
            #expect(resumed.isSubagent)
            #expect(resumed.model == Self.sol)
            #expect(resumed.effort == "high")
            #expect(resumed.serviceTier == "priority")
            #expect(second.cliVersion == nil)  // ordinal 0 was not reread
            #expect(second.cursor.lastOrdinal == 8)
            #expect(second.cursor.byteOffset == nil)
            #expect(second.cursor.compressedSize == compressed.size)
            #expect(second.cursor.compressedModified == compressed.modified)
            #expect(!RolloutParser.needsRead(compressed, cursor: second.cursor))
            #expect(Self.ids(try RolloutParser.parse(file: compressed, cursor: second.cursor)) == [])
        }
    }

    @Test func unchangedCompressedFileIsNotReread() throws {
        try withScratchDirectory { home in
            var builder = Self.session()
            builder.userMessage(at: 1)
            builder.usage(at: 5, response: 1)
            try builder.writeCompressed(codexHome: home)
            let file = try Self.onlyFile(home)
            #expect(RolloutParser.needsRead(file, cursor: nil))

            let first = try RolloutParser.parse(file: file, cursor: nil)
            #expect(Self.ids(first) == Self.ids(1))
            #expect(first.cursor.compressedSize == file.size)
            #expect(first.cursor.compressedModified == file.modified)
            #expect(!RolloutParser.needsRead(file, cursor: first.cursor))

            // A replaced archive (different size) is read again, and only new ordinals emit.
            builder.userMessage(at: 6)
            builder.usage(at: 9, response: 2)
            try builder.writeCompressed(codexHome: home)
            let changed = try Self.onlyFile(home)
            #expect(RolloutParser.needsRead(changed, cursor: first.cursor))
            let second = try RolloutParser.parse(file: changed, cursor: first.cursor)
            #expect(Self.ids(second) == Self.ids(2))
        }
    }

    @Test func plainFileNeedsReadOnlyWhenItsSizeDiffers() throws {
        try withScratchDirectory { home in
            var builder = Self.session()
            builder.userMessage(at: 1)
            try builder.writePlain(codexHome: home)
            let file = try Self.onlyFile(home)
            #expect(RolloutParser.needsRead(file, cursor: nil))
            let parse = try RolloutParser.parse(file: file, cursor: nil)
            #expect(!RolloutParser.needsRead(file, cursor: parse.cursor))

            builder.usage(at: 4, response: 1)
            try builder.writePlain(codexHome: home)
            #expect(RolloutParser.needsRead(try Self.onlyFile(home), cursor: parse.cursor))
        }
    }

    // MARK: Usage limit

    @Test func usageLimitSnapshotFromTokenCount() throws {
        try withScratchDirectory { home in
            var builder = Self.session()
            let firstReset = builder.date(3_600)
            let secondReset = builder.date(7_200)
            builder.tokenCount(at: 3, usedPercent: 10, windowMinutes: 300, resetsAt: firstReset)
            builder.tokenCount(at: 7, usedPercent: 12.5, windowMinutes: 300, resetsAt: secondReset)
            // A token_count without rate limits leaves the latest snapshot alone.
            builder.record("event_msg", at: 8, payload: ["type": "token_count", "info": ["total_token_usage": ["output_tokens": 1]]])
            try builder.writePlain(codexHome: home)

            let parse = try Self.parse(home)
            #expect(parse.usageLimit == UsageLimitSnapshot(
                provider: .codex, at: builder.date(7), usedPercent: 12.5, windowMinutes: 300, resetsAt: secondReset))
        }
    }

    // MARK: Format problems

    @Test func missingTokenUsageRecordsIsFormatProblem() throws {
        // 50 lines with a turn and no token_usage_record: a format problem; 49 are not yet.
        for (lineCount, problem) in [(49, false), (50, true)] {
            try withScratchDirectory { home in
                var builder = Self.session()
                builder.taskStarted(at: 1)
                while builder.nextOrdinal < lineCount { builder.assistantMessage(at: 2) }
                try builder.writePlain(codexHome: home)

                let parse = try Self.parse(home)
                #expect(parse.cursor.sawTurn)
                #expect(!parse.cursor.sawUsage)
                #expect((parse.problem != nil) == problem, "\(lineCount) lines")
            }
        }
        // Many lines but no turn ever ran: not a problem.
        try withScratchDirectory { home in
            var builder = RolloutBuilder(session: 2)
            builder.sessionMeta()
            while builder.nextOrdinal < 80 { builder.assistantMessage(at: 2) }
            try builder.writePlain(codexHome: home)

            let parse = try Self.parse(home)
            #expect(!parse.cursor.sawTurn)
            #expect(parse.problem == nil)
        }
        // The count spans runs: the cursor carries sawTurn and the ordinal.
        try withScratchDirectory { home in
            var builder = Self.session(3)
            builder.taskStarted(at: 1)
            while builder.nextOrdinal < 50 { builder.assistantMessage(at: 2) }
            try builder.writePlain(builder.encoded(0..<30), codexHome: home)
            let first = try Self.parse(home)
            #expect(first.problem == nil)
            try builder.writePlain(codexHome: home)
            #expect(try Self.parse(home, cursor: first.cursor).problem != nil)
        }
    }

    @Test func malformedUsageRecordIsFormatProblem() throws {
        let malformed: [[String: Any]] = [
            ["turn_id": "turn_synthetic_01", "usage": ["input_tokens": 10, "output_tokens": 400]],  // no response_id
            ["response_id": RolloutBuilder.responseID(1), "usage": ["input_tokens": 10]],  // no output_tokens
            ["response_id": RolloutBuilder.responseID(1)]  // no usage at all
        ]
        for payload in malformed {
            try withScratchDirectory { home in
                var builder = Self.session()
                builder.userMessage(at: 1)
                builder.record("token_usage_record", at: 5, payload: payload)  // 3
                builder.userMessage(at: 6)
                builder.usage(at: 9, response: 2)  // 5
                try builder.writePlain(codexHome: home)

                let parse = try Self.parse(home)
                let problem = try #require(parse.problem)
                #expect(problem.contains("ordinal 3"))
                // The malformed record emits nothing; reading continues past it.
                #expect(Self.ids(parse) == Self.ids(2))
                #expect(parse.responses.first?.start == builder.date(6))
                #expect(parse.cursor.lastOrdinal == 5)
                #expect(parse.cursor.sawUsage)
            }
        }
    }

    @Test func lineThatIsNotARolloutRecordIsFormatProblem() throws {
        try withScratchDirectory { home in
            var builder = Self.session()
            builder.userMessage(at: 1)
            builder.usage(at: 5, response: 1)
            var data = builder.encoded(0..<3)
            data.append(Data("not json\n".utf8))
            data.append(builder.encoded(3..<4))
            try builder.writePlain(data, codexHome: home)

            let parse = try Self.parse(home)
            #expect(parse.problem != nil)
            #expect(Self.ids(parse) == Self.ids(1))
            #expect(parse.cursor.byteOffset == data.count)
        }
    }

    // MARK: Privacy

    @Test func noContentFieldsAreRetained() throws {
        let marker = "SYNTHETIC-CONTENT-MARKER-0451"
        try withScratchDirectory { home in
            var builder = RolloutBuilder(session: 1)
            builder.sessionMeta(instructions: marker)
            builder.turnContext(at: 0.5, model: Self.sol)
            builder.userMessage(at: 1, text: marker)
            builder.reasoning(at: 2, text: marker)
            builder.toolCall(at: 3, arguments: marker)
            builder.toolOutput(at: 4, output: marker)
            builder.toolOutput(at: 4.5, custom: true, output: marker)
            builder.assistantMessage(at: 5, text: marker)
            builder.usage(at: 9, response: 1)
            builder.record("token_usage_record", at: 10, payload: ["usage": ["output_tokens": 1], "note": marker])  // malformed
            builder.tokenCount(at: 11, usedPercent: 5, windowMinutes: 300, resetsAt: builder.date(600))
            try builder.writePlain(codexHome: home)
            #expect(String(decoding: builder.encoded(), as: UTF8.self).contains(marker))

            let parse = try Self.parse(home)
            #expect(Self.ids(parse) == Self.ids(1))
            #expect(parse.problem != nil)
            #expect(parse.usageLimit != nil)
            #expect(!String(describing: parse).contains(marker))
            #expect(!String(reflecting: parse).contains(marker))
            let encodedCursor = try JSONEncoder().encode(parse.cursor)
            #expect(!String(decoding: encodedCursor, as: UTF8.self).contains(marker))
            let encodedResponses = try JSONEncoder().encode(parse.responses)
            #expect(!String(decoding: encodedResponses, as: UTF8.self).contains(marker))
        }
    }
}
