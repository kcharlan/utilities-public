import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

@Suite struct ProviderSummaryTests {
    @Test func readProblemRowGivesAReadProblemState() throws {
        try withRules { h in
            let source = SourceSummary(provider: .codex, name: "Codex", statusName: "Example", statusSourceID: "example", signals: [], naming: SyntheticNaming())
            let at = h.sep4(9)
            try h.store.setSourceState(SourceStateRow(source: "codex", state: .readProblem("synthetic"), unavailableSince: at, updatedAt: at))
            #expect(try ProviderSummary.load(store: h.store, sources: [source])[0].state == .readProblem(since: at))
        }
    }

    @Test func stateLinesAndConfirmation() {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let at = calendar.date(from: DateComponents(year: 2000, month: 1, day: 1, hour: 14, minute: 2))!
        #expect(Copy.providerState(.normal, name: "Codex", calendar: calendar) == "Reading normally.")
        #expect(Copy.providerState(.notSetUp("Synthetic setup"), name: "Codex", calendar: calendar) == "Synthetic setup")
        #expect(Copy.providerState(.backfilling(started: at), name: "Codex", calendar: calendar) == "Reading 30 days of history, started 14:02. No notifications are sent for it.")
        #expect(Copy.providerState(.rebuildRequested(at: at), name: "Codex", calendar: calendar) == "Rebuild requested at 14:02. Waiting for the collector.")
        #expect(Copy.providerVersion(name: "Codex", version: "0.0.0-synthetic", seen: at, calendar: calendar) == "Codex 0.0.0-synthetic last seen at 14:02.")
        #expect(Copy.providerHistory(oldest: at, finished: at.addingTimeInterval(30 * 86_400), calendar: calendar) == "History from Jan 01, 2000. Read in full Jan 31, 2000.")
        #expect(Copy.providerRebuildConfirmation(name: "Codex", others: ["Claude Code"], days: 30, cutoff: at, calendar: calendar) == "Telltale will re-read the last 30 days of Codex logs. Codex speed history before Jan 01, 2000 is removed. Claude Code isn't touched and keeps watching. Accepted baselines are kept, and no notifications are sent for the history it reads.")
    }
    @Test func statePrecedence() throws {
        try withRules { h in
            let source = SourceSummary(provider: .codex, name: "Codex", statusName: "Example", statusSourceID: "example", signals: [], naming: SyntheticNaming())
            let at = h.sep4(9)
            try h.store.setSourceState(SourceStateRow(source: "codex", state: .formatProblem("synthetic"), unavailableSince: at, updatedAt: at))
            try h.store.setBackfill(ProviderBackfill(reason: .new, startedAt: at, through: at, finishedAt: nil, announce: false), unit: "codex")
            try h.store.set(.providerRebuildRequests, ["codex": at])
            #expect(try ProviderSummary.load(store: h.store, sources: [source])[0].state == .rebuildRequested(at: at))
            try h.store.set(.providerRebuildRequests, [:])
            #expect(try ProviderSummary.load(store: h.store, sources: [source])[0].state == .backfilling(started: at))
            try h.store.setBackfill(ProviderBackfill(reason: .new, startedAt: at, through: at, finishedAt: at, announce: false), unit: "codex")
            #expect(try ProviderSummary.load(store: h.store, sources: [source])[0].state == .formatProblem(since: at))
            try h.store.setSourceState(SourceStateRow(source: "codex", state: .notSetUp("Synthetic setup"), updatedAt: at))
            #expect(try ProviderSummary.load(store: h.store, sources: [source])[0].state == .notSetUp("Synthetic setup"))
            try h.store.setSourceState(SourceStateRow(source: "codex", state: .ready, updatedAt: at))
            #expect(try ProviderSummary.load(store: h.store, sources: [source])[0].state == .normal)
        }
    }
    @Test func factsComeFromProviderStateAndResponses() throws {
        try withRules { h in
            let folder = URL(fileURLWithPath: "/synthetic/provider")
            let source = SourceSummary(provider: .codex, name: "Codex", statusName: "Example", statusSourceID: "example", signals: [], naming: SyntheticNaming(), dataFolder: folder)
            let at = h.sep4(9)
            try h.run(2, throughput: 40, hour: 9)
            try h.store.setSourceState(SourceStateRow(source: "codex", state: .ready, version: "0.0.0-synthetic", updatedAt: at))
            try h.store.setBackfill(ProviderBackfill(reason: .new, startedAt: at, through: at, finishedAt: at, announce: false), unit: "codex")
            let summary = try #require(ProviderSummary.load(store: h.store, sources: [source]).first)
            #expect(summary.sourceVersion == "0.0.0-synthetic")
            #expect(summary.lastIngestAt == at)
            #expect(summary.oldestResponse != nil)
            #expect(summary.lastBackfillFinished == at)
            #expect(summary.dataFolder == folder)
        }
    }
}
