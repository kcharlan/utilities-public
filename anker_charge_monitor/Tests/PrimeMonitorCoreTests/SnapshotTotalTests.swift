import Foundation
import Testing
@testable import PrimeMonitorCore

extension ChargerSnapshot {
    static func fixture(c3: (Bool, Int, Int, Int), c4: (Bool, Int, Int, Int)) -> Self {
        Self(receivedAt: Date(timeIntervalSince1970: 0), readings: PortID.allCases.map { port in
            let value = port == .c3 ? c3 : port == .c4 ? c4 : (false, 0, 0, 0)
            return PortReading(port: port, active: value.0, voltageMilli: value.1,
                               currentMilli: value.2, powerCenti: value.3)
        })
    }
}
@Test func totalSumsReportedPowerOnly() {
    let s = ChargerSnapshot.fixture(c3: (true, 12345, 321, 123), c4: (true, 23456, 654, 456))
    #expect(s.totalPowerCenti == 579 && DisplayFormatter.watts(centi: 579) == "5.79 W")
}
@Test func snapshotOrdersReadingsAndRetainsInactiveReportedPower() {
    let s = ChargerSnapshot(receivedAt: Date(), readings: [
        PortReading(port: .a2, active: false, voltageMilli: 0, currentMilli: 20, powerCenti: -1),
        PortReading(port: .c1, active: true, voltageMilli: 5000, currentMilli: 100, powerCenti: 50)
    ])
    #expect(s.readings.map(\.port) == [.c1, .a2])
    #expect(s.totalPowerCenti == 49)
}
