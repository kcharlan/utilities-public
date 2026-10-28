import AppKit
import Observation
import SwiftUI
import TelltaleCore

/// Spec section 9.3's collector view: the four lamps from collector health, the run summary from
/// the run records, the actions, and the tail of `collector.log` **(plan call)**.
///
/// Turn on, Turn off and Repair change launchd state, so only the installed copy offers them
/// (ruling R24, AppDelegate's installed-app check); any other copy shows the view read-only, with
/// `Copy.collectorManagedByInstalledCopy`. Run now kicks the job once, as the panel's Check now
/// does. launchctl runs off the main actor; a failure shows in `LaunchAgentError`'s words
/// (`Copy.notInAppBundle`, `wrongBundle`, `launchctlError`).
@MainActor @Observable final class CollectorViewModel {
    struct Lamp: Equatable, Identifiable {
        var label: String
        var symbol: String
        var state: LampState
        var id: String { label }
    }

    struct Fact: Equatable, Identifiable {
        var label: String
        var value: String
        var id: String { label }
    }

    struct LogLine: Equatable, Identifiable {
        var id: Int
        var text: String
        var isError: Bool
    }

    /// How a launchd change ended: done, failed (`error` says why), or not started because another
    /// change was still running.
    enum ChangeOutcome: Equatable { case done, failed, busy }

    /// Lines of `collector.log` the view shows.
    static let logLineCount = 12
    /// How much of the log's end is read for them.
    static let logTailBytes = 16 * 1_024
    /// Runs read for the summary.
    static let runWindow = 20

    @ObservationIgnored let live: LiveStore
    @ObservationIgnored let actions: UserActions
    @ObservationIgnored let manager: LaunchAgentManager
    @ObservationIgnored let paths: TelltalePaths
    @ObservationIgnored let calendar: Calendar
    @ObservationIgnored private let now: @MainActor () -> Date
    /// The executable a turn-on or repair installs: this app's own.
    @ObservationIgnored var currentExecutable: URL
    @ObservationIgnored var reveal: (URL) -> Void
    /// Whether this copy may change launchd state (the installed copy, ruling R24).
    let canManage: Bool

    private(set) var enabled = SettingKey.collectorEnabled.defaultValue
    private(set) var intervalMinutes = SettingKey.intervalMinutes.defaultValue
    private(set) var facts: [Fact] = []
    private(set) var logLines: [LogLine] = []
    private(set) var busy = false
    /// The last action's failure; nil after a clean action.
    private(set) var error: String?
    /// Why the last load could not read the database; nil after a clean load.
    private(set) var loadError: String?
    /// Whether the collector's database exists, which it does from the first run on. Before
    /// then there is nowhere to store an off choice (rulings R27, R30).
    private(set) var databaseReady = false

    init(
        live: LiveStore, actions: UserActions, manager: LaunchAgentManager, currentExecutable: URL, canManage: Bool, paths: TelltalePaths,
        calendar: Calendar = .current, now: @escaping @MainActor () -> Date = Date.init,
        reveal: @escaping (URL) -> Void = { NSWorkspace.shared.activateFileViewerSelecting([$0]) }
    ) {
        self.live = live
        self.actions = actions
        self.manager = manager
        self.currentExecutable = currentExecutable
        self.canManage = canManage
        self.paths = paths
        self.calendar = calendar
        self.now = now
        self.reveal = reveal
    }

    var report: CollectorHealthReport? { live.health }

    /// Spec section 9.3's lamps: unlit when the collector is off by choice or nothing is known.
    var lamps: [Lamp] {
        let report = report
        return [
            Lamp(label: "Installed", symbol: "checkmark.square", state: report?.installed ?? .unlit),
            Lamp(label: "Loaded", symbol: "power", state: report?.loaded ?? .unlit),
            Lamp(label: "Last run", symbol: "clock", state: report?.lastRun ?? .unlit),
            Lamp(label: "On schedule", symbol: "calendar", state: report?.onSchedule ?? .unlit),
        ]
    }

    var problems: [String] { report?.problems ?? [] }
    /// The off or first-run line, or the running line.
    var stateLine: String {
        if let footer = report?.footer, !footer.isEmpty { return footer }
        return enabled ? Copy.collectorRunning(minutes: intervalMinutes) : Copy.collectorOff
    }
    var showsRepair: Bool { canManage && report?.needsRepair == true }
    var offersTurnOn: Bool { !enabled || report?.loaded == .red }
    var offersTurnOff: Bool { enabled && databaseReady }
    /// Shown in place of Turn off before the first run (ruling R30).
    var firstRunNote: String? { canManage && enabled && !databaseReady ? Copy.collectorTurnOffAfterFirstRun : nil }
    var managementNote: String? { canManage ? nil : Copy.collectorManagedByInstalledCopy }
    var logExists: Bool { FileManager.default.fileExists(atPath: paths.log.path) }

    /// Rereads the settings, the run records and the log's tail.
    func load() {
        do {
            let loaded = try live.read { store, _ in
                (try store.value(.collectorEnabled), Settings.usableInterval(try store.value(.intervalMinutes)),
                 try store.recentRuns(limit: Self.runWindow, includingSkipped: false))
            }
            databaseReady = loaded != nil
            if let (enabled, interval, runs) = loaded {
                self.enabled = enabled
                intervalMinutes = interval
                facts = facts(runs: runs, interval: interval)
            } else {
                enabled = SettingKey.collectorEnabled.defaultValue
                intervalMinutes = SettingKey.intervalMinutes.defaultValue
                facts = facts(runs: [], interval: intervalMinutes)
            }
            loadError = nil
        } catch {
            loadError = error.localizedDescription
        }
        logLines = readLog()
    }

    func turnOn() async {
        // Before the collector's first run there is no database to store it in (ruling R27): on
        // matches the default, so nothing is lost, and there is nothing to put back either.
        let storeEnabled = { (value: Bool) in
            do {
                try self.actions.set(.collectorEnabled, value)
            } catch StoreError.notInitialized {
            }
        }
        let was = stored(.collectorEnabled)
        await manage(
            change: { manager, executable, interval in try manager.turnOn(executable: executable, intervalMinutes: interval) },
            save: { try storeEnabled(true) }, restore: { if let was { try storeEnabled(was) } })
    }

    /// Not offered until the first run has created the database the off choice is stored in (R30).
    func turnOff() async {
        guard offersTurnOff else { return }
        await manage(
            change: { manager, _, _ in try manager.turnOff() },
            save: { try self.actions.set(.collectorEnabled, false) }, restore: { try self.actions.set(.collectorEnabled, true) })
    }

    func repair() async {
        guard showsRepair else { return }
        await manage(change: { manager, executable, interval in try manager.repair(executable: executable, intervalMinutes: interval) })
    }

    /// Spec section 9.3's Change interval, from Settings: store the interval, then, while the
    /// collector is on, rewrite the plist and reload the job; while it is off, only store it. Like Turn
    /// off, it waits for the first run, which creates the database the interval is stored in
    /// (rulings R27 and R30). An out-of-range value fails with `Settings.intervalError`'s message.
    @discardableResult func changeInterval(_ minutes: Int) async -> ChangeOutcome {
        guard canManage, databaseReady else { return .failed }
        if let message = Settings.intervalError(minutes) {
            error = message
            return .failed
        }
        var reload: (@Sendable (LaunchAgentManager, URL, Int) throws -> Void)?
        if enabled {
            reload = { manager, executable, _ in try manager.changeInterval(executable: executable, intervalMinutes: minutes) }
        }
        let previous = stored(.intervalMinutes) ?? intervalMinutes
        return await manage(
            change: reload, save: { try self.actions.set(.intervalMinutes, minutes) },
            restore: { try self.actions.set(.intervalMinutes, previous) })
    }

    /// "Run now": one collector run outside its schedule.
    func runNow() async {
        await perform { try await self.actions.checkNow() }
    }

    func showLogFile() { reveal(paths.log) }

    // MARK: Internals

    /// The stored value of `key` now, to put back after a failed change; nil before the database exists.
    private func stored<V>(_ key: SettingKey<V>) -> V? {
        (try? live.read { store, _ in try store.value(key) }) ?? nil
    }

    /// A launchd change that failed after its setting was stored, and whose setting couldn't be
    /// put back.
    private struct PartialChange: LocalizedError {
        var errorDescription: String?
    }

    /// `save` stores the setting a change implies, then the launchd change (when there is one) runs
    /// off the main actor. Saving first means a setting that can't be stored leaves launchd alone:
    /// a Turn off that booted the job out and then couldn't store "off" would be undone by the next
    /// launch, which turns an enabled collector without a plist back on. A failed launchd change
    /// runs `restore` to put the setting back; if that fails too, the error says the change is only
    /// partly applied. While another change runs, nothing happens and the outcome says so.
    @discardableResult private func manage(
        change: (@Sendable (LaunchAgentManager, URL, Int) throws -> Void)?, save: (() throws -> Void)? = nil,
        restore: (() throws -> Void)? = nil
    ) async -> ChangeOutcome {
        guard canManage else { return .failed }
        guard !busy else { return .busy }
        let manager = manager, executable = currentExecutable, interval = intervalMinutes
        let succeeded = await perform {
            try save?()
            guard let change else { return }
            do {
                try await Task.detached { try change(manager, executable, interval) }.value
            } catch {
                do {
                    try restore?()
                } catch let restoreError {
                    throw PartialChange(errorDescription: Copy.collectorChangePartial(
                        reason: error.localizedDescription, restoreReason: restoreError.localizedDescription))
                }
                throw error
            }
        }
        await live.refresh()
        load()
        return succeeded ? .done : .failed
    }

    @discardableResult private func perform(_ body: () async throws -> Void) async -> Bool {
        busy = true
        defer { busy = false }
        do {
            try await body()
            error = nil
            return true
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }

    private func facts(runs: [CollectorRunRecord], interval: Int) -> [Fact] {
        var facts = [Fact(label: "Runs", value: Copy.collectorSchedule(minutes: interval))]
        if let last = runs.first {
            facts.append(Fact(label: "Last run", value: Copy.collectorLastRun(
                at: last.startedAt, outcome: last.outcome, seconds: last.finishedAt.map { $0.timeIntervalSince(last.startedAt) }, calendar: calendar,
                stranded: CollectorHealth.isStranded(last, intervalMinutes: interval, now: now()))))
            if enabled {
                let next = CollectorHealth.nextRun(after: last.startedAt, intervalMinutes: interval, now: now())
                facts.append(Fact(label: "Next run", value: Copy.clock(next, calendar)))
            }
        }
        if let success = runs.first(where: { $0.outcome == .succeeded }) {
            let detail = success.detail.trimmingCharacters(in: .whitespacesAndNewlines)
            facts.append(Fact(label: "Last success", value: Copy.clock(success.finishedAt ?? success.startedAt, calendar) + (detail.isEmpty ? "" : ", \(detail)")))
        }
        facts.append(Fact(label: "Job label", value: manager.label))
        return facts
    }

    /// A failure line: a failed run or step, something that couldn't be done, or an unavailable
    /// source. An ingest summary's "0 failed turns" is a count, not a failure.
    static func isError(_ line: String) -> Bool {
        let lower = line.lowercased()
        return lower.contains("couldn't") || lower.contains("unavailable") || lower.contains("error")
            || lower.range(of: #"\bfail(ed|ure|s)?\b(?! turns)"#, options: .regularExpression) != nil
    }

    /// The last lines of the log, with the ISO time shortened to the clock time in `calendar`'s zone.
    private func readLog() -> [LogLine] {
        guard let handle = try? FileHandle(forReadingFrom: paths.log) else { return [] }
        defer { try? handle.close() }
        guard let size = try? handle.seekToEnd() else { return [] }
        let start = size > UInt64(Self.logTailBytes) ? size - UInt64(Self.logTailBytes) : 0
        guard (try? handle.seek(toOffset: start)) != nil, let data = try? handle.readToEnd() else { return [] }
        var lines = String(decoding: data, as: UTF8.self).split(separator: "\n", omittingEmptySubsequences: true).map(String.init)
        if start > 0, !lines.isEmpty { lines.removeFirst() }
        let parser = Date.ISO8601FormatStyle(timeZone: calendar.timeZone)
        return lines.suffix(Self.logLineCount).enumerated().map { index, line in
            var text = line
            if let space = line.firstIndex(of: " "), let date = try? parser.parse(String(line[..<space])) {
                let parts = calendar.dateComponents([.hour, .minute, .second], from: date)
                text = String(format: "%02ld:%02ld:%02ld", parts.hour ?? 0, parts.minute ?? 0, parts.second ?? 0) + line[space...]
            }
            return LogLine(id: index, text: text, isError: Self.isError(text))
        }
    }
}

/// The collector view, as the visual doc's collector wireframe and the mockup's problem state.
struct CollectorView: View {
    let model: CollectorViewModel
    var openSettings: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 8) {
                ForEach(model.lamps) { lamp in
                    DashboardLamp(label: lamp.label, symbol: lamp.symbol, color: Self.color(lamp.state), width: 108)
                }
            }
            if !model.problems.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(model.problems.enumerated()), id: \.offset) { _, problem in
                        AlertLine(color: Theme.red, text: problem)
                    }
                }
                .frame(maxWidth: 640, alignment: .leading)
            } else {
                Text(model.stateLine).foregroundStyle(Theme.swiftUI(Theme.dim))
            }
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 6) {
                ForEach(model.facts) { fact in
                    GridRow {
                        Text(fact.label).foregroundStyle(Theme.swiftUI(Theme.dim)).frame(width: 124, alignment: .leading)
                        Text(fact.value).textSelection(.enabled)
                    }
                }
            }
            HStack(spacing: 8) {
                Button("Run now") { Task { await model.runNow() } }.disabled(model.busy).buttonStyle(DashboardButtonStyle())
                if model.offersTurnOn {
                    Button("Turn on") { Task { await model.turnOn() } }.disabled(model.busy || !model.canManage)
                }
                if model.offersTurnOff {
                    Button("Turn off") { Task { await model.turnOff() } }.disabled(model.busy || !model.canManage)
                }
                if model.showsRepair {
                    Button("Repair") { Task { await model.repair() } }.disabled(model.busy)
                }
                Button("Change interval") { openSettings() }
                Button("Show log file") { model.showLogFile() }.disabled(!model.logExists)
            }
            .buttonStyle(DashboardButtonStyle(quiet: true))
            if let note = model.managementNote {
                Text(note).font(.system(size: 12)).foregroundStyle(Theme.swiftUI(Theme.dim))
            }
            if let note = model.firstRunNote {
                Text(note).font(.system(size: 12)).foregroundStyle(Theme.swiftUI(Theme.dim))
            }
            if let error = model.loadError {
                AlertLine(color: Theme.red, text: error)
            }
            if let error = model.error {
                AlertLine(color: Theme.red, text: error)
            }
            if !model.logLines.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(model.logLines) { line in
                        Text(line.text)
                            .foregroundStyle(line.isError ? Theme.swiftUI(Theme.red) : Theme.swiftUI(Theme.dim))
                            .lineLimit(1).truncationMode(.tail)
                    }
                }
                .font(.system(size: 12, design: .monospaced))
                .padding(.horizontal, 12).padding(.vertical, 10)
                .frame(maxWidth: 760, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 8).fill(Theme.swiftUI(Theme.sidebar)))
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Recent collector log lines")
            }
        }
        .font(.system(size: 13))
        .foregroundStyle(Theme.swiftUI(Theme.readout))
    }

    static func color(_ state: LampState) -> Color? {
        switch state {
        case .unlit: nil
        case .green: Theme.swiftUI(Theme.green)
        case .red: Theme.swiftUI(Theme.red)
        }
    }
}
