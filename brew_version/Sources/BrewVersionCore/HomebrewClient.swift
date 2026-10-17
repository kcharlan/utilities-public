import Foundation

public enum LookupError: Error, Equatable, Sendable {
    case unreachable(PackageName)
    case http(status: Int, PackageName)
    case invalidVersion(PackageKind, PackageName)
    case notFound(PackageName, KindPreference)

    public var cliMessage: String {
        switch self {
        case .unreachable(let name): "Error: could not reach Homebrew for \(name)."
        case .http(let status, let name): "Error: Homebrew returned HTTP \(status) for \(name)."
        case .invalidVersion(let kind, let name): "Error: no valid \(kind.rawValue) version returned for \(name)."
        case .notFound(let name, let preference): "Error: \(name) not found in Homebrew (\(preference.label))."
        }
    }

    public var rowMessage: String {
        switch self {
        case .unreachable: "Couldn't reach Homebrew."
        case .http(let status, _): "Homebrew returned HTTP \(status)."
        case .invalidVersion: "Homebrew returned no usable version."
        case .notFound: "Not found in Homebrew."
        }
    }
}

public struct CachedListing: Codable, Equatable, Sendable {
    public let etag: String
    public let listing: Listing

    public init(etag: String, listing: Listing) {
        self.etag = etag
        self.listing = listing
    }
}

public actor ListingCache {
    private var entries: [URL: CachedListing]
    public init(entries: [URL: CachedListing] = [:]) { self.entries = entries }
    public func entry(for url: URL) -> CachedListing? { entries[url] }
    public func store(_ entry: CachedListing, for url: URL) { entries[url] = entry }
    public func snapshot() -> [URL: CachedListing] { entries }
}

public struct HomebrewClient: Sendable {
    private let transport: any HTTPTransport
    private let cache: ListingCache?

    public init(transport: any HTTPTransport, cache: ListingCache? = nil) {
        self.transport = transport
        self.cache = cache
    }

    public func lookup(_ name: PackageName, kinds: KindPreference) async throws -> Listing {
        for kind in kinds.candidates {
            // PackageName admits only URL-path-safe characters.
            let url = URL(string: "https://formulae.brew.sh/api/\(kind.rawValue)/\(name.rawValue).json")!
            let cached = await cache?.entry(for: url)
            let response: HTTPResponse
            do { response = try await transport.get(url, ifNoneMatch: cached?.etag) }
            catch { throw LookupError.unreachable(name) }
            switch response.status {
            case 404: continue
            case 304:
                guard let cached else { throw LookupError.http(status: 304, name) }
                return cached.listing
            case 300...399: throw LookupError.unreachable(name)
            case 200:
                let listing = try Listing.decode(response.body, kind: kind, name: name)
                if let etag = response.etag {
                    await cache?.store(CachedListing(etag: etag, listing: listing), for: url)
                }
                return listing
            default: throw LookupError.http(status: response.status, name)
            }
        }
        throw LookupError.notFound(name, kinds)
    }
}
