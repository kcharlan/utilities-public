import SwiftUI
import AppKit
@MainActor @Observable final class SyntheticController { var showOtherUpdates = true }
@main struct Prototype: App {
    @NSApplicationDelegateAdaptor(Delegate.self) var delegate
    var body: some Scene { Settings { Text("Synthetic Settings prototype").padding(40) } }
}
@MainActor final class Delegate: NSObject, NSApplicationDelegate {
    var item: NSStatusItem!
    let popover = NSPopover()
    let controller = SyntheticController()
    func applicationDidFinishLaunching(_ notification: Notification) {
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.button?.image = NSImage(systemSymbolName: "mug", accessibilityDescription: "Brew Version Settings prototype")
        item.button?.target = self; item.button?.action = #selector(toggle)
        popover.behavior = .transient
        popover.contentViewController = NSHostingController(rootView: VStack {
            Text("Synthetic Settings prototype")
            SettingsLink { Text("Settings…") }
        }.padding(24))
    }
    @objc func toggle() {
        if popover.isShown { popover.performClose(nil) }
        else { popover.show(relativeTo: item.button!.bounds, of: item.button!, preferredEdge: .minY) }
    }
}
