import AppKit
import Foundation
import UserNotifications
import TelltaleCore

/// What the executable was asked to do, from its command line.
enum LaunchCommand: Equatable {
    case app
    case collect
    case notificationCheck(result: URL, mode: String)
    /// Anything else: an unknown or extra argument, or `--notification-check` without both
    /// `--result` and `--mode`. It never falls through to the UI, so a launchd typo can't open it.
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
            return .usageError
        }
    }
}

@main struct TelltaleMain {
    @MainActor static func main() async {
        switch LaunchCommand.parse(CommandLine.arguments) {
        case .notificationCheck(let result, let mode):
            exit(await NotificationCheck.run(service: NativeNotificationService(), resultURL: result, mode: mode))
        case .collect:
            // No UI instance gate (Task 11): the collector runs beside the app.
            exit(await CollectorEntry.run())
        case .usageError:
            FileHandle.standardError.write(Data(LaunchCommand.usage.utf8))
            exit(LaunchCommand.usageExitCode)
        case .app:
            let app = NSApplication.shared
            app.setActivationPolicy(.accessory)
            let delegate = PlaceholderAppDelegate()
            app.delegate = delegate
            withExtendedLifetime(delegate) { app.run() }
        }
    }
}

/// Placeholder UI for the notification spike: asks for notification permission,
/// reports the answer in a small window and runs until quit. Task 11 replaces it.
@MainActor final class PlaceholderAppDelegate: NSObject, NSApplicationDelegate {
    private let service: any NotificationService
    private let label = NSTextField(wrappingLabelWithString: "Requesting notification permission...")
    private var window: NSWindow?

    init(service: any NotificationService = NativeNotificationService()) {
        self.service = service
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let quit = NSButton(title: "Quit", target: NSApp, action: #selector(NSApplication.terminate(_:)))
        let stack = NSStackView(views: [label, quit])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12
        stack.edgeInsets = NSEdgeInsets(top: 16, left: 16, bottom: 16, right: 16)
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 360, height: 120), styleMask: [.titled, .closable],
                              backing: .buffered, defer: false)
        window.title = TelltaleRelease.displayName
        window.contentView = stack
        window.isReleasedWhenClosed = false
        window.center()
        window.makeKeyAndOrderFront(nil)
        self.window = window
        NSApp.activate()
        Task { await reportAuthorization() }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    private func reportAuthorization() async {
        do {
            var status = await service.authorizationStatus()
            if status == .notDetermined { status = try await service.requestAuthorization() ? .authorized : .denied }
            label.stringValue = status == .authorized || status == .provisional
                ? "Notifications are allowed for \(TelltaleRelease.displayName)."
                : Copy.notificationsDenied
        } catch {
            label.stringValue = Copy.notificationAuthorizationFailure(error: error)
        }
    }
}
