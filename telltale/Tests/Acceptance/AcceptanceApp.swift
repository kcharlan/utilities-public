// Port: brew_version/Tests/Acceptance/AcceptanceApp.swift, AcceptanceApp, AcceptanceDelegate and
// SyntheticNotificationService, fbd3e03.
// Adaptation: the maintained status item, panel and notifier read a seeded Telltale database (an
// alerting model, a shift prompt, the collector off) under the bundle's explicit private home.
// launchctl goes through SyntheticCommandRunner, so CollectorMonitor's read-only health never
// reaches launchd, and Check now's kickstart is a double that records a synthetic run. The
// Homebrew transport controls become Telltale's: an added red alert and a posting failure.
import AppKit
import SwiftUI
import TelltaleCore
import UserNotifications

// Compiled only by build.sh into a distinct bundle (com.example.telltale.acceptance, which
// LaunchAgentManager refuses). No production simulation path.
@main struct AcceptanceApp {
    @MainActor static func main() {
        let app = NSApplication.shared
        ApplicationMenu.install()
        let delegate = AcceptanceDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}

/// Everything the acceptance app shows, built over an explicit synthetic home; the service tests
/// build it the same way without the native notification center.
@MainActor final class AcceptanceHarness {
    let paths: TelltalePaths
    let runner = SyntheticCommandRunner()
    let notificationService: SyntheticNotificationService
    let notifier: UserNotifier
    let monitor: CollectorMonitor
    let live: LiveStore
    let actions: UserActions

    /// Seeds the acceptance scene the first time; a relaunch keeps what the last session changed.
    init(home: URL, notificationService: SyntheticNotificationService, calendar: Calendar = .current, now: @escaping @MainActor () -> Date = Date.init) throws {
        let paths = SyntheticEnvironment.paths(home: home)
        if !FileManager.default.fileExists(atPath: paths.database.path) {
            try SyntheticEnvironment.seed(.acceptance, home: home, now: now(), calendar: calendar)
        }
        self.paths = paths
        self.notificationService = notificationService
        notifier = UserNotifier(service: notificationService)
        let monitor = CollectorMonitor(
            paths: paths, manager: LaunchAgentManager(paths: paths, uid: getuid(), runner: runner),
            currentExecutable: Bundle.main.executableURL ?? home.appending(path: "Acceptance", directoryHint: .notDirectory),
            service: notificationService, calendar: calendar, now: now)
        self.monitor = monitor
        let live = LiveStore(
            paths: paths, sources: SyntheticEnvironment.sources, calendar: calendar, now: now, health: { await monitor.evaluate() })
        self.live = live
        actions = UserActions(
            paths: paths, calendar: calendar, now: now, kickstart: { try SyntheticEnvironment.recordCheck(paths: paths, at: Date()) },
            changed: { live.reload() })
    }

    /// "Add red alert": a red failed-turns alert beside the seeded amber ones.
    func addRedAlert(at now: Date = Date()) throws {
        let store = try Store.open(paths.database, mode: .readWrite)
        try SyntheticEnvironment.alert(
            store, rule: .failedTurns, scope: "*", direction: nil, onset: now.addingTimeInterval(-120), at: now,
            body: Copy.failedTurns(count: 3, reasons: ["synthetic failure"]), severity: .red)
        live.reload()
    }
}

@MainActor final class AcceptanceDelegate: NSObject, NSApplicationDelegate {
    let notificationService = SyntheticNotificationService(native: NativeNotificationService())
    let harness: AcceptanceHarness
    private var status: StatusItemController?
    override init() {
        let home = SyntheticEnvironment.requireHome(Bundle.main.object(forInfoDictionaryKey: "SyntheticAcceptanceHome"))
        do {
            harness = try AcceptanceHarness(home: home, notificationService: notificationService)
        } catch {
            fatalError("Synthetic acceptance home could not be seeded: \(error.localizedDescription)")
        }
        super.init()
        notificationService.native?.center.delegate = harness.notifier
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        let harness = harness
        let controls = AnyView(VStack {
            Text("Synthetic acceptance only").font(.caption)
            HStack {
                Button("Light") { self.status?.setAppearance(NSAppearance(named: .aqua)) }
                Button("Dark") { self.status?.setAppearance(NSAppearance(named: .darkAqua)) }
                Button("Add red alert") { try? harness.addRedAlert() }
            }
            HStack {
                Button("Test notification") { Task { await harness.notifier.sendTestNotification() } }
                Button("Test posting failure") {
                    self.notificationService.failNext = true
                    Task { await harness.notifier.sendTestNotification() }
                }
            }
        }.padding(10))
        let status = StatusItemController(store: harness.live, actions: harness.actions, notifier: harness.notifier, accessory: controls)
        self.status = status
        harness.notifier.showPopover = { [weak status] in status?.showPopover() }
        harness.live.start()
        status.showPopover()
        Task { await harness.notifier.requestAuthorization() }
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        status?.showPopover(); return true
    }
    func applicationWillTerminate(_ notification: Notification) {
        harness.live.stop()
    }
}

// A harness-only fault at the maintained notifier's system-service boundary. Without a native
// service (the service tests) it records requests instead of posting them.
@MainActor final class SyntheticNotificationService: NotificationService {
    let native: NativeNotificationService?
    var failNext = false
    private(set) var posted: [UNNotificationRequest] = []
    init(native: NativeNotificationService?) { self.native = native }
    func authorizationStatus() async -> UNAuthorizationStatus { await native?.authorizationStatus() ?? .authorized }
    func requestAuthorization() async throws -> Bool { try await native?.requestAuthorization() ?? true }
    func post(_ request: UNNotificationRequest) async throws {
        if failNext { failNext = false; throw SyntheticPostingError() }
        posted.append(request)
        try await native?.post(request)
    }
    func delivered() async -> [UNNotification] { await native?.delivered() ?? [] }
}
private struct SyntheticPostingError: LocalizedError {
    var errorDescription: String? { "Synthetic posting failure for acceptance" }
}
