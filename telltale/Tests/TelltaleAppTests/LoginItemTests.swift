// Port: anker_charge_monitor/Tests/PrimeMonitorAppTests/LoginItemTests.swift, LoginItemTests, 4f965e8
// (with LoginServiceStub from that commit's SettingsWindowTests.swift).
// Adaptation: the stub counts registrations; Telltale adds spec section 3's Open at login under
// ruling R32 (the default applied once, by the installed copy; launch never overrides a removal)
// and the Settings switch, which stores the choice only in the collector's database (ruling R27).
import Foundation
import Testing
import TelltaleCore
import TelltaleTestSupport
@testable import Telltale

@MainActor final class LoginServiceStub: LoginService {
    var status: LoginStatus = .notRegistered
    var fail = false
    var settingsOpened = false
    private(set) var registrations = 0
    private(set) var unregistrations = 0
    func register() throws {
        if fail { throw CocoaError(.fileWriteUnknown) }
        registrations += 1
        status = .requiresApproval
    }
    func unregister() throws {
        unregistrations += 1
        status = .notRegistered
    }
    func openSettings() { settingsOpened = true }
}

@MainActor @Suite(.serialized) struct LoginItemTests {
    @Test func requiresApproval() {
        let service = LoginServiceStub()
        let subject = LoginItem(service: service)
        #expect(!subject.enabled)
        subject.setEnabled(true)
        #expect(subject.enabled && subject.requiresApproval)
        subject.openSettings(); #expect(service.settingsOpened)
        service.status = .enabled; subject.refresh()
        #expect(subject.enabled && !subject.requiresApproval)
        service.fail = true; subject.setEnabled(true); #expect(subject.error != nil)
        subject.setEnabled(false); #expect(!subject.enabled && subject.error == nil)
        service.status = .notFound; subject.refresh(); #expect(subject.description == "App service unavailable")
    }

    /// Ruling R32: spec section 3's default (on) is applied once, at the installed copy's first
    /// launch, and remembered outside the database, which doesn't exist yet (R27). A copy outside
    /// Applications neither registers nor uses up that first launch (R24's reasoning).
    @Test func firstLaunchRegistersOnce() async throws {
        try await withDelegate { h in
            let build = h.delegate(current: h.buildExecutable)
            h.launch(build)
            h.terminate(build)
            #expect(h.login.registrations == 0 && !h.launchRecord.openAtLoginDefaultApplied)

            let first = h.delegate()
            h.launch(first)
            #expect(h.login.registrations == 1 && first.login.requiresApproval)
            h.terminate(first)
            #expect(h.preferences.values == [PreferencesLaunchRecord.defaultAppliedKey: true])
            #expect(PreferencesLaunchRecord.defaultAppliedKey.hasPrefix("local.utilities.telltale."))

            let again = h.delegate()
            h.launch(again)
            h.terminate(again)
            #expect(h.login.registrations == 1)

            // Removed in System Settings before the first run: nothing registers, and there is no
            // database to store the mirrored setting in, so none is created.
            h.login.status = .notRegistered
            let removed = h.delegate()
            h.launch(removed)
            h.terminate(removed)
            #expect(h.login.registrations == 1 && !removed.login.enabled && !h.databaseExists)
        }
    }

    /// A first launch over a database whose setting is already off registers nothing.
    @Test func firstLaunchKeepsStoredOff() async throws {
        try await withDelegate { h in
            try PanelWorld.seed(h.paths).set(.openAtLogin, false)
            let first = h.delegate()
            h.launch(first)
            h.terminate(first)
            #expect(h.login.registrations == 0 && h.launchRecord.openAtLoginDefaultApplied)
            #expect(try Store.open(h.paths.database, mode: .readOnly).value(.openAtLogin) == false)
        }
    }

    /// Ruling R32: launch never overrides a removal in System Settings > Login Items; the stored
    /// setting mirrors the system instead, in both directions.
    @Test func launchNeverOverridesRemoval() async throws {
        try await withDelegate { h in
            try PanelWorld.seed(h.paths).set(.openAtLogin, true)
            h.launchRecord.openAtLoginDefaultApplied = true
            h.login.status = .enabled
            let registered = h.delegate()
            h.launch(registered)
            h.terminate(registered)
            #expect(h.login.registrations == 0 && h.login.unregistrations == 0)

            // The user removes Telltale in System Settings, then relaunches it.
            h.login.status = .notRegistered
            let removed = h.delegate()
            h.launch(removed)
            #expect(h.login.registrations == 0 && !removed.login.enabled)
            #expect(try Store.open(h.paths.database, mode: .readOnly).value(.openAtLogin) == false)
            h.terminate(removed)

            // Allowed again in System Settings: the stored setting follows, and still nothing registers.
            h.login.status = .enabled
            let allowed = h.delegate()
            h.launch(allowed)
            h.terminate(allowed)
            #expect(h.login.registrations == 0)
            #expect(try Store.open(h.paths.database, mode: .readOnly).value(.openAtLogin) == true)
            #expect(h.failures.isEmpty)
        }
    }

    /// Only the user's switch in Settings registers.
    @Test func togglingOnRegisters() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try DashboardWorld(directory)
            try PanelWorld.seed(world.paths).set(.openAtLogin, false)
            await world.live.refresh()
            world.model.select(.settings)
            #expect(!world.settings.login.enabled)
            world.settings.setOpenAtLogin(true)
            #expect(world.login.registrations == 1 && world.settings.login.enabled)
            #expect(try Store.open(world.paths.database, mode: .readOnly).value(.openAtLogin) == true)
            #expect(world.settings.errors[.general] == nil)
        }
    }

    /// The switch stores the choice first and changes the system only once that worked; a failed
    /// system change puts the stored setting back to the system's state, so the two never disagree.
    @Test func openAtLoginWritesStayInStep() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try DashboardWorld(directory)
            try PanelWorld.seed(world.paths).set(.openAtLogin, false)
            await world.live.refresh()
            world.model.select(.settings)

            world.login.fail = true
            world.settings.setOpenAtLogin(true)
            #expect(world.settings.login.error != nil && !world.settings.login.enabled)
            #expect(try Store.open(world.paths.database, mode: .readOnly).value(.openAtLogin) == false)

            // The store write fails (the database went away): the system isn't changed.
            world.login.fail = false
            for suffix in ["", "-wal", "-shm"] {
                try? FileManager.default.removeItem(atPath: world.paths.database.path + suffix)
            }
            world.settings.setOpenAtLogin(true)
            #expect(world.settings.errors[.general] != nil)
            #expect(world.login.registrations == 0 && !world.settings.login.enabled)
            #expect(!FileManager.default.fileExists(atPath: world.paths.database.path))
        }
    }

    /// Settings' Open at login switch unregisters and stores the choice, so the next launch keeps it
    /// off. A failed change stores nothing; before the first run, or outside Applications, nothing
    /// changes and Settings says why.
    @Test func turningOffUnregisters() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try DashboardWorld(directory)
            try PanelWorld.seed(world.paths)
            world.login.status = .enabled
            await world.live.refresh()
            world.model.select(.settings)
            #expect(world.settings.login.enabled)

            world.settings.setOpenAtLogin(false)
            #expect(world.login.unregistrations == 1 && !world.settings.login.enabled)
            #expect(try Store.open(world.paths.database, mode: .readOnly).value(.openAtLogin) == false)

            world.login.fail = true
            world.settings.setOpenAtLogin(true)
            #expect(world.settings.login.error != nil)
            #expect(try Store.open(world.paths.database, mode: .readOnly).value(.openAtLogin) == false)

            // Before the collector's first run there is nowhere to store the choice (R27).
            let early = try DashboardWorld(directory.appending(path: "early", directoryHint: .isDirectory))
            early.login.status = .enabled
            await early.live.refresh()
            early.model.select(.settings)
            #expect(early.settings.firstRunNote == Copy.settingsAfterFirstRun)
            early.settings.setOpenAtLogin(false)
            #expect(early.login.unregistrations == 0 && early.settings.login.enabled)
            #expect(!FileManager.default.fileExists(atPath: early.paths.database.path))

            // A copy outside Applications doesn't register or unregister itself.
            let other = try DashboardWorld(directory.appending(path: "other", directoryHint: .isDirectory), canManage: false)
            try PanelWorld.seed(other.paths)
            other.login.status = .enabled
            await other.live.refresh()
            other.model.select(.settings)
            #expect(other.settings.installedCopyNote == Copy.settingsInstalledCopyOnly)
            other.settings.setOpenAtLogin(false)
            #expect(other.login.unregistrations == 0)
        }
    }
}
