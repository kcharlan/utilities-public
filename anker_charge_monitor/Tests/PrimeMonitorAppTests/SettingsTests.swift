import AppKit
import Testing
import PrimeMonitorCore
@testable import PrimeMonitor

private struct SettingsProvider: CredentialProvider {
    func retrieve() async throws -> AnkerCredentials { appCredentials }
}
@Suite @MainActor struct SettingsTests {
    @Test func signInStoresOnlyNonsecretProviderSettings() async throws {
        let directory = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = StateStore(fileURL: directory.appending(path: "state.json", directoryHint: .notDirectory))
        let backend = AppBackend(), cache = MemorySessionStore(), clock = ManualScheduler()
        let monitor = MonitorController(backend: backend, secrets: cache, state: store, events: SystemEvents(sources: []), now: { clock.date }, scheduler: clock, makeProvider: { _ in SettingsProvider() })
        monitor.start(); await settle()
        let form = CredentialSettings(monitor: monitor)
        form.edit(item: "Synthetic Login", vault: "Synthetic Vault", country: "ca")
        #expect(monitor.appState.credentials == form.configuration.selection)
        #expect(try await cache.load()?.credentials == appCredentials)
        form.edit(item: "Replacement", vault: "", country: "US")
        #expect(monitor.snapshot == nil)
        await form.connect()
        #expect(await backend.log.contains("login"))
        let saved = try String(contentsOf: store.fileURL, encoding: .utf8)
        #expect(!saved.contains(appCredentials.email) && !saved.contains(appCredentials.password) && !saved.contains(appSession.authToken))
        #expect(store.load().state.credentials == OnePasswordConfiguration(item: "Replacement", vault: nil, country: "US").selection)
        #expect(try await cache.load()?.session == appSession)
        await form.signOut()
        #expect(store.load().state.credentials == nil && !cache.configured)
        await monitor.stop()
    }
    @Test func countryPickerDefaultsToUS() throws {
        let rig = try ControllerRig(configured: false)
        defer { try? FileManager.default.removeItem(at: rig.directory) }
        let form = CredentialSettings(monitor: rig.controller)
        #expect(form.country == "US" && form.item == "Anker" && form.vault.isEmpty)
        #expect(SettingsView.countryOptions.contains("US"))
    }
    @Test func observedSelectionChangesPreserveAnItemNameWhileTypingSpaces() async throws {
        let rig = try ControllerRig(configured: false); await rig.start()
        let form = CredentialSettings(monitor: rig.controller)
        form.edit(item: "Synthetic ", vault: "", country: "US")
        form.sync() // Same callback the maintained view uses for observed state.
        #expect(form.item == "Synthetic ")
        form.edit(item: form.item + "Login", vault: "", country: "US")
        #expect(form.configuration.item == "Synthetic Login")
        rig.controller.setCredentialSelection(OnePasswordConfiguration(item: "Another Login", vault: "Another Vault", country: "CA").selection)
        form.sync()
        #expect(form.item == "Another Login" && form.vault == "Another Vault" && form.country == "CA")
        await rig.finish()
    }
    @Test func chargerPickerListsSupportedOnly() {
        let unsupported = ChargerInfo(serial: "synthetic-other", model: "A0000", alias: "Other", name: "Other")
        #expect(SettingsView.supportedChargers([unsupported, appCharger]) == [appCharger])
    }
    @Test func literalItemNameSurvivesPersistenceSyncAndReappearance() async throws {
        let rig = try ControllerRig(configured: false); await rig.start()
        let form = CredentialSettings(monitor: rig.controller)
        form.edit(item: " Synthetic Login ", vault: "", country: "US")
        form.sync()
        #expect(form.item == " Synthetic Login ")
        #expect(rig.controller.appState.credentials?.settings["item"] == " Synthetic Login ")
        let reappeared = CredentialSettings(monitor: rig.controller)
        #expect(reappeared.item == " Synthetic Login ")
        let saved = StateStore(fileURL: rig.directory.appending(path: "state.json", directoryHint: .notDirectory)).load()
        #expect(saved.state.credentials?.settings["item"] == " Synthetic Login ")
        form.edit(item: "   ", vault: "", country: "US")
        #expect(!form.valid)
        await rig.finish()
    }
    @Test func intervalPickerOffersEveryClosedIntervalDefaultingToDefault() throws {
        let rig = try ControllerRig(configured: false)
        defer { try? FileManager.default.removeItem(at: rig.directory) }
        #expect(SettingsView.intervals == ClosedInterval.allCases)
        #expect(rig.controller.appState.closedInterval == .default)
        for interval in SettingsView.intervals { rig.controller.setClosedInterval(interval); #expect(rig.controller.appState.closedInterval == interval) }
    }
    @Test func firstLaunchWithoutSecretsOpensSettings() async throws {
        for configured in [false, true] {
            let rig = try ControllerRig(configured: configured)
            let status = SetupStatus()
            let delegate = AppDelegate(controller: rig.controller, acquireLease: { AppInstanceLease {} }, statusFactory: { status })
            delegate.applicationDidFinishLaunching(Notification(name: NSApplication.didFinishLaunchingNotification))
            await delegate.startupTask?.value
            #expect(status.settingsOpenings == (configured ? 0 : 1))
            await rig.finish()
        }
    }
}
@MainActor private final class SetupStatus: PopoverPresenting {
    var settingsOpenings = 0
    func showPopover() {}
    func showSettings() { settingsOpenings += 1 }
}
