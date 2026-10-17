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
    var symbol: String { amberCount > 0 ? "mug.fill" : "mug" }
    var accessibility: String {
        if amberCount == 0 { return "Brew Version, no watched updates" }
        return "Brew Version, \(amberCount) watched update\(amberCount == 1 ? "" : "s") available"
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
enum PopoverActions {
    static func shouldAllowTransientClose(event: NSEvent.EventType?, mouseInButton: Bool) -> Bool {
        let click = event.map { [.leftMouseDown, .leftMouseUp, .rightMouseDown, .rightMouseUp].contains($0) } ?? false
        return !(click && mouseInButton)
    }
    static func toggle(isShown: Bool, show: () -> Void, close: () -> Void) {
        if isShown { close() } else { show() }
    }
}
@MainActor enum PopoverAppearance {
    static func apply(_ appearance: NSAppearance?, to popover: NSPopover) {
        // Popovers inherit the status button's appearance unless overridden;
        // changing only NSApplication.appearance need not update that content.
        popover.appearance = appearance
        popover.contentViewController?.view.appearance = appearance
        popover.contentViewController?.view.window?.appearance = appearance
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
    var options: [CheckInterval] { CheckInterval.presets.contains(current) ? CheckInterval.presets : CheckInterval.presets + [current] }
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
