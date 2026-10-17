import Testing
@testable import BrewVersionCore

struct UpdateStatusTests {
    let name = PackageName("synthetic-package")!
    @Test func versionsAndRevision() {
        let listing = Listing(name: name, kind: .formula, version: "1.0.0")
        #expect(updateStatus(listing: listing, installed: .init(version: "1.0.0", source: .cellar)) == .upToDate)
        #expect(updateStatus(listing: listing, installed: .init(version: "2.0", source: .cellar)) == .ahead)
        #expect(updateStatus(listing: .init(name: name, kind: .formula, version: "1.0.0", revision: 2),
                             installed: .init(version: "1.0.0_1", source: .cellar)) == .updateAvailable(installed: "1.0.0_1"))
    }
    @Test func appBundleComparesBeforeComma() {
        let listing = Listing(name: name, kind: .cask, version: "3.3.1,4940")
        #expect(updateStatus(listing: listing, installed: .init(version: "3.3.1", source: .appBundle)) == .upToDate)
        #expect(updateStatus(listing: listing, installed: .init(version: "3.3.1,4939", source: .caskroom)) == .updateAvailable(installed: "3.3.1,4939"))
    }
    @Test func missingAndUnversioned() {
        #expect(updateStatus(listing: .init(name: name, kind: .formula, version: "1"), installed: nil) == .notInstalled)
        let latest = Listing(name: name, kind: .cask, version: "latest")
        #expect(updateStatus(listing: latest, installed: .init(version: "latest", source: .caskroom)) == .unversioned)
        #expect(updateStatus(listing: latest, installed: nil) == .notInstalled)
    }
}
