import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

@Suite struct ShiftDetectorTests {
    /// One active October day: a response at 09:00 and, unless `direction` is nil, a speed
    /// episode (onset 08:50, fired 09:05) that idle-ends at 10:00, or clears at 10:00 when `cleared`.
    private static func day(
        _ h: BaselineHarness, _ day: Int, _ direction: Direction?, worst: Double = 0.75, cleared: Bool = false
    ) throws {
        try h.add(1, throughput: 40, month: 10, day: day)
        guard let direction else { return }
        try h.episode(
            rule: EpisodeRow.speedRule(direction), direction: direction,
            onset: h.at(10, day, 8, 50), fired: h.at(10, day, 9, 5), ended: h.at(10, day, 10),
            endReason: cleared ? EpisodeRow.EndReason.cleared : EpisodeRow.EndReason.idleEnded, worst: worst)
    }

    private static func prompt(_ h: BaselineHarness, _ at: Date) throws -> ShiftPrompt? {
        try ShiftDetector.prompt(provider: .codex, model: h.model, at: at, store: h.store, calendar: h.calendar)
    }

    @Test func consecutiveActiveDaysPrompt() throws {
        try withBaseline { h in
            try Self.day(h, 5, .slower, worst: 0.75)
            try Self.day(h, 6, .slower, worst: 0.70)
            #expect(try Self.prompt(h, h.at(10, 6, 20)) == nil, "two days aren't a lasting shift")
            try Self.day(h, 7, .slower, worst: 0.80)

            let prompt = try #require(try Self.prompt(h, h.at(10, 7, 20)))
            #expect(prompt.provider == .codex)
            #expect(prompt.model == h.model)
            #expect(prompt.direction == .slower)
            #expect(prompt.firstDay == h.localDay(10, 5))
            #expect(prompt.days == 3)
            // Median of the episodes' deviations: 25%, 30%, 20%.
            #expect(prompt.typicalPercent == 25)
            #expect(prompt.incidentIDs.isEmpty)

            // The next morning, before any episode fires that day, the prompt stands.
            try h.add(1, throughput: 40, month: 10, day: 8, hour: 7)
            #expect(try Self.prompt(h, h.at(10, 8, 8)) == prompt)
            // A finished active day without a slowdown ends the run.
            #expect(try Self.prompt(h, h.at(10, 9, 8)) == nil)
            // Evaluation sees only episodes fired by then.
            #expect(try Self.prompt(h, h.at(10, 7, 9)) == nil)
        }
    }

    @Test func gapDayWithoutActivityDoesNotBreakRun() throws {
        try withBaseline { h in
            try Self.day(h, 5, .slower)
            // Oct 6: no responses at all.
            try Self.day(h, 7, .slower)
            try Self.day(h, 8, .slower)
            let prompt = try #require(try Self.prompt(h, h.at(10, 8, 20)))
            #expect(prompt.firstDay == h.localDay(10, 5))
            #expect(prompt.days == 3)
        }
        try withBaseline { h in
            try Self.day(h, 5, .slower)
            try Self.day(h, 6, nil) // active, no slowdown
            try Self.day(h, 7, .slower)
            try Self.day(h, 8, .slower)
            #expect(try Self.prompt(h, h.at(10, 8, 20)) == nil)
        }
    }

    @Test func oppositeDirectionBreaksRun() throws {
        try withBaseline { h in
            try Self.day(h, 5, .slower)
            try Self.day(h, 6, .faster, worst: 1.2)
            try Self.day(h, 7, .slower)
            try Self.day(h, 8, .slower)
            #expect(try Self.prompt(h, h.at(10, 8, 20)) == nil)
            try Self.day(h, 9, .slower)
            let prompt = try #require(try Self.prompt(h, h.at(10, 9, 20)))
            #expect(prompt.direction == .slower)
            #expect(prompt.firstDay == h.localDay(10, 7))
        }
        try withBaseline { h in
            // The faster direction prompts too.
            for day in 5...7 { try Self.day(h, day, .faster, worst: 1.2) }
            let prompt = try #require(try Self.prompt(h, h.at(10, 7, 20)))
            #expect(prompt.direction == .faster)
            #expect(prompt.typicalPercent == 20)
        }
    }

    @Test func keepAsAbnormalSuppressesUntilClearAndNewRun() throws {
        try withBaseline { h in
            for day in 5...7 { try Self.day(h, day, .slower) }
            let prompt = try #require(try Self.prompt(h, h.at(10, 7, 20)))
            try ShiftDetector.keepAsAbnormal(prompt, at: h.at(10, 7, 21), store: h.store)
            #expect(try Self.prompt(h, h.at(10, 7, 22)) == nil)
            #expect(try RawSQLite.rows(h.url, "SELECT provider, model, direction, first_day FROM shift_dismissals")
                == [["codex", h.model, "slower", "2026-10-05"]])

            // The shift continues without a clear: still dismissed.
            try Self.day(h, 8, .slower)
            #expect(try Self.prompt(h, h.at(10, 8, 20)) == nil)
            // Oct 9's slowdown clears at 10:00. Oct 10 and 11 slow again: two days after the clear.
            try Self.day(h, 9, .slower, cleared: true)
            try Self.day(h, 10, .slower)
            try Self.day(h, 11, .slower)
            #expect(try Self.prompt(h, h.at(10, 11, 20)) == nil)
            // A third day makes a new run, which prompts.
            try Self.day(h, 12, .slower)
            let renewed = try #require(try Self.prompt(h, h.at(10, 12, 20)))
            #expect(renewed.firstDay == h.localDay(10, 10))
            #expect(renewed.days == 3)
        }
    }

    @Test func promptListsOverlappingIncidents() throws {
        try withBaseline { h in
            for day in 5...7 { try Self.day(h, day, .slower) }
            func incident(_ id: String, published: Date, resolved: Date?) -> IncidentRecord {
                IncidentRecord(
                    source: "example.status", id: id, name: "Synthetic incident \(id)",
                    status: resolved == nil ? "investigating" : "resolved", publishedAt: published,
                    updatedAt: resolved ?? published, link: URL(string: "https://status.example.com/incidents/\(id)")!,
                    history: [StatusChange(at: published, status: "investigating")],
                    impacts: [ComponentImpact(componentID: "component-a", status: "degraded_performance", start: published, end: resolved)])
            }
            try h.store.upsert(incidents: [
                incident("synthetic-before", published: h.at(10, 1, 9), resolved: h.at(10, 1, 11)),
                incident("synthetic-during", published: h.at(10, 6, 9), resolved: h.at(10, 6, 15)),
                incident("synthetic-open", published: h.at(10, 7, 8), resolved: nil),
                incident("synthetic-late-evening", published: h.at(10, 7, 22), resolved: h.at(10, 7, 23)),
                incident("synthetic-after", published: h.at(10, 8, 9), resolved: h.at(10, 8, 10)),
            ])
            let prompt = try #require(try Self.prompt(h, h.at(10, 7, 20)))
            #expect(prompt.incidentIDs == ["synthetic-during", "synthetic-open"])

            // Oct 8 has no responses, so the run (Oct 5–7) still stands on Oct 8. Its window ends
            // with Oct 7: the late-evening incident overlaps it, Oct 8's incident doesn't.
            let nextDay = try #require(try Self.prompt(h, h.at(10, 8, 20)))
            #expect(nextDay.firstDay == h.localDay(10, 5))
            #expect(nextDay.incidentIDs == ["synthetic-during", "synthetic-open", "synthetic-late-evening"])
        }
    }
}
