import Foundation

/// MQTT 3.1.1 subset matching anker-solix-api `mqtt.py` create_client,
/// publish and subscribe defaults at 8a5222b (PR §3.2): clean session, no
/// credentials/will, and QoS 0. Wire layout follows MQTT 3.1.1 §§2–3.
enum MQTTPacket: Equatable, Sendable {
    case connect(clientID: String, keepAlive: UInt16)
    case connack(returnCode: UInt8)
    case subscribe(id: UInt16, topic: String)
    case suback(id: UInt16, code: UInt8)
    case publish(topic: String, payload: Data)
    case pingreq, pingresp, disconnect

    func encoded() -> [UInt8] {
        let header: UInt8
        let body: [UInt8]
        switch self {
        case let .connect(clientID, keepAlive):
            header = 0x10
            body = Self.string("MQTT") + [4, 2] + Self.word(keepAlive) + Self.string(clientID)
        case let .connack(code): header = 0x20; body = [0, code]
        case let .subscribe(id, topic):
            precondition(id != 0)
            header = 0x82; body = Self.word(id) + Self.string(topic) + [0]
        case let .suback(id, code): header = 0x90; body = Self.word(id) + [code]
        case let .publish(topic, payload): header = 0x30; body = Self.string(topic) + payload
        case .pingreq: header = 0xc0; body = []
        case .pingresp: header = 0xd0; body = []
        case .disconnect: header = 0xe0; body = []
        }
        precondition(body.count <= 268_435_455)
        var length = body.count, bytes: [UInt8] = []
        repeat {
            var byte = UInt8(length % 128)
            length /= 128
            if length > 0 { byte |= 0x80 }
            bytes.append(byte)
        } while length > 0
        return [header] + bytes + body
    }

    private static func word(_ value: UInt16) -> [UInt8] {
        [UInt8(value >> 8), UInt8(truncatingIfNeeded: value)]
    }

    private static func string(_ value: String) -> [UInt8] {
        let bytes = Array(value.utf8)
        precondition(bytes.count <= 65535)
        return word(UInt16(bytes.count)) + bytes
    }
}

enum MQTTDecodeError: Error { case malformedPacket, unsupportedPacket }

/// Buffers fragmented packets and emits coalesced packets in stream order.
struct MQTTDecoder {
    private var buffer: [UInt8] = []

    mutating func feed(_ bytes: [UInt8]) throws -> [MQTTPacket] {
        buffer += bytes
        var packets: [MQTTPacket] = []
        var offset = 0
        while buffer.count - offset >= 2 {
            var length = 0, multiplier = 1, index = offset + 1
            var complete = false
            for count in 0..<4 {
                guard index < buffer.count else { break }
                let byte = buffer[index]; index += 1
                length += Int(byte & 0x7f) * multiplier
                if byte & 0x80 == 0 {
                    guard count == 0 || byte != 0 else { throw MQTTDecodeError.malformedPacket }
                    complete = true; break
                }
                guard count < 3 else { throw MQTTDecodeError.malformedPacket }
                multiplier *= 128
            }
            guard complete, buffer.count - index >= length else { break }
            packets.append(try decode(header: buffer[offset], body: Array(buffer[index..<index + length])))
            offset = index + length
        }
        buffer.removeFirst(offset)
        return packets
    }

    private func decode(header: UInt8, body: [UInt8]) throws -> MQTTPacket {
        func word(_ index: Int) -> UInt16 { UInt16(body[index]) << 8 | UInt16(body[index + 1]) }
        switch header {
        case 0x20:
            guard body.count == 2, body[0] == 0, body[1] <= 5 else { throw MQTTDecodeError.malformedPacket }
            return .connack(returnCode: body[1])
        case 0x90:
            guard body.count == 3, word(0) != 0, [0, 1, 2, 0x80].contains(body[2]) else {
                throw MQTTDecodeError.malformedPacket
            }
            return .suback(id: word(0), code: body[2])
        case 0x30, 0x31:
            guard body.count >= 2 else { throw MQTTDecodeError.malformedPacket }
            let count = Int(word(0))
            guard count > 0, count <= body.count - 2,
                  let topic = String(bytes: body[2..<2 + count], encoding: .utf8),
                  !topic.contains("\0"), !topic.contains("+"), !topic.contains("#") else {
                throw MQTTDecodeError.malformedPacket
            }
            return .publish(topic: topic, payload: Data(body[(2 + count)...]))
        case 0xc0, 0xd0, 0xe0:
            guard body.isEmpty else { throw MQTTDecodeError.malformedPacket }
            return header == 0xc0 ? .pingreq : (header == 0xd0 ? .pingresp : .disconnect)
        default: throw MQTTDecodeError.unsupportedPacket
        }
    }
}
