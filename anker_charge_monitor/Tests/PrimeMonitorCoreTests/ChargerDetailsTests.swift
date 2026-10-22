import Foundation
import Testing
import PrimeMonitorCore

// Masks and sentinels from anker-solix-api 9e72894, `mqttmap.py` `_A2345_0a00`
// keys a3 (fault bits), bd (vendor/product IDs) and be (class/model code).
private func details(_ bits: UInt8?) -> ChargerDetails {
    ChargerDetails(faultBits: bits, identitySupport: nil, identities: [:], rawFields: [:])
}

@Test func faultMasksMatchProtocolAuthority() {
    let ports: [PortID] = [.c1, .c2, .c3, .c4, .a1, .a2]
    #expect(details(0x01).overTemperature == true)
    #expect(ports.allSatisfy { details(0x01).fault($0) == false })
    #expect(ports.map { details(0x02).fault($0) } == [true, false, false, false, false, false])
    #expect(ports.map { details(0x04).fault($0) } == [false, true, false, false, false, false])
    #expect(ports.map { details(0x08).fault($0) } == [false, false, true, false, false, false])
    #expect(ports.map { details(0x10).fault($0) } == [false, false, false, true, false, false])
    // usba_fault? covers either USB-A port: both report the one shared bit.
    #expect(ports.map { details(0x20).fault($0) } == [false, false, false, false, true, true])
    #expect(details(0x20).overTemperature == false)
    #expect(ports.allSatisfy { details(0x3f).fault($0) == true } && details(0x3f).overTemperature == true)
    #expect(ports.map { details(0x0b).fault($0) } == [true, false, true, false, false, false])
    #expect(details(0x0b).overTemperature == true)
}

@Test func clearAndUnmappedBitsAreDecodedClear() {
    for bits: UInt8 in [0x00, 0x40, 0x80, 0xc0] {
        #expect(details(bits).overTemperature == false)
        #expect(PortID.allCases.allSatisfy { details(bits).fault($0) == false })
        #expect(details(bits).faultBits == bits)
    }
}

@Test func unknownFaultBitsMakeNoClaim() {
    #expect(details(nil).overTemperature == nil)
    #expect(PortID.allCases.allSatisfy { details(nil).fault($0) == nil })
}

@Test func identitySentinelsMatchProtocolAuthority() {
    #expect(PortIdentity.reported(vendorID: 0xfffa, productID: 0xfffb, brandClass: 10, modelCode: 7) == .nothingAttached)
    #expect(PortIdentity.reported(vendorID: 0, productID: 0, brandClass: 10, modelCode: 7) == .identifying)
    // Only the exact pairs are sentinels.
    #expect(PortIdentity.reported(vendorID: 0xfffa, productID: 0x0001, brandClass: nil, modelCode: nil)
            == .identified(vendorID: 0xfffa, productID: 0x0001, brandClass: nil, modelCode: nil))
    #expect(PortIdentity.reported(vendorID: 0xfeed, productID: 0xfffb, brandClass: nil, modelCode: nil)
            == .identified(vendorID: 0xfeed, productID: 0xfffb, brandClass: nil, modelCode: nil))
    #expect(PortIdentity.reported(vendorID: 0, productID: 0xbeef, brandClass: nil, modelCode: nil)
            == .identified(vendorID: 0, productID: 0xbeef, brandClass: nil, modelCode: nil))
    #expect(PortIdentity.reported(vendorID: 0xc0de, productID: 0, brandClass: nil, modelCode: nil)
            == .identified(vendorID: 0xc0de, productID: 0, brandClass: nil, modelCode: nil))
}

@Test func optionalMetadataIsIndependentlyMissing() {
    func identified(_ brand: UInt16?, _ model: UInt16?) -> PortIdentity {
        .reported(vendorID: 0xfeed, productID: 0xbeef, brandClass: brand, modelCode: model)
    }
    func expected(_ brand: UInt16?, _ model: UInt16?) -> PortIdentity {
        .identified(vendorID: 0xfeed, productID: 0xbeef, brandClass: brand, modelCode: model)
    }
    #expect(identified(10, 7) == expected(10, 7))
    #expect(identified(0xffff, 0xffff) == expected(nil, nil))
    #expect(identified(0xffff, 7) == expected(nil, 7))
    #expect(identified(10, 0xffff) == expected(10, nil))
    #expect(identified(nil, 7) == expected(nil, 7))
    #expect(identified(10, nil) == expected(10, nil))
    // Unknown classes and zero values remain reported numbers.
    #expect(identified(99, 0) == expected(99, 0))
    #expect(identified(0, 0xfffe) == expected(0, 0xfffe))
    #expect(PortIdentity.absent == 0xffff)
}

@Test func detailsDefaultToNilOnSnapshots() {
    #expect(ChargerSnapshot(receivedAt: .distantPast, readings: []).details == nil)
    let value = details(0x01)
    #expect(ChargerSnapshot(receivedAt: .distantPast, readings: [], details: value).details == value)
}
