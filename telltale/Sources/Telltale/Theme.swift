import AppKit
import SwiftUI
import TelltaleCore

/// The visual doc's colors. Lamp colors are the panel's only custom colors: amber darkens in light
/// appearance for contrast; the others keep their hue. The dashboard adds its cluster surfaces, dark
/// by default with the doc's light counterparts. Each color resolves when drawn, so the menu-bar
/// glyph follows the bar, the panel follows the system and the dashboard follows its own appearance
/// (spec section 9.4: Dark, Light or Match system).
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
    static let amber = dynamic("TelltaleAmber", dark: 0xF0A800, light: 0xB87A00)
    static let blue = rgb(0x4C8DFF)
    /// Collector running: the footer's dot and the collector view's lamps only, never "all good".
    static let green = rgb(0x3DB879)

    // MARK: Dashboard surfaces

    /// The window background: the smoked face of a gauge cluster.
    static let cluster = dynamic("TelltaleCluster", dark: 0x151B21, light: 0xF6F7F8)
    /// Unlit lamps, plot frames and separators.
    static let housing = dynamic("TelltaleHousing", dark: 0x262F37, light: 0xD9DEE2)
    /// Primary numbers and text.
    static let readout = dynamic("TelltaleReadout", dark: 0xE9EDF0, light: 0x141A1F)
    /// Labels, the "usual" values and axes. The doc names no light value; this darker grey keeps
    /// contrast on the light cluster **(plan call)**.
    static let dim = dynamic("TelltaleDim", dark: 0x8D99A3, light: 0x5D6872)
    /// The sidebar, a step darker than the cluster (the mockup's `#11171C`).
    static let sidebar = dynamic("TelltaleSidebar", dark: 0x11171C, light: 0xECEEF0)
    /// An unlit lamp's icon and caption (the mockup's `#4B5661` and `#6E7A85`).
    static let unlitIcon = dynamic("TelltaleUnlitIcon", dark: 0x4B5661, light: 0xA8AEB4)
    static let unlitCaption = dynamic("TelltaleUnlitCaption", dark: 0x6E7A85, light: 0x7A8087)
    /// Usual-speed dots and neutral event marks (the mockup's `#5A6670`).
    static let usual = dynamic("TelltaleUsual", dark: 0x5A6670, light: 0x8D99A3)
    /// A provider incident's band on the speed chart and its legend swatch: the mockup's amber at
    /// 9% fill with a 45% dashed edge. Light appearance needs more of both to show on the light
    /// cluster **(plan call)**.
    static let incidentFill = dynamic("TelltaleIncidentFill", dark: (0xF0A800, 0.09), light: (0xB87A00, 0.16))
    static let incidentEdge = dynamic("TelltaleIncidentEdge", dark: (0xF0A800, 0.45), light: (0xB87A00, 0.75))

    static func swiftUI(_ color: NSColor) -> Color { Color(nsColor: color) }

    /// Spec section 9.4's dashboard appearance; nil follows the system.
    static func dashboardAppearance(_ setting: Appearance) -> NSAppearance? {
        switch setting {
        case .dark: NSAppearance(named: .darkAqua)
        case .light: NSAppearance(named: .aqua)
        case .system: nil
        }
    }

    private static func dynamic(_ name: String, dark: (Int, CGFloat), light: (Int, CGFloat)) -> NSColor {
        NSColor(name: name) { appearance in
            let (value, alpha) = isDark(appearance) ? dark : light
            return rgb(value).withAlphaComponent(alpha)
        }
    }

    private static func isDark(_ appearance: NSAppearance) -> Bool {
        appearance.bestMatch(from: [.aqua, .darkAqua, .vibrantLight, .vibrantDark]).map { [.darkAqua, .vibrantDark].contains($0) } == true
    }

    private static func dynamic(_ name: String, dark: Int, light: Int) -> NSColor {
        NSColor(name: name) { isDark($0) ? rgb(dark) : rgb(light) }
    }

    private static func rgb(_ value: Int) -> NSColor {
        NSColor(srgbRed: CGFloat((value >> 16) & 0xFF) / 255, green: CGFloat((value >> 8) & 0xFF) / 255, blue: CGFloat(value & 0xFF) / 255, alpha: 1)
    }
}
