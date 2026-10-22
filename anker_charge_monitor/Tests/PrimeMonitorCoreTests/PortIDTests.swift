import Testing
@testable import PrimeMonitorCore

@Test func portsMapToUpstreamFieldsInFrontPanelOrder() {
    #expect(PortID.allCases.map(\.label) == ["C1", "C2", "C3", "C4", "A1", "A2"])
    #expect(PortID.allCases.map(\.fieldID) == [0xa4, 0xa5, 0xa6, 0xa7, 0xa8, 0xa9])
    #expect(PortID(fieldID: 0xa6) == .c3 && PortID(fieldID: 0xaa) == nil)
}

@Test func usbCPortsAreTheFourIdentityPorts() {
    #expect(PortID.usbC == [.c1, .c2, .c3, .c4])
    #expect(PortID.allCases.filter(\.isUSBC) == PortID.usbC)
    #expect(!PortID.a1.isUSBC && !PortID.a2.isUSBC)
}
