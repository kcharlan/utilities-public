import AppKit
import SwiftUI
import Observation
import BrewVersionCore

@MainActor @Observable final class PopoverFocus { var generation = UUID() }
private struct StatusContent: View {
    let controller: WatchController
    let notifier: UserNotifier
    let settings: SettingsWindowController
    let focus: PopoverFocus
    let accessory: AnyView?
    var body: some View {
        VStack(spacing: 0) {
            PopoverView(controller: controller, notifier: notifier, openSettings: settings.show, focusGeneration: focus.generation)
            if let accessory { accessory }
        }
    }
}
@MainActor protocol PopoverPresenting: AnyObject { func showPopover() }
@MainActor final class StatusItemController: NSObject, NSPopoverDelegate, PopoverPresenting {
    private let controller: WatchController
    private let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    private let popover = NSPopover()
    private let focus = PopoverFocus()
    private let settings: SettingsWindowController
    private var statusObservation: StatusObservation?
    init(controller: WatchController, notifier: UserNotifier, accessory: AnyView? = nil) {
        self.controller = controller
        settings = SettingsWindowController(controller: controller, notifier: notifier)
        super.init()
        popover.behavior = .transient; popover.delegate = self
        popover.contentViewController = NSHostingController(rootView: StatusContent(controller: controller, notifier: notifier, settings: settings, focus: focus, accessory: accessory))
        item.button?.target = self; item.button?.action = #selector(toggle)
        statusObservation = StatusObservation(controller: controller) { [weak self] presentation in
            guard let self else { return }
            let image = NSImage(systemSymbolName: presentation.symbol, accessibilityDescription: presentation.accessibility)
            image?.isTemplate = true; self.item.button?.image = image
            self.item.button?.setAccessibilityLabel(presentation.accessibility)
            self.item.button?.setAccessibilityHelp(presentation.accessibility)
            self.item.button?.toolTip = presentation.accessibility
        }
    }
    @objc private func toggle() {
        PopoverActions.toggle(isShown: popover.isShown, show: showPopover, close: { popover.close() })
    }
    func showPopover() {
        guard let button = item.button else { return }
        NSApp.activate(ignoringOtherApps: true)
        focus.generation = UUID()
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        popover.contentViewController?.view.window?.makeKey()
    }
    func setAppearance(_ appearance: NSAppearance?) {
        NSApp.appearance = appearance
        PopoverAppearance.apply(appearance, to: popover)
        settings.setAppearance(appearance)
    }
    func popoverShouldClose(_ popover: NSPopover) -> Bool {
        // A transient popover can close on mouse-down before the status button's
        // mouse-up action. Let that action own toggling so it cannot reopen it.
        let overButton: Bool
        if let button = item.button, let window = button.window {
            overButton = button.bounds.contains(button.convert(window.convertPoint(fromScreen: NSEvent.mouseLocation), from: nil))
        } else { overButton = false }
        return PopoverActions.shouldAllowTransientClose(event: NSApp.currentEvent?.type, mouseInButton: overButton)
    }
    func popoverDidClose(_ notification: Notification) { controller.popoverClosed() }
}
