import Foundation
import Testing
import TelltaleCodex
import TelltaleCore
import TelltaleTestSupport

@Suite struct RetryLogSourceTests {
    private static let origin = RolloutBuilder.defaultOrigin
    private static func at(_ seconds: TimeInterval) -> Date { origin.addingTimeInterval(seconds) }

    private static func read(_ home: URL, after: Int64 = 0) throws -> (events: [ConnectionEventRecord], maxID: Int64, oldestRetained: Date?) {
        try RetryLogSource.read(codexHome: home, afterID: after)
    }

    @Test func parsesRetriesAndError() throws {
        try withScratchDirectory { home in
            let database = try CodexDatabase.logs(codexHome: home)
            let id = try database.addLog(
                at: Self.at(60.25),
                body: CodexDatabase.retryBody(retries: 2, maxRetries: 5, samplingError: CodexDatabase.disconnectError))

            let read = try Self.read(home)
            #expect(read.events == [
                ConnectionEventRecord(
                    provider: .codex, sourceID: "logs_2:\(id)", at: Self.at(60.25), kind: .disconnect,
                    detail: CodexDatabase.disconnectError, retries: 2, maxRetries: 5)
            ])
            #expect(read.maxID == id)
        }
    }

    @Test func classifiesWebsocketLimitAsReconnect() throws {
        // Its text also says "stream disconnected", so it must be recognized first.
        let error = "stream disconnected before completion: " + CodexDatabase.websocketLimitError
        for text in [CodexDatabase.websocketLimitError, error, error.uppercased()] {
            #expect(RetryLogSource.kind(of: text) == .reconnect, "\(text)")
        }
        try withScratchDirectory { home in
            let database = try CodexDatabase.logs(codexHome: home)
            try database.addLog(at: Self.at(1), body: CodexDatabase.retryBody(samplingError: error))
            #expect(try Self.read(home).events.map(\.kind) == [.reconnect])
        }
    }

    @Test func classifiesResetAsDisconnect() throws {
        #expect(RetryLogSource.kind(of: CodexDatabase.disconnectError) == .disconnect)
        #expect(RetryLogSource.kind(of: "stream disconnected before completion: synthetic") == .disconnect)
        #expect(RetryLogSource.kind(of: "WebSocket protocol error: Connection reset without closing handshake") == .disconnect)
        #expect(RetryLogSource.kind(of: "synthetic timeout talking to the server") == .retry)
        #expect(RetryLogSource.kind(of: "") == .retry)
    }

    @Test func onlyWarnRetryRowsRead() throws {
        try withScratchDirectory { home in
            let database = try CodexDatabase.logs(codexHome: home)
            let body = CodexDatabase.retryBody(samplingError: CodexDatabase.disconnectError)
            try database.addLog(at: Self.at(1), level: "INFO", body: body)
            try database.addLog(at: Self.at(2), level: "ERROR", body: body)
            try database.addLog(at: Self.at(3), level: "warn", body: body)
            try database.addLog(at: Self.at(4), target: "codex_core::other", body: body)
            let kept = try database.addLog(at: Self.at(5), body: body)

            let read = try Self.read(home)
            #expect(read.events.map(\.sourceID) == ["logs_2:\(kept)"])
        }
    }

    @Test func incrementalByID() throws {
        try withScratchDirectory { home in
            let database = try CodexDatabase.logs(codexHome: home)
            let body = CodexDatabase.retryBody(samplingError: CodexDatabase.disconnectError)
            let first = try database.addLog(at: Self.at(1), body: body)
            let second = try database.addLog(at: Self.at(2), body: body)

            let one = try Self.read(home)
            #expect(one.events.count == 2)
            #expect(one.maxID == second)

            let none = try Self.read(home, after: one.maxID)
            #expect(none.events.isEmpty)
            #expect(none.maxID == second)

            let third = try database.addLog(at: Self.at(3), body: body)
            let two = try Self.read(home, after: one.maxID)
            #expect(two.events.map(\.sourceID) == ["logs_2:\(third)"])
            #expect(two.maxID == third)

            // A row of another kind moves maxID too, so later reads do not rescan past it.
            let other = try database.addLog(at: Self.at(4), level: "INFO", target: "codex_core::other", body: "synthetic")
            let skipped = try Self.read(home, after: two.maxID)
            #expect(skipped.events.isEmpty)
            #expect(skipped.maxID == other)
            #expect(first < second)
        }
    }

    @Test func reportsOldestRetainedRow() throws {
        try withScratchDirectory { home in
            let database = try CodexDatabase.logs(codexHome: home)
            #expect(try Self.read(home).oldestRetained == nil)  // an empty table
            #expect(try Self.read(home, after: 7).maxID == 7)

            let body = CodexDatabase.retryBody(samplingError: CodexDatabase.disconnectError)
            try database.addLog(at: Self.at(10.5), level: "INFO", target: "codex_core::other", body: "synthetic")
            let second = try database.addLog(at: Self.at(20), body: body)
            try database.addLog(at: Self.at(30), body: body)
            // Any row counts, not only retry rows.
            #expect(try Self.read(home).oldestRetained == Self.at(10.5))

            try database.pruneLogs(before: second)
            #expect(try Self.read(home).oldestRetained == Self.at(20))
        }
    }

    @Test func idsBelowTheCursorRestartFromTheBeginning() throws {
        try withScratchDirectory { home in
            // A fresh logs file: its ids start over, below the cursor from the old one.
            let database = try CodexDatabase.logs(codexHome: home, number: 3)
            let body = CodexDatabase.retryBody(samplingError: CodexDatabase.disconnectError)
            try database.addLog(at: Self.at(1), body: body)
            try database.addLog(at: Self.at(2), body: body)
            let read = try Self.read(home, after: 5_000)
            #expect(read.events.map(\.sourceID) == ["logs_3:1", "logs_3:2"])
            #expect(read.maxID == 2)
        }
    }

    @Test func highestNumberedDatabaseWins() throws {
        try withScratchDirectory { home in
            for number in [2, 10, 3] {
                let database = try CodexDatabase.logs(codexHome: home, number: number)
                try database.addLog(at: Self.at(1), body: CodexDatabase.retryBody(retries: number, samplingError: "synthetic"))
            }
            #expect(try Self.read(home).events.map(\.retries) == [10])
        }
    }

    @Test func fieldParsingIsStrict() throws {
        // max_retries is not retries, a missing field is nil, and later text cannot supply fields.
        let onlyMax = RetryLogSource.event(id: 1, source: "logs_2", at: Self.origin, body: "span max_retries=5 sampling_error=synthetic")
        #expect(onlyMax.retries == nil && onlyMax.maxRetries == 5 && onlyMax.detail == "synthetic")
        let planted = RetryLogSource.event(
            id: 2, source: "logs_2", at: Self.origin, body: "span retries=1 max_retries=5 sampling_error=boom retries=9 max_retries=9")
        #expect(planted.retries == 1 && planted.maxRetries == 5)
        #expect(planted.detail == "boom retries=9 max_retries=9")
        let bare = RetryLogSource.event(id: 3, source: "logs_2", at: Self.origin, body: "")
        #expect(bare.kind == .retry && bare.detail.isEmpty && bare.retries == nil && bare.maxRetries == nil)
        let tooLong = RetryLogSource.event(id: 4, source: "logs_2", at: Self.origin, body: "retries=1 sampling_error=" + String(repeating: "x", count: 1_000))
        #expect(tooLong.detail.count == RetryLogSource.maximumDetail)
    }

    @Test func missingColumnIsFormatProblem() throws {
        try withScratchDirectory { home in
            let database = try CodexDatabase.logs(codexHome: home, omitting: ["target"])
            try database.addLog(at: Self.at(1), body: "synthetic")
            let problem = try #require(throws: ReadOnlySQLite.FormatProblem.self) { try Self.read(home) }
            #expect(problem.detail.contains("target") && problem.detail.contains("logs_2.sqlite"))
        }
    }

    @Test func noDatabaseIsNoEvents() throws {
        try withScratchDirectory { home in
            let read = try Self.read(home, after: 42)
            #expect(read.events.isEmpty && read.maxID == 42 && read.oldestRetained == nil)
        }
    }
}
