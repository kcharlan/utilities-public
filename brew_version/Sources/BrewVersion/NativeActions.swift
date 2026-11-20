import AppKit
import CoreText
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
    static func countLabel(_ count: Int) -> String {
        count > 99 ? "99+" : String(count)
    }
    var accessibility: String {
        let watched = amberCount == 0 ? "Brew Version, no watched updates" : "Brew Version, \(amberCount) watched update\(amberCount == 1 ? "" : "s") available"
        guard otherCount > 0 else { return watched }
        return watched + ", \(otherCount) other update\(otherCount == 1 ? "" : "s")"
    }
}
/// The menu bar mug shows an amber watched-count chip and an optional Other
/// updates count beside it. Their colours resolve in the bar's appearance.
/// Count images draw their own colours because macOS 27 ignores a status
/// button's contentTintColor when drawing template images.
@MainActor enum StatusIcon {
    private static func line(_ text: String, font: NSFont, color: NSColor) -> CTLine {
        CTLineCreateWithAttributedString(NSAttributedString(string: text, attributes: [.font: font, .foregroundColor: color]))
    }
    static func image(for presentation: StatusPresentation) -> NSImage? {
        guard let mug = NSImage(systemSymbolName: "mug", accessibilityDescription: presentation.accessibility) else { return nil }
        guard presentation.amberCount > 0 || presentation.otherCount > 0 else {
            mug.isTemplate = true
            return mug
        }
        guard let outline = mug.withSymbolConfiguration(.init(paletteColors: [.textColor])) else {
            mug.isTemplate = true
            return mug
        }
        let base = NSFont.systemFont(ofSize: 11, weight: .bold)
        let chipFont = base.fontDescriptor.withDesign(.rounded).flatMap { NSFont(descriptor: $0, size: 11) } ?? base
        let countFont = NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .medium)
        let watched = presentation.amberCount > 0 ? StatusPresentation.countLabel(presentation.amberCount) : nil
        let other = presentation.otherCount > 0 ? StatusPresentation.countLabel(presentation.otherCount) : nil
        func width(_ text: String, font: NSFont) -> CGFloat {
            CGFloat(CTLineGetTypographicBounds(line(text, font: font, color: .textColor), nil, nil, nil))
        }
        let chipWidth = watched.map { max(15, width($0, font: chipFont) + 8) } ?? 0
        let chipRect = NSRect(x: mug.size.width + 3, y: 1, width: chipWidth, height: 14)
        let otherWidth = other.map { width($0, font: countFont) } ?? 0
        let otherX = (watched == nil ? mug.size.width : chipRect.maxX) + 3
        let rightEdge = other == nil ? chipRect.maxX : otherX + otherWidth
        let size = NSSize(width: ceil(rightEdge), height: mug.size.height)
        let image = NSImage(size: size, flipped: false) { _ in
            outline.draw(in: NSRect(origin: .zero, size: mug.size))
            guard let context = NSGraphicsContext.current?.cgContext else { return false }
            if let watched {
                NSColor.systemOrange.setFill()
                NSBezierPath(roundedRect: chipRect, xRadius: 7, yRadius: 7).fill()
                let textLine = line(watched, font: chipFont, color: NSColor(white: 0, alpha: 0.88))
                let textWidth = CGFloat(CTLineGetTypographicBounds(textLine, nil, nil, nil))
                context.textPosition = CGPoint(x: chipRect.midX - textWidth / 2, y: chipRect.midY - chipFont.capHeight / 2)
                CTLineDraw(textLine, context)
            }
            if let other {
                let textLine = line(other, font: countFont, color: NSColor.textColor.withAlphaComponent(0.62))
                let textWidth = CGFloat(CTLineGetTypographicBounds(textLine, nil, nil, nil))
                context.textPosition = CGPoint(x: otherX + otherWidth / 2 - textWidth / 2, y: 7.5 - countFont.capHeight / 2)
                CTLineDraw(textLine, context)
            }
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
