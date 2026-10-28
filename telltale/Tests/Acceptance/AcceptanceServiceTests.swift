// Port: brew_version/Tests/Acceptance/AcceptanceServiceTests.swift, AcceptanceServiceTests, fbd3e03.
// Adaptation: the Homebrew transport and tap cases are replaced by Telltale's harness services:
// seeded-store construction, the launchctl and Check now doubles, the notification fault, and
// isolation from live paths. Source tests mapped:
//   tapTransportAndInventoryAreSynthetic, baselineAdvanceAndCatalogAreSynthetic
//     -> seededScenesBuildTheirPanels, acceptanceSceneMatchesTheBrief
//   (new) commandDoubleNeverReachesLaunchd, acceptanceBundleIsRefusedByLaunchAgentManager,
//         checkNowDoubleRecordsASyntheticRun, notificationFaultIsRetried, pathsStayInsideTheSyntheticHome
import Foundation
import Testing
import TelltaleCore
@testable import Acceptance

@MainActor @Suite struct AcceptanceServiceTests {
    private func temporaryHome(_ name: String) throws -> URL {
        let home = FileManager.default.temporaryDirectory.appending(path: "telltale-acceptance-\(name)-\(UUID().uuidString)", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
        return home
    }

    @Test func seededScenesBuildTheirPanels() async throws {
        for scene in [SyntheticEnvironment.Scene.quiet, .alerting, .shift] {
            let home = try temporaryHome(scene.rawValue)
            defer { try? FileManager.default.removeItem(at: home) }
            let now = SyntheticEnvironment.snapshotNow
            let paths = try SyntheticEnvironment.seed(scene, home: home, now: now, calendar: SyntheticEnvironment.calendar)
            let health = SyntheticEnvironment.health(scene)
            let live = LiveStore(
                paths: paths, sources: SyntheticEnvironment.sources, calendar: SyntheticEnvironment.calendar, now: { now }, health: { health },
                watchFiles: false)
            await live.refresh()
            let snapshot = live.snapshot
            #expect(snapshot.checkedAt == now.addingTimeInterval(-60))
            #expect(snapshot.models.map(\.name) == ["Example", "Sample"])
            #expect(snapshot.footer == Copy.collectorRunning(minutes: 5))
            switch scene {
            case .quiet:
                #expect(snapshot.alerts.isEmpty && snapshot.shift == nil)
            case .alerting:
                #expect(snapshot.lamps[.speed] == .amber && snapshot.lamps[.load] == .amber)
                #expect(snapshot.models.map(\.color) == [.amber, nil])
                #expect(snapshot.alerts.map(\.text).contains("Example is 26% slower than usual for prompts this size. Since 08:40."))
            case .shift:
                #expect(snapshot.alerts.isEmpty)
                #expect(snapshot.shiftText == "Example has been about 26% slower than usual for 3 days. Accept as usual?")
            case .acceptance, .dashboard, .collectorProblem:
                Issue.record("not a panel snapshot scene")
            }
        }
    }

    @Test func acceptanceSceneMatchesTheBrief() async throws {
        let home = try temporaryHome("brief")
        defer { try? FileManager.default.removeItem(at: home) }
        let harness = try AcceptanceHarness(home: home, notificationService: SyntheticNotificationService(native: nil))
        await harness.live.refresh()
        let snapshot = harness.live.snapshot
        #expect(!snapshot.alerts.isEmpty && snapshot.lamps[.speed] == .amber)
        #expect(snapshot.shift?.model == SyntheticEnvironment.example)
        #expect(snapshot.collector == .unlit && snapshot.footer == Copy.collectorOff)
        #expect(try Store.open(harness.paths.database, mode: .readOnly).value(.collectorEnabled) == false)

        // A relaunch keeps the session's changes instead of seeding again.
        try harness.addRedAlert()
        let relaunched = try AcceptanceHarness(home: home, notificationService: SyntheticNotificationService(native: nil))
        #expect(relaunched.live.snapshot.lamps[.errors] == .red)
        #expect(relaunched.live.snapshot.alerts.first?.text == "3 turns failed: synthetic failure")
    }

    @Test func commandDoubleNeverReachesLaunchd() async throws {
        let home = try temporaryHome("launchctl")
        defer { try? FileManager.default.removeItem(at: home) }
        let harness = try AcceptanceHarness(home: home, notificationService: SyntheticNotificationService(native: nil))
        let report = await harness.monitor.evaluate()
        #expect(report?.footer == Copy.collectorOff)
        // Only the read-only status query, answered by the double; nothing posted for health.
        #expect(!harness.runner.calls.isEmpty && harness.runner.calls.allSatisfy { $0.first == "print" })
        #expect(harness.notificationService.posted.isEmpty)
    }

    @Test func acceptanceBundleIsRefusedByLaunchAgentManager() throws {
        let home = try temporaryHome("bundle")
        defer { try? FileManager.default.removeItem(at: home) }
        let macOS = home.appending(path: "Telltale Synthetic Acceptance.app/Contents/MacOS", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: macOS, withIntermediateDirectories: true)
        let executable = macOS.appending(path: "Acceptance", directoryHint: .notDirectory)
        try Data("#!/bin/sh\n".utf8).write(to: executable)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: executable.path)
        let info: [String: Any] = ["CFBundleIdentifier": "com.example.telltale.acceptance", "CFBundleExecutable": "Acceptance"]
        try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0)
            .write(to: macOS.deletingLastPathComponent().appending(path: "Info.plist", directoryHint: .notDirectory))
        let runner = SyntheticCommandRunner()
        let manager = LaunchAgentManager(paths: SyntheticEnvironment.paths(home: home), uid: getuid(), runner: runner)
        #expect(throws: LaunchAgentError.wrongBundle("com.example.telltale.acceptance")) {
            try manager.turnOn(executable: executable, intervalMinutes: 5)
        }
        #expect(runner.calls.isEmpty)
        #expect(!FileManager.default.fileExists(atPath: SyntheticEnvironment.paths(home: home).launchAgents.path))
    }

    @Test func checkNowDoubleRecordsASyntheticRun() async throws {
        let home = try temporaryHome("check")
        defer { try? FileManager.default.removeItem(at: home) }
        let harness = try AcceptanceHarness(home: home, notificationService: SyntheticNotificationService(native: nil))
        let before = try #require(harness.live.snapshot.checkedAt)
        try await harness.actions.checkNow()
        harness.live.reload()
        #expect(try #require(harness.live.snapshot.checkedAt) > before)
        #expect(harness.runner.calls.allSatisfy { $0.first == "print" })
    }

    @Test func notificationFaultIsRetried() async throws {
        let home = try temporaryHome("notify")
        defer { try? FileManager.default.removeItem(at: home) }
        let service = SyntheticNotificationService(native: nil)
        let harness = try AcceptanceHarness(home: home, notificationService: service)
        service.failNext = true
        await harness.notifier.sendTestNotification()
        #expect(harness.notifier.lastError?.contains("Synthetic posting failure") == true)
        await harness.notifier.retry()
        #expect(harness.notifier.lastError == nil)
        #expect(service.posted.map(\.content.title) == [Copy.testNotificationTitle])
    }

    @Test func pathsStayInsideTheSyntheticHome() throws {
        let home = try temporaryHome("paths")
        defer { try? FileManager.default.removeItem(at: home) }
        let paths = SyntheticEnvironment.paths(home: home)
        for url in [paths.appSupport, paths.database, paths.lock, paths.appLock, paths.logDirectory, paths.launchAgents, paths.codexHome] {
            #expect(url.standardizedFileURL.path.hasPrefix(home.standardizedFileURL.path + "/"))
        }
        #expect(SyntheticEnvironment.requireHome(home.path) == URL(fileURLWithPath: home.path, isDirectory: true))
    }
}
