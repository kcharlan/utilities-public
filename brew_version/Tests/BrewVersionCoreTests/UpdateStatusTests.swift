import Foundation
import Testing
@testable import BrewVersionCore

struct UpdateStatusTests {
    let name = PackageName("synthetic-package")!
    @Test func formulaVersionSchemeFollowsHomebrewOutdated() throws {
        let cases: [(String, Int?, String, Int?, Int, UpdateStatus)] = [
            ("2023.1", 0, "1.0", 1, 0, .updateAvailable(installed: "2023.1")),
            ("1.0", 0, "1.0", 1, 0, .upToDate),
            ("1.0_1", 1, "1.0", 1, 2, .updateAvailable(installed: "1.0_1")),
            ("1.1", 1, "1.0", 0, 0, .ahead),
            ("1.0", nil, "2.0", nil, 0, .updateAvailable(installed: "1.0"))
        ]
        for (keg, kegScheme, version, scheme, revision, expected) in cases {
            var listing = Listing(name: name, kind: .formula, version: version, revision: revision)
            var installed = InstalledVersion(version: keg, source: .cellar)
            if let scheme {
                var object = try #require(JSONSerialization.jsonObject(with: JSONEncoder().encode(listing)) as? [String: Any])
                object["versionScheme"] = scheme
                listing = try JSONDecoder().decode(Listing.self, from: JSONSerialization.data(withJSONObject: object))
            }
            if let kegScheme {
                var object = try #require(JSONSerialization.jsonObject(with: JSONEncoder().encode(installed)) as? [String: Any])
                object["versionScheme"] = kegScheme
                installed = try JSONDecoder().decode(InstalledVersion.self, from: JSONSerialization.data(withJSONObject: object))
            }
            #expect(updateStatus(listing: listing, installed: installed) == expected, "\(keg) scheme \(String(describing: kegScheme)) vs \(version) scheme \(String(describing: scheme))")
        }
    }
    @Test func formulaRevisionFollowsUpstreamVersion() {
        let cases: [(String, String, Int, UpdateStatus)] = [
            ("1.0_1", "1.0.1", 0, .updateAvailable(installed: "1.0_1")),
            ("1.0_2", "1.0.1", 0, .updateAvailable(installed: "1.0_2")),
            ("1.0_1", "1.0", 2, .updateAvailable(installed: "1.0_1")),
            ("1.0_1", "1.0", 1, .upToDate),
            ("1.0.0_01", "1.0", 1, .upToDate),
            ("1.0_10", "1.0", 2, .ahead),
            ("1.0", "1.0", 0, .upToDate),
            ("1_2_3", "1_2", 3, .upToDate),
            ("1.0_2beta", "1.0_2beta", 0, .upToDate),
            ("1.0_", "1.0_", 0, .upToDate),
            ("1.0_99999999999999999999999999", "1.0", 2, .ahead)
        ]
        for (installed, version, revision, expected) in cases {
            #expect(updateStatus(listing: .init(name: name, kind: .formula, version: version, revision: revision),
                                 installed: .init(version: installed, source: .cellar)) == expected)
        }
    }
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
