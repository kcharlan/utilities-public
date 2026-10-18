import Foundation
import Testing
@testable import BrewVersionCore

struct TapClientTests {
    let name = PackageName("synthetic-owner/synthetic-tap/synthetic-tool")!
    let url = URL(string: "https://raw.githubusercontent.com/synthetic-owner/homebrew-synthetic-tap/HEAD/Formula/synthetic-tool.rb")!
    func entry(path: String = "Formula/synthetic-tool.rb", repository: GitHubRepository? = .init(owner: "synthetic-owner", repo: "homebrew-synthetic-tap")) -> TapEntry {
        TapEntry(name: name, kind: .formula, path: path, repository: repository)
    }
    func response(_ status: Int, _ body: String = "version \"4.5.6\"", etag: String? = nil) -> Result<HTTPResponse, URLError> {
        .success(HTTPResponse(status: status, body: Data(body.utf8), etag: etag))
    }

    @Test func requestsRemoteRepositoryPath() async throws {
        let transport = StubTransport([url: [response(200)]])
        let listing = try await TapClient(transport: transport).lookup(entry())
        #expect(listing.name == name)
        #expect(listing.version == "4.5.6")
        #expect(await transport.requests == [.init(url: url, etag: nil)])
    }

    @Test func encodesEachURLComponent() async throws {
        let encoded = URL(string: "https://raw.githubusercontent.com/synthetic%20owner/homebrew-synthetic%25tap/HEAD/Formula/synthetic%20folder/synthetic%23tool%3F%25.rb")!
        let transport = StubTransport([encoded: [response(200)]])
        _ = try await TapClient(transport: transport).lookup(entry(path: "Formula/synthetic folder/synthetic#tool?%.rb", repository: .init(owner: "synthetic owner", repo: "homebrew-synthetic%tap")))
        #expect(await transport.requests.map(\.url.absoluteString) == [encoded.absoluteString])
    }

    @Test func etagRoundTrip() async throws {
        let transport = StubTransport([url: [response(200, etag: "synthetic-etag"), response(304)]])
        let cache = ListingCache(), client = TapClient(transport: transport, cache: cache)
        let first = try await client.lookup(entry())
        #expect(try await client.lookup(entry()) == first)
        #expect(await transport.requests == [.init(url: url, etag: nil), .init(url: url, etag: "synthetic-etag")])
        #expect(cache.snapshot()[url] == CachedListing(etag: "synthetic-etag", listing: first))
    }

    @Test func sharedRemoteAliasesDoNotReuseAnotherIdentity() async throws {
        let alias = PackageName("synthetic-other/synthetic-tap/synthetic-tool")!
        let transport = StubTransport([url: [response(200, etag: "synthetic-first"), response(200, "version \"7.8\"", etag: "synthetic-second")]])
        let client = TapClient(transport: transport, cache: ListingCache())
        _ = try await client.lookup(entry())
        let listing = try await client.lookup(TapEntry(name: alias, kind: .formula, path: entry().path, repository: entry().repository))
        #expect(listing.name == alias)
        #expect(listing.version == "7.8")
        #expect(await transport.requests == [.init(url: url, etag: nil), .init(url: url, etag: nil)])
    }

    @Test func mismatchedCachedIdentityOrKindCannotSatisfy304() async {
        let alias = PackageName("synthetic-other/synthetic-tap/synthetic-tool")!
        for listing in [Listing(name: alias, kind: .formula, version: "4.5.6"),
                        Listing(name: name, kind: .cask, version: "4.5.6")] {
            let cache = ListingCache(entries: [url: CachedListing(etag: "synthetic-wrong", listing: listing)])
            let transport = StubTransport([url: [response(304)]])
            await #expect(throws: LookupError.tapHTTP(status: 304, name)) {
                try await TapClient(transport: transport, cache: cache).lookup(entry())
            }
            #expect(await transport.requests == [.init(url: url, etag: nil)])
        }
    }

    @Test func errorMapping() async {
        let cases: [(Result<HTTPResponse, URLError>, LookupError)] = [
            (response(200, "version ENV[\"SYNTHETIC_VERSION\"]"), .unreadableTapVersion(name)),
            (.success(HTTPResponse(status: 200, body: Data([0xff]))), .unreadableTapVersion(name)),
            (response(304), .tapHTTP(status: 304, name)),
            (response(404), .notFoundInTap(name)),
            (.failure(URLError(.cannotConnectToHost)), .tapUnreachable(name))
        ] + [300, 301, 302, 303, 305, 307, 308, 399].map { (response($0), .tapUnreachable(name)) }
          + [201, 204, 400, 401, 403, 429, 500, 503].map { (response($0), .tapHTTP(status: $0, name)) }
        for (response, expected) in cases {
            let transport = StubTransport([url: [response]])
            await #expect(throws: expected) { try await TapClient(transport: transport).lookup(entry()) }
        }
        let transport = StubTransport([:])
        await #expect(throws: LookupError.unsupportedTapRemote(name.tap!)) {
            try await TapClient(transport: transport).lookup(entry(repository: nil))
        }
        #expect(await transport.requests.isEmpty)
    }
}
