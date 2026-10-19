import AppKit
import AnkerCloud
import Foundation
import PrimeMonitorCore

/// Composition adapted from BrewVersion/BrewVersionApp.swift, main, 579ebb7.
@main struct PrimeMonitorApp {
    @MainActor static func main() async {
        let liveCheck = CommandLine.arguments.contains("--live-check")
        let lease: AppInstanceLease
        do { lease = try AppInstanceGate.acquire(at: StateStore().fileURL.deletingLastPathComponent().appending(path: "instance.lock", directoryHint: .notDirectory)) }
        catch {
            if liveCheck { print("Couldn't acquire instance gate. Quit \(PrimeMonitorRelease.displayName) before live-check."); exit(error as? AppInstanceGateError == .alreadyRunning ? 4 : 5) }
            let alert = NSAlert(); alert.messageText = "\(PrimeMonitorRelease.displayName) is already running or its state directory is unavailable."; alert.runModal(); return
        }
        let controller = MonitorController(backend: AnkerCloudBackend.live(), secrets: MemorySessionStore(), state: StateStore(), events: SystemEvents(), now: Date.init, scheduler: TimerPollScheduler(), makeProvider: { selection in
            guard let configuration = OnePasswordConfiguration(selection: selection) else { throw CredentialFailure.unsupported }
            return OnePasswordProvider(configuration: configuration)
        })
        if liveCheck {
            let result = await LiveCheck.run(controller: controller, acquireLease: { lease }, timeout: 30, output: { print($0) }); exit(result)
        }
        let app = NSApplication.shared
        ApplicationMenu.install()
        let delegate = AppDelegate(controller: controller, acquireLease: { lease })
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
