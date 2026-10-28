import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

/// Spec section 9.2's model view data, read from a seeded store (`RuleHarness`: Sep 2026 in New
/// York, the synthetic model "Example" and the status source "Example Status").
private enum Detail {
    static func load(_ h: RuleHarness, range: ChartRange = .day, at now: Date, statusSourceID: String? = RuleHarness.sourceID) throws -> ModelDetail {
        try ModelDetail.load(
            store: h.store, baseline: h.base.engine, provider: .codex, model: h.model, statusSourceID: statusSourceID, range: range, now: now,
            calendar: h.calendar)
    }

    static func point(_ h: RuleHarness, _ at: Date, _ index: Double?, state: EvalPointState = .known, model: String = Synth.model) -> EvalPointRow {
        EvalPointRow(
            provider: .codex, model: model, at: at, speedIndex: index, mixUsual: 40, medianTPS: index.map { $0 * 40 }, samples: 12, state: state)
    }

    @discardableResult
    static func speedEpisode(
        _ h: RuleHarness, _ direction: Direction, severity: LampColor, onset: Date, ended: Date?
    ) throws -> Int64 {
        try h.store.insertEpisode(EpisodeRow(
            rule: EpisodeRow.speedRule(direction), provider: ProviderID.codex.rawValue, scope: h.model, direction: direction,
            onset: onset, firedAt: onset.addingTimeInterval(900), endedAt: ended,
            endReason: ended == nil ? nil : EpisodeRow.EndReason.cleared, severity: severity.rawValue,
            worstValue: direction == .slower ? 0.7 : 1.3))
    }
}

@Suite struct ModelDetailTests {
    @Test func dotsAreHourlyMediansOfStoredPoints() throws {
        try withRules { h in
            try h.store.insertEvalPoints([
                Detail.point(h, h.sep4(8, 0), 0.9), Detail.point(h, h.sep4(8, 5), 1.0), Detail.point(h, h.sep4(8, 10), 1.3),
                Detail.point(h, h.sep4(9, 0), 0.7), Detail.point(h, h.sep4(9, 5), 0.8),
                // Thin and cold points, and a known point without an index, make no dot.
                Detail.point(h, h.sep4(10, 0), nil, state: .thin), Detail.point(h, h.sep4(10, 5), 0.5, state: .cold),
                Detail.point(h, h.sep4(10, 10), nil),
                // Another model's points belong to its own view.
                Detail.point(h, h.sep4(9, 10), 2.0, model: Synth.otherModel),
            ])
            let detail = try Detail.load(h, at: h.sep4(11))
            #expect(detail.dots.map(\.hour) == [h.sep4(8), h.sep4(9)])
            #expect(approximately(detail.dots.first?.index, 1.0))
            #expect(approximately(detail.dots.last?.index, 0.75))
            #expect(detail.dots.allSatisfy { $0.color == nil })
        }
    }

    @Test func dotColorsComeFromEpisodesAtTheTime() throws {
        try withRules { h in
            try h.store.insertEvalPoints((7...12).map { Detail.point(h, h.sep4($0, 30), 1.0) })
            // Amber from 08:10 to 09:20; a red episode overlaps 09:00; blue from 11:40, still open.
            try Detail.speedEpisode(h, .slower, severity: .amber, onset: h.sep4(8, 10), ended: h.sep4(9, 20))
            try Detail.speedEpisode(h, .slower, severity: .red, onset: h.sep4(9, 40), ended: h.sep4(9, 55))
            try Detail.speedEpisode(h, .faster, severity: .blue, onset: h.sep4(11, 40), ended: nil)
            // Episodes of other rules don't color speed.
            try h.store.insertEpisode(EpisodeRow(
                rule: RuleID.largePrompts.rawValue, provider: ProviderID.codex.rawValue, scope: "*", direction: nil, onset: h.sep4(10),
                firedAt: h.sep4(10, 5), endedAt: h.sep4(10, 50), endReason: EpisodeRow.EndReason.cleared, severity: LampColor.amber.rawValue,
                worstValue: 4))
            let detail = try Detail.load(h, at: h.sep4(13))
            #expect(detail.dots.map(\.color) == [nil, .amber, .red, nil, .blue, .blue])
        }
    }

    @Test func incidentBandsAndFailureMarkers() throws {
        try withRules { h in
            try h.store.upsert(incidents: [
                h.incident("inc_synthetic_01", published: h.sep4(8), resolved: h.sep4(9), impacts: []),
                h.incident("inc_synthetic_02", published: h.sep4(10, 30), impacts: []),
            ])
            try h.run(2, throughput: 40, hour: 9)
            let responseTurn = try #require(try h.store.responses(provider: .codex, model: h.model, endingIn: h.sep4(9)...h.sep4(9, 5)).first?.turnID)
            try h.store.upsert(failedTurns: [
                // Completed: the marker sits at completion.
                FailedTurnRecord(
                    provider: .codex, threadID: "thread_synthetic_01", turnID: "turn_synthetic_901", startedAt: h.sep4(9, 50),
                    completedAt: h.sep4(9, 52), model: h.model, errorCode: "serverOverloaded", message: "Synthetic failure 1"),
                // No model recorded: attributed through a response in the same turn (spec section 6.2).
                FailedTurnRecord(
                    provider: .codex, threadID: "thread_synthetic_02", turnID: responseTurn, startedAt: h.sep4(10, 10),
                    errorCode: "serverOverloaded", message: "Synthetic failure 2"),
                // Another model's failure.
                FailedTurnRecord(
                    provider: .codex, threadID: "thread_synthetic_03", turnID: "turn_synthetic_903", startedAt: h.sep4(10, 20),
                    model: Synth.otherModel, errorCode: "serverOverloaded", message: "Synthetic failure 3"),
            ])
            let detail = try Detail.load(h, at: h.sep4(11))
            #expect(detail.incidents == [
                DateInterval(start: h.sep4(8), end: h.sep4(9)),
                // Still open: the band runs to now.
                DateInterval(start: h.sep4(10, 30), end: h.sep4(11)),
            ])
            #expect(detail.failures == [h.sep4(9, 52), h.sep4(10, 10)])
        }
    }

    /// Bands come only from the selected model's provider's status source.
    @Test func incidentBandsAreScopedToTheProvidersStatusSource() throws {
        try withRules { h in
            var other = h.incident("inc_synthetic_09", published: h.sep4(9), resolved: h.sep4(10), impacts: [])
            other.source = "example-other-status"
            try h.store.upsert(incidents: [h.incident("inc_synthetic_01", published: h.sep4(8), resolved: h.sep4(9), impacts: []), other])
            #expect(try Detail.load(h, at: h.sep4(11)).incidents == [DateInterval(start: h.sep4(8), end: h.sep4(9))])
            #expect(try Detail.load(h, at: h.sep4(11), statusSourceID: "example-other-status").incidents == [DateInterval(start: h.sep4(9), end: h.sep4(10))])
            #expect(try Detail.load(h, at: h.sep4(11), statusSourceID: nil).incidents.isEmpty)
        }
    }

    @Test func readoutUsualIsMixMatched() throws {
        try withRules { h in
            // Usual: small prompts at 40 tok/s, 300k+ prompts at 20 tok/s.
            for day in 1...3 {
                try h.base.add(20, throughput: 40, month: 9, day: day)
                try h.base.add(20, throughput: 20, month: 9, day: day, hour: 14, inputTokens: 320_000)
            }
            // The last hour: only large prompts, at their usual speed.
            try h.run(30, throughput: 20, hour: 9, inputTokens: 320_000)
            let readout = try Detail.load(h, at: h.sep4(9, 30)).lastHour
            #expect(approximately(readout.tps, 20))
            #expect(approximately(readout.usualTPS, 20))
            // 1,000 output tokens at 20 tok/s take 50 s, and would take 50 s at usual speed.
            #expect(approximately(readout.medianSeconds, 50))
            #expect(approximately(readout.usualMedianSeconds, 50))

            // Slower than usual for the same mix: the gap shows.
            try h.run(30, throughput: 10, hour: 10, inputTokens: 320_000)
            let slow = try Detail.load(h, at: h.sep4(10, 30)).lastHour
            #expect(approximately(slow.tps, 10) && approximately(slow.usualTPS, 20))
            #expect(approximately(slow.medianSeconds, 100) && approximately(slow.usualMedianSeconds, 50))
        }
    }

    @Test func bucketGapsListed() throws {
        try withRules { h in
            try h.seedUsual()
            try h.run(10, throughput: 40, hour: 9)
            try h.run(5, throughput: 20, hour: 9, minute: 15, inputTokens: 320_000)
            try h.run(5, throughput: 30, hour: 9, minute: 20, inputTokens: 120_000)
            let detail = try Detail.load(h, at: h.sep4(9, 30))
            #expect(detail.bucketGaps == [.from100k, .from300k])
            #expect(detail.learning == .learning(days: 3, of: BaselineEngine.activeDayCount))
        }
    }

    @Test func rangeLimitsData() throws {
        try withRules { h in
            let now = h.sep4(10)
            let early = h.at(9, 3, 9) // 25 hours before now
            try h.store.insertEvalPoints([Detail.point(h, early, 0.9), Detail.point(h, h.sep4(9), 1.1)])
            try h.store.upsert(failedTurns: [
                FailedTurnRecord(
                    provider: .codex, threadID: "thread_synthetic_01", turnID: "turn_synthetic_901", startedAt: early, model: h.model,
                    errorCode: "serverOverloaded", message: "Synthetic failure 1"),
                FailedTurnRecord(
                    provider: .codex, threadID: "thread_synthetic_02", turnID: "turn_synthetic_902", startedAt: h.sep4(9, 30), model: h.model,
                    errorCode: "serverOverloaded", message: "Synthetic failure 2"),
            ])
            try h.store.upsert(incidents: [h.incident("inc_synthetic_01", published: early, resolved: early.addingTimeInterval(1_800), impacts: [])])

            let day = try Detail.load(h, range: .day, at: now)
            #expect(day.interval == DateInterval(start: now.addingTimeInterval(-86_400), end: now))
            #expect(day.dots.map(\.hour) == [h.sep4(9)])
            #expect(day.failures == [h.sep4(9, 30)])
            #expect(day.incidents.isEmpty)

            let week = try Detail.load(h, range: .week, at: now)
            #expect(week.dots.map(\.hour) == [early, h.sep4(9)])
            #expect(week.failures == [early, h.sep4(9, 30)])
            #expect(week.incidents == [DateInterval(start: early, end: early.addingTimeInterval(1_800))])

            // A band that starts before the range is clipped to it.
            let six = try Detail.load(h, range: .sixHours, at: early.addingTimeInterval(6 * 3_600 + 900))
            #expect(six.incidents == [DateInterval(start: early.addingTimeInterval(900), end: early.addingTimeInterval(1_800))])
            #expect(ChartRange.allCases.map(\.label) == ["6h", "24h", "7d", "14d"])
        }
    }
}
