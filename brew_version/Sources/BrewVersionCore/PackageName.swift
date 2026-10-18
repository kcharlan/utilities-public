import Foundation

public struct PackageName: Hashable, Codable, Sendable, CustomStringConvertible {
    public let rawValue: String

    public init?(_ raw: String) {
        guard let first = raw.utf8.first,
              Self.isAlphanumeric(first),
              raw.utf8.allSatisfy({ Self.isAlphanumeric($0) || [64, 43, 46, 95, 45].contains($0) })
        else { return nil }
        rawValue = raw
    }

    private static func isAlphanumeric(_ byte: UInt8) -> Bool {
        (97...122).contains(byte) || (48...57).contains(byte)
    }

    public var description: String { rawValue }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.singleValueContainer()
        let raw = try container.decode(String.self)
        guard let name = Self(raw) else {
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
