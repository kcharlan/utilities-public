import Foundation

public struct Catalog: Sendable {
    let listings: [Listing]
    private let byKind: [PackageKind: [PackageName: Listing]]
    init(listings: [Listing]) {
        var byKind: [PackageKind: [PackageName: Listing]] = [:]
        for listing in listings { byKind[listing.kind, default: [:]][listing.name] = listing }
        self.byKind = byKind
        self.listings = listings.sorted {
            if $0.name != $1.name { return $0.name.rawValue < $1.name.rawValue }
            return $0.kind.rawValue < $1.kind.rawValue
        }
    }
    public func listing(for name: PackageName, kind: PackageKind) -> Listing? {
        byKind[kind]?[name]
    }
    public func suggestions(prefix: String, limit: Int = 8) -> [(name: PackageName, kind: PackageKind)] {
        guard limit > 0 else { return [] }
        return listings.lazy.filter { $0.name.rawValue.hasPrefix(prefix) }.prefix(limit).map { ($0.name, $0.kind) }
    }
}

public struct CatalogFetch: Sendable {
    public let catalog: Catalog
    public let revalidated: Bool
}

public actor CatalogClient {
    private let transport: any HTTPTransport
    private let cacheDirectory: URL
    private var cacheFile: URL { cacheDirectory.appendingPathComponent("catalog.json") }
    private var previous: CatalogIndex?
    private var didReadCache = false

    public init(transport: any HTTPTransport, cacheDirectory: URL) {
        self.transport = transport; self.cacheDirectory = cacheDirectory
    }
    public nonisolated static func makeTransport() -> URLSessionTransport {
        URLSessionTransport(requestTimeout: 10, resourceTimeout: 120)
    }
    public func cached() throws -> Catalog? { readCache()?.catalog }

    public func load() async throws -> CatalogFetch {
        try await fetch()
    }
    private func fetch() async throws -> CatalogFetch {
        let previous = readCache()
        do {
            let formula = try await fetchList(.formula, previous: previous?.formula)
            let cask = try await fetchList(.cask, previous: previous?.cask)
            let index = CatalogIndex(schema: 1, formula: formula, cask: cask)
            // Publish the two validated lists together: no partial refresh can poison a good pair.
            try FileManager.default.createDirectory(at: cacheDirectory, withIntermediateDirectories: true,
                                                    attributes: [.posixPermissions: 0o700])
            try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: cacheDirectory.path)
            try JSONEncoder().encode(index).write(to: cacheFile, options: .atomic)
            self.previous = index
            return CatalogFetch(catalog: index.catalog, revalidated: true)
        } catch {
            if let previous { return CatalogFetch(catalog: previous.catalog, revalidated: false) }
            throw error
        }
    }
    private func fetchList(_ kind: PackageKind, previous: CatalogListIndex?) async throws -> CatalogListIndex {
        let url = URL(string: "https://formulae.brew.sh/api/\(kind.rawValue).json")!
        var response = try await transport.get(url, ifNoneMatch: previous?.etag)
        if response.status == 304, previous == nil {
            response = try await transport.get(url, ifNoneMatch: nil)
        }
        if response.status == 304, let previous {
            return previous
        }
        guard response.status == 200 else { throw CatalogError.http(response.status) }
        let listings = try Listing.decodeList(response.body, kind: kind)
        return CatalogListIndex(listings: listings, etag: response.etag)
    }
    private func readCache() -> CatalogIndex? {
        guard !didReadCache else { return previous }
        didReadCache = true
        guard let data = try? Data(contentsOf: cacheFile),
              let index = try? JSONDecoder().decode(CatalogIndex.self, from: data), index.schema == 1,
              index.formula.valid(kind: .formula), index.cask.valid(kind: .cask) else { return nil }
        previous = index
        return index
    }
}

private enum CatalogError: Error { case http(Int) }
private struct CatalogListIndex: Codable, Sendable {
    let listings: [Listing]
    let etag: String?
    func valid(kind: PackageKind) -> Bool {
        !listings.isEmpty && listings.allSatisfy {
            $0.kind == kind && !$0.version.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && (kind == .cask || $0.revision >= 0)
        }
    }
}
private struct CatalogIndex: Codable, Sendable {
    let schema: Int
    let formula: CatalogListIndex
    let cask: CatalogListIndex
    var catalog: Catalog { Catalog(listings: formula.listings + cask.listings) }
}

public struct OtherUpdate: Equatable, Sendable {
    public var listing: Listing
    public var installed: InstalledVersion
}

public func otherUpdates(catalog: Catalog, installed: InstalledReader, watched: Set<PackageName>) -> [OtherUpdate] {
    otherUpdates(catalog: catalog, snapshot: installed.snapshot(listings: catalog.listings), watched: watched)
}

public func otherUpdates(catalog: Catalog, snapshot: InstalledSnapshot, watched: Set<PackageName>) -> [OtherUpdate] {
    catalog.listings.compactMap { listing -> OtherUpdate? in
        guard !watched.contains(listing.name),
              let local = snapshot.installed(listing.name, kind: listing.kind),
              case .updateAvailable = updateStatus(listing: listing, installed: local) else { return nil }
        return OtherUpdate(listing: listing, installed: local)
    }.sorted {
        if $0.listing.name != $1.listing.name { return $0.listing.name.rawValue < $1.listing.name.rawValue }
        return $0.listing.kind.rawValue < $1.listing.kind.rawValue
    }
}
