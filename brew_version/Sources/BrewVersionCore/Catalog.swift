import Foundation

public struct Catalog: Sendable {
    private let listings: [Listing]
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

public struct CatalogClient: Sendable {
    private let transport: any HTTPTransport
    private let cacheDirectory: URL
    private var cacheFile: URL { cacheDirectory.appendingPathComponent("catalog.json") }

    public init(transport: any HTTPTransport, cacheDirectory: URL) {
        self.transport = transport; self.cacheDirectory = cacheDirectory
    }
    public static func makeTransport() -> URLSessionTransport {
        URLSessionTransport(requestTimeout: 10, resourceTimeout: 120)
    }
    public func cached() throws -> Catalog? { readCache()?.catalog }

    public func load() async throws -> CatalogFetch {
        // Bulk JSON decoding and disk I/O must never inherit the UI actor.
        try await Task.detached { try await self.fetch() }.value
    }
    private func fetch() async throws -> CatalogFetch {
        let previous = readCache()
        do {
            let formula = try await fetchList(.formula, previous: previous?.bytes.formula)
            let cask = try await fetchList(.cask, previous: previous?.bytes.cask)
            let bytes = CatalogBytes(formula: formula.bytes, cask: cask.bytes)
            let catalog = Catalog(listings: formula.listings + cask.listings)
            // Publish the two validated lists together: no partial refresh can poison a good pair.
            try FileManager.default.createDirectory(at: cacheDirectory, withIntermediateDirectories: true,
                                                    attributes: [.posixPermissions: 0o700])
            try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: cacheDirectory.path)
            try JSONEncoder().encode(bytes).write(to: cacheFile, options: .atomic)
            return CatalogFetch(catalog: catalog, revalidated: true)
        } catch {
            if let previous { return CatalogFetch(catalog: previous.catalog, revalidated: false) }
            throw error
        }
    }
    private func fetchList(_ kind: PackageKind, previous: CatalogListBytes?) async throws -> (bytes: CatalogListBytes, listings: [Listing]) {
        let url = URL(string: "https://formulae.brew.sh/api/\(kind.rawValue).json")!
        var response = try await transport.get(url, ifNoneMatch: previous?.etag)
        if response.status == 304, previous == nil {
            response = try await transport.get(url, ifNoneMatch: nil)
        }
        if response.status == 304, let previous {
            return (previous, try decodeList(previous.data, kind: kind))
        }
        guard response.status == 200 else { throw CatalogError.http(response.status) }
        let listings = try decodeList(response.body, kind: kind)
        return (CatalogListBytes(data: response.body, etag: response.etag), listings)
    }
    private func readCache() -> (bytes: CatalogBytes, catalog: Catalog)? {
        guard let data = try? Data(contentsOf: cacheFile),
              let bytes = try? JSONDecoder().decode(CatalogBytes.self, from: data),
              let formula = try? decodeList(bytes.formula.data, kind: .formula),
              let cask = try? decodeList(bytes.cask.data, kind: .cask) else { return nil }
        return (bytes, Catalog(listings: formula + cask))
    }
    private func decodeList(_ data: Data, kind: PackageKind) throws -> [Listing] {
        guard let objects = try JSONSerialization.jsonObject(with: data) as? [[String: Any]] else {
            throw CatalogError.invalidList
        }
        return objects.compactMap { object in
            guard let listing = Listing.decodeItem(object, kind: kind),
                  !listing.version.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
            return listing
        }
    }
}

private enum CatalogError: Error { case http(Int), invalidList }
private struct CatalogListBytes: Codable, Sendable {
    let data: Data
    let etag: String?
}
private struct CatalogBytes: Codable, Sendable {
    let formula: CatalogListBytes
    let cask: CatalogListBytes
}

public struct OtherUpdate: Equatable, Sendable {
    public var listing: Listing
    public var installed: InstalledVersion
}

public func otherUpdates(catalog: Catalog, installed: InstalledReader, watched: Set<PackageName>) -> [OtherUpdate] {
    installed.installedPackages().compactMap { package -> OtherUpdate? in
        guard !watched.contains(package.name),
              let listing = catalog.listing(for: package.name, kind: package.kind),
              let local = installed.installed(package.name, kind: package.kind, listing: listing),
              case .updateAvailable = updateStatus(listing: listing, installed: local) else { return nil }
        return OtherUpdate(listing: listing, installed: local)
    }.sorted {
        if $0.listing.name != $1.listing.name { return $0.listing.name.rawValue < $1.listing.name.rawValue }
        return $0.listing.kind.rawValue < $1.listing.kind.rawValue
    }
}
