import Foundation
import Testing
import TelltaleCodex
import TelltaleCore
@testable import Telltale

@Suite struct RegistryTests {
    static let paths = TelltalePaths(
        home: URL(fileURLWithPath: "/nonexistent-synthetic/home", isDirectory: true),
        codexHome: URL(fileURLWithPath: "/nonexistent-synthetic/codex", isDirectory: true))

    @Test func usageSourcesReadTheInjectedCodexHome() throws {
        let sources = Registry.usageSources(paths: Self.paths)
        #expect(sources.map(\.provider) == [.codex])
        let codex = try #require(sources.first as? CodexUsageSource)
        #expect(codex.codexHome == Self.paths.codexHome)
    }

    @Test func everyUsageSourceNamesARegisteredStatusSource() {
        let statusIDs = Registry.statusSources().map(\.id)
        #expect(statusIDs == ["openai"])
        #expect(Set(statusIDs).count == statusIDs.count)
        for source in Registry.usageSources(paths: Self.paths) {
            #expect(statusIDs.contains(source.statusSourceID), "\(source.provider.rawValue) names \(source.statusSourceID)")
        }
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
}
