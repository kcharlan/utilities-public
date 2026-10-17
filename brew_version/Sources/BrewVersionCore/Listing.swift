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
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let listing = decodeObject(object, kind: kind, name: name)
        else { throw LookupError.invalidVersion(kind, name) }
        return listing
    }

    public static func decodeItem(_ object: [String: Any], kind: PackageKind) -> Listing? {
        guard let rawName = object[kind == .formula ? "name" : "token"] as? String,
              let name = PackageName(rawName) else { return nil }
        return decodeObject(object, kind: kind, name: name)
    }

    private static func decodeObject(_ object: [String: Any], kind: PackageKind, name: PackageName) -> Listing? {
        let rawVersion = kind == .formula ? (object["versions"] as? [String: Any])?["stable"] : object["version"]
        guard let version = rawVersion as? String, !version.isEmpty else { return nil }
        return Listing(name: name, kind: kind, version: version,
                       revision: object["revision"] as? Int ?? 0,
                       autoUpdates: object["auto_updates"] as? Bool ?? false,
                       summary: object["desc"] as? String,
                       homepage: (object["homepage"] as? String).flatMap(URL.init(string:)),
                       appNames: kind == .cask ? appNames(object["artifacts"]) : [])
    }

    private static func appNames(_ artifacts: Any?) -> [String] {
        guard let artifacts = artifacts as? [Any] else { return [] }
        return artifacts.compactMap { artifact in
            guard let object = artifact as? [String: Any], let args = object["app"] as? [Any] else { return nil }
            // Homebrew Relocated#initialize stores a target in the app argument list;
            // artifacts_list may also serialize a resolved sibling target.
            let argumentTarget = args.dropFirst().compactMap { ($0 as? [String: Any])?["target"] }.first
            let paths = [object["target"], argumentTarget, args.first]
            return paths.compactMap { value -> String? in
                guard let path = value as? String, !path.isEmpty else { return nil }
                let component = (path as NSString).lastPathComponent
                return component.isEmpty || component == "/" ? nil : component
            }.first
        }
    }
}
