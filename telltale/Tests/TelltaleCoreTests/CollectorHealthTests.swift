import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

/// Spec section 9.3's Collector lamps and section 7.4's Collector health row, on synthetic run
/// records. Times are 2026-10-05 in New York; the interval is 5 minutes unless a test says otherwise.
private enum Health {
    static let app = URL(fileURLWithPath: "/nonexistent-synthetic/Applications/Telltale.app/Contents/MacOS/Telltale")
    static let elsewhere = URL(fileURLWithPath: "/nonexistent-synthetic/Old/Telltale.app/Contents/MacOS/Telltale")

    static func at(_ hour: Int, _ minute: Int, _ second: Int = 0) -> Date { Synth.local(2026, 10, 5, hour, minute, second) }

    /// A run that started at `start` and, unless it is `running`, finished four seconds later.
    static func run(_ id: Int64, _ start: Date, _ outcome: RunOutcome, detail: String = "") -> CollectorRunRecord {
        CollectorRunRecord(
            id: id, startedAt: start, finishedAt: outcome == .running ? nil : start.addingTimeInterval(4), outcome: outcome, detail: detail)
    }

    static func evaluate(
        enabled: Bool = true, installed: URL? = app, installedAt: Date? = nil, loaded: Bool = true, runs: [CollectorRunRecord], interval: Int = 5,
        states: [SourceStateRow] = [], now: Date
    ) -> CollectorHealthReport {
        CollectorHealth.evaluate(
            enabled: enabled, installedExecutable: installed, installedAt: installedAt, currentExecutable: app, loaded: loaded, runs: runs,
            intervalMinutes: interval, sourceStates: states, now: now, calendar: Synth.newYork)
    }

    /// Two successful runs at 09:00 and 09:05.
    static let healthyRuns = [run(1, at(9, 0), .succeeded), run(2, at(9, 5), .succeeded)]
}

@Suite struct CollectorHealthTests {
    @Test func problemKeysNameTheCollectorAndEachSource() {
        let state = SourceStateRow(source: "example", state: .formatProblem("synthetic"), unavailableSince: Health.at(9, 0), updatedAt: Health.at(9, 5))
        #expect(Health.evaluate(loaded: false, runs: Health.healthyRuns, now: Health.at(9, 7)).problemKeys == ["collector"])
        #expect(Health.evaluate(runs: Health.healthyRuns, states: [state], now: Health.at(9, 7)).problemKeys == ["source.example"])
        #expect(Health.evaluate(loaded: false, runs: Health.healthyRuns, states: [state], now: Health.at(9, 7)).problemKeys == ["collector", "source.example"])
    }
    @Test func repairOnlyRedCollectorHasAProblemKey() {
        for installed in [nil, Health.elsewhere] {
            let report = Health.evaluate(installed: installed, runs: Health.healthyRuns, now: Health.at(9, 7))
            #expect(report.problems.isEmpty && !report.notify && report.lamp == .red)
            #expect(report.problemKeys == ["collector"])
        }
    }
    @Test func readProblemLightsRedWithItsOwnWording() {
        let at = Health.at(9, 0)
        let state = SourceStateRow(source: "example", state: .readProblem("synthetic"), unavailableSince: at, updatedAt: Health.at(9, 5))
        let report = Health.evaluate(runs: Health.healthyRuns, states: [state], now: Health.at(9, 7))
        #expect(report.lamp == .red)
        #expect(report.problems.contains(Copy.readProblem(source: "example", since: at, calendar: Synth.newYork)))
    }
    @Test func readProblemFromOneRunShowsButDoesNotNotify() {
        let at = Health.at(9, 5)
        let state = SourceStateRow(source: "example", state: .readProblem("synthetic"), unavailableSince: at, updatedAt: at)
        let report = Health.evaluate(runs: Health.healthyRuns, states: [state], now: Health.at(9, 7))
        #expect(report.lamp == .red)
        #expect(!report.notify)
    }
    @Test func noticeNamesTheConfirmedReadProblem() {
        let at = Health.at(9, 0)
        let state = SourceStateRow(source: "example", state: .readProblem("synthetic"), unavailableSince: at, updatedAt: Health.at(9, 5))
        let report = Health.evaluate(runs: Health.healthyRuns, states: [state], now: Health.at(9, 7))
        #expect(report.notice == Copy.readProblem(source: "example", since: at, calendar: Synth.newYork))
    }

    @Test func formatProblemUsesTheSourcesName() {
        let state = SourceStateRow(source: "synthetic-provider", state: .formatProblem("synthetic"), unavailableSince: Health.at(9, 12), updatedAt: Health.at(9, 20))
        let report = CollectorHealth.evaluate(enabled: true, installedExecutable: Health.app, installedAt: nil, currentExecutable: Health.app,
            loaded: true, runs: Health.healthyRuns, intervalMinutes: 5, sourceStates: [state], now: Health.at(9, 21), calendar: Synth.newYork,
            sourceNames: ["synthetic-provider": "Synthetic Provider"])
        #expect(report.problems.contains("Synthetic Provider changed its log format. Telltale can't read Synthetic Provider responses since 09:12."))
    }
    @Test func allGreenWhenHealthy() {
        let report = Health.evaluate(runs: Health.healthyRuns, now: Health.at(9, 7))
        #expect(report == CollectorHealthReport(
            installed: .green, loaded: .green, lastRun: .green, onSchedule: .green, problems: [], needsRepair: false, footer: "", notice: nil))
        #expect(report.lamp == .green)
    }

    @Test func offByChoiceIsUnlit() {
        // Everything that would be red while on: no plist, not loaded, failures, a format problem.
        let report = Health.evaluate(
            enabled: false, installed: nil, loaded: false,
            runs: [Health.run(1, Health.at(8, 0), .failed, detail: "synthetic failure"), Health.run(2, Health.at(8, 5), .failed, detail: "synthetic failure")],
            states: [SourceStateRow(source: "codex", state: .formatProblem("synthetic"), unavailableSince: Health.at(8, 0), updatedAt: Health.at(8, 5))],
            now: Health.at(12, 0))
        #expect(report == CollectorHealthReport(
            installed: .unlit, loaded: .unlit, lastRun: .unlit, onSchedule: .unlit, problems: [], needsRepair: false,
            footer: "Collector off. Turn it on to keep watching.", notice: nil))
        #expect(report.lamp == .unlit)
    }

    @Test func missingPlistWhileEnabledIsRed() {
        for installed in [nil, Health.elsewhere] {
            let report = Health.evaluate(installed: installed, runs: Health.healthyRuns, now: Health.at(9, 7))
            #expect(report.installed == .red)
            #expect([report.loaded, report.lastRun, report.onSchedule] == [.green, .green, .green])
            #expect(report.needsRepair)
            #expect(report.lamp == .red)
            // Not one of section 7.4's notify conditions on its own.
            #expect(!report.notify)
        }
    }

    @Test func notLoadedIsRedAndNotifies() {
        let report = Health.evaluate(loaded: false, runs: Health.healthyRuns, now: Health.at(9, 7))
        #expect(report.loaded == .red)
        #expect([report.installed, report.lastRun, report.onSchedule] == [.green, .green, .green])
        #expect(report.problems == ["Telltale's collector isn't loaded. Open the Collector view to turn it back on."])
        #expect(report.notify)
        #expect(report.lamp == .red)
    }

    @Test func lastRunFailedShowsReasonAndNextTry() {
        let runs = [Health.run(1, Health.at(9, 0), .succeeded), Health.run(2, Health.at(9, 5), .failed, detail: "database is locked")]
        let report = Health.evaluate(runs: runs, now: Health.at(9, 7))
        #expect(report.lastRun == .red)
        #expect(report.onSchedule == .green)
        // It failed at 09:05:04, when it finished; launchd starts the next run an interval after 09:05.
        #expect(report.problems == ["The collector failed at 09:05: database is locked. Next try 09:10."])
        // One failure, and a success within three intervals: shown, not notified.
        #expect(!report.notify)

        // Past the expected start, the next try is the next interval boundary after now.
        #expect(Health.evaluate(runs: runs, now: Health.at(9, 13)).problems == ["The collector failed at 09:05: database is locked. Next try 09:15."])
    }

    @Test func onScheduleBoundary() {
        // The limit is 2 × the interval + 1 minute after the last run started: 09:11:00 for 09:00 at 5 minutes.
        let runs = [Health.run(1, Health.at(9, 0), .succeeded)]
        #expect(Health.evaluate(runs: runs, now: Health.at(9, 11, 0)).onSchedule == .green)
        let late = Health.evaluate(runs: runs, now: Health.at(9, 11, 1))
        #expect(late.onSchedule == .red)
        #expect(late.problems == ["The collector hasn't run since 09:00."])
        #expect(!late.notify)

        // 21:00 for a 10-minute interval.
        #expect(Health.evaluate(runs: runs, interval: 10, now: Health.at(9, 21, 0)).onSchedule == .green)
        #expect(Health.evaluate(runs: runs, interval: 10, now: Health.at(9, 21, 1)).onSchedule == .red)
    }

    @Test func twoFailedRunsInARowNotify() {
        let one = [Health.run(1, Health.at(9, 0), .succeeded), Health.run(2, Health.at(9, 5), .failed, detail: "synthetic failure")]
        #expect(!Health.evaluate(runs: one, now: Health.at(9, 6)).notify)

        // A run a killed process left behind is closed as failed "interrupted" and counts.
        let two = one + [Health.run(3, Health.at(9, 10), .failed, detail: "interrupted")]
        let report = Health.evaluate(runs: two, now: Health.at(9, 11))
        #expect(report.notify)
        #expect(report.lastRun == .red)
        #expect(report.problems == ["The collector failed at 09:10: interrupted. Next try 09:15."])

        // A success in between breaks the streak.
        let broken = [
            Health.run(1, Health.at(9, 0), .failed, detail: "synthetic failure"), Health.run(2, Health.at(9, 5), .succeeded),
            Health.run(3, Health.at(9, 10), .failed, detail: "synthetic failure"),
        ]
        #expect(!Health.evaluate(runs: broken, now: Health.at(9, 11)).notify)
    }

    @Test func noSuccessForThreeIntervalsNotifies() {
        // The last success started at 09:00; three 5-minute intervals end at 09:15:00.
        let runs = [Health.run(1, Health.at(9, 0), .succeeded)]
        #expect(!Health.evaluate(runs: runs, now: Health.at(9, 15, 0)).notify)
        let overdue = Health.evaluate(runs: runs, now: Health.at(9, 15, 1))
        #expect(overdue.notify)
        #expect(overdue.problems == ["The collector hasn't run since 09:00."])

        // Never a success: measured from the oldest run on record.
        let failing = [Health.run(1, Health.at(9, 0), .failed, detail: "synthetic failure")]
        #expect(!Health.evaluate(runs: failing, now: Health.at(9, 15, 0)).notify)
        #expect(Health.evaluate(runs: failing, now: Health.at(9, 15, 1)).notify)

        // A run in progress that started on schedule hasn't failed yet: no verdict until it ends.
        let inProgress = runs + [Health.run(2, Health.at(9, 14), .running)]
        let pending = Health.evaluate(runs: inProgress, now: Health.at(9, 16))
        #expect(!pending.notify)
        #expect(pending.onSchedule == .green)
        #expect(pending.lastRun == .green)

        // One stuck past the schedule limit doesn't hold the verdict back.
        let stuck = Health.evaluate(runs: runs + [Health.run(2, Health.at(9, 5), .running)], now: Health.at(9, 16, 1))
        #expect(stuck.notify)
        #expect(stuck.onSchedule == .red)
        #expect(stuck.problems == ["The collector hasn't run since 09:05."])
    }

    @Test func skippedRunsDoNotCount() {
        // A skipped run between two failures doesn't break the streak, and isn't the last run.
        let streak = [
            Health.run(1, Health.at(9, 0), .succeeded), Health.run(2, Health.at(9, 5), .failed, detail: "first failure"),
            Health.run(3, Health.at(9, 10), .skipped, detail: CollectorRun.skippedDetail),
            Health.run(4, Health.at(9, 12), .failed, detail: "second failure"),
            Health.run(5, Health.at(9, 13), .skipped, detail: CollectorRun.skippedDetail),
        ]
        let report = Health.evaluate(runs: streak, now: Health.at(9, 14))
        #expect(report.notify)
        #expect(report.lastRun == .red)
        #expect(report.problems == ["The collector failed at 09:12: second failure. Next try 09:17."])

        // Skips neither keep the schedule nor count as a success.
        let skipsOnly = [
            Health.run(1, Health.at(9, 0), .succeeded), Health.run(2, Health.at(9, 5), .skipped, detail: CollectorRun.skippedDetail),
            Health.run(3, Health.at(9, 10), .skipped, detail: CollectorRun.skippedDetail),
            Health.run(4, Health.at(9, 15), .skipped, detail: CollectorRun.skippedDetail),
        ]
        let skipping = Health.evaluate(runs: skipsOnly, now: Health.at(9, 15, 30))
        #expect(skipping.lastRun == .green)
        #expect(skipping.onSchedule == .red)
        #expect(skipping.notify)

        // Only skips on record: nothing to judge yet.
        let none = Health.evaluate(runs: [Health.run(1, Health.at(9, 0), .skipped, detail: CollectorRun.skippedDetail)], now: Health.at(9, 1))
        #expect([none.lastRun, none.onSchedule] == [.unlit, .unlit])
        #expect(!none.notify)
        #expect(none.footer == "Waiting for the collector's first run.")
    }

    @Test func noRunsYetWaitsForTheFirstRun() {
        // Turned on (the plist written) at 09:00; three 5-minute intervals end at 09:15:00.
        let turnedOn = Health.at(9, 0)
        for now in [Health.at(9, 0), Health.at(9, 15, 0)] {
            let report = Health.evaluate(installedAt: turnedOn, runs: [], now: now)
            #expect([report.installed, report.loaded, report.lastRun, report.onSchedule] == [.green, .green, .unlit, .unlit])
            #expect(report.footer == "Waiting for the collector's first run.")
            #expect(report.problems.isEmpty)
            #expect(!report.notify)
            #expect(report.lamp == .green)
        }

        // The first run never arrived: measured from turn-on, as if it were the last success.
        let late = Health.evaluate(installedAt: turnedOn, runs: [], now: Health.at(9, 15, 1))
        #expect(late.notify)
        #expect(late.problems == ["The collector hasn't run since 09:00."])
        #expect([late.lastRun, late.onSchedule] == [.unlit, .unlit])
        #expect(late.lamp == .red)
        // Task 11: the footer no longer says it's waiting beside a problem that says it gave up.
        #expect(late.footer == "")
        let unloaded = Health.evaluate(installedAt: turnedOn, loaded: false, runs: [], now: Health.at(9, 1))
        #expect(unloaded.problems == ["Telltale's collector isn't loaded. Open the Collector view to turn it back on."])
        #expect(unloaded.footer == "")

        // No plist, no reference: nothing to measure from.
        #expect(!Health.evaluate(installed: nil, installedAt: nil, runs: [], now: Health.at(12, 0)).notify)
        // Skipped runs don't count, so turn-on is still the reference; a counted run replaces it.
        let skippedOnly = [Health.run(1, Health.at(9, 0), .skipped, detail: CollectorRun.skippedDetail)]
        #expect(Health.evaluate(installedAt: Health.at(8, 0), runs: skippedOnly, now: Health.at(9, 15, 1)).notify)
        let counted = [Health.run(1, Health.at(9, 10), .failed, detail: "synthetic failure")]
        #expect(!Health.evaluate(installedAt: turnedOn, runs: counted, now: Health.at(9, 15, 1)).notify)
    }

    @Test func formatProblemLightsRed() {
        let states = [
            SourceStateRow(source: "codex", state: .formatProblem("synthetic missing column"), unavailableSince: Health.at(9, 12), updatedAt: Health.at(9, 20)),
            SourceStateRow(source: "openai", state: .ready, updatedAt: Health.at(9, 20)),
            SourceStateRow(source: "example", state: .notSetUp("No synthetic data yet"), unavailableSince: Health.at(9, 0), updatedAt: Health.at(9, 20)),
        ]
        let runs = [Health.run(1, Health.at(9, 15), .succeeded), Health.run(2, Health.at(9, 20), .succeeded)]
        let report = Health.evaluate(runs: runs, states: states, now: Health.at(9, 21))
        #expect([report.installed, report.loaded, report.lastRun, report.onSchedule] == [.green, .green, .green, .green])
        #expect(report.problems == ["codex changed its log format. Telltale can't read codex responses since 09:12."])
        #expect(report.notify)
        #expect(report.lamp == .red)

        // A not-set-up source alone is not a format problem.
        #expect(Health.evaluate(runs: runs, states: [states[2]], now: Health.at(9, 21)).lamp == .green)
    }

    @Test func formatProblemFromOneRunShowsButDoesNotNotify() {
        let state = SourceStateRow(source: "codex", state: .formatProblem("synthetic"), unavailableSince: Health.at(9, 20), updatedAt: Health.at(9, 20))
        let runs = [Health.run(1, Health.at(9, 15), .succeeded), Health.run(2, Health.at(9, 20), .succeeded)]
        let report = Health.evaluate(runs: runs, states: [state], now: Health.at(9, 21))
        #expect(report.problems == ["codex changed its log format. Telltale can't read codex responses since 09:20."])
        #expect(report.lamp == .red)
        #expect(!report.notify)
    }

    @Test func noticeNamesTheConfirmedFormatProblem() {
        // Claude's problem began this run; Codex's was reported again. The panel lists both, by source.
        let states = [
            SourceStateRow(source: "claude", state: .formatProblem("synthetic"), unavailableSince: Health.at(9, 20), updatedAt: Health.at(9, 20)),
            SourceStateRow(source: "codex", state: .formatProblem("synthetic"), unavailableSince: Health.at(9, 12), updatedAt: Health.at(9, 20)),
        ]
        let runs = [Health.run(1, Health.at(9, 15), .succeeded), Health.run(2, Health.at(9, 20), .succeeded)]
        let report = Health.evaluate(runs: runs, states: states, now: Health.at(9, 21))
        #expect(report.problems == [
            "claude changed its log format. Telltale can't read claude responses since 09:20.",
            "codex changed its log format. Telltale can't read codex responses since 09:12.",
        ])
        #expect(report.notice == "codex changed its log format. Telltale can't read codex responses since 09:12.")
        #expect(report.notify)

        // Another notify condition names itself, ahead of any format problem.
        let unloaded = Health.evaluate(loaded: false, runs: runs, states: states, now: Health.at(9, 21))
        #expect(unloaded.notice == "Telltale's collector isn't loaded. Open the Collector view to turn it back on.")
        // Unconfirmed problems alone don't notify.
        #expect(Health.evaluate(runs: runs, states: [states[0]], now: Health.at(9, 21)).notice == nil)
    }

    @Test func invalidStoredIntervalFallsBackToTheDefault() {
        // The collector runs every 5 minutes when the stored interval is invalid; health measures the same.
        let runs = [Health.run(1, Health.at(9, 0), .succeeded)]
        #expect(Health.evaluate(runs: runs, interval: 0, now: Health.at(9, 11, 0)).onSchedule == .green)
        #expect(Health.evaluate(runs: runs, interval: 0, now: Health.at(9, 11, 1)).onSchedule == .red)
    }
}
