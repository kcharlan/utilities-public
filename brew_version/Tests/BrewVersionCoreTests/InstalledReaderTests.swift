import Foundation
import Testing
@testable import BrewVersionCore

final class InstallationFixture {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent("brew-version-synthetic-brew-\(UUID().uuidString)")
    let fm = FileManager.default
    init() throws { try fm.createDirectory(at: root, withIntermediateDirectories: true) }
    deinit { try? fm.removeItem(at: root) }
    @discardableResult func directory(_ path: String) throws -> URL {
        let url = root.appendingPathComponent(path)
        try fm.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }
    @discardableResult func install(_ path: String, kind: PackageKind, tap: String? = nil) throws -> URL {
        let url = try directory(path)
        let receiptDirectory = kind == .formula ? url : try directory((path as NSString).deletingLastPathComponent + "/.metadata")
        let receipt = ["source": ["tap": tap ?? (kind == .formula ? "homebrew/core" : "homebrew/cask")]]
        try JSONSerialization.data(withJSONObject: receipt).write(to: receiptDirectory.appendingPathComponent("INSTALL_RECEIPT.json"))
        return url
    }
    func reader(_ roots: [String] = ["prefix"]) -> InstalledReader {
        InstalledReader(prefixes: HomebrewPrefix.detectAll(candidates: roots.map { root.appendingPathComponent($0) }),
                        applicationDirectories: [root.appendingPathComponent("Applications"), root.appendingPathComponent("UserApplications")])
    }
    func app(_ version: String, directory: String = "Applications") throws {
        let contents = try self.directory("\(directory)/Synthetic.app/Contents")
        try PropertyListSerialization.data(fromPropertyList: ["CFBundleShortVersionString": version], format: .xml, options: 0)
            .write(to: contents.appendingPathComponent("Info.plist"))
    }
}

struct InstalledReaderTests {
    let formula = PackageName("synthetic-formula")!
    let cask = PackageName("synthetic-cask")!
    var selfUpdating: Listing { .init(name: cask, kind: .cask, version: "2.0.0", autoUpdates: true, appNames: ["Synthetic.app"]) }

    @Test func provenance() throws {
        for kind in [PackageKind.formula, .cask] {
            for state in ["admitted", "third-party", "missing", "unreadable", "malformed", "unknown", "wrong-kind", "dangling-link"] {
                let f = try InstallationFixture()
                let name = kind == .formula ? formula : cask
                let rack = kind == .formula ? "Cellar" : "Caskroom"
                let keg = try f.install("prefix/\(rack)/\(name)/2.0.0", kind: kind,
                                        tap: state == "third-party" ? "synthetic-owner/synthetic-tap" :
                                            state == "wrong-kind" ? (kind == .formula ? "homebrew/cask" : "homebrew/core") : nil)
                let receipt = (kind == .formula ? keg : keg.deletingLastPathComponent().appendingPathComponent(".metadata"))
                    .appendingPathComponent("INSTALL_RECEIPT.json")
                switch state {
                case "missing": try f.fm.removeItem(at: receipt)
                case "unreadable": try f.fm.removeItem(at: receipt); try f.fm.createDirectory(at: receipt, withIntermediateDirectories: true)
                case "malformed": try Data("synthetic malformed".utf8).write(to: receipt)
                case "unknown": try Data("{\"source\":{}}".utf8).write(to: receipt)
                case "dangling-link":
                    try f.fm.removeItem(at: receipt)
                    try f.fm.createSymbolicLink(atPath: receipt.path, withDestinationPath: "synthetic-absent-receipt")
                default: break
                }
                try f.app("8.0.0")
                let installed = f.reader().installed(name, kind: kind, listing: kind == .cask ? selfUpdating : nil)
                let admitted = state == "admitted" || (kind == .cask && state == "missing")
                #expect((installed != nil) == admitted, "\(kind) \(state)")
                #expect(f.reader().installedPackages().contains { $0.name == name && $0.kind == kind } == admitted)
            }
        }
    }
    @Test func formulaFromOptLink() throws {
        let f = try InstallationFixture()
        try f.install("prefix/Cellar/synthetic-formula/1.0.0_1", kind: .formula)
        try f.install("prefix/Cellar/synthetic-formula/2.0.0", kind: .formula)
        let opt = try f.directory("prefix/opt")
        try f.fm.createSymbolicLink(atPath: opt.appendingPathComponent("synthetic-formula").path,
                                   withDestinationPath: "../Cellar/synthetic-formula/1.0.0_1")
        #expect(f.reader().installed(formula, kind: .formula, listing: nil) == .init(version: "1.0.0_1", source: .cellar))
    }
    @Test func formulaWithoutOptLinkUsesHighest() throws {
        let f = try InstallationFixture()
        for version in ["1.9", "1.10", "0.9.0"] { try f.install("prefix/Cellar/synthetic-formula/\(version)", kind: .formula) }
        #expect(f.reader().installed(formula, kind: .formula, listing: nil)?.version == "1.10")
    }
    @Test func formulaKegRevisionOrdering() throws {
        let cases: [([String], String, Int, UpdateStatus)] = [
            (["1.0_1"], "1.0.1", 0, .updateAvailable(installed: "1.0_1")),
            (["1.0_2"], "1.0.1", 0, .updateAvailable(installed: "1.0_2")),
            (["1.0_1"], "1.0", 2, .updateAvailable(installed: "1.0_1")),
            (["1.0_1"], "1.0", 1, .upToDate),
            (["1.0_2", "1.0.1"], "1.0.1", 0, .upToDate),
            (["1.0_2", "1.0_10"], "1.0", 10, .upToDate),
            (["1.0.0_1", "1.0_01"], "1.0", 1, .upToDate)
        ]
        let expectedKegs = ["1.0_1", "1.0_2", "1.0_1", "1.0_1", "1.0.1", "1.0_10", "1.0.0_1"]
        for (index, row) in cases.enumerated() {
            let (versions, version, revision, status) = row
            let f = try InstallationFixture()
            for keg in versions { try f.install("prefix/Cellar/synthetic-formula/\(keg)", kind: .formula) }
            let listing = Listing(name: formula, kind: .formula, version: version, revision: revision)
            let installed = f.reader().installed(formula, kind: .formula, listing: listing)
            #expect(installed?.version == expectedKegs[index])
            #expect(updateStatus(listing: listing, installed: installed) == status)
        }
    }
    @Test func legacyCaskWithoutReceipt() throws {
        let f = try InstallationFixture()
        try f.directory("prefix/Caskroom/synthetic-cask/1.0")
        let reader = f.reader()
        #expect(reader.installed(cask, kind: .cask, listing: nil) == .init(version: "1.0", source: .caskroom))
        #expect(reader.installedPackages().contains { $0.name == cask && $0.kind == .cask })
        #expect(reader.installed(cask, kind: .cask, listing: selfUpdating) == .init(version: "1.0", source: .caskroomFallback))
        try f.app("2.3.0")
        #expect(reader.installed(cask, kind: .cask, listing: selfUpdating) == .init(version: "2.3.0", source: .appBundle))
    }
    @Test func legacyCaskSymlinkIsNotInstalled() throws {
        let f = try InstallationFixture()
        try f.directory("synthetic-target")
        let rack = try f.directory("prefix/Caskroom/synthetic-cask")
        try f.fm.createSymbolicLink(at: rack.appendingPathComponent("1.0"), withDestinationURL: f.root.appendingPathComponent("synthetic-target"))
        #expect(f.reader().installed(cask, kind: .cask, listing: selfUpdating) == nil)
        #expect(f.reader().installedPackages().isEmpty)
    }
    @Test func caskHighestKeepsVersionTokenOrdering() throws {
        let f = try InstallationFixture()
        for version in ["1.0_2", "1.0.1"] { try f.install("prefix/Caskroom/synthetic-cask/\(version)", kind: .cask) }
        #expect(f.reader().installed(cask, kind: .cask, listing: nil)?.version == "1.0_2")
    }
    @Test func aliasNameIsNotInstalled() throws {
        let f = try InstallationFixture()
        try f.install("prefix/Cellar/synthetic-formula/1.0.0", kind: .formula)
        let opt = try f.directory("prefix/opt")
        try f.fm.createSymbolicLink(atPath: opt.appendingPathComponent("synthetic-alias").path,
                                   withDestinationPath: "../Cellar/synthetic-formula/1.0.0")
        let alias = PackageName("synthetic-alias")!
        #expect(f.reader().installed(alias, kind: .formula, listing: nil) == nil)
        #expect(!f.reader().installedPackages().contains { $0.name == alias })
    }
    @Test func caskIgnoresMetadataAndLatestLink() throws {
        let f = try InstallationFixture()
        try f.install("prefix/Caskroom/synthetic-cask/2.0.0", kind: .cask)
        try f.fm.createSymbolicLink(atPath: f.root.appendingPathComponent("prefix/Caskroom/synthetic-cask/latest").path, withDestinationPath: "2.0.0")
        #expect(f.reader().installed(cask, kind: .cask, listing: nil) == .init(version: "2.0.0", source: .caskroom))
    }
    @Test func realLatestCaskDirectoryIsInstalledAndUnversioned() throws {
        let f = try InstallationFixture()
        try f.install("prefix/Caskroom/synthetic-cask/latest", kind: .cask)
        let listing = Listing(name: cask, kind: .cask, version: "latest")
        let reader = f.reader()
        let installed = reader.installed(cask, kind: .cask, listing: listing)
        #expect(installed == .init(version: "latest", source: .caskroom))
        #expect(reader.installedPackages().contains { $0.name == cask && $0.kind == .cask })
        #expect(updateStatus(listing: listing, installed: installed) == .unversioned)
        try f.app("2.3.0")
        let selfUpdatingLatest = Listing(name: cask, kind: .cask, version: "latest", autoUpdates: true, appNames: ["Synthetic.app"])
        let appInstalled = reader.installed(cask, kind: .cask, listing: selfUpdatingLatest)
        #expect(appInstalled == .init(version: "2.3.0", source: .appBundle))
        #expect(updateStatus(listing: selfUpdatingLatest, installed: appInstalled) == .unversioned)
    }
    @Test func selfUpdatingCaskReadsAppBundle() throws {
        let f = try InstallationFixture()
        try f.install("prefix/Caskroom/synthetic-cask/2.0.0", kind: .cask)
        try f.app("2.3.0"); try f.app("7.0.0", directory: "UserApplications")
        #expect(f.reader().installed(cask, kind: .cask, listing: selfUpdating) == .init(version: "2.3.0", source: .appBundle))
    }
    @Test func appBundleReadIsFresh() throws {
        let f = try InstallationFixture()
        try f.install("prefix/Caskroom/synthetic-cask/2.0.0", kind: .cask)
        let reader = f.reader()
        try f.app("2.3.0")
        #expect(reader.installed(cask, kind: .cask, listing: selfUpdating)?.version == "2.3.0")
        try f.app("2.4.0")
        #expect(reader.installed(cask, kind: .cask, listing: selfUpdating)?.version == "2.4.0")
    }
    @Test func missingAppFallsBackToCaskroom() throws {
        let f = try InstallationFixture()
        try f.install("prefix/Caskroom/synthetic-cask/2.0.0", kind: .cask)
        #expect(f.reader().installed(cask, kind: .cask, listing: selfUpdating) == .init(version: "2.0.0", source: .caskroomFallback))
        try f.app("")
        #expect(f.reader().installed(cask, kind: .cask, listing: selfUpdating)?.source == .caskroomFallback)
    }
    @Test func firstPrefixWins() throws {
        let f = try InstallationFixture()
        try f.install("one/Cellar/synthetic-formula/1", kind: .formula)
        try f.install("two/Cellar/synthetic-formula/2", kind: .formula)
        #expect(f.reader(["absent", "one", "two"]).installed(formula, kind: .formula, listing: nil)?.version == "1")
        #expect(HomebrewPrefix.detectAll(candidates: ["one", "two"].map { f.root.appendingPathComponent($0) }).map(\.root.lastPathComponent) == ["one", "two"])
    }
    @Test func secondPrefixFound() throws {
        let f = try InstallationFixture()
        try f.directory("one/Cellar")
        try f.install("two/Cellar/synthetic-formula/2", kind: .formula)
        #expect(f.reader(["one", "two"]).installed(formula, kind: .formula, listing: nil)?.version == "2")
    }
    @Test func excludedLinkedKegDoesNotUseOlderKeg() throws {
        let f = try InstallationFixture()
        try f.install("one/Cellar/synthetic-formula/1", kind: .formula)
        try f.install("one/Cellar/synthetic-formula/2", kind: .formula, tap: "synthetic-owner/synthetic-tap")
        let opt = try f.directory("one/opt")
        try f.fm.createSymbolicLink(atPath: opt.appendingPathComponent("synthetic-formula").path, withDestinationPath: "../Cellar/synthetic-formula/2")
        #expect(f.reader(["one"]).installed(formula, kind: .formula, listing: nil) == nil)
        #expect(f.reader(["one"]).installedPackages().isEmpty)
        try f.install("two/Cellar/synthetic-formula/3", kind: .formula)
        #expect(f.reader(["one", "two"]).installed(formula, kind: .formula, listing: nil)?.version == "3")
    }
    @Test func installedPackagesSkipsHiddenAndInvalid() throws {
        let f = try InstallationFixture()
        try f.install("prefix/Cellar/synthetic-formula/1", kind: .formula)
        try f.install("prefix/Caskroom/synthetic-cask/1", kind: .cask)
        for name in [".synthetic-hidden", "Synthetic-invalid"] { try f.install("prefix/Cellar/\(name)/1", kind: .formula) }
        try Data().write(to: f.root.appendingPathComponent("prefix/Cellar/synthetic-file"))
        let packages = f.reader().installedPackages()
        #expect(packages.count == 2)
        #expect(packages.contains { $0.name == formula && $0.kind == .formula })
        #expect(packages.contains { $0.name == cask && $0.kind == .cask })
    }
}
