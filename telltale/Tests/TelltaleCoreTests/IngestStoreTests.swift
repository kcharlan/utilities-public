import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

@Suite struct IngestStoreTests {
    private static func makeStore(_ directory: URL) throws -> Store {
        try Store.open(directory.appending(path: "telltale.sqlite"), mode: .readWrite)
    }

    /// Spec section 6.1: a forked copy shows a near-zero duration, so the longer copy wins
    /// whichever file is ingested first.
    @Test func duplicateResponseKeepsLongerDuration() throws {
        let original = Synthetic.response(1, endingAt: 1_000, duration: 12, outputTokens: 600)
        var copy = original
        copy.start = Synthetic.at(999.9)
        copy.sessionID = "00000000-0000-4000-8000-000000000099"
        copy.isSubagent = true
        let window = Synthetic.at(0)...Synthetic.at(2_000)

        try withScratchDirectory { directory in
            let store = try Self.makeStore(directory)
            #expect(try store.upsert(responses: [original]) == 1)
            #expect(try store.upsert(responses: [copy]) == 0)
            #expect(try store.responses(provider: .codex, model: original.model, endingIn: window) == [original])
        }
        try withScratchDirectory { directory in
            let store = try Self.makeStore(directory)
            #expect(try store.upsert(responses: [copy]) == 1)
            #expect(try store.upsert(responses: [original]) == 1)
            #expect(try store.responses(provider: .codex, model: original.model, endingIn: window) == [original])
        }
        try withScratchDirectory { directory in
            // Both copies in one batch, in either order, and a re-ingest of the winner changes nothing.
            for batch in [[original, copy], [copy, original]] {
                let store = try Self.makeStore(directory)
                try store.upsert(responses: batch)
                #expect(try store.responses(provider: .codex, model: original.model, endingIn: window) == [original])
                #expect(try store.upsert(responses: [original]) == 0)
                try store.exec("DELETE FROM responses")
            }
        }
    }

    @Test func sameResponseIDUnderAnotherProviderIsADifferentRow() throws {
        try withScratchDirectory { directory in
            let store = try Self.makeStore(directory)
            let codex = Synthetic.response(1, endingAt: 100)
            let other = Synthetic.response(1, provider: Synthetic.otherProvider, endingAt: 100)
            #expect(try store.upsert(responses: [codex, other]) == 2)
            let window = Synthetic.at(0)...Synthetic.at(200)
            #expect(try store.responses(provider: .codex, model: codex.model, endingIn: window) == [codex])
            #expect(try store.responses(provider: Synthetic.otherProvider, model: codex.model, endingIn: window) == [other])
        }
    }

    @Test func optionalFieldsSurviveAStoreRoundTrip() throws {
        try withScratchDirectory { directory in
            let store = try Self.makeStore(directory)
            var full = Synthetic.response(1, endingAt: 100)
            full.serviceTier = "priority"
            full.reasoningTokens = 321
            var bare = Synthetic.response(2, endingAt: 200)
            bare.effort = nil
            bare.turnID = nil
            try store.upsert(responses: [full, bare])
            let found = try store.responses(provider: .codex, model: full.model, endingIn: Synthetic.at(0)...Synthetic.at(300))
            #expect(found == [full, bare])
        }
    }

    @Test func failedTurnUpdateReplacesButKeepsEvaluatedAt() throws {
        try withScratchDirectory { directory in
            let store = try Self.makeStore(directory)
            let first = Synthetic.failedTurn(1, message: "first")
            #expect(try store.upsert(failedTurns: [first]) == 1)
            try store.exec("UPDATE failed_turns SET evaluated_at = 777.5")

            var updated = first
            updated.completedAt = Synthetic.at(120)
            updated.message = "second"
            updated.errorCode = "cyberPolicy"
            #expect(try store.upsert(failedTurns: [updated]) == 1)
            // An identical re-ingest writes nothing.
            #expect(try store.upsert(failedTurns: [updated]) == 0)

            let rows = try store.query("SELECT turn_id, thread_id, started_at, completed_at, model, error_code, message, evaluated_at FROM failed_turns") { row in
                [row.text(0), row.text(1), "\(row.double(2))", "\(row.optionalDouble(3) ?? -1)", row.optionalText(4) ?? "nil", row.text(5), row.text(6), "\(row.optionalDouble(7) ?? -1)"]
            }
            #expect(rows == [[
                "turn_synthetic_1", "thread_synthetic_1", "\(Synthetic.at(60).timeIntervalSince1970)",
                "\(Synthetic.at(120).timeIntervalSince1970)", "example-model-1.0", "cyberPolicy", "second", "777.5",
            ]])
        }
    }

    @Test func connectionEventsUpsertByProviderAndSource() throws {
        try withScratchDirectory { directory in
            let store = try Self.makeStore(directory)
            let event = ConnectionEventRecord(provider: .codex, sourceID: "event_synthetic_1", at: Synthetic.at(10), kind: .retry, detail: "Reconnecting 2/5", retries: 2, maxRetries: 5)
            let bare = ConnectionEventRecord(provider: .codex, sourceID: "event_synthetic_2", at: Synthetic.at(20), kind: .disconnect, detail: "Stream closed")
            #expect(try store.upsert(connectionEvents: [event, bare]) == 2)
            #expect(try store.upsert(connectionEvents: [event]) == 0)
            var changed = event
            changed.kind = .reconnect
            #expect(try store.upsert(connectionEvents: [changed]) == 1)

            let rows = try store.query("SELECT source_id, at, kind, detail, retries, max_retries FROM connection_events ORDER BY at") { row in
                ConnectionEventRecord(
                    provider: .codex, sourceID: row.text(0), at: Date(timeIntervalSince1970: row.double(1)),
                    kind: ConnectionKind(rawValue: row.text(2))!, detail: row.text(3),
                    retries: row.optionalInt(4), maxRetries: row.optionalInt(5))
            }
            #expect(rows == [changed, bare])
        }
    }

    @Test func usageLimitRoundTripsPerProvider() throws {
        try withScratchDirectory { directory in
            let store = try Self.makeStore(directory)
            #expect(try store.usageLimit(provider: .codex) == nil)
            let first = UsageLimitSnapshot(provider: .codex, at: Synthetic.at(10), usedPercent: 41.5, windowMinutes: 300, resetsAt: Synthetic.at(9_000))
            let second = UsageLimitSnapshot(provider: .codex, at: Synthetic.at(20), usedPercent: 92, windowMinutes: 300, resetsAt: nil)
            try store.setUsageLimit(first)
            #expect(try store.usageLimit(provider: .codex) == first)
            try store.setUsageLimit(second)
            #expect(try store.usageLimit(provider: .codex) == second)
            #expect(try store.usageLimit(provider: Synthetic.otherProvider) == nil)
        }
    }

    @Test func cursorRoundTrip() throws {
        try withScratchDirectory { directory in
            let url = directory.appending(path: "telltale.sqlite")
            let store = try Store.open(url, mode: .readWrite)
            #expect(try store.cursor("codex") == nil)
            let binary = Data([0x00, 0xFF, 0x7B, 0x00, 0x22])
            try store.setCursor("codex", binary)
            try store.setCursor("openai-status", Data())
            #expect(try store.cursor("codex") == binary)
            #expect(try store.cursor("openai-status") == Data())
            try store.setCursor("codex", Data("replaced".utf8))
            #expect(try Store.open(url, mode: .readOnly).cursor("codex") == Data("replaced".utf8))
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM cursors") == "2")
        }
    }

    @Test func sourceStateRoundTrip() throws {
        try withScratchDirectory { directory in
            let store = try Self.makeStore(directory)
            #expect(try store.sourceState("codex") == nil)
            let ready = SourceStateRow(source: "codex", state: .ready, version: "1.2.3", unavailableSince: nil, updatedAt: Synthetic.at(10))
            try store.setSourceState(ready)
            #expect(try store.sourceState("codex") == ready)
            for state in [SetupState.notSetUp("No Codex data yet"), .formatProblem("Unrecognized rollout line")] {
                let row = SourceStateRow(source: "codex", state: state, version: nil, unavailableSince: Synthetic.at(5), updatedAt: Synthetic.at(20))
                try store.setSourceState(row)
                #expect(try store.sourceState("codex") == row)
            }
            #expect(try store.sourceState("openai-status") == nil)
        }
    }

    @Test func responsesQueryFiltersByModelAndRange() throws {
        try withScratchDirectory { directory in
            let store = try Self.makeStore(directory)
            let early = Synthetic.response(1, endingAt: 100)
            let boundaryLow = Synthetic.response(2, endingAt: 200)
            let middle = Synthetic.response(3, endingAt: 250)
            let boundaryHigh = Synthetic.response(4, endingAt: 300)
            let late = Synthetic.response(5, endingAt: 400)
            let otherModel = Synthetic.response(6, model: "example-model-2.0", endingAt: 250)
            let otherProvider = Synthetic.response(7, provider: Synthetic.otherProvider, endingAt: 250)
            // Inserted out of order: the query orders by end time.
            try store.upsert(responses: [late, middle, otherModel, boundaryHigh, early, otherProvider, boundaryLow])

            let found = try store.responses(provider: .codex, model: "example-model-1.0", endingIn: Synthetic.at(200)...Synthetic.at(300))
            #expect(found == [boundaryLow, middle, boundaryHigh])
            #expect(try store.responses(provider: .codex, model: "example-model-2.0", endingIn: Synthetic.at(0)...Synthetic.at(1_000)) == [otherModel])
            #expect(try store.responses(provider: .codex, model: "example-model-1.0", endingIn: Synthetic.at(500)...Synthetic.at(600)).isEmpty)
            #expect(try store.responses(provider: .codex, model: "no-such-model", endingIn: Synthetic.at(0)...Synthetic.at(1_000)).isEmpty)
        }
    }

    @Test func largeBatchesLandInOneTransaction() throws {
        try withScratchDirectory { directory in
            let store = try Self.makeStore(directory)
            let batch = (1...2_000).map { Synthetic.response($0, endingAt: Double($0)) }
            #expect(try store.upsert(responses: batch) == 2_000)
            #expect(try store.responses(provider: .codex, model: "example-model-1.0", endingIn: Synthetic.at(0)...Synthetic.at(3_000)).count == 2_000)
        }
    }

    @Test func runRecordsListNewestFirst() throws {
        try withScratchDirectory { directory in
            let store = try Self.makeStore(directory)
            #expect(try store.recentRuns(limit: 10).isEmpty)
            let first = try store.beginRun(at: Synthetic.at(100))
            try store.finishRun(first, at: Synthetic.at(105), outcome: .succeeded, detail: "ok")
            let second = try store.beginRun(at: Synthetic.at(200))
            try store.finishRun(second, at: Synthetic.at(201), outcome: .skipped, detail: "skipped: previous run still active")
            let third = try store.beginRun(at: Synthetic.at(300))
            let fourth = try store.beginRun(at: Synthetic.at(400))
            try store.finishRun(fourth, at: Synthetic.at(402), outcome: .failed, detail: "boom")

            let runs = try store.recentRuns(limit: 10)
            #expect(runs.map(\.id) == [fourth, third, second, first])
            #expect(Set([first, second, third, fourth]).count == 4)
            #expect(runs[0] == CollectorRunRecord(id: fourth, startedAt: Synthetic.at(400), finishedAt: Synthetic.at(402), outcome: .failed, detail: "boom"))
            #expect(runs[1] == CollectorRunRecord(id: third, startedAt: Synthetic.at(300), finishedAt: nil, outcome: .running, detail: ""))
            #expect(runs[2].outcome == .skipped)
            #expect(runs[3].outcome == .succeeded)
            #expect(try store.recentRuns(limit: 2).map(\.id) == [fourth, third])
            #expect(try store.recentRuns(limit: 0).isEmpty)
        }
    }
}
