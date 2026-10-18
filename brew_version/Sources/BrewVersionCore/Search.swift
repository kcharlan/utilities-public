import Foundation

public enum SearchToken: Equatable, Sendable { case valid(PackageName), invalid(String) }
public func tokenize(_ text: String) -> [SearchToken] {
    var seen: Set<String> = []
    return text.split(whereSeparator: \.isWhitespace).compactMap { part in
        let value = String(part)
        guard seen.insert(value).inserted else { return nil }
        return PackageName(value).map(SearchToken.valid) ?? .invalid(value)
    }
}
public enum LookupResult: Equatable, Sendable {
    case found(Listing, installed: InstalledVersion?, watched: Bool)
    case notFound(PackageName), failed(PackageName, String), invalid(String)
}

// One controller-wide permit pool bounds checks, adds and search together.
actor LookupScheduler {
    private var active = 0
    private var waiting: [CheckedContinuation<Void, Never>] = []
    func lookup(_ name: PackageName, kinds: KindPreference, client: HomebrewClient) async throws -> Listing {
        try Task.checkCancellation()
        if active == 4 { await withCheckedContinuation { waiting.append($0) } }
        else { active += 1 }
        defer {
            if waiting.isEmpty { active -= 1 }
            else { waiting.removeFirst().resume() }
        }
        try Task.checkCancellation()
        return try await client.lookup(name, kinds: kinds)
    }
}
