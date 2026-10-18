import Foundation
import Testing
@testable import BrewVersionCore

struct TapNameTests {
    @Test func acceptsShortAndFullNames() throws {
        let short = try #require(PackageName("synthetic-tool"))
        #expect(short.tap == nil)
        #expect(short.shortName == "synthetic-tool")
        for raw in ["synthetic-owner/synthetic-tap/synthetic-tool",
                    "synthetic-owner/homebrew-synthetic-tap/synthetic-tool",
                    "Synthetic-Owner/synthetic-tap/synthetic-tool"] {
            let name = try #require(PackageName(raw))
            #expect(name.tap?.description == "synthetic-owner/synthetic-tap")
            #expect(name.shortName == "synthetic-tool")
            #expect(name.rawValue == "synthetic-owner/synthetic-tap/synthetic-tool")
            #expect(try JSONDecoder().decode(PackageName.self, from: JSONEncoder().encode(name)) == name)
        }
    }

    @Test func normalizesTapAliases() throws {
        let cases: [(String, String, Bool)] = [
            ("synthetic-owner/homebrew-synthetic-tap", "synthetic-owner/synthetic-tap", false),
            ("synthetic-owner/linuxbrew-synthetic-tap", "synthetic-owner/synthetic-tap", false),
            ("Synthetic-Owner/synthetic-tap", "synthetic-owner/synthetic-tap", false),
            ("homebrew/core", "homebrew/core", true),
            ("Homebrew/homebrew-core", "homebrew/core", true),
            ("homebrew/homebrew", "homebrew/core", true),
            ("linuxbrew/core", "homebrew/core", true),
            ("Linuxbrew/linuxbrew-homebrew", "homebrew/core", true),
            ("homebrew/cask", "homebrew/cask", true),
            ("Homebrew/homebrew-cask", "homebrew/cask", true),
            ("HOMEBREW/HOMEBREW-CORE", "homebrew/core", true),
            ("LINUXBREW/LINUXBREW-HOMEBREW", "homebrew/core", true),
            ("HOMEBREW/HOMEBREW-CASK", "homebrew/cask", true),
            ("linuxbrew/cask", "linuxbrew/cask", false),
            ("homebrew/cask-synthetic", "homebrew/cask-synthetic", false)
        ]
        for (raw, canonical, official) in cases {
            let tap = try #require(TapName(raw))
            #expect(tap.description == canonical)
            #expect(tap.isOfficial == official)
            #expect(try JSONDecoder().decode(TapName.self, from: JSONEncoder().encode(tap)) == tap)
        }
    }

    @Test func rejectsMalformed() {
        for raw in ["a/b", "a/b/c/d", "/a/b", "a/b/", "homebrew/core/x",
                    "homebrew/homebrew-cask/x", "a b/c/d", "a/b/Synthetic", "a/b/@x",
                    "a+/b/x", "a/b+/x", "a/.b/x", "a/homebrew-/x"] {
            #expect(PackageName(raw) == nil)
        }
        for raw in ["", "a", "a/b/c", "/b", "a/", "a b/c", "a/b+", "a/.b"] {
            #expect(TapName(raw) == nil)
        }
    }

    @Test func acceptsOtherHomebrewTaps() {
        #expect(PackageName("homebrew/synthetic-extra/x")?.tap?.isOfficial == false)
    }

    @Test func loads102State() throws {
        let fixture = try #require(Bundle.module.url(forResource: "state-1.0.2", withExtension: "json", subdirectory: "Fixtures"))
        let f = WatchFixture(); defer { f.clean() }
        try FileManager.default.createDirectory(at: f.directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try FileManager.default.copyItem(at: fixture, to: f.file)
        let loaded = f.store.load()
        #expect(loaded.problem == nil && loaded.canSave)
        #expect(loaded.state.watched.map(\.name.rawValue) == ["synthetic-tool"])
        #expect(loaded.state.watched.first?.name.tap == nil)
    }

    @Test func tapEntriesSaveUnderSeparateKeys() throws {
        let official = WatchEntry(name: PackageName("synthetic-tool")!)
        let officialSecond = WatchEntry(name: PackageName("synthetic-shared")!)
        let tap = WatchEntry(name: PackageName("synthetic-owner/synthetic-tap/synthetic-tool")!)
        let tapSecond = WatchEntry(name: PackageName("synthetic-owner/synthetic-tap/synthetic-app")!)
        var state = AppState.initial
        state.watched = [tap, official, tapSecond, officialSecond]
        let officialURL = URL(string: "https://formulae.brew.sh/api/formula/synthetic-tool.json")!
        let tapURL = URL(string: "https://raw.githubusercontent.com/synthetic-owner/homebrew-synthetic-tap/HEAD/Formula/synthetic-tool.rb")!
        state.listingCache = [
            officialURL: CachedListing(etag: "synthetic-official", listing: Listing(name: official.name, kind: .formula, version: "4.5.6")),
            tapURL: CachedListing(etag: "synthetic-tap", listing: Listing(name: tap.name, kind: .formula, version: "9.0.1"))
        ]
        let data = try JSONEncoder().encode(state)
        let object = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let watches = try #require(object["watched"] as? [[String: Any]])
        #expect(watches.compactMap { $0["name"] as? String } == ["synthetic-tool", "synthetic-shared"])
        let tapWatches = try #require(object["tapWatched"] as? [[String: Any]])
        #expect(tapWatches.compactMap { $0["name"] as? String } == ["synthetic-owner/synthetic-tap/synthetic-tool", "synthetic-owner/synthetic-tap/synthetic-app"])
        let officialCache = try JSONSerialization.data(withJSONObject: #require(object["listingCache"]))
        #expect(try JSONDecoder().decode([URL: CachedListing].self, from: officialCache) == [officialURL: state.listingCache[officialURL]!])
        let tapCache = try JSONSerialization.data(withJSONObject: #require(object["tapListingCache"]))
        #expect(try JSONDecoder().decode([URL: CachedListing].self, from: tapCache) == [tapURL: state.listingCache[tapURL]!])
        let decoded = try JSONDecoder().decode(AppState.self, from: data)
        #expect(decoded.watched == [official, officialSecond, tap, tapSecond])
        #expect(decoded.listingCache == state.listingCache)
        // 1.0.2 ignores these unknown keys, so its remaining input is all official.
        var rollback = object
        rollback.removeValue(forKey: "tapWatched")
        rollback.removeValue(forKey: "tapListingCache")
        let rolledBack = try JSONDecoder().decode(AppState.self, from: JSONSerialization.data(withJSONObject: rollback))
        #expect(rolledBack.watched == [official, officialSecond])
        #expect(rolledBack.listingCache == [officialURL: state.listingCache[officialURL]!])
    }

    @Test func tapErrorsUseCopy() {
        let tap = TapName("synthetic-owner/synthetic-tap")!
        let full = PackageName("synthetic-owner/synthetic-tap/synthetic-tool")!
        let cases: [(LookupError, String, String)] = [
            (.notTapped(tap), "Error: synthetic-owner/synthetic-tap is not tapped.", "synthetic-owner/synthetic-tap is no longer tapped."),
            (.unsupportedTapRemote(tap), "Error: synthetic-owner/synthetic-tap is not hosted on GitHub.", "Only taps hosted on GitHub can be checked."),
            (.notFoundInTap(full), "Error: synthetic-owner/synthetic-tap/synthetic-tool not found in synthetic-owner/synthetic-tap.", "Not found in synthetic-owner/synthetic-tap."),
            (.unreadableTapVersion(full), "Error: could not read a version for synthetic-owner/synthetic-tap/synthetic-tool.", "Can't read this tap's version."),
            (.tapUnreachable(full), "Error: could not reach GitHub for synthetic-owner/synthetic-tap/synthetic-tool.", "Couldn't reach GitHub."),
            (.tapHTTP(status: 503, full), "Error: GitHub returned HTTP 503 for synthetic-owner/synthetic-tap/synthetic-tool.", "GitHub returned HTTP 503.")
        ]
        for (error, cli, row) in cases {
            #expect(error.cliMessage == cli)
            #expect(error.rowMessage == row)
        }
        let other = PackageName("synthetic-owner/synthetic-other/synthetic-tool")!
        #expect(LookupError.ambiguous("synthetic-tool", [full, other]).cliMessage == "Error: synthetic-tool matches several taps: synthetic-owner/synthetic-other/synthetic-tool, synthetic-owner/synthetic-tap/synthetic-tool. Use the full name.")
        #expect(LookupError.ambiguous("synthetic-tool", [full, other]).rowMessage == "synthetic-tool matches several taps. Use the full name.")
    }

    @Test func officialClientRefusesTapNames() async throws {
        let full = try #require(PackageName("synthetic-owner/synthetic-tap/synthetic-tool"))
        let transport = StubTransport([:])
        do {
            _ = try await HomebrewClient(transport: transport).lookup(full, kinds: .auto)
            Issue.record("Expected notFound")
        } catch {
            #expect(error as? LookupError == .notFound(full, .auto))
        }
        #expect(await transport.requests.isEmpty)
    }
}
