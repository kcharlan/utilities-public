import Foundation
import Testing
import BrewVersionCore
@testable import Acceptance

struct AcceptanceServiceTests {
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
        #expect(catalog.suggestions(prefix: "synthetic").count == 2)
    }
}
