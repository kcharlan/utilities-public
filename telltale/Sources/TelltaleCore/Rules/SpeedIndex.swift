import Foundation

/// One model's speed at an evaluation point (spec section 7.1). `samples` counts the responses
/// with both a throughput and a usual in the trailing window; `index` is nil when there are
/// fewer than `SpeedIndex.minimumSamples`. `mixUsual` and `medianTPS` describe the same
/// responses whenever there is at least one.
public struct SpeedReading: Sendable, Equatable, Hashable {
    public var index: Double?
    public var mixUsual: Double?
    public var medianTPS: Double?
    public var samples: Int

    public init(index: Double?, mixUsual: Double?, medianTPS: Double?, samples: Int) {
        self.index = index
        self.mixUsual = mixUsual
        self.medianTPS = medianTPS
        self.samples = samples
    }
}

public enum SpeedIndex {
    /// The trailing window, in minutes.
    public static let windowMinutes = 15
    /// Fewer qualifying responses than this make the point unknown ("thin data").
    public static let minimumSamples = 10

    /// The median, over responses ending in `(point − 15 min, point]` with a throughput and a
    /// usual, of throughput ÷ usual. Responses outside the window are ignored, so callers may
    /// pass a superset.
    public static func at(_ point: Date, responses: [ResponseRecord], usual: (ResponseRecord) -> Double?) -> SpeedReading {
        let start = point.addingTimeInterval(-TimeInterval(windowMinutes * 60))
        var ratios: [Double] = []
        var usuals: [Double] = []
        var throughputs: [Double] = []
        for response in responses where response.end > start && response.end <= point {
            guard let throughput = response.throughput, let expected = usual(response), expected > 0 else { continue }
            ratios.append(throughput / expected)
            usuals.append(expected)
            throughputs.append(throughput)
        }
        return SpeedReading(
            index: ratios.count >= minimumSamples ? median(ratios) : nil, mixUsual: median(usuals),
            medianTPS: median(throughputs), samples: ratios.count)
    }
}

/// A rule's view of one evaluation point.
public struct SpeedConditions: Sendable, Equatable, Hashable {
    public var trigger: Tri
    public var clear: Tri
    public var red: Tri

    public init(trigger: Tri, clear: Tri, red: Tri) {
        self.trigger = trigger
        self.clear = clear
        self.red = red
    }

    public static let unknown = SpeedConditions(trigger: .unknown, clear: .unknown, red: .unknown)
}

extension SpeedRule {
    /// Spec section 7.4 with this rule's fractions as index boundaries (`1 ± fraction`).
    /// Slower fires at `≤ 1 − threshold`, clears above `1 − clearBand` and is red at
    /// `≤ 1 − 2 × threshold` (spec section 7.2). Faster fires at `≥ 1 + threshold`, clears below
    /// `1 + clearBand` and is never red: its lamp is blue. A missing index is unknown.
    public func conditions(index: Double?, direction: Direction) -> SpeedConditions {
        guard let index else { return .unknown }
        switch direction {
        case .slower:
            return SpeedConditions(
                trigger: Tri(index <= 1 - threshold), clear: Tri(index > 1 - clearBand), red: Tri(index <= 1 - 2 * threshold))
        case .faster:
            return SpeedConditions(trigger: Tri(index >= 1 + threshold), clear: Tri(index < 1 + clearBand), red: .false)
        }
    }
}
