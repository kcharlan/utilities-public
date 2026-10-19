import Foundation
import PrimeMonitorCore

/// Per-port map ported from anker-solix-api `mqttmap.py`, `_A2345_0a00`,
/// and `mqtttypes.py`, `DeviceHexDataField` signed little-endian `sile`
/// decoding, commit 8a5222b. See PR §6.1.
public enum PortDecoder {
    /// Rejects missing, mistyped or truncated port data so a partial reply cannot
    /// replace the last complete snapshot. Values stay in their signed wire units.
    public static func snapshot(from frame: HexFrame, receivedAt: Date) -> ChargerSnapshot? {
        guard frame.messageType == 0x0a00 else { return nil }
        var readings: [PortReading] = []
        for port in PortID.allCases {
            guard let field = frame.fields[port.fieldID], field.count >= 8, field[0] == 0x04 else {
                return nil
            }
            readings.append(PortReading(
                port: port,
                active: field[1] == 1,
                voltageMilli: signedLittleEndian(field, at: 2),
                currentMilli: signedLittleEndian(field, at: 4),
                powerCenti: signedLittleEndian(field, at: 6)
            ))
        }
        return ChargerSnapshot(receivedAt: receivedAt, readings: readings)
    }

    private static func signedLittleEndian(_ bytes: [UInt8], at index: Int) -> Int {
        Int(Int16(bitPattern: UInt16(bytes[index]) | UInt16(bytes[index + 1]) << 8))
    }
}
