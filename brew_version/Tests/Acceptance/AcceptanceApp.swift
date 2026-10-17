import AppKit
import SwiftUI
import BrewVersionCore

// Compiled only by build.sh into a distinct bundle. No production simulation path.
@main struct AcceptanceApp: App {
    @NSApplicationDelegateAdaptor(AcceptanceDelegate.self) var delegate
    var body: some Scene { Settings { SettingsView(controller: delegate.controller) } }
}
@MainActor final class AcceptanceDelegate: NSObject, NSApplicationDelegate {
    let service = SyntheticTransport()
    let notifier = UserNotifier()
    let controller: WatchController
    private var status: StatusItemController?
    override init() {
        // The builder records an explicit fresh private directory in this harness plist.
        guard let path = Bundle.main.object(forInfoDictionaryKey: "SyntheticAcceptanceHome") as? String,
              path.hasPrefix("/"), FileManager.default.fileExists(atPath: path) else { fatalError("Explicit acceptance home missing") }
        let home = URL(fileURLWithPath: path)
        let prefix = home.appendingPathComponent("synthetic-prefix")
        let keg = prefix.appendingPathComponent("Cellar/synthetic-installed/1.0-synthetic")
        do {
            try FileManager.default.createDirectory(at: keg, withIntermediateDirectories: true)
            try Data("{\"source\":{\"tap\":\"homebrew/core\"}}".utf8).write(to: keg.appendingPathComponent("INSTALL_RECEIPT.json"))
        } catch { fatalError("Cannot create synthetic receipt: \(error)") }
        controller = WatchController(transport: service,
            installed: InstalledReader(prefixes: HomebrewPrefix.detectAll(candidates: [prefix]), applicationDirectories: []),
            store: WatchStore(fileURL: home.appendingPathComponent("state/state.json")), notifier: notifier,
            catalogClient: CatalogClient(transport: service, cacheDirectory: home.appendingPathComponent("catalog")))
        super.init()
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        let controls = AnyView(VStack {
            Text("Synthetic acceptance only").font(.caption)
            HStack {
                Button("Advance release and check") { Task { await self.service.advance(); await self.controller.checkNow() } }
                Button("Light") { NSApp.appearance = NSAppearance(named: .aqua) }
                Button("Dark") { NSApp.appearance = NSAppearance(named: .darkAqua) }
            }
        }.padding(10))
        let status = StatusItemController(controller: controller, accessory: controls)
        self.status = status
        notifier.showPopover = { [weak status] in status?.showPopover() }
        Task { await controller.hydrateCatalog(); await controller.scheduledTick() }
    }
}
