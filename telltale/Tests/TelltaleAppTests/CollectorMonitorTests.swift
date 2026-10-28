import Foundation
import Testing
import UserNotifications
import TelltaleCore
import TelltaleTestSupport
@testable import Telltale

/// Records posted requests; authorization is not the monitor's business.
@MainActor private final class RecordingNotificationService: NotificationService {
    struct Refused: LocalizedError {
        var errorDescription: String? { "synthetic notification refusal" }
    }

    private(set) var posted: [UNNotificationRequest] = []
    var refuses = false
    func authorizationStatus() async -> UNAuthorizationStatus { .authorized }
    func requestAuthorization() async throws -> Bool { true }
    func post(_ request: UNNotificationRequest) async throws {
        if refuses { throw Refused() }
        posted.append(request)
    }
    func delivered() async -> [UNNotification] { [] }
}

/// One monitor's world under a scratch directory: injected paths, a fake `launchctl`, a store,
/// a controllable clock and a recording notification service. Times are 2026-10-05 in New York.
@MainActor private final class MonitorHarness {
    let directory: URL
    let paths: TelltalePaths
    let runner = FakeCommandRunner()
    let service = RecordingNotificationService()
    let store: Store
    let currentExecutable = URL(fileURLWithPath: "/nonexistent-synthetic/Applications/Telltale.app/Contents/MacOS/Telltale")
    var now = MonitorHarness.at(9, 0)

    init(_ directory: URL) throws {
        self.directory = directory
        paths = TelltalePaths(home: directory.appending(path: "home", directoryHint: .isDirectory))
        store = try Store.open(paths.database, mode: .readWrite)
    }

    static func at(_ hour: Int, _ minute: Int) -> Date { Synth.local(2026, 10, 5, hour, minute) }

    /// A monitor for this harness, or for another home (`paths`) sharing its runner, service and clock.
    func monitor(paths other: TelltalePaths? = nil) -> CollectorMonitor {
        let paths = other ?? paths
        return CollectorMonitor(
            paths: paths, manager: LaunchAgentManager(paths: paths, uid: 4_242, runner: runner), currentExecutable: currentExecutable,
            service: service, calendar: Synth.newYork, now: { [unowned self] in self.now })
    }

    /// `launchctl print` succeeds (loaded) or reports the service missing.
    func setLoaded(_ loaded: Bool) {
        runner.respond(to: "print", with: loaded
            ? CommandResult(status: 0, stdout: "synthetic service\n", stderr: "")
            : CommandResult(status: 113, stdout: "", stderr: "Could not find service\n"))
    }

    func recordRun(at start: Date, _ outcome: RunOutcome, detail: String = "") throws {
        let id = try store.beginRun(at: start)
        try store.finishRun(id, at: start.addingTimeInterval(4), outcome: outcome, detail: detail)
    }

    func setRule(_ change: (inout BasicRule) -> Void) throws {
        var rules = try store.value(.rules)
        change(&rules.collectorHealth)
        try store.set(.rules, rules)
    }

    /// Advances the clock a minute (the health-check cadence) and checks.
    @discardableResult func tick(_ monitor: CollectorMonitor) async -> CollectorHealthReport? {
        now = now.addingTimeInterval(CollectorMonitor.checkInterval)
        return await monitor.check()
    }

    var bodies: [String] { service.posted.map(\.content.body) }
}

@MainActor private func withMonitor(_ body: (MonitorHarness) async throws -> Void) async throws {
    try await withAsyncScratchDirectory { try await body(MonitorHarness($0)) }
}

private let notLoaded = "Telltale's collector isn't loaded. Open the Collector view to turn it back on."
private let recovered = "Telltale's collector is running again."

@MainActor @Suite struct CollectorMonitorTests {
    @Test func checksEveryMinute() {
        #expect(CollectorMonitor.checkInterval == 60)
    }

    @Test func postsOncePerEpisode() async throws {
        try await withMonitor { h in
            try h.recordRun(at: MonitorHarness.at(9, 0), .succeeded)
            let monitor = h.monitor()

            // A problem seen on a single check (for example just after wake, before launchd's
            // catch-up run) is not yet an episode.
            h.setLoaded(false)
            await h.tick(monitor)
            h.setLoaded(true)
            await h.tick(monitor)
            #expect(h.service.posted.isEmpty)

            // Seen on two checks in a row: one notification.
            h.setLoaded(false)
            await h.tick(monitor)
            #expect(h.service.posted.isEmpty)
            await h.tick(monitor)
            #expect(h.bodies == [notLoaded])
            let request = try #require(h.service.posted.first)
            #expect(request.content.title == "Collector health")
            #expect(request.content.threadIdentifier == "collectorHealth")
            #expect(try h.store.value(.collectorHealthNotice) == HealthNoticeState(problem: notLoaded, notifiedAt: h.now))

            // The episode goes on, even as its problems change: no more notifications.
            for _ in 0..<5 { await h.tick(monitor) }
            try h.recordRun(at: h.now, .failed, detail: "synthetic failure")
            await h.tick(monitor)
            #expect(h.bodies == [notLoaded])

            // A new episode after recovery notifies again, with its own identifier.
            h.setLoaded(true)
            try h.recordRun(at: h.now, .succeeded)
            await h.tick(monitor)
            h.setLoaded(false)
            await h.tick(monitor)
            await h.tick(monitor)
            #expect(h.bodies == [notLoaded, recovered, notLoaded])
            #expect(Set(h.service.posted.map(\.identifier)).count == 3)
        }
    }

    @Test func postsRecoveredWhenGone() async throws {
        try await withMonitor { h in
            try h.recordRun(at: MonitorHarness.at(9, 0), .succeeded)
            let monitor = h.monitor()
            h.setLoaded(false)
            await h.tick(monitor)
            await h.tick(monitor)
            #expect(h.bodies == [notLoaded])

            h.setLoaded(true)
            let report = await h.tick(monitor)
            #expect(report?.notify == false)
            #expect(h.bodies == [notLoaded, recovered])
            #expect(h.service.posted.last?.content.title == "Collector health")
            #expect(try h.store.value(.collectorHealthNotice) == nil)

            // Healthy checks after that stay quiet.
            await h.tick(monitor)
            #expect(h.bodies == [notLoaded, recovered])
        }
    }

    @Test func relaunchDoesNotRepost() async throws {
        try await withMonitor { h in
            try h.recordRun(at: MonitorHarness.at(9, 0), .succeeded)
            h.setLoaded(false)
            let first = h.monitor()
            await h.tick(first)
            await h.tick(first)
            #expect(h.bodies == [notLoaded])

            // A relaunched app reads the stored notice instead of announcing the same episode again.
            let relaunched = h.monitor()
            for _ in 0..<3 { await h.tick(relaunched) }
            #expect(h.bodies == [notLoaded])

            // It still announces the recovery.
            h.setLoaded(true)
            await h.tick(relaunched)
            #expect(h.bodies == [notLoaded, recovered])
        }
    }

    @Test func respectsRuleSettings() async throws {
        try await withMonitor { h in
            try h.recordRun(at: MonitorHarness.at(9, 0), .succeeded)
            let monitor = h.monitor()

            // Rule off: no notifications and no episode.
            try h.setRule { $0.enabled = false }
            h.setLoaded(false)
            for _ in 0..<3 { await h.tick(monitor) }
            #expect(h.service.posted.isEmpty)
            #expect(try h.store.value(.collectorHealthNotice) == nil)

            // Notify off: the episode is tracked silently; its clear notice still follows
            // "Notify when it clears", as the collector's rules do.
            try h.setRule { $0 = BasicRule(enabled: true, notify: false, notifyOnClear: true) }
            await h.tick(monitor)
            await h.tick(monitor)
            #expect(h.service.posted.isEmpty)
            #expect(try h.store.value(.collectorHealthNotice) != nil)
            h.setLoaded(true)
            await h.tick(monitor)
            #expect(h.bodies == [recovered])

            // Notify when it clears off: the fire notifies, the recovery doesn't.
            try h.setRule { $0 = BasicRule(enabled: true, notify: true, notifyOnClear: false) }
            h.setLoaded(false)
            await h.tick(monitor)
            await h.tick(monitor)
            #expect(h.bodies == [recovered, notLoaded])
            h.setLoaded(true)
            await h.tick(monitor)
            #expect(h.bodies == [recovered, notLoaded])
            #expect(try h.store.value(.collectorHealthNotice) == nil)

            // Turning the rule off mid-episode ends it silently.
            try h.setRule { $0 = .init(enabled: true, notify: true, notifyOnClear: true) }
            h.setLoaded(false)
            await h.tick(monitor)
            await h.tick(monitor)
            #expect(h.bodies == [recovered, notLoaded, notLoaded])
            try h.setRule { $0.enabled = false }
            await h.tick(monitor)
            #expect(h.bodies == [recovered, notLoaded, notLoaded])
            #expect(try h.store.value(.collectorHealthNotice) == nil)
        }
    }

    @Test func invalidStoredRulesUseTheDefaultHealthRule() async throws {
        try await withMonitor { h in
            try h.recordRun(at: MonitorHarness.at(9, 0), .succeeded)
            // Ruling R16: rules that fail validation are replaced by the defaults as a whole, so the
            // stored health switch (off here) doesn't count; the default rule (on) does.
            var rules = try h.store.value(.rules)
            rules.collectorHealth.enabled = false
            rules.failedTurns.coalesceMinutes = 0
            try h.store.set(.rules, rules)
            #expect(try !h.store.usableRules().problems.isEmpty)
            let monitor = h.monitor()
            h.setLoaded(false)
            await h.tick(monitor)
            await h.tick(monitor)
            #expect(h.bodies == [notLoaded])
        }
    }

    @Test func collectorOffByChoiceNeverNotifies() async throws {
        try await withMonitor { h in
            try h.store.set(.collectorEnabled, false)
            let monitor = h.monitor()
            h.setLoaded(false)
            for _ in 0..<3 { await h.tick(monitor) }
            #expect(h.service.posted.isEmpty)
            let report = await monitor.check()
            #expect(report?.footer == "Collector off. Turn it on to keep watching.")
        }
    }

    @Test func refusedPostIsRetriedAtTheNextCheck() async throws {
        try await withMonitor { h in
            try h.recordRun(at: MonitorHarness.at(9, 0), .succeeded)
            let monitor = h.monitor()
            h.setLoaded(false)
            h.service.refuses = true
            await h.tick(monitor)
            await h.tick(monitor)
            #expect(monitor.lastError == "synthetic notification refusal")
            #expect(try h.store.value(.collectorHealthNotice) == nil)

            h.service.refuses = false
            await h.tick(monitor)
            #expect(h.bodies == [notLoaded])
            #expect(monitor.lastError == nil)
            #expect(try h.store.value(.collectorHealthNotice)?.problem == notLoaded)
        }
    }

    /// Before the collector's first run there is no database: the check reads the defaults.
    @Test func checksBeforeTheDatabaseExists() async throws {
        try await withMonitor { h in
            let fresh = TelltalePaths(home: h.directory.appending(path: "fresh", directoryHint: .isDirectory))
            let monitor = h.monitor(paths: fresh)
            h.setLoaded(false)
            let report = try #require(await h.tick(monitor))
            // Task 11 footer fix: not loaded is a problem, so the footer no longer also says it is
            // waiting for a first run (the panel shows the problem instead).
            #expect(report.footer == "")
            #expect(report.problems == [notLoaded])
            #expect(report.installed == .red)
            #expect(!FileManager.default.fileExists(atPath: fresh.database.path))

            // Collector on by default and not loaded: the episode is announced once. Ruling R27:
            // the app never creates the database, so the notice is held in memory until it exists.
            await h.tick(monitor)
            await h.tick(monitor)
            #expect(h.bodies == [notLoaded])
            #expect(!FileManager.default.fileExists(atPath: fresh.appSupport.path))

            // Once the collector creates the database, the held notice is stored there, and the
            // open episode is still not announced again.
            try Store.open(fresh.database, mode: .readWrite).set(.collectorEnabled, true)
            await h.tick(monitor)
            #expect(h.bodies == [notLoaded])
            #expect(try Store.open(fresh.database, mode: .readOnly).value(.collectorHealthNotice)?.problem == notLoaded)
        }
    }

    @Test func turningTheCollectorOffEndsTheEpisodeSilently() async throws {
        try await withMonitor { h in
            try h.recordRun(at: MonitorHarness.at(9, 0), .succeeded)
            let monitor = h.monitor()
            h.setLoaded(false)
            await h.tick(monitor)
            await h.tick(monitor)
            #expect(h.bodies == [notLoaded])

            // Off by choice is not a recovery: no "running again", and the episode is gone.
            try h.store.set(.collectorEnabled, false)
            await h.tick(monitor)
            #expect(h.bodies == [notLoaded])
            #expect(try h.store.value(.collectorHealthNotice) == nil)

            // Turning it back on with the job still unloaded is a new episode.
            try h.store.set(.collectorEnabled, true)
            await h.tick(monitor)
            await h.tick(monitor)
            #expect(h.bodies == [notLoaded, notLoaded])
        }
    }

    @Test func refusedRecoveryIsRetriedAtTheNextCheck() async throws {
        try await withMonitor { h in
            try h.recordRun(at: MonitorHarness.at(9, 0), .succeeded)
            let monitor = h.monitor()
            h.setLoaded(false)
            await h.tick(monitor)
            await h.tick(monitor)
            let notice = try h.store.value(.collectorHealthNotice)
            #expect(notice != nil)

            h.setLoaded(true)
            h.service.refuses = true
            await h.tick(monitor)
            #expect(monitor.lastError == "synthetic notification refusal")
            // The episode is kept, so the recovery is announced later rather than lost.
            #expect(try h.store.value(.collectorHealthNotice) == notice)

            h.service.refuses = false
            await h.tick(monitor)
            #expect(h.bodies == [notLoaded, recovered])
            #expect(try h.store.value(.collectorHealthNotice) == nil)
        }
    }

    /// No run ever recorded (for example, the first run crashes before opening the database):
    /// the job's turn-on time, the plist's modification date, stands in for the last success.
    @Test func firstRunThatNeverArrivesNotifiesFromTurnOn() async throws {
        try await withMonitor { h in
            let plist = h.paths.launchAgents.appending(path: "local.utilities.telltale.collector.plist")
            try FileManager.default.createDirectory(at: h.paths.launchAgents, withIntermediateDirectories: true)
            let contents: [String: Any] = ["ProgramArguments": [h.currentExecutable.path, "--collect"]]
            try PropertyListSerialization.data(fromPropertyList: contents, format: .xml, options: 0).write(to: plist)
            try FileManager.default.setAttributes([.modificationDate: MonitorHarness.at(9, 0)], ofItemAtPath: plist.path)
            h.setLoaded(true)
            let monitor = h.monitor()

            // Three 5-minute intervals after 09:00 is 09:15:00: still waiting.
            h.now = MonitorHarness.at(9, 14)
            let waiting = try #require(await h.tick(monitor))
            #expect(!waiting.notify)
            #expect(waiting.footer == "Waiting for the collector's first run.")

            await h.tick(monitor)
            await h.tick(monitor)
            #expect(h.bodies == ["The collector hasn't run since 09:00."])
        }
    }

    /// Ruling R24: the read-only evaluation a non-installed copy uses reports health but never posts,
    /// never writes the notice, and never creates the database.
    @Test func evaluateReportsWithoutPostingOrWriting() async throws {
        try await withAsyncScratchDirectory { directory in
            let h = try MonitorHarness(directory)
            h.setLoaded(false)
            let monitor = h.monitor()
            for _ in 0..<3 {
                h.now = h.now.addingTimeInterval(CollectorMonitor.checkInterval)
                let report = try #require(await monitor.evaluate())
                #expect(report.notify && report.problems.first == notLoaded)
            }
            #expect(monitor.lastReport?.notify == true)
            #expect(h.service.posted.isEmpty)
            #expect(try h.store.value(.collectorHealthNotice) == nil)

            // Without a database it reads the defaults and leaves the database uncreated.
            let elsewhere = TelltalePaths(home: directory.appending(path: "other-home", directoryHint: .isDirectory))
            let report = try #require(await h.monitor(paths: elsewhere).evaluate())
            #expect(report.footer == "")
            #expect(report.problems.first == notLoaded)
            #expect(!FileManager.default.fileExists(atPath: elsewhere.database.path))
            #expect(h.service.posted.isEmpty)
        }
    }
}
