import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

@Suite struct RetentionTests {
    static let calendar = Synth.newYork
    /// 2026-10-15 12:00 in New York.
    static let now = Synth.local(2026, 10, 15, 12)

    static func daysAgo(_ days: Int, from date: Date = now) -> Date {
        calendar.date(byAdding: .day, value: -days, to: date)!
    }

    @Test func retentionTableValues() {
        #expect(Retention.responseDays == 180)
        #expect(Retention.runDays == 30)
    }

    @Test func prunesPerRetentionTable() throws {
        try withScratchDirectory { directory in
            let url = directory.appending(path: "telltale.sqlite")
            let store = try Store.open(url, mode: .readWrite)
            var synth = Synth()
            try store.upsert(responses: [
                synth.response(throughput: 40, end: Self.daysAgo(181)),  // resp_synthetic_01: gone
                synth.response(throughput: 40, end: Self.daysAgo(179)),  // resp_synthetic_02: kept
            ])
            let oldRun = try store.beginRun(at: Self.daysAgo(31))
            try store.finishRun(oldRun, at: Self.daysAgo(31), outcome: .succeeded)
            let keptRun = try store.beginRun(at: Self.daysAgo(29))
            try store.finishRun(keptRun, at: Self.daysAgo(29), outcome: .succeeded)
            // Kept indefinitely: events, episodes, incidents and baseline acceptances.
            let ancient = Self.daysAgo(400)
            let episode = try store.insertEpisode(EpisodeRow(
                rule: EpisodeRow.slowerRule, provider: "codex", scope: Synth.model, direction: .slower, onset: ancient,
                firedAt: ancient, endedAt: ancient, endReason: EpisodeRow.EndReason.cleared, severity: "amber", worstValue: 0.8))
            try store.insertEvent(EventRow(at: ancient, kind: EventKind.ruleFired, provider: "codex", scope: Synth.model,
                                           title: "Slower than usual", body: "synthetic", episodeID: episode))
            try store.upsert(incidents: [IncidentRecord(
                source: "example-status", id: "inc_synthetic_01", name: "Synthetic incident", status: "resolved",
                publishedAt: ancient, updatedAt: ancient, link: URL(string: "https://status.example.com/incidents/inc_synthetic_01")!,
                history: [], impacts: [])])
            _ = try store.insertEpoch(provider: .codex, model: Synth.model, since: LocalDay(ancient, calendar: Self.calendar),
                                      createdAt: ancient, before: UsualTable(medians: [:], samples: [:], activeDays: 0, epochID: nil))

            #expect(try Retention.prune(store: store, now: Self.now, calendar: Self.calendar))

            #expect(try RawSQLite.column(url, "SELECT response_id FROM responses") == ["resp_synthetic_02"])
            #expect(try store.recentRuns(limit: 10).map(\.id) == [keptRun])
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM episodes") == "1")
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM events") == "1")
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM incidents") == "1")
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM baseline_epochs") == "1")
            #expect(try store.value(.lastPrunedDay) == "2026-10-15")
        }
    }

    @Test func prunesAtMostOncePerDay() throws {
        try withScratchDirectory { directory in
            let url = directory.appending(path: "telltale.sqlite")
            let store = try Store.open(url, mode: .readWrite)
            var synth = Synth()
            #expect(try Retention.prune(store: store, now: Self.now, calendar: Self.calendar))

            // Old enough to prune, but stored after today's pass.
            try store.upsert(responses: [synth.response(throughput: 40, end: Self.daysAgo(200))])
            let laterToday = Synth.local(2026, 10, 15, 23, 55)
            #expect(try Retention.prune(store: store, now: laterToday, calendar: Self.calendar) == false)
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM responses") == "1")

            let tomorrow = Synth.local(2026, 10, 16, 0, 5)
            #expect(try Retention.prune(store: store, now: tomorrow, calendar: Self.calendar))
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM responses") == "0")
            #expect(try store.value(.lastPrunedDay) == "2026-10-16")
        }
    }
}
