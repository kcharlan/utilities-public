// Port: brew_version/Sources/BrewVersion/AppDelegate.swift, AppDelegate, eb960f3.
// Adaptation: Telltale's composition (spec sections 9.1 and 9.3): the instance gate, the live
// store, the collector monitor and wake events, wired to the status item. Every path, runner and
// service is injected; the composition root (TelltaleMain) supplies the live ones.
import AppKit
import TelltaleCore

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate {
    private let paths: TelltalePaths
    private let currentExecutable: URL
    private let installedAppURL: URL
    private let sources: [SourceSummary]
    private let notificationService: any NotificationService
    private let manager: LaunchAgentManager
    private let calendar: Calendar
    private let eventSources: [any SystemEventSource]?
    private let watchFiles: Bool
    private let makeStatus: @MainActor (PanelModel, any DashboardOpening) -> any PopoverPresenting
    private let quit: @MainActor () -> Void
    private let reportFailure: @MainActor (String) -> Void

    private(set) var liveStore: LiveStore?
    let notifier: UserNotifier
    private(set) var monitor: CollectorMonitor?
    /// The dashboard window (spec section 9.2), which Open dashboard and Settings show.
    private(set) var dashboard: DashboardWindowController?
    /// Whether this copy posts health notifications and writes their notice (R24: installed only).
    private(set) var monitorStarted = false
    private var status: (any PopoverPresenting)?
    private var events: SystemEvents?
    private var lease: AppInstanceLease?

    /// - `installedAppURL`: the bundle whose main executable may manage the collector
    ///   (`/Applications/Telltale.app` in production, a synthetic bundle in tests).
    /// - `eventSources`: nil uses the native wake notification.
    /// - `makeStatus`: builds the status item around the panel's model and the dashboard.
    /// - `reportFailure`: launch problems the panel can't show (the default writes to standard error;
    ///   collector problems reach the panel footer through collector health).
    init(
        paths: TelltalePaths, currentExecutable: URL, installedAppURL: URL, runner: any CommandRunner, sources: [SourceSummary],
        notificationService: any NotificationService, uid: uid_t = getuid(), calendar: Calendar = .current,
        eventSources: [any SystemEventSource]? = nil, watchFiles: Bool = true,
        makeStatus: @escaping @MainActor (PanelModel, any DashboardOpening) -> any PopoverPresenting = { model, dashboard in
            StatusItemController(model: model, dashboard: dashboard)
        },
        quit: @escaping @MainActor () -> Void = { NSApp.terminate(nil) },
        reportFailure: @escaping @MainActor (String) -> Void = { FileHandle.standardError.write(Data("\($0)\n".utf8)) }
    ) {
        self.paths = paths
        self.currentExecutable = currentExecutable
        self.installedAppURL = installedAppURL
        self.sources = sources
        self.notificationService = notificationService
        manager = LaunchAgentManager(paths: paths, uid: uid, runner: runner)
        self.calendar = calendar
        self.eventSources = eventSources
        self.watchFiles = watchFiles
        self.makeStatus = makeStatus
        self.quit = quit
        self.reportFailure = reportFailure
        notifier = UserNotifier(service: notificationService)
        super.init()
        // Before launch finishes, so a click that launched the app reaches the notifier.
        (notificationService as? NativeNotificationService)?.center.delegate = notifier
    }

    /// The installed bundle's main executable (its Info.plist's `CFBundleExecutable`), compared
    /// with this process's executable once both are standardized and symlink-resolved.
    var isInstalledCopy: Bool {
        let contents = installedAppURL.appending(path: "Contents", directoryHint: .isDirectory)
        guard let data = try? Data(contentsOf: contents.appending(path: "Info.plist", directoryHint: .notDirectory)),
              let info = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
              let name = info["CFBundleExecutable"] as? String, !name.isEmpty
        else { return false }
        let main = contents.appending(path: "MacOS", directoryHint: .isDirectory).appending(path: name, directoryHint: .notDirectory)
        return LaunchAgentManager.sameExecutable(currentExecutable, main)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            lease = try AppInstanceGate.acquire(at: paths.appLock)
        } catch AppInstanceGateError.alreadyRunning {
            quit()
            return
        } catch {
            reportFailure("\(TelltaleRelease.displayName) can't open its support folder: \(error.localizedDescription)")
            quit()
            return
        }
        let installed = isInstalledCopy
        if installed { restoreCollector() }

        let monitor = CollectorMonitor(paths: paths, manager: manager, currentExecutable: currentExecutable, service: notificationService, calendar: calendar)
        let live = LiveStore(paths: paths, sources: sources, calendar: calendar, health: { [weak monitor] in await monitor?.evaluate() }, watchFiles: watchFiles)
        let manager = manager
        let actions = UserActions(paths: paths, calendar: calendar, kickstart: { try manager.kickstart() }, changed: { [weak live] in live?.reload() })
        let panel = PanelModel(store: live, actions: actions, notifier: notifier, calendar: calendar)
        // Turn on, Turn off and Repair change launchd state, so only the installed copy may (R24).
        let collector = CollectorViewModel(
            live: live, actions: actions, manager: manager, currentExecutable: currentExecutable, canManage: installed, paths: paths, calendar: calendar)
        let dashboard = DashboardWindowController(model: DashboardModel(live: live, panel: panel, collector: collector, sources: sources, calendar: calendar))
        let status = makeStatus(panel, dashboard)
        notifier.showPopover = { [weak status] in status?.showPopover() }
        let events = eventSources.map { SystemEvents(sources: $0) { [weak live] in await live?.refresh() } }
            ?? SystemEvents { [weak live] in await live?.refresh() }

        self.monitor = monitor
        self.dashboard = dashboard
        liveStore = live
        self.status = status
        self.events = events
        events.start()
        live.start()
        if installed {
            monitor.start()
            monitorStarted = true
            Task { await notifier.requestAuthorization() }
        }
    }

    /// At launch, an installed copy turns the collector on when it should be on and its plist is
    /// missing (spec section 9.3). Settings are read read-only: before the first run they are the
    /// defaults, and the app never creates the database.
    private func restoreCollector() {
        var enabled = SettingKey.collectorEnabled.defaultValue
        var interval = SettingKey.intervalMinutes.defaultValue
        do {
            let store = try Store.open(paths.database, mode: .readOnly)
            enabled = try store.value(.collectorEnabled)
            interval = Settings.usableInterval(try store.value(.intervalMinutes))
        } catch StoreError.notInitialized {
        } catch {
            reportFailure(Copy.databaseUnavailable(reason: error.localizedDescription))
            return
        }
        guard enabled, !FileManager.default.fileExists(atPath: manager.plistURL.path) else { return }
        do {
            try manager.turnOn(executable: currentExecutable, intervalMinutes: interval)
        } catch {
            reportFailure(error.localizedDescription)
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        status?.showPopover(); return true
    }

    func applicationWillTerminate(_ notification: Notification) {
        events?.stop()
        liveStore?.stop()
        monitor?.stop()
        lease?.release()
        lease = nil
    }
}
