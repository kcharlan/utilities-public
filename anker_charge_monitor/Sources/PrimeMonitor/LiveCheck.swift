import Foundation
import PrimeMonitorCore

@MainActor enum LiveCheck {
    static func run(controller: MonitorController, acquireLease: () throws -> AppInstanceLease,
                    timeout: TimeInterval = 30, output: (String) -> Void) async -> Int32 {
        let lease: AppInstanceLease
        do { lease = try acquireLease() }
        catch AppInstanceGateError.alreadyRunning { output("\(PrimeMonitorRelease.displayName) is already running. Quit it before live-check."); return 4 }
        catch { output("Couldn't acquire the instance gate."); return 5 }
        controller.start(); controller.panelOpened()
        let result = await wait(controller, timeout: timeout, output: output)
        await controller.stop(); lease.release()
        return result
    }
    private static func wait(_ controller: MonitorController, timeout: TimeInterval, output: (String) -> Void) async -> Int32 {
        let deadline = ContinuousClock.now.advanced(by: .seconds(max(0, timeout)))
        while true {
            // Errors win over retained readings: persistence failures cannot pass a live check.
            switch controller.status {
            case .error, .sessionEnded, .signInFailed, .verificationRequired: output("Monitoring failed; open \(PrimeMonitorRelease.displayName) to review account or settings."); return 5
            case .notConfigured: output("No saved account. Configure \(PrimeMonitorRelease.displayName) first."); return 2
            default: break
            }
            if controller.appState.charger == nil { output("No selected charger. Configure \(PrimeMonitorRelease.displayName) first."); return 2 }
            if let snapshot = controller.snapshot, !controller.isStale {
                for line in DiagnosticReadout.lines(snapshot) { output(line) }; return 0
            }
            if Task.isCancelled || ContinuousClock.now >= deadline { output("Timed out waiting for charger readings."); return 3 }
            try? await Task.sleep(for: .milliseconds(10))
        }
    }
}
