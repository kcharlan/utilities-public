// Port: brew_version/Sources/BrewVersion/NativeActions.swift, StatusIcon and StatusObservation, 5e1e642.
// Adaptation: the visual doc's lamp lens replaces the mug symbol, the dot takes the most severe
// lit lamp's color (Theme), and the panel snapshot replaces StatusPresentation.
import AppKit
import Observation
import TelltaleCore

/// The menu-bar lens. On macOS 27 the menu bar ignores a status button's
/// `contentTintColor` and draws a tinted template image black, which vanishes
/// on a dark bar. The lit lens therefore draws its own colours: its drawing
/// handler runs in the bar's appearance, so the text-coloured outline follows
/// light and dark, and the dot matches the lamp color in the panel.
@MainActor enum StatusIcon {
    /// The mockup's `i-lens` symbol: an 18 × 16 pt rounded rectangle with a filament.
    static let lensSize = NSSize(width: 18, height: 16)
    /// Large enough that the acknowledged ring's hole (7 pt) reads apart from a filled dot at menu-bar size.
    static let dotDiameter: CGFloat = 10
    /// How far the dot extends past the lens's right edge.
    static let dotOverhang: CGFloat = 5

    static func image(for snapshot: PanelSnapshot) -> NSImage? {
        let description = accessibility(for: snapshot)
        guard let lit = snapshot.mostSevere else {
            let lens = NSImage(size: lensSize, flipped: false) { _ in
                NSColor.black.setStroke()
                drawLens()
                return true
            }
            lens.isTemplate = true
            lens.accessibilityDescription = description
            return lens
        }
        let size = NSSize(width: lensSize.width + dotOverhang, height: lensSize.height)
        let image = NSImage(size: size, flipped: false) { _ in
            NSColor.textColor.setStroke()
            drawLens()
            let dot = NSRect(x: size.width - dotDiameter, y: size.height - dotDiameter, width: dotDiameter, height: dotDiameter)
            // Clear a thin ring so the dot reads apart from the lens's rim.
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.current?.compositingOperation = .clear
            NSBezierPath(ovalIn: dot.insetBy(dx: -1, dy: -1)).fill()
            NSGraphicsContext.restoreGraphicsState()
            if let attention = snapshot.attention {
                Theme.nsColor(attention).setFill()
                NSBezierPath(ovalIn: dot).fill()
            } else {
                Theme.nsColor(lit).setStroke()
                let ring = NSBezierPath(ovalIn: dot.insetBy(dx: 0.75, dy: 0.75))
                ring.lineWidth = 1.5
                ring.stroke()
            }
            return true
        }
        image.isTemplate = false
        image.accessibilityDescription = description
        return image
    }

    /// Spec section 9.1: the accessibility text names the lit lamps, in strip order with
    /// Collector last; a quiet panel says `Copy.nothingToReport`.
    static func accessibility(for snapshot: PanelSnapshot) -> String {
        let lit = snapshot.signals.compactMap { signal in
            snapshot.lamps[signal].flatMap { $0 }.map { "\(snapshot.labels[signal] ?? signal.rawValue.capitalized) \($0.rawValue)\(snapshot.isAcknowledged(signal) ? " (acknowledged)" : "")" }
        }
        let body = lit.isEmpty ? Copy.nothingToReport : lit.joined(separator: ", ") + "."
        return "\(TelltaleRelease.displayName): \(body)"
    }

    /// The `i-lens` path in an 18 × 16 box, y up: `rect x=1.5 y=2 w=15 h=12 rx=4` stroked 1.6,
    /// then the filament `M5.5 8.5c1.2-2 2.3-2 3.5 0s2.3 2 3.5 0` stroked 1.5 with round caps.
    private static func drawLens() {
        let height = lensSize.height
        let rim = NSBezierPath(roundedRect: NSRect(x: 1.5, y: height - 2 - 12, width: 15, height: 12), xRadius: 4, yRadius: 4)
        rim.lineWidth = 1.6
        rim.stroke()
        // SVG y runs down; flip each point.
        func point(_ x: CGFloat, _ y: CGFloat) -> NSPoint { NSPoint(x: x, y: height - y) }
        let filament = NSBezierPath()
        filament.move(to: point(5.5, 8.5))
        filament.curve(to: point(9, 8.5), controlPoint1: point(6.7, 6.5), controlPoint2: point(7.8, 6.5))
        filament.curve(to: point(12.5, 8.5), controlPoint1: point(10.2, 10.5), controlPoint2: point(11.3, 10.5))
        filament.lineWidth = 1.5
        filament.lineCapStyle = .round
        filament.stroke()
    }
}
@MainActor final class StatusObservation {
    private let store: LiveStore
    private let changed: (PanelSnapshot) -> Void
    init(store: LiveStore, changed: @escaping (PanelSnapshot) -> Void) {
        self.store = store; self.changed = changed
        observe()
    }
    private func observe() {
        withObservationTracking {
            changed(store.snapshot)
        } onChange: { [weak self] in Task { @MainActor in self?.observe() } }
    }
}
