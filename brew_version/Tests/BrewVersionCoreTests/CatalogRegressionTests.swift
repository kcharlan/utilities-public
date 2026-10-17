import Foundation
import Testing
@testable import BrewVersionCore

struct CatalogRegressionTests {
    @Test(arguments: ["[]", #"[{"name":"synthetic-empty","versions":{"stable":null}}]"#])
    func unusableSuccessRetainsValidPair(_ body: String) async throws {
        let f = WatchFixture(); defer { f.clean() }
        _ = try await seedCatalog(f.directory)
        let before = try Data(contentsOf: f.directory.appendingPathComponent("catalog.json"))
        let transport = StubTransport([catalogURL(.formula): [catalogResponse(200, body)],
                                       catalogURL(.cask): [catalogResponse(200, syntheticCaskList)]])
        let result = try await CatalogClient(transport: transport, cacheDirectory: f.directory).load()
        #expect(!result.revalidated)
        #expect(result.catalog.listing(for: PackageName("synthetic-formula")!, kind: .formula)?.version == "2")
        #expect(try Data(contentsOf: f.directory.appendingPathComponent("catalog.json")) == before)
    }
    @Test func bulkyIgnoredMetadataDoesNotSurviveCacheOrRevalidation() async throws {
        let f = WatchFixture(); defer { f.clean() }
        // Invented metadata dwarfs the retained listing; never use real API data.
        let padding = String(repeating: "synthetic-unused-metadata", count: 100_000)
        let body = "[{\"name\":\"synthetic-formula\",\"versions\":{\"stable\":\"2\"},\"bottle\":{\"ignored\":\"\(padding)\"}}]"
        let transport = StubTransport([catalogURL(.formula): [catalogResponse(200, body, etag: "synthetic-f"), catalogResponse(304)],
                                       catalogURL(.cask): [catalogResponse(200, syntheticCaskList, etag: "synthetic-c"), catalogResponse(304)]])
        let client = CatalogClient(transport: transport, cacheDirectory: f.directory)
        _ = try await client.load()
        let bytes = try Data(contentsOf: f.directory.appendingPathComponent("catalog.json"))
        #expect(bytes.count < 4096)
        // Revalidation must use the in-memory digested listings even after disk corruption.
        try Data("synthetic corrupt disk".utf8).write(to: f.directory.appendingPathComponent("catalog.json"))
        let result = try await client.load()
        #expect(result.revalidated && result.catalog.suggestions(prefix: "").count == 2)
        #expect(await transport.requests.map(\.etag) == [nil, nil, "synthetic-f", "synthetic-c"])
    }
    @Test func oldRawCacheIsIgnoredAndReplaced() async throws {
        let f = WatchFixture(); defer { f.clean() }
        try FileManager.default.createDirectory(at: f.directory, withIntermediateDirectories: true)
        let raw = ["formula": ["data": Data(syntheticFormulaList.utf8).base64EncodedString(), "etag": "synthetic-legacy"],
                   "cask": ["data": Data(syntheticCaskList.utf8).base64EncodedString(), "etag": "synthetic-legacy"]]
        try JSONSerialization.data(withJSONObject: raw).write(to: f.directory.appendingPathComponent("catalog.json"))
        let transport = catalogStub()
        let client = CatalogClient(transport: transport, cacheDirectory: f.directory)
        #expect(try await client.cached() == nil)
        #expect(try await client.load().revalidated)
        #expect(await transport.requests.allSatisfy { $0.etag == nil })
        let restart = CatalogClient(transport: StubTransport([:]), cacheDirectory: f.directory)
        #expect(try await restart.cached()?.suggestions(prefix: "").count == 2)
    }
}
