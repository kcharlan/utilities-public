import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

@Suite struct NotificationPolicyTests {
    @Test func episodeThreadIDMatchesNotice() {
        let result = select([outcome(at: latest, fired(latest))])
        #expect(result.first?.threadID == NotificationPolicy.threadID(rule: .slower, provider: "codex", scope: Synth.model))
        #expect(result.first?.threadID == "slower.codex.\(Synth.model)")
    }
    @Test func clearedAndCatchUpBodiesArePrefixed() {
        let info = RuleProviderInfo(name: "Synthetic Provider", failureNoun: "request", signals: [.speed], rules: [.slower], naming: SyntheticNaming())
        var notices = FailureNotices()
        let caughtUp = outcome(at: minutesBefore(30), fired(minutesBefore(30)), catchUp: "Synthetic Provider: slower")
        let selected = NotificationPolicy.select([caughtUp], latestPoint: latest, intervalMinutes: 5, settings: .defaults, mode: .live,
            failureNotices: &notices, calendar: calendar, provider: info)
        #expect(selected.map(\.body) == ["Synthetic Provider: slower"])
        let clear = outcome(at: latest, .cleared, message: "back")
        let cleared = NotificationPolicy.select([clear], latestPoint: latest, intervalMinutes: 5, settings: .defaults, mode: .live,
            failureNotices: &notices, calendar: calendar, provider: info)
        #expect(cleared.map(\.body) == ["Synthetic Provider: back"])
    }
    let calendar = Synth.newYork
    let latest = Synth.local(2026, 9, 4, 12, 0)

    func minutesBefore(_ minutes: Double) -> Date { latest.addingTimeInterval(-minutes * 60) }

    func outcome(
        _ rule: RuleID = .slower, at: Date, _ transition: Transition?, episode: Int64 = 1, scope: String = Synth.model,
        failures: [FailedTurnRecord] = [], message: String? = nil, catchUp: String? = nil
    ) -> RuleOutcome {
        RuleOutcome(
            at: at, rule: rule, provider: "codex", scope: scope, transition: transition, failures: failures, episodeID: episode,
            title: rule.title, message: message ?? "\(rule.rawValue) message at \(at.timeIntervalSince1970)", catchUpMessage: catchUp)
    }

    func fired(_ at: Date, severity: LampColor = .amber) -> Transition { .fired(onset: at.addingTimeInterval(-900), severity: severity) }

    func select(
        _ outcomes: [RuleOutcome], latest: Date? = nil, interval: Int = 5, settings: RuleSettings = .defaults,
        mode: EvalMode = .live, notices: inout FailureNotices
    ) -> [PendingNotification] {
        NotificationPolicy.select(
            outcomes, latestPoint: latest ?? self.latest, intervalMinutes: interval, settings: settings, mode: mode,
            failureNotices: &notices, calendar: calendar)
    }

    func select(_ outcomes: [RuleOutcome], latest: Date? = nil, interval: Int = 5, settings: RuleSettings = .defaults, mode: EvalMode = .live) -> [PendingNotification] {
        var notices = FailureNotices()
        return select(outcomes, latest: latest, interval: interval, settings: settings, mode: mode, notices: &notices)
    }

    func failure(_ number: Int, at: Date, code: String = "serverOverloaded") -> FailedTurnRecord {
        FailedTurnRecord(
            provider: .codex, threadID: "thread_synthetic_\(number)", turnID: "turn_synthetic_\(number)", startedAt: at,
            completedAt: at, errorCode: code, message: "Synthetic failure \(number)")
    }

    @Test func reversedOutcomePostsNothing() {
        #expect(select([outcome(at: latest, .reversed)]).isEmpty)
    }
    @Test func reversalInsideACatchUpPassPostsNoStaleNotice() {
        let old = outcome(at: minutesBefore(60), fired(minutesBefore(60)), episode: 1, catchUp: "old")
        let end = outcome(at: minutesBefore(30), .reversed, episode: 1)
        let replacement = outcome(.faster, at: minutesBefore(30), fired(minutesBefore(30)), episode: 2, message: "reversed", catchUp: "new catch-up")
        #expect(select([old, end, replacement]).map(\.body) == ["new catch-up"])
        let fresh = outcome(.faster, at: latest, fired(latest), episode: 2, message: "reversed", catchUp: "new catch-up")
        #expect(select([outcome(at: latest, .reversed), fresh]).map(\.body) == ["reversed"])
    }
    @Test func backfillNeverNotifies() {
        var notices = FailureNotices()
        let outcomes = [
            outcome(at: latest, fired(latest)),
            outcome(.failedTurns, at: latest, fired(latest, severity: .red), episode: 2, scope: "*", failures: [failure(1, at: latest)]),
        ]
        #expect(select(outcomes, mode: .backfill, notices: &notices).isEmpty)
        #expect(notices == FailureNotices())
    }

    @Test func freshFireUsesFiredCopy() {
        let fire = outcome(at: latest, fired(latest), message: "fired copy", catchUp: "catch-up copy")
        let notices = select([fire])
        #expect(notices == [PendingNotification(
            id: "slower-1-fired", title: "🟠 Slower than usual", body: "fired copy", threadID: "slower.codex.\(Synth.model)")])
    }

    /// A banner's title leads with what happened: the lamp that lit, in its color, or the clear.
    @Test func titlesLeadWithAlertOrCleared() {
        #expect(select([outcome(at: latest, fired(latest))]).map(\.title) == ["🟠 Slower than usual"])
        #expect(select([outcome(at: latest, fired(latest, severity: .red))]).map(\.title) == ["🔴 Slower than usual"])
        #expect(select([outcome(.faster, at: latest, fired(latest, severity: .blue))]).map(\.title) == ["🔵 Faster than usual"])
        #expect(select([outcome(at: latest, .escalated)]).map(\.title) == ["🔴 Slower than usual"])
        #expect(select([outcome(at: latest, .cleared)]).map(\.title) == ["✓ Cleared: Slower than usual"])
        // A catch-up alert is still an alert.
        let caughtUp = outcome(at: minutesBefore(120), fired(minutesBefore(120)), catchUp: "caught up")
        #expect(select([caughtUp]).map(\.title) == ["🟠 Slower than usual"])
        let failed = outcome(.failedTurns, at: latest, fired(latest, severity: .red), scope: "*", failures: [failure(1, at: latest)])
        #expect(select([failed]).map(\.title) == ["🔴 Failed turns"])
        var clearNotices = RuleSettings.defaults
        clearNotices.failedTurns.notifyOnClear = true
        #expect(select([outcome(.failedTurns, at: latest, .cleared, scope: "*")], settings: clearNotices).map(\.title) == ["✓ Cleared: Failed turns"])
    }

    @Test func transitionExactlyOneIntervalOldIsFresh() {
        // Fresh: latestPoint − at ≤ interval. 5 minutes old with a 5-minute interval is fresh.
        let edge = outcome(at: minutesBefore(5), fired(minutesBefore(5)), message: "fired copy", catchUp: "catch-up copy")
        #expect(select([edge]).map(\.body) == ["fired copy"])
        // One point older is caught up.
        let older = outcome(at: minutesBefore(10), fired(minutesBefore(10)), message: "fired copy", catchUp: "catch-up copy")
        #expect(select([older]).map(\.body) == ["catch-up copy"])
        // A longer interval widens freshness.
        #expect(select([older], interval: 10).map(\.body) == ["fired copy"])
    }

    @Test func openEpisodeFromGapUsesCatchUpCopy() {
        let fire = outcome(at: minutesBefore(120), fired(minutesBefore(120)), catchUp: "caught up 25%")
        #expect(select([fire]).map(\.body) == ["caught up 25%"])
        #expect(select([fire]).map(\.id) == ["slower-1-catchUp"])

        // Escalated inside the gap too, still open: one notice, with the latest catch-up wording.
        let escalated = outcome(at: minutesBefore(60), .escalated, catchUp: "caught up 34%")
        #expect(select([fire, escalated]).map(\.body) == ["caught up 34%"])
        // A fresh escalation of an episode caught up in the same selection isn't announced again.
        let freshEscalation = outcome(at: latest, .escalated, message: "now 34%", catchUp: "caught up 34%")
        #expect(select([fire, freshEscalation]).map(\.body) == ["caught up 34%"])
    }

    @Test func episodeClosedInsideGapIsSilent() {
        let outcomes = [
            outcome(at: minutesBefore(120), fired(minutesBefore(120))),
            outcome(at: minutesBefore(60), .escalated),
            outcome(at: minutesBefore(30), .cleared),
        ]
        #expect(select(outcomes).isEmpty)
        let idle = [outcome(at: minutesBefore(120), fired(minutesBefore(120))), outcome(at: minutesBefore(30), .idleEnded)]
        #expect(select(idle).isEmpty)
    }

    @Test func staleClearAndEscalationAreSilent() {
        // The episode fired in an earlier run; this run caught up its escalation and clear.
        #expect(select([outcome(at: minutesBefore(60), .escalated)]).isEmpty)
        #expect(select([outcome(at: minutesBefore(30), .cleared)]).isEmpty)
        // Fresh ones notify.
        #expect(select([outcome(at: latest, .escalated, message: "now 34%")]).map(\.body) == ["now 34%"])
        #expect(select([outcome(at: latest, .cleared, message: "back")]).map(\.body) == ["back"])
        // Idle ends are always silent.
        #expect(select([outcome(at: latest, .idleEnded)]).isEmpty)
    }

    @Test func clearRespectsNotifyOnClear() {
        let cleared = outcome(at: latest, .cleared, message: "back")
        var settings = RuleSettings.defaults
        #expect(select([cleared], settings: settings).map(\.body) == ["back"])
        settings.slower.notifyOnClear = false
        #expect(select([cleared], settings: settings).isEmpty)
        // Large prompts don't notify on clear by default (spec section 7.4).
        #expect(select([outcome(.largePrompts, at: latest, .cleared)]).isEmpty)
        // Notify off silences fires; Notify when it clears stays independent.
        settings.slower.notify = false
        settings.slower.notifyOnClear = true
        #expect(select([outcome(at: latest, fired(latest))], settings: settings).isEmpty)
        #expect(select([cleared], settings: settings).map(\.body) == ["back"])
        // Disconnects don't notify by default.
        #expect(select([outcome(.disconnects, at: latest, fired(latest), scope: "*")]).isEmpty)
    }

    @Test func failedTurnsCoalesce() {
        var settings = RuleSettings.defaults
        settings.failedTurns.coalesceMinutes = 20
        var notices = FailureNotices()
        func t(_ minute: Int) -> Date { Synth.local(2026, 9, 4, 9, minute) }
        func run(at minute: Int, _ outcomes: [RuleOutcome]) -> [String] {
            select(outcomes, latest: t(minute), settings: settings, notices: &notices).map(\.body)
        }
        func failed(at minute: Int, _ failures: [FailedTurnRecord], fires: Bool = false) -> RuleOutcome {
            outcome(.failedTurns, at: t(minute), fires ? fired(t(minute), severity: .red) : nil, episode: 7, scope: "*", failures: failures)
        }

        // 09:05: the first failure notifies at once.
        #expect(run(at: 5, [failed(at: 5, [failure(1, at: t(3))], fires: true)]) == ["1 turn failed: model at capacity"])
        #expect(notices.lastNoticeAt == t(5))
        // 09:10 and 09:20: inside the 20-minute window, failures wait.
        #expect(run(at: 10, [failed(at: 10, [failure(2, at: t(8)), failure(3, at: t(9), code: "cyberPolicy")])]).isEmpty)
        #expect(run(at: 15, []).isEmpty)
        #expect(run(at: 20, [failed(at: 20, [failure(4, at: t(18))])]).isEmpty)
        #expect(notices.waiting.count == 3)
        // 09:25: the window has ended; the 3 waiting failures go out with their reasons.
        #expect(run(at: 25, []) == ["3 turns failed: model at capacity, blocked by policy"])
        #expect(notices == FailureNotices(lastNoticeAt: t(25), waiting: []))
        // 09:30: a new failure waits again until 09:45.
        #expect(run(at: 30, [failed(at: 30, [failure(5, at: t(28))])]).isEmpty)
        #expect(run(at: 40, []).isEmpty)
        #expect(run(at: 45, []) == ["1 turn failed: model at capacity"])
    }

    @Test func failedTurnsInsideGapUseCatchUpCopyWhileOpen() {
        var notices = FailureNotices()
        let outcomes = [
            outcome(.failedTurns, at: minutesBefore(30), fired(minutesBefore(30), severity: .red), episode: 3, scope: "*", failures: [failure(1, at: minutesBefore(33))]),
            outcome(.failedTurns, at: minutesBefore(20), nil, episode: 3, scope: "*", failures: [failure(2, at: minutesBefore(22))]),
        ]
        let bodies = select(outcomes, notices: &notices).map(\.body)
        #expect(bodies == ["2 turns failed since 11:27: model at capacity"])
        #expect(notices.lastNoticeAt == latest)

        // Cleared inside the gap: recorded only.
        var quiet = FailureNotices()
        let closed = outcomes + [outcome(.failedTurns, at: minutesBefore(10), .cleared, episode: 3, scope: "*")]
        #expect(select(closed, notices: &quiet).isEmpty)
        #expect(quiet == FailureNotices())
    }

    @Test func withheldFailedTurnNoticeKeepsEveryFailureWaiting() {
        // A waiting failure, a fresh one, and a catch-up one from an episode still open: select sends all
        // three; when that notice can't be posted, all three wait again and the last notice time stays.
        let before = FailureNotices(lastNoticeAt: minutesBefore(40), waiting: [failure(1, at: minutesBefore(45))])
        let outcomes = [
            outcome(.failedTurns, at: minutesBefore(30), fired(minutesBefore(30), severity: .red), episode: 3, scope: "*",
                    failures: [failure(2, at: minutesBefore(33))]),
            outcome(.failedTurns, at: latest, nil, episode: 3, scope: "*", failures: [failure(3, at: minutesBefore(2))]),
        ]
        var sent = before
        #expect(select(outcomes, notices: &sent).count == 1)
        #expect(sent == FailureNotices(lastNoticeAt: latest, waiting: []))

        let withheld = NotificationPolicy.withheldFailureNotices(
            outcomes, latestPoint: latest, intervalMinutes: 5, settings: .defaults, failureNotices: before)

        #expect(withheld.lastNoticeAt == minutesBefore(40))
        #expect(Set(withheld.waiting.map(\.turnID)) == ["turn_synthetic_1", "turn_synthetic_2", "turn_synthetic_3"])
    }

    @Test func notifyOffRuleStillWritesEvents() throws {
        try withRules { h in
            try h.seedUsual()
            try h.run(30, throughput: 30, hour: 9)
            h.settings.slower.notify = false
            let outcomes = try h.evaluate(through: h.sep4(9, 20))
            #expect(outcomes.map(\.rule) == [.slower])
            var notices = FailureNotices()
            let pending = NotificationPolicy.select(
                outcomes, latestPoint: h.sep4(9, 20), intervalMinutes: 5, settings: h.settings, mode: .live,
                failureNotices: &notices, calendar: h.calendar)
            #expect(pending.isEmpty)
            #expect(try h.events().map { $0[0] } == ["ruleFired"])
        }
    }

    @Test func failureNoticesPersistInRuleState() throws {
        try withRules { h in
            #expect(try h.store.failureNotices(provider: .codex) == FailureNotices())
            let notices = FailureNotices(lastNoticeAt: h.sep4(9, 5), waiting: [failure(1, at: h.sep4(9, 3))])
            try h.store.setFailureNotices(notices, provider: .codex)
            #expect(try h.store.failureNotices(provider: .codex) == notices)
        }
    }

    @Test func failedTurnNoticesCoalescePerProvider() throws {
        try withRules { h in
            let other = ProviderID(rawValue: "synthetic-other")
            var otherFailure = failure(2, at: latest)
            otherFailure.provider = other
            var first = FailureNotices()
            var second = FailureNotices()
            let codex = outcome(.failedTurns, at: latest, fired(latest, severity: .red), failures: [failure(1, at: latest)])
            var otherOutcome = outcome(.failedTurns, at: latest, fired(latest, severity: .red), failures: [otherFailure])
            otherOutcome.provider = other.rawValue
            let firstNotice = try #require(select([codex], notices: &first).first)
            let secondNotice = try #require(select([otherOutcome], notices: &second).first)
            #expect(firstNotice.id != secondNotice.id)
            #expect(firstNotice.threadID == NotificationPolicy.failedTurnsThreadID(provider: .codex))
            #expect(secondNotice.threadID == NotificationPolicy.failedTurnsThreadID(provider: other))
            let soon = latest.addingTimeInterval(300)
            let another = outcome(.failedTurns, at: soon, nil, failures: [failure(3, at: soon)])
            #expect(select([another], latest: soon, notices: &first).isEmpty)
            #expect(first.waiting.count == 1)
            #expect(second.waiting.isEmpty)
            try h.store.setFailureNotices(first, provider: .codex)
            try h.store.setFailureNotices(second, provider: other)
            #expect(try h.store.failureNotices(provider: .codex) == first)
            #expect(try h.store.failureNotices(provider: other) == second)
        }
    }
}
