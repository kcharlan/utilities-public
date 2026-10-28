import Foundation
import Testing
@testable import BrewVersionCore

private final class ResolverFixture {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent("brew-version-synthetic-resolver-\(UUID().uuidString)")
    init(_ packages: [(String, PackageKind)]) throws {
        for (full, kind) in packages {
            let parts = full.split(separator: "/")
            let tap = root.appendingPathComponent("Library/Taps/\(parts[0])/\(parts[1])")
            let config = tap.appendingPathComponent(".git/config")
            try FileManager.default.createDirectory(at: config.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data("[remote \"origin\"]\n url = https://github.com/\(parts[0])/homebrew-\(parts[1]).git\n".utf8).write(to: config)
            let file = tap.appendingPathComponent("\(kind == .formula ? "Formula" : "Casks")/\(parts[2]).rb")
            try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data("# synthetic fixture".utf8).write(to: file)
        }
    }
    deinit { try? FileManager.default.removeItem(at: root) }
    var index: TapIndex { TapIndex.scan(prefixes: [HomebrewPrefix(root: root)]) }
}

struct PackageResolverTests {
    let bare = PackageName("synthetic-tool")!
    let full = PackageName("synthetic-owner/synthetic-tap/synthetic-tool")!
    func resolver(_ transport: any HTTPTransport, _ index: TapIndex) -> PackageResolver {
        PackageResolver(client: HomebrewClient(transport: transport), tapClient: TapClient(transport: transport), taps: index)
    }
    func rawURL(_ name: PackageName, _ kind: PackageKind = .formula) -> URL {
        let tap = name.tap!
        return URL(string: "https://raw.githubusercontent.com/\(tap.user)/homebrew-\(tap.repo)/HEAD/\(kind == .formula ? "Formula" : "Casks")/\(name.shortName).rb")!
    }
    var missing: Result<HTTPResponse, URLError> { .success(.init(status: 404, body: Data())) }
    var tapResponse: Result<HTTPResponse, URLError> { .success(.init(status: 200, body: Data("version \"4.5.6\"".utf8))) }

    @Test func bareNamePrefersOfficialThenUniqueTap() async throws {
        let shared = PackageName("synthetic-shared")!
        let f = try ResolverFixture([(full.rawValue, .formula), ("synthetic-owner/synthetic-tap/synthetic-shared", .formula)])
        let transport = StubTransport([watchURL(shared): [watchResponse("9.0.1")], watchURL(bare): [missing], watchURL(bare, kind: .cask): [missing], rawURL(full): [tapResponse]])
        let r = resolver(transport, f.index)
        #expect(try await r.resolveBare(shared, kinds: .auto).name == shared)
        #expect(try await r.resolveBare(bare, kinds: .auto).name == full)
        #expect(await transport.requests.map(\.url) == [watchURL(shared), watchURL(bare), watchURL(bare, kind: .cask), rawURL(full)])
    }

    @Test func ambiguousAcrossTaps() async throws {
        let other = PackageName("synthetic-other/synthetic-tap/synthetic-tool")!
        let f = try ResolverFixture([(full.rawValue, .formula), (other.rawValue, .formula)])
        let transport = StubTransport([watchURL(bare): [missing], watchURL(bare, kind: .cask): [missing]])
        await #expect(throws: LookupError.ambiguous(bare.shortName, [other, full])) {
            try await resolver(transport, f.index).resolveBare(bare, kinds: .auto)
        }
        #expect(await transport.requests.count == 2)
    }

    @Test func fullNameRequiresTappedTap() async {
        let transport = StubTransport([:])
        await #expect(throws: LookupError.notTapped(full.tap!)) {
            try await resolver(transport, .empty).lookup(full, kinds: .auto)
        }
        #expect(await transport.requests.isEmpty)
    }

    @Test func kindPreferenceFiltersTaps() async throws {
        let f = try ResolverFixture([(full.rawValue, .formula)])
        let transport = StubTransport([watchURL(bare, kind: .cask): [missing]])
        let r = resolver(transport, f.index)
        #expect(r.tapMatches(bare, kinds: .cask).isEmpty)
        #expect(r.tapMatches(bare, kinds: .formula).map(\.name) == [full])
        await #expect(throws: LookupError.notFoundInTap(full)) { try await r.lookup(full, kinds: .cask) }
        await #expect(throws: LookupError.notFound(bare, .cask)) { try await r.resolveBare(bare, kinds: .cask) }
        let absent = PackageName("synthetic-owner/synthetic-tap/synthetic-absent")!
        await #expect(throws: LookupError.notFoundInTap(absent)) { try await r.lookup(absent, kinds: .auto) }
        #expect(await transport.requests.map(\.url) == [watchURL(bare, kind: .cask)])
    }

    @Test func sameTapKindsAreNotAmbiguous() async throws {
        let f = try ResolverFixture([(full.rawValue, .formula), (full.rawValue, .cask)])
        let transport = StubTransport([watchURL(bare): [missing], watchURL(bare, kind: .cask): [missing, missing], rawURL(full): [tapResponse], rawURL(full, .cask): [tapResponse]])
        let r = resolver(transport, f.index)
        #expect(try await r.resolveBare(bare, kinds: .auto).kind == .formula)
        #expect(try await r.resolveBare(bare, kinds: .cask).kind == .cask)
        let other = PackageName("synthetic-other/synthetic-tap/synthetic-tool")!
        let multiple = try ResolverFixture([(full.rawValue, .formula), (full.rawValue, .cask), (other.rawValue, .formula)])
        let missingTransport = StubTransport([watchURL(bare): [missing], watchURL(bare, kind: .cask): [missing]])
        await #expect(throws: LookupError.ambiguous(bare.shortName, [other, full])) {
            try await resolver(missingTransport, multiple.index).resolveBare(bare, kinds: .auto)
        }
    }

    @Test func lookupNeverFallsBack() async throws {
        let f = try ResolverFixture([(full.rawValue, .formula)])
        let transport = StubTransport([watchURL(bare): [missing], watchURL(bare, kind: .cask): [missing]])
        await #expect(throws: LookupError.notFound(bare, .auto)) { try await resolver(transport, f.index).lookup(bare, kinds: .auto) }
        #expect(await transport.requests.count == 2)
    }

    @Test func officialErrorsNeverFallBack() async throws {
        let f = try ResolverFixture([(full.rawValue, .formula)])
        let failures: [(Result<HTTPResponse, URLError>, LookupError)] = [
            (.failure(URLError(.timedOut)), .unreachable(bare)),
            (.success(.init(status: 503, body: Data())), .http(status: 503, bare)),
            (.success(.init(status: 200, body: Data("{}".utf8))), .invalidVersion(.formula, bare))
        ]
        for (response, error) in failures {
            let transport = StubTransport([watchURL(bare): [response]])
            await #expect(throws: error) { try await resolver(transport, f.index).resolveBare(bare, kinds: .auto) }
            #expect(await transport.requests.count == 1)
        }
    }

    @Test func canonicalFullNameIsPreserved() async throws {
        let f = try ResolverFixture([("synthetic-owner/homebrew-homebrew-synthetic-tap/synthetic-tool", .formula)])
        let entry = try #require(f.index.entries(shortName: bare.shortName, kinds: .auto).first)
        #expect(entry.name.rawValue == "synthetic-owner/homebrew-synthetic-tap/synthetic-tool")
        let url = URL(string: "https://raw.githubusercontent.com/synthetic-owner/homebrew-homebrew-homebrew-synthetic-tap/HEAD/Formula/synthetic-tool.rb")!
        let transport = StubTransport([watchURL(bare): [missing], watchURL(bare, kind: .cask): [missing], url: [tapResponse, tapResponse]])
        let r = resolver(transport, f.index)
        #expect(try await r.resolveBare(bare, kinds: .auto).name == entry.name)
        #expect(try await r.lookup(entry.name, kinds: .auto).name == entry.name)
    }

    @Test func schedulerBoundsTapLookups() async throws {
        let transport = HeldTapTransport(), scheduler = LookupScheduler()
        let client = TapClient(transport: transport)
        let tasks = (0..<8).map { index in
            Task { try await scheduler.run {
                try await client.lookup(TapEntry(name: PackageName("synthetic-owner/synthetic-tap/synthetic-tool-\(index)")!, kind: .formula, path: "Formula/synthetic-tool-\(index).rb", repository: .init(owner: "synthetic-owner", repo: "homebrew-synthetic-tap")))
            } }
        }
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while await transport.started < 4, ContinuousClock.now < deadline { await Task.yield() }
        #expect(await transport.started == 4)
        for _ in 0..<100 { await Task.yield() }
        #expect(await transport.started == 4)
        await transport.release()
        for task in tasks { _ = try await task.value }
        #expect(await transport.started == 8)
        #expect(await transport.peak == 4)
        #expect(try await scheduler.run { 42 } == 42)
    }
}

private actor HeldTapTransport: HTTPTransport {
    var started = 0, active = 0, peak = 0
    var held: [CheckedContinuation<Void, Never>] = []
    var released = false
    func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse {
        started += 1; active += 1; peak = max(peak, active)
        if !released { await withCheckedContinuation { held.append($0) } }
        active -= 1
        return HTTPResponse(status: 200, body: Data("version \"4.5.6\"".utf8))
    }
    func release() {
        released = true
        let waiting = held; held.removeAll()
        for continuation in waiting { continuation.resume() }
    }
}
