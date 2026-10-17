import AppKit
import SwiftUI
import Observation
import BrewVersionCore

@MainActor final class StatusItemController: NSObject, NSPopoverDelegate {
    private let controller: WatchController
    private let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    private let popover = NSPopover()
    init(controller: WatchController, accessory: AnyView? = nil) {
        self.controller = controller
        super.init()
        popover.behavior = .transient; popover.delegate = self
        popover.contentViewController = NSHostingController(rootView: VStack(spacing: 0) { PopoverView(controller: controller); if let accessory { accessory } })
        item.button?.target = self; item.button?.action = #selector(toggle)
        updateImage()
    }
    private func updateImage() {
        withObservationTracking {
            let image = NSImage(systemSymbolName: controller.amberCount > 0 ? "mug.fill" : "mug", accessibilityDescription: "Brew Version")
            image?.isTemplate = true; item.button?.image = image
        } onChange: { [weak self] in Task { @MainActor in self?.updateImage() } }
    }
    @objc private func toggle() { if popover.isShown { popover.performClose(nil) } else { showPopover() } }
    func showPopover() {
        guard let button = item.button else { return }
        NSApp.activate(ignoringOtherApps: true)
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        popover.contentViewController?.view.window?.makeKey()
    }
    func popoverDidClose(_ notification: Notification) { controller.popoverClosed() }
}
