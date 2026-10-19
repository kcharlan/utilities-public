/// The A2345 frame subset ported from anker-solix-api `mqtttypes.py`,
/// `DeviceHexDataHeader`, `DeviceHexDataField` and `DeviceHexData`, commit 8a5222b.
/// Fields retain their complete wire payload (type byte, when present, plus value).
public struct HexFrame: Equatable, Sendable {
    public let messageType: UInt16
    public let fields: [UInt8: [UInt8]]

    public init(messageType: UInt16, fields: [UInt8: [UInt8]]) {
        self.messageType = messageType
        self.fields = fields
    }

    public static func parse(_ bytes: [UInt8]) throws -> HexFrame {
        guard bytes.starts(with: [0xff, 0x09]) else { throw HexFrameError.prefix }
        guard bytes.count >= 10,
              Int(bytes[2]) | (Int(bytes[3]) << 8) == bytes.count else {
            throw HexFrameError.length
        }
        guard xorChecksum(bytes) == 0 else { throw HexFrameError.checksum }

        let end = bytes.count - 1
        // Upstream treats byte 9 as an increment unless it is a0...a9.
        var index = end > 9 && !(0xa0...0xa9).contains(bytes[9]) ? 10 : 9
        var fields: [UInt8: [UInt8]] = [:]
        while index < end {
            guard end - index >= 2 else { throw HexFrameError.truncatedField }
            let fieldID = bytes[index]
            var length = Int(bytes[index + 1])
            var start = index + 2
            // DeviceHexDataField distinguishes 2-byte LE string/bin lengths
            // using the remaining bytes, UTF-8 validity and the next field ID.
            // The remaining byte count includes the checksum, as upstream does.
            if end - index >= 3 {
                let extendedLength = length | (Int(bytes[index + 2]) << 8)
                let type = bytes[index + 3]
                let remaining = bytes.count - index
                if extendedLength > 3, extendedLength <= remaining - 4 {
                    let next = index + 3 + extendedLength
                    let isString = type == 0 && String(validating: bytes[(index + 4)..<next], as: UTF8.self) != nil
                    let isBinary = type == 4 && (
                        remaining - extendedLength == 4 ||
                        (bytes[next] > fieldID && remaining - extendedLength >= 3)
                    )
                    if isString || isBinary {
                        length = extendedLength
                        start += 1
                    }
                }
            }
            guard length > 0, length <= end - start else { throw HexFrameError.truncatedField }
            fields[fieldID] = Array(bytes[start..<start + length])
            index = start + length
        }
        return HexFrame(messageType: UInt16(bytes[7]) << 8 | UInt16(bytes[8]), fields: fields)
    }

    public static func xorChecksum(_ bytes: some Sequence<UInt8>) -> UInt8 {
        bytes.reduce(0, ^)
    }
}

public enum HexFrameError: Error, Equatable {
    case prefix, length, checksum, truncatedField
}
