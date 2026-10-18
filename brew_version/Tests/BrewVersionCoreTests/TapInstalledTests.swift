import Foundation
import Testing
@testable import BrewVersionCore

struct TapInstalledTests {
    let tap = TapName("synthetic-owner/synthetic-tap")!
    let full = PackageName("synthetic-owner/synthetic-tap/synthetic-shared")!
    let official = PackageName("synthetic-shared")!

    private func reader(_ fixture: InstallationFixture, taps: Set<TapName>) -> InstalledReader {
        InstalledReader(prefixes: HomebrewPrefix.detectAll(candidates: [fixture.root.appendingPathComponent("prefix")]),
                        applicationDirectories: [fixture.root.appendingPathComponent("Applications")],
                        tappedTaps: { taps })
    }

    @Test func tapInstallKeyedByFullName() throws {
        let f = try InstallationFixture()
        try f.install("prefix/Cellar/synthetic-shared/4.5.6", kind: .formula,
                      tap: "SYNTHETIC-OWNER/homebrew-synthetic-tap")
        let r = reader(f, taps: [tap])
        let snapshot = r.snapshot(listings: [])
        #expect(snapshot.installed(full, kind: .formula) == .init(version: "4.5.6", source: .cellar))
        #expect(snapshot.installed(official, kind: .formula) == nil)
        #expect(r.installedPackages().count == 1)
        #expect(r.installedPackages().first?.name == full)
    }

    @Test func untappedLeftoverIsNotOfficialInstall() throws {
        let f = try InstallationFixture()
        try f.install("prefix/Cellar/synthetic-shared/4.5.6", kind: .formula, tap: tap.description)
        let r = reader(f, taps: [])
        #expect(r.installed(official, kind: .formula, listing: nil) == nil)
        #expect(r.installed(full, kind: .formula, listing: nil) == nil)
        #expect(r.installedPackages().isEmpty)
    }

    @Test func officialWatchIgnoresTapInstall() throws {
        let f = try InstallationFixture()
        try f.install("prefix/Cellar/synthetic-shared/4.5.6", kind: .formula, tap: tap.description)
        let r = reader(f, taps: [tap])
        #expect(r.installed(official, kind: .formula, listing: nil) == nil)
        #expect(r.installed(full, kind: .formula, listing: nil)?.version == "4.5.6")
    }

    @Test func pointLookupProvenance() throws {
        let other = PackageName("synthetic-owner/synthetic-other/synthetic-shared")!
        for kind in [PackageKind.formula, .cask] {
            let officialTap = kind == .formula ? "homebrew/core" : "homebrew/cask"
            let wrongKind = kind == .formula ? "homebrew/cask" : "homebrew/core"
            for (receiptTap, tapped, expected): (String?, Bool, String?) in [
                (officialTap, true, "official"), (wrongKind, true, nil),
                ("SYNTHETIC-OWNER/homebrew-synthetic-tap", true, "tap"),
                (tap.description, false, nil), (nil, true, kind == .cask ? "official" : nil),
                ("synthetic malformed/tap name", true, nil)
            ] {
                let f = try InstallationFixture()
                let rack = kind == .formula ? "Cellar" : "Caskroom"
                if let receiptTap {
                    try f.install("prefix/\(rack)/synthetic-shared/4.5.6", kind: kind, tap: receiptTap)
                } else { try f.directory("prefix/\(rack)/synthetic-shared/4.5.6") }
                let r = reader(f, taps: tapped ? [tap] : [])
                let snapshot = r.snapshot(listings: [])
                for (name, identity) in [(official, "official"), (full, "tap"), (other, "other")] {
                    let want: InstalledVersion? = expected == identity
                        ? .init(version: "4.5.6", source: kind == .formula ? .cellar : .caskroom) : nil
                    #expect(r.installed(name, kind: kind, listing: nil) == want,
                            "\(kind), receipt \(receiptTap ?? "missing"), tapped \(tapped), name \(name)")
                    #expect(snapshot.installed(name, kind: kind) == want)
                }
                #expect(r.installedPackages().count == (expected == nil ? 0 : 1))
            }
        }
    }

    @Test func tapCaskAppBundle() throws {
        let f = try InstallationFixture()
        try f.install("prefix/Caskroom/synthetic-app/4.5.6", kind: .cask, tap: tap.description)
        try f.app("9.0.1")
        let name = PackageName("synthetic-owner/synthetic-tap/synthetic-app")!
        let listing = Listing(name: name, kind: .cask, version: "7.8", autoUpdates: true, appNames: ["Synthetic.app"])
        let r = reader(f, taps: [tap])
        let want = InstalledVersion(version: "9.0.1", source: .appBundle)
        #expect(r.installed(name, kind: .cask, listing: listing) == want)
        #expect(r.snapshot(listings: [listing]).installed(name, kind: .cask) == want)
    }

    @Test func repeatedPrefixReceiptPreservesProvenance() throws {
        let f = try InstallationFixture()
        let rawTap = "synthetic-owner/homebrew-homebrew-synthetic-tap"
        try f.install("prefix/Cellar/synthetic-tool/4.5.6", kind: .formula, tap: rawTap)
        let r = reader(f, taps: [TapName(rawTap)!])
        let name = PackageName("synthetic-owner/homebrew-homebrew-synthetic-tap/synthetic-tool")!
        let different = PackageName("synthetic-owner/homebrew-synthetic-tap/synthetic-tool")!
        #expect(r.installed(name, kind: .formula, listing: nil)?.version == "4.5.6")
        #expect(r.snapshot(listings: []).installed(name, kind: .formula)?.version == "4.5.6")
        #expect(r.snapshot(listings: []).installed(different, kind: .formula) == nil)
    }
}
