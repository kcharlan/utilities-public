import Foundation
import Testing
import PrimeMonitorCore
@testable import AnkerCloud

/// The realtime-trigger example in anker-solix-api `mqtt.py`
/// `generate_mqtt_command`'s docstring (commit 9e72894). The docstring omits the
/// checksum; this test computes it from the listed bytes.
@Test func builderReproducesGenerateMQTTCommandDocstringFrame() throws {
    let listed: [UInt8] = [0xff, 0x09, 0x1f, 0x00, 0x03, 0x00, 0x0f, 0x00, 0x57,
                           0xa1, 0x01, 0x22,
                           0xa2, 0x02, 0x01, 0x01,
                           0xa3, 0x05, 0x03, 0x2c, 0x01, 0x00, 0x00,
                           0xfe, 0x05, 0x03, 0xc8, 0xd7, 0xb6, 0x68]
    let checksum = listed.reduce(0, ^)
    let frame = CommandFrame.build(messageType: 0x0057, fields: [
        .pattern22(), .ui(0xa2, 1), .var(0xa3, 300), .timestamp(1_756_813_256)
    ])
    #expect(frame == listed + [checksum])
    #expect(checksum == 0x21)
    #expect(try HexFrame.parse(frame).messageType == 0x0057)
}

@Test func builderSortsFieldsAndKeepsTheLastValueForARepeatedField() {
    let ordered = CommandFrame.build(messageType: 0x0200, fields: [.pattern22(), .timestamp(0x12345678)])
    let shuffled = CommandFrame.build(messageType: 0x0200, fields: [.timestamp(1), .pattern22(), .timestamp(0x12345678)])
    #expect(shuffled == ordered)
    #expect(ordered == StatusRequest.frame(timestamp: 0x12345678))
}

/// Synthetic `0207` vectors for every target and value at the invented timestamp
/// `0x12345678` (Fixtures/README.md). The checksums were computed separately
/// from the listed bytes, not by the builder.
@Test(arguments: [
    (PortSwitch.c1, false, [UInt8](arrayLiteral: 0x00, 0x00, 0x90)), (.c1, true, [0x00, 0x01, 0x91]),
    (.c2, false, [0x01, 0x00, 0x91]), (.c2, true, [0x01, 0x01, 0x90]),
    (.c3, false, [0x02, 0x00, 0x92]), (.c3, true, [0x02, 0x01, 0x93]),
    (.c4, false, [0x03, 0x00, 0x93]), (.c4, true, [0x03, 0x01, 0x92]),
    (.usbA, false, [0x04, 0x00, 0x94]), (.usbA, true, [0x04, 0x01, 0x95])
])
func portSwitchFrameMatchesSyntheticVector(target: PortSwitch, on: Bool, varying: [UInt8]) throws {
    let expected: [UInt8] = [0xff, 0x09, 0x1c, 0x00, 0x03, 0x00, 0x0f, 0x02, 0x07,
                             0xa1, 0x01, 0x22,
                             0xa2, 0x02, 0x01, varying[0],
                             0xa3, 0x02, 0x01, varying[1],
                             0xfe, 0x05, 0x03, 0x78, 0x56, 0x34, 0x12,
                             varying[2]]
    let frame = PortSwitchCommand.frame(target: target, on: on, timestamp: 0x12345678)
    #expect(frame == expected)
    let parsed = try HexFrame.parse(frame)
    #expect(parsed.messageType == 0x0207)
    #expect(parsed.fields[0xa2] == [0x01, target.wireIndex])
    #expect(parsed.fields[0xa3] == [0x01, on ? 1 : 0])
    // A command frame never decodes as a status reply.
    #expect(PortDecoder.snapshot(from: parsed, receivedAt: Date(timeIntervalSince1970: 0)) == nil)
}

@Test func portSwitchTimestampUsesAllFourLittleEndianBytes() throws {
    for timestamp: UInt32 in [0, 0x12345678, .max] {
        let frame = PortSwitchCommand.frame(target: .c3, on: true, timestamp: timestamp)
        #expect(frame.count == 28)
        #expect(Array(frame[23...26]) == (0..<4).map { UInt8(truncatingIfNeeded: timestamp >> ($0 * 8)) })
        #expect(try HexFrame.parse(frame).messageType == 0x0207)
    }
}
