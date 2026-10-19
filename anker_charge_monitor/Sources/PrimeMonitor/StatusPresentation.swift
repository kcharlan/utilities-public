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

    /// Compact title: the button's own image–title gap replaces a leading
    /// space, and a thin space separates the unit. The symbol matches the text size.
    @MainActor func apply(to button: NSButton) {
        let size = CGFloat(textSize.pointSize)
        let image = NSImage(systemSymbolName: symbol, accessibilityDescription: accessibility)?
            .withSymbolConfiguration(.init(pointSize: size, weight: .regular))
        image?.isTemplate = true; button.image = image
        button.imagePosition = .imageLeading
        button.contentTintColor = dimmed ? .secondaryLabelColor : nil
        button.setAccessibilityLabel(accessibility)
        button.setAccessibilityHelp(accessibility)
        button.toolTip = tooltip
        button.attributedTitle = NSAttributedString(string: title, attributes: [.font: NSFont.monospacedDigitSystemFont(ofSize: size, weight: .regular), .foregroundColor: dimmed ? NSColor.secondaryLabelColor : NSColor.labelColor])
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
