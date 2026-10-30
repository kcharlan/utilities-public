import Foundation
import Testing
@testable import BrewVersionCore

let watchName = PackageName("synthetic-watch")!
func watchListing(_ version: String = "2.0", revision: Int = 0, kind: PackageKind = .formula) -> Listing {
    Listing(name: watchName, kind: kind, version: version, revision: revision)
}
func baseline(_ listing: Listing = watchListing("1.0"), installed: InstalledVersion? = nil) -> WatchEntry {
    evaluate(WatchEntry(name: listing.name), listing: listing, installed: installed).0
}

struct EvaluateTests {
    let old = InstalledVersion(version: "0.5", source: .cellar)
    @Test func digestOrdersNewestFirstThenByName() throws {
        let older = Date(timeIntervalSince1970: 100), newer = Date(timeIntervalSince1970: 200)
        let digest = try #require(alertDigest(for: [pending("synthetic-a", "1.0", older),
                                                    pending("synthetic-c", "3.0", newer),
                                                    pending("synthetic-b", "2.0", newer)]))
        #expect(digest.names.map(\.rawValue) == ["synthetic-b", "synthetic-c", "synthetic-a"])
        #expect(digest.title == "3 updates on Homebrew")
        #expect(digest.body == "synthetic-b 2.0, synthetic-c 3.0, synthetic-a 1.0")
    }
    @Test func singleDigestKeepsTheIndividualAlertText() throws {
        let digest = try #require(alertDigest(for: [pending("synthetic-a", "2.0", Date(timeIntervalSince1970: 1))]))
        #expect(digest.title == "synthetic-a 2.0 is on Homebrew")
        #expect(digest.body == "You have 0.5.")
    }
    @Test func digestSkipsEntriesThatAreNoLongerAmberOrNotPending() {
        var skipped = pending("synthetic-a", "2.0", Date(timeIntervalSince1970: 1))
        skipped.skippedRelease = skipped.lastListing.map(ReleaseID.init)
        var told = pending("synthetic-b", "2.0", Date(timeIntervalSince1970: 1))
        told.alertPendingSince = nil
        #expect(alertDigest(for: [skipped, told]) == nil)
    }
    @Test func tapDigestUsesShortNames() throws {
        let since = Date(timeIntervalSince1970: 1)
        let digest = try #require(alertDigest(for: [
            pending("synthetic-owner/synthetic-tap/synthetic-tool", "7.8", since),
            pending("synthetic-a", "2.0", since)
        ]))
        #expect(digest.body == "synthetic-a 2.0, synthetic-tool 7.8")
    }
    func pending(_ name: String, _ version: String, _ since: Date) -> WatchEntry {
        let listing = Listing(name: PackageName(name)!, kind: .formula, version: version)
        return WatchEntry(name: listing.name, kind: .formula, lastListing: listing,
                          installed: InstalledVersion(version: "0.5", source: .cellar),
                          alertPendingSince: since)
    }
    @Test func transitions() {
        let v = watchListing()
        let (added, noNotice) = evaluate(WatchEntry(name: watchName), listing: v, installed: old)
        #expect(noNotice == nil && added.isAmber && !added.unseenRelease)
        #expect(added.lastSeenRelease == ReleaseID(v) && added.notifiedRelease == ReleaseID(v))
        var entry = baseline()
        entry.lastError = "Synthetic previous error"
        let (updated, notice) = evaluate(entry, listing: v, installed: old)
        #expect(updated.lastListing == v && updated.installed == old && updated.kind == .formula && updated.lastError == nil)
        #expect(updated.isAmber && updated.notifiedRelease == ReleaseID(v))
        #expect(notice == Notice(name: watchName, title: "synthetic-watch 2.0 is on Homebrew", body: "You have 0.5."))
        #expect(evaluate(updated, listing: v, installed: old).1 == nil)
        var skipped = updated
        skipped.skippedRelease = ReleaseID(v)
        skipped.unseenRelease = true
        let skippedResult = evaluate(skipped, listing: v, installed: nil)
        #expect(!skippedResult.0.isAmber && !skippedResult.0.unseenRelease && skippedResult.1 == nil)
        for version in ["2.0", "3.0"] {
            let result = evaluate(entry, listing: v, installed: InstalledVersion(version: version, source: .cellar))
            #expect(!result.0.isAmber && result.1 == nil && !result.0.unseenRelease)
        }
        for installed in [nil, old] {
            let result = evaluate(entry, listing: watchListing("latest", kind: .cask), installed: installed)
            #expect(!result.0.isAmber && result.1 == nil && !result.0.unseenRelease)
        }
    }
    @Test func notInstalledPollsUntilAcknowledged() throws {
        var entry = baseline()
        #expect(!entry.isAmber)
        let result = evaluate(entry, listing: watchListing(), installed: nil)
        entry = result.0
        #expect(result.1?.body == "Was 1.0." && entry.isAmber && entry.unseenRelease)
        for _ in 0..<3 {
            let poll = evaluate(entry, listing: watchListing(), installed: nil)
            #expect(poll.1 == nil && poll.0.isAmber)
            entry = poll.0
        }
        entry = try JSONDecoder().decode(WatchEntry.self, from: JSONEncoder().encode(entry))
        #expect(evaluate(entry, listing: watchListing(), installed: nil).0.isAmber)
        entry.lastSeenRelease = ReleaseID(watchListing())
        entry.unseenRelease = false
        let acknowledged = evaluate(entry, listing: watchListing(), installed: nil)
        #expect(!acknowledged.0.isAmber && acknowledged.1 == nil)
    }
    @Test func formulaRevisionIdentity() {
        var entry = baseline(watchListing("2.0", revision: 1), installed: old)
        for revision in [2,3] {
            let result = evaluate(entry, listing: watchListing("2.0", revision: revision), installed: old)
            #expect(result.1?.title == "synthetic-watch 2.0_\(revision) is on Homebrew")
            #expect(result.0.isAmber)
            entry = result.0
        }
        #expect(evaluate(entry, listing: watchListing("2.0", revision: 3), installed: old).1 == nil)
        entry.skippedRelease = ReleaseID(watchListing("2.0", revision: 3))
        #expect(!evaluate(entry, listing: watchListing("2.0", revision: 3), installed: old).0.isAmber)
        #expect(ReleaseID(watchListing("2,synthetic", revision: 5, kind: .cask)).revision == 0)
        #expect(ReleaseID(watchListing("2,synthetic", kind: .cask)).displayVersion == "2,synthetic")
    }
}
