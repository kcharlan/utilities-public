import Foundation
import PrimeMonitorCore

/// Ported from anker-solix-api `mqtt.py` get_topic_prefix and
/// `mqtt_monitor.py` main subscription loop, commit 8a5222b; PR §4.1.
enum AnkerTopics {
    static func subscriptions(info: MQTTInfo, charger: ChargerInfo) -> [String] {
        ["cmd", "dt"].map { "\($0)/\(info.appName)/\(charger.model)/\(charger.serial)/#" }.sorted()
    }

    static func publish(info: MQTTInfo, charger: ChargerInfo) -> String {
        "cmd/\(info.appName)/\(charger.model)/\(charger.serial)/req"
    }
}

/// Ported from anker-solix-api `mqtt.py` publish / on_message, commit
/// 8a5222b; `publish` is unchanged at 9e72894. Every command uses the same
/// envelope around its frame. Fixed sequence, session and seed follow PR §§4.2, 4.3, 8.6.
enum MQTTEnvelope {
    static func statusRequest(info: MQTTInfo, charger: ChargerInfo, timestamp: UInt32) -> Data {
        command(info: info, charger: charger, frame: StatusRequest.frame(timestamp: timestamp), timestamp: timestamp)
    }

    static func command(info: MQTTInfo, charger: ChargerInfo, frame: [UInt8], timestamp: UInt32) -> Data {
        let payload = "{\"device_sn\":\(quoted(charger.serial)),\"account_id\":\(quoted(info.userID)),\"data\":\(quoted(Data(frame).base64EncodedString()))}"
        let clientID = "android-\(info.appName)-\(info.userID)-\(info.certificateID)"
        // Preserve upstream insertion order, including the nested JSON string.
        let message = "{\"head\":{\"version\":\"1.0.0.1\",\"client_id\":\(quoted(clientID)),\"sess_id\":\"1234-5678\",\"msg_seq\":1,\"seed\":1,\"timestamp\":\(timestamp),\"cmd_status\":2,\"cmd\":17,\"sign_code\":1,\"device_pn\":\(quoted(charger.model)),\"device_sn\":\(quoted(charger.serial))},\"payload\":\(quoted(payload))}"
        return Data(message.utf8)
    }

    static func frame(fromMessage message: Data) -> [UInt8]? {
        guard let outer = try? JSONSerialization.jsonObject(with: message) as? [String: Any],
              let encodedPayload = outer["payload"] as? String,
              let payload = try? JSONSerialization.jsonObject(with: Data(encodedPayload.utf8)) as? [String: Any],
              let encodedFrame = payload["data"] as? String,
              let frame = Data(base64Encoded: encodedFrame), !frame.isEmpty else { return nil }
        return Array(frame)
    }

    private static func quoted(_ value: String) -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.withoutEscapingSlashes]
        // A String always has a valid JSON encoding.
        return String(decoding: try! encoder.encode(value), as: UTF8.self)
    }
}
