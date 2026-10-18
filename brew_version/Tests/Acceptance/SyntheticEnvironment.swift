import Foundation
import BrewVersionCore

@MainActor enum SyntheticEnvironment {
    static var now = Date()
    static func advanceRefreshClock() { now = now.addingTimeInterval(601) }
    static func setTapPresent(_ present: Bool, home: URL) throws {
        let tap = home.appendingPathComponent("synthetic-prefix/Library/Taps/synthetic-owner/homebrew-synthetic-tap")
        let parked = home.appendingPathComponent("synthetic-parked-tap")
        let source = present ? parked : tap
        let destination = present ? tap : parked
        if FileManager.default.fileExists(atPath: source.path) { try FileManager.default.moveItem(at: source, to: destination) }
    }
    static func setTapPresent(_ present: Bool) {
        guard let path = Bundle.main.object(forInfoDictionaryKey: "SyntheticAcceptanceHome") as? String else { fatalError("Explicit acceptance home missing") }
        do { try setTapPresent(present, home: URL(fileURLWithPath: path)) }
        catch { fatalError("Cannot change synthetic tap: \(error)") }
    }
    static func prepareTapFixtures(home: URL) throws -> URL {
        let prefix = home.appendingPathComponent("synthetic-prefix")
        let tap = prefix.appendingPathComponent("Library/Taps/synthetic-owner/homebrew-synthetic-tap")
        for path in [".git", "Formula", "Casks"] {
            try FileManager.default.createDirectory(at: tap.appendingPathComponent(path), withIntermediateDirectories: true)
        }
        try Data("[remote \"origin\"]\nurl = https://github.com/synthetic-owner/homebrew-synthetic-tap.git\n".utf8).write(to: tap.appendingPathComponent(".git/config"))
        for (name, kind) in [("synthetic-tool", "Formula"), ("synthetic-shared", "Formula"), ("synthetic-app", "Casks")] {
            try Data("# Synthetic discovery only\n".utf8).write(to: tap.appendingPathComponent("\(kind)/\(name).rb"))
            let receipt = kind == "Formula" ? "Cellar/\(name)/1.0-synthetic" : "Caskroom/\(name)/.metadata"
            let directory = prefix.appendingPathComponent(receipt)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            if kind == "Casks" { try FileManager.default.createDirectory(at: prefix.appendingPathComponent("Caskroom/\(name)/1.0-synthetic"), withIntermediateDirectories: true) }
            try Data(#"{"source":{"tap":"synthetic-owner/synthetic-tap"}}"#.utf8).write(to: directory.appendingPathComponent("INSTALL_RECEIPT.json"))
        }
        return prefix
    }
    static func makeController(service: SyntheticTransport, notifier: UserNotifier) -> WatchController {
        guard let path = Bundle.main.object(forInfoDictionaryKey: "SyntheticAcceptanceHome") as? String,
              path.hasPrefix("/"), FileManager.default.fileExists(atPath: path) else { fatalError("Explicit acceptance home missing") }
        let home = URL(fileURLWithPath: path)
        let prefix = home.appendingPathComponent("synthetic-prefix")
        let keg = prefix.appendingPathComponent("Cellar/synthetic-installed/1.0-synthetic")
        let fallback = prefix.appendingPathComponent("Caskroom/synthetic-fallback/1.0-synthetic")
        do {
            _ = try prepareTapFixtures(home: home)
            try FileManager.default.createDirectory(at: keg, withIntermediateDirectories: true)
            try FileManager.default.createDirectory(at: fallback, withIntermediateDirectories: true)
            try Data("{\"source\":{\"tap\":\"homebrew/core\"}}".utf8).write(to: keg.appendingPathComponent("INSTALL_RECEIPT.json"))
        } catch { fatalError("Cannot create synthetic inventory: \(error)") }
        return WatchController(transport: service,
            installed: InstalledReader(prefixes: HomebrewPrefix.detectAll(candidates: [prefix]), applicationDirectories: [], tappedTaps: { TapIndex.scan(prefixes: HomebrewPrefix.detectAll(candidates: [prefix])).taps }),
            store: WatchStore(fileURL: home.appendingPathComponent("state/state.json")), notifier: notifier, now: { now },
            catalogClient: CatalogClient(transport: service, cacheDirectory: home.appendingPathComponent("catalog")),
            taps: { TapIndex.scan(prefixes: HomebrewPrefix.detectAll(candidates: [prefix])) })
    }
}
