import Foundation

public struct HomebrewPrefix: Sendable {
    public let root: URL
    public static func detectAll(candidates: [URL]) -> [HomebrewPrefix] {
        candidates.filter { root in
            ["Cellar", "Caskroom"].contains { isDirectory(root.appendingPathComponent($0)) }
        }.map { HomebrewPrefix(root: $0) }
    }
}

public enum InstalledSource: String, Codable, Sendable { case cellar, caskroom, appBundle, caskroomFallback }
public struct InstalledVersion: Equatable, Codable, Sendable {
    public var version: String
    public var source: InstalledSource
    public init(version: String, source: InstalledSource) { self.version = version; self.source = source }
}

public struct InstalledSnapshot: Sendable {
    var versions: [PackageKind: [PackageName: InstalledVersion]] = [:]
    public init() {}
    public func installed(_ name: PackageName, kind: PackageKind) -> InstalledVersion? { versions[kind]?[name] }
}

public protocol InstalledReading: Sendable {
    func snapshot(listings: [Listing]) -> InstalledSnapshot
    func installed(_ name: PackageName, kind: PackageKind, listing: Listing?) -> InstalledVersion?
}

public struct InstalledReader: InstalledReading {
    private let prefixes: [HomebrewPrefix]
    private let applicationDirectories: [URL]
    private let readData: @Sendable (URL) throws -> Data
    private let tappedTaps: @Sendable () -> Set<TapName>
    public init(prefixes: [HomebrewPrefix], applicationDirectories: [URL], tappedTaps: @escaping @Sendable () -> Set<TapName> = { [] }) {
        self.init(prefixes: prefixes, applicationDirectories: applicationDirectories, readData: { try Data(contentsOf: $0) }, tappedTaps: tappedTaps)
    }
    init(prefixes: [HomebrewPrefix], applicationDirectories: [URL], readData: @escaping @Sendable (URL) throws -> Data, tappedTaps: @escaping @Sendable () -> Set<TapName> = { [] }) {
        self.prefixes = prefixes
        self.applicationDirectories = applicationDirectories
        self.readData = readData
        self.tappedTaps = tappedTaps
    }

    public func installed(_ name: PackageName, kind: PackageKind, listing: Listing?) -> InstalledVersion? {
        for prefix in prefixes {
            guard let installation = admittedVersion(name, kind: kind, prefix: prefix),
                  installation.name == name else { continue }
            return resolvedVersion(installation.version, kind: kind, listing: listing)
        }
        return nil
    }

    private func resolvedVersion(_ version: String, kind: PackageKind, listing: Listing?) -> InstalledVersion {
        if kind == .formula { return .init(version: version, source: .cellar) }
        if let listing, listing.autoUpdates {
            for directory in applicationDirectories {
                for app in listing.appNames where app == (app as NSString).lastPathComponent && app.hasSuffix(".app") {
                    let plist = directory.appendingPathComponent(app).appendingPathComponent("Contents/Info.plist")
                    if let data = try? readData(plist),
                       let object = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
                       let version = object["CFBundleShortVersionString"] as? String,
                       !version.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        return .init(version: version, source: .appBundle)
                    }
                }
            }
            return .init(version: version, source: .caskroomFallback)
        }
        return .init(version: version, source: .caskroom)
    }

    public func installedPackages() -> [(name: PackageName, kind: PackageKind)] {
        snapshot(listings: []).versions.flatMap { kind, versions in versions.keys.map { ($0, kind) } }
    }

    /// Admit each rack once, retaining its selected version and provenance for
    /// both watch evaluation and Other updates. No second receipt pass is needed.
    public func snapshot(listings: [Listing]) -> InstalledSnapshot {
        var byKind: [PackageKind: [PackageName: Listing]] = [:]
        for listing in listings { byKind[listing.kind, default: [:]][listing.name] = listing }
        var result = InstalledSnapshot()
        for prefix in prefixes {
            for kind in [PackageKind.formula, .cask] {
                for rack in directories(prefix.root.appendingPathComponent(kind == .formula ? "Cellar" : "Caskroom")) {
                    guard let shortName = PackageName(rack.lastPathComponent),
                          let installation = admittedVersion(shortName, kind: kind, prefix: prefix),
                          result.versions[kind]?[installation.name] == nil else { continue }
                    let name = installation.name
                    result.versions[kind, default: [:]][name] = resolvedVersion(installation.version, kind: kind, listing: byKind[kind]?[name])
                }
            }
        }
        return result
    }

    // Receipt layout follows Homebrew at 19fe946b9a257cb41ebb5cef5c592ba7923d1f3b:
    // Tab.for_keg (tab/tab.rb), Cask::Tab.for_cask (cask/tab.rb),
    // Cask::Metadata#metadata_main_container_path and AbstractTab.create (tab.rb).
    // Legacy casks may lack a receipt; explicit invalid provenance is still rejected.
    // Formulas always require a receipt. Both read paths use the receipt's
    // admitted identity, so a tap rack can never satisfy an official watch.
    private func admittedVersion(_ name: PackageName, kind: PackageKind, prefix: HomebrewPrefix) -> (name: PackageName, version: String)? {
        let shortName = name.shortName
        let rack = prefix.root.appendingPathComponent(kind == .formula ? "Cellar" : "Caskroom").appendingPathComponent(shortName)
        guard isDirectory(rack) else { return nil }
        let versions = directories(rack).filter { !isSymbolicLink($0) }
        let selected: URL?
        if kind == .formula {
            let opt = prefix.root.appendingPathComponent("opt").appendingPathComponent(shortName)
            let resolved = opt.resolvingSymlinksInPath().standardizedFileURL
            if isSymbolicLink(opt), isDirectory(resolved),
               resolved.deletingLastPathComponent() == rack.resolvingSymlinksInPath().standardizedFileURL {
                selected = resolved
            } else { selected = highest(versions, kind: kind) }
        } else { selected = highest(versions, kind: kind) }
        guard let selected else { return nil }
        let receiptDirectory = kind == .formula ? selected : rack.appendingPathComponent(".metadata")
        let receipt = receiptDirectory.appendingPathComponent("INSTALL_RECEIPT.json")
        let data: Data
        do { data = try readData(receipt) }
        catch {
            if kind == .cask, (error as? CocoaError)?.code == .fileReadNoSuchFile,
               !isSymbolicLink(receipt), let officialName = PackageName(shortName) {
                return (officialName, selected.lastPathComponent)
            }
            return nil
        }
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let source = object["source"] as? [String: Any],
              let rawTap = source["tap"] as? String,
              let tap = TapName(rawTap) else { return nil }
        let admittedName: PackageName?
        if tap.isOfficial {
            guard tap.description == (kind == .formula ? "homebrew/core" : "homebrew/cask") else { return nil }
            admittedName = PackageName(shortName)
        } else {
            guard tappedTaps().contains(tap) else { return nil }
            // Use the receipt input: composing with an already normalized tap
            // would remove a second reserved repository prefix.
            admittedName = PackageName("\(rawTap)/\(shortName)")
        }
        guard let admittedName else { return nil }
        return (admittedName, selected.lastPathComponent)
    }
    private func highest(_ versions: [URL], kind: PackageKind) -> URL? {
        // Stable filename order makes equal or asymmetric upstream comparisons deterministic.
        versions.reduce(nil) { best, candidate in
            guard let best else { return candidate }
            let comparison = kind == .formula
                ? FormulaVersion(keg: candidate.lastPathComponent).compare(FormulaVersion(keg: best.lastPathComponent))
                : VersionOrder.compare(candidate.lastPathComponent, best.lastPathComponent)
            return comparison == .orderedDescending ? candidate : best
        }
    }
}

private func isDirectory(_ url: URL) -> Bool {
    var directory: ObjCBool = false
    return FileManager.default.fileExists(atPath: url.path, isDirectory: &directory) && directory.boolValue
}
private func isSymbolicLink(_ url: URL) -> Bool {
    (try? url.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink) == true
}
private func directories(_ url: URL) -> [URL] {
    ((try? FileManager.default.contentsOfDirectory(at: url, includingPropertiesForKeys: [.isDirectoryKey, .isSymbolicLinkKey], options: .skipsHiddenFiles)) ?? [])
        .filter(isDirectory).sorted { $0.lastPathComponent < $1.lastPathComponent }
}
