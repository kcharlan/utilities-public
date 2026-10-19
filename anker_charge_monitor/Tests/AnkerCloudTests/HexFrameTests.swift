import Foundation
import Testing
@testable import AnkerCloud

func syntheticCorpusFrames() throws -> [[UInt8]] {
    let url = try #require(Bundle.module.url(forResource: "synthetic_0a00_frames", withExtension: "txt", subdirectory: "Fixtures"))
    return try String(contentsOf: url, encoding: .utf8).split(whereSeparator: \.isNewline).map { line in
        #expect(line.count == 652)
        let chars = Array(line)
        return try stride(from: 0, to: chars.count, by: 2).map { index in
            try #require(UInt8(String(chars[index...index + 1]), radix: 16))
        }
    }
}

/// Builds a synthetic frame independently of the production encoder.
func syntheticFrame(type: UInt16 = 0x0a00, fields: [UInt8], increment: Bool = true) -> [UInt8] {
    var bytes: [UInt8] = [0xff, 0x09, 0, 0, 3, 1, 15, UInt8(type >> 8), UInt8(truncatingIfNeeded: type)]
    if increment { bytes.append(0) }
    bytes += fields
    let length = bytes.count + 1
    bytes[2] = UInt8(truncatingIfNeeded: length)
    bytes[3] = UInt8(length >> 8)
    bytes.append(bytes.reduce(0, ^))
    return bytes
}

@Test func everySyntheticCorpusFrameParses() throws {
    let frames = try syntheticCorpusFrames()
    #expect(frames.count == 115)
    #expect(Set(frames).count == 115)
    for bytes in frames {
        #expect(bytes.count == 326)
        #expect(bytes.prefix(10) == [0xff, 9, 0x46, 1, 3, 1, 15, 10, 0, 0])
        #expect(HexFrame.xorChecksum(bytes) == 0)
        #expect(try HexFrame.parse(bytes).messageType == 0x0a00)
    }
}

@Test func corruptFramesAreRejected() {
    let valid = syntheticFrame(fields: [0xa1, 1, 0x22])
    var badPrefix = valid
    badPrefix[0] = 0
    #expect(throws: HexFrameError.prefix) { try HexFrame.parse(badPrefix) }
    var badLength = valid
    badLength[2] += 1
    #expect(throws: HexFrameError.length) { try HexFrame.parse(badLength) }
    var badChecksum = valid
    badChecksum[badChecksum.count - 1] ^= 1
    #expect(throws: HexFrameError.checksum) { try HexFrame.parse(badChecksum) }
    for bytes in [[], [0xff], [0xff, 9], [0xff, 9, 0, 0]] as [[UInt8]] {
        #expect(throws: (any Error).self) { try HexFrame.parse(bytes) }
    }
    for fields: [UInt8] in [[0xa1], [0xa1, 3, 4], [0xa1, 0]] {
        #expect(throws: HexFrameError.truncatedField) { try HexFrame.parse(syntheticFrame(fields: fields)) }
    }
}

@Test func fieldsPreserveTypeByteAndHeaderIncrementIsOptional() throws {
    for increment in [true, false] {
        let frame = try HexFrame.parse(syntheticFrame(type: 0x0200, fields: [0xa1, 1, 0x22, 0xfe, 5, 3, 1, 2, 3, 4], increment: increment))
        #expect(frame.messageType == 0x0200)
        #expect(frame.fields == [0xa1: [0x22], 0xfe: [3, 1, 2, 3, 4]])
    }
}

@Test func twoByteStringAndBinaryLengthsMatchUpstreamHeuristic() throws {
    for type: UInt8 in [0, 4] {
        let frame = try HexFrame.parse(syntheticFrame(fields: [0xa1, 5, 0, type, 1, 2, 3, 4, 0xa2, 1, 0x22]))
        #expect(frame.fields[0xa1] == [type, 1, 2, 3, 4])
        #expect(frame.fields[0xa2] == [0x22])
        // A two-byte-length binary field can also end directly at the checksum.
        let last = try HexFrame.parse(syntheticFrame(fields: [0xa1, 5, 0, type, 1, 2, 3, 4]))
        #expect(last.fields[0xa1] == [type, 1, 2, 3, 4])
    }
    // In the 1-byte form, the third payload byte looks like a next field only
    // accidentally; upstream's binary heuristic rejects the long interpretation.
    let single = try HexFrame.parse(syntheticFrame(fields: [0xa1, 5, 0, 4, 1, 2, 3, 0xa2, 1, 0x22]))
    #expect(single.fields[0xa1] == [0, 4, 1, 2, 3])
    #expect(single.fields[0xa2] == [0x22])
    // Exercise a genuinely wide length, including its nonzero high byte.
    let longPayload = [UInt8(4)] + Array(repeating: UInt8(0xff), count: 299)
    let long = try HexFrame.parse(syntheticFrame(fields: [0xa1, 0x2c, 1] + longPayload))
    #expect(long.fields[0xa1] == longPayload)
}
