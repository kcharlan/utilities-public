import Foundation
import BrewVersionCore

@MainActor enum SyntheticEnvironment {
    static func makeController(service: SyntheticTransport, notifier: UserNotifier) -> WatchController {
        guard let path = Bundle.main.object(forInfoDictionaryKey: "SyntheticAcceptanceHome") as? String,
              path.hasPrefix("/"), FileManager.default.fileExists(atPath: path) else { fatalError("Explicit acceptance home missing") }
        let home = URL(fileURLWithPath: path)
        let prefix = home.appendingPathComponent("synthetic-prefix")
        let keg = prefix.appendingPathComponent("Cellar/synthetic-installed/1.0-synthetic")
        let fallback = prefix.appendingPathComponent("Caskroom/synthetic-fallback/1.0-synthetic")
        do {
            try FileManager.default.createDirectory(at: keg, withIntermediateDirectories: true)
            try FileManager.default.createDirectory(at: fallback, withIntermediateDirectories: true)
            try Data("{\"source\":{\"tap\":\"homebrew/core\"}}".utf8).write(to: keg.appendingPathComponent("INSTALL_RECEIPT.json"))
        } catch { fatalError("Cannot create synthetic inventory: \(error)") }
        return WatchController(transport: service,
            installed: InstalledReader(prefixes: HomebrewPrefix.detectAll(candidates: [prefix]), applicationDirectories: []),
            store: WatchStore(fileURL: home.appendingPathComponent("state/state.json")), notifier: notifier,
            catalogClient: CatalogClient(transport: service, cacheDirectory: home.appendingPathComponent("catalog")))
    }
}
