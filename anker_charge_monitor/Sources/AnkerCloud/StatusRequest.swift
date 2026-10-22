import PrimeMonitorCore

/// A2345 command frames built as anker-solix-api `mqtt.py` `generate_mqtt_command`
/// does (commit 9e72894), with `mqtttypes.py` `DeviceHexDataHeader` (publish form:
/// `03 00 0f` pattern, no increment), `DeviceHexData.update_field` (fields sorted by
/// ID, a repeated ID replaced), `_update_hexbytes` (length includes the checksum)
/// and `DeviceHexDataField.hex` (ID, length, type byte when present, value).
public enum CommandFrame {
    /// One command field: ID, optional type byte and value bytes.
    public struct Field: Equatable, Sendable {
        public let id: UInt8
        public let type: UInt8?
        public let value: [UInt8]

        public init(id: UInt8, type: UInt8?, value: [UInt8]) {
            self.id = id
            self.type = type
            self.value = value
        }

        /// `mqttcmdmap.py` `CMD_HEADER` `a1` (`pattern_22`): untyped `22`.
        public static func pattern22(_ id: UInt8 = 0xa1) -> Field {
            Field(id: id, type: nil, value: [0x22])
        }

        /// `DeviceHexDataTypes.ui` (`01`): one unsigned byte.
        public static func ui(_ id: UInt8, _ value: UInt8) -> Field {
            Field(id: id, type: 0x01, value: [value])
        }

        /// `DeviceHexDataTypes.var` (`03`): four little-endian bytes.
        public static func `var`(_ id: UInt8, _ value: UInt32) -> Field {
            Field(id: id, type: 0x03, value: (0..<4).map { UInt8(truncatingIfNeeded: value >> ($0 * 8)) })
        }

        /// `mqttcmdmap.py` `TIMESTAMP_FE` (`DeviceHexData.add_timestamp_field`):
        /// Unix seconds as a `var` field `fe`.
        public static func timestamp(_ seconds: UInt32) -> Field { .var(0xfe, seconds) }

        var bytes: [UInt8] {
            let length = (type == nil ? 0 : 1) + value.count
            // `DeviceHexDataField.hex` writes the minimal little-endian length bytes.
            let lengthBytes: [UInt8] = length > 0xff
                ? [UInt8(truncatingIfNeeded: length), UInt8(truncatingIfNeeded: length >> 8)]
                : [UInt8(length)]
            return [id] + lengthBytes + (type.map { [$0] } ?? []) + value
        }
    }

    public static func build(messageType: UInt16, fields: [Field]) -> [UInt8] {
        var byID: [UInt8: Field] = [:]
        for field in fields { byID[field.id] = field }
        let body = byID.keys.sorted().flatMap { byID[$0]!.bytes }
        let length = 9 + body.count + 1
        var bytes: [UInt8] = [0xff, 0x09, UInt8(truncatingIfNeeded: length), UInt8(truncatingIfNeeded: length >> 8),
                              0x03, 0x00, 0x0f, UInt8(messageType >> 8), UInt8(truncatingIfNeeded: messageType)]
        bytes += body
        bytes.append(HexFrame.xorChecksum(bytes))
        return bytes
    }
}

/// A2345 `0200` status request: `mqttmap.py` A2345 `"0200"` (`CMD_STATUS_REQUEST`,
/// which is `CMD_COMMON`), originally ported from commit 8a5222b. See PR §5.3.
public enum StatusRequest {
    public static func frame(timestamp: UInt32) -> [UInt8] {
        CommandFrame.build(messageType: 0x0200, fields: [.pattern22(), .timestamp(timestamp)])
    }
}

/// A2345 `0207` USB port switch: `mqttmap.py` A2345 `"0207"` with
/// `mqttcmdmap.py` `CMD_USB_PORT_SWITCH` (`CMD_COMMON` plus `a2`
/// `set_port_switch_select`, a `ui` `CHARGER_PORT_IDS` index, and `a3`
/// `set_port_switch`, a `ui` 0 off / 1 on), commit 9e72894.
public enum PortSwitchCommand {
    public static func frame(target: PortSwitch, on: Bool, timestamp: UInt32) -> [UInt8] {
        CommandFrame.build(messageType: 0x0207, fields: [
            .pattern22(), .ui(0xa2, target.wireIndex), .ui(0xa3, on ? 1 : 0), .timestamp(timestamp)
        ])
    }
}
