import AppKit
import SwiftUI
import Testing
import TelltaleCore
import TelltaleTestSupport
@testable import Telltale

/// Spec section 9.3's collector view through its model: four lamps, Repair only when the plist
/// needs it, launchctl failures shown in Copy's words, and nothing that changes launchd state
/// outside the installed copy (ruling R24). launchctl is always `FakeCommandRunner`.
@MainActor @Suite(.serialized) struct CollectorViewTests {
    static let off = CollectorHealthReport(
        installed: .unlit, loaded: .unlit, lastRun: .unlit, onSchedule: .unlit, problems: [], needsRepair: false,
        footer: Copy.collectorOff, notify: false)
    static let moved = CollectorHealthReport(
        installed: .red, loaded: .green, lastRun: .green, onSchedule: .green, problems: [], needsRepair: true, footer: "", notify: false)

    @Test func repairShownOnlyWhenNeeded() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try DashboardWorld(directory, health: DashboardWorld.running)
            try PanelWorld.seed(world.paths)
            await world.live.refresh()
            #expect(!world.collector.showsRepair)

            world.clock.health = Self.moved
            await world.live.refresh()
            #expect(world.collector.showsRepair)
            await world.collector.repair()
            #expect(world.collector.error == nil)
            #expect(world.runner.calls.map { $0.arguments.first ?? "" } == ["bootout", "bootstrap"])
            let plist = try TestPaths.plistDictionary(at: world.collector.manager.plistURL)
            #expect((plist["ProgramArguments"] as? [String])?.first == world.executable.path)

            // A copy that isn't the installed app never offers Repair or changes launchd (R24).
            let other = try DashboardWorld(directory.appending(path: "other", directoryHint: .isDirectory), canManage: false, health: Self.moved)
            try PanelWorld.seed(other.paths)
            await other.live.refresh()
            #expect(!other.collector.showsRepair && !other.collector.canManage)
            #expect(other.collector.managementNote == Copy.collectorManagedByInstalledCopy)
            await other.collector.repair()
            await other.collector.turnOn()
            await other.collector.turnOff()
            #expect(other.runner.calls.isEmpty)
        }
    }

    @Test func turnOnFailureShowsErrorText() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try DashboardWorld(directory, health: Self.off)
            try PanelWorld.seed(world.paths)
            try Store.open(world.paths.database, mode: .readWrite).set(.collectorEnabled, false)
            await world.live.refresh()
            world.runner.respond(to: "bootstrap", with: CommandResult(status: 5, stdout: "", stderr: "Synthetic bootstrap failure\n"))
            await world.collector.turnOn()
            #expect(world.collector.error == Copy.launchctlError(command: "bootstrap", status: 5, stderr: "Synthetic bootstrap failure"))
            // A failed turn-on leaves the setting off.
            #expect(try Store.open(world.paths.database, mode: .readOnly).value(.collectorEnabled) == false)

            // An executable outside an app bundle, or another bundle's, is refused before launchctl runs.
            let loose = DashboardWorld.self
            let bare = directory.appending(path: "bin/Telltale", directoryHint: .notDirectory)
            try FileManager.default.createDirectory(at: bare.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data("#!/bin/sh\n".utf8).write(to: bare)
            try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: bare.path)
            let calls = world.runner.calls.count
            world.collector.currentExecutable = bare
            await world.collector.turnOn()
            #expect(world.collector.error == Copy.notInAppBundle)
            world.collector.currentExecutable = try loose.makeApp(directory.appending(path: "Other.app", directoryHint: .isDirectory), identifier: "com.example.other")
            await world.collector.turnOn()
            #expect(world.collector.error == Copy.wrongBundle)
            #expect(world.runner.calls.count == calls)

            // Success clears the error and stores the setting.
            world.runner.respond(to: "bootstrap", with: CommandResult(status: 0, stdout: "", stderr: ""))
            world.collector.currentExecutable = world.executable
            await world.collector.turnOn()
            #expect(world.collector.error == nil)
            #expect(try Store.open(world.paths.database, mode: .readOnly).value(.collectorEnabled) == true)

            await world.collector.turnOff()
            #expect(world.collector.error == nil)
            #expect(try Store.open(world.paths.database, mode: .readOnly).value(.collectorEnabled) == false)
            #expect(!FileManager.default.fileExists(atPath: world.collector.manager.plistURL.path))
        }
    }

    @Test func offStateShowsUnlitLamps() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try DashboardWorld(directory, health: Self.off)
            try PanelWorld.seed(world.paths)
            try Store.open(world.paths.database, mode: .readWrite).set(.collectorEnabled, false)
            await world.live.refresh()
            world.collector.load()
            #expect(world.collector.lamps.map(\.state) == [.unlit, .unlit, .unlit, .unlit])
            #expect(world.collector.lamps.map(\.label) == ["Installed", "Loaded", "Last run", "On schedule"])
            #expect(world.collector.problems.isEmpty)
            #expect(world.collector.stateLine == Copy.collectorOff)
            #expect(world.collector.offersTurnOn && !world.collector.offersTurnOff && !world.collector.showsRepair)

            // Running: green lamps and the run summary from the run records.
            world.clock.health = DashboardWorld.running
            try Store.open(world.paths.database, mode: .readWrite).set(.collectorEnabled, true)
            await world.live.refresh()
            world.collector.load()
            #expect(world.collector.lamps.map(\.state) == [.green, .green, .green, .green])
            #expect(!world.collector.offersTurnOn && world.collector.offersTurnOff)
            #expect(world.collector.facts.first { $0.label == "Runs" }?.value == Copy.collectorSchedule(minutes: 5))
            #expect(world.collector.facts.first { $0.label == "Last run" }?.value == "09:29, succeeded in 4.0 s")
            #expect(world.collector.facts.first { $0.label == "Job label" }?.value == TelltaleRelease.collectorLabel)
        }
    }

    /// A world whose collector is on, with its plist written through the fake `launchctl`.
    private func onWorld(_ directory: URL) async throws -> DashboardWorld {
        let world = try DashboardWorld(directory, health: DashboardWorld.running)
        try PanelWorld.seed(world.paths)
        await world.live.refresh()
        world.collector.load()
        await world.collector.turnOn()
        #expect(world.collector.error == nil)
        #expect(FileManager.default.fileExists(atPath: world.collector.manager.plistURL.path))
        return world
    }

    private func storedEnabled(_ world: DashboardWorld) throws -> Bool {
        try Store.open(world.paths.database, mode: .readOnly).value(.collectorEnabled)
    }

    /// The setting is stored before launchd changes. When it can't be stored, launchd is left
    /// alone: a turn-off that booted the job out first would leave the setting on with no plist,
    /// and the next launch would turn the collector back on.
    @Test func turnOffThatCantStoreTheSettingLeavesTheCollectorOn() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try await onWorld(directory)
            let calls = world.runner.calls.count
            try DashboardWorld.exec(world.paths.database, """
                CREATE TRIGGER synthetic_refuse_insert BEFORE INSERT ON settings BEGIN SELECT RAISE(ABORT, 'synthetic refusal'); END;
                CREATE TRIGGER synthetic_refuse_update BEFORE UPDATE ON settings BEGIN SELECT RAISE(ABORT, 'synthetic refusal'); END;
                """)

            await world.collector.turnOff()

            #expect(world.collector.error != nil)
            #expect(world.runner.calls.count == calls)
            #expect(FileManager.default.fileExists(atPath: world.collector.manager.plistURL.path))
            #expect(try storedEnabled(world))
        }
    }

    /// A launchd change that fails puts the stored setting back; when that fails too, the error
    /// says the change is only partly applied.
    @Test func failedLaunchdChangeRestoresTheSettingOrSaysItIsPartial() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try await onWorld(directory)
            world.runner.respond(to: "bootout", with: CommandResult(status: 5, stdout: "", stderr: "Synthetic bootout failure\n"))
            let failure = Copy.launchctlError(command: "bootout", status: 5, stderr: "Synthetic bootout failure")

            await world.collector.turnOff()
            #expect(world.collector.error == failure)
            #expect(try storedEnabled(world))

            // The setting can be turned off but not back on: the turn-off is stored, the job stays.
            try DashboardWorld.exec(world.paths.database, """
                CREATE TRIGGER synthetic_refuse_on BEFORE UPDATE ON settings WHEN NEW.key = 'collectorEnabled' AND NEW.value_json = 'true'
                BEGIN SELECT RAISE(ABORT, 'synthetic refusal'); END;
                """)
            await world.collector.turnOff()
            #expect(world.collector.error?.hasPrefix(failure + " The setting couldn't be put back (") == true)
            #expect(world.collector.error?.hasSuffix("), so the change is only partly applied.") == true)
            #expect(try !storedEnabled(world))
            #expect(FileManager.default.fileExists(atPath: world.collector.manager.plistURL.path))
        }
    }

    /// A Turn off or interval change boots out a run in progress, and nothing closes its `running`
    /// record while the collector is off: past the schedule limit it reads as interrupted.
    @Test func runningRecordPastTheScheduleLimitReadsAsInterrupted() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try DashboardWorld(directory, health: Self.off)
            let store = try PanelWorld.seed(world.paths)
            try store.set(.collectorEnabled, false)
            _ = try store.beginRun(at: PanelWorld.now.addingTimeInterval(-30))  // 09:29:30, after the seeded run
            await world.live.refresh()
            world.clock.now = PanelWorld.now.addingTimeInterval(3_600)
            world.collector.load()
            #expect(world.collector.facts.first { $0.label == "Last run" }?.value == "09:29, interrupted")

            // Still inside the limit (2 × 5 min + 1 min), it is running.
            world.clock.now = PanelWorld.now
            world.collector.load()
            #expect(world.collector.facts.first { $0.label == "Last run" }?.value == "09:29, running")
        }
    }

    /// Ruling R30: before the collector's first run there is no database to store an off choice in
    /// (R27 forbids creating it), so the next launch would turn the collector back on. Turn off
    /// waits for the first run, and the view says so; nothing reaches launchctl.
    @Test func turnOffWaitsForTheFirstRun() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try DashboardWorld(directory, health: DashboardWorld.running)
            await world.live.refresh()
            world.collector.load()
            #expect(!world.collector.offersTurnOff && !world.collector.offersTurnOn)
            #expect(world.collector.firstRunNote == Copy.collectorTurnOffAfterFirstRun)
            await world.collector.turnOff()
            #expect(world.runner.calls.isEmpty)
            #expect(!FileManager.default.fileExists(atPath: world.paths.database.path))

            try PanelWorld.seed(world.paths)
            await world.live.refresh()
            world.collector.load()
            #expect(world.collector.offersTurnOff && world.collector.firstRunNote == nil)
        }
    }

    /// A failed read shows as a load problem, never as an action's failure, and the next good
    /// read clears it.
    @Test func loadErrorsStaySeparateFromActionErrors() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try DashboardWorld(directory)
            try PanelWorld.seed(world.paths)
            await world.live.refresh()
            // Hide the run records behind the open read-only connection, then read again.
            try DashboardWorld.exec(world.paths.database, "ALTER TABLE collector_runs RENAME TO collector_runs_hidden")
            world.collector.load()
            #expect(world.collector.loadError != nil)
            #expect(world.collector.error == nil)
            try DashboardWorld.exec(world.paths.database, "ALTER TABLE collector_runs_hidden RENAME TO collector_runs")
            world.collector.load()
            #expect(world.collector.loadError == nil && world.collector.error == nil)
        }
    }

    @Test func logTailAndShowLogFile() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try DashboardWorld(directory)
            try PanelWorld.seed(world.paths)
            let log = CollectorLog(url: world.paths.log, timeZone: Synth.newYork.timeZone)
            try FileManager.default.createDirectory(at: world.paths.logDirectory, withIntermediateDirectories: true)
            for minute in 0..<18 { log.write("synthetic line \(minute)", at: Synth.local(2026, 9, 4, 9, minute)) }
            // An ingest summary counting zero failed turns is not an error line; an unavailable source is.
            log.write("Codex: 4 responses, 0 failed turns, 0 connection events, 0 gaps; ready", at: Synth.local(2026, 9, 4, 9, 18))
            log.write("Demo status unavailable: synthetic timeout", at: Synth.local(2026, 9, 4, 9, 19))
            log.write("run failed: synthetic history locked", at: Synth.local(2026, 9, 4, 9, 20, 1))
            await world.live.refresh()
            world.collector.load()
            #expect(world.collector.logLines.count == CollectorViewModel.logLineCount)
            #expect(world.collector.logLines.last?.text == "09:20:01 run failed: synthetic history locked")
            #expect(world.collector.logLines.last?.isError == true)
            #expect(world.collector.logLines.first?.isError == false)
            #expect(world.collector.logLines.suffix(3).map(\.isError) == [false, true, true])
            world.collector.showLogFile()
            #expect(world.revealed == [world.paths.log])
        }
    }
}
