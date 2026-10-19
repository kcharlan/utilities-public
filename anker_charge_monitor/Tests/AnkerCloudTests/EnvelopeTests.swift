import Foundation
import Testing
import PrimeMonitorCore
@testable import AnkerCloud

private let envelopeInfo = MQTTInfo(userID: "<USER_ID>", appName: "anker_power", thingName: "synthetic",
    certificateID: "<CERT_ID>", certificatePEM: "", privateKeyPEM: "", rootCAPEM: "", endpoint: "example.invalid")
private let envelopeCharger = ChargerInfo(serial: "<SN>", model: "A2345", alias: "Synthetic", name: "Synthetic")

@Test func statusRequestEnvelopeMatchesSyntheticExample() {
    let expected = #"{"head":{"version":"1.0.0.1","client_id":"android-anker_power-<USER_ID>-<CERT_ID>","sess_id":"1234-5678","msg_seq":1,"seed":1,"timestamp":305419896,"cmd_status":2,"cmd":17,"sign_code":1,"device_pn":"A2345","device_sn":"<SN>"},"payload":"{\"device_sn\":\"<SN>\",\"account_id\":\"<USER_ID>\",\"data\":\"/wkUAAMADwIAoQEi/gUDeFY0Ep4=\"}"}"#
    #expect(MQTTEnvelope.statusRequest(info: envelopeInfo, charger: envelopeCharger, timestamp: 0x12345678) == Data(expected.utf8))
}

@Test func topicsMatchMonitorMembership() {
    #expect(AnkerTopics.subscriptions(info: envelopeInfo, charger: envelopeCharger) ==
        ["cmd/anker_power/A2345/<SN>/#", "dt/anker_power/A2345/<SN>/#"])
    #expect(AnkerTopics.publish(info: envelopeInfo, charger: envelopeCharger) == "cmd/anker_power/A2345/<SN>/req")
}

@Test func ignoresNonPortMessages() throws {
    for message in [#"{"payload":"{\"version\":1,\"rssi\":-50}"}"#, #"{"payload":{}}"#, #"{"payload":"[]"}"#,
                    #"{"payload":"{\"data\":\"bad base64!\"}"}"#, "not json"] {
        #expect(MQTTEnvelope.frame(fromMessage: Data(message.utf8)) == nil)
    }
    let echo = MQTTEnvelope.statusRequest(info: envelopeInfo, charger: envelopeCharger, timestamp: 0x12345678)
    let frame = try HexFrame.parse(#require(MQTTEnvelope.frame(fromMessage: echo)))
    #expect(PortDecoder.snapshot(from: frame, receivedAt: Date()) == nil)
}

@Test func envelopeExtractsReplyAndEscapesUserStrings() throws {
    let message = #"{"payload":"{\"data\":\"/wkUAAMADwIAoQEi/gUDeFY0Ep4=\",\"pn\":\"A2345\"}"}"#
    #expect(MQTTEnvelope.frame(fromMessage: Data(message.utf8)) == [0xff,9,20,0,3,0,15,2,0,0xa1,1,0x22,0xfe,5,3,0x78,0x56,0x34,0x12,0x9e])
    let charger = ChargerInfo(serial: "synthetic\"/\\\n", model: "A2345", alias: "", name: "")
    let data = MQTTEnvelope.statusRequest(info: envelopeInfo, charger: charger, timestamp: 0)
    let outer = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
    let payload = try #require(outer["payload"] as? String)
    let inner = try #require(JSONSerialization.jsonObject(with: Data(payload.utf8)) as? [String: Any])
    #expect(inner["device_sn"] as? String == charger.serial)
}
