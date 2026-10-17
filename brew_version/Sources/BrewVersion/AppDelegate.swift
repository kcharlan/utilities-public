import AppKit
import BrewVersionCore

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate {
    let controller: WatchController
    let notifier: UserNotifier
    private var status: StatusItemController?
    private var events: SystemEvents?
    override init() {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let prefixes = HomebrewPrefix.detectAll(candidates: [URL(fileURLWithPath: "/opt/homebrew"), URL(fileURLWithPath: "/usr/local")])
        let installed = prefixes.isEmpty ? nil : InstalledReader(prefixes: prefixes, applicationDirectories: [URL(fileURLWithPath: "/Applications"), home.appendingPathComponent("Applications")])
        notifier = UserNotifier()
        controller = WatchController(transport: URLSessionTransport.standard(), installed: installed,
            store: WatchStore(fileURL: home.appendingPathComponent("Library/Application Support/Brew Version/state.json")),
            notifier: notifier,
            catalogClient: CatalogClient(transport: CatalogClient.makeTransport(), cacheDirectory: home.appendingPathComponent("Library/Caches/Brew Version")))
        super.init()
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        let status = StatusItemController(controller: controller)
        self.status = status
        notifier.showPopover = { [weak status] in status?.showPopover() }
        events = SystemEvents { [weak self] in
            guard let self else { return }
            Task { await self.controller.scheduledTick() }
        }
        events?.start()
        Task { await controller.hydrateCatalog(); await controller.scheduledTick() }
    }
    func applicationWillTerminate(_ notification: Notification) { events?.stop() }
}
