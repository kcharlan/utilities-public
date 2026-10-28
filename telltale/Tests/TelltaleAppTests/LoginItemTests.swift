// Port: anker_charge_monitor/Tests/PrimeMonitorAppTests/LoginItemTests.swift, LoginItemTests, 4f965e8
// (with LoginServiceStub from that commit's SettingsWindowTests.swift).
// Adaptation: the stub counts registrations; Telltale adds spec section 3's launch registration
// (Open at login, on by default, applied only by the installed copy) and turning it off in
// Settings, which stores the choice only in the collector's database (ruling R27).
import Foundation
import ServiceManagement
import Testing
import TelltaleCore
import TelltaleTestSupport
@testable import Telltale

@MainActor final class LoginServiceStub: LoginService {
    var status: SMAppService.Status = .notRegistered
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

    /// Spec section 3: Open at login is on by default, so the installed copy registers at launch
    /// while the setting is on and nothing is registered. A registration that exists (enabled, or
    /// waiting for approval in System Settings) is left alone, and a copy outside Applications
    /// never registers itself (ruling R24's reasoning).
    @Test func launchRegistersWhenOpenAtLoginOn() async throws {
        try await withDelegate { h in
            // Before the first run the setting is its default, on.
            let first = h.delegate()
            h.launch(first)
            #expect(h.login.registrations == 1 && first.login.enabled && first.login.requiresApproval)
            h.terminate(first)

            let again = h.delegate()
            h.launch(again)
            h.terminate(again)
            #expect(h.login.registrations == 1)

            // Off by choice: nothing is registered.
            h.login.status = .notRegistered
            try PanelWorld.seed(h.paths).set(.openAtLogin, false)
            let off = h.delegate()
            h.launch(off)
            h.terminate(off)
            #expect(h.login.registrations == 1)

            // Back on: a copy outside Applications still registers nothing; the installed one does.
            try Store.open(h.paths.database, mode: .readWrite).set(.openAtLogin, true)
            let build = h.delegate(current: h.buildExecutable)
            h.launch(build)
            h.terminate(build)
            #expect(h.login.registrations == 1)
            let installed = h.delegate()
            h.launch(installed)
            h.terminate(installed)
            #expect(h.login.registrations == 2)
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
