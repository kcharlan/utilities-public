import Foundation

public struct TapClient: Sendable {
    private let transport: any HTTPTransport
    private let cache: ListingCache?

    public init(transport: any HTTPTransport, cache: ListingCache? = nil) {
        self.transport = transport
        self.cache = cache
    }

    public func lookup(_ entry: TapEntry) async throws -> Listing {
        guard let repository = entry.repository else {
            throw LookupError.unsupportedTapRemote(entry.name.tap!)
        }
        // Encode components separately: a file or repository name cannot add a
        // query, fragment, or path separator to the fixed HTTPS origin.
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-._~"))
        let components = [repository.owner, repository.repo, "HEAD"] + entry.path.split(separator: "/").map(String.init)
        let path = components.map { $0.addingPercentEncoding(withAllowedCharacters: allowed)! }.joined(separator: "/")
        let url = URL(string: "https://raw.githubusercontent.com/\(path)")!
        // A tap alias can share a URL with another identity. Its parsed listing
        // is usable only for the requested package and kind.
        let candidate = await cache?.entry(for: url)
        let cached = candidate.flatMap {
            $0.listing.name == entry.name && $0.listing.kind == entry.kind ? $0 : nil
        }
        let response: HTTPResponse
        do { response = try await transport.get(url, ifNoneMatch: cached?.etag) }
        catch { throw LookupError.tapUnreachable(entry.name) }
        switch response.status {
        case 200:
            guard let text = String(data: response.body, encoding: .utf8),
                  let listing = TapFileReader.listing(from: text, name: entry.name, kind: entry.kind) else {
                throw LookupError.unreadableTapVersion(entry.name)
            }
            if let etag = response.etag {
                await cache?.store(CachedListing(etag: etag, listing: listing), for: url)
            }
            return listing
        case 304:
            guard let cached else { throw LookupError.tapHTTP(status: 304, entry.name) }
            return cached.listing
        case 404: throw LookupError.notFoundInTap(entry.name)
        case 300...399: throw LookupError.tapUnreachable(entry.name)
        default: throw LookupError.tapHTTP(status: response.status, entry.name)
        }
    }
}
