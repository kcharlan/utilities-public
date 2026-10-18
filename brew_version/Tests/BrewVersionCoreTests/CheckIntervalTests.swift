import Foundation
import Testing
@testable import BrewVersionCore

struct CheckIntervalTests {
    @Test func exposedBoundsAndValidationMessage() {
        #expect(CheckInterval.allowedMinutes == 10...1440)
        #expect(CheckInterval.validationMessage(locale: Locale(identifier: "en_US")) == "Enter 10 to 1,440 minutes.")
        #expect(CheckInterval.validationMessage(locale: Locale(identifier: "de_DE")) == "Enter 10 to 1.440 minutes.")
    }
    @Test func rangePresetsLabelsAndSchedule() {
        #expect(CheckInterval(minutes: 9) == nil)
        #expect(CheckInterval(minutes: 10) != nil)
        #expect(CheckInterval(minutes: 1440) != nil)
        #expect(CheckInterval(minutes: 1441) == nil)
        for minutes in 10...1440 { #expect(CheckInterval(minutes: minutes)?.minutes == minutes) }
        #expect(CheckInterval.presets.map(\.minutes) == [10, 15, 30, 60, 120, 360])
        #expect(CheckInterval.standard.minutes == 30)
        for (minutes, label) in [(10,"10 minutes"),(60,"1 hour"),(120,"2 hours"),(45,"45 minutes"),(90,"90 minutes"),(1440,"24 hours")] {
            #expect(CheckInterval(minutes: minutes)?.label == label)
        }
        let start = Date(timeIntervalSince1970: 100)
        #expect(CheckSchedule.nextDue(lastCheck: nil, interval: .standard) == nil)
        #expect(CheckSchedule.isDue(lastCheck: nil, interval: .standard, now: start))
        #expect(!CheckSchedule.isDue(lastCheck: start, interval: .standard, now: start.addingTimeInterval(1740)))
        #expect(CheckSchedule.isDue(lastCheck: start, interval: .standard, now: start.addingTimeInterval(1800)))
    }
    @Test func decodingValidatesMinutes() throws {
        for raw in [#"{"minutes":9}"#, #"{"minutes":1441}"#, #"{"minutes":10.5}"#] {
            #expect(throws: (any Error).self) { try JSONDecoder().decode(CheckInterval.self, from: Data(raw.utf8)) }
        }
        #expect(try JSONDecoder().decode(CheckInterval.self, from: Data(#"{"minutes":10}"#.utf8)).minutes == 10)
    }
}
