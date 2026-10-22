import Foundation
import PrimeMonitorCore

/// Per-port map ported from anker-solix-api `mqttmap.py`, `_A2345_0a00`,
/// and `mqtttypes.py`, `DeviceHexDataField` signed little-endian `sile`
/// decoding, commit 8a5222b. See PR §6.1. Detail fields follow commit
/// 9e72894181aef868e7b3ed0ba05bd322d54bb5d7; see protocol reference §6.2.
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
        return ChargerSnapshot(receivedAt: receivedAt, readings: readings, details: details(from: frame))
    }

    /// Wire types that `DeviceHexDataField.extract_value` (9e72894) carries into
    /// each map's `BYTES` extraction: `sile` and `var` reach it through the `bin`
    /// branch with the whole map; `ui` passes only the inner byte map, which the
    /// `bin` branch then cannot read; `strb` reads the dictionary byte maps of
    /// `b7`/`bd`/`be` but fails on `a3`'s bit-mask list. Every other type,
    /// including a typeless one-byte field, extracts nothing.
    static func acceptsType(_ type: UInt8, for fieldID: UInt8) -> Bool {
        switch type {
        case 0x02, 0x03, 0x04: true // sile, var, bin
        case 0x06: fieldID != 0xa3 // strb
        default: false
        }
    }

    /// Decodes each detail field independently. A missing, short or unsupported
    /// field leaves only its own values unknown; present payloads stay verbatim.
    static func details(from frame: HexFrame) -> ChargerDetails? {
        let raw = frame.fields.filter { ChargerDetails.fieldIDs.contains($0.key) }
        guard !raw.isEmpty else { return nil }
        // Upstream indexes BYTES positions into f_value, the payload after its type byte.
        func value(_ fieldID: UInt8) -> ArraySlice<UInt8>? {
            guard let payload = raw[fieldID], let type = payload.first,
                  acceptsType(type, for: fieldID) else { return nil }
            return payload.dropFirst()
        }
        func word(_ value: ArraySlice<UInt8>?, at offset: Int) -> UInt16? {
            guard let value, value.count >= offset + 2 else { return nil }
            return unsignedLittleEndian(value, at: value.startIndex + offset)
        }
        let faults = value(0xa3)
        let support = value(0xb7)
        let ids = value(0xbd)
        let metadata = value(0xbe)
        var identities: [PortID: PortIdentity] = [:]
        for (index, port) in PortID.usbC.enumerated() {
            guard let vendor = word(ids, at: 4 * index),
                  let product = word(ids, at: 4 * index + 2) else { continue }
            identities[port] = .reported(vendorID: vendor, productID: product,
                                         brandClass: word(metadata, at: 4 * index),
                                         modelCode: word(metadata, at: 4 * index + 2))
        }
        return ChargerDetails(
            faultBits: faults?.first,
            identitySupport: support.flatMap { $0.count >= 2 ? $0[$0.startIndex + 1] : nil },
            identities: identities,
            rawFields: raw
        )
    }

    private static func signedLittleEndian(_ bytes: [UInt8], at index: Int) -> Int {
        Int(Int16(bitPattern: UInt16(bytes[index]) | UInt16(bytes[index + 1]) << 8))
    }

    /// Identity words are unsigned (`SIGNED: False` upstream), unlike readings.
    private static func unsignedLittleEndian(_ bytes: ArraySlice<UInt8>, at index: Int) -> UInt16 {
        UInt16(bytes[index]) | UInt16(bytes[index + 1]) << 8
    }
}
