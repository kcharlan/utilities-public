/// A2345 `0200` status request ported from anker-solix-api commit 8a5222b:
/// `mqtt.py` `generate_mqtt_command` / `status_request`, `mqttcmdmap.py`
/// `CMD_STATUS_REQUEST`, `CMD_COMMON`, `TIMESTAMP_FE`, and `mqtttypes.py`
/// `DeviceHexData._update_hexbytes` / `add_timestamp_field`. See PR §5.3.
public enum StatusRequest {
    public static func frame(timestamp: UInt32) -> [UInt8] {
        var bytes: [UInt8] = [
            0xff, 0x09, 0x14, 0x00, 0x03, 0x00, 0x0f, 0x02, 0x00,
            0xa1, 0x01, 0x22,
            0xfe, 0x05, 0x03
        ]
        bytes += (0..<4).map { UInt8(truncatingIfNeeded: timestamp >> ($0 * 8)) }
        bytes.append(HexFrame.xorChecksum(bytes))
        return bytes
    }
}
