import Foundation
import Testing
import PrimeMonitorCore
@testable import PrimeMonitor

struct StatusPresentationTests {
    let now = Date(timeIntervalSince1970: 1000)
    var snapshot: ChargerSnapshot { .init(receivedAt: now.addingTimeInterval(-12), readings: [.init(port: .c4, active: true, voltageMilli: 20000, currentMilli: 1551, powerCenti: 4321)]) }
    @Test func liveShowsBoltAndTotal() {
        let value = StatusPresentation.make(status: .connected, snapshot: snapshot, isStale: false, now: now)
        #expect(value.symbol == "bolt.fill" && value.title == DisplayFormatter.watts(centi: 4321, separator: "\u{2009}"))
        #expect(!value.dimmed && value.tooltip.contains("12 s ago"))
        #expect(value.accessibility.contains("43.21 W"))
    }
    @Test func staleDimsAndWarns() {
        let value = StatusPresentation.make(status: .connected, snapshot: snapshot, isStale: true, now: now)
        #expect(value.symbol == "exclamationmark.triangle.fill" && value.dimmed)
        #expect(value.tooltip.contains("Stale") && value.tooltip.contains("12 s ago"))
        #expect(value.title == "43.21\u{2009}W")
    }
    @Test func textSizeCarriesThroughEveryState() {
        for status in [ConnectionStatus.notConfigured, .connected, .networkUnavailable] {
            #expect(StatusPresentation.make(status: status, snapshot: snapshot, isStale: false, now: now, textSize: .pt11).textSize == .pt11)
        }
        #expect(StatusPresentation.make(status: .connected, snapshot: snapshot, isStale: false, now: now).textSize == .default)
    }
    @Test func notConfiguredShowsSymbolOnly() {
        let value = StatusPresentation.make(status: .notConfigured, snapshot: nil, isStale: true, now: now)
        #expect(value.symbol == "bolt.fill" && value.title.isEmpty)
        #expect(value.tooltip.contains("Settings"))
    }
    @Test func errorStatesDimAndWarn() {
        for status in [ConnectionStatus.error("Synthetic problem"), .signInFailed("Synthetic sign-in"), .sessionEnded, .verificationRequired, .networkUnavailable] {
            let value = StatusPresentation.make(status: status, snapshot: snapshot, isStale: false, now: now)
            #expect(value.dimmed && value.symbol == "exclamationmark.triangle.fill")
            #expect(value.title == "43.21\u{2009}W" && !value.tooltip.isEmpty)
        }
    }
}
