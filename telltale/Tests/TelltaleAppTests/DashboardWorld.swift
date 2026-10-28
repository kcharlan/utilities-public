import AppKit
import Foundation
import TelltaleCore
import TelltaleTestSupport
@testable import Telltale

/// Records activation-policy changes instead of applying them to the test process.
@MainActor final class ActivationRecorder: ActivationPolicyApplying {
    private(set) var policies: [NSApplication.ActivationPolicy] = []
    func setActivationPolicy(_ policy: NSApplication.ActivationPolicy) -> Bool {
        policies.append(policy)
        return true
    }
}

/// The dashboard's objects over a scratch `PanelWorld` database, a fake `launchctl` and a
/// synthetic app bundle carrying Telltale's real identifier (never /Applications).
@MainActor final class DashboardWorld {
    let directory: URL
    let paths: TelltalePaths
    let runner = FakeCommandRunner()
    let live: LiveStore
    let actions: UserActions
    let panel: PanelModel
    let collector: CollectorViewModel
    let settings: SettingsModel
    /// The login-item service behind Settings' Open at login (never `SMAppService`).
    let login: LoginServiceStub
    let model: DashboardModel
    let executable: URL
    let clock: WorldClock
    var revealed: [URL] = []

    static let running = CollectorHealthReport(
        installed: .green, loaded: .green, lastRun: .green, onSchedule: .green, problems: [], needsRepair: false, footer: "", notify: false)

    init(_ directory: URL, now: Date = PanelWorld.now, canManage: Bool = true, health: CollectorHealthReport? = DashboardWorld.running) throws {
        self.directory = directory
        let clock = WorldClock(now: now, health: health)
        self.clock = clock
        paths = PanelWorld.paths(directory)
        executable = try Self.makeApp(directory.appending(path: "Applications/Telltale.app", directoryHint: .isDirectory))
        let live = LiveStore(
            paths: paths, sources: PanelWorld.sources, calendar: Synth.newYork, now: { clock.now }, health: { clock.health }, pollInterval: .seconds(3_600),
            watchFiles: false)
        self.live = live
        // Check now and Rebuild kick the job as the app does, through the fake `launchctl`.
        let manager = LaunchAgentManager(paths: paths, uid: 4_242, runner: runner)
        actions = UserActions(paths: paths, calendar: Synth.newYork, now: { clock.now }, kickstart: { try manager.kickstart() }, changed: { live.reload() })
        panel = PanelModel(store: live, actions: actions, notifier: UserNotifier(service: NotificationServiceStub()), calendar: Synth.newYork)
        collector = CollectorViewModel(
            live: live, actions: actions, manager: manager, currentExecutable: executable,
            canManage: canManage, paths: paths, calendar: Synth.newYork, now: { clock.now }, reveal: { _ in })
        let login = LoginServiceStub()
        self.login = login
        settings = SettingsModel(live: live, collector: collector, sources: PanelWorld.sources, login: LoginItem(service: login))
        model = DashboardModel(
            live: live, panel: panel, collector: collector, settings: settings, sources: PanelWorld.sources, calendar: Synth.newYork, now: { clock.now })
        collector.reveal = { [unowned self] in revealed.append($0) }
    }

    func controller(activation: ActivationRecorder, presented: @escaping (NSWindow) -> Void, activations: @escaping () -> Void = {}) -> DashboardWindowController {
        DashboardWindowController(model: model, activation: activation, activate: activations, present: presented)
    }

    /// A minimal app bundle whose Info.plist names Telltale's executable and `identifier`.
    static func makeApp(_ app: URL, identifier: String = TelltaleRelease.bundleIdentifier) throws -> URL {
        let macOS = app.appending(path: "Contents/MacOS", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: macOS, withIntermediateDirectories: true)
        let info: [String: Any] = ["CFBundleExecutable": "Telltale", "CFBundleIdentifier": identifier, "CFBundlePackageType": "APPL"]
        try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0).write(to: app.appending(path: "Contents/Info.plist"))
        let binary = macOS.appending(path: "Telltale", directoryHint: .notDirectory)
        try Data("#!/bin/sh\nexit 0\n".utf8).write(to: binary)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: binary.path)
        return binary
    }
}

/// The world's injected time and collector health, changeable mid-test.
@MainActor final class WorldClock {
    var now: Date
    var health: CollectorHealthReport?
    init(now: Date, health: CollectorHealthReport?) {
        self.now = now
        self.health = health
    }
}
