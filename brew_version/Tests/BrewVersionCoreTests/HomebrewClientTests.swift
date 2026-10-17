import Foundation
import Testing
@testable import BrewVersionCore

actor StubTransport: HTTPTransport {
    struct Request: Equatable { let url: URL; let etag: String? }
    var responses: [URL: [Result<HTTPResponse, URLError>]]
    var requests: [Request] = []
    init(_ responses: [URL: [Result<HTTPResponse, URLError>]]) { self.responses = responses }
    func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse {
        requests.append(Request(url: url, etag: ifNoneMatch))
        guard var queue = responses[url], !queue.isEmpty else { throw URLError(.badURL) }
        let next = queue.removeFirst()
        responses[url] = queue
        return try next.get()
    }
}

struct HomebrewClientTests {
    let name = PackageName("synthetic-formula")!
    func url(_ kind: PackageKind, _ name: String = "synthetic-formula") -> URL {
        URL(string: "https://formulae.brew.sh/api/\(kind.rawValue)/\(name).json")!
    }
    func response(_ status: Int, _ body: String = "", etag: String? = nil) -> Result<HTTPResponse, URLError> {
        .success(HTTPResponse(status: status, body: Data(body.utf8), etag: etag))
    }

    @Test func concurrentStoresAndImmediateSnapshotsRetainEveryEntry() async {
        let cache = ListingCache()
        await withTaskGroup(of: Void.self) { group in
            for worker in 0..<4 {
                group.addTask {
                    for index in 0..<40 {
                        let name = PackageName("synthetic-cache-\(worker)-\(index)")!
                        let url = watchURL(name)
                        await cache.store(CachedListing(etag: name.rawValue,
                            listing: Listing(name: name, kind: .formula, version: "1")), for: url)
                        let snapshot = cache.snapshot()
                        #expect(snapshot[url]?.listing.name == name)
                        #expect(snapshot.values.allSatisfy { $0.etag == $0.listing.name.rawValue })
                    }
                }
            }
        }
        let before = cache.snapshot()
        #expect(before.count == 160)
        let name = PackageName("synthetic-cache-0-0")!
        await cache.store(CachedListing(etag: "synthetic-replacement",
            listing: Listing(name: name, kind: .formula, version: "2")), for: watchURL(name))
        #expect(before[watchURL(name)]?.listing.version == "1")
        #expect(cache.snapshot()[watchURL(name)]?.listing.version == "2")
    }

    @Test func formulaFound() async throws {
        let stub = StubTransport([url(.formula): [response(200, #"{"versions":{"stable":"1.2"},"revision":3}"#)]])
        let listing = try await HomebrewClient(transport: stub).lookup(name, kinds: .auto)
        #expect(listing.name == name)
        #expect(listing.kind == .formula)
        #expect(listing.version == "1.2")
        #expect(listing.revision == 3)
        #expect(await stub.requests == [.init(url: url(.formula), etag: nil)])
    }

    @Test func fallsBackToCask() async throws {
        let stub = StubTransport([url(.formula): [response(404)], url(.cask): [response(200, #"{"version":"2"}"#)]])
        let listing = try await HomebrewClient(transport: stub).lookup(name, kinds: .auto)
        #expect(listing.name == name)
        #expect(listing.kind == .cask)
        #expect(listing.version == "2")
        #expect(await stub.requests.map(\.url) == [url(.formula), url(.cask)])
    }

    @Test func caskOnlySkipsFormula() async throws {
        let stub = StubTransport([url(.cask): [response(200, #"{"version":"2"}"#)]])
        #expect(try await HomebrewClient(transport: stub).lookup(name, kinds: .cask).kind == .cask)
        #expect(await stub.requests.map(\.url) == [url(.cask)])
    }

    @Test func notFoundBoth() async {
        let missing = PackageName("synthetic-missing")!
        let stub = StubTransport([url(.formula, missing.rawValue): [response(404)], url(.cask, missing.rawValue): [response(404)]])
        await checkError(stub, name: missing, kinds: .auto, expected: .notFound(missing, .auto), cli: "Error: synthetic-missing not found in Homebrew (formula cask).", row: "Not found in Homebrew.")
    }

    @Test func httpErrorStops() async {
        let cask = PackageName("synthetic-cask")!
        let stub = StubTransport([url(.formula, cask.rawValue): [response(404)], url(.cask, cask.rawValue): [response(503)]])
        await checkError(stub, name: cask, kinds: .auto, expected: .http(status: 503, cask), cli: "Error: Homebrew returned HTTP 503 for synthetic-cask.", row: "Homebrew returned HTTP 503.")
        #expect(await stub.requests.map(\.url) == [url(.formula, cask.rawValue), url(.cask, cask.rawValue)])
        let stopped = StubTransport([url(.formula): [response(503)]])
        await checkError(stopped, expected: .http(status: 503, name), cli: "Error: Homebrew returned HTTP 503 for synthetic-formula.", row: "Homebrew returned HTTP 503.")
        #expect(await stopped.requests.count == 1)
    }

    @Test func unreachable() async {
        await checkError(StubTransport([url(.formula): [.failure(URLError(.cannotConnectToHost))]]), expected: .unreachable(name), cli: "Error: could not reach Homebrew for synthetic-formula.", row: "Couldn't reach Homebrew.")
    }

    @Test(arguments: [300, 301, 302, 303, 305, 307, 308, 399]) func refusedRedirectIsUnreachable(_ status: Int) async {
        await checkError(StubTransport([url(.formula): [response(status)]]), expected: .unreachable(name), cli: "Error: could not reach Homebrew for synthetic-formula.", row: "Couldn't reach Homebrew.")
    }

    @Test(arguments: [#"{"versions":{"stable":""}}"#, #"{"versions":{"stable":null}}"#, #"{"versions":{"stable":3}}"#, "not json"])
    func invalidVersion(_ body: String) async {
        await checkError(StubTransport([url(.formula): [response(200, body)]]), expected: .invalidVersion(.formula, name), cli: "Error: no valid formula version returned for synthetic-formula.", row: "Homebrew returned no usable version.")
    }

    @Test func etagRoundTrip() async throws {
        let stub = StubTransport([url(.formula): [response(200, #"{"versions":{"stable":"1.2"}}"#, etag: "synthetic-etag"), response(304)]])
        let cache = ListingCache()
        let client = HomebrewClient(transport: stub, cache: cache)
        let first = try await client.lookup(name, kinds: .auto)
        let second = try await client.lookup(name, kinds: .auto)
        #expect(first.version == "1.2")
        #expect(second == first)
        #expect(await stub.requests == [.init(url: url(.formula), etag: nil), .init(url: url(.formula), etag: "synthetic-etag")])
        #expect(cache.snapshot()[url(.formula)] == CachedListing(etag: "synthetic-etag", listing: first))
    }

    @Test func notModifiedWithoutCacheIsError() async {
        await checkError(StubTransport([url(.formula): [response(304)]]), expected: .http(status: 304, name), cli: "Error: Homebrew returned HTTP 304 for synthetic-formula.", row: "Homebrew returned HTTP 304.")
    }

    private func checkError(_ stub: StubTransport, name suppliedName: PackageName? = nil, kinds: KindPreference = .auto, expected: LookupError, cli: String, row: String) async {
        do {
            _ = try await HomebrewClient(transport: stub).lookup(suppliedName ?? name, kinds: kinds)
            Issue.record("Expected lookup to fail")
        } catch let error as LookupError {
            #expect(error == expected)
            #expect(error.cliMessage == cli)
            #expect(error.rowMessage == row)
        } catch { Issue.record("Unexpected error: \(error)") }
    }
}
