import Foundation
import Testing
@testable import BrewVersionCore

struct OtherUpdatesTests {
    @Test func onlyUnwatchedUpdatesAndFallbackSource() async throws {
        let f = try InstallationFixture()
        let catalog = try await seedCatalog(f.root.appendingPathComponent("cache"))
        try f.install("prefix/Cellar/synthetic-formula/1", kind: .formula)
        try f.install("prefix/Caskroom/synthetic-cask/1", kind: .cask)
        try f.install("prefix/Cellar/synthetic-not-in-catalog/1", kind: .formula)
        let updates = otherUpdates(catalog: catalog, installed: f.reader(), watched: [])
        #expect(updates.map(\.listing.name.rawValue) == ["synthetic-cask", "synthetic-formula"])
        #expect(updates[0].installed.source == .caskroomFallback)
        #expect(otherUpdates(catalog: catalog, installed: f.reader(), watched: [PackageName("synthetic-cask")!]).count == 1)
        try f.install("prefix/Cellar/synthetic-formula/2", kind: .formula)
        try f.install("prefix/Caskroom/synthetic-cask/4", kind: .cask)
        #expect(otherUpdates(catalog: catalog, installed: f.reader(), watched: []).isEmpty)
    }
    @Test func unversionedIsExcluded() async throws {
        let f = try InstallationFixture()
        try f.install("prefix/Caskroom/synthetic-cask/1", kind: .cask)
        let stub = StubTransport([catalogURL(.formula): [catalogResponse()], catalogURL(.cask): [catalogResponse(200, #"[{"token":"synthetic-cask","version":"latest"}]"#)]])
        let catalog = try await CatalogClient(transport: stub, cacheDirectory: f.root.appendingPathComponent("cache")).load().catalog
        #expect(otherUpdates(catalog: catalog, installed: f.reader(), watched: []).isEmpty)
    }
    @Test(arguments: [PackageKind.formula, .cask])
    func tapNameCollision(_ kind: PackageKind) async throws {
        for state in ["third-party", "missing", "unreadable", "malformed", "unknown", "wrong-kind"] {
            let f = try InstallationFixture()
            let name = kind == .formula ? "synthetic-formula" : "synthetic-cask"
            let rack = kind == .formula ? "Cellar" : "Caskroom"
            let keg = try f.install("prefix/\(rack)/\(name)/1", kind: kind,
                                    tap: state == "third-party" ? "synthetic-owner/synthetic-tap" :
                                        state == "wrong-kind" ? (kind == .formula ? "homebrew/cask" : "homebrew/core") : nil)
            let receipt = (kind == .formula ? keg : keg.deletingLastPathComponent().appendingPathComponent(".metadata"))
                .appendingPathComponent("INSTALL_RECEIPT.json")
            switch state {
            case "missing": try f.fm.removeItem(at: receipt)
            case "unreadable": try f.fm.removeItem(at: receipt); try f.fm.createDirectory(at: receipt, withIntermediateDirectories: true)
            case "malformed": try Data("synthetic malformed".utf8).write(to: receipt)
            case "unknown": try Data(#"{"source":{}}"#.utf8).write(to: receipt)
            default: break
            }
            let catalog = try await seedCatalog(f.root.appendingPathComponent("cache"))
            #expect(otherUpdates(catalog: catalog, installed: f.reader(), watched: []).isEmpty, "\(kind) \(state)")
        }
    }
}
