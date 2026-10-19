import Foundation
import Testing
@testable import AnkerCloud

@Test func connectPacketBytes() {
    #expect(MQTTPacket.connect(clientID: "synthetic_00001", keepAlive: 60).encoded() ==
        [0x10,27,0,4,77,81,84,84,4,2,0,60,0,15] + Array("synthetic_00001".utf8))
}

@Test func subscribeAndPublishBytes() {
    #expect(MQTTPacket.subscribe(id: 0x1234, topic: "dt/x/#").encoded() ==
        [0x82,11,0x12,0x34,0,6,100,116,47,120,47,35,0])
    #expect(MQTTPacket.publish(topic: "cmd/x", payload: Data([0xff,0])).encoded() ==
        [0x30,9,0,5,99,109,100,47,120,0xff,0])
    #expect(MQTTPacket.pingreq.encoded() == [0xc0,0])
    #expect(MQTTPacket.pingresp.encoded() == [0xd0,0])
    #expect(MQTTPacket.disconnect.encoded() == [0xe0,0])
    #expect(MQTTPacket.connack(returnCode: 5).encoded() == [0x20,2,0,5])
    #expect(MQTTPacket.suback(id: 0x1234, code: 0x80).encoded() == [0x90,3,0x12,0x34,0x80])
}

@Test func decoderHandlesSplitAndCoalescedPackets() throws {
    var decoder = MQTTDecoder()
    #expect(try decoder.feed([0x30,9,0,5,99]) == [])
    #expect(try decoder.feed([109,100,47,120,0xff,0,0x20,2,0,0,0x90,3,0x12,0x34,0,0xd0,0]) == [
        .publish(topic: "cmd/x", payload: Data([0xff,0])), .connack(returnCode: 0),
        .suback(id: 0x1234, code: 0), .pingresp
    ])
}

@Test func decoderHandlesMultibyteRemainingLength() throws {
    var decoder = MQTTDecoder()
    #expect(try decoder.feed([0x30,0x83]) == [])
    #expect(try decoder.feed([0x01,0,1,120] + [UInt8](repeating: 42, count: 128)) ==
        [.publish(topic: "x", payload: Data(repeating: 42, count: 128))])
    #expect(MQTTPacket.publish(topic: "x", payload: Data(repeating: 42, count: 128)).encoded() ==
        [0x30,0x83,1,0,1,120] + [UInt8](repeating: 42, count: 128))
}

@Test func decoderRejectsMalformedPackets() {
    // Invalid variable lengths, fixed flags, truncated strings, QoS>0 and invalid acknowledgments.
    for bytes: [UInt8] in [[0x30,0x80,0x80,0x80,0x80], [0xd1,0], [0x30,2,0,4],
                          [0x32,3,0,1,120], [0x20,2,2,0], [0x90,3,0,0,0], [0xd0,1,0]] {
        #expect(throws: (any Error).self) { var decoder = MQTTDecoder(); _ = try decoder.feed(bytes) }
    }
}
