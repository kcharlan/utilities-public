import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

@Suite struct SpeedIndexTests {
    let point = Synth.local(2026, 9, 4, 9, 15)

    /// Usual 40 tok/s for medium effort and 20 for high; no usual for any other effort.
    static func usual(_ response: ResponseRecord) -> Double? {
        switch response.effort {
        case "medium": 40
        case "high": 20
        default: nil
        }
    }

    func ending(_ secondsBeforePoint: TimeInterval) -> Date { point.addingTimeInterval(-secondsBeforePoint) }

    @Test func medianOfRatiosInTrailingWindow() {
        var synth = Synth()
        // Spec section 7.1: responses ending in the trailing 15 minutes, (09:00, 09:15].
        let medium = [30.0, 32, 34, 36, 38, 44].enumerated().map { synth.response(throughput: $1, end: ending(Double($0) * 60)) }
        let high = [10.0, 14, 18, 22, 26].enumerated().map { synth.response(effort: "high", throughput: $1, end: ending(Double($0) * 60 + 30)) }
        let outside = [
            synth.response(throughput: 5, end: ending(15 * 60)),  // exactly 15 minutes old: outside
            synth.response(throughput: 5, end: point.addingTimeInterval(1)),  // after the point
        ]
        let reading = SpeedIndex.at(point, responses: medium + high + outside, usual: Self.usual)

        // Ratios: 0.75 0.8 0.85 0.9 0.95 1.1 (medium); 0.5 0.7 0.9 1.1 1.3 (high). Median of 11: 0.9.
        #expect(reading.samples == 11)
        #expect(approximately(reading.index, 0.9))
        // Mix-matched usual (spec section 8): median of each response's own usual, 6 × 40 and 5 × 20.
        #expect(approximately(reading.mixUsual, 40))
        // Median throughput of the same 11 responses.
        #expect(approximately(reading.medianTPS, 30))
        #expect(SpeedIndex.windowMinutes == 15)
        #expect(SpeedIndex.minimumSamples == 10)
    }

    @Test func belowMinimumSamplesIsUnknown() {
        var synth = Synth()
        let nine = (0..<9).map { synth.response(throughput: 30, end: ending(Double($0) * 60)) }
        let thin = SpeedIndex.at(point, responses: nine, usual: Self.usual)
        #expect(thin.index == nil)
        #expect(thin.samples == 9)
        // The window's speed and usual are still reported for charts.
        #expect(approximately(thin.medianTPS, 30))
        #expect(approximately(thin.mixUsual, 40))

        let ten = nine + [synth.response(throughput: 30, end: ending(600))]
        #expect(approximately(SpeedIndex.at(point, responses: ten, usual: Self.usual).index, 0.75))

        let empty = SpeedIndex.at(point, responses: [], usual: Self.usual)
        #expect(empty == SpeedReading(index: nil, mixUsual: nil, medianTPS: nil, samples: 0))
    }

    @Test func responsesWithoutUsualAreLeftOut() {
        var synth = Synth()
        let judged = (0..<10).map { synth.response(throughput: 30, end: ending(Double($0) * 60)) }
        // A key below the bucket minimum has no usual (spec section 8): left out of the index.
        let unjudged = (0..<5).map { synth.response(effort: "low", throughput: 400, end: ending(Double($0) * 60 + 10)) }
        let reading = SpeedIndex.at(point, responses: judged + unjudged, usual: Self.usual)
        #expect(reading.samples == 10)
        #expect(approximately(reading.index, 0.75))
        #expect(approximately(reading.medianTPS, 30))

        let onlyUnjudged = SpeedIndex.at(point, responses: unjudged, usual: Self.usual)
        #expect(onlyUnjudged == SpeedReading(index: nil, mixUsual: nil, medianTPS: nil, samples: 0))
    }

    @Test func shortResponsesIgnored() {
        var synth = Synth()
        let nine = (0..<9).map { synth.response(throughput: 30, end: ending(Double($0) * 60)) }
        // Under 300 output tokens there is no throughput (spec section 6.1).
        let short = (0..<5).map { synth.response(throughput: 5, end: ending(Double($0) * 60 + 20), outputTokens: 299) }
        let reading = SpeedIndex.at(point, responses: nine + short, usual: Self.usual)
        #expect(reading.samples == 9)
        #expect(reading.index == nil)
    }

    @Test func speedRuleConditionsUseFractions() {
        // Spec section 7.4 defaults: slower fires at ≤ 0.85, clears above 0.92, is red at ≤ 0.70.
        let slower = RuleSettings.defaults.slower
        #expect(slower.conditions(index: 0.80, direction: .slower) == SpeedConditions(trigger: .true, clear: .false, red: .false))
        #expect(slower.conditions(index: 0.90, direction: .slower) == SpeedConditions(trigger: .false, clear: .false, red: .false))
        #expect(slower.conditions(index: 0.95, direction: .slower) == SpeedConditions(trigger: .false, clear: .true, red: .false))
        #expect(slower.conditions(index: 0.65, direction: .slower) == SpeedConditions(trigger: .true, clear: .false, red: .true))
        #expect(slower.conditions(index: nil, direction: .slower) == SpeedConditions(trigger: .unknown, clear: .unknown, red: .unknown))
        // Faster: fires at ≥ 1.15, clears below 1.08, never red (its lamp is blue).
        let faster = RuleSettings.defaults.faster
        #expect(faster.conditions(index: 1.20, direction: .faster) == SpeedConditions(trigger: .true, clear: .false, red: .false))
        #expect(faster.conditions(index: 1.10, direction: .faster) == SpeedConditions(trigger: .false, clear: .false, red: .false))
        #expect(faster.conditions(index: 1.05, direction: .faster) == SpeedConditions(trigger: .false, clear: .true, red: .false))
        #expect(faster.conditions(index: 1.60, direction: .faster) == SpeedConditions(trigger: .true, clear: .false, red: .false))
    }
}
