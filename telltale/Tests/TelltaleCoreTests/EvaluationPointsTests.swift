import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

@Suite struct EvaluationPointsTests {
    let calendar = Synth.newYork

    func local(_ hour: Int, _ minute: Int, _ second: Int = 0) -> Date { Synth.local(2026, 9, 4, hour, minute, second) }

    func isOnBoundary(_ date: Date) -> Bool {
        let parts = calendar.dateComponents([.minute, .second, .nanosecond], from: date)
        return parts.minute! % 5 == 0 && parts.second == 0 && parts.nanosecond == 0
    }

    @Test func pointsOnFiveMinuteBoundaries() {
        // Spec section 7.1: every 5 minutes on wall-clock boundaries (:00, :05, …).
        let points = EvaluationPoints.after(nil, through: local(9, 21, 40), earliest: local(9, 2, 17))
        #expect(points == [local(9, 5), local(9, 10), local(9, 15), local(9, 20)])
        #expect(points.allSatisfy(isOnBoundary))
        #expect(EvaluationPoints.cadence == 300)
    }

    @Test func afterLastPointExclusive() {
        #expect(EvaluationPoints.after(local(9, 10), through: local(9, 20), earliest: local(8, 0)) == [local(9, 15), local(9, 20)])
        // A last point between boundaries resumes at the next boundary.
        #expect(EvaluationPoints.after(local(9, 12, 30), through: local(9, 20), earliest: local(8, 0)) == [local(9, 15), local(9, 20)])
        // Nothing new yet.
        #expect(EvaluationPoints.after(local(9, 20), through: local(9, 24, 59), earliest: local(8, 0)).isEmpty)
    }

    @Test func cappedAtEarliest() {
        // An earliest on a boundary is itself a point; an older last point doesn't reach before it.
        #expect(EvaluationPoints.after(local(7, 0), through: local(9, 10), earliest: local(9, 0)) == [local(9, 0), local(9, 5), local(9, 10)])
        #expect(EvaluationPoints.after(nil, through: local(9, 10), earliest: local(9, 0)) == [local(9, 0), local(9, 5), local(9, 10)])
        #expect(EvaluationPoints.after(nil, through: local(8, 59), earliest: local(9, 0)).isEmpty)
    }

    @Test func evaluationPointsAcrossDSTAreContiguous() {
        // America/New_York falls back on Sun 2026-11-01 at 06:00Z (02:00 EDT becomes 01:00 EST).
        // 1_793_511_000 = 05:30Z = 01:30 EDT; 1_793_518_200 = 07:30Z = 02:30 EST: two real hours.
        let first = Date(timeIntervalSince1970: 1_793_511_000)
        let last = Date(timeIntervalSince1970: 1_793_518_200)
        let points = EvaluationPoints.after(nil, through: last, earliest: Date(timeIntervalSince1970: 1_793_510_999))

        #expect(points.count == 25)
        #expect(points.first == first)
        #expect(points.last == last)
        let gaps = zip(points, points.dropFirst()).map { $1.timeIntervalSince($0) }
        #expect(gaps.allSatisfy { $0 == 300 })
        #expect(Set(points).count == points.count)
        #expect(points.allSatisfy(isOnBoundary))

        // The repeated local hour is evaluated twice: 01:55 EDT (05:55Z) and 01:55 EST (06:55Z).
        let firstLocal = calendar.dateComponents([.day, .hour, .minute], from: Date(timeIntervalSince1970: 1_793_512_500))
        let repeatedLocal = calendar.dateComponents([.day, .hour, .minute], from: Date(timeIntervalSince1970: 1_793_516_100))
        #expect(firstLocal == repeatedLocal)
        #expect(points.contains(Date(timeIntervalSince1970: 1_793_512_500)))
        #expect(points.contains(Date(timeIntervalSince1970: 1_793_516_100)))
    }

    @Test func durationsBecomePointCounts() {
        // Plan call: round up, at least 1 point.
        let cases: [(Int, Int)] = [(1, 1), (4, 1), (5, 1), (6, 2), (10, 2), (11, 3), (15, 3), (30, 6), (31, 7)]
        for (minutes, points) in cases {
            #expect(EvaluationPoints.count(forMinutes: minutes) == points, "\(minutes) minutes")
        }
    }
}
