import Foundation
import TelltaleCore

/// `Telltale --collect`: one collector run for the real user, with the registered plugins.
/// launchd starts it every N minutes (spec section 9.3); its exit code is the run's.
enum CollectorEntry {
    static func run() async -> Int32 {
        let paths = TelltalePaths.live()
        let report = await CollectorRun(
            paths: paths, sources: Registry.usageSources(paths: paths), statusSources: Registry.statusSources(),
            notifier: NativeNotificationPoster(), calendar: .current, now: Date()
        ).run()
        return report.exitCode
    }
}

