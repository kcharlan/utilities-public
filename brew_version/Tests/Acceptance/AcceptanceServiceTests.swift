import Foundation
import Testing
import BrewVersionCore
@testable import Acceptance

struct AcceptanceServiceTests {
    @MainActor @Test func tapTransportAndInventoryAreSynthetic() async throws {
        let service = SyntheticTransport()
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-taps-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let prefix = try SyntheticEnvironment.prepareTapFixtures(home: home)
        let prefixes = HomebrewPrefix.detectAll(candidates: [prefix])
        let index = TapIndex.scan(prefixes: prefixes)
        let name = PackageName("synthetic-owner/synthetic-tap/synthetic-tool")!
        let listing = try await TapClient(transport: service).lookup(index.entry(name, kind: .formula)!)
        #expect(listing.version == "4.5.6")
        let reader = InstalledReader(prefixes: prefixes, applicationDirectories: [], tappedTaps: { TapIndex.scan(prefixes: prefixes).taps })
        #expect(reader.installed(name, kind: .formula, listing: listing)?.version == "1.0-synthetic")
        await service.setTapFailures(true)
        let url = URL(string: "https://raw.githubusercontent.com/synthetic-owner/homebrew-synthetic-tap/HEAD/Formula/synthetic-tool.rb")!
        #expect(try await service.get(url, ifNoneMatch: nil).status == 503)
        let clock = AcceptanceClock()
        let controller = WatchController(transport: service, installed: reader,
            store: WatchStore(fileURL: home.appendingPathComponent("state.json")), notifier: AcceptanceQuietNotifier(), now: { clock.now },
            catalogClient: CatalogClient(transport: service, cacheDirectory: home.appendingPathComponent("cache")), taps: { TapIndex.scan(prefixes: prefixes) })
        await controller.refreshNow()
        #expect(controller.tapCheckFailures == 1)
        #expect(controller.tapUncheckable == 1)
        #expect(controller.suggestions(prefix: "synthetic-tool").first?.installed == true)
        #expect(controller.suggestions(prefix: "synthetic-app").first?.kind == .cask)
        await service.setTapFailures(false)
        clock.now = clock.now.addingTimeInterval(601)
        await controller.refreshNow()
        #expect(controller.tapCheckFailures == 0 && controller.tapUncheckable == 0)
        await controller.add(name, kind: .formula)
        try SyntheticEnvironment.setTapPresent(false, home: home)
        clock.now = clock.now.addingTimeInterval(601)
        await controller.refreshNow()
        #expect(controller.state.watched.first?.lastError == "synthetic-owner/synthetic-tap is no longer tapped.")
        try SyntheticEnvironment.setTapPresent(true, home: home)
        #expect(TapIndex.scan(prefixes: prefixes).entry(name, kind: .formula) != nil)
    }
    @Test func baselineAdvanceAndCatalogAreSynthetic() async throws {
        let service = SyntheticTransport()
        let name = PackageName("synthetic-formula")!
        let client = HomebrewClient(transport: service)
        #expect(try await client.lookup(name, kinds: .auto).version == "1.0-synthetic")
        await service.advance()
        #expect(try await client.lookup(name, kinds: .auto).version == "2.0-synthetic")
        let unknown = URL(string: "https://formulae.brew.sh/api/formula/synthetic-missing.json")!
        #expect(try await service.get(unknown, ifNoneMatch: nil).status == 404)
        let home = FileManager.default.temporaryDirectory.appendingPathComponent("synthetic-catalog-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        let catalog = try await CatalogClient(transport: service, cacheDirectory: home).load().catalog
        let installed = try #require(catalog.listing(for: PackageName("synthetic-installed")!, kind: .formula))
        #expect(installed.version == "2.0-synthetic")
        #expect(catalog.suggestions(prefix: "synthetic").count == 6)
        let shared = PackageName("synthetic-shared")!
        #expect(try await client.lookup(shared, kinds: .formula).version == "3.0-synthetic")
        #expect(try await client.lookup(shared, kinds: .cask).version == "4.0-synthetic")
        let fallback = try await client.lookup(PackageName("synthetic-fallback")!, kinds: .cask)
        #expect(fallback.autoUpdates)
        #expect(fallback.appNames == ["Synthetic Missing.app"])
    }
}
private struct AcceptanceQuietNotifier: Notifier { func post(_ notice: Notice) async {} }
@MainActor private final class AcceptanceClock { var now = Date() }
