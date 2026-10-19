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
