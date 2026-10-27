import Foundation
import Testing
import TelltaleCodex
import TelltaleCore
import TelltaleTestSupport

@Suite struct ThreadHistorySourceTests {
    private static let origin = RolloutBuilder.defaultOrigin
    private static func at(_ seconds: TimeInterval) -> Date { origin.addingTimeInterval(seconds) }
    private static let capacity = CodexDatabase.errorJSON(code: "serverOverloaded", message: "Selected model is at capacity")

    @Test func failedRowsBecomeFailedTurns() throws {
        try withScratchDirectory { home in
            let database = try CodexDatabase.threadHistory(codexHome: home)
            try database.addTurn(thread: 1, turn: 1, status: "failed", errorJSON: Self.capacity, startedAt: Self.at(100), completedAt: Self.at(130))
            try database.addTurn(thread: 2, turn: 2, status: "failed", errorJSON: CodexDatabase.errorJSON(code: "cyberPolicy", message: "Synthetic policy message"), startedAt: Self.at(50))

            let turns = try ThreadHistorySource.read(codexHome: home, since: Self.at(0))
            #expect(turns == [
                FailedTurnRecord(
                    provider: .codex, threadID: "thread_synthetic_02", turnID: "turn_synthetic_02", startedAt: Self.at(50),
                    completedAt: nil, model: nil, errorCode: "cyberPolicy", message: "Synthetic policy message"),
                FailedTurnRecord(
                    provider: .codex, threadID: "thread_synthetic_01", turnID: "turn_synthetic_01", startedAt: Self.at(100),
                    completedAt: Self.at(130), model: nil, errorCode: "serverOverloaded", message: "Selected model is at capacity")
            ])
        }
    }

    @Test func nonFailedRowsIgnored() throws {
        try withScratchDirectory { home in
            let database = try CodexDatabase.threadHistory(codexHome: home)
            for (turn, status) in ["completed", "inProgress", "interrupted", "FAILED", "failed "].enumerated() {
                try database.addTurn(turn: turn + 1, status: status, errorJSON: Self.capacity, startedAt: Self.at(100))
            }
            #expect(try ThreadHistorySource.read(codexHome: home, since: Self.at(0)).isEmpty)
        }
    }

    @Test func rowsBeforeSinceAreExcluded() throws {
        try withScratchDirectory { home in
            let database = try CodexDatabase.threadHistory(codexHome: home)
            try database.addTurn(turn: 1, status: "failed", errorJSON: Self.capacity, startedAt: Self.at(99))
            try database.addTurn(turn: 2, status: "failed", errorJSON: Self.capacity, startedAt: Self.at(100))
            let turns = try ThreadHistorySource.read(codexHome: home, since: Self.at(100))
            #expect(turns.map(\.turnID) == ["turn_synthetic_02"])
        }
    }

    @Test func rescansLastTwoHours() throws {
        #expect(ThreadHistorySource.rescanWindow == 2 * 3600)
        let lastScan = Self.at(10 * 3600)
        #expect(ThreadHistorySource.rescanStart(after: lastScan) == Self.at(8 * 3600))

        try withScratchDirectory { home in
            // Codex writes a row when the turn starts and updates it when the turn ends.
            let database = try CodexDatabase.threadHistory(codexHome: home)
            try database.addTurn(turn: 1, status: "inProgress", startedAt: Self.at(9 * 3600))  // 1 h before the scan
            try database.addTurn(turn: 2, status: "inProgress", startedAt: Self.at(7 * 3600))  // 3 h before
            #expect(try ThreadHistorySource.read(codexHome: home, since: ThreadHistorySource.rescanStart(after: lastScan)).isEmpty)

            let end = Self.at(10 * 3600 + 60)
            try database.finishTurn(turn: 1, status: "failed", errorJSON: Self.capacity, completedAt: end)
            try database.finishTurn(turn: 2, status: "failed", errorJSON: Self.capacity, completedAt: end)
            let turns = try ThreadHistorySource.read(codexHome: home, since: ThreadHistorySource.rescanStart(after: lastScan))
            #expect(turns.map(\.turnID) == ["turn_synthetic_01"])
            #expect(turns.first?.completedAt == end)
        }
    }

    @Test func highestNumberedDatabaseWins() throws {
        try withScratchDirectory { home in
            // 10 beats 9 and 2 numerically, though "thread_history_2" sorts after "thread_history_10".
            for (number, turn) in [(1, 1), (2, 2), (10, 3), (9, 4)] {
                let database = try CodexDatabase.threadHistory(codexHome: home, number: number)
                try database.addTurn(turn: turn, status: "failed", errorJSON: Self.capacity, startedAt: Self.at(100))
            }
            let turns = try ThreadHistorySource.read(codexHome: home, since: Self.at(0))
            #expect(turns.map(\.turnID) == ["turn_synthetic_03"])
        }
    }

    @Test func missingColumnIsFormatProblem() throws {
        for column in ThreadHistorySource.columns {
            try withScratchDirectory { home in
                let database = try CodexDatabase.threadHistory(codexHome: home, omitting: [column])
                try database.addTurn(turn: 1, status: "failed", errorJSON: Self.capacity, startedAt: Self.at(100))
                let problem = try #require(throws: ReadOnlySQLite.FormatProblem.self) {
                    try ThreadHistorySource.read(codexHome: home, since: Self.at(0))
                }
                #expect(problem.detail.contains(column), "\(column)")
                #expect(problem.detail.contains("thread_history_1.sqlite"))
            }
        }
        try withScratchDirectory { home in
            let database = try CodexDatabase.threadHistory(codexHome: home)
            try database.execute("DROP TABLE thread_turns")
            #expect(throws: ReadOnlySQLite.FormatProblem.self) { try ThreadHistorySource.read(codexHome: home, since: Self.at(0)) }
        }
    }

    @Test func noDatabaseIsNoTurns() throws {
        try withScratchDirectory { home in
            let turns = try ThreadHistorySource.read(codexHome: home, since: Self.at(0))
            #expect(turns.isEmpty)
        }
    }

    @Test func unreadableErrorStillCountsAsFailedTurn() throws {
        try withScratchDirectory { home in
            let database = try CodexDatabase.threadHistory(codexHome: home)
            try database.addTurn(turn: 1, status: "failed", errorJSON: nil, startedAt: Self.at(1))
            try database.addTurn(turn: 2, status: "failed", errorJSON: "not json", startedAt: Self.at(2))
            try database.addTurn(turn: 3, status: "failed", errorJSON: "{\"message\":\"Synthetic text\"}", startedAt: Self.at(3))
            // A serialized enum with a payload: the variant name is the code.
            try database.addTurn(turn: 4, status: "failed", errorJSON: "{\"message\":\"m\",\"codexErrorInfo\":{\"synthetic_variant\":{\"n\":1}}}", startedAt: Self.at(4))

            let turns = try ThreadHistorySource.read(codexHome: home, since: Self.at(0))
            #expect(turns.map(\.errorCode) == ["unknown", "unknown", "unknown", "synthetic_variant"])
            #expect(turns.map(\.message) == ["", "", "Synthetic text", "m"])
        }
    }

    @Test func startFallsBackToCompletionAndRowsWithNoTimeAreSkipped() throws {
        try withScratchDirectory { home in
            let database = try CodexDatabase.threadHistory(codexHome: home)
            try database.addTurn(turn: 1, status: "failed", errorJSON: Self.capacity, startedAt: nil, completedAt: Self.at(40))
            try database.addTurn(turn: 2, status: "failed", errorJSON: Self.capacity, startedAt: nil)
            let turns = try ThreadHistorySource.read(codexHome: home, since: Self.at(0))
            #expect(turns.map(\.turnID) == ["turn_synthetic_01"])
            #expect(turns.first?.startedAt == Self.at(40))
        }
    }
}
