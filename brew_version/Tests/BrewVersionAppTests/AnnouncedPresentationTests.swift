import Testing
import BrewVersionCore
@testable import BrewVersion

struct AnnouncedPresentationTests {
    @Test func announcedStatusUsesInstalledVersion() {
        let listing = Listing(name: PackageName("synthetic-a")!, kind: .formula, version: "2.0")
        #expect(statusText(listing, installed: .init(version: "1.0", source: .cellar), announced: true) == "You have 1.0 · not in brew yet")
        #expect(statusText(listing, installed: nil, announced: true) == "Not installed · not in brew yet")
    }
    @Test func watchedTitleAndOrderPreferAmberThenAnnounced() {
        func entry(_ name: String, pending: Bool, installed: String) -> WatchEntry {
            let listing = Listing(name: PackageName(name)!, kind: .formula, version: "2.0")
            var entry = WatchEntry(name: listing.name, kind: .formula, lastListing: listing, installed: .init(version: installed, source: .cellar))
            if pending { entry.pendingRelease = ReleaseID(listing) }
            return entry
        }
        let amber = entry("synthetic-z", pending: false, installed: "1.0")
        let announced = entry("synthetic-y", pending: true, installed: "1.0")
        let current = entry("synthetic-a", pending: false, installed: "2.0")
        #expect(sortedWatches([current, announced, amber]).map(\.name) == [amber.name, announced.name, current.name])
        #expect(watchTitle([announced, current]) == "1 announced")
        #expect(watchTitle([announced, announced]) == "2 announced")
        #expect(watchTitle([amber, announced]) == "1 update")
        #expect(watchTitle([]) == "Nothing watched yet")
        #expect(watchTitle([current]) == "All up to date")
    }
}
