import AppKit
import BrewVersionCore
import Observation

@MainActor struct HomepageAction {
    var openURL: (URL) -> Void
    init(open: @escaping (URL) -> Void = { NSWorkspace.shared.open($0) }) { openURL = open }
    static func isAvailable(_ url: URL) -> Bool {
        ["http", "https"].contains(url.scheme?.lowercased() ?? "") && url.host?.isEmpty == false
    }
    @discardableResult func open(_ url: URL) -> Bool {
        guard Self.isAvailable(url) else { return false }
        openURL(url); return true
    }
}
struct StatusPresentation {
    let amberCount: Int
    var accessibility: String {
        if amberCount == 0 { return "Brew Version, no watched updates" }
        return "Brew Version, \(amberCount) watched update\(amberCount == 1 ? "" : "s") available"
    }
}
/// The menu bar mug. On macOS 27 the menu bar ignores a status button's
/// `contentTintColor` and draws a tinted template image black, which vanishes
/// on a dark bar. The alert mug therefore draws its own colours: its drawing
/// handler runs in the bar's appearance, so the text-coloured outline follows
/// light and dark, and the amber dot matches the dot on an amber watch row.
@MainActor enum StatusIcon {
    static let dotDiameter: CGFloat = 7
    /// How far the dot extends past the mug's right edge.
    static let dotOverhang: CGFloat = 3
    static func image(for presentation: StatusPresentation) -> NSImage? {
        guard let mug = NSImage(systemSymbolName: "mug", accessibilityDescription: presentation.accessibility) else { return nil }
        guard presentation.amberCount > 0, let outline = mug.withSymbolConfiguration(.init(paletteColors: [.textColor])) else {
            mug.isTemplate = true
            return mug
        }
        let size = NSSize(width: mug.size.width + dotOverhang, height: mug.size.height)
        let image = NSImage(size: size, flipped: false) { _ in
            outline.draw(in: NSRect(origin: .zero, size: mug.size))
            let dot = NSRect(x: size.width - dotDiameter, y: size.height - dotDiameter, width: dotDiameter, height: dotDiameter)
            // Clear a thin ring so the dot reads apart from the mug's rim.
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.current?.compositingOperation = .clear
            NSBezierPath(ovalIn: dot.insetBy(dx: -1, dy: -1)).fill()
            NSGraphicsContext.restoreGraphicsState()
            NSColor.systemOrange.setFill()
            NSBezierPath(ovalIn: dot).fill()
            return true
        }
        image.isTemplate = false
        image.accessibilityDescription = presentation.accessibility
        return image
    }
}
@MainActor final class StatusObservation {
    private let controller: WatchController
    private let changed: (StatusPresentation) -> Void
    init(controller: WatchController, changed: @escaping (StatusPresentation) -> Void) {
        self.controller = controller; self.changed = changed
        observe()
    }
    private func observe() {
        withObservationTracking {
            changed(StatusPresentation(amberCount: controller.amberCount))
        } onChange: { [weak self] in Task { @MainActor in self?.observe() } }
    }
}
struct PersistencePresentation {
    let issue: PersistenceIssue?
    var saveHint: String? { issue == .saveFailure ? "Retry the failed action to save it." : nil }
}
func installedSourceNote(_ installed: InstalledVersion?) -> String? {
    installed?.source == .caskroomFallback ? "Version from Homebrew's records; the app may have updated itself." : nil
}
struct IntervalSelection {
    let current: CheckInterval
    var presets = CheckInterval.presets
    var options: [CheckInterval] { presets.contains(current) ? presets : presets + [current] }
}
@MainActor @Observable final class CustomIntervalInput {
    var minutes: String
    var invalid = false
    init(minutes: String = "") { self.minutes = minutes }
    var validInterval: CheckInterval? {
        guard !minutes.isEmpty, minutes.utf8.allSatisfy({ (48...57).contains($0) }), let number = Int(minutes) else { return nil }
        return CheckInterval(minutes: number)
    }
    func save(controller: WatchController) -> Bool {
        guard let interval = validInterval else { invalid = true; return false }
        invalid = false
        controller.setInterval(interval)
        return controller.state.interval == interval
    }
}
