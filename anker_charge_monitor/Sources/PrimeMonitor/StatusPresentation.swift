import Foundation
import AppKit
import Observation
import PrimeMonitorCore

struct StatusPresentation: Equatable {
    let symbol: String
    let title: String
    let dimmed: Bool
    let tooltip: String
    let accessibility: String
    var textSize: MenuBarTextSize = .default

    /// Shows the symbol and reading as one image with no button title.
    /// NSStatusBarButton's title cell pads a title by about 3 pt on each side;
    /// an image-only button adds nothing. A thin space separates the unit.
    @MainActor func apply(to button: NSButton) {
        // Clear the title first: setting a title can change imagePosition.
        button.title = ""
        button.image = StatusImage.make(for: self)
        button.imagePosition = .imageOnly
        button.setAccessibilityLabel(accessibility)
        button.setAccessibilityHelp(accessibility)
        button.toolTip = tooltip
    }

    static func make(status: ConnectionStatus, snapshot: ChargerSnapshot?, isStale: Bool, now: Date, textSize: MenuBarTextSize = .default) -> Self {
        if status == .notConfigured {
            return .init(symbol: "bolt.fill", title: "", dimmed: false, tooltip: "Open Settings to sign in", accessibility: "\(PrimeMonitorRelease.displayName), open Settings to sign in", textSize: textSize)
        }
        let title = snapshot.map { DisplayFormatter.watts(centi: $0.totalPowerCenti, separator: "\u{2009}") } ?? ""
        let spoken = snapshot.map { DisplayFormatter.watts(centi: $0.totalPowerCenti) } ?? ""
        let reason: String
        let failed: Bool
        switch status {
        case .connected: reason = isStale ? "Stale readings" : "Connected"; failed = isStale
        case .connecting: reason = "Connecting"; failed = isStale && snapshot != nil
        case .networkUnavailable: reason = "Network unavailable"; failed = true
        case .sessionEnded: reason = "Session ended — sign in again"; failed = true
        case .signInFailed(let message), .error(let message): reason = message; failed = true
        case .verificationRequired: reason = "Verification required — open the Anker app"; failed = true
        case .notConfigured: reason = "Open Settings to sign in"; failed = false
        }
        let age = snapshot.map { "; updated " + DisplayFormatter.age(now.timeIntervalSince($0.receivedAt)) } ?? ""
        let tooltip = reason + age
        return .init(symbol: failed ? "exclamationmark.triangle.fill" : "bolt.fill", title: title, dimmed: failed, tooltip: tooltip, accessibility: "\(PrimeMonitorRelease.displayName), " + (spoken.isEmpty ? "" : spoken + ", ") + tooltip, textSize: textSize)
    }
}

/// Draws the status symbol, a fixed gap and the reading into one image,
/// following Brew Version's StatusIcon (NativeActions.swift). Colours resolve
/// in the drawing handler, which runs under the menu bar's real appearance;
/// the macOS 27 menu bar draws a tinted template image black. `textColor`
/// stays opaque in every appearance, unlike `labelColor`.
@MainActor enum StatusImage {
    static let gap: CGFloat = 4
    static func font(_ size: MenuBarTextSize) -> NSFont { .monospacedDigitSystemFont(ofSize: size.pointSize, weight: .regular) }
    static func make(for presentation: StatusPresentation) -> NSImage? {
        let color: NSColor = presentation.dimmed ? .secondaryLabelColor : .textColor
        let configuration = NSImage.SymbolConfiguration(pointSize: presentation.textSize.pointSize, weight: .regular)
            .applying(.init(paletteColors: [color]))
        guard let symbol = NSImage(systemSymbolName: presentation.symbol, accessibilityDescription: nil)?
            .withSymbolConfiguration(configuration) else { return nil }
        let title = NSAttributedString(string: presentation.title, attributes: [.font: font(presentation.textSize), .foregroundColor: color])
        let text = presentation.title.isEmpty ? .zero : title.size()
        let size = NSSize(width: ceil(symbol.size.width + (text.width > 0 ? gap + text.width : 0)),
                          height: ceil(max(symbol.size.height, text.height)))
        let image = NSImage(size: size, flipped: false) { _ in
            symbol.draw(in: NSRect(x: 0, y: (size.height - symbol.size.height) / 2, width: symbol.size.width, height: symbol.size.height))
            if text.width > 0 { title.draw(at: NSPoint(x: symbol.size.width + gap, y: (size.height - text.height) / 2)) }
            return true
        }
        image.isTemplate = false
        image.accessibilityDescription = presentation.accessibility
        return image
    }
}

// Port: BV NativeActions.swift, StatusObservation, 579ebb7. Observe monitor
// presentation rather than watched update counts; use the shared Core formatter.
@MainActor final class StatusObservation {
    private let controller: MonitorController
    private let changed: (StatusPresentation) -> Void
    init(controller: MonitorController, changed: @escaping (StatusPresentation) -> Void) {
        self.controller = controller; self.changed = changed
        observe()
    }
    private func observe() {
        withObservationTracking {
            changed(.make(status: controller.status, snapshot: controller.snapshot, isStale: controller.isStale, now: controller.displayTime,
                         textSize: controller.appState.menuBarTextSize ?? .default))
        } onChange: { [weak self] in Task { @MainActor in self?.observe() } }
    }
}
