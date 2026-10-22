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

/// A port power switch the charger reports, and the target of a switch command.
/// Targets and wire indexes follow anker-solix-api `mqttcmdmap.py` `CHARGER_PORT_IDS`
/// (usbc_1...usbc_4 = 0...3, usba = 4), commit 9e72894. The two USB-A ports have
/// the one `usba` target, so A1 and A2 both map to `usbA`.
public enum PortSwitch: CaseIterable, Hashable, Sendable {
    case c1, c2, c3, c4, usbA

    public init(_ port: PortID) {
        switch port {
        case .c1: self = .c1
        case .c2: self = .c2
        case .c3: self = .c3
        case .c4: self = .c4
        case .a1, .a2: self = .usbA
        }
    }

    /// The index upstream `CHARGER_PORT_IDS` assigns the target.
    public var wireIndex: UInt8 {
        switch self {
        case .c1: 0
        case .c2: 1
        case .c3: 2
        case .c4: 3
        case .usbA: 4
        }
    }

    /// The `0a00` detail field reporting this switch: `_A2345_0a00` keys `aa`...`ae`.
    public var fieldID: UInt8 { 0xaa + wireIndex }
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
    /// Decoded `_A2345_0a00` switch states (`aa`...`ae` byte 00: 0 off, 1 on). A
    /// switch that was missing, mistyped or reported another value is absent, which
    /// means unknown, never off.
    public let switches: [PortSwitch: Bool]

    /// `_A2345_0a00` detail fields: `a3` fault bits, `b7` identity support,
    /// `bd` USB-PD vendor/product IDs, `be` class/model code and the `aa`...`ae`
    /// port switches.
    public static let fieldIDs: [UInt8] = [0xa3, 0xb7, 0xbd, 0xbe] + PortSwitch.allCases.map(\.fieldID)

    public init(faultBits: UInt8?, identitySupport: UInt8?,
                identities: [PortID: PortIdentity], rawFields: [UInt8: [UInt8]],
                switches: [PortSwitch: Bool] = [:]) {
        self.faultBits = faultBits
        self.identitySupport = identitySupport
        self.identities = identities
        self.rawFields = rawFields
        self.switches = switches
    }

    /// `a3` byte 0 mask `0x01`: either NTC above 125 °C, held until below 95 °C.
    public var overTemperature: Bool? { faultBits.map { $0 & 0x01 != 0 } }

    /// `a3` byte 0 masks `0x02...0x10` for C1–C4; `0x20` is shared by both
    /// USB-A ports ("either USB-A port" upstream), so A1 and A2 report the same bit.
    public func fault(_ port: PortID) -> Bool? {
        faultBits.map { $0 & Self.faultMask(port) != 0 }
    }

    /// The reported switch for the port. A1 and A2 read the one shared USB-A switch;
    /// nil means the charger did not report it.
    public func switchedOn(_ port: PortID) -> Bool? { switches[PortSwitch(port)] }

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
