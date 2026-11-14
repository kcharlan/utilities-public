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
    var otherCount: Int = 0
    enum Badge { case none, watched, other }
    var badge: Badge { amberCount > 0 ? .watched : (otherCount > 0 ? .other : .none) }
    var accessibility: String {
        let watched = amberCount == 0 ? "Brew Version, no watched updates" : "Brew Version, \(amberCount) watched update\(amberCount == 1 ? "" : "s") available"
        guard otherCount > 0 else { return watched }
        return watched + ", \(otherCount) other update\(otherCount == 1 ? "" : "s")"
    }
}
/// The menu bar mug resolves its outline and other-updates dot in the bar's
/// appearance. A watched update takes precedence and draws one amber dot.
/// Badged images draw their own colours because macOS 27 ignores a status
/// button's contentTintColor when drawing template images.
@MainActor enum StatusIcon {
    static let dotDiameter: CGFloat = 7
    /// How far the dot extends past the mug's right edge.
    static let dotOverhang: CGFloat = 3
    static func image(for presentation: StatusPresentation) -> NSImage? {
        guard let mug = NSImage(systemSymbolName: "mug", accessibilityDescription: presentation.accessibility) else { return nil }
        guard presentation.badge != .none, let outline = mug.withSymbolConfiguration(.init(paletteColors: [.textColor])) else {
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
            (presentation.badge == .watched ? NSColor.systemOrange : NSColor.textColor).setFill()
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
            changed(StatusPresentation(amberCount: controller.amberCount, otherCount: controller.badgedOtherCount))
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

@MainActor struct LogRevealAction {
    let fileURL: URL
    private let revealURL: (URL) -> Void
    init(fileURL: URL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/Brew Version/events.jsonl"),
         reveal: @escaping (URL) -> Void = { NSWorkspace.shared.activateFileViewerSelecting([$0]) }) {
        self.fileURL = fileURL; self.revealURL = reveal
    }
    func reveal() {
        revealURL(FileManager.default.fileExists(atPath: fileURL.path) ? fileURL : fileURL.deletingLastPathComponent())
    }
}
