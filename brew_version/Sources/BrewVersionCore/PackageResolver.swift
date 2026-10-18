import Foundation

public struct PackageResolver: Sendable {
    private let client: HomebrewClient
    private let tapClient: TapClient
    private let taps: TapIndex

    public init(client: HomebrewClient, tapClient: TapClient, taps: TapIndex) {
        self.client = client
        self.tapClient = tapClient
        self.taps = taps
    }

    /// Look up exactly the requested source; watched official names never drift
    /// into a tap merely because their official package has disappeared.
    public func lookup(_ name: PackageName, kinds: KindPreference) async throws -> Listing {
        guard let tap = name.tap else { return try await client.lookup(name, kinds: kinds) }
        guard taps.taps.contains(tap) else { throw LookupError.notTapped(tap) }
        for kind in kinds.candidates {
            if let entry = taps.entry(name, kind: kind) { return try await tapClient.lookup(entry) }
        }
        throw LookupError.notFoundInTap(name)
    }

    public func resolveBare(_ name: PackageName, kinds: KindPreference) async throws -> Listing {
        guard name.tap == nil else { return try await lookup(name, kinds: kinds) }
        do { return try await client.lookup(name, kinds: kinds) }
        catch let error as LookupError {
            guard case .notFound = error else { throw error }
            let matches = tapMatches(name, kinds: kinds)
            let identities = Set(matches.map(\.name)).sorted { $0.rawValue < $1.rawValue }
            guard let identity = identities.first else { throw error }
            guard identities.count == 1 else { throw LookupError.ambiguous(name.shortName, identities) }
            return try await lookup(identity, kinds: kinds)
        }
    }

    public func tapMatches(_ name: PackageName, kinds: KindPreference) -> [TapEntry] {
        taps.entries(shortName: name.shortName, kinds: kinds)
    }
}
