import Foundation
import Testing
@testable import BrewVersionCore

struct ListingTests {
    let name = PackageName("synthetic-formula")!

    @Test func formulaFields() throws {
        let listing = try Listing.decode(Data(#"{"name":"synthetic-formula","versions":{"stable":"1.2.3"},"revision":2,"desc":"Synthetic","homepage":"https://example.invalid/"}"#.utf8), kind: .formula, name: name)
        #expect(listing.name == name)
        #expect(listing.kind == .formula)
        #expect(listing.version == "1.2.3")
        #expect(listing.revision == 2)
        #expect(listing.summary == "Synthetic")
        #expect(listing.homepage == URL(string: "https://example.invalid/"))
        #expect(listing.appNames == [])
        #expect(!listing.autoUpdates)
    }

    @Test func caskAppNames() throws {
        let listing = try cask(#"[{"app":["Synthetic.app"]},{"app":["Source.app",{"target":"Renamed.app"}]},{"zap":[]}]"#)
        #expect(listing.appNames == ["Synthetic.app", "Renamed.app"])
        #expect(listing.version == "2.3")
        #expect(listing.kind == .cask)
        #expect(listing.name == name)
        #expect(listing.autoUpdates)
    }

    @Test func caskSiblingTarget() throws {
        let listing = try cask(#"[{"app":["Source.app",{"target":"Argument.app"}],"target":"/synthetic-apps/Override.app"},{"app":["nested/Source.app",{"target":"nested/Argument.app"}],"target":4},{"app":["nested/Source.app",{"target":""}],"target":""}]"#)
        #expect(listing.appNames == ["Override.app", "Argument.app", "Source.app"])
    }

    @Test func malformedArtifactsDoNotFail() throws {
        #expect(try cask(#""oops""#).appNames == [])
        #expect(try cask(#"[null,4,{"app":"oops"},{"app":[]},{"app":[3]}]"#).appNames == [])
    }

    @Test func missingOptionals() throws {
        let listing = try Listing.decode(Data(#"{"version":"latest","auto_updates":null}"#.utf8), kind: .cask, name: name)
        #expect(listing.version == "latest")
        #expect(listing.revision == 0)
        #expect(!listing.autoUpdates)
        #expect(listing.summary == nil)
        #expect(listing.homepage == nil)
    }

    @Test func bulkItems() throws {
        let formula = Listing.decodeItem(["name": "synthetic-formula", "versions": ["stable": "3"]], kind: .formula)
        #expect(formula?.name == name)
        #expect(formula?.version == "3")
        let cask = Listing.decodeItem(["token": "synthetic-cask", "version": "4"], kind: .cask)
        #expect(cask?.name.rawValue == "synthetic-cask")
        #expect(cask?.version == "4")
        #expect(Listing.decodeItem(["name": "Bad", "versions": ["stable": "1"]], kind: .formula) == nil)
        #expect(Listing.decodeItem(["token": "synthetic-cask", "version": ""], kind: .cask) == nil)
    }

    private func cask(_ artifacts: String) throws -> Listing {
        try Listing.decode(Data("{\"version\":\"2.3\",\"auto_updates\":true,\"artifacts\":\(artifacts)}".utf8), kind: .cask, name: name)
    }
}
