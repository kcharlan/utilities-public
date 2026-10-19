import Foundation
import Testing
@testable import AnkerCloud

@Test func statusRequestMatchesSyntheticWorkedExample() {
    let frame = StatusRequest.frame(timestamp: 0x12345678)
    #expect(frame == [0xff,0x09,0x14,0x00,0x03,0x00,0x0f,0x02,0x00,0xa1,0x01,0x22,0xfe,0x05,0x03,0x78,0x56,0x34,0x12,0x9e])
    #expect(Data(frame).base64EncodedString() == "/wkUAAMADwIAoQEi/gUDeFY0Ep4=")
}

@Test func timestampUsesAllFourLittleEndianBytes() throws {
    for timestamp: UInt32 in [0, 0x12345678, .max] {
        let bytes = StatusRequest.frame(timestamp: timestamp)
        #expect(bytes.count == 20)
        #expect(Array(bytes[15...18]) == (0..<4).map { UInt8(truncatingIfNeeded: timestamp >> ($0 * 8)) })
        #expect(try HexFrame.parse(bytes).messageType == 0x0200)
    }
}
