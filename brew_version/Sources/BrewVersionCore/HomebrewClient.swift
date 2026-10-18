import Foundation

public enum LookupError: Error, Equatable, Sendable {
    case unreachable(PackageName)
    case http(status: Int, PackageName)
    case invalidVersion(PackageKind, PackageName)
    case notFound(PackageName, KindPreference)
    case notTapped(TapName)
    case unsupportedTapRemote(TapName)
    case notFoundInTap(PackageName)
    case unreadableTapVersion(PackageName)
    case tapUnreachable(PackageName)
    case tapHTTP(status: Int, PackageName)
    case ambiguous(String, [PackageName])

    public var cliMessage: String {
        switch self {
        case .unreachable(let name): "Error: could not reach Homebrew for \(name)."
        case .http(let status, let name): "Error: Homebrew returned HTTP \(status) for \(name)."
        case .invalidVersion(let kind, let name): "Error: no valid \(kind.rawValue) version returned for \(name)."
        case .notFound(let name, let preference): "Error: \(name) not found in Homebrew (\(preference.label))."
        case .notTapped(let tap): "Error: \(tap) is not tapped."
        case .unsupportedTapRemote(let tap): "Error: \(tap) is not hosted on GitHub."
        case .notFoundInTap(let name): "Error: \(name) not found in \(name.tap!.description)."
        case .unreadableTapVersion(let name): "Error: could not read a version for \(name)."
        case .tapUnreachable(let name): "Error: could not reach GitHub for \(name)."
        case .tapHTTP(let status, let name): "Error: GitHub returned HTTP \(status) for \(name)."
        case .ambiguous(let name, let matches):
            "Error: \(name) matches several taps: \(matches.map(\.rawValue).sorted().joined(separator: ", ")). Use the full name."
        }
    }

    public var rowMessage: String {
        switch self {
        case .unreachable: "Couldn't reach Homebrew."
        case .http(let status, _): "Homebrew returned HTTP \(status)."
        case .invalidVersion: "Homebrew returned no usable version."
        case .notFound: "Not found in Homebrew."
        case .notTapped(let tap): "\(tap) is no longer tapped."
        case .unsupportedTapRemote: "Only taps hosted on GitHub can be checked."
        case .notFoundInTap(let name): "Not found in \(name.tap!.description)."
        case .unreadableTapVersion: "Can't read this tap's version."
        case .tapUnreachable: "Couldn't reach GitHub."
        case .tapHTTP(let status, _): "GitHub returned HTTP \(status)."
        case .ambiguous(let name, _): "\(name) matches several taps. Use the full name."
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
    private let storage: ListingCacheStorage
    public init(entries: [URL: CachedListing] = [:]) { storage = ListingCacheStorage(entries: entries) }
    public func entry(for url: URL) -> CachedListing? { storage.entry(for: url) }
    public func store(_ entry: CachedListing, for url: URL) { storage.store(entry, for: url) }
    // Final controller merges need an immediate value snapshot, without an actor
    // hop that could replace the caller's listing-dependent installation capture.
    public nonisolated func snapshot() -> [URL: CachedListing] { storage.snapshot() }
}

// All mutable dictionary access stays under this lock. Returned dictionaries
// have value semantics; no mutable reference or storage pointer escapes.
private final class ListingCacheStorage: @unchecked Sendable {
    private let lock = NSLock()
    private var entries: [URL: CachedListing]
    init(entries: [URL: CachedListing]) { self.entries = entries }
    func entry(for url: URL) -> CachedListing? { lock.withLock { entries[url] } }
    func store(_ entry: CachedListing, for url: URL) { lock.withLock { entries[url] = entry } }
    func snapshot() -> [URL: CachedListing] { lock.withLock { entries } }
}

public struct HomebrewClient: Sendable {
    private let transport: any HTTPTransport
    private let cache: ListingCache?

    public init(transport: any HTTPTransport, cache: ListingCache? = nil) {
        self.transport = transport
        self.cache = cache
    }

    public func lookup(_ name: PackageName, kinds: KindPreference) async throws -> Listing {
        guard name.tap == nil else { throw LookupError.notFound(name, kinds) }
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
