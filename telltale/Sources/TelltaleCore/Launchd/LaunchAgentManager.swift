import Foundation

public enum LaunchAgentError: Error, Equatable, Sendable, LocalizedError {
    /// The executable isn't the main executable of an app bundle.
    case notInAppBundle
    /// The bundle's identifier (carried for logs) isn't Telltale's.
    case wrongBundle(String)
    /// The interval is out of range; the message is `Settings.intervalError`'s.
    case invalidInterval(String)
    /// `launchctl <command>` exited with `status`; `stderr` is trimmed.
    case launchctl(command: String, status: Int32, stderr: String)

    public var errorDescription: String? {
        switch self {
        case .notInAppBundle: Copy.notInAppBundle
        case .wrongBundle: Copy.wrongBundle
        case .invalidInterval(let message): message
        case .launchctl(let command, let status, let stderr): Copy.launchctlError(command: command, status: status, stderr: stderr)
        }
    }
}

/// Installs and controls the collector's user launchd job (spec section 9.3's actions table).
///
/// The job is a plist in `~/Library/LaunchAgents` that runs `[executable, --collect]` every
/// interval. Installing it (`turnOn`, `changeInterval`, `repair`) validates first and writes
/// nothing when validation fails: the executable must be the main executable of an app bundle
/// whose identifier is Telltale's, so a build product or the acceptance build can never become
/// the collector, and the interval must pass `Settings.intervalError`. The plist is replaced
/// atomically, then the job is booted out (a not-loaded result is fine) and bootstrapped; any
/// other launchctl failure throws.
public struct LaunchAgentManager: Sendable {
    public static let launchctl = "/bin/launchctl"
    /// Exit statuses `launchctl bootout` uses when the job isn't loaded: ESRCH ("No such
    /// process") and 113 ("Could not find service").
    static let notLoadedStatuses: Set<Int32> = [3, 113]

    public let paths: TelltalePaths
    public let uid: uid_t
    public let runner: any CommandRunner
    public let label: String

    public init(paths: TelltalePaths, uid: uid_t, runner: any CommandRunner, label: String = TelltaleRelease.collectorLabel) {
        self.paths = paths
        self.uid = uid
        self.runner = runner
        self.label = label
    }

    /// The real user's job, run through `ProcessRunner`.
    public static func live(paths: TelltalePaths) -> LaunchAgentManager {
        LaunchAgentManager(paths: paths, uid: getuid(), runner: ProcessRunner())
    }

    /// `~/Library/LaunchAgents/<label>.plist`
    public var plistURL: URL { paths.launchAgents.appending(path: "\(label).plist", directoryHint: .notDirectory) }
    private var domain: String { "gui/\(uid)" }
    private var service: String { "gui/\(uid)/\(label)" }

    /// The job's property list (spec section 9.3).
    public func plist(executable: URL, intervalMinutes: Int) -> [String: Any] {
        [
            "Label": label,
            "ProgramArguments": [executable.standardizedFileURL.path, "--collect"],
            "StartInterval": intervalMinutes * 60,
            "RunAtLoad": true,
            "ProcessType": "Background",
            "StandardOutPath": paths.log.path,
            "StandardErrorPath": paths.log.path,
        ]
    }

    public func turnOn(executable: URL, intervalMinutes: Int) throws {
        try install(executable: executable, intervalMinutes: intervalMinutes)
    }

    /// Boots the job out, then removes the plist. Off already is fine; a failed bootout keeps the plist.
    public func turnOff() throws {
        try bootout()
        if FileManager.default.fileExists(atPath: plistURL.path) {
            try FileManager.default.removeItem(at: plistURL)
        }
    }

    /// Rewrites the plist with the new interval, then reloads the job.
    public func changeInterval(executable: URL, intervalMinutes: Int) throws {
        try install(executable: executable, intervalMinutes: intervalMinutes)
    }

    /// "Run now" and "Check now": start the job once, outside its schedule.
    public func kickstart() throws {
        try launchctl("kickstart", [service])
    }

    /// The executable the installed plist runs; nil when there is no readable plist.
    public func installedExecutable() -> URL? {
        guard let data = try? Data(contentsOf: plistURL),
              let plist = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
              let path = (plist["ProgramArguments"] as? [String])?.first
        else { return nil }
        return URL(fileURLWithPath: path)
    }

    /// Whether `launchctl print` finds the job. Spec section 9.3 uses it only for the Loaded lamp,
    /// because its output format isn't stable, so only the exit status is read.
    public func isLoaded() -> Bool {
        (try? runner.run(Self.launchctl, ["print", service]).status) == 0
    }

    /// True when a plist exists but doesn't run `currentExecutable` (the app moved or was
    /// replaced), or can't be read. No plist is "off", not "needs repair".
    public func needsRepair(currentExecutable: URL) -> Bool {
        guard FileManager.default.fileExists(atPath: plistURL.path) else { return false }
        guard let installed = installedExecutable() else { return true }
        return !Self.sameExecutable(installed, currentExecutable)
    }

    /// Rewrites the plist for `executable` and reloads the job.
    public func repair(executable: URL, intervalMinutes: Int) throws {
        try install(executable: executable, intervalMinutes: intervalMinutes)
    }

    /// Whether two paths name the same file once standardized and symlink-resolved.
    public static func sameExecutable(_ first: URL, _ second: URL) -> Bool {
        resolved(first).path == resolved(second).path
    }

    // MARK: Internals

    private static func resolved(_ url: URL) -> URL { url.standardizedFileURL.resolvingSymlinksInPath() }

    private func install(executable: URL, intervalMinutes: Int) throws {
        try validate(executable: executable, intervalMinutes: intervalMinutes)
        let data = try PropertyListSerialization.data(
            fromPropertyList: plist(executable: executable, intervalMinutes: intervalMinutes), format: .xml, options: 0)
        try FileManager.default.createDirectory(at: paths.launchAgents, withIntermediateDirectories: true)
        // launchd opens StandardOutPath at each spawn but doesn't create its directory.
        try FileManager.default.createDirectory(at: paths.logDirectory, withIntermediateDirectories: true)
        try data.write(to: plistURL, options: .atomic)
        try bootout()
        try launchctl("bootstrap", [domain, plistURL.path])
    }

    /// Spec section 9.3's preconditions, checked in order: an app bundle's main executable, Telltale's
    /// bundle identifier, then a valid interval.
    private func validate(executable: URL, intervalMinutes: Int) throws {
        let binary = Self.resolved(executable)
        let macOS = binary.deletingLastPathComponent()
        let contents = macOS.deletingLastPathComponent()
        let bundle = contents.deletingLastPathComponent()
        guard macOS.lastPathComponent == "MacOS", contents.lastPathComponent == "Contents", bundle.pathExtension == "app",
              FileManager.default.isExecutableFile(atPath: binary.path),
              let data = try? Data(contentsOf: contents.appending(path: "Info.plist", directoryHint: .notDirectory)),
              let info = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
              info["CFBundleExecutable"] as? String == binary.lastPathComponent
        else { throw LaunchAgentError.notInAppBundle }
        let identifier = info["CFBundleIdentifier"] as? String ?? ""
        guard identifier == TelltaleRelease.bundleIdentifier else { throw LaunchAgentError.wrongBundle(identifier) }
        if let message = Settings.intervalError(intervalMinutes) { throw LaunchAgentError.invalidInterval(message) }
    }

    private func bootout() throws {
        let result = try runner.run(Self.launchctl, ["bootout", service])
        guard result.status == 0 || Self.notLoadedStatuses.contains(result.status) else { throw failure("bootout", result) }
    }

    private func launchctl(_ command: String, _ arguments: [String]) throws {
        let result = try runner.run(Self.launchctl, [command] + arguments)
        guard result.status == 0 else { throw failure(command, result) }
    }

    private func failure(_ command: String, _ result: CommandResult) -> LaunchAgentError {
        .launchctl(command: command, status: result.status, stderr: result.stderr.trimmingCharacters(in: .whitespacesAndNewlines))
    }
}
