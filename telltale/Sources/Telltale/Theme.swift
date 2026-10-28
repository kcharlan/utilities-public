import AppKit
import SwiftUI
import TelltaleCore

/// The visual doc's lamp colors, the panel's only custom colors. Amber darkens in light
/// appearance for contrast; the others keep their hue. Each color resolves when drawn, so the
/// menu-bar glyph follows the bar and the panel follows the system.
enum Theme {
    static func nsColor(_ lamp: LampColor) -> NSColor {
        switch lamp {
        case .red: red
        case .amber: amber
        case .blue: blue
        }
    }
    static func color(_ lamp: LampColor) -> Color { Color(nsColor: nsColor(lamp)) }

    static let red = rgb(0xE5484D)
    static let amber = NSColor(name: "TelltaleAmber") { appearance in
        appearance.bestMatch(from: [.aqua, .darkAqua, .vibrantLight, .vibrantDark]).map { [.darkAqua, .vibrantDark].contains($0) } == true
            ? rgb(0xF0A800) : rgb(0xB87A00)
    }
    static let blue = rgb(0x4C8DFF)
    /// Collector running: the footer's dot only, never "all good".
    static let green = rgb(0x3DB879)

    private static func rgb(_ value: Int) -> NSColor {
        NSColor(srgbRed: CGFloat((value >> 16) & 0xFF) / 255, green: CGFloat((value >> 8) & 0xFF) / 255, blue: CGFloat(value & 0xFF) / 255, alpha: 1)
    }
}
