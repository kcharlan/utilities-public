import Foundation

/// Point size of the status item's reading; the symbol is drawn at the same size.
public enum MenuBarTextSize: Int, CaseIterable, Codable, Sendable {
    case pt10 = 10, pt11 = 11, pt12 = 12, pt13 = 13
    /// The system menu bar font size.
    public static let `default`: MenuBarTextSize = .pt13
    public var pointSize: Double { Double(rawValue) }
}
