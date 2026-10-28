import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

/// Spec section 9.2's Workload measures, last 3 hours against usual, on a seeded store
/// (`BaselineHarness`: Sep 2026 in New York, the synthetic model "Example").
private struct WorkloadSeed {
    let h: BaselineHarness
    var number = 0

    init(_ h: BaselineHarness) { self.h = h }

    /// One response ending at `end`, with every workload field chosen.
    mutating func response(
        _ end: Date, session: Int = 1, subagent: Bool = false, effort: String? = "medium", input: Int = 10_000, cached: Int = 0,
        output: Int = 1_000, reasoning: Int? = nil
    ) -> ResponseRecord {
        number += 1
        return ResponseRecord(
            provider: .codex, model: Synth.model, effort: effort, sessionID: String(format: "00000000-0000-4000-8000-%012ld", session),
            isSubagent: subagent, turnID: String(format: "turn_synthetic_%02ld", number), responseID: String(format: "resp_synthetic_%02ld", number),
            start: end.addingTimeInterval(-25), end: end, inputTokens: input, cachedInputTokens: cached, outputTokens: output,
            reasoningTokens: reasoning)
    }

    /// `count` responses a minute apart from `first`.
    mutating func add(_ count: Int, from first: Date, session: Int = 1, effort: String? = "medium", input: Int = 10_000) throws {
        var records: [ResponseRecord] = []
        for index in 0..<count {
            records.append(response(first.addingTimeInterval(Double(index) * 60), session: session, effort: effort, input: input))
        }
        try h.store.upsert(responses: records)
    }

    func load(at now: Date) throws -> Workload {
        try Workload.load(store: h.store, provider: .codex, model: Synth.model, now: now, calendar: h.calendar)
    }
}

@Suite struct WorkloadTests {
    @Test func nowIsLastThreeHoursActiveHoursOnly() throws {
        try withBaseline { h in
            var seed = WorkloadSeed(h)
            let now = h.at(9, 4, 12)
            // 09:00–10:00: 20 responses from one session. 10:00–11:00: nothing. 11:00–12:00: 10 from two sessions.
            try seed.add(20, from: h.at(9, 4, 9, 5))
            try seed.add(5, from: h.at(9, 4, 11, 1), session: 2)
            try seed.add(5, from: h.at(9, 4, 11, 30), session: 3)
            // Before the window.
            try seed.add(40, from: h.at(9, 4, 8, 0), session: 4)

            let workload = try seed.load(at: now)
            #expect(workload.window == DateInterval(start: h.at(9, 4, 9), end: now))
            // 30 responses over 2 active hours, not 3.
            #expect(approximately(workload.responsesPerHour.now, 15))
            // One session, then two: 1.5 an active hour.
            #expect(approximately(workload.activeSessions.now, 1.5))
            #expect(approximately(workload.medianPrompt.now, 10_000))

            let quiet = try seed.load(at: h.at(9, 4, 23))
            #expect(quiet.responsesPerHour.now == nil && quiet.medianPrompt.now == nil && quiet.cachedShare.now == nil)
        }
    }

    @Test func usualIsMedianOfActiveHours() throws {
        try withBaseline { h in
            var seed = WorkloadSeed(h)
            // Sep 1: 10 responses at 09:xx and 30 at 14:xx; Sep 2: 20 at 10:xx. Idle hours don't count as zeros.
            try seed.add(10, from: h.at(9, 1, 9), input: 20_000)
            try seed.add(30, from: h.at(9, 1, 14), input: 100_000)
            try seed.add(20, from: h.at(9, 2, 10), input: 60_000)
            // The window itself never counts toward usual.
            try seed.add(50, from: h.at(9, 4, 9, 5), input: 300_000)

            let workload = try seed.load(at: h.at(9, 4, 12))
            #expect(approximately(workload.responsesPerHour.usual, 20))
            #expect(approximately(workload.medianPrompt.usual, 60_000))
            #expect(approximately(workload.activeSessions.usual, 1))
            #expect(workload.usualActiveDays == 2)
        }
    }

    @Test func sharesComputedFromSums() throws {
        try withBaseline { h in
            var seed = WorkloadSeed(h)
            try h.store.upsert(responses: [
                seed.response(h.at(9, 4, 11), subagent: true, input: 100_000, cached: 90_000, output: 1_000, reasoning: 800),
                seed.response(h.at(9, 4, 11, 5), input: 10_000, cached: 0, output: 3_000, reasoning: 0),
                // No reasoning recorded: left out of the reasoning share, counted elsewhere.
                seed.response(h.at(9, 4, 11, 10), input: 10_000, cached: 10_000, output: 1_000, reasoning: nil),
            ])
            let workload = try seed.load(at: h.at(9, 4, 12))
            // 100k cached of 120k input, not the mean of 0.9, 0 and 1.
            #expect(approximately(workload.cachedShare.now, 100_000.0 / 120_000))
            // 800 reasoning of 4,000 output among responses that record reasoning.
            #expect(approximately(workload.reasoningShare.now, 0.2))
            #expect(approximately(workload.subagentShare.now, 1.0 / 3))
        }
    }

    @Test func effortMixSumsToOne() throws {
        try withBaseline { h in
            var seed = WorkloadSeed(h)
            try seed.add(3, from: h.at(9, 4, 11), effort: "high")
            try seed.add(1, from: h.at(9, 4, 11, 30), effort: "medium")
            try seed.add(10, from: h.at(9, 1, 9), effort: "medium")
            try seed.add(5, from: h.at(9, 2, 9), effort: "low")
            try seed.add(5, from: h.at(9, 2, 10), effort: nil)

            let mix = try seed.load(at: h.at(9, 4, 12)).effortMix
            #expect(Set(mix.map(\.effort)) == ["high", "medium", "low", nil])
            #expect(approximately(mix.reduce(0) { $0 + $1.now }, 1))
            #expect(approximately(mix.reduce(0) { $0 + $1.usual }, 1))
            #expect(approximately(mix.first { $0.effort == "high" }?.now, 0.75))
            #expect(approximately(mix.first { $0.effort == "medium" }?.usual, 0.5))
            #expect(approximately(mix.first { $0.effort == nil }?.usual, 0.25))
        }
    }

    @Test func histogramSharesBothSides() throws {
        try withBaseline { h in
            var seed = WorkloadSeed(h)
            try seed.add(2, from: h.at(9, 4, 11), input: 10_000)
            try seed.add(2, from: h.at(9, 4, 11, 10), input: 320_000)
            try seed.add(3, from: h.at(9, 2, 9), input: 10_000)
            try seed.add(1, from: h.at(9, 2, 10), input: 120_000)

            let histogram = try seed.load(at: h.at(9, 4, 12)).histogram
            #expect(histogram.map(\.bucket) == InputBucket.allCases)
            #expect(histogram.map(\.now) == [0.5, 0, 0, 0, 0.5])
            #expect(histogram.map(\.usual) == [0.75, 0, 0.25, 0, 0])
        }
    }

    @Test func usageLimitIncluded() throws {
        try withBaseline { h in
            let seed = WorkloadSeed(h)
            #expect(try seed.load(at: h.at(9, 4, 12)).usageLimit == nil)
            let limit = UsageLimitSnapshot(provider: .codex, at: h.at(9, 4, 11), usedPercent: 42, windowMinutes: 300, resetsAt: h.at(9, 4, 15))
            try h.store.setUsageLimit(limit)
            #expect(try seed.load(at: h.at(9, 4, 12)).usageLimit == limit)
        }
    }
}
