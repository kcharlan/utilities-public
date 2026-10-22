import Foundation
import Testing
import PrimeMonitorCore
@testable import AnkerCloud

private let receivedAt = Date(timeIntervalSince1970: 123)
private func snapshot(row: Int, frames: [[UInt8]]) throws -> ChargerSnapshot {
    try #require(PortDecoder.snapshot(from: HexFrame.parse(frames[row]), receivedAt: receivedAt))
}

@Test func syntheticRowsDecodeToKnownValues() throws {
    let frames = try syntheticCorpusFrames()
    let r0 = try snapshot(row: 0, frames: frames)
    #expect(r0.receivedAt == receivedAt)
    #expect(r0.readings.map(\.port) == PortID.allCases)
    #expect(r0.readings.map(\.active) == [false, false, true, true, false, false])
    #expect(r0.readings[0] == PortReading(port: .c1, active: false, voltageMilli: 0, currentMilli: 7, powerCenti: 0))
    #expect(r0.readings[2] == PortReading(port: .c3, active: true, voltageMilli: 12345, currentMilli: 321, powerCenti: 123))
    #expect(r0.readings[3] == PortReading(port: .c4, active: true, voltageMilli: 23456, currentMilli: 654, powerCenti: 456))
    #expect(try snapshot(row: 1, frames: frames).readings[2].currentMilli == 322)
    #expect(try snapshot(row: 2, frames: frames).readings[2] == PortReading(port: .c3, active: true, voltageMilli: 12345, currentMilli: 323, powerCenti: 125))
    #expect(try snapshot(row: 2, frames: frames).readings[3].currentMilli == 656)
    for index in frames.indices {
        let value = try snapshot(row: index, frames: frames)
        #expect(value.readings.count == 6)
        #expect(value.readings[0].currentMilli == 7)
        #expect(value.readings.map(\.active) == [false, false, true, true, false, false])
        #expect(value.readings.map(\.port) == PortID.allCases)
        #expect(value.readings[2].currentMilli == 321 + index)
        #expect(value.readings[3].currentMilli == 654 + index)
        #expect(value.totalPowerCenti == 579 + 2 * index)
    }
}

@Test func signedFieldsUseWireIntegersAndReportedPower() throws {
    let fields = PortID.allCases.reversed().flatMap { [$0.fieldID, 8, 4, 1, 0xff, 0xff, 0, 0x80, 0xfe, 0xff] as [UInt8] }
    let snapshot = try #require(PortDecoder.snapshot(from: HexFrame.parse(syntheticFrame(fields: fields)), receivedAt: receivedAt))
    #expect(snapshot.readings.map(\.port) == PortID.allCases)
    #expect(snapshot.readings.allSatisfy { $0.voltageMilli == -1 && $0.currentMilli == -32768 && $0.powerCenti == -2 })
}

@Test func otherMessagesAndIncompletePortDataDoNotCreateSnapshots() throws {
    #expect(PortDecoder.snapshot(from: try HexFrame.parse(StatusRequest.frame(timestamp: 0)), receivedAt: receivedAt) == nil)
    #expect(PortDecoder.snapshot(from: try HexFrame.parse(syntheticFrame(fields: [0xa1, 1, 0x22])), receivedAt: receivedAt) == nil)
    for payload: [UInt8] in [[4, 1, 0, 0], [3, 1, 0, 0, 0, 0, 0, 0]] {
        let fields = PortID.allCases.flatMap { [$0.fieldID, UInt8(payload.count)] + payload }
        #expect(PortDecoder.snapshot(from: try HexFrame.parse(syntheticFrame(fields: fields)), receivedAt: receivedAt) == nil)
    }
}

// Detail fields follow anker-solix-api 9e72894 `_A2345_0a00` a3/b7/bd/be.
// Expectations below are written from that map, not from the generator.
private let detailRowReadings = [
    PortReading(port: .c1, active: false, voltageMilli: 0, currentMilli: 7, powerCenti: 0),
    PortReading(port: .c2, active: false, voltageMilli: 0, currentMilli: 7, powerCenti: 0),
    PortReading(port: .c3, active: true, voltageMilli: 12345, currentMilli: 321, powerCenti: 123),
    PortReading(port: .c4, active: true, voltageMilli: 23456, currentMilli: 654, powerCenti: 456),
    PortReading(port: .a1, active: false, voltageMilli: 0, currentMilli: 0, powerCenti: 0),
    PortReading(port: .a2, active: false, voltageMilli: 0, currentMilli: 0, powerCenti: 0),
]
private func device(_ vendor: UInt16, _ product: UInt16, _ brand: UInt16?, _ model: UInt16?) -> PortIdentity {
    .identified(vendorID: vendor, productID: product, brandClass: brand, modelCode: model)
}
private let mixed: [PortID: PortIdentity] = [
    .c1: .nothingAttached, .c2: .identifying,
    .c3: device(0xfeed, 0xbeef, 10, 7), .c4: device(0xc0de, 0x0042, 99, 0x0101),
]
private let fourWithoutMetadata: [PortID: PortIdentity] = [
    .c1: device(0xfeed, 0xbeef, nil, nil), .c2: device(0xc0de, 0x0042, nil, nil),
    .c3: device(0xfeed, 0x0001, nil, nil), .c4: device(0xfeed, 0x0002, nil, nil),
]
private let detailIDs: Set<UInt8> = [0xa3, 0xb7, 0xbd, 0xbe]
/// Six valid port readings for directly constructed frames.
private let idlePorts = Dictionary(uniqueKeysWithValues: PortID.allCases.map { ($0.fieldID, [0x04, 0, 0, 0, 7, 0, 0, 0] as [UInt8]) })

private func details(_ frame: [UInt8]) throws -> ChargerDetails {
    try #require(PortDecoder.snapshot(from: HexFrame.parse(frame), receivedAt: receivedAt)?.details)
}
private func constructedDetails(_ extra: [UInt8: [UInt8]]) throws -> ChargerDetails? {
    let frame = HexFrame(messageType: 0x0a00, fields: idlePorts.merging(extra) { $1 })
    return try #require(PortDecoder.snapshot(from: frame, receivedAt: receivedAt)).details
}

@Test func detailsCorpusDecodesToKnownValues() throws {
    let frames = try fixtureFrames("synthetic_0a00_details_frames")
    // (fault bits, identity support, identities, present detail fields) per row.
    let expected: [(UInt8?, UInt8?, [PortID: PortIdentity], Set<UInt8>)] = [
        (0x00, 6, mixed, detailIDs),
        (0x01, 2, [.c1: .nothingAttached, .c2: .nothingAttached, .c3: .nothingAttached, .c4: .nothingAttached], detailIDs),
        (0x3f, 6, mixed, detailIDs), // sile-encoded a3
        (0x0a, 6, mixed, detailIDs), // var-encoded a3
        (0x14, 6, mixed, detailIDs),
        (0x20, 6, mixed, detailIDs),
        (0xc0, 6, mixed, detailIDs),
        (nil, nil, [:], detailIDs), // all str
        (nil, nil, [:], detailIDs), // all ui
        (0x08, 6, mixed, detailIDs), // all sile
        (0x08, 6, mixed, detailIDs), // all var
        (0x08, 6, mixed, detailIDs), // all bin
        (nil, nil, [:], detailIDs), // all sfle
        (nil, 6, mixed, detailIDs), // all strb
        (nil, nil, [:], detailIDs), // all json
        (nil, nil, [:], detailIDs), // all unk
        (0x00, nil, mixed, [0xa3, 0xbd, 0xbe]),
        (0x00, 6, [.c1: device(0xfeed, 0xbeef, 10, 7)], detailIDs),
        (nil, 6, [.c1: device(0xfeed, 0xbeef, 10, 7), .c2: device(0xc0de, 0x0042, 99, 0x0101),
                  .c3: device(0xfeed, 0x0001, 5, nil), .c4: device(0xfeed, 0x0002, nil, nil)], [0xb7, 0xbd, 0xbe]),
        (nil, nil, fourWithoutMetadata, detailIDs),
        (0x00, 6, fourWithoutMetadata, detailIDs),
        (0x00, 6, [.c1: device(0xfeed, 0xbeef, nil, 7), .c2: device(0xc0de, 0x0042, 10, nil),
                   .c3: device(0xfeed, 0x0001, 19, 0), .c4: device(0xfeed, 0x0002, 0x1234, 0)], detailIDs),
        (nil, 2, [:], [0xb7]),
    ]
    #expect(frames.count == expected.count)
    #expect(Set(frames).count == frames.count)
    let detailFree = try snapshot(row: 0, frames: try syntheticCorpusFrames())
    for (row, expectation) in expected.enumerated() {
        let (bits, support, identities, present) = expectation
        let frame = try HexFrame.parse(frames[row])
        let value = try #require(PortDecoder.snapshot(from: frame, receivedAt: receivedAt), "row \(row)")
        // Readings match literal values, the detail-free corpus and the stripped frame.
        #expect(value.readings == detailRowReadings, "row \(row)")
        #expect(value.readings == detailFree.readings, "row \(row)")
        let stripped = HexFrame(messageType: 0x0a00, fields: frame.fields.filter { !detailIDs.contains($0.key) })
        #expect(PortDecoder.snapshot(from: stripped, receivedAt: receivedAt) == ChargerSnapshot(receivedAt: receivedAt, readings: detailRowReadings))
        let details = try #require(value.details, "row \(row)")
        #expect(details.faultBits == bits, "row \(row)")
        #expect(details.identitySupport == support, "row \(row)")
        #expect(details.identities == identities, "row \(row)")
        #expect(Set(details.rawFields.keys) == present, "row \(row)")
        #expect(details.rawFields == frame.fields.filter { detailIDs.contains($0.key) }, "row \(row)")
    }
    // Verbatim payloads, type byte included.
    #expect(try details(frames[0]).rawFields == [
        0xa3: [0x04, 0x00, 0x00],
        0xb7: [0x04, 0xff, 0x06],
        0xbd: [0x04, 0xfa, 0xff, 0xfb, 0xff, 0x00, 0x00, 0x00, 0x00, 0xed, 0xfe, 0xef, 0xbe, 0xde, 0xc0, 0x42, 0x00],
        0xbe: [0x04, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x0a, 0x00, 0x07, 0x00, 0x63, 0x00, 0x01, 0x01],
    ])
    #expect(try details(frames[2]).rawFields[0xa3] == [0x02, 0x3f, 0x00])
    #expect(try details(frames[5]).rawFields[0xa3] == [0x04, 0x20, 0xff])
    #expect(try details(frames[17]).rawFields[0xbd] == [0x04, 0xed, 0xfe, 0xef, 0xbe, 0xde, 0xc0])
    #expect(try details(frames[18]).rawFields[0xbe] == [0x04, 0x0a, 0x00, 0x07, 0x00, 0x63, 0x00, 0x01, 0x01, 0x05, 0x00])
    let missing = try details(frames[19]).rawFields
    #expect(missing[0xa3] == [0x04] && missing[0xb7] == [0x04, 0xff] && missing[0xbe] == [0x04])
    for (offset, type) in ([0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0xfe, 0xff] as [UInt8]).enumerated() {
        #expect(try details(frames[7 + offset]).rawFields.values.allSatisfy { $0.first == type }, "type \(type)")
    }
    #expect(try details(frames[20]).rawFields[0xbe]?.first == 0x01)
}

@Test func existingCorpusHasNoDetails() throws {
    for frame in try syntheticCorpusFrames() {
        #expect(try #require(PortDecoder.snapshot(from: HexFrame.parse(frame), receivedAt: receivedAt)).details == nil)
    }
}

@Test func detailsFieldTypesMatchUpstream() throws {
    // DeviceHexDataField.extract_value at 9e72894: sile/var/bin reach BYTES
    // extraction for every detail map; strb reads b7/bd/be but not a3's mask
    // list; ui, str, sfle, json, unk and every other type byte extract nothing.
    let payloads: [UInt8: [UInt8]] = [
        0xa3: [0x3f, 0x00],
        0xb7: [0xff, 0x06],
        0xbd: [0xed, 0xfe, 0xef, 0xbe, 0xde, 0xc0, 0x42, 0x00, 0x00, 0x00, 0x00, 0x00, 0xfa, 0xff, 0xfb, 0xff],
        0xbe: [0x0a, 0x00, 0x07, 0x00, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff],
    ]
    let accepted: [UInt8: Set<UInt8>] = [
        0xa3: [0x02, 0x03, 0x04],
        0xb7: [0x02, 0x03, 0x04, 0x06],
        0xbd: [0x02, 0x03, 0x04, 0x06],
        0xbe: [0x02, 0x03, 0x04, 0x06],
    ]
    let validIDs = [0x04] + payloads[0xbd]!
    for type in UInt8.min...UInt8.max {
        for (id, value) in payloads {
            // be metadata needs a valid bd identity to attach to.
            let extra = id == 0xbe ? [id: [type] + value, 0xbd: validIDs] : [id: [type] + value]
            let decoded = try #require(try constructedDetails(extra))
            let accepts = accepted[id]!.contains(type)
            #expect(decoded.rawFields[id] == [type] + value)
            switch id {
            case 0xa3: #expect(decoded.faultBits == (accepts ? 0x3f : nil), "type \(type)")
            case 0xb7: #expect(decoded.identitySupport == (accepts ? 6 : nil), "type \(type)")
            case 0xbd:
                #expect(decoded.identities == (accepts ? [.c1: device(0xfeed, 0xbeef, nil, nil), .c2: device(0xc0de, 0x0042, nil, nil),
                                                          .c3: .identifying, .c4: .nothingAttached] : [:]), "type \(type)")
            default:
                #expect(decoded.identities[.c1] == device(0xfeed, 0xbeef, accepts ? 10 : nil, accepts ? 7 : nil), "type \(type)")
                #expect(decoded.identities[.c2] == device(0xc0de, 0x0042, nil, nil), "type \(type)")
            }
        }
    }
}

@Test func malformedAndPartialDetailFieldsKeepUsableParts() throws {
    let portFields = PortID.allCases.flatMap { [$0.fieldID, 8, 4, 0, 0, 0, 7, 0, 0, 0] as [UInt8] }
    // No detail field: no details. Unrelated fields do not create details.
    #expect(try constructedDetails([:]) == nil)
    #expect(try constructedDetails([0xb6: [0x01], 0xbf: [0x01]]) == nil)
    // The parser rejects a zero-length field and a field running past the
    // frame; direct construction still preserves a present empty payload.
    #expect(throws: HexFrameError.truncatedField) { try HexFrame.parse(syntheticFrame(fields: portFields + [0xbd, 0])) }
    #expect(throws: HexFrameError.truncatedField) { try HexFrame.parse(syntheticFrame(fields: portFields + [0xbd, 17, 4, 0xed, 0xfe])) }
    #expect(try constructedDetails([0xbd: []]) == ChargerDetails(faultBits: nil, identitySupport: nil, identities: [:], rawFields: [0xbd: []]))
    // Missing support: other fields remain usable.
    #expect(try constructedDetails([0xa3: [0x04, 0x02, 0x00], 0xbd: [0x04, 0xed, 0xfe, 0xef, 0xbe]]) == ChargerDetails(
        faultBits: 0x02, identitySupport: nil, identities: [.c1: device(0xfeed, 0xbeef, nil, nil)],
        rawFields: [0xa3: [0x04, 0x02, 0x00], 0xbd: [0x04, 0xed, 0xfe, 0xef, 0xbe]]))
    // Short identity data: a vendor without product is unknown, never nothing-attached.
    #expect(try constructedDetails([0xbd: [0x04, 0xed, 0xfe, 0xef]])?.identities == [:])
    #expect(try constructedDetails([0xbd: [0x04, 0xfa, 0xff, 0xfb, 0xff, 0x00, 0x00, 0x00]])?.identities == [.c1: .nothingAttached])
    // Short metadata: a class without its model code.
    #expect(try constructedDetails([0xbd: [0x04, 0xed, 0xfe, 0xef, 0xbe], 0xbe: [0x04, 0x0a, 0x00, 0x07]])?.identities
            == [.c1: device(0xfeed, 0xbeef, 10, nil)])
    // Missing value bytes after the type byte.
    #expect(try constructedDetails([0xa3: [0x04], 0xb7: [0x04, 0xff], 0xbe: [0x04]]) == ChargerDetails(
        faultBits: nil, identitySupport: nil, identities: [:], rawFields: [0xa3: [0x04], 0xb7: [0x04, 0xff], 0xbe: [0x04]]))
    // Unsupported types keep raw evidence without decoded values.
    #expect(try constructedDetails([0xa3: [0x01, 0x3f], 0xb7: [0x05, 0xff, 0x06]]) == ChargerDetails(
        faultBits: nil, identitySupport: nil, identities: [:], rawFields: [0xa3: [0x01, 0x3f], 0xb7: [0x05, 0xff, 0x06]]))
    // Unsigned identity reads; signed port readings are unchanged.
    let high = try #require(PortDecoder.snapshot(from: HexFrame(messageType: 0x0a00, fields: idlePorts.merging([
        0xa4: [0x04, 1, 0xff, 0xff, 0, 0x80, 0xfe, 0xff],
        0xbd: [0x04, 0xff, 0xff, 0x00, 0x80],
    ]) { $1 }), receivedAt: receivedAt))
    #expect(high.readings[0] == PortReading(port: .c1, active: true, voltageMilli: -1, currentMilli: -32768, powerCenti: -2))
    #expect(high.details?.identities == [.c1: device(0xffff, 0x8000, nil, nil)])
    // Mandatory readings still gate the snapshot even with valid details.
    var incomplete = idlePorts.merging([0xa3: [0x04, 0x01, 0x00]]) { $1 }
    incomplete[0xa9] = nil
    #expect(PortDecoder.snapshot(from: HexFrame(messageType: 0x0a00, fields: incomplete), receivedAt: receivedAt) == nil)
}
