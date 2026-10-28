import Foundation
import Testing
@testable import BrewVersionCore

private final class TapFixture {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent("brew-version-synthetic-taps-\(UUID().uuidString)")
    let fm = FileManager.default
    init() throws { try fm.createDirectory(at: root, withIntermediateDirectories: true) }
    deinit { try? fm.removeItem(at: root) }
    @discardableResult func write(_ path: String, _ text: String = "# synthetic fixture\n") throws -> URL {
        let file = root.appendingPathComponent(path)
        try fm.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data(text.utf8).write(to: file)
        return file
    }
    @discardableResult func tap(_ name: String = "synthetic-owner/homebrew-synthetic-tap", layout: String = "Library/Taps",
                               remote: String? = "https://github.com/synthetic-owner/homebrew-synthetic-tap.git") throws -> String {
        let path = "\(layout)/\(name)"
        try write("\(path)/.git/config", remote.map { "[remote \"origin\"]\n url = \($0)\n" } ?? "[core]\n bare = false\n")
        return path
    }
    func scan() -> TapIndex { TapIndex.scan(prefixes: [HomebrewPrefix(root: root)]) }
}

struct TapIndexTests {
    @Test func scansLayouts() throws {
        let f = try TapFixture(), tap = try f.tap()
        for path in ["Formula/synthetic-tool.rb", "Formula/s/synthetic-nested.rb", "Casks/synthetic-app.rb", "Casks/s/synthetic-shared.rb"] {
            try f.write("\(tap)/\(path)")
        }
        let index = f.scan(), entries = index.suggestions(prefix: "synthetic-")
        #expect(entries.map(\.name.rawValue) == ["synthetic-owner/synthetic-tap/synthetic-app", "synthetic-owner/synthetic-tap/synthetic-nested", "synthetic-owner/synthetic-tap/synthetic-shared", "synthetic-owner/synthetic-tap/synthetic-tool"])
        #expect(entries.map(\.kind) == [.cask, .formula, .cask, .formula])
        #expect(entries.map(\.path) == ["Casks/synthetic-app.rb", "Formula/s/synthetic-nested.rb", "Casks/s/synthetic-shared.rb", "Formula/synthetic-tool.rb"])
        #expect(index.taps == [TapName("synthetic-owner/synthetic-tap")!])
        #expect(entries.allSatisfy { $0.repository?.repo == "homebrew-synthetic-tap" })
    }

    @Test func formulaDirectoryPrecedence() throws {
        let f = try TapFixture(), tap = try f.tap()
        try f.write("\(tap)/synthetic-root.rb")
        try f.write("\(tap)/nested/synthetic-hidden.rb")
        try f.write("\(tap)/Casks/synthetic-app.rb")
        #expect(f.scan().suggestions(prefix: "synthetic-").map(\.path) == ["Casks/synthetic-app.rb", "synthetic-root.rb"])
        try f.write("\(tap)/HomebrewFormula/s/synthetic-legacy.rb")
        #expect(f.scan().suggestions(prefix: "synthetic-").map(\.path) == ["Casks/synthetic-app.rb", "HomebrewFormula/s/synthetic-legacy.rb"])
        try f.write("\(tap)/Formula/synthetic-tool.rb")
        #expect(f.scan().suggestions(prefix: "synthetic-").map(\.path) == ["Casks/synthetic-app.rb", "Formula/synthetic-tool.rb"])
        try f.fm.removeItem(at: f.root.appendingPathComponent("\(tap)/Formula/synthetic-tool.rb"))
        #expect(f.scan().entries(shortName: "synthetic-legacy", kinds: .formula).isEmpty)
    }

    @Test func duplicateShardKeepsLongerPath() throws {
        let f = try TapFixture(), tap = try f.tap()
        for directory in ["Formula", "Casks"] {
            for prefix in ["", "s/", "longer/", "equalx/"] { try f.write("\(tap)/\(directory)/\(prefix)synthetic-shared.rb") }
        }
        #expect(f.scan().entries(shortName: "synthetic-shared", kinds: .auto).map(\.path) == ["Formula/equalx/synthetic-shared.rb", "Casks/equalx/synthetic-shared.rb"])
    }

    @Test func intelRepositoryLayout() throws {
        let f = try TapFixture(), tap = try f.tap(layout: "Homebrew/Library/Taps")
        try f.write("\(tap)/synthetic-tool.rb")
        #expect(f.scan().suggestions(prefix: "synthetic-t").map(\.path) == ["synthetic-tool.rb"])
        try f.fm.createDirectory(at: f.root.appendingPathComponent("Library/Taps"), withIntermediateDirectories: true)
        #expect(f.scan().taps.isEmpty)
    }

    @Test func remoteParsing() throws {
        for remote in ["https://github.com/Synthetic-Remote/homebrew-Synthetic-Repo", "git@github.com:Synthetic-Remote/homebrew-Synthetic-Repo.git", "ssh://git@github.com/Synthetic-Remote/homebrew-Synthetic-Repo.git///", "git://github.com/Synthetic-Remote/homebrew-Synthetic-Repo/", " HTTPS://GITHUB.COM/Synthetic-Remote/homebrew-Synthetic-Repo.GIT "] {
            let f = try TapFixture()
            try f.tap(remote: remote)
            let repository = f.scan().repository(for: TapName("synthetic-owner/synthetic-tap")!)
            #expect(repository?.owner == "synthetic-remote", "\(remote)")
            #expect(repository?.repo == "homebrew-synthetic-repo", "\(remote)")
        }
        for remote: String? in [nil, "https://synthetic.invalid/synthetic-owner/synthetic-repo.git", "ssh://git@github.com:443/synthetic-owner/synthetic-repo.git", "https://github.com/synthetic-owner/synthetic-repo/extra"] {
            let f = try TapFixture(); try f.tap(remote: remote)
            #expect(f.scan().repository(for: TapName("synthetic-owner/synthetic-tap")!) == nil)
            #expect(f.scan().taps.count == 1)
        }
        let f = try TapFixture(), tap = try f.tap()
        try f.write("\(tap)/.git/config", "[remote \"other\"]\nurl = https://github.com/synthetic-wrong/synthetic-wrong\n[remote \"origin\"]\n URL = \"git@github.com:Synthetic-Remote/homebrew-Synthetic-Repo.git\" # comment\n")
        #expect(f.scan().repository(for: TapName("synthetic-owner/synthetic-tap")!)?.owner == "synthetic-remote")
    }

    @Test func packageBasenamesKeepExistingGrammar() throws {
        let f = try TapFixture(), tap = try f.tap()
        for dir in ["Formula", "Casks"] {
            try f.write("\(tap)/\(dir)/synthetic-tool@1+2.3_4-5.rb")
            for invalid in ["Synthetic-upper", "-synthetic", "synthetic space", "synthetic!bad"] { try f.write("\(tap)/\(dir)/\(invalid).rb") }
        }
        #expect(f.scan().suggestions(prefix: "synthetic-").map(\.name.shortName) == ["synthetic-tool@1+2.3_4-5", "synthetic-tool@1+2.3_4-5"])
    }

    @Test func skipsOfficialAndInvalid() throws {
        let f = try TapFixture()
        for name in ["homebrew/homebrew-core", "homebrew/homebrew-cask", "linuxbrew/homebrew-core", ".synthetic-owner/homebrew-synthetic-tap", "synthetic-owner/.synthetic-tap", "synthetic!owner/homebrew-synthetic-tap", "synthetic-owner/homebrew-synthetic!tap"] {
            let tap = try f.tap(name); try f.write("\(tap)/Formula/synthetic-tool.rb")
        }
        try f.write("Library/Taps/synthetic-owner/homebrew-synthetic-no-git/Formula/synthetic-tool.rb")
        let tap = try f.tap()
        try f.write("\(tap)/Formula/.hidden/synthetic-tool.rb")
        try f.write("\(tap)/Formula/.synthetic-hidden.rb")
        try f.write("\(tap)/Formula/synthetic-text.txt")
        #expect(f.scan().suggestions(prefix: "").isEmpty)
        #expect(f.scan().taps == [TapName("synthetic-owner/synthetic-tap")!])
    }

    @Test func queries() throws {
        let f = try TapFixture(), tap = try f.tap()
        try f.write("\(tap)/Formula/synthetic-shared.rb")
        try f.write("\(tap)/Casks/synthetic-shared.rb")
        try f.write("\(tap)/Formula/synthetic-tool.rb")
        let other = try f.tap("synthetic-other/homebrew-synthetic-tap")
        try f.write("\(other)/Casks/synthetic-shared.rb")
        let index = f.scan(), name = PackageName("synthetic-owner/synthetic-tap/synthetic-shared")!
        #expect(index.entries(shortName: "synthetic-shared", kinds: .auto).map(\.kind) == [.cask, .formula, .cask])
        #expect(index.entries(shortName: "synthetic-shared", kinds: .formula).count == 1)
        #expect(index.entries(shortName: "synthetic-shared", kinds: .cask).count == 2)
        #expect(index.entry(name, kind: nil)?.kind == .formula)
        #expect(index.entry(name, kind: .cask)?.path == "Casks/synthetic-shared.rb")
        #expect(index.entry(PackageName("synthetic-shared")!, kind: nil) == nil)
        #expect(index.suggestions(prefix: "synthetic-t").map(\.name.shortName) == ["synthetic-tool"])
        #expect(TapIndex.empty.entries(shortName: "synthetic-shared", kinds: .auto).isEmpty)
    }

    @Test func rescanSeesNewTaps() throws {
        let f = try TapFixture(), old = f.scan(), tap = try f.tap()
        try f.write("\(tap)/Formula/synthetic-tool.rb")
        #expect(old.taps.isEmpty)
        #expect(f.scan().suggestions(prefix: "synthetic-t").count == 1)
    }

    @Test func preservesRepeatedPrefixesAndFirstPrefixPrecedence() throws {
        let first = try TapFixture(), second = try TapFixture()
        for f in [first, second] {
            let tap = try f.tap("synthetic-owner/homebrew-linuxbrew-synthetic-tap")
            try f.write("\(tap)/Formula/\(f === first ? "synthetic-tool" : "synthetic-other").rb")
        }
        let index = TapIndex.scan(prefixes: [HomebrewPrefix(root: first.root), HomebrewPrefix(root: second.root)])
        #expect(index.taps.map(\.description) == ["synthetic-owner/linuxbrew-synthetic-tap"])
        #expect(index.suggestions(prefix: "").map(\.name.rawValue) == ["synthetic-owner/linuxbrew-synthetic-tap/synthetic-tool"])
        #expect(index.suggestions(prefix: "").first?.name.tap == index.taps.first)
    }
}

extension TapIndexTests {
    @Test func shardingDoesNotFollowDirectorySymlinks() throws {
        let f = try TapFixture(), tap = try f.tap()
        try f.write("synthetic-outside/synthetic-tool.rb")
        for directory in ["Formula", "Casks"] {
            try f.fm.createDirectory(at: f.root.appendingPathComponent("\(tap)/\(directory)"), withIntermediateDirectories: true)
            try f.fm.createSymbolicLink(at: f.root.appendingPathComponent("\(tap)/\(directory)/synthetic-link"),
                                       withDestinationURL: f.root.appendingPathComponent("synthetic-outside"))
        }
        #expect(f.scan().suggestions(prefix: "").isEmpty)
    }

    @Test func remoteSubsectionIsCaseSensitive() throws {
        let f = try TapFixture(), tap = try f.tap()
        try f.write("\(tap)/.git/config", "[remote \"ORIGIN\"]\n url = https://github.com/synthetic-owner/synthetic-repo\n")
        #expect(f.scan().repository(for: TapName("synthetic-owner/synthetic-tap")!) == nil)
    }
}

extension TapIndexTests {
    @Test func formulaDirectorySelectionFollowsDirectoryLinks() throws {
        let f = try TapFixture(), tap = try f.tap()
        try f.write("\(tap)/synthetic-formula-source/synthetic-tool.rb")
        try f.write("\(tap)/HomebrewFormula/synthetic-other.rb")
        try f.fm.createSymbolicLink(at: f.root.appendingPathComponent("\(tap)/Formula"),
                                   withDestinationURL: f.root.appendingPathComponent("\(tap)/synthetic-formula-source"))
        #expect(f.scan().suggestions(prefix: "").map(\.path) == ["Formula/synthetic-tool.rb"])
    }
}
