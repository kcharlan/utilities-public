import Foundation

// Tap aliases follow Homebrew tap.rb/tap_constants.rb at
// 3073d6a8c34f71da054b000cfdbb62594a07c969. Canonicalize case before
// alias dispatch so equality and persisted names have a stable identity.
public struct TapName: Hashable, Codable, Sendable, CustomStringConvertible {
    public let user: String
    public let repo: String

    public init?(_ raw: String) {
        let parts = raw.lowercased().split(separator: "/", omittingEmptySubsequences: false)
        guard parts.count == 2 else { return nil }
        var user = String(parts[0])
        var repo = String(parts[1])
        for prefix in ["homebrew-", "linuxbrew-"] where repo.hasPrefix(prefix) {
            repo.removeFirst(prefix.count)
            break
        }
        if ["homebrew", "linuxbrew"].contains(user), ["core", "homebrew"].contains(repo) {
            user = "homebrew"; repo = "core"
        }
        self.init(canonical: "\(user)/\(repo)")
    }

    // Canonical repository names may still begin with a reserved prefix:
    // Homebrew removes only one prefix from typed/directory-derived input.
    // Reading a saved identity must validate it without normalizing it again.
    fileprivate init?(canonical raw: String) {
        let parts = raw.split(separator: "/", omittingEmptySubsequences: false)
        guard parts.count == 2 else { return nil }
        let user = String(parts[0]), repo = String(parts[1])
        guard Self.validSegment(user), Self.validSegment(repo) else { return nil }
        self.user = user; self.repo = repo
    }

    private static func validSegment(_ raw: String) -> Bool {
        guard let first = raw.utf8.first, isAlphanumeric(first) else { return false }
        return raw.utf8.allSatisfy { isAlphanumeric($0) || [95, 46, 45].contains($0) }
    }
    private static func isAlphanumeric(_ byte: UInt8) -> Bool {
        (97...122).contains(byte) || (48...57).contains(byte)
    }
    public var description: String { "\(user)/\(repo)" }
    public var isOfficial: Bool { user == "homebrew" && ["core", "cask"].contains(repo) }

    public init(from decoder: any Decoder) throws {
        let c = try decoder.singleValueContainer()
        guard let tap = Self(canonical: try c.decode(String.self)) else {
            throw DecodingError.dataCorruptedError(in: c, debugDescription: "Invalid Homebrew tap name")
        }
        self = tap
    }
    public func encode(to encoder: any Encoder) throws {
        var c = encoder.singleValueContainer()
        try c.encode(description)
    }
}

public struct PackageName: Hashable, Codable, Sendable, CustomStringConvertible {
    public let rawValue: String
    public var tap: TapName? {
        let parts = rawValue.split(separator: "/")
        return parts.count == 3 ? TapName(canonical: parts.prefix(2).joined(separator: "/")) : nil
    }
    public var shortName: String { String(rawValue.split(separator: "/").last!) }

    public init?(_ raw: String) {
        self.init(raw, normalizeTap: true)
    }

    private init?(_ raw: String, normalizeTap: Bool) {
        let parts = raw.split(separator: "/", omittingEmptySubsequences: false)
        let short: String
        let tap: TapName?
        if parts.count == 3 {
            let rawTap = parts.prefix(2).joined(separator: "/")
            guard let source = normalizeTap ? TapName(rawTap) : TapName(canonical: rawTap),
                  !source.isOfficial else { return nil }
            tap = source; short = String(parts[2])
        } else if parts.count == 1 {
            tap = nil; short = raw
        } else { return nil }
        guard let first = short.utf8.first,
              Self.isAlphanumeric(first),
              short.utf8.allSatisfy({ Self.isAlphanumeric($0) || [64, 43, 46, 95, 45].contains($0) })
        else { return nil }
        rawValue = tap.map { "\($0)/\(short)" } ?? short
    }

    private static func isAlphanumeric(_ byte: UInt8) -> Bool {
        (97...122).contains(byte) || (48...57).contains(byte)
    }

    public var description: String { rawValue }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.singleValueContainer()
        let raw = try container.decode(String.self)
        guard let name = Self(raw, normalizeTap: false) else {
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Invalid Homebrew package name")
        }
        self = name
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }
}

public enum PackageKind: String, Codable, Sendable {
    case formula, cask
}

public enum KindPreference: Sendable, Equatable {
    case auto, formula, cask

    public init(_ kind: PackageKind) {
        self = kind == .formula ? .formula : .cask
    }

    public var candidates: [PackageKind] {
        switch self {
        case .auto: [.formula, .cask]
        case .formula: [.formula]
        case .cask: [.cask]
        }
    }

    public var label: String { candidates.map(\.rawValue).joined(separator: " ") }
}
