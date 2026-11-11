import AppKit
import BrewVersionCore

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate {
    let controller: WatchController
    let notifier: UserNotifier
    private var status: (any PopoverPresenting)?
    private var events: SystemEvents?
    private let log: any EventLogging
    private let brewPath: String
    override convenience init() {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let prefixes = HomebrewPrefix.detectAll(candidates: [URL(fileURLWithPath: "/opt/homebrew"), URL(fileURLWithPath: "/usr/local")])
        let installed = prefixes.isEmpty ? nil : InstalledReader(prefixes: prefixes, applicationDirectories: [URL(fileURLWithPath: "/Applications"), home.appendingPathComponent("Applications")], tappedTaps: { TapIndex.scan(prefixes: prefixes).taps })
        let log = EventLog(directory: home.appendingPathComponent("Library/Logs/Brew Version"))
        let gate = BrewGate.live(prefixes: prefixes, home: home, log: log)
        let notifier = UserNotifier()
        notifier.log = log
        let controller = WatchController(transport: LoggingTransport(URLSessionTransport.standard(), log: log), installed: installed,
            store: WatchStore(fileURL: home.appendingPathComponent("Library/Application Support/Brew Version/state.json")),
            notifier: notifier,
            catalogClient: CatalogClient(transport: LoggingTransport(CatalogClient.makeTransport(), log: log), cacheDirectory: home.appendingPathComponent("Library/Caches/Brew Version")), networkAvailable: false,
            taps: { TapIndex.scan(prefixes: prefixes) }, brewGate: gate, log: log)
        self.init(controller: controller, notifier: notifier, log: log, brewPath: gate?.executablePath ?? "none")
    }
    init(controller: WatchController, notifier: UserNotifier, status: (any PopoverPresenting)? = nil, log: any EventLogging = NoEventLog(), brewPath: String = "none") {
        self.controller = controller; self.notifier = notifier; self.status = status; self.log = log; self.brewPath = brewPath
        super.init()
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        log.record("app.launch", ["version": .string(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "unknown"), "build": .string(Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "unknown"), "os": .string(ProcessInfo.processInfo.operatingSystemVersionString), "brew": .string(brewPath), "confirmWithBrew": .bool(controller.state.confirmWithBrew), "watched": .int(controller.state.watched.count)])
        let status = StatusItemController(controller: controller, notifier: notifier)
        self.status = status
        notifier.showPopover = { [weak status] in status?.showPopover() }
        notifier.acknowledgeAlert = { [weak controller] in controller?.acknowledgeAlerts() }
        events = SystemEvents(network: { [weak self] in await self?.controller.setNetworkAvailable($0) }) { [weak self] in
            await self?.controller.scheduledTick()
        }
        events?.start()
        Task { await notifier.removeLegacyAlerts(); controller.reconcileAlert(); await controller.hydrateCatalog() }
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        status?.showPopover(); return true
    }
    func flushLog() async { await (log as? EventLog)?.flush() }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard log is EventLog else { return .terminateNow }
        events?.stop()
        Task { await flushLog(); sender.reply(toApplicationShouldTerminate: true) }
        return .terminateLater
    }
    func applicationWillTerminate(_ notification: Notification) { events?.stop() }
}
