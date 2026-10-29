import Foundation
import Testing
import TelltaleCodex
import TelltaleCore
import TelltaleTestSupport

@Suite struct CodexUsageSourceTests {
    private static let origin = RolloutBuilder.defaultOrigin
    private static func at(_ seconds: TimeInterval) -> Date { origin.addingTimeInterval(seconds) }
    private static let sol = "gpt-6.1-sol"
    private static let capacity = CodexDatabase.errorJSON(code: "serverOverloaded", message: "Selected model is at capacity")
    private static let disconnect = CodexDatabase.retryBody(samplingError: CodexDatabase.disconnectError)

    /// A session with one response (ordinal-complete) and a usage-limit snapshot.
    private static func session(
        _ number: Int = 1, response: Int? = nil, version: String = "0.0.0-synthetic", percent: Double = 10, limitAt: TimeInterval = 13
    ) -> RolloutBuilder {
        var builder = RolloutBuilder(session: number)
        builder.sessionMeta(cliVersion: version)
        builder.turnContext(at: 1, model: sol)
        builder.userMessage(at: 2)
        builder.usage(at: 12, response: response ?? number)
        builder.tokenCount(at: limitAt, usedPercent: percent, windowMinutes: 300, resetsAt: builder.date(3_600))
        return builder
    }

    private static func source(_ home: URL) -> CodexUsageSource {
        CodexUsageSource(codexHome: home, busyTimeout: .milliseconds(20))
    }

    private static func cursor(_ result: IngestResult) throws -> CodexCursor {
        try #require(CodexCursor.decode(result.cursor))
    }

    // MARK: Identity

    @Test func declaresCodex() {
        let source = CodexUsageSource(codexHome: URL(fileURLWithPath: "/nonexistent-synthetic"))
        #expect(source.provider == .codex)
        #expect(source.displayName == "Codex")
        #expect(source.statusSourceID == "openai")
        #expect(source.signals == [.speed, .errors, .link, .provider, .load])
        #expect(source.displayName(model: Self.sol) == "6.1 Sol")
        #expect(source.incidentTitle("GPT-6.1 Sol Codex", names: Self.sol))
        #expect(!source.incidentTitle("GPT-6.1 Terra Codex", names: Self.sol))
    }

    // MARK: Composition

    @Test func composesAllReaders() throws {
        try withScratchDirectory { home in
            try Self.session(1).writePlain(codexHome: home)
            try Self.session(2, version: "0.1.0-synthetic", percent: 42, limitAt: 14).writeCompressed(codexHome: home, archived: true)
            let history = try CodexDatabase.threadHistory(codexHome: home)
            try history.addTurn(turn: 1, status: "failed", errorJSON: Self.capacity, startedAt: Self.at(100))
            try history.addTurn(turn: 2, status: "completed", startedAt: Self.at(200))
            let logs = try CodexDatabase.logs(codexHome: home)
            let id = try logs.addLog(at: Self.at(300), body: Self.disconnect)

            let source = Self.source(home)
            let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(3_600))
            #expect(first.state == .ready)
            #expect(first.batch.responses.map(\.responseID).sorted() == [RolloutBuilder.responseID(1), RolloutBuilder.responseID(2)])
            #expect(first.batch.responses.allSatisfy { $0.provider == .codex && $0.model == Self.sol })
            #expect(first.batch.failedTurns.map(\.turnID) == ["turn_synthetic_01"])
            #expect(first.batch.connectionEvents.map(\.sourceID) == ["logs_2:\(id)"])
            #expect(first.batch.connectionGaps.isEmpty)
            // The newest snapshot and the version of the most recently modified session file.
            #expect(first.batch.usageLimit?.usedPercent == 42)
            #expect(first.batch.usageLimit?.provider == .codex)
            #expect(first.batch.sourceVersion != nil)

            let stored = try Self.cursor(first)
            #expect(stored.sessions.keys.sorted() == [RolloutBuilder.sessionID(1), RolloutBuilder.sessionID(2)])
            #expect(stored.threadHistorySince == Self.at(3_600))
            #expect(stored.logsAfterID == id)
            #expect(stored.logsLastSeen == Self.at(3_600))

            // A second run finds nothing new in rollouts or the log; failed turns are rescanned.
            let second = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Self.at(3_700))
            #expect(second.state == .ready)
            #expect(second.batch.responses.isEmpty)
            #expect(second.batch.connectionEvents.isEmpty)
            #expect(second.batch.usageLimit == nil)
            #expect(try Self.cursor(second).threadHistorySince == Self.at(3_700))
        }
    }

    @Test func versionComesFromTheNewestFile() throws {
        try withScratchDirectory { home in
            let older = try Self.session(1, version: "0.1.0-synthetic").writePlain(codexHome: home)
            let newer = try Self.session(2, version: "0.2.0-synthetic").writePlain(codexHome: home)
            try FileManager.default.setAttributes([.modificationDate: Self.at(100)], ofItemAtPath: older.path)
            try FileManager.default.setAttributes([.modificationDate: Self.at(200)], ofItemAtPath: newer.path)
            let result = Self.source(home).ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(300))
            #expect(result.batch.sourceVersion == "0.2.0-synthetic")
        }
    }

    @Test func rolloutFailureStillReturnsFailedTurns() throws {
        try withScratchDirectory { home in
            let broken = try Self.session(1).writeCompressed(codexHome: home)
            try Data("this is not a zstd frame".utf8).write(to: broken)
            try Self.session(2).writePlain(codexHome: home)
            let history = try CodexDatabase.threadHistory(codexHome: home)
            try history.addTurn(turn: 1, status: "failed", errorJSON: Self.capacity, startedAt: Self.at(100))
            let logs = try CodexDatabase.logs(codexHome: home)
            try logs.addLog(at: Self.at(300), body: Self.disconnect)

            let result = Self.source(home).ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(3_600))
            guard case .formatProblem(let detail) = result.state else {
                Issue.record("expected a format problem, got \(result.state)")
                return
            }
            #expect(detail.contains("rollout") && detail.contains(RolloutBuilder.sessionID(1)))
            #expect(result.batch.failedTurns.count == 1)
            #expect(result.batch.connectionEvents.count == 1)
            // The healthy session is read; the broken one has no cursor, so it is retried.
            #expect(result.batch.responses.map(\.responseID) == [RolloutBuilder.responseID(2)])
            #expect(try Self.cursor(result).sessions.keys.sorted() == [RolloutBuilder.sessionID(2)])
        }
    }

    @Test func eachDatabaseProblemNamesItsPartAndOthersStillRead() throws {
        try withScratchDirectory { home in
            try Self.session(1).writePlain(codexHome: home)
            let history = try CodexDatabase.threadHistory(codexHome: home, omitting: ["error_json"])
            try history.addTurn(turn: 1, status: "failed", startedAt: Self.at(100))
            let logs = try CodexDatabase.logs(codexHome: home, omitting: ["target"])
            try logs.addLog(at: Self.at(300), body: Self.disconnect)

            let result = Self.source(home).ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(3_600))
            // Rollouts read, so the first problem is the failed-turns table.
            guard case .formatProblem(let detail) = result.state else {
                Issue.record("expected a format problem, got \(result.state)")
                return
            }
            #expect(detail.contains("failed turns") && detail.contains("error_json"))
            #expect(result.batch.responses.count == 1)
            let stored = try Self.cursor(result)
            #expect(stored.threadHistorySince == nil && stored.logsAfterID == nil && stored.logsLastSeen == nil)
        }
        try withScratchDirectory { home in
            let logs = try CodexDatabase.logs(codexHome: home, omitting: ["target"])
            try logs.addLog(at: Self.at(300), body: Self.disconnect)
            guard case .formatProblem(let detail) = Self.source(home).ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(1)).state else {
                Issue.record("expected a format problem")
                return
            }
            #expect(detail.contains("connection log") && detail.contains("target"))
        }
    }

    @Test func formatProblemIsNotPersisted() throws {
        try withScratchDirectory { home in
            var builder = Self.session(1)
            builder.record("token_usage_record", at: 20, payload: ["usage": ["output_tokens": 1]])  // malformed
            try builder.writePlain(codexHome: home)

            let source = Self.source(home)
            let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(100))
            guard case .formatProblem = first.state else {
                Issue.record("expected a format problem, got \(first.state)")
                return
            }
            #expect(first.batch.responses.count == 1)  // readable lines still count
            // Nothing new is parsed, so nothing re-reports: a later clean run is ready.
            let second = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Self.at(200))
            #expect(second.state == .ready)
            #expect(second.batch.responses.isEmpty)
        }
    }

    @Test func brokenFileRecoversWhenItIsReplaced() throws {
        try withScratchDirectory { home in
            let builder = Self.session(1)
            let url = try builder.writeCompressed(codexHome: home)
            try Data("this is not a zstd frame".utf8).write(to: url)

            let source = Self.source(home)
            let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(100))
            guard case .formatProblem = first.state else {
                Issue.record("expected a format problem, got \(first.state)")
                return
            }
            try builder.writeCompressed(codexHome: home)
            let second = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Self.at(200))
            #expect(second.state == .ready)
            #expect(second.batch.responses.count == 1)
        }
    }

    @Test func failedTurnsAreRescannedForTwoHoursOnly() throws {
        try withScratchDirectory { home in
            let history = try CodexDatabase.threadHistory(codexHome: home)
            try history.addTurn(turn: 1, status: "failed", errorJSON: Self.capacity, startedAt: Self.at(100))
            let source = Self.source(home)
            let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(1_000))
            #expect(first.batch.failedTurns.count == 1)
            // Within two hours of the last scan the row is read again; the store keeps one copy.
            let second = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Self.at(7_000))
            #expect(second.batch.failedTurns.count == 1)
            // The next scan starts two hours before the last (7000 s): -200 s, so 100 s is still in. By
            // the pass after 20000 s the scan starts at 12800 s, and the row is out.
            let third = source.ingest(cursor: second.cursor, backfillFrom: .distantPast, now: Self.at(20_000))
            #expect(third.batch.failedTurns.count == 1)
            let fourth = source.ingest(cursor: third.cursor, backfillFrom: .distantPast, now: Self.at(30_000))
            #expect(fourth.batch.failedTurns.isEmpty)
        }
    }

    // MARK: Busy

    @Test func busyReaderKeepsItsCursor() throws {
        try withScratchDirectory { home in
            try Self.session(1).writePlain(codexHome: home)
            let history = try CodexDatabase.threadHistory(codexHome: home, journal: .delete)
            try history.addTurn(turn: 1, status: "failed", errorJSON: Self.capacity, startedAt: Self.at(100))
            let logs = try CodexDatabase.logs(codexHome: home, journal: .delete)
            let firstID = try logs.addLog(at: Self.at(300), body: Self.disconnect)

            let source = Self.source(home)
            let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(1_000))
            #expect(first.state == .ready)
            let before = try Self.cursor(first)
            #expect(before.logsAfterID == firstID && before.threadHistorySince == Self.at(1_000))

            // Codex holds both files; a new rollout still reads.
            try history.beginExclusive()
            try logs.beginExclusive()
            try logs.addLog(at: Self.at(1_100), body: Self.disconnect)
            try Self.session(2).writePlain(codexHome: home)
            let busy = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Self.at(2_000))
            #expect(busy.state == .ready)  // skipped, not a problem
            #expect(busy.batch.connectionEvents.isEmpty && busy.batch.failedTurns.isEmpty)
            #expect(busy.batch.responses.map(\.responseID) == [RolloutBuilder.responseID(2)])
            let after = try Self.cursor(busy)
            #expect(after.logsAfterID == before.logsAfterID)
            #expect(after.logsLastSeen == before.logsLastSeen)
            #expect(after.threadHistorySince == before.threadHistorySince)
            #expect(after.sessions.count == 2)

            // Once Codex lets go, the skipped rows are read.
            try history.commit()
            try logs.commit()
            let later = source.ingest(cursor: busy.cursor, backfillFrom: .distantPast, now: Self.at(3_000))
            #expect(later.state == .ready)
            #expect(later.batch.connectionEvents.count == 1)
            #expect(try Self.cursor(later).logsAfterID == firstID + 1)
        }
    }

    @Test func closedDatabasesAreSkippedQuietlyAndReadAfterReopening() throws {
        try withScratchDirectory { home in
            try Self.session(1).writePlain(codexHome: home)
            let history = try CodexDatabase.threadHistory(codexHome: home)
            try history.addTurn(turn: 1, status: "failed", errorJSON: Self.capacity, startedAt: Self.at(100))
            let logs = try CodexDatabase.logs(codexHome: home)
            let firstID = try logs.addLog(at: Self.at(300), body: Self.disconnect)

            let source = Self.source(home)
            let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(1_000))
            #expect(first.state == .ready)
            let before = try Self.cursor(first)
            #expect(before.logsAfterID == firstID && before.threadHistorySince == Self.at(1_000))

            // Codex wrote more rows, then exited: both files are closed WAL databases.
            try history.addTurn(turn: 2, status: "failed", errorJSON: Self.capacity, startedAt: Self.at(1_100))
            try logs.addLog(at: Self.at(1_200), body: Self.disconnect)
            try history.closeLikeCodex()
            try logs.closeLikeCodex()

            let skipped = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Self.at(2_000))
            #expect(skipped.state == .ready)  // skipped, not a format problem
            #expect(skipped.batch.connectionEvents.isEmpty && skipped.batch.failedTurns.isEmpty)
            let after = try Self.cursor(skipped)
            #expect(after.logsAfterID == before.logsAfterID)
            #expect(after.logsLastSeen == before.logsLastSeen)
            #expect(after.threadHistorySince == before.threadHistorySince)
            for url in [history.url, logs.url] {
                #expect(!FileManager.default.fileExists(atPath: url.path + "-wal"))
            }

            // Once Codex reopens the files, the unread rows are read. The writers stay open across
            // the read, as Codex's do while it runs.
            let reopened = (try CodexDatabase.reopen(history.url), try CodexDatabase.reopen(logs.url))
            try withExtendedLifetime(reopened) {
                for url in [history.url, logs.url] {
                    #expect(FileManager.default.fileExists(atPath: url.path + "-wal"))
                }
                let later = source.ingest(cursor: skipped.cursor, backfillFrom: .distantPast, now: Self.at(3_000))
                #expect(later.state == .ready)
                #expect(later.batch.failedTurns.map(\.turnID).contains("turn_synthetic_02"))
                #expect(later.batch.connectionEvents.count == 1)
                let stored = try Self.cursor(later)
                #expect(stored.logsAfterID == firstID + 1)
            }
        }
    }

    /// A skip is not a good read: a file's format problem stays reported while Codex has it closed,
    /// so the problem's episode doesn't end and restart with every Codex session.
    @Test func closedDatabaseKeepsItsFormatProblem() throws {
        try withScratchDirectory { home in
            try Self.session(1).writePlain(codexHome: home)
            let history = try CodexDatabase.threadHistory(codexHome: home, omitting: ["error_json"])
            try history.addTurn(turn: 1, status: "failed", startedAt: Self.at(100))
            let logs = try CodexDatabase.logs(codexHome: home, omitting: ["target"])
            try logs.addLog(at: Self.at(300), body: Self.disconnect)

            let source = Self.source(home)
            let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(1_000))
            guard case .formatProblem(let detail) = first.state else {
                Issue.record("expected a format problem, got \(first.state)")
                return
            }
            #expect(detail.contains("failed turns") && detail.contains("error_json"))

            // Codex exits: both files are closed and skipped, and the problem is still reported.
            try history.closeLikeCodex()
            try logs.closeLikeCodex()
            let skipped = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Self.at(2_000))
            #expect(skipped.state == first.state)
            #expect(skipped.batch.failedTurns.isEmpty && skipped.batch.connectionEvents.isEmpty)
            let second = source.ingest(cursor: skipped.cursor, backfillFrom: .distantPast, now: Self.at(3_000))
            #expect(second.state == first.state)
            let kept = try Self.cursor(second)
            #expect(kept.threadHistoryProblem == detail)
            #expect(kept.logsProblem?.contains("connection log") == true && kept.logsProblem?.contains("target") == true)
            #expect(kept.threadHistorySince == nil && kept.logsAfterID == nil)

            // Codex reopens the files with the columns back: a good read clears each problem.
            let fixedHistory = try CodexDatabase.reopen(history.url)
            try fixedHistory.execute("ALTER TABLE thread_turns ADD COLUMN error_json TEXT")
            let fixedLogs = try CodexDatabase.reopen(logs.url)
            try fixedLogs.execute("ALTER TABLE logs ADD COLUMN target TEXT NOT NULL DEFAULT ''")
            try withExtendedLifetime((fixedHistory, fixedLogs)) {
                let later = source.ingest(cursor: second.cursor, backfillFrom: .distantPast, now: Self.at(4_000))
                #expect(later.state == .ready)
                #expect(later.batch.failedTurns.count == 1)
                let stored = try Self.cursor(later)
                #expect(stored.threadHistorySince == Self.at(4_000) && stored.logsLastSeen == Self.at(4_000))
                #expect(stored.threadHistoryProblem == nil && stored.logsProblem == nil)
            }
        }
    }

    @Test func keptProblemIsDroppedWhenCodexMovesToANewFile() throws {
        try withScratchDirectory { home in
            let old = try CodexDatabase.threadHistory(codexHome: home, omitting: ["error_json"])
            let source = Self.source(home)
            let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(100))
            #expect(try Self.cursor(first).threadHistoryProblemFile == "thread_history_1.sqlite")
            let newer = try CodexDatabase.threadHistory(codexHome: home, number: 2)
            try newer.closeLikeCodex()
            let result = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Self.at(200))
            #expect(result.state == .ready)
            #expect(try Self.cursor(result).threadHistoryProblem == nil)
            #expect(try Self.cursor(result).threadHistoryProblemFile == nil)
            _ = old
        }
    }

    @Test func keptProblemWithoutAFileStaysWithTheCurrentFile() throws {
        try withScratchDirectory { home in
            let history = try CodexDatabase.threadHistory(codexHome: home)
            try history.closeLikeCodex()
            let cursor = CodexCursor(threadHistoryProblem: "Codex failed turns: synthetic")
            let result = Self.source(home).ingest(cursor: cursor.encoded(), backfillFrom: .distantPast, now: Self.at(100))
            #expect(result.state == .formatProblem("Codex failed turns: synthetic"))
        }
    }

    @Test func transientReadFailureIsNotKept() throws {
        try withScratchDirectory { home in
            let history = try CodexDatabase.threadHistory(codexHome: home)
            try history.closeLikeCodex()
            #expect(chmod(history.url.path, 0o000) == 0)
            defer { chmod(history.url.path, 0o600) }
            let source = Self.source(home)
            let failed = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(100))
            guard case .formatProblem(let detail) = failed.state else { Issue.record("expected read failure"); return }
            #expect(detail.contains("couldn't be read"))
            #expect(try Self.cursor(failed).threadHistoryProblem == nil)
            #expect(chmod(history.url.path, 0o600) == 0)
            #expect(source.ingest(cursor: failed.cursor, backfillFrom: .distantPast, now: Self.at(200)).state == .ready)
        }
    }

    @Test func readFailureLeavesAnEarlierFormatProblemKept() throws {
        try withScratchDirectory { home in
            let history = try CodexDatabase.threadHistory(codexHome: home, omitting: ["error_json"])
            let source = Self.source(home)
            let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(100))
            try history.closeLikeCodex()
            #expect(chmod(history.url.path, 0o000) == 0)
            defer { chmod(history.url.path, 0o600) }
            let failed = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Self.at(200))
            #expect(failed.state == first.state)
            #expect(try Self.cursor(failed).threadHistoryProblem == Self.cursor(first).threadHistoryProblem)
            #expect(try Self.cursor(failed).threadHistoryProblemFile == "thread_history_1.sqlite")
        }
    }

    @Test func busyDatabaseKeepsItsFormatProblem() throws {
        try withScratchDirectory { home in
            let history = try CodexDatabase.threadHistory(codexHome: home, omitting: ["error_json"], journal: .delete)
            let source = Self.source(home)
            let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(100))
            try history.beginExclusive()
            let busy = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Self.at(200))
            #expect(busy.state == first.state)
            #expect(try Self.cursor(busy).threadHistoryProblemFile == "thread_history_1.sqlite")
            try history.commit()
        }
    }

    @Test func readFailureAfterFileChangeDropsTheOldFormatProblem() throws {
        try withScratchDirectory { home in
            let old = try CodexDatabase.threadHistory(codexHome: home, omitting: ["error_json"])
            let source = Self.source(home)
            let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(100))
            let newer = try CodexDatabase.threadHistory(codexHome: home, number: 2)
            try newer.closeLikeCodex()
            #expect(chmod(newer.url.path, 0o000) == 0)
            defer { chmod(newer.url.path, 0o600) }
            let failed = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Self.at(200))
            guard case .formatProblem(let detail) = failed.state else { Issue.record("expected read failure"); return }
            #expect(detail.contains("couldn't be read"))
            #expect(try Self.cursor(failed).threadHistoryProblem == nil)
            #expect(try Self.cursor(failed).threadHistoryProblemFile == nil)
            #expect(chmod(newer.url.path, 0o600) == 0)
            #expect(source.ingest(cursor: failed.cursor, backfillFrom: .distantPast, now: Self.at(300)).state == .ready)
            _ = old
        }
    }

    // MARK: Gaps

    @Test func gapRecordedWhenLogRetentionPassedCursor() throws {
        try withScratchDirectory { home in
            let logs = try CodexDatabase.logs(codexHome: home)
            try logs.addLog(at: Self.at(100), body: Self.disconnect)
            let source = Self.source(home)

            // The first run has no earlier read to compare with, so no gap.
            let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(1_000))
            #expect(first.batch.connectionGaps.isEmpty)

            // Still retained: the oldest row (100 s) predates the last read (1000 s).
            let second = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Self.at(1_100))
            #expect(second.batch.connectionGaps.isEmpty)

            // Rows from 1100 s to 5000 s were pruned unread; the oldest kept row is from 5000 s.
            let kept = try logs.addLog(at: Self.at(5_000), body: Self.disconnect)
            try logs.pruneLogs(before: kept)
            let third = source.ingest(cursor: second.cursor, backfillFrom: .distantPast, now: Self.at(6_000))
            #expect(third.batch.connectionGaps == [DateInterval(start: Self.at(1_100), end: Self.at(5_000))])
            #expect(third.batch.connectionEvents.map(\.sourceID) == ["logs_2:\(kept)"])
            #expect(try Self.cursor(third).logsLastSeen == Self.at(6_000))

            // The gap is reported once.
            let fourth = source.ingest(cursor: third.cursor, backfillFrom: .distantPast, now: Self.at(6_100))
            #expect(fourth.batch.connectionGaps.isEmpty)
        }
    }

    // MARK: Setup

    @Test func missingCodexHomeIsNotSetUp() throws {
        try withScratchDirectory { scratch in
            let home = scratch.appending(path: "absent", directoryHint: .isDirectory)
            let source = Self.source(home)
            let fresh = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(1))
            guard case .notSetUp(let reason) = fresh.state else {
                Issue.record("expected notSetUp, got \(fresh.state)")
                return
            }
            #expect(!reason.isEmpty)
            #expect(fresh.batch.responses.isEmpty && fresh.batch.failedTurns.isEmpty && fresh.batch.connectionEvents.isEmpty)
            #expect(CodexCursor.decode(fresh.cursor) == CodexCursor())
            #expect(!FileManager.default.fileExists(atPath: home.path))

            // An existing cursor is kept.
            let kept = CodexCursor(sessions: [:], threadHistorySince: Self.at(5), logsAfterID: 9, logsLastSeen: Self.at(6)).encoded()
            #expect(source.ingest(cursor: kept, backfillFrom: .distantPast, now: Self.at(10)).cursor == kept)

            // A file where the folder should be is not a Codex home either.
            let file = scratch.appending(path: "file")
            try Data().write(to: file)
            guard case .notSetUp = Self.source(file).ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(1)).state else {
                Issue.record("expected notSetUp for a file")
                return
            }
        }
    }

    @Test func emptyCodexHomeIsReady() throws {
        try withScratchDirectory { home in
            let result = Self.source(home).ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(1))
            #expect(result.state == .ready)
        }
    }

    // MARK: Cursor

    @Test func cursorDatesRoundTripExactly() throws {
        // File modification dates carry sub-millisecond fractions; ISO 8601 or millisecond forms
        // would lose them and needsRead would be true forever.
        let modified = Date(timeIntervalSince1970: 1_767_225_600.123456789)
        let session = SessionCursor(byteOffset: nil, compressedSize: 10, compressedModified: modified)
        let cursor = CodexCursor(sessions: ["s": session], threadHistorySince: modified, logsAfterID: 5, logsLastSeen: modified)
        let decoded = try #require(CodexCursor.decode(cursor.encoded()))
        #expect(decoded == cursor)
        #expect(decoded.sessions["s"]?.compressedModified == modified)
        #expect(decoded.sessions["s"]?.compressedModified?.timeIntervalSinceReferenceDate == modified.timeIntervalSinceReferenceDate)
        #expect(CodexCursor.decode(Data("not json".utf8)) == nil)
        #expect(CodexCursor.decode(nil) == nil)
    }

    /// A cursor stored by 0.2.0, before files' format problems were kept, still decodes, and a cursor
    /// with no kept problems encodes without their keys.
    @Test func cursorWithoutKeptProblemsDecodes() throws {
        let stored = Data(#"{"logsAfterID":9,"logsLastSeen":700000060.5,"sessions":{},"threadHistorySince":700000000.25}"#.utf8)
        let decoded = try #require(CodexCursor.decode(stored))
        #expect(decoded == CodexCursor(
            threadHistorySince: Date(timeIntervalSinceReferenceDate: 700_000_000.25), logsAfterID: 9,
            logsLastSeen: Date(timeIntervalSinceReferenceDate: 700_000_060.5)))
        #expect(decoded.threadHistoryProblem == nil && decoded.logsProblem == nil)
        #expect(decoded.encoded() == stored)

        var kept = decoded
        kept.threadHistoryProblem = "synthetic failed-turns problem"
        kept.logsProblem = "synthetic connection-log problem"
        #expect(CodexCursor.decode(kept.encoded()) == kept)
    }

    @Test func unchangedCompressedFilesAreSkipped() throws {
        try withScratchDirectory { home in
            let builder = Self.session(1)
            let url = try builder.writeCompressed(codexHome: home)
            // A modification date with nanoseconds, as APFS keeps.
            let modified = Date(timeIntervalSince1970: 1_767_225_600.123456789)
            try FileManager.default.setAttributes([.modificationDate: modified], ofItemAtPath: url.path)

            let source = Self.source(home)
            let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(100))
            #expect(first.state == .ready)
            #expect(first.batch.responses.count == 1)

            // The cursor, through its encoding, still says the file needs no read.
            let stored = try Self.cursor(first)
            let file = try #require(RolloutDiscovery.files(codexHome: home).first)
            #expect(!RolloutParser.needsRead(file, cursor: stored.sessions[file.sessionID]))

            // Prove it end to end: same size and date, different bytes. Reading it would fail.
            let size = try Data(contentsOf: url).count
            try Data(repeating: 0x41, count: size).write(to: url)
            try FileManager.default.setAttributes([.modificationDate: file.modified], ofItemAtPath: url.path)
            let second = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Self.at(200))
            #expect(second.state == .ready)
            #expect(second.batch.responses.isEmpty)
            #expect(try Self.cursor(second).sessions == stored.sessions)

            // A changed file is read again, and the broken contents are reported.
            try FileManager.default.setAttributes([.modificationDate: file.modified.addingTimeInterval(1)], ofItemAtPath: url.path)
            guard case .formatProblem = source.ingest(cursor: second.cursor, backfillFrom: .distantPast, now: Self.at(300)).state else {
                Issue.record("a changed file should be read again")
                return
            }
        }
    }

    @Test func vanishedSessionCursorIsDropped() throws {
        try withScratchDirectory { home in
            let gone = try Self.session(1).writePlain(codexHome: home)
            try Self.session(2).writePlain(codexHome: home)
            let source = Self.source(home)
            let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(100))
            #expect(try Self.cursor(first).sessions.count == 2)

            try FileManager.default.removeItem(at: gone)
            let second = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Self.at(200))
            #expect(second.state == .ready)
            #expect(try Self.cursor(second).sessions.keys.sorted() == [RolloutBuilder.sessionID(2)])
        }
    }

    // MARK: Backfill

    @Test func firstRunBackfillsOnlyRecentWork() throws {
        try withScratchDirectory { home in
            let old = try Self.session(1).writePlain(codexHome: home)
            let recent = try Self.session(2).writePlain(codexHome: home)
            try FileManager.default.setAttributes([.modificationDate: Self.at(100)], ofItemAtPath: old.path)
            try FileManager.default.setAttributes([.modificationDate: Self.at(5_000)], ofItemAtPath: recent.path)
            let history = try CodexDatabase.threadHistory(codexHome: home)
            try history.addTurn(turn: 1, status: "failed", errorJSON: Self.capacity, startedAt: Self.at(1_000))
            try history.addTurn(turn: 2, status: "failed", errorJSON: Self.capacity, startedAt: Self.at(4_000))

            let source = Self.source(home)
            let first = source.ingest(cursor: nil, backfillFrom: Self.at(3_000), now: Self.at(6_000))
            #expect(first.batch.responses.map(\.responseID) == [RolloutBuilder.responseID(2)])
            #expect(first.batch.failedTurns.map(\.turnID) == ["turn_synthetic_02"])
            #expect(try Self.cursor(first).sessions.keys.sorted() == [RolloutBuilder.sessionID(2)])

            // The old file stays unread on later runs: only changed or new work is picked up.
            let second = source.ingest(cursor: first.cursor, backfillFrom: Self.at(3_000), now: Self.at(7_000))
            #expect(second.batch.responses.isEmpty)
            #expect(try Self.cursor(second).sessions.keys.sorted() == [RolloutBuilder.sessionID(2)])
        }
    }

    // MARK: Safety

    @Test func codexFilesAreNotModified() throws {
        try withScratchDirectory { home in
            try Self.session(1).writePlain(codexHome: home)
            try Self.session(2).writeCompressed(codexHome: home)
            try Self.session(3).writeCompressed(codexHome: home, archived: true)
            let history = try CodexDatabase.threadHistory(codexHome: home)
            try history.addTurn(turn: 1, status: "failed", errorJSON: Self.capacity, startedAt: Self.at(100))
            let logs = try CodexDatabase.logs(codexHome: home)
            try logs.addLog(at: Self.at(300), body: Self.disconnect)

            let before = try FileSnapshot.take(home)
            let source = Self.source(home)
            let first = source.ingest(cursor: nil, backfillFrom: .distantPast, now: Self.at(3_600))
            _ = source.ingest(cursor: first.cursor, backfillFrom: .distantPast, now: Self.at(3_700))
            #expect(first.batch.responses.count == 3)
            #expect(first.batch.failedTurns.count == 1 && first.batch.connectionEvents.count == 1)
            #expect(try FileSnapshot.take(home) == before)
            #expect(before.count == 5)
        }
    }
}
