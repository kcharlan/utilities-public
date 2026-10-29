import Foundation
import Testing
import TelltaleCodex
import TelltaleClaude
import TelltaleCore
@testable import Telltale

@Suite struct RegistryTests {
    static let paths = TelltalePaths(
        home: URL(fileURLWithPath: "/nonexistent-synthetic/home", isDirectory: true),
        codexHome: URL(fileURLWithPath: "/nonexistent-synthetic/codex", isDirectory: true))

    @Test func usageSourcesReadTheInjectedCodexHome() throws {
        let sources = Registry.usageSources(paths: Self.paths)
        #expect(sources.map(\.provider) == [.codex, .claude])
        let codex = try #require(sources.first as? CodexUsageSource)
        #expect(codex.codexHome == Self.paths.codexHome)
    }

    @Test func everyUsageSourceNamesARegisteredStatusSource() {
        let statusIDs = Registry.statusSources().map(\.id)
        #expect(statusIDs == ["openai", "anthropic"])
        #expect(Set(statusIDs).count == statusIDs.count)
        for source in Registry.usageSources(paths: Self.paths) {
            #expect(statusIDs.contains(source.statusSourceID), "\(source.provider.rawValue) names \(source.statusSourceID)")
        }
    }

    @Test func usageSourcesReadTheInjectedClaudeHome() throws {
        let claude = try #require(Registry.usageSources(paths: Self.paths).last as? ClaudeUsageSource)
        #expect(claude.roots == [Self.paths.claudeHome])
    }

    @Test func statusIDsDifferFromProviderIDs() {
        for source in Registry.usageSources(paths: Self.paths) {
            #expect(source.provider.rawValue != source.statusSourceID)
        }
        #expect(Registry.statusSummaries().last?.defaultWatchedComponents == ["Claude Code"])
    }

    @Test func statusSummariesCarryDefaults() throws {
        let summaries = Registry.sourceSummaries(paths: Self.paths)
        #expect(summaries[0].failureNoun == "turn")
        #expect(summaries[1].failureNoun == "request")
        #expect(summaries[1].dataFolder == Self.paths.claudeHome)
    }

    @Test func configRootIsUsedOnlyWhenItExists() throws {
        let home = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: home) }
        let paths = TelltalePaths(home: home)
        try FileManager.default.createDirectory(at: paths.claudeConfigRoot, withIntermediateDirectories: true)
        let claude = try #require(Registry.usageSources(paths: paths).last as? ClaudeUsageSource)
        #expect(claude.roots == [paths.claudeHome, paths.claudeConfigRoot])
    }

    @Test func providersAreUnique() {
        let providers = Registry.usageSources(paths: Self.paths).map(\.provider)
        #expect(Set(providers).count == providers.count)
    }

    @Test func noticesBecomeRequestsWithStableIdentity() {
        let notice = PendingNotification(
            id: "slower-7-fired", title: "Slower than usual", body: "Example is 25% slower than usual.", threadID: "slower.codex.example")
        let request = NativeNotificationPoster.request(for: notice)
        #expect(request.identifier == "slower-7-fired")
        #expect(request.content.title == "Slower than usual")
        #expect(request.content.body == "Example is 25% slower than usual.")
        #expect(request.content.threadIdentifier == "slower.codex.example")
        #expect(request.trigger == nil)
    }

    @Test func sourceSummariesNameTheStatusSource() throws {
        let summary = try #require(Registry.sourceSummaries(paths: Self.paths).first)
        #expect(Registry.sourceSummaries(paths: Self.paths).count == 2)
        #expect(summary.provider == .codex && summary.name == "Codex" && summary.statusName == "OpenAI")
        #expect(summary.signals == [.speed, .errors, .link, .provider, .load])
    }
}
