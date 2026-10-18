import Foundation
import Testing
@testable import BrewVersionCore

struct CatalogCacheIOTests {
    // Removing preflight admission must fail on bytes read, even though cached() still returns nil.
    @Test(arguments: [0, 1_000_000])
    func rejectsLegacyBeforeReadingPayload(_ paddingCount: Int) async throws {
        let f = WatchFixture(); defer { f.clean() }
        try FileManager.default.createDirectory(at: f.directory, withIntermediateDirectories: true)
        let legacy = ["formula": ["data": Data(repeating: 65, count: paddingCount).base64EncodedString(),
                                  "etag": "synthetic-legacy"],
                      "cask": ["data": Data(syntheticCaskList.utf8).base64EncodedString(),
                               "etag": "synthetic-legacy"]]
        try JSONSerialization.data(withJSONObject: legacy).write(to: f.directory.appendingPathComponent("catalog.json"))
        let reads = CatalogReadCounts()
        let transport = catalogStub()
        let client = CatalogClient(transport: transport, cacheDirectory: f.directory, openCacheFile: reads.open)
        #expect(try await client.cached() == nil)
        #expect(reads.bytes <= 128)
        #expect(reads.wholeReads == 0)
        #expect(reads.closes == 1)
        #expect(try await client.load().revalidated)
        #expect(await transport.requests.allSatisfy { $0.etag == nil })
        #expect(reads.opens == 1)
        let restart = CatalogClient(transport: StubTransport([:]), cacheDirectory: f.directory)
        #expect(try await restart.cached()?.suggestions(prefix: "").count == 2)
    }

    @Test(arguments: ["", "{", #"{"format":"brew-version-catalog-v2","index""#,
                      #"{"format":"synthetic-unknown","index":{}}"#])
    func invalidOrTruncatedPrefixDoesNotReadRemainder(_ invalid: String) async throws {
        let f = WatchFixture(); defer { f.clean() }
        try FileManager.default.createDirectory(at: f.directory, withIntermediateDirectories: true)
        try Data(invalid.utf8).write(to: f.directory.appendingPathComponent("catalog.json"))
        let reads = CatalogReadCounts()
        let client = CatalogClient(transport: StubTransport([:]), cacheDirectory: f.directory, openCacheFile: reads.open)
        #expect(try await client.cached() == nil)
        #expect(reads.bytes <= 128 && reads.wholeReads == 0 && reads.closes == 1)
    }

    @Test func unmarkedSlimCacheRefetchesWithoutReadingItsPayload() async throws {
        let f = WatchFixture(); defer { f.clean() }
        _ = try await seedCatalog(f.directory)
        let file = f.directory.appendingPathComponent("catalog.json")
        let envelope = try #require(JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any])
        #expect(envelope["format"] as? String == "brew-version-catalog-v2")
        try JSONSerialization.data(withJSONObject: #require(envelope["index"])).write(to: file)
        let reads = CatalogReadCounts()
        let transport = catalogStub()
        let client = CatalogClient(transport: transport, cacheDirectory: f.directory, openCacheFile: reads.open)
        #expect(try await client.cached() == nil)
        #expect(reads.bytes <= 128 && reads.wholeReads == 0)
        #expect(try await client.load().revalidated)
        #expect(await transport.requests.allSatisfy { $0.etag == nil })
    }

    @Test func markedCacheHydratesOnceAndReusesTypedListingsAndETags() async throws {
        let f = WatchFixture(); defer { f.clean() }
        _ = try await seedCatalog(f.directory)
        let file = f.directory.appendingPathComponent("catalog.json")
        let byteCount = try Data(contentsOf: file).count
        let reads = CatalogReadCounts()
        let transport = StubTransport([catalogURL(.formula): [catalogResponse(304), catalogResponse(304)],
                                       catalogURL(.cask): [catalogResponse(304), catalogResponse(304)]])
        let client = CatalogClient(transport: transport, cacheDirectory: f.directory, openCacheFile: reads.open)
        #expect(try await client.cached()?.listing(for: PackageName("synthetic-formula")!, kind: .formula)?.version == "2")
        #expect(try await client.cached()?.listing(for: PackageName("synthetic-cask")!, kind: .cask)?.autoUpdates == true)
        #expect(try await client.load().revalidated)
        try Data("synthetic corrupt disk".utf8).write(to: file)
        #expect(try await client.load().catalog.suggestions(prefix: "").count == 2)
        #expect(await transport.requests.map(\.etag) == ["synthetic-formula-tag", "synthetic-cask-tag",
                                                       "synthetic-formula-tag", "synthetic-cask-tag"])
        #expect(reads.opens == 1 && reads.closes == 1 && reads.wholeReads == 1)
        #expect(reads.bytes == byteCount)
    }

    @Test(arguments: ["", "{}", #"{"schema":99,"formula":{},"cask":{}}"#])
    func admittedButInvalidPayloadIsNotAConditionalCache(_ payload: String) async throws {
        let f = WatchFixture(); defer { f.clean() }
        try FileManager.default.createDirectory(at: f.directory, withIntermediateDirectories: true)
        let bytes = Data((#"{"format":"brew-version-catalog-v2","index":"# + payload + "}").utf8)
        try bytes.write(to: f.directory.appendingPathComponent("catalog.json"))
        let transport = catalogStub()
        let client = CatalogClient(transport: transport, cacheDirectory: f.directory)
        #expect(try await client.cached() == nil)
        #expect(try await client.load().revalidated)
        #expect(await transport.requests.allSatisfy { $0.etag == nil })
    }
}

private final class CatalogReadCounts: @unchecked Sendable {
    private let lock = NSLock()
    private var counts = (bytes: 0, whole: 0, opens: 0, closes: 0)
    var bytes: Int { lock.withLock { counts.bytes } }
    var wholeReads: Int { lock.withLock { counts.whole } }
    var opens: Int { lock.withLock { counts.opens } }
    var closes: Int { lock.withLock { counts.closes } }
    func open(_ url: URL) throws -> any CatalogCacheInput {
        let handle = try FileHandle(forReadingFrom: url)
        lock.withLock { counts.opens += 1 }
        return CountingCatalogInput(handle: handle, counts: self)
    }
    func record(_ data: Data?, whole: Bool) {
        lock.withLock {
            counts.bytes += data?.count ?? 0
            if whole { counts.whole += 1 }
        }
    }
    func closed() { lock.withLock { counts.closes += 1 } }
}

private final class CountingCatalogInput: CatalogCacheInput, @unchecked Sendable {
    let handle: FileHandle
    let counts: CatalogReadCounts
    init(handle: FileHandle, counts: CatalogReadCounts) { self.handle = handle; self.counts = counts }
    func read(upToCount count: Int) throws -> Data? {
        let data = try handle.read(upToCount: count)
        counts.record(data, whole: false)
        return data
    }
    func readToEnd() throws -> Data? {
        let data = try handle.readToEnd()
        counts.record(data, whole: true)
        return data
    }
    func close() throws { try handle.close(); counts.closed() }
}
