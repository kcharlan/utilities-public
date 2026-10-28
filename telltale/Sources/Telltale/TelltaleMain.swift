import AppKit
import Foundation
import TelltaleCore

/// What the executable was asked to do, from its command line.
enum LaunchCommand: Equatable {
    case app
    case collect
    case notificationCheck(result: URL, mode: String)
    /// Anything else: an unknown or extra argument, or `--notification-check` without both
    /// `--result` and `--mode`. It never falls through to the UI, so a launchd typo can't open it;
    /// only the system's own launch arguments (`isSystemLaunch`) still mean `.app`.
    case usageError

    static let usageExitCode = CollectorRun.ExitCode.usage
    static let usage = """
        Usage: Telltale                 (menu bar app)
               Telltale --collect       (one collector run)
               Telltale --notification-check --result <path> --mode <name>

        """

    static func parse(_ arguments: [String]) -> LaunchCommand {
        let arguments = Array(arguments.dropFirst())
        switch arguments.first {
        case nil:
            return .app
        case "--collect":
            return arguments.count == 1 ? .collect : .usageError
        case "--notification-check":
            // `--result <path>` and `--mode <name>`, once each, in either order.
            var values: [String: String] = [:]
            var rest = arguments.dropFirst()
            while let flag = rest.popFirst() {
                guard flag == "--result" || flag == "--mode", values[flag] == nil, let value = rest.popFirst() else { return .usageError }
                values[flag] = value
            }
            guard let result = values["--result"], let mode = values["--mode"] else { return .usageError }
            return .notificationCheck(result: URL(fileURLWithPath: result), mode: mode)
        default:
            return isSystemLaunch(arguments) ? .app : .usageError
        }
    }

    /// Arguments the system or a debugger adds to an ordinary app launch: a lone `-psn_…` process
    /// serial number, or `-NS…` and `-Apple…` argument-domain defaults, each a flag plus its value.
    private static func isSystemLaunch(_ arguments: [String]) -> Bool {
        if arguments.count == 1, arguments[0].hasPrefix("-psn_") { return true }
        var rest = arguments[...]
        while let flag = rest.popFirst() {
            guard flag.hasPrefix("-NS") || flag.hasPrefix("-Apple"), rest.popFirst() != nil else { return false }
        }
        return true
    }
}

@main struct TelltaleMain {
    @MainActor static func main() async {
        switch LaunchCommand.parse(CommandLine.arguments) {
        case .notificationCheck(let result, let mode):
            exit(await NotificationCheck.run(service: NativeNotificationService(), resultURL: result, mode: mode))
        case .collect:
            // No UI instance gate: the collector runs beside the app.
            exit(await CollectorEntry.run())
        case .usageError:
            FileHandle.standardError.write(Data(LaunchCommand.usage.utf8))
            exit(LaunchCommand.usageExitCode)
        case .app:
            let app = NSApplication.shared
            app.setActivationPolicy(.accessory)
            ApplicationMenu.install()
            // Barlow Semi Condensed for the dashboard's readouts; the system font stands in on failure.
            if let fonts = Fonts.bundled { Fonts.register(from: fonts) }
            let paths = TelltalePaths.live()
            let delegate = AppDelegate(
                paths: paths, currentExecutable: Bundle.main.executableURL ?? URL(fileURLWithPath: CommandLine.arguments[0]),
                installedAppURL: URL(fileURLWithPath: "/Applications/\(TelltaleRelease.displayName).app", isDirectory: true),
                runner: ProcessRunner(), sources: Registry.sourceSummaries(paths: paths), notificationService: NativeNotificationService(),
                login: LoginItem())
            app.delegate = delegate
            withExtendedLifetime(delegate) { app.run() }
        }
    }
}

