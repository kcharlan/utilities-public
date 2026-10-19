import Foundation

public enum DisplayFormatter {
    /// The menu bar passes a thin space as the separator; other readings keep a full space.
    public static func watts(centi: Int, separator: String = " ") -> String { scaled(centi, divisor: 100, places: 2) + separator + "W" }
    public static func volts(milli: Int) -> String { scaled(milli, divisor: 1000, places: 3) + " V" }
    public static func amps(milli: Int) -> String { scaled(milli, divisor: 1000, places: 3) + " A" }

    private static func scaled(_ value: Int, divisor: UInt, places: Int) -> String {
        let magnitude = value.magnitude
        let fraction = String(magnitude % divisor)
        return (value < 0 ? "-" : "") + String(magnitude / divisor) + "."
            + String(repeating: "0", count: places - fraction.count) + fraction
    }

    public static func age(_ seconds: TimeInterval) -> String {
        let whole = seconds.isFinite ? max(0, seconds.rounded(.down)) : 0
        // Clamp before converting, including TimeInterval values outside Int's range.
        let count = whole >= Double(Int.max) ? Int.max : Int(whole)
        return count < 60 ? "\(count) s ago" : "\(count / 60) min ago"
    }
}
