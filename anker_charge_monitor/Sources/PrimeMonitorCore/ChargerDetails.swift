/// A USB-C port's connected-device identity, interpreted from anker-solix-api
/// `mqttmap.py`, `_A2345_0a00` keys `bd` and `be`, commit 9e72894.
public enum PortIdentity: Equatable, Sendable {
    case nothingAttached
    case identifying
    case identified(vendorID: UInt16, productID: UInt16,
                    brandClass: UInt16?, modelCode: UInt16?)

    /// Applies the upstream sentinels: `bd` reports `{fffa, fffb}` with no
    /// device and `{0, 0}` while unresolved; `be` reports `ffff` for an absent
    /// class or model code. Metadata is independent and only kept when identified.
    public static func reported(vendorID: UInt16, productID: UInt16,
                                brandClass: UInt16?, modelCode: UInt16?) -> PortIdentity {
        switch (vendorID, productID) {
        case (0xfffa, 0xfffb): .nothingAttached
        case (0, 0): .identifying
        default: .identified(vendorID: vendorID, productID: productID,
                             brandClass: brandClass == absent ? nil : brandClass,
                             modelCode: modelCode == absent ? nil : modelCode)
        }
    }

    /// The upstream `be` absence sentinel for class and model code.
    public static let absent: UInt16 = 0xffff
}

/// Status detail decoded from the A2345 `0a00` reply. `nil` members were not
/// decoded; `rawFields` keeps every present detail payload, type byte included.
public struct ChargerDetails: Equatable, Sendable {
    public let faultBits: UInt8?
    /// `b7` byte 01. Upstream says 6 when every port's PD controller reports
    /// protocol revision 4 or later, else 2, and that it gates the `bd` read.
    /// The owner's charger reported a resolved `bd`/`be` identity on one port
    /// while this value was 2, so it is informational only: presentation never
    /// treats any value as "cannot identify"; decoded `identities` always win.
    public let identitySupport: UInt8?
    public let identities: [PortID: PortIdentity]
    public let rawFields: [UInt8: [UInt8]]

    /// `_A2345_0a00` detail fields: `a3` fault bits, `b7` identity support,
    /// `bd` USB-PD vendor/product IDs and `be` class/model code.
    public static let fieldIDs: [UInt8] = [0xa3, 0xb7, 0xbd, 0xbe]

    public init(faultBits: UInt8?, identitySupport: UInt8?,
                identities: [PortID: PortIdentity], rawFields: [UInt8: [UInt8]]) {
        self.faultBits = faultBits
        self.identitySupport = identitySupport
        self.identities = identities
        self.rawFields = rawFields
    }

    /// `a3` byte 0 mask `0x01`: either NTC above 125 °C, held until below 95 °C.
    public var overTemperature: Bool? { faultBits.map { $0 & 0x01 != 0 } }

    /// `a3` byte 0 masks `0x02...0x10` for C1–C4; `0x20` is shared by both
    /// USB-A ports ("either USB-A port" upstream), so A1 and A2 report the same bit.
    public func fault(_ port: PortID) -> Bool? {
        faultBits.map { $0 & Self.faultMask(port) != 0 }
    }

    private static func faultMask(_ port: PortID) -> UInt8 {
        switch port {
        case .c1: 0x02
        case .c2: 0x04
        case .c3: 0x08
        case .c4: 0x10
        case .a1, .a2: 0x20
        }
    }
}
