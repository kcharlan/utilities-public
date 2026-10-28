import Foundation
import TelltaleCore

/// Places conspicuously synthetic responses for the baseline and rule tests: a model, an
/// effort, a service tier, an input size, a throughput and an end time. Response ids are
/// deterministic (`resp_synthetic_NN`, counting up from `firstNumber`).
public struct Synth {
    public static let model = "example-model-1.0"
    public static let otherModel = "example-model-2.0"
    public static let sessionID = "00000000-0000-4000-8000-000000000001"

    /// The calendar the baseline and rule tests use.
    public static var newYork: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "America/New_York")!
        return calendar
    }

    /// A local time in `calendar` (default `newYork`).
    public static func local(
        _ year: Int, _ month: Int, _ day: Int, _ hour: Int = 0, _ minute: Int = 0, _ second: Int = 0,
        calendar: Calendar = Synth.newYork
    ) -> Date {
        calendar.date(from: DateComponents(year: year, month: month, day: day, hour: hour, minute: minute, second: second))!
    }

    public var provider: ProviderID
    public private(set) var nextNumber: Int

    public init(provider: ProviderID = .codex, firstNumber: Int = 1) {
        self.provider = provider
        self.nextNumber = firstNumber
    }

    /// One response ending at `end`. Its duration is `outputTokens / throughput`, so
    /// `throughput` is the record's computed throughput when `outputTokens` is at least 300.
    public mutating func response(
        model: String = Synth.model, effort: String? = "medium", tier: String? = nil, inputTokens: Int = 10_000,
        throughput: Double, end: Date, outputTokens: Int = 1_000
    ) -> ResponseRecord {
        let number = nextNumber
        nextNumber += 1
        let duration = Double(outputTokens) / throughput
        return ResponseRecord(
            provider: provider, model: model, effort: effort, serviceTier: tier, sessionID: Self.sessionID,
            isSubagent: false, turnID: String(format: "turn_synthetic_%02ld", number),
            responseID: String(format: "resp_synthetic_%02ld", number),
            start: end.addingTimeInterval(-duration), end: end, inputTokens: inputTokens,
            cachedInputTokens: 0, outputTokens: outputTokens)
    }

    /// `count` responses ending `spacing` seconds apart, the first at `firstEnd`.
    public mutating func responses(
        _ count: Int, model: String = Synth.model, effort: String? = "medium", tier: String? = nil,
        inputTokens: Int = 10_000, throughput: Double, from firstEnd: Date, spacing: TimeInterval = 60,
        outputTokens: Int = 1_000
    ) -> [ResponseRecord] {
        (0..<count).map { index in
            response(
                model: model, effort: effort, tier: tier, inputTokens: inputTokens, throughput: throughput,
                end: firstEnd.addingTimeInterval(Double(index) * spacing), outputTokens: outputTokens)
        }
    }
}
