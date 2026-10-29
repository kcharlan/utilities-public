import Foundation
import TelltaleCodex
import TelltaleClaude
import TelltaleStatuspage
import TelltaleCore
import TelltaleOpenAIStatus

/// The single registration list (spec section 5): plugins are compiled in, and snapping one in
/// means adding it here. Each usage source's `statusSourceID` names a status source below.
enum Registry {
    static func usageSources(paths: TelltalePaths) -> [any UsageSource] {
        [CodexUsageSource(codexHome: paths.codexHome, snapshotDirectory: paths.codexSnapshots), ClaudeUsageSource(roots: [paths.claudeHome] + (FileManager.default.fileExists(atPath: paths.claudeConfigRoot.path) ? [paths.claudeConfigRoot] : []))]
    }

    static func statusSources() -> [any StatusSource] {
        [OpenAIStatusSource(transport: URLSessionTransport()), StatuspageSource(id: "anthropic", displayName: "Claude", baseURL: URL(string: "https://status.claude.com")!, transport: URLSessionTransport(), defaultWatchedComponents: ["Claude Code"])]
    }

    static func statusSummaries() -> [StatusSourceSummary] {
        statusSources().map { StatusSourceSummary(id: $0.id, displayName: $0.displayName, defaultWatchedComponents: $0.defaultWatchedComponents) }
    }

    /// The usage sources as the panel sees them: name, the status source's name for the Provider
    /// lamp, declared signals and model naming.
    static func sourceSummaries(paths: TelltalePaths) -> [SourceSummary] {
        let statusNames = Dictionary(statusSources().map { ($0.id, $0.displayName) }, uniquingKeysWith: { first, _ in first })
        return usageSources(paths: paths).map { source in
            SourceSummary(
                provider: source.provider, name: source.displayName, statusName: statusNames[source.statusSourceID] ?? source.displayName, statusSourceID: source.statusSourceID,
                signals: source.signals, naming: source, dataFolder: source.dataFolder, failureNoun: source.failureNoun, supportedRules: source.supportedRules)
        }
    }
}
