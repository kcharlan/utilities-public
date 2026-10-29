import Foundation

/// Every runtime location Telltale uses (spec sections 4 and 9.3), derived from
/// one injected home so tests never touch the real `~/Library` or `~/.codex`.
public struct TelltalePaths: Sendable, Equatable {
    /// `~/Library/Application Support/Telltale`
    public let appSupport: URL
    /// The SQLite database (WAL mode).
    public let database: URL
    /// The collector's overlap-guard `flock` file.
    public let lock: URL
    /// The app's single-instance gate (plan call, used by Task 11).
    public let appLock: URL
    /// `~/Library/Logs/Telltale`
    public let logDirectory: URL
    public let log: URL
    /// `~/Library/LaunchAgents`, where the collector's plist is written.
    public let launchAgents: URL
    /// The Codex data directory (`~/.codex` unless overridden).
    public let codexHome: URL
    public let claudeHome: URL
    public let claudeConfigRoot: URL

    public init(home: URL, codexHome: URL? = nil, claudeHome: URL? = nil) {
        func directory(_ base: URL, _ components: String...) -> URL {
            components.reduce(base) { $0.appending(path: $1, directoryHint: .isDirectory) }
        }
        appSupport = directory(home, "Library", "Application Support", "Telltale")
        database = appSupport.appending(path: "telltale.sqlite", directoryHint: .notDirectory)
        lock = appSupport.appending(path: "collector.lock", directoryHint: .notDirectory)
        appLock = appSupport.appending(path: "app.lock", directoryHint: .notDirectory)
        logDirectory = directory(home, "Library", "Logs", "Telltale")
        log = logDirectory.appending(path: "collector.log", directoryHint: .notDirectory)
        launchAgents = directory(home, "Library", "LaunchAgents")
        self.codexHome = codexHome ?? directory(home, ".codex")
        self.claudeHome = claudeHome ?? directory(home, ".claude")
        self.claudeConfigRoot = directory(home, ".config", "claude")
    }

    /// Paths for the real user. `CODEX_HOME` overrides the Codex directory when it
    /// is set and non-empty, as Codex's own variable does (plan call).
    public static func live(environment: [String: String] = ProcessInfo.processInfo.environment) -> TelltalePaths {
        let override = environment["CODEX_HOME"].flatMap { $0.isEmpty ? nil : URL(fileURLWithPath: $0, isDirectory: true) }
        let claude = environment["CLAUDE_CONFIG_DIR"].flatMap { $0.isEmpty ? nil : URL(fileURLWithPath: $0, isDirectory: true) }
        return TelltalePaths(home: FileManager.default.homeDirectoryForCurrentUser, codexHome: override, claudeHome: claude)
    }
}
