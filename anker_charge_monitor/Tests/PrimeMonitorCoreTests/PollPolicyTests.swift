import Foundation
import Testing
import PrimeMonitorCore

@Test func intervals() {
    #expect(ClosedInterval.allCases.map(\.rawValue) == [30, 60, 120, 300])
    #expect(ClosedInterval.default == .m1)
    #expect(PollPolicy.openInterval == 5)
    #expect(PollPolicy.replyDeadline == 10)
    for closed in ClosedInterval.allCases {
        #expect(PollPolicy.interval(panelOpen: true, closed: closed, asleep: false) == 5)
        #expect(PollPolicy.interval(panelOpen: false, closed: closed, asleep: false) == Double(closed.rawValue))
        #expect(PollPolicy.interval(panelOpen: true, closed: closed, asleep: true) == nil)
        #expect(PollPolicy.interval(panelOpen: false, closed: closed, asleep: true) == nil)
    }
}

@Test func closedIntervalsRoundTripThroughSettings() throws {
    for closed in ClosedInterval.allCases {
        let data = try JSONEncoder().encode(closed)
        #expect(try JSONDecoder().decode(ClosedInterval.self, from: data) == closed)
    }
    #expect(throws: (any Error).self) {
        try JSONDecoder().decode(ClosedInterval.self, from: Data("45".utf8))
    }
}
