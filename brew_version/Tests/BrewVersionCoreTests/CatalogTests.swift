import Foundation
import Testing
@testable import BrewVersionCore

func catalogURL(_ kind: PackageKind) -> URL {
    URL(string: "https://formulae.brew.sh/api/\(kind.rawValue).json")!
}
func catalogResponse(_ status: Int = 200, _ body: String = "[]", etag: String? = nil) -> Result<HTTPResponse, URLError> {
    .success(HTTPResponse(status: status, body: Data(body.utf8), etag: etag))
}
let syntheticFormulaList = #"[{"name":"synthetic-formula","versions":{"stable":"2"}},{"name":"synthetic-unusable","versions":{"stable":null}},{"name":"synthetic-empty","versions":{"stable":" "}}]"#
let syntheticCaskList = #"[{"token":"synthetic-cask","version":"3","auto_updates":true,"artifacts":[{"app":["Synthetic.app"]}]}]"#
func catalogStub() -> StubTransport {
    StubTransport([catalogURL(.formula): [catalogResponse(200, syntheticFormulaList, etag: "synthetic-formula-tag")],
                   catalogURL(.cask): [catalogResponse(200, syntheticCaskList, etag: "synthetic-cask-tag")]])
}
func seedCatalog(_ directory: URL) async throws -> Catalog {
    try await CatalogClient(transport: catalogStub(), cacheDirectory: directory).load().catalog
}

struct CatalogTests {
    @Test(arguments: [false, true]) func validDownloadSurvivesUnwritableCacheAndReusesItsETags(_ seeded: Bool) async throws {
        let f = WatchFixture(); defer { f.clean() }
        try FileManager.default.createDirectory(at: f.directory, withIntermediateDirectories: true)
        let blocked = seeded ? f.directory : f.directory.appendingPathComponent("synthetic-blocked-cache")
        if seeded { _ = try await seedCatalog(blocked) }
        else { try Data("synthetic file blocking directory".utf8).write(to: blocked) }
        let transport = StubTransport([
            catalogURL(.formula): [catalogResponse(200, syntheticFormulaList.replacingOccurrences(of: "\"2\"", with: "\"4\""), etag: "synthetic-new-formula"), catalogResponse(304), catalogResponse(500)],
            catalogURL(.cask): [catalogResponse(200, syntheticCaskList, etag: "synthetic-new-cask"), catalogResponse(304)]])
        let client = CatalogClient(transport: transport, cacheDirectory: blocked)
        if seeded {
            _ = try await client.cached()
            let cacheFile = blocked.appendingPathComponent("catalog.json")
            try FileManager.default.removeItem(at: cacheFile)
            try FileManager.default.createDirectory(at: cacheFile, withIntermediateDirectories: false)
        }
        let result = try await client.load()
        #expect(result.revalidated)
        #expect(result.cacheWriteError?.contains("Couldn't save catalog cache") == true)
        #expect(result.catalog.suggestions(prefix: "").count == 2)
        #expect(result.catalog.listing(for: PackageName("synthetic-formula")!, kind: .formula)?.version == "4")
        #expect(try await client.cached()?.suggestions(prefix: "").count == 2)
        _ = try await client.load()
        #expect(await transport.requests.map(\.etag) == [seeded ? "synthetic-formula-tag" : nil,
            seeded ? "synthetic-cask-tag" : nil, "synthetic-new-formula", "synthetic-new-cask"])
        let fallback = try await client.load()
        #expect(!fallback.revalidated)
        #expect(fallback.cacheWriteError != nil)
        #expect(fallback.catalog.listing(for: PackageName("synthetic-formula")!, kind: .formula)?.version == "4")
    }
    @Test func exactlyHalfPreviousUsableCountIsAdmitted() async throws {
        let f = WatchFixture(); defer { f.clean() }
        func formulas(_ count: Int) -> String {
            "[" + (0..<count).map { #"{"name":"synthetic-formula-\#($0)","versions":{"stable":"2"}}"# }.joined(separator: ",") + "]"
        }
        let transport = StubTransport([
            catalogURL(.formula): [catalogResponse(200, formulas(6)), catalogResponse(200, formulas(3))],
            catalogURL(.cask): [catalogResponse(200, syntheticCaskList), catalogResponse(304)]])
        let client = CatalogClient(transport: transport, cacheDirectory: f.directory)
        _ = try await client.load()
        let result = try await client.load()
        #expect(result.revalidated)
        #expect(result.catalog.suggestions(prefix: "", limit: 100).count == 4)
    }
    @Test(arguments: [PackageKind.formula, .cask])
    func suspiciousUsableCountPreservesBothListsAndETags(_ kind: PackageKind) async throws {
        let f = WatchFixture(); defer { f.clean() }
        let formulas = "[" + (0..<6).map { #"{"name":"synthetic-formula-\#($0)","versions":{"stable":"2"}}"# }.joined(separator: ",") + "]"
        let casks = "[" + (0..<6).map { #"{"token":"synthetic-cask-\#($0)","version":"3"}"# }.joined(separator: ",") + "]"
        let transport = StubTransport([
            catalogURL(.formula): [catalogResponse(200, formulas, etag: "synthetic-formula-old"),
                catalogResponse(200, kind == .formula ? syntheticFormulaList : formulas, etag: "synthetic-formula-new"), catalogResponse(304)],
            catalogURL(.cask): [catalogResponse(200, casks, etag: "synthetic-cask-old"),
                catalogResponse(200, kind == .cask ? syntheticCaskList : casks, etag: "synthetic-cask-new"), catalogResponse(304)]])
        let client = CatalogClient(transport: transport, cacheDirectory: f.directory)
        _ = try await client.load()
        let before = try Data(contentsOf: f.directory.appendingPathComponent("catalog.json"))
        let result = try await client.load()
        #expect(!result.revalidated)
        #expect(result.catalog.suggestions(prefix: "", limit: 100).count == 12)
        #expect(try Data(contentsOf: f.directory.appendingPathComponent("catalog.json")) == before)
        #expect(try await client.cached()?.suggestions(prefix: "", limit: 100).count == 12)
        _ = try await client.load()
        #expect(await transport.requests.suffix(2).map(\.etag) == ["synthetic-formula-old", "synthetic-cask-old"])
    }
    @Test func decodesListsAndSkipsUnusableItems() async throws {
        let f = WatchFixture(); defer { f.clean() }
        let catalog = try await seedCatalog(f.directory)
        #expect(catalog.listing(for: PackageName("synthetic-formula")!, kind: .formula)?.version == "2")
        #expect(catalog.listing(for: PackageName("synthetic-cask")!, kind: .cask)?.autoUpdates == true)
        #expect(catalog.suggestions(prefix: "").count == 2)
    }
    @Test func suggestions() async throws {
        let f = WatchFixture(); defer { f.clean() }
        let catalog = try await seedCatalog(f.directory)
        #expect(catalog.suggestions(prefix: "synthetic", limit: 1).map(\.name.rawValue) == ["synthetic-cask"])
        #expect(catalog.suggestions(prefix: "cask").isEmpty)
        #expect(catalog.suggestions(prefix: "synthetic-c").map(\.kind) == [.cask])
        #expect(catalog.suggestions(prefix: "", limit: 0).isEmpty)
        #expect(catalog.suggestions(prefix: "", limit: -1).isEmpty)
    }
    @Test func makeTransportTimeout() {
        #expect(CatalogClient.makeTransport().configuration.timeoutIntervalForResource == 120)
        #expect(CatalogClient.makeTransport().configuration.timeoutIntervalForRequest == 10)
    }
    @Test func cachedDoesNotRequest() async throws {
        let f = WatchFixture(); defer { f.clean() }
        _ = try await seedCatalog(f.directory)
        let transport = StubTransport([:])
        let client = CatalogClient(transport: transport, cacheDirectory: f.directory)
        #expect(try await client.cached()?.suggestions(prefix: "").count == 2)
        #expect(await transport.requests.isEmpty)
        for file in try FileManager.default.contentsOfDirectory(at: f.directory, includingPropertiesForKeys: nil) {
            try Data("synthetic corrupt cache".utf8).write(to: file)
        }
        #expect(try await CatalogClient(transport: transport, cacheDirectory: f.directory).cached() == nil)
    }
    @Test func revalidationOutcome() async throws {
        let f = WatchFixture(); defer { f.clean() }
        let initial = try await CatalogClient(transport: catalogStub(), cacheDirectory: f.directory).load()
        #expect(initial.revalidated)
        let transport = StubTransport([catalogURL(.formula): [catalogResponse(304)], catalogURL(.cask): [catalogResponse(304)]])
        let revalidated = try await CatalogClient(transport: transport, cacheDirectory: f.directory).load()
        #expect(revalidated.revalidated && revalidated.catalog.suggestions(prefix: "").count == 2)
        #expect(await transport.requests.map(\.etag) == ["synthetic-formula-tag", "synthetic-cask-tag"])
        let failure = StubTransport([catalogURL(.formula): [catalogResponse(500)]])
        let fallback = try await CatalogClient(transport: failure, cacheDirectory: f.directory).load()
        #expect(!fallback.revalidated && fallback.catalog.suggestions(prefix: "").count == 2)
    }
    @Test func failureWithoutCacheThrows() async {
        let f = WatchFixture(); defer { f.clean() }
        await #expect(throws: (any Error).self) {
            try await CatalogClient(transport: StubTransport([catalogURL(.formula): [catalogResponse(500)]]), cacheDirectory: f.directory).load()
        }
    }
    @Test func notModifiedWithoutCacheRetriesUnconditionally() async throws {
        let f = WatchFixture(); defer { f.clean() }
        let transport = StubTransport([catalogURL(.formula): [catalogResponse(304), catalogResponse(200, syntheticFormulaList)],
                                       catalogURL(.cask): [catalogResponse(304), catalogResponse(200, syntheticCaskList)]])
        #expect(try await CatalogClient(transport: transport, cacheDirectory: f.directory).load().revalidated)
        #expect(await transport.requests.count == 4)
        #expect(await transport.requests.allSatisfy { $0.etag == nil })
    }
    @Test(arguments: ["synthetic invalid JSON", "{}", "[3]"])
    func partialOrInvalidDownloadPreservesCache(_ invalid: String) async throws {
        let f = WatchFixture(); defer { f.clean() }
        _ = try await seedCatalog(f.directory)
        let files = try FileManager.default.contentsOfDirectory(at: f.directory, includingPropertiesForKeys: nil)
        let before = try files.map { try Data(contentsOf: $0) }
        let transport = StubTransport([catalogURL(.formula): [catalogResponse(200, syntheticFormulaList, etag: "synthetic-new")],
                                       catalogURL(.cask): [catalogResponse(200, invalid)]])
        let result = try await CatalogClient(transport: transport, cacheDirectory: f.directory).load()
        #expect(!result.revalidated && result.catalog.suggestions(prefix: "").count == 2)
        #expect(try files.map { try Data(contentsOf: $0) } == before)
    }
}
