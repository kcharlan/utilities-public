import Foundation
import Testing
import PrimeMonitorCore

private func time(_ seconds: TimeInterval) -> Date { Date(timeIntervalSince1970: seconds) }

@Test func oneMissIsNotStaleTwoMissesAre() {
    var tracker = StalenessTracker(closed: .m1)
    tracker.requestSent(at: time(0))
    tracker.requestSent(at: time(5))
    tracker.requestSent(at: time(10))
    #expect(!tracker.isStale(snapshotAt: time(0), now: time(14.999)))
    #expect(tracker.isStale(snapshotAt: time(0), now: time(15)))
    tracker.replyReceived(at: time(16))
    #expect(!tracker.isStale(snapshotAt: time(16), now: time(30)))
}

@Test(arguments: ClosedInterval.allCases)
func openCloseOpenNeverFlagsHealthyData(closed: ClosedInterval) {
    var tracker = StalenessTracker(closed: closed)
    var snapshot = time(0)
    for seconds in [0.0, 5, 10, 10 + Double(closed.rawValue), 11 + Double(closed.rawValue)] {
        tracker.requestSent(at: time(seconds))
        #expect(!tracker.isStale(snapshotAt: snapshot, now: time(seconds + 1)))
        snapshot = time(seconds + 1)
        tracker.replyReceived(at: snapshot)
        #expect(!tracker.isStale(snapshotAt: snapshot, now: snapshot))
    }
}

@Test(arguments: ClosedInterval.allCases)
func reopenBeforeFirstClosedRequestIsNotStale(closed: ClosedInterval) {
    var tracker = StalenessTracker(closed: closed)
    tracker.replyReceived(at: time(0))
    let reopened = Double(closed.rawValue) - 1
    tracker.requestSent(at: time(reopened))
    #expect(!tracker.isStale(snapshotAt: time(0), now: time(reopened)))
    tracker.replyReceived(at: time(reopened + 1))
    #expect(!tracker.isStale(snapshotAt: time(reopened + 1), now: time(reopened + 5)))
}

@Test func failureWhileOpenFlagsWithinTwoPolls() {
    var tracker = StalenessTracker(closed: .m5)
    tracker.requestSent(at: time(5))
    tracker.requestSent(at: time(10))
    tracker.requestSent(at: time(15))
    #expect(!tracker.isStale(snapshotAt: time(0), now: time(19.999)))
    #expect(tracker.isStale(snapshotAt: time(0), now: time(20)))
}

@Test(arguments: ClosedInterval.allCases)
func failureThenCloseStillFlags(closed: ClosedInterval) {
    var tracker = StalenessTracker(closed: closed)
    tracker.requestSent(at: time(5))
    tracker.requestSent(at: time(10))
    #expect(tracker.isStale(snapshotAt: time(0), now: time(20)))
    #expect(tracker.isStale(snapshotAt: time(0), now: time(20 + Double(closed.rawValue))))
}

@Test(arguments: ClosedInterval.allCases)
func wakeAfterLongSleepIsStaleUntilReply(closed: ClosedInterval) {
    var tracker = StalenessTracker(closed: closed)
    #expect(tracker.isStale(snapshotAt: nil, now: time(0)))
    tracker.replyReceived(at: time(0))
    #expect(tracker.isStale(snapshotAt: time(0), now: time(3600)))
    tracker.requestSent(at: time(3600))
    #expect(tracker.isStale(snapshotAt: time(0), now: time(3601)))
    tracker.replyReceived(at: time(3602))
    #expect(!tracker.isStale(snapshotAt: time(3602), now: time(3602)))
}

@Test func shorterIntervalWithImmediateAnsweredRequestIsNotStale() {
    var tracker = StalenessTracker(closed: .m5)
    tracker.setClosedInterval(.s30, at: time(200))
    tracker.requestSent(at: time(200))
    #expect(!tracker.isStale(snapshotAt: time(0), now: time(209.999)))
    tracker.replyReceived(at: time(209))
    #expect(!tracker.isStale(snapshotAt: time(209), now: time(211)))
}

@Test func shortenedIntervalUsesNewBackstopAtUnansweredDeadline() {
    var tracker = StalenessTracker(closed: .m5)
    tracker.setClosedInterval(.s30, at: time(200))
    tracker.requestSent(at: time(200))
    #expect(!tracker.isStale(snapshotAt: time(0), now: time(209.999)))
    #expect(tracker.isStale(snapshotAt: time(0), now: time(210)))
}

@Test func shorteningNeverHidesExistingAgeOrMissWarnings() {
    var ageTracker = StalenessTracker(closed: .m5)
    ageTracker.setClosedInterval(.s30, at: time(700))
    #expect(ageTracker.isStale(snapshotAt: time(0), now: time(701)))
    var missTracker = StalenessTracker(closed: .m5)
    missTracker.requestSent(at: time(180))
    missTracker.requestSent(at: time(185))
    missTracker.setClosedInterval(.s30, at: time(200))
    #expect(missTracker.isStale(snapshotAt: time(179), now: time(201)))
}

@Test func shorteningKeepsMissDetectionActiveDuringGrace() {
    var tracker = StalenessTracker(closed: .m5)
    tracker.requestSent(at: time(190))
    tracker.requestSent(at: time(195))
    tracker.setClosedInterval(.s30, at: time(200))
    tracker.requestSent(at: time(200))
    #expect(!tracker.isStale(snapshotAt: time(189), now: time(204.999)))
    #expect(tracker.isStale(snapshotAt: time(189), now: time(205)))
}

@Test func freshReplyEndsGraceAndResetsEvenFinalizedMisses() {
    var tracker = StalenessTracker(closed: .m5)
    tracker.requestSent(at: time(0))
    tracker.requestSent(at: time(5))
    tracker.requestSent(at: time(20))
    tracker.setClosedInterval(.s30, at: time(200))
    tracker.replyReceived(at: time(201))
    #expect(!tracker.isStale(snapshotAt: time(201), now: time(271)))
    #expect(tracker.isStale(snapshotAt: time(201), now: time(271.001)))
}

@Test(arguments: [(ClosedInterval.s30, 70.0), (.m1, 130.0), (.m2, 250.0), (.m5, 610.0)])
func ageBackstopStrictlyExceedsThreshold(closed: ClosedInterval, threshold: TimeInterval) {
    let tracker = StalenessTracker(closed: closed)
    #expect(!tracker.isStale(snapshotAt: time(0), now: time(threshold)))
    #expect(tracker.isStale(snapshotAt: time(0), now: time(threshold + 0.001)))
}

@Test func longerOrUnchangedIntervalDoesNotAddGrace() {
    var tracker = StalenessTracker(closed: .s30)
    tracker.setClosedInterval(.m1, at: time(200))
    #expect(tracker.isStale(snapshotAt: time(0), now: time(201)))
    tracker.setClosedInterval(.m1, at: time(201))
    #expect(tracker.isStale(snapshotAt: time(0), now: time(202)))
}
