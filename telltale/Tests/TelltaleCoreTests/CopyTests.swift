import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

/// One case per Copy table row (plan, Copy table): synthetic arguments and the exact text.
struct CopyCase: Sendable, CustomTestStringConvertible {
    let function: String
    let actual: String
    let expected: String

    init(_ function: String, _ actual: String, _ expected: String) {
        self.function = function
        self.actual = actual
        self.expected = expected
    }

    var testDescription: String { function }
}

private struct SyntheticError: LocalizedError {
    let errorDescription: String?
}

private enum Fixture {
    static let calendar = Synth.newYork
    static let since = Synth.local(2026, 9, 4, 8, 5)
    static let later = Synth.local(2026, 9, 4, 14, 40)
}

@Suite struct CopyTests {
    @Test func readProblemCopyAndProviderState() {
        let expected = "Telltale can't read Example's logs since 08:05. Open the Collector view to see the error."
        #expect(Copy.readProblem(source: "Example", since: Fixture.since, calendar: Fixture.calendar) == expected)
        #expect(Copy.providerState(.readProblem(since: Fixture.since), name: "Example", calendar: Fixture.calendar) == expected)
    }

    @Test func arrivalText() {
        #expect(Copy.arrival(name: "Synthetic", days: 30, readyModels: []) == "Telltale now watches Synthetic. It read 30 days of history; usual speeds are still being learned.")
        #expect(Copy.arrival(name: "Synthetic", days: 30, readyModels: ["Example", "Sample"]) == "Telltale now watches Synthetic. It read 30 days of history; usual speeds are ready for Example, Sample.")
    }
    @Test func versionAndIdleArrivalCopy() {
        #expect(Copy.versionLine == "Telltale \(TelltaleRelease.version)")
        #expect(Copy.arrivalIdle(name: "Synthetic", days: 30) == "Telltale now watches Synthetic. It read 30 days of history; none of its models responded in the last 14 days.")
    }
    @Test func compactionsCopy() {
        #expect(Copy.compactionsFired(count: 3, windowMinutes: 60, blocked: 220) == "3 automatic compactions in the last 60 minutes. Fresh sessions or subagents would keep more context. They held sessions for 3 min 40 s.")
        #expect(Copy.compactionsFired(count: 2, windowMinutes: 30, blocked: nil) == "2 automatic compactions in the last 30 minutes. Fresh sessions or subagents would keep more context.")
        #expect(Copy.compactionsCleared(windowMinutes: 60) == "No automatic compactions in the last 60 minutes.")
    }
    @Test func claudeFailureReasons() {
        #expect(Copy.failedTurnReason(code: "overloaded") == "model overloaded")
        #expect(Copy.failedTurnReason(code: "serverError") == "server error")
        #expect(Copy.failedTurnReason(code: "timeout") == "request timed out")
        #expect(Copy.failedTurnReason(code: "connection") == "connection failed")
    }
    @Test func formatProblemNamesTheSource() {
        #expect(Copy.formatProblem(source: "Synthetic Provider", since: Fixture.since, calendar: Fixture.calendar)
            == "Synthetic Provider changed its log format. Telltale can't read Synthetic Provider responses since 08:05.")
    }
    static let cases: [CopyCase] = {
        let calendar = Fixture.calendar
        let since = Fixture.since
        let later = Fixture.later
        return [
            CopyCase("acknowledge", Copy.acknowledge, "Acknowledge"),
            CopyCase("acknowledgeAll", Copy.acknowledgeAll, "Acknowledge all"),
            CopyCase("markAsNew", Copy.markAsNew, "Mark as new"),
            CopyCase("acknowledged", Copy.acknowledged(at: since, calendar: calendar), "Acknowledged 08:05"),
            CopyCase("failedTurnsOpen one", Copy.failedTurnsOpen(source: "Example", noun: "request", count: 1, reasons: ["model at capacity"], since: since, calendar: calendar), "Example: 1 request failed since 08:05: model at capacity"),
            CopyCase("failedTurnsOpen many unknown", Copy.failedTurnsOpen(source: "Example", noun: "request", count: 2, reasons: [], since: since, calendar: calendar), "Example: 2 requests failed since 08:05"),
            CopyCase("failedTurnsBeyondAcknowledged one", Copy.failedTurnsBeyondAcknowledged(source: "Example", noun: "request", count: 1, reasons: ["model at capacity"], acknowledged: since, calendar: calendar), "Example: 1 more request failed than you acknowledged at 08:05: model at capacity"),
            CopyCase("failedTurnsBeyondAcknowledged many unknown", Copy.failedTurnsBeyondAcknowledged(source: "Example", noun: "request", count: 2, reasons: [], acknowledged: since, calendar: calendar), "Example: 2 more requests failed than you acknowledged at 08:05"),
            CopyCase("failedTurnsTotal one", Copy.failedTurnsTotal(count: 1, since: since, calendar: calendar), "1 failed since 08:05"),
            CopyCase("failedTurnsTotal many", Copy.failedTurnsTotal(count: 2, since: since, calendar: calendar), "2 failed since 08:05"),
            CopyCase("slowerFired", Copy.slowerFired(model: "Example", percent: 26, since: since, calendar: calendar),
                     "Example is 26% slower than usual for prompts this size. Since 08:05."),
            CopyCase("slowerCatchUp", Copy.slowerCatchUp(model: "Example", percent: 22, since: since, calendar: calendar),
                     "Example has been 22% slower since 08:05."),
            CopyCase("slowerEscalated", Copy.slowerEscalated(model: "Example", percent: 34), "Example is now 34% slower than usual."),
            CopyCase("speedCleared", Copy.speedCleared(model: "Example"), "Example is back to usual speed."),
            CopyCase("fasterFired", Copy.fasterFired(model: "Example", percent: 30, since: since, calendar: calendar),
                     "Example is 30% faster than usual. Check that output isn't shallower. Since 08:05."),
            CopyCase("fasterCatchUp", Copy.fasterCatchUp(model: "Example", percent: 30, since: since, calendar: calendar),
                     "Example has been 30% faster than usual since 08:05."),
            CopyCase("largePromptsFired", Copy.largePromptsFired(count: 3, of: 10, tokens: 300_000),
                     "3 of your last 10 prompts were at least 300k tokens. A fresh session would speed things up."),
            CopyCase("largePromptsFired (millions)", Copy.largePromptsFired(count: 4, of: 12, tokens: 1_000_000),
                     "4 of your last 12 prompts were at least 1M tokens. A fresh session would speed things up."),
            CopyCase("largePromptsFired (uneven)", Copy.largePromptsFired(count: 2, of: 5, tokens: 123_456),
                     "2 of your last 5 prompts were at least 123456 tokens. A fresh session would speed things up."),
            CopyCase("largePromptsCleared", Copy.largePromptsCleared, "Prompt sizes are back to usual."),
            CopyCase("failedTurns (one)", Copy.failedTurns(count: 1, reasons: ["model at capacity"]), "1 turn failed: model at capacity"),
            CopyCase("failedTurns (several)", Copy.failedTurns(count: 3, reasons: ["model at capacity", "blocked by policy", "model at capacity"]),
                     "3 turns failed: model at capacity, blocked by policy"),
            CopyCase("failedTurnsCatchUp (one)", Copy.failedTurnsCatchUp(count: 1, reasons: ["blocked by policy"], since: since, calendar: calendar),
                     "1 turn failed since 08:05: blocked by policy"),
            CopyCase("failedTurnsCatchUp (several)", Copy.failedTurnsCatchUp(count: 2, reasons: ["model at capacity"], since: since, calendar: calendar),
                     "2 turns failed since 08:05: model at capacity"),
            CopyCase("failedTurnsCleared", Copy.failedTurnsCleared(quietMinutes: 30), "No failed turns for 30 minutes."),
            CopyCase("disconnectsFired", Copy.disconnectsFired(count: 4, windowMinutes: 60), "4 disconnect or retry events in the last 60 minutes."),
            CopyCase("disconnectsCatchUp", Copy.disconnectsCatchUp(since: since, calendar: calendar), "Frequent disconnects since 08:05."),
            CopyCase("disconnectsCleared", Copy.disconnectsCleared, "Connection is steady again."),
            CopyCase("incidentFired", Copy.incidentFired(source: "Example Status", name: "Elevated errors"), "Example Status: Elevated errors."),
            CopyCase("incidentCatchUp", Copy.incidentCatchUp(source: "Example Status", name: "Elevated errors", since: since, calendar: calendar),
                     "Example Status: Elevated errors. Open since 08:05."),
            CopyCase("incidentEscalated", Copy.incidentEscalated(source: "Example Status", name: "Elevated errors"),
                     "Example Status: Elevated errors is now an outage."),
            CopyCase("incidentCleared", Copy.incidentCleared(source: "Example Status", name: "Elevated errors"),
                     "Example Status resolved: Elevated errors."),
            CopyCase("statusPost", Copy.statusPost(source: "Example Status", title: "Scheduled maintenance"),
                     "Example Status posted: Scheduled maintenance."),
            CopyCase("statusUnavailable", Copy.statusUnavailable(source: "Example", since: later, calendar: calendar),
                     "Example status unavailable since 14:40."),
            CopyCase("usageLimitFired", Copy.usageLimitFired(percent: 92, windowMinutes: 300, resets: later, calendar: calendar),
                     "92% of the 300-minute limit used. Resets at 14:40."),
            CopyCase("usageLimitFired (no reset)", Copy.usageLimitFired(percent: 95, windowMinutes: 10_080, resets: nil, calendar: calendar),
                     "95% of the 10080-minute limit used."),
            CopyCase("usageLimitCleared", Copy.usageLimitCleared, "Usage is back under the limit you set."),
            CopyCase("thinData", Copy.thinData, "Not enough recent responses to judge speed"),
            CopyCase("noBucketHistory", Copy.noBucketHistory(bucket: .from300k), "Not enough history yet for 300k+ prompts"),
            CopyCase("learning", Copy.learning(days: 5, of: 14), "Learning usual: 5 of 14 days"),
            CopyCase("shiftPrompt (slower)", Copy.shiftPrompt(model: "Example", percent: 25, days: 3, direction: .slower),
                     "Example has been about 25% slower than usual for 3 days. Accept as usual?"),
            CopyCase("shiftPrompt (faster)", Copy.shiftPrompt(model: "Example", percent: 18, days: 4, direction: .faster),
                     "Example has been about 18% faster than usual for 4 days. Accept as usual?"),
            CopyCase("acceptance (lower)", Copy.acceptance(model: "Example", percent: -24), "Example's usual speed is now 24% lower than before."),
            CopyCase("acceptance (higher)", Copy.acceptance(model: "Example", percent: 12), "Example's usual speed is now 12% higher than before."),
            CopyCase("drift", Copy.drift(percent: 6, direction: .slower, acceptedOn: LocalDay(year: 2026, month: 10, day: 12)),
                     "Usual is 6% slower than when you accepted it on Oct 12."),
            CopyCase("drift (faster)", Copy.drift(percent: 7, direction: .faster, acceptedOn: LocalDay(year: 2026, month: 1, day: 3)),
                     "Usual is 7% faster than when you accepted it on Jan 3."),
            CopyCase("connectionGap", Copy.connectionGap(from: since, to: later, calendar: calendar),
                     "Connection history incomplete from 08:05 to 14:40."),
            CopyCase("intervalError", Copy.intervalError(min: 1, max: 60), "Choose an interval from 1 to 60 minutes"),
            CopyCase("clearBandError", Copy.clearBandError, "The clear band must be stricter than the trigger"),
            CopyCase("invalidRuleParameter", Copy.invalidRuleParameter(field: "Disconnects window"), "Choose a valid value for Disconnects window."),
            CopyCase("notInAppBundle", Copy.notInAppBundle, "Run Telltale from Telltale.app to turn on the collector"),
            CopyCase("wrongBundle", Copy.wrongBundle, "This copy of Telltale can't run the collector"),
            CopyCase("launchctlError", Copy.launchctlError(command: "bootstrap", status: 5, stderr: "Input/output error"),
                     "Collector command bootstrap failed (5): Input/output error"),
            CopyCase("rebuildConfirmation", Copy.rebuildConfirmation(days: 30, providers: ["Example A", "Example B"]),
                     "Telltale will re-read the last 30 days of logs for Example A, Example B. Your accepted baselines are kept."),
            CopyCase("providerAdded", Copy.providerAdded(name: "Example A", days: 30),
                     "Telltale now watches Example A. It read 30 days of history and sent no notifications for it."),
            CopyCase("historyRebuilt", Copy.historyRebuilt(name: "Example A", days: 30),
                     "Example A history rebuilt from 30 days of logs."),
            CopyCase("componentMissing", Copy.componentMissing, "(not on the status page now)"),
            CopyCase("nothingToReport", Copy.nothingToReport, "Nothing to report."),
            CopyCase("waitingForFirstRun", Copy.waitingForFirstRun, "Waiting for the collector's first run."),
            CopyCase("databaseUnavailable", Copy.databaseUnavailable(reason: "disk I/O error"),
                     "Telltale can't read its database: disk I/O error. Retrying automatically."),
            CopyCase("notificationCheckTitle", Copy.notificationCheckTitle, "Telltale notification check"),
            CopyCase("notificationCheckBody", Copy.notificationCheckBody(mode: "ui-running"), "Notification check: ui-running"),
            CopyCase("testNotificationTitle", Copy.testNotificationTitle, "Telltale notification check"),
            CopyCase("testNotificationBody", Copy.testNotificationBody, "This is a test notification from Telltale. Click to open the panel."),
            CopyCase("notificationsDenied", Copy.notificationsDenied,
                     "Notifications are off. Allow Telltale in System Settings, then retry notifications."),
            CopyCase("notificationRetryPending", Copy.notificationRetryPending, "A notification is waiting to be retried. Retry notifications."),
            CopyCase("notificationAuthorizationFailure", Copy.notificationAuthorizationFailure(error: SyntheticError(errorDescription: "Synthetic refusal")),
                     "Notification authorization failed: Synthetic refusal. Retry notifications."),
            CopyCase("notificationPostFailure", Copy.notificationPostFailure(error: SyntheticError(errorDescription: "Synthetic failure.")),
                     "Couldn't post notification: Synthetic failure. Retry notifications."),
            CopyCase("undoEarlierAcceptanceConfirmation", Copy.undoEarlierAcceptanceConfirmation(model: "Example"),
                     "Restore Example's baseline from before this acceptance? Later acceptances for this model will also be undone."),
            CopyCase("collectorNotBuilt", Copy.collectorNotBuilt, "Collector not built yet"),
            CopyCase("failedTurnReason (capacity)", Copy.failedTurnReason(code: "serverOverloaded"), "model at capacity"),
            CopyCase("failedTurnReason (policy)", Copy.failedTurnReason(code: "cyberPolicy"), "blocked by policy"),
            CopyCase("failedTurnReason (other)", Copy.failedTurnReason(code: "syntheticCode"), "syntheticCode"),
            CopyCase("collectorOff", Copy.collectorOff, "Collector off. Turn it on to keep watching."),
            CopyCase("readProblem", Copy.readProblem(source: "Example", since: since, calendar: calendar),
                     "Telltale can't read Example's logs since 08:05. Open the Collector view to see the error."),
            CopyCase("formatProblem", Copy.formatProblem(since: since, calendar: calendar),
                     "Codex changed its log format. Telltale can't read responses since 08:05."),
            CopyCase("collectorNotLoaded", Copy.collectorNotLoaded,
                     "Telltale's collector isn't loaded. Open the Collector view to turn it back on."),
            CopyCase("collectorFailing", Copy.collectorFailing(at: since, reason: "database is locked", next: later, calendar: calendar),
                     "The collector failed at 08:05: database is locked. Next try 14:40."),
            CopyCase("collectorFailing (reason ends a sentence)",
                     Copy.collectorFailing(at: since, reason: "The disk is full. \n", next: later, calendar: calendar),
                     "The collector failed at 08:05: The disk is full. Next try 14:40."),
            CopyCase("collectorOverdue", Copy.collectorOverdue(since: since, calendar: calendar), "The collector hasn't run since 08:05."),
            CopyCase("collectorRecovered", Copy.collectorRecovered, "Telltale's collector is running again."),
            CopyCase("collectorTurnOffAfterFirstRun", Copy.collectorTurnOffAfterFirstRun, "You can turn the collector off after its first run."),
            CopyCase("settingsAfterFirstRun", Copy.settingsAfterFirstRun, "You can change settings after the collector's first run."),
            CopyCase("settingsInstalledCopyOnly", Copy.settingsInstalledCopyOnly, "Only Telltale in Applications can change this."),
            CopyCase("storedRulesUnusable", Copy.storedRulesUnusable, "The saved rules couldn't be used, so Telltale is using the defaults shown here."),
            CopyCase("componentsNotLoaded", Copy.componentsNotLoaded, "The status page's components appear here after the collector reads it."),
            CopyCase("collectorChangeRunning", Copy.collectorChangeRunning, "Another collector change is still running. Try again in a moment."),
            CopyCase(
                "collectorChangePartial", Copy.collectorChangePartial(reason: "Synthetic reason.", restoreReason: "synthetic restore"),
                "Synthetic reason. The setting couldn't be put back (synthetic restore), so the change is only partly applied."),
            CopyCase("storedRulesUndecodable", Copy.storedRulesUndecodable, "The stored rules couldn't be read."),
        ]
    }()

    @Test(arguments: cases)
    func copyRow(_ row: CopyCase) {
        #expect(row.actual == row.expected)
    }

    @Test func failedTurnsClearedUsesConfiguredQuietMinutes() throws {
        try withRules { h in
            h.settings.failedTurns.quietMinutes = 45
            try h.store.upsert(failedTurns: [h.failure(1, started: h.sep4(9, 1), completed: h.sep4(9, 2))])
            // Counted at 09:05; 45 quiet minutes later is 09:50.
            #expect(try h.evaluate(through: h.sep4(9, 45)).count == 1)
            let cleared = try h.evaluate(through: h.sep4(9, 50))
            #expect(cleared.map(\.transition) == [.cleared])
            #expect(cleared.first?.message == "No failed turns for 45 minutes.")
        }
    }

    @Test func disconnectsFiredUsesConfiguredWindow() throws {
        try withRules { h in
            h.settings.disconnects.count = 2
            h.settings.disconnects.windowMinutes = 20
            try h.store.upsert(connectionEvents: [
                h.connection(1, at: h.sep4(9, 1), kind: .disconnect),
                h.connection(2, at: h.sep4(9, 3), kind: .retry),
            ])
            let outcomes = try h.evaluate(through: h.sep4(9, 30))
            // Fires at 09:05; the 20-minute window (09:05, 09:25] at 09:25 holds none.
            #expect(outcomes.map(\.at) == [h.sep4(9, 5), h.sep4(9, 25)])
            #expect(outcomes.first?.message == "2 disconnect or retry events in the last 20 minutes.")
        }
    }

    @Test func clockTimesUseTheCalendarsTimeZone() {
        var utc = Calendar(identifier: .gregorian)
        utc.timeZone = TimeZone(identifier: "UTC")!
        // 08:05 in New York (EDT, UTC−4) is 12:05 UTC.
        #expect(Copy.disconnectsCatchUp(since: Fixture.since, calendar: utc) == "Frequent disconnects since 12:05.")
    }
}
