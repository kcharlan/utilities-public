/// Mapping ported from anker-solix-api mqttmap.py, `_A2345_0a00`, commit 8a5222b.
/// Labels and front-panel order follow the approved Prime Monitor specification.
public enum PortID: String, CaseIterable, Sendable {
    case c1, c2, c3, c4, a1, a2

    public var label: String { rawValue.uppercased() }

    /// The USB-C ports, in front-panel order. Only these report connected-device
    /// identity (`bd`/`be`); C1–C4 also have their own fault bits.
    public static let usbC: [PortID] = [.c1, .c2, .c3, .c4]
    public var isUSBC: Bool { Self.usbC.contains(self) }

    public var fieldID: UInt8 {
        switch self {
        case .c1: 0xa4
        case .c2: 0xa5
        case .c3: 0xa6
        case .c4: 0xa7
        case .a1: 0xa8
        case .a2: 0xa9
        }
    }

    public init?(fieldID: UInt8) {
        guard let port = Self.allCases.first(where: { $0.fieldID == fieldID }) else { return nil }
        self = port
    }
}
