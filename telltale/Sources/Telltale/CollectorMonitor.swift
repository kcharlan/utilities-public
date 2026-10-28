import Foundation
import TelltaleCore
import UserNotifications

/// The UI's collector health check (spec sections 7.4 and 9.3): the collector can't report its
/// own absence, so the app checks every minute and posts the Collector health notification.
///
/// A health episode starts when `CollectorHealthReport.notify` holds on two checks in a row (one
/// check alone can be the moment after wake before launchd's catch-up run starts) and ends at the
/// first check where it doesn't. It posts once per episode and, when "Notify when it clears" is on,
/// `Copy.collectorRecovered` at the end. The open episode is stored as
/// `SettingKey.collectorHealthNotice`, so a relaunched app doesn't announce it again. With the
/// rule off nothing posts and an open episode ends silently; with Notify off the episode is
/// tracked without its notice, as the collector's rules are.
@MainActor final class CollectorMonitor {
    /// Spec section 9.3: every minute.
    static let checkInterval: TimeInterval = 60
    static let threadID = "collectorHealth"
    /// How many recent counted runs a check reads; enough for every verdict (`CollectorHealth`).
    static let runWindow = 20

    private let paths: TelltalePaths
    private let manager: LaunchAgentManager
    private let currentExecutable: URL
    private let service: any NotificationService
    private let calendar: Calendar
    private let now: @MainActor () -> Date
    /// The previous check found the notify condition: one more makes an episode.
    private var unconfirmed = false
    private var loop: Task<Void, Never>?

    /// The latest report, for the UI.
    private(set) var lastReport: CollectorHealthReport?
    /// The latest failure to read the database or post, for the UI; nil after a clean check.
    private(set) var lastError: String?

    init(
        paths: TelltalePaths, manager: LaunchAgentManager, currentExecutable: URL, service: any NotificationService,
        calendar: Calendar = .current, now: @escaping @MainActor () -> Date = Date.init
    ) {
        self.paths = paths
        self.manager = manager
        self.currentExecutable = currentExecutable
        self.service = service
        self.calendar = calendar
        self.now = now
    }

    /// Checks now and then every `checkInterval` until `stop()`.
    func start() {
        guard loop == nil else { return }
        loop = Task { [weak self] in
            while !Task.isCancelled {
                await self?.check()
                try? await Task.sleep(for: .seconds(Self.checkInterval))
            }
        }
    }

    func stop() {
        loop?.cancel()
        loop = nil
    }

    /// One health check: evaluates, posts what the episode calls for, and returns the report (nil
    /// when the database couldn't be read).
    @discardableResult func check() async -> CollectorHealthReport? {
        let inputs: Inputs
        do {
            inputs = try readInputs()
        } catch {
            lastError = error.localizedDescription
            return nil
        }
        let manager = manager
        let (installed, loaded) = await Task.detached { (manager.installedExecutable(), manager.isLoaded()) }.value
        let at = now()
        let report = CollectorHealth.evaluate(
            enabled: inputs.enabled, installedExecutable: installed, currentExecutable: currentExecutable, loaded: loaded,
            runs: inputs.runs, intervalMinutes: inputs.intervalMinutes, sourceStates: inputs.sourceStates, now: at, calendar: calendar)
        lastReport = report
        lastError = nil
        do {
            try await advanceEpisode(report, rule: inputs.rule, notice: inputs.notice, at: at)
        } catch {
            lastError = error.localizedDescription
        }
        return report
    }

    // MARK: Episodes

    private func advanceEpisode(_ report: CollectorHealthReport, rule: BasicRule, notice: HealthNoticeState?, at: Date) async throws {
        guard rule.enabled else {
            unconfirmed = false
            if notice != nil { try save(nil) }
            return
        }
        guard report.notify else {
            unconfirmed = false
            guard let notice else { return }
            if rule.notifyOnClear {
                try await post(id: Self.identifier(notice, "cleared"), body: Copy.collectorRecovered)
            }
            try save(nil)
            return
        }
        guard notice == nil else { return }
        guard unconfirmed else {
            unconfirmed = true
            return
        }
        // `problems` is never empty while `notify` holds; the fallback only keeps this total.
        let opened = HealthNoticeState(problem: report.problems.first ?? Copy.collectorNotLoaded, notifiedAt: at)
        if rule.notify {
            try await post(id: Self.identifier(opened, "fired"), body: opened.problem)
        }
        try save(opened)
        unconfirmed = false
    }

    private static func identifier(_ notice: HealthNoticeState, _ kind: String) -> String {
        "\(threadID)-\(Int(notice.notifiedAt.timeIntervalSince1970))-\(kind)"
    }

    private func post(id: String, body: String) async throws {
        let notification = PendingNotification(id: id, title: CollectorHealth.title, body: body, threadID: Self.threadID)
        try await service.post(NativeNotificationPoster.request(for: notification))
    }

    // MARK: Store

    private struct Inputs {
        var enabled: Bool
        var intervalMinutes: Int
        var rule: BasicRule
        var runs: [CollectorRunRecord]
        var sourceStates: [SourceStateRow]
        var notice: HealthNoticeState?
    }

    /// Reads through a read-only connection; before the collector's first run there is no
    /// database, which reads as the defaults with no runs.
    private func readInputs() throws -> Inputs {
        let store: Store
        do {
            store = try Store.open(paths.database, mode: .readOnly)
        } catch StoreError.notInitialized {
            return Inputs(
                enabled: SettingKey.collectorEnabled.defaultValue, intervalMinutes: SettingKey.intervalMinutes.defaultValue,
                rule: RuleSettings.defaults.collectorHealth, runs: [], sourceStates: [], notice: nil)
        }
        return Inputs(
            enabled: try store.value(.collectorEnabled), intervalMinutes: try store.value(.intervalMinutes),
            rule: try store.value(.rules).collectorHealth, runs: try store.recentRuns(limit: Self.runWindow, includingSkipped: false),
            sourceStates: try store.sourceStates(), notice: try store.value(.collectorHealthNotice))
    }

    /// Writes the notice through a short-lived read-write connection, as the app does for settings.
    private func save(_ notice: HealthNoticeState?) throws {
        try Store.open(paths.database, mode: .readWrite).set(.collectorHealthNotice, notice)
    }
}
