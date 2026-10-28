import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

/// A temporary store, a baseline engine on the America/New_York calendar and a `Synth`.
final class BaselineHarness {
    let url: URL
    let calendar = Synth.newYork
    var store: Store
    var engine: BaselineEngine
    var synth = Synth()
    let model = Synth.model

    init(directory: URL) throws {
        url = directory.appending(path: "telltale.sqlite")
        store = try Store.open(url, mode: .readWrite)
        engine = BaselineEngine(store: store, calendar: calendar)
    }

    /// Reopens the store and recreates the engine, as a later collector run would.
    func reopen() throws {
        store = try Store.open(url, mode: .readWrite)
        engine = BaselineEngine(store: store, calendar: calendar)
    }

    /// A local time in 2026.
    func at(_ month: Int, _ day: Int, _ hour: Int = 0, _ minute: Int = 0) -> Date {
        Synth.local(2026, month, day, hour, minute)
    }

    func localDay(_ month: Int, _ day: Int) -> LocalDay { LocalDay(year: 2026, month: month, day: day) }

    /// `count` responses a minute apart, the first ending at `month`/`day` `hour`:`minute`.
    func add(
        _ count: Int, throughput: Double, month: Int, day: Int, hour: Int = 9, minute: Int = 0,
        model: String? = nil, effort: String? = "medium", tier: String? = nil, inputTokens: Int = 10_000,
        outputTokens: Int = 1_000
    ) throws {
        try store.upsert(responses: synth.responses(
            count, model: model ?? self.model, effort: effort, tier: tier, inputTokens: inputTokens,
            throughput: throughput, from: at(month, day, hour, minute), outputTokens: outputTokens))
    }

    @discardableResult
    func episode(
        rule: String = EpisodeRow.slowerRule, direction: Direction? = .slower, model: String? = nil,
        onset: Date, fired: Date, ended: Date?, endReason: String? = EpisodeRow.EndReason.idleEnded, worst: Double = 0.75
    ) throws -> Int64 {
        try store.insertEpisode(EpisodeRow(
            rule: rule, provider: ProviderID.codex.rawValue, scope: model ?? self.model, direction: direction,
            onset: onset, firedAt: fired, endedAt: ended, endReason: ended == nil ? nil : endReason,
            severity: "amber", worstValue: worst))
    }

    func usual(_ date: Date, model: String? = nil) throws -> UsualTable {
        try engine.usual(provider: .codex, model: model ?? self.model, at: date)
    }

    /// The baseline key every default `add` uses.
    static let defaultKey = UsualKey(effort: "medium", serviceTier: "none", bucket: .under50k)

    /// Sep 1–14: 20 responses a day at 40 tok/s from 09:00. Sep 15–17: a lasting slowdown, 10
    /// responses a day at 30 tok/s from 09:00, each day inside a slower episode (onset 08:50,
    /// fired 09:05, idle-ended 09:30), so the slow responses are excluded from usual.
    func seedLastingSlowdown(model: String? = nil) throws {
        for day in 1...14 { try add(20, throughput: 40, month: 9, day: day, model: model) }
        for day in 15...17 {
            try add(10, throughput: 30, month: 9, day: day, model: model)
            try episode(model: model, onset: at(9, day, 8, 50), fired: at(9, day, 9, 5), ended: at(9, day, 9, 30))
        }
    }

    /// Event rows of `kind`: [scope, epoch_id, title, body, undone_at is null ("live" or "undone")].
    func events(_ kind: String) throws -> [[String]] {
        try RawSQLite.rows(url, """
            SELECT scope, epoch_id, title, body, CASE WHEN undone_at IS NULL THEN 'live' ELSE 'undone' END
            FROM events WHERE kind = '\(kind)' ORDER BY id
            """)
    }
}

func withBaseline(_ body: (BaselineHarness) throws -> Void) throws {
    try withScratchDirectory { directory in try body(try BaselineHarness(directory: directory)) }
}

func approximately(_ value: Double?, _ expected: Double, tolerance: Double = 1e-6) -> Bool {
    guard let value else { return false }
    return abs(value - expected) <= tolerance
}

@Suite struct BaselineTests {
    // MARK: Keys and buckets

    @Test func bucketEdges() {
        // Spec section 7.1: < 50k, 50–100k, 100–200k, 200–300k, 300k+.
        let cases: [(Int, InputBucket)] = [
            (0, .under50k), (49_999, .under50k), (50_000, .from50k),
            (99_999, .from50k), (100_000, .from100k),
            (199_999, .from100k), (200_000, .from200k),
            (299_999, .from200k), (300_000, .from300k), (2_000_000, .from300k),
        ]
        for (tokens, bucket) in cases {
            #expect(InputBucket(inputTokens: tokens) == bucket, "\(tokens) tokens")
        }
        #expect(InputBucket.allCases.map(\.label) == ["under 50k", "50–100k", "100–200k", "200–300k", "300k+"])
    }

    @Test func usualKeyedByEffortAndServiceTier() throws {
        try withBaseline { h in
            // Same bucket; effort and tier each change independently.
            try h.add(20, throughput: 40, month: 9, day: 1, hour: 9)
            try h.add(20, throughput: 30, month: 9, day: 1, hour: 10, effort: "high")
            try h.add(20, throughput: 50, month: 9, day: 1, hour: 11, tier: "priority")
            let table = try h.usual(h.at(9, 2, 12))

            #expect(table.medians.count == 3)
            #expect(approximately(table.medians[UsualKey(effort: "medium", serviceTier: "none", bucket: .under50k)], 40))
            #expect(approximately(table.medians[UsualKey(effort: "high", serviceTier: "none", bucket: .under50k)], 30))
            #expect(approximately(table.medians[UsualKey(effort: "medium", serviceTier: "priority", bucket: .under50k)], 50))

            // A response with no recorded tier keys as "none" (spec section 8).
            let untiered = h.synth.response(tier: nil, throughput: 10, end: h.at(9, 2, 12))
            #expect(UsualKey(untiered) == UsualKey(effort: "medium", serviceTier: "none", bucket: .under50k))
            #expect(approximately(table.usual(for: untiered), 40))
            #expect(approximately(table.usual(for: h.synth.response(effort: "high", throughput: 10, end: h.at(9, 2, 12))), 30))
            #expect(table.usual(for: h.synth.response(effort: "low", throughput: 10, end: h.at(9, 2, 12))) == nil)
        }
    }

    @Test func bucketBelowMinimumHasNoUsual() throws {
        try withBaseline { h in
            try h.add(20, throughput: 40, month: 9, day: 1, hour: 9)
            try h.add(19, throughput: 25, month: 9, day: 1, hour: 10, inputTokens: 350_000)
            let table = try h.usual(h.at(9, 2, 12))
            let large = UsualKey(effort: "medium", serviceTier: "none", bucket: .from300k)

            #expect(table.samples[large] == 19)
            #expect(table.medians[large] == nil)
            #expect(table.usual(for: h.synth.response(inputTokens: 350_000, throughput: 10, end: h.at(9, 2, 12))) == nil)
            #expect(table.samples[BaselineHarness.defaultKey] == 20)
            #expect(approximately(table.medians[BaselineHarness.defaultKey], 40))
        }
    }

    // MARK: Active days

    @Test func onlyMostRecentActiveDaysCount() throws {
        try withBaseline { h in
            // Sep 1: 30 responses at 100. Sep 2–15 (14 active days): 2 a day at 40 = 28 samples.
            // With Sep 1 counted the median would be 100 (30 of 58 samples).
            try h.add(30, throughput: 100, month: 9, day: 1)
            for day in 2...15 { try h.add(2, throughput: 40, month: 9, day: day) }
            let table = try h.usual(h.at(9, 16, 12))

            #expect(table.activeDays == 14)
            #expect(table.samples[BaselineHarness.defaultKey] == 28)
            #expect(approximately(table.medians[BaselineHarness.defaultKey], 40))
        }
    }

    @Test func inactiveDaysDoNotCount() throws {
        try withBaseline { h in
            // Sep 1: 30 at 100, outside the window. Sep 2, 4, …, 28: 14 active days, 2 a day at 40.
            // Sep 3, 5, …, 29 hold only responses under 300 output tokens (no throughput), so
            // they aren't active days; if they were, the window would hold only 7 real days.
            try h.add(30, throughput: 100, month: 9, day: 1)
            for day in stride(from: 2, through: 28, by: 2) { try h.add(2, throughput: 40, month: 9, day: day) }
            for day in stride(from: 3, through: 29, by: 2) {
                try h.add(3, throughput: 40, month: 9, day: day, outputTokens: 200)
            }
            let table = try h.usual(h.at(9, 30, 12))

            #expect(table.activeDays == 14)
            #expect(table.samples[BaselineHarness.defaultKey] == 28)
            #expect(approximately(table.medians[BaselineHarness.defaultKey], 40))
            let days = try h.engine.activeDays(provider: .codex, model: h.model, before: h.at(9, 30), from: nil)
            #expect(days == [h.localDay(9, 1)] + stride(from: 2, through: 28, by: 2).map { h.localDay(9, $0) })
            #expect(try h.engine.activeDays(provider: .codex, model: h.model, before: h.at(9, 30), from: h.localDay(9, 27)) == [h.localDay(9, 28)])
        }
    }

    @Test func activeDaysAcrossFallBackCountOnce() throws {
        try withBaseline { h in
            // America/New_York falls back on Sun 2026-11-01 at 02:00 EDT (06:00Z) to 01:00 EST.
            // Unix seconds, all 1,000 output tokens at 40 tok/s (25 s duration):
            let instants: [(TimeInterval, String)] = [
                (1_793_503_800, "2026-11-01T03:30Z = Oct 31 23:30 EDT"),
                (1_793_507_400, "2026-11-01T04:30Z = Nov 1 00:30 EDT"),
                (1_793_511_000, "2026-11-01T05:30Z = Nov 1 01:30 EDT (first 01:30)"),
                (1_793_514_600, "2026-11-01T06:30Z = Nov 1 01:30 EST (repeated hour)"),
                (1_793_518_200, "2026-11-01T07:30Z = Nov 1 02:30 EST"),
                (1_793_593_800, "2026-11-02T04:30Z = Nov 1 23:30 EST"),
                (1_793_597_400, "2026-11-02T05:30Z = Nov 2 00:30 EST"),
            ]
            let responses = instants.map { h.synth.response(throughput: 40, end: Date(timeIntervalSince1970: $0.0)) }
            try h.store.upsert(responses: responses)
            // Both 01:30 readings are local 01:30 on Nov 1.
            let first = h.calendar.dateComponents([.day, .hour, .minute], from: responses[2].end)
            let repeated = h.calendar.dateComponents([.day, .hour, .minute], from: responses[3].end)
            #expect(first == repeated)

            let before = Date(timeIntervalSince1970: 1_793_606_400) // 2026-11-02T08:00Z = Nov 2 03:00 EST
            let days = try h.engine.activeDays(provider: .codex, model: h.model, before: before, from: nil)
            #expect(days == [h.localDay(10, 31), h.localDay(11, 1), h.localDay(11, 2)])
            #expect(try h.usual(before).activeDays == 3)
            #expect(LocalDay(responses[3].end, calendar: h.calendar).start(in: h.calendar)
                == Date(timeIntervalSince1970: 1_793_505_600)) // Nov 1 00:00 EDT = 04:00Z
            // Nov 1 is 25 hours long: Nov 2 starts at 00:00 EST = 05:00Z.
            #expect(h.localDay(11, 2).start(in: h.calendar) == Date(timeIntervalSince1970: 1_793_595_600))
        }
    }

    // MARK: Unflagged and earlier data

    @Test func responsesInsideSpeedEpisodesAreExcluded() throws {
        try withBaseline { h in
            try h.add(20, throughput: 40, month: 9, day: 1, hour: 9)
            // A closed slower episode over 11:00–11:09 and an open one from 14:00.
            try h.add(10, throughput: 20, month: 9, day: 1, hour: 11)
            try h.episode(onset: h.at(9, 1, 10, 55), fired: h.at(9, 1, 11, 10), ended: h.at(9, 1, 11, 30))
            try h.add(10, throughput: 20, month: 9, day: 1, hour: 14)
            try h.episode(direction: .slower, onset: h.at(9, 1, 13, 55), fired: h.at(9, 1, 14, 10), ended: nil)
            // Counting all 40 responses would give a median of 30.
            let table = try h.usual(h.at(9, 2, 12))
            #expect(table.samples[BaselineHarness.defaultKey] == 20)
            #expect(approximately(table.medians[BaselineHarness.defaultKey], 40))

            // A faster episode excludes too.
            try h.add(30, throughput: 90, month: 9, day: 2, hour: 9)
            try h.episode(rule: EpisodeRow.fasterRule, direction: .faster, onset: h.at(9, 2, 8, 55), fired: h.at(9, 2, 9, 10), ended: h.at(9, 2, 10))
            #expect(try h.usual(h.at(9, 3, 12)).samples[BaselineHarness.defaultKey] == 20)
        }
    }

    @Test func largePromptEpisodesDoNotExclude() throws {
        try withBaseline { h in
            try h.add(20, throughput: 40, month: 9, day: 1, hour: 9)
            try h.add(20, throughput: 20, month: 9, day: 1, hour: 11)
            try h.episode(rule: "largePrompts", direction: nil, onset: h.at(9, 1, 10, 55), fired: h.at(9, 1, 11, 10), ended: nil)
            let table = try h.usual(h.at(9, 2, 12))
            #expect(table.samples[BaselineHarness.defaultKey] == 40)
            #expect(approximately(table.medians[BaselineHarness.defaultKey], 30))
        }
    }

    @Test func onlyEarlierDataIsUsed() throws {
        try withBaseline { h in
            try h.add(20, throughput: 40, month: 9, day: 1, hour: 9)
            // Exactly at the 10:00 cutoff: not "before" it.
            try h.add(1, throughput: 1_000, month: 9, day: 1, hour: 10)
            try h.add(20, throughput: 20, month: 9, day: 1, hour: 10, minute: 30)

            // 10:45 uses data ending before 10:00 (start of its sampling hour).
            let early = try h.usual(h.at(9, 1, 10, 45))
            #expect(early.samples[BaselineHarness.defaultKey] == 20)
            #expect(approximately(early.medians[BaselineHarness.defaultKey], 40))

            let later = try h.usual(h.at(9, 1, 11, 5))
            #expect(later.samples[BaselineHarness.defaultKey] == 41)
            #expect(approximately(later.medians[BaselineHarness.defaultKey], 40))

            // An episode excludes only once it has fired by the cutoff: not at 11:50 (before it
            // fired), nor at 12:15 (fired 12:10, after the 12:00 cutoff), but from 13:00.
            try h.episode(onset: h.at(9, 1, 10, 25), fired: h.at(9, 1, 12, 10), ended: nil)
            #expect(try h.usual(h.at(9, 1, 11, 50)).samples[BaselineHarness.defaultKey] == 41)
            #expect(try h.usual(h.at(9, 1, 12, 15)).samples[BaselineHarness.defaultKey] == 41)
            #expect(try h.usual(h.at(9, 1, 13, 5)).samples[BaselineHarness.defaultKey] == 21)
        }
    }

    // MARK: Acceptance and Undo

    @Test func acceptStartsEpochFromSinceDay() throws {
        try withBaseline { h in
            try h.seedLastingSlowdown()
            // Before: Sep 4–17 are the 14 active days; the slow Sep 15–17 responses are inside
            // episodes, so usual is 40 from Sep 4–14 (11 days × 20).
            let before = try h.usual(h.at(9, 18, 10, 5))
            #expect(before.samples[BaselineHarness.defaultKey] == 220)
            #expect(approximately(before.medians[BaselineHarness.defaultKey], 40))
            #expect(before.epochID == nil)

            // Accept from Sep 15: only Sep 15–17 count, and their episode responses are normal.
            let acceptance = try h.engine.accept(provider: .codex, model: h.model, since: h.localDay(9, 15), at: h.at(9, 18, 10, 20))
            // Comparison sample: Sep 15–17's 30 responses, each 30 / 40 − 1 = −25%.
            #expect(acceptance.percentChange == -25)

            let after = try h.usual(h.at(9, 18, 10, 25))
            #expect(after.epochID == acceptance.epochID)
            #expect(after.activeDays == 3)
            #expect(after.samples[BaselineHarness.defaultKey] == 30)
            #expect(approximately(after.medians[BaselineHarness.defaultKey], 30))
            #expect(try h.engine.learning(provider: .codex, model: h.model, at: h.at(9, 18, 10, 25)) == .learning(days: 3, of: 14))

            let epoch = try #require(try h.engine.currentEpoch(provider: .codex, model: h.model))
            #expect(epoch.id == acceptance.epochID)
            #expect(epoch.since == h.localDay(9, 15))
            #expect(epoch.createdAt == h.at(9, 18, 10, 20))
            #expect(epoch.undoneAt == nil)
            #expect(approximately(epoch.before.medians[BaselineHarness.defaultKey], 40))
            #expect(approximately(epoch.after.medians[BaselineHarness.defaultKey], 30))
            #expect(epoch.after.epochID == acceptance.epochID)

            let sentence = "example-model-1.0's usual speed is now 25% lower than before."
            #expect(Copy.acceptance(model: h.model, percent: -25) == sentence)
            #expect(Copy.acceptance(model: h.model, percent: 12) == "example-model-1.0's usual speed is now 12% higher than before.")
            #expect(Copy.acceptance(model: h.model, percent: 0) == "example-model-1.0's usual speed is unchanged.")
            #expect(try h.events(EventKind.baselineAccepted) == [[h.model, "\(acceptance.epochID)", sentence, sentence, "live"]])
        }
    }

    @Test func undoRestoresPreviousEpoch() throws {
        try withBaseline { h in
            try h.seedLastingSlowdown()
            let acceptance = try h.engine.accept(provider: .codex, model: h.model, since: h.localDay(9, 15), at: h.at(9, 18, 10, 20))
            try h.engine.undo(epochID: acceptance.epochID, at: h.at(9, 18, 10, 40))

            let restored = try h.usual(h.at(9, 18, 10, 45))
            #expect(restored.epochID == nil)
            #expect(approximately(restored.medians[BaselineHarness.defaultKey], 40))
            #expect(try h.engine.currentEpoch(provider: .codex, model: h.model) == nil)
            #expect(try h.events(EventKind.baselineAccepted).map { $0[4] } == ["undone"])
            #expect(try h.events(EventKind.baselineUndone) == [[h.model, "\(acceptance.epochID)", Copy.baselineRestored(model: h.model), Copy.baselineRestored(model: h.model), "live"]])
            // The epoch row is kept, marked undone.
            #expect(try RawSQLite.scalar(h.url, "SELECT undone_at FROM baseline_epochs WHERE id = \(acceptance.epochID)")
                == "\(h.at(9, 18, 10, 40).timeIntervalSince1970)")
            // Undoing twice is refused.
            #expect(throws: StoreError.self) { try h.engine.undo(epochID: acceptance.epochID, at: h.at(9, 18, 10, 50)) }
        }
    }

    @Test func undoEarlierAcceptanceRestoresItsPredecessor() throws {
        try withBaseline { h in
            try h.seedLastingSlowdown()
            try h.seedLastingSlowdown(model: Synth.otherModel)
            let first = try h.engine.accept(provider: .codex, model: h.model, since: h.localDay(9, 10), at: h.at(9, 18, 10, 0))
            let selected = try h.engine.accept(provider: .codex, model: h.model, since: h.localDay(9, 15), at: h.at(9, 18, 10, 10))
            let later = try h.engine.accept(provider: .codex, model: h.model, since: h.localDay(9, 16), at: h.at(9, 18, 10, 20))
            let other = try h.engine.accept(provider: .codex, model: Synth.otherModel, since: h.localDay(9, 16), at: h.at(9, 18, 10, 25))
            let otherBefore = try h.usual(h.at(9, 18, 10, 50), model: Synth.otherModel)

            try h.engine.undo(epochID: selected.epochID, at: h.at(9, 18, 10, 30))

            // The model returns to the first acceptance: Sep 10–17, slow days counted as normal
            // (5 days × 20 at 40 and 3 × 10 at 30, median 40).
            let restored = try h.usual(h.at(9, 18, 10, 35))
            #expect(restored.epochID == first.epochID)
            #expect(restored.samples[BaselineHarness.defaultKey] == 130)
            #expect(approximately(restored.medians[BaselineHarness.defaultKey], 40))
            #expect(try h.engine.currentEpoch(provider: .codex, model: h.model)?.id == first.epochID)
            let undone = try RawSQLite.column(h.url, "SELECT id FROM baseline_epochs WHERE undone_at IS NOT NULL ORDER BY id")
            #expect(undone == ["\(selected.epochID)", "\(later.epochID)"])

            // The independent model is untouched.
            #expect(try h.engine.currentEpoch(provider: .codex, model: Synth.otherModel)?.id == other.epochID)
            #expect(try h.usual(h.at(9, 18, 10, 50), model: Synth.otherModel) == otherBefore)

            let accepted = try h.events(EventKind.baselineAccepted)
            #expect(accepted.map { [$0[0], $0[1], $0[4]] } == [
                [h.model, "\(first.epochID)", "live"], [h.model, "\(selected.epochID)", "undone"],
                [h.model, "\(later.epochID)", "undone"], [Synth.otherModel, "\(other.epochID)", "live"],
            ])
            #expect(try h.events(EventKind.baselineUndone).map { $0[1] } == ["\(selected.epochID)"])
        }
    }

    @Test func midHourAcceptAndUndoAffectNextEvaluation() throws {
        try withBaseline { h in
            try h.seedLastingSlowdown()
            let point1 = try h.usual(h.at(9, 18, 10, 5))
            #expect(approximately(point1.medians[BaselineHarness.defaultKey], 40))

            let acceptance = try h.engine.accept(provider: .codex, model: h.model, since: h.localDay(9, 15), at: h.at(9, 18, 10, 20))
            // The 10:05 point keeps the table in effect then; 10:25 uses the new epoch.
            #expect(try h.usual(h.at(9, 18, 10, 5)) == point1)
            let point2 = try h.usual(h.at(9, 18, 10, 25))
            #expect(point2.epochID == acceptance.epochID)
            #expect(approximately(point2.medians[BaselineHarness.defaultKey], 30))

            try h.engine.undo(epochID: acceptance.epochID, at: h.at(9, 18, 10, 40))
            #expect(try h.usual(h.at(9, 18, 10, 5)) == point1)
            #expect(try h.usual(h.at(9, 18, 10, 25)) == point2)
            let point3 = try h.usual(h.at(9, 18, 10, 45))
            #expect(point3.epochID == nil)
            #expect(approximately(point3.medians[BaselineHarness.defaultKey], 40))
        }
    }

    @Test func midHourActionSurvivesNewEngine() throws {
        try withBaseline { h in
            try h.seedLastingSlowdown()
            let acceptance = try h.engine.accept(provider: .codex, model: h.model, since: h.localDay(9, 15), at: h.at(9, 18, 10, 20))
            let original = try h.usual(h.at(9, 18, 10, 25))
            try h.reopen()
            #expect(try h.usual(h.at(9, 18, 10, 25)) == original)
            #expect(original.epochID == acceptance.epochID)

            try h.engine.undo(epochID: acceptance.epochID, at: h.at(9, 18, 10, 40))
            let restored = try h.usual(h.at(9, 18, 10, 45))
            try h.reopen()
            #expect(try h.usual(h.at(9, 18, 10, 45)) == restored)
            #expect(try h.usual(h.at(9, 18, 10, 25)) == original)
            #expect(restored.epochID == nil)
        }
    }

    @Test func episodesAfterAcceptanceStillExcluded() throws {
        try withBaseline { h in
            try h.seedLastingSlowdown()
            try h.engine.accept(provider: .codex, model: h.model, since: h.localDay(9, 15), at: h.at(9, 18, 10, 20))
            // Sep 19: 20 normal responses at 30, then 60 at 15 inside a slower episode that
            // fires after the acceptance. Counting them would move the median to 15.
            try h.add(20, throughput: 30, month: 9, day: 19, hour: 9)
            try h.add(60, throughput: 15, month: 9, day: 19, hour: 11)
            try h.episode(onset: h.at(9, 19, 10, 55), fired: h.at(9, 19, 11, 10), ended: h.at(9, 19, 12, 30))

            let table = try h.usual(h.at(9, 20, 12))
            #expect(table.samples[BaselineHarness.defaultKey] == 50)
            #expect(approximately(table.medians[BaselineHarness.defaultKey], 30))
        }
    }

    // MARK: Cold start

    @Test func coldThenLearningThenReady() throws {
        try withBaseline { h in
            #expect(try h.engine.learning(provider: .codex, model: h.model, at: h.at(9, 1, 12)) == .cold(days: 0))
            try h.add(20, throughput: 40, month: 9, day: 1)
            try h.add(20, throughput: 40, month: 9, day: 2)
            #expect(try h.engine.learning(provider: .codex, model: h.model, at: h.at(9, 3, 12)) == .cold(days: 2))
            try h.add(20, throughput: 40, month: 9, day: 3)
            #expect(try h.engine.learning(provider: .codex, model: h.model, at: h.at(9, 4, 12)) == .learning(days: 3, of: 14))
            for day in 4...13 { try h.add(1, throughput: 40, month: 9, day: day) }
            #expect(try h.engine.learning(provider: .codex, model: h.model, at: h.at(9, 14, 12)) == .learning(days: 13, of: 14))
            try h.add(1, throughput: 40, month: 9, day: 14)
            #expect(try h.engine.learning(provider: .codex, model: h.model, at: h.at(9, 15, 12)) == .ready)
            // Only data before the evaluation hour counts: Sep 14's 09:00 response is not yet in at 09:30.
            #expect(try h.engine.learning(provider: .codex, model: h.model, at: h.at(9, 14, 9, 30)) == .learning(days: 13, of: 14))
        }
    }

    @Test func acceptWithRecentSinceDateIsColdUntilEnoughDays() throws {
        try withBaseline { h in
            for day in 1...14 { try h.add(20, throughput: 40, month: 9, day: day) }
            #expect(try h.engine.learning(provider: .codex, model: h.model, at: h.at(9, 15, 8)) == .ready)

            try h.engine.accept(provider: .codex, model: h.model, since: h.localDay(9, 14), at: h.at(9, 15, 8, 10))
            #expect(try h.engine.learning(provider: .codex, model: h.model, at: h.at(9, 15, 8, 15)) == .cold(days: 1))
            try h.add(5, throughput: 40, month: 9, day: 15)
            #expect(try h.engine.learning(provider: .codex, model: h.model, at: h.at(9, 16, 8)) == .cold(days: 2))
            try h.add(5, throughput: 40, month: 9, day: 16)
            #expect(try h.engine.learning(provider: .codex, model: h.model, at: h.at(9, 17, 8)) == .learning(days: 3, of: 14))
        }
    }

    @Test func warmEngineSeesOtherConnectionsCommits() throws {
        try withBaseline { h in
            let key = BaselineHarness.defaultKey
            try h.add(20, throughput: 40, month: 9, day: 2, hour: 9)
            let point = h.at(9, 2, 10, 30) // cutoff 10:00
            #expect(try h.usual(point).samples[key] == 20)
            func fresh() throws -> UsualTable {
                try BaselineEngine(store: Store.open(h.url, mode: .readOnly), calendar: h.calendar)
                    .usual(provider: .codex, model: h.model, at: point)
            }

            // The collector, on its own connection, ingests responses ending 09:30–09:49 late.
            let collector = try Store.open(h.url, mode: .readWrite)
            var synth = Synth(firstNumber: 100)
            try collector.upsert(responses: synth.responses(20, throughput: 20, from: h.at(9, 2, 9, 30)))
            let withLate = try fresh()
            #expect(withLate.samples[key] == 40)
            #expect(try h.usual(point) == withLate)

            // Catch-up then records a slower episode over them that fired before the cutoff.
            try collector.insertEpisode(EpisodeRow(
                rule: EpisodeRow.slowerRule, provider: ProviderID.codex.rawValue, scope: h.model, direction: .slower,
                onset: h.at(9, 2, 9, 25), firedAt: h.at(9, 2, 9, 50), endedAt: h.at(9, 2, 9, 55),
                endReason: EpisodeRow.EndReason.idleEnded, severity: "red", worstValue: 0.5))
            let withEpisode = try fresh()
            #expect(withEpisode.samples[key] == 20)
            #expect(try h.usual(point) == withEpisode)
        }
    }

    @Test func acceptComputesBeforeFromCurrentData() throws {
        try withBaseline { h in
            let key = BaselineHarness.defaultKey
            try h.add(20, throughput: 40, month: 9, day: 2, hour: 9)
            #expect(try h.usual(h.at(9, 2, 10, 5)).samples[key] == 20)
            // A write on the engine's own connection doesn't change data_version, so only
            // Accept's own cache reset keeps `before` (permanent history) current.
            try h.add(20, throughput: 20, month: 9, day: 2, hour: 9, minute: 30)
            try h.engine.accept(provider: .codex, model: h.model, since: h.localDay(9, 2), at: h.at(9, 2, 10, 20))
            let epoch = try #require(try h.engine.currentEpoch(provider: .codex, model: h.model))
            #expect(epoch.before.samples[key] == 40)
            #expect(approximately(epoch.before.medians[key], 30))
        }
    }

    @Test func acceptAndUndoRejectInvalidTimes() throws {
        try withBaseline { h in
            try h.seedLastingSlowdown()
            #expect(throws: StoreError.self) {
                try h.engine.accept(provider: .codex, model: h.model, since: h.localDay(9, 19), at: h.at(9, 18, 10, 20))
            }
            #expect(try RawSQLite.scalar(h.url, "SELECT COUNT(*) FROM baseline_epochs") == "0")
            #expect(try RawSQLite.scalar(h.url, "SELECT COUNT(*) FROM events") == "0")

            // The acceptance day itself is a valid since day.
            let acceptance = try h.engine.accept(provider: .codex, model: h.model, since: h.localDay(9, 18), at: h.at(9, 18, 10, 20))
            #expect(throws: StoreError.self) { try h.engine.undo(epochID: acceptance.epochID, at: h.at(9, 18, 10, 10)) }
            #expect(try h.engine.currentEpoch(provider: .codex, model: h.model)?.id == acceptance.epochID)
            #expect(try h.events(EventKind.baselineAccepted).map { $0[4] } == ["live"])
            #expect(try h.events(EventKind.baselineUndone).isEmpty)
        }
    }

    @Test func speedRuleIDsArePinned() throws {
        // Task 8's RuleID raw values for the speed rules reference these; stored rows use them.
        #expect(EpisodeRow.slowerRule == "slower")
        #expect(EpisodeRow.fasterRule == "faster")
        #expect(EpisodeRow.speedRule(.slower) == "slower")
        #expect(EpisodeRow.speedRule(.faster) == "faster")
        #expect(EpisodeRow.EndReason.cleared == "cleared")
        #expect(EpisodeRow.EndReason.idleEnded == "idleEnded")
        try withBaseline { h in
            try h.episode(onset: h.at(9, 1, 9), fired: h.at(9, 1, 9, 15), ended: nil)
            try h.episode(rule: EpisodeRow.fasterRule, direction: .faster, onset: h.at(9, 1, 10), fired: h.at(9, 1, 10, 15), ended: nil)
            #expect(try RawSQLite.column(h.url, "SELECT rule FROM episodes ORDER BY id") == ["slower", "faster"])
        }
    }

    @Test func episodeRowsRoundTripAndSpeedEpisodesFilter() throws {
        try withBaseline { h in
            let id = try h.episode(onset: h.at(9, 1, 9), fired: h.at(9, 1, 9, 15), ended: nil)
            try h.episode(rule: "largePrompts", direction: nil, onset: h.at(9, 1, 9), fired: h.at(9, 1, 9, 15), ended: nil)
            try h.episode(model: Synth.otherModel, onset: h.at(9, 1, 9), fired: h.at(9, 1, 9, 15), ended: nil)
            try h.episode(rule: EpisodeRow.fasterRule, direction: .faster, onset: h.at(9, 1, 8), fired: h.at(9, 1, 8, 15), ended: nil)

            var stored = try #require(try h.store.speedEpisodes(provider: .codex, model: h.model).last)
            #expect(try h.store.speedEpisodes(provider: .codex, model: h.model).map(\.direction) == [.faster, .slower])
            #expect(stored.id == id)
            stored.endedAt = h.at(9, 1, 10)
            stored.endReason = EpisodeRow.EndReason.cleared
            stored.severity = "red"
            stored.worstValue = 0.6
            stored.detail = Data(#"{"synthetic":true}"#.utf8)
            try h.store.updateEpisode(stored)
            #expect(try h.store.speedEpisodes(provider: .codex, model: h.model).last == stored)

            stored.id = nil
            #expect(throws: StoreError.self) { try h.store.updateEpisode(stored) }
            stored.id = 999
            #expect(throws: StoreError.self) { try h.store.updateEpisode(stored) }
        }
    }

    // MARK: Drift and mix

    @Test func driftReportedAgainstAcceptedUsual() throws {
        // After accepting from Sep 15 (usual 30), Sep 19 brings 40 responses at `rate`, enough to
        // move the current median to `rate`. Drift = rate / 30 − 1 over the same mix.
        let cases: [(rate: Double, expected: Drift?)] = [
            (28.8, nil), // −4%: under the 5% threshold
            (31.2, nil), // +4%
            (28.2, Drift(percent: 6, direction: .slower, acceptedOn: LocalDay(year: 2026, month: 9, day: 18))),
            (31.8, Drift(percent: 6, direction: .faster, acceptedOn: LocalDay(year: 2026, month: 9, day: 18))),
            (25.5, Drift(percent: 15, direction: .slower, acceptedOn: LocalDay(year: 2026, month: 9, day: 18))),
        ]
        for (rate, expected) in cases {
            try withBaseline { h in
                try h.seedLastingSlowdown()
                #expect(try h.engine.drift(provider: .codex, model: h.model, at: h.at(9, 18, 10)) == nil, "no epoch")
                try h.engine.accept(provider: .codex, model: h.model, since: h.localDay(9, 15), at: h.at(9, 18, 10, 20))
                #expect(try h.engine.drift(provider: .codex, model: h.model, at: h.at(9, 18, 10, 30)) == nil, "just accepted")
                try h.add(40, throughput: rate, month: 9, day: 19)
                #expect(try h.engine.drift(provider: .codex, model: h.model, at: h.at(9, 20, 12)) == expected, "rate \(rate)")
            }
        }
    }

    @Test func mixUsualMatchesRecentMix() throws {
        let small = UsualKey(effort: "medium", serviceTier: "none", bucket: .under50k)
        let high = UsualKey(effort: "high", serviceTier: "none", bucket: .under50k)
        let large = UsualKey(effort: "medium", serviceTier: "none", bucket: .from100k)
        let table = UsualTable(medians: [small: 40, high: 30, large: 20], samples: [small: 20, high: 20, large: 20], activeDays: 14, epochID: nil)
        var synth = Synth()
        let end = Synth.local(2026, 9, 1, 12)
        func response(effort: String = "medium", input: Int = 10_000) -> ResponseRecord {
            synth.response(effort: effort, inputTokens: input, throughput: 25, end: end)
        }

        // Mostly small prompts at medium: 40.
        #expect(mixUsual([response(), response(), response(), response(effort: "high"), response(input: 150_000)], table: table) == 40)
        // Recent work at high effort: its own usual, so a slowdown explained by effort shows no gap.
        #expect(mixUsual([response(effort: "high"), response(effort: "high"), response()], table: table) == 30)
        // Even count: the mean of the middle two. A key without usual (300k+) is left out.
        #expect(mixUsual([response(), response(input: 150_000), response(input: 400_000)], table: table) == 30)
        #expect(mixUsual([response(input: 400_000)], table: table) == nil)
        #expect(mixUsual([], table: table) == nil)
    }
}
