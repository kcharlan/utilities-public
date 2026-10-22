import Foundation

/// A connected device's USB-PD vendor and product IDs, as reported by `bd`.
public struct DeviceKey: Hashable, Sendable {
    public let vendorID: UInt16
    public let productID: UInt16
    public init(vendorID: UInt16, productID: UInt16) {
        self.vendorID = vendorID
        self.productID = productID
    }

    /// Parses a catalog `devices` key: four hexadecimal vendor digits, a colon
    /// and four hexadecimal product digits, in either letter case.
    public init?(catalogKey: String) {
        let parts = catalogKey.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 2, let vendor = DeviceCatalog.hexKey(parts[0]), let product = DeviceCatalog.hexKey(parts[1]) else { return nil }
        self.init(vendorID: vendor, productID: product)
    }

    /// The normalized uppercase `VID:PID` spelling written by the app.
    public var catalogKey: String { DeviceCatalog.hex(vendorID) + ":" + DeviceCatalog.hex(productID) }
}

public enum DeviceNameProblem: Equatable, Sendable { case notText, empty, tooLong }

/// A rejected catalog document. Each entry failure names its section and key.
public enum DeviceCatalogError: Error, Equatable, Sendable, CustomStringConvertible, LocalizedError {
    case notJSON
    case notObject
    case schema
    case missingSection(String)
    case invalidKey(section: String, key: String)
    case aliasKey(section: String, key: String, alias: String)
    case invalidName(section: String, key: String, DeviceNameProblem)

    public var description: String {
        switch self {
        case .notJSON: "The device catalog is not valid JSON."
        case .notObject: "The device catalog must be a JSON object."
        case .schema: "The device catalog \"schema\" must be the integer \(DeviceCatalog.schema)."
        case .missingSection(let section): "The device catalog needs a \"\(section)\" object."
        case .invalidKey(let section, let key):
            switch section {
            case "brands": "brands entry \"\(key)\": the key must be a decimal brand class from 0 to \(PortIdentity.absent - 1) without leading zeros."
            case "vendors": "vendors entry \"\(key)\": the key must be four hexadecimal digits."
            default: "\(section) entry \"\(key)\": the key must be four hexadecimal vendor digits, a colon and four hexadecimal product digits."
            }
        case .aliasKey(let section, let key, let alias): "\(section) entry \"\(key)\" repeats entry \"\(alias)\"."
        case .invalidName(let section, let key, let problem):
            switch problem {
            case .notText: "\(section) entry \"\(key)\": the name must be a string."
            case .empty: "\(section) entry \"\(key)\": the name is empty."
            case .tooLong: "\(section) entry \"\(key)\": the name is longer than \(DeviceCatalog.maximumNameLength) characters."
            }
        }
    }
    public var errorDescription: String? { description }
}

/// Brand-class, vendor and user device names for connected-port labels.
/// The JSON document is validated by hand: its keys are numeric spellings,
/// so synthesized dictionary decoding would neither validate nor normalize them.
public struct DeviceCatalog: Equatable, Sendable {
    public var brands: [UInt16: String]
    public var vendors: [UInt16: String]
    public var devices: [DeviceKey: String]
    public init() { brands = [:]; vendors = [:]; devices = [:] }

    public static let schema = 1
    public static let maximumNameLength = 64

    public static func decode(_ data: Data) throws(DeviceCatalogError) -> Self {
        try decodeDocument(data).catalog
    }

    /// Validates `data` and also returns its parsed top-level object, so a
    /// writer can preserve `source` and unknown keys.
    public static func decodeDocument(_ data: Data) throws(DeviceCatalogError) -> (catalog: Self, object: [String: Any]) {
        let parsed: Any
        do { parsed = try JSONSerialization.jsonObject(with: data, options: [.fragmentsAllowed]) }
        catch { throw .notJSON }
        guard let object = parsed as? [String: Any] else { throw .notObject }
        guard let schema = object["schema"] as? NSNumber, isInteger(schema), schema.intValue == Self.schema else { throw .schema }
        var catalog = DeviceCatalog()
        catalog.brands = try section("brands", in: object) { key in
            guard key.utf8.allSatisfy({ (0x30...0x39).contains($0) }), key == "0" || !key.hasPrefix("0"),
                  let value = UInt16(key), value != PortIdentity.absent else { return nil }
            return value
        }
        catalog.vendors = try section("vendors", in: object) { hexKey(Substring($0)) }
        catalog.devices = try section("devices", in: object) { DeviceKey(catalogKey: $0) }
        return (catalog, object)
    }

    /// A trimmed name, or nil when blank. Callers check `maximumNameLength`.
    public static func normalizedName(_ name: String?) -> String? {
        guard let trimmed = name?.trimmingCharacters(in: .whitespacesAndNewlines), !trimmed.isEmpty else { return nil }
        return trimmed
    }

    /// Resolves the user's device name, then brand-class, then vendor names,
    /// and otherwise the uppercase hexadecimal `VID:PID`.
    public func label(for identity: PortIdentity) -> String? {
        switch identity {
        case .nothingAttached: nil
        case .identifying: "Identifying…"
        case let .identified(vendorID, productID, brandClass, _):
            devices[DeviceKey(vendorID: vendorID, productID: productID)]
                ?? brandClass.flatMap { brands[$0] }
                ?? vendors[vendorID]
                ?? DeviceKey(vendorID: vendorID, productID: productID).catalogKey
        }
    }

    private static func section<Key: Hashable>(_ name: String, in object: [String: Any],
                                                key parse: (String) -> Key?) throws(DeviceCatalogError) -> [Key: String] {
        guard let entries = object[name] as? [String: Any] else { throw .missingSection(name) }
        var result: [Key: String] = [:], spellings: [Key: String] = [:]
        // Sorted iteration makes the reported entry deterministic.
        for raw in entries.keys.sorted() {
            guard let key = parse(raw) else { throw .invalidKey(section: name, key: raw) }
            if let alias = spellings[key] { throw .aliasKey(section: name, key: raw, alias: alias) }
            spellings[key] = raw
            guard let text = entries[raw] as? String else { throw .invalidName(section: name, key: raw, .notText) }
            guard let trimmed = normalizedName(text) else { throw .invalidName(section: name, key: raw, .empty) }
            guard trimmed.count <= maximumNameLength else { throw .invalidName(section: name, key: raw, .tooLong) }
            result[key] = trimmed
        }
        return result
    }

    /// JSON booleans and fractional or exponent literals are not integers here.
    private static func isInteger(_ number: NSNumber) -> Bool {
        CFGetTypeID(number) != CFBooleanGetTypeID() && !CFNumberIsFloatType(number)
    }

    static func hexKey(_ text: Substring) -> UInt16? {
        guard text.utf8.count == 4, text.utf8.allSatisfy({ (0x30...0x39).contains($0) || (0x41...0x46).contains($0) || (0x61...0x66).contains($0) }) else { return nil }
        return UInt16(text, radix: 16)
    }

    static func hex(_ value: UInt16) -> String {
        let digits = String(value, radix: 16, uppercase: true)
        return String(repeating: "0", count: 4 - digits.count) + digits
    }
}
