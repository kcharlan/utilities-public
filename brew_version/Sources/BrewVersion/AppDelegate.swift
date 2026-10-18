import AppKit
import BrewVersionCore

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate {
    let controller: WatchController
    let notifier: UserNotifier
    private var status: (any PopoverPresenting)?
    private var events: SystemEvents?
    override convenience init() {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let prefixes = HomebrewPrefix.detectAll(candidates: [URL(fileURLWithPath: "/opt/homebrew"), URL(fileURLWithPath: "/usr/local")])
        let installed = prefixes.isEmpty ? nil : InstalledReader(prefixes: prefixes, applicationDirectories: [URL(fileURLWithPath: "/Applications"), home.appendingPathComponent("Applications")], tappedTaps: { TapIndex.scan(prefixes: prefixes).taps })
        let notifier = UserNotifier()
        let controller = WatchController(transport: URLSessionTransport.standard(), installed: installed,
            store: WatchStore(fileURL: home.appendingPathComponent("Library/Application Support/Brew Version/state.json")),
            notifier: notifier,
            catalogClient: CatalogClient(transport: CatalogClient.makeTransport(), cacheDirectory: home.appendingPathComponent("Library/Caches/Brew Version")), networkAvailable: false,
            taps: { TapIndex.scan(prefixes: prefixes) })
        self.init(controller: controller, notifier: notifier)
    }
    init(controller: WatchController, notifier: UserNotifier, status: (any PopoverPresenting)? = nil) {
        self.controller = controller; self.notifier = notifier; self.status = status
        super.init()
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        let status = StatusItemController(controller: controller, notifier: notifier)
        self.status = status
        notifier.showPopover = { [weak status] in status?.showPopover() }
        events = SystemEvents(network: { [weak self] in await self?.controller.setNetworkAvailable($0) }) { [weak self] in
            await self?.controller.scheduledTick()
        }
        events?.start()
        Task { await controller.hydrateCatalog() }
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        status?.showPopover(); return true
    }
    func applicationWillTerminate(_ notification: Notification) { events?.stop() }
}
