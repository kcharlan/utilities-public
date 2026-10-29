import AppKit
import Foundation
import Testing
import SQLite3
import TelltaleCore
import TelltaleTestSupport
@testable import Telltale

/// Spec section 9.4's Settings through its model: rule parameters shown as percentages and minutes,
/// invalid edits shown inline and never saved, the interval through `LaunchAgentManager`, the
/// watched-components checklist, Rebuild behind its confirmation, and the dashboard appearance.
/// Every write goes through `UserActions` into the collector's database (ruling R27); launchctl is
/// always `FakeCommandRunner`.
@MainActor @Suite(.serialized) struct SettingsViewTests {
    @Test func providerTravelsWithTheAlert() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try await ready(directory)
            let settings = world.settings
            let previous = world.clock.now.addingTimeInterval(-60)
            try Store.open(world.paths.database, mode: .readWriteExisting).set(.providerRebuildRequests, [ProviderID.claude.rawValue: previous])
            settings.requestRebuild(provider: .codex)
            settings.cancelProviderRebuild()
            await settings.confirmRebuild(provider: .codex)
            #expect(try stored(world, .providerRebuildRequests)[ProviderID.codex.rawValue] == world.clock.now)
            #expect(try stored(world, .providerRebuildRequests)[ProviderID.claude.rawValue] == previous)
            #expect(try stored(world, .rebuildRequestedAt) == nil)
        }
    }
    @Test func rebuildDisabledWhenRequested() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try await ready(directory)
            let store = try Store.open(world.paths.database, mode: .readWriteExisting)
            try store.set(.providerRebuildRequests, [ProviderID.codex.rawValue: world.clock.now])
            world.settings.load()
            let row = try #require(world.settings.providers.first)
            #expect(!world.settings.canRebuild(row))
            world.settings.requestRebuild(provider: row.provider)
            #expect(world.settings.pendingProviderRebuild == nil)
        }
    }
    @Test func rebuildDisabledWhileBackfilling() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try await ready(directory)
            let encoder = JSONEncoder()
            encoder.dateEncodingStrategy = .secondsSince1970
            let backfill = ProviderBackfill(reason: .new, startedAt: world.clock.now, through: world.clock.now, finishedAt: nil, announce: false)
            let json = String(decoding: try encoder.encode(backfill), as: UTF8.self)
            var db: OpaquePointer?
            #expect(sqlite3_open(world.paths.database.path, &db) == SQLITE_OK)
            defer { sqlite3_close(db) }
            var statement: OpaquePointer?
            #expect(sqlite3_prepare_v2(db, "INSERT INTO rule_state (rule, provider, scope, json) VALUES ('engine', 'codex', 'backfill', ?)", -1, &statement, nil) == SQLITE_OK)
            defer { sqlite3_finalize(statement) }
            #expect(sqlite3_bind_text(statement, 1, json, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self)) == SQLITE_OK)
            #expect(sqlite3_step(statement) == SQLITE_DONE)
            world.settings.load()
            let row = try #require(world.settings.providers.first)
            #expect(!world.settings.canRebuild(row))
            world.settings.requestRebuild(provider: row.provider)
            #expect(world.settings.pendingProviderRebuild == nil)
        }
    }
    @Test func compactionParametersAreEditable() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try await ready(directory)
            #expect(world.settings.text(.compactionCount) == "2")
            #expect(world.settings.text(.compactionWindow) == "60")
            world.settings.edit(.compactionCount, "3")
            world.settings.edit(.compactionWindow, "30")
            #expect(try stored(world, .rules).compactions.count == 3)
            #expect(try stored(world, .rules).compactions.windowMinutes == 30)
            world.settings.edit(.compactionCount, "0")
            #expect(world.settings.parameterErrors[.compactionCount] != nil)
            #expect(try stored(world, .rules).compactions.count == 3)
        }
    }
    @Test func appWriteOnVersion1WaitsForCollector() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try await ready(directory)
            var db: OpaquePointer?
            #expect(sqlite3_open(world.paths.database.path, &db) == SQLITE_OK)
            #expect(sqlite3_exec(db, "DROP TABLE compactions; PRAGMA user_version = 1", nil, nil, nil) == SQLITE_OK)
            sqlite3_close(db)
            world.settings.edit(.compactionCount, "3")
            #expect(world.settings.errors[.rules] == Copy.settingsAfterUpgrade)
            world.settings.requestRebuild()
            await world.settings.confirmRebuild()
            #expect(world.settings.errors[.data] == Copy.settingsAfterUpgrade)
        }
    }
    /// A world whose collector has run once, with the dashboard on Settings.
    private func ready(_ directory: URL, canManage: Bool = true) async throws -> DashboardWorld {
        let world = try DashboardWorld(directory, canManage: canManage)
        try PanelWorld.seed(world.paths)
        await world.live.refresh()
        world.model.select(.settings)
        return world
    }

    private func stored<V>(_ world: DashboardWorld, _ key: SettingKey<V>) throws -> V {
        try Store.open(world.paths.database, mode: .readOnly).value(key)
    }

    @Test func editingThresholdSavesRuleSettings() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try await ready(directory)
            let settings = world.settings
            #expect(settings.databaseReady && settings.firstRunNote == nil)
            // Fractions show as percentages, durations as minutes, token counts in thousands.
            #expect(settings.text(.slowerThreshold) == "15" && settings.text(.slowerDuration) == "15")
            #expect(settings.text(.slowerClearBand) == "8" && settings.text(.slowerClearDuration) == "30")
            #expect(settings.text(.largeTokens) == "300" && settings.text(.usagePercent) == "90")
            #expect(RuleParameter.slowerThreshold.unit == .percent && RuleParameter.slowerDuration.unit == .minutes)

            settings.edit(.slowerThreshold, "20")
            #expect(settings.parameterErrors.isEmpty)
            var expected = RuleSettings.defaults
            expected.slower.threshold = 0.20
            #expect(try stored(world, .rules) == expected)
            #expect(settings.text(.slowerThreshold) == "20")

            settings.edit(.slowerDuration, "20")
            settings.edit(.largeTokens, "250")
            settings.set(.slower, .notify, false)
            settings.set(.usageLimit, .enabled, true)
            expected.slower.durationMinutes = 20
            expected.largePrompts.inputTokens = 250_000
            expected.slower.notify = false
            expected.usageLimit.enabled = true
            #expect(try stored(world, .rules) == expected)
            #expect(!settings.isOn(.slower, .notify) && settings.isOn(.usageLimit, .enabled))
        }
    }

    @Test func clearBandNotStricterShowsErrorAndDoesNotSave() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try await ready(directory)
            let settings = world.settings
            settings.edit(.slowerClearBand, "15")
            #expect(settings.parameterErrors[.slowerClearBand] == [Copy.clearBandError])
            // The invalid entry stays in its field to be fixed; nothing was stored.
            #expect(settings.text(.slowerClearBand) == "15")
            #expect(try stored(world, .rules) == .defaults)

            settings.edit(.fasterDuration, "soon")
            #expect(settings.parameterErrors[.fasterDuration] == [Copy.invalidRuleParameter(field: "Faster than usual duration")])
            #expect(try stored(world, .rules) == .defaults)

            settings.edit(.slowerClearBand, "6")
            #expect(settings.parameterErrors[.slowerClearBand] == nil)
            #expect(settings.parameterErrors[.fasterDuration] != nil)
            #expect(try stored(world, .rules).slower.clearBand == 0.06)
        }
    }

    @Test func resetToDefaultRestoresDefaults() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try await ready(directory)
            let settings = world.settings
            settings.edit(.slowerThreshold, "20")
            settings.set(.slower, .enabled, false)
            settings.edit(.fasterThreshold, "25")
            settings.edit(.slowerClearBand, "40")
            #expect(settings.parameterErrors[.slowerClearBand] != nil)

            settings.resetToDefault(.slower)
            let rules = try stored(world, .rules)
            #expect(rules.slower == RuleSettings.defaults.slower)
            #expect(rules.faster.threshold == 0.25)
            #expect(settings.parameterErrors.isEmpty)
            #expect(settings.text(.slowerClearBand) == "8" && settings.text(.slowerThreshold) == "15")
            #expect(settings.isOn(.slower, .enabled))
        }
    }

    @Test func invalidStoredRulesShowDefaultsWithNote() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try DashboardWorld(directory)
            var invalid = RuleSettings.defaults
            invalid.faster.clearBand = 0.5
            try PanelWorld.seed(world.paths).set(.rules, invalid)
            await world.live.refresh()
            world.model.select(.settings)
            // Ruling R16: the collector uses the defaults, and Settings shows them with a note.
            #expect(world.settings.rulesNote == Copy.storedRulesUnusable)
            #expect(world.settings.text(.fasterClearBand) == "8")
            world.settings.edit(.slowerThreshold, "20")
            #expect(world.settings.rulesNote == nil)
            #expect(try stored(world, .rules).faster == RuleSettings.defaults.faster)
        }
    }

    /// Ruling R16 when the stored rules JSON no longer decodes at all: the defaults, with the note.
    @Test func undecodableStoredRulesShowDefaultsWithNote() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try DashboardWorld(directory)
            try PanelWorld.seed(world.paths)
            try DashboardWorld.exec(
                world.paths.database, "INSERT OR REPLACE INTO settings (key, value_json) VALUES ('\(SettingKey.rules.name)', '{\"slower\": \"synthetic\"')")
            #expect(try Store.open(world.paths.database, mode: .readOnly).usableRules().problems == [Copy.storedRulesUndecodable])
            await world.live.refresh()
            world.model.select(.settings)
            #expect(world.settings.rulesNote == Copy.storedRulesUnusable)
            #expect(world.settings.text(.slowerThreshold) == "15" && world.settings.text(.fasterClearBand) == "8")
            // A change stores a complete, decodable rules value built on the defaults.
            world.settings.edit(.slowerThreshold, "20")
            #expect(world.settings.rulesNote == nil)
            var expected = RuleSettings.defaults
            expected.slower.threshold = 0.20
            #expect(try stored(world, .rules) == expected)
        }
    }

    /// Spec section 9.3's Change interval: the plist is rewritten for this app's executable, then
    /// the job is booted out and bootstrapped, and only then is the interval stored.
    @Test func intervalChangeRewritesLaunchAgent() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try await ready(directory)
            let settings = world.settings
            #expect(settings.intervalText == "5")
            await settings.editInterval("10")
            #expect(settings.intervalError == nil && world.collector.error == nil)
            #expect(world.runner.calls.map { $0.arguments.first ?? "" } == ["bootout", "bootstrap"])
            let plist = try TestPaths.plistDictionary(at: world.collector.manager.plistURL)
            #expect(plist["StartInterval"] as? Int == 600)
            #expect((plist["ProgramArguments"] as? [String]) == [world.executable.path, "--collect"])
            #expect(try stored(world, .intervalMinutes) == 10)
            #expect(world.collector.intervalMinutes == 10 && settings.intervalText == "10")

            // Out of range: the validator's message, and nothing reaches launchctl or the store.
            await settings.editInterval("0")
            #expect(settings.intervalError == Settings.intervalError(0))
            await settings.editInterval("often")
            #expect(settings.intervalError == Settings.intervalError(0))
            #expect(try world.runner.calls.count == 2 && stored(world, .intervalMinutes) == 10)

            // With the collector off there is no job to reload: the interval is only stored.
            try Store.open(world.paths.database, mode: .readWrite).set(.collectorEnabled, false)
            world.model.load()
            await settings.editInterval("15")
            #expect(settings.intervalError == nil)
            #expect(try world.runner.calls.count == 2 && stored(world, .intervalMinutes) == 15)
        }
    }

    @Test func intervalChangeFailureShowsMessage() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try await ready(directory)
            world.runner.respond(to: "bootstrap", with: CommandResult(status: 5, stdout: "", stderr: "Synthetic bootstrap failure\n"))
            await world.settings.editInterval("10")
            #expect(world.collector.error == Copy.launchctlError(command: "bootstrap", status: 5, stderr: "Synthetic bootstrap failure"))
            #expect(try stored(world, .intervalMinutes) == 5)

            // An executable outside an app bundle is refused in Copy's words before launchctl runs.
            let bare = directory.appending(path: "bin/Telltale", directoryHint: .notDirectory)
            try FileManager.default.createDirectory(at: bare.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data("#!/bin/sh\n".utf8).write(to: bare)
            try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: bare.path)
            world.collector.currentExecutable = bare
            let calls = world.runner.calls.count
            await world.settings.editInterval("10")
            #expect(world.collector.error == Copy.notInAppBundle)
            #expect(try world.runner.calls.count == calls && stored(world, .intervalMinutes) == 5)

            // A copy outside Applications changes no launchd state (R24) and says so.
            let other = try await ready(directory.appending(path: "other", directoryHint: .isDirectory), canManage: false)
            #expect(other.settings.installedCopyNote == Copy.settingsInstalledCopyOnly)
            await other.settings.editInterval("10")
            #expect(try other.runner.calls.isEmpty && stored(other, .intervalMinutes) == 5)
        }
    }

    /// The interval draft follows this change's own outcome, not the collector view's last error:
    /// an unchanged value clears it even after an unrelated failure, and a change the collector view
    /// couldn't start because another was running keeps it and says so.
    @Test func intervalDraftFollowsItsOwnChange() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try await ready(directory)
            let settings = world.settings

            // An unrelated failure (Run now's kickstart) leaves the collector view's error set.
            world.runner.respond(to: "kickstart", with: CommandResult(status: 3, stdout: "", stderr: "Synthetic kickstart failure\n"))
            await world.collector.runNow()
            #expect(world.collector.error != nil)
            await settings.editInterval("5")
            #expect(settings.intervalDraft == nil && settings.intervalError == nil)

            // Run now is still running: the interval draft stays, with a note, and nothing changes.
            world.runner.respond(to: "kickstart", with: CommandResult(status: 0, stdout: "", stderr: ""))
            let release = DispatchSemaphore(value: 0)
            world.runner.observe { call in
                if call.arguments.first == "kickstart" { release.wait() }
            }
            let run = Task { await world.collector.runNow() }
            var waits = 0
            while !world.collector.busy, waits < 1_000 {
                await Task.yield()
                waits += 1
            }
            #expect(world.collector.busy)
            await settings.editInterval("10")
            #expect(settings.intervalDraft == "10" && settings.intervalError == Copy.collectorChangeRunning)
            #expect(try !world.runner.calls.contains { $0.arguments.first == "bootstrap" } && stored(world, .intervalMinutes) == 5)
            release.signal()
            await run.value
            #expect(!world.collector.busy && world.collector.error == nil)

            // Once it finishes, committing the kept draft changes the interval.
            await settings.commitInterval()
            #expect(settings.intervalDraft == nil && settings.intervalError == nil)
            #expect(try stored(world, .intervalMinutes) == 10)
        }
    }

    @Test func componentChecklistSavesNames() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try DashboardWorld(directory)
            try PanelWorld.seed(world.paths).replace(
                components: [
                    StatusComponent(id: "comp_synthetic_01", name: "CLI"), StatusComponent(id: "comp_synthetic_02", name: "Codex API"),
                    StatusComponent(id: "comp_synthetic_03", name: "Example Chat"),
                ], source: PanelWorld.statusSourceID)
            await world.live.refresh()
            world.model.select(.settings)
            let settings = world.settings
            #expect(settings.componentGroups.map(\.name) == ["Example Status"])
            let rows = settings.componentGroups.first?.rows ?? []
            // The page's components, then the saved defaults the page no longer lists.
            #expect(rows.map(\.name) == ["CLI", "Codex API", "Example Chat", "VS Code extension", "Codex in ChatGPT Desktop", "Codex Web", "Responses"])
            #expect(rows.map(\.watched) == [true, true, false, true, true, true, true])
            #expect(rows.filter(\.missing).map(\.name) == ["VS Code extension", "Codex in ChatGPT Desktop", "Codex Web", "Responses"])
            #expect(rows.first { $0.name == "Codex Web" }?.label == "Codex Web \(Copy.componentMissing)")
            #expect(rows.first { $0.name == "CLI" }?.label == "CLI")

            settings.setWatched("Example Chat", true)
            settings.setWatched("Responses", false)
            #expect(try stored(world, .watchedComponents) == ["CLI", "VS Code extension", "Codex in ChatGPT Desktop", "Codex API", "Codex Web", "Example Chat"])
            #expect(try stored(world, .watchedDefaultsApplied) == ["openai", PanelWorld.statusSourceID])
            // Unwatched, a name missing from the page drops out of the list.
            #expect(!(settings.componentGroups.first?.rows ?? []).contains { $0.name == "Responses" })
            #expect(settings.componentGroups.first?.rows.first { $0.name == "Example Chat" }?.watched == true)
        }
    }

    @Test func rebuildRequiresConfirmationThenKickstarts() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try await ready(directory)
            let settings = world.settings
            settings.requestRebuild()
            #expect(settings.confirmingRebuild)
            #expect(settings.rebuildConfirmation == Copy.rebuildConfirmation(days: CollectorRun.lookbackDays, providers: settings.sources.map(\.name)))
            #expect(try stored(world, .rebuildRequestedAt) == nil)
            #expect(world.runner.calls.isEmpty)

            settings.cancelRebuild()
            #expect(try !settings.confirmingRebuild && stored(world, .rebuildRequestedAt) == nil)

            // Closing the alert clears its binding before the Rebuild button's task runs.
            settings.requestRebuild()
            settings.cancelRebuild()
            await settings.confirmRebuild()
            #expect(!settings.confirmingRebuild && settings.errors[.data] == nil)
            #expect(try stored(world, .rebuildRequestedAt) == world.clock.now)
            #expect(world.runner.calls.map(\.arguments) == [["kickstart", "gui/4242/\(TelltaleRelease.collectorLabel)"]])

            // Kicking the job changes launchd state, so another copy doesn't offer Rebuild (R24).
            let other = try await ready(directory.appending(path: "other", directoryHint: .isDirectory), canManage: false)
            other.settings.requestRebuild()
            #expect(!other.settings.confirmingRebuild)
            await other.settings.confirmRebuild()
            #expect(try other.runner.calls.isEmpty && stored(other, .rebuildRequestedAt) == nil)
        }
    }

    @Test func appearanceChangeUpdatesTheme() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try await ready(directory)
            var windows: [NSWindow] = []
            let controller = world.controller(activation: ActivationRecorder(), presented: { windows.append($0) })
            controller.openSettings()
            #expect(world.settings.appearance == .dark)
            #expect(windows.last?.appearance?.name == .darkAqua)

            world.settings.setAppearance(.light)
            #expect(try stored(world, .appearance) == .light)
            #expect(windows.last?.appearance?.name == .aqua)
            world.settings.setAppearance(.system)
            #expect(windows.last?.appearance == nil)

            // A harness's explicit appearance gives way to the next choice made in Settings.
            controller.setAppearance(NSAppearance(named: .aqua))
            world.settings.setAppearance(.dark)
            #expect(windows.last?.appearance?.name == .darkAqua)
            controller.openDashboard()
            #expect(windows.last?.appearance?.name == .darkAqua)
            windows.last?.close()
        }
    }

    /// Ruling R33: Match system means nil all the way up. After the acceptance harness pinned the
    /// panel and the dashboard, the next Settings choice of Match system leaves the window with no
    /// appearance of its own, the application unpinned and the window resolving as the application does.
    @Test func matchSystemAfterHarnessOverrideFollowsTheSystem() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try await ready(directory)
            let panel = try PanelFixture(home: directory.appending(path: "panel", directoryHint: .isDirectory))
            defer {
                panel.status.setAppearance(nil)
                NSApp.appearance = nil
            }
            var windows: [NSWindow] = []
            let controller = world.controller(activation: ActivationRecorder(), presented: { windows.append($0) })
            controller.openSettings()

            panel.status.setAppearance(NSAppearance(named: .aqua))
            controller.setAppearance(NSAppearance(named: .aqua))
            #expect(windows.last?.appearance?.name == .aqua)

            world.settings.setAppearance(.system)
            let window = try #require(windows.last)
            #expect(window.appearance == nil)
            #expect(NSApp.appearance == nil)
            #expect(window.effectiveAppearance.name == NSApp.effectiveAppearance.name)

            // Closing and reopening keeps following the system.
            controller.openDashboard()
            #expect(window.appearance == nil && NSApp.appearance == nil)
            #expect(window.effectiveAppearance.name == NSApp.effectiveAppearance.name)
            window.close()
        }
    }

    /// A dashboard opened with the stored Match system choice has no window appearance of its own.
    @Test func storedMatchSystemOpensWithNoWindowAppearance() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try await ready(directory)
            world.settings.setAppearance(.system)
            #expect(try stored(world, .appearance) == .system)

            var windows: [NSWindow] = []
            let controller = world.controller(activation: ActivationRecorder(), presented: { windows.append($0) })
            controller.openDashboard()
            let window = try #require(windows.last)
            #expect(window.appearance == nil)
            #expect(NSApp.appearance == nil)
            #expect(window.effectiveAppearance.name == NSApp.effectiveAppearance.name)
            window.close()
        }
    }

    /// Ruling R27: before the collector's first run there is no database to store a setting in, so
    /// Settings shows the defaults read-only, says why, and creates nothing.
    @Test func settingsWaitForTheFirstRun() async throws {
        try await withAsyncScratchDirectory { directory in
            let world = try DashboardWorld(directory)
            await world.live.refresh()
            world.model.select(.settings)
            let settings = world.settings
            #expect(!settings.databaseReady && settings.firstRunNote == Copy.settingsAfterFirstRun)
            #expect(settings.text(.slowerThreshold) == "15")
            settings.edit(.slowerThreshold, "20")
            settings.set(.slower, .notify, false)
            settings.setWatched("CLI", false)
            settings.setAppearance(.light)
            await settings.editInterval("10")
            settings.requestRebuild()
            #expect(!settings.confirmingRebuild && settings.appearance == .dark)
            #expect(world.runner.calls.isEmpty)
            #expect(!FileManager.default.fileExists(atPath: world.paths.database.path))
        }
    }
}
