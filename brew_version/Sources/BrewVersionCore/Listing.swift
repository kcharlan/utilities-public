import Foundation

public struct Listing: Codable, Equatable, Sendable {
    public let name: PackageName
    public let kind: PackageKind
    public let version: String
    public let revision: Int
    public let autoUpdates: Bool
    public let summary: String?
    public let homepage: URL?
    public let appNames: [String]

    public init(name: PackageName, kind: PackageKind, version: String, revision: Int = 0,
                autoUpdates: Bool = false, summary: String? = nil, homepage: URL? = nil,
                appNames: [String] = []) {
        self.name = name
        self.kind = kind
        self.version = version
        self.revision = revision
        self.autoUpdates = autoUpdates
        self.summary = summary
        self.homepage = homepage
        self.appNames = appNames
    }

    public static func decode(_ data: Data, kind: PackageKind, name: PackageName) throws -> Listing {
        guard let fields = try? JSONDecoder().decode(ListingFields.self, from: data),
              let listing = fields.listing(kind: kind, name: name)
        else { throw LookupError.invalidVersion(kind, name) }
        return listing
    }

    public static func decodeItem(_ object: [String: Any], kind: PackageKind) -> Listing? {
        guard let data = try? JSONSerialization.data(withJSONObject: object),
              let fields = try? JSONDecoder().decode(ListingFields.self, from: data) else { return nil }
        return fields.listing(kind: kind)
    }
    static func decodeList(_ data: Data, kind: PackageKind) throws -> [Listing] {
        let decoder = JSONDecoder()
        decoder.userInfo[.listingKind] = kind
        let listings = try decoder.decode(ListingList.self, from: data).listings
        guard !listings.isEmpty else { throw CocoaError(.coderReadCorrupt) }
        return listings
    }
}

private extension CodingUserInfoKey {
    static let listingKind = CodingUserInfoKey(rawValue: "listingKind")!
}
private struct ListingList: Decodable {
    let listings: [Listing]
    init(from decoder: any Decoder) throws {
        var items = try decoder.unkeyedContainer()
        let kind = decoder.userInfo[.listingKind] as! PackageKind
        var result: [Listing] = []
        while !items.isAtEnd {
            let item = try items.superDecoder()
            guard let fields = try? ListingFields(from: item) else {
                throw CocoaError(.coderReadCorrupt)
            }
            if let listing = fields.listing(kind: kind) { result.append(listing) }
        }
        listings = result
    }
}

// Decode only fields used by Listing. Unknown bottle/dependency metadata never
// becomes a Foundation object graph or a persisted copy of the API response.
private struct ListingFields: Decodable {
    let name: String?, token: String?, version: String?, stable: String?
    let revision: Int, autoUpdates: Bool
    let summary: String?, homepage: String?
    let appNames: [String]
    enum Keys: String, CodingKey { case name, token, version, versions, stable, revision, auto_updates, desc, homepage, artifacts }
    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        name = try? c.decode(String.self, forKey: .name)
        token = try? c.decode(String.self, forKey: .token)
        version = try? c.decode(String.self, forKey: .version)
        stable = (try? c.nestedContainer(keyedBy: Keys.self, forKey: .versions)).flatMap { try? $0.decode(String.self, forKey: .stable) }
        revision = (try? c.decode(Int.self, forKey: .revision)) ?? 0
        autoUpdates = (try? c.decode(Bool.self, forKey: .auto_updates)) ?? false
        summary = try? c.decode(String.self, forKey: .desc)
        homepage = try? c.decode(String.self, forKey: .homepage)
        var names: [String] = []
        if var artifacts = try? c.nestedUnkeyedContainer(forKey: .artifacts) {
            while !artifacts.isAtEnd {
                let item = try artifacts.superDecoder()
                if let artifact = try? AppArtifact(from: item), let name = artifact.name { names.append(name) }
            }
        }
        appNames = names
    }
    func listing(kind: PackageKind, name explicitName: PackageName? = nil) -> Listing? {
        guard let name = explicitName ?? (kind == .formula ? name : token).flatMap(PackageName.init),
              let version = kind == .formula ? stable : version,
              !version.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              kind == .cask || revision >= 0 else { return nil }
        return Listing(name: name, kind: kind, version: version, revision: revision,
                       autoUpdates: autoUpdates, summary: summary, homepage: homepage.flatMap(URL.init(string:)),
                       appNames: kind == .cask ? appNames : [])
    }
}
private struct AppArtifact: Decodable {
    let name: String?
    enum Keys: String, CodingKey { case app, target }
    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        guard var args = try? c.nestedUnkeyedContainer(forKey: .app) else { name = nil; return }
        var source: String?, argumentTarget: String?
        var index = 0
        while !args.isAtEnd {
            let argument = try args.superDecoder()
            if index == 0 { source = try? argument.singleValueContainer().decode(String.self) }
            else if argumentTarget == nil, let target = try? argument.container(keyedBy: Keys.self) {
                argumentTarget = try? target.decode(String.self, forKey: .target)
            }
            index += 1
        }
        name = [(try? c.decode(String.self, forKey: .target)), argumentTarget, source].compactMap { path -> String? in
            guard let path, !path.isEmpty else { return nil }
            let component = (path as NSString).lastPathComponent
            return component.isEmpty || component == "/" ? nil : component
        }.first
    }
}
