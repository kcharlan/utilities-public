import Foundation
import TelltaleCore
import UserNotifications

/// The UI's collector health check (spec sections 7.4 and 9.3): the collector can't report its
/// own absence, so the app checks every minute and posts the Collector health notification.
///
/// A health episode starts when `CollectorHealthReport.notify` holds on two checks in a row and ends
/// at the first check where it doesn't, unless it is only held after a wake. It posts once per
/// episode and, when "Notify when it clears" is on, `Copy.collectorRecovered` at the end.
///
/// launchd's catch-up run can start more than a minute after wake, so two checks alone don't cover
/// it, and two checks can sit in separate dark wakes hours apart. Each check therefore compares
/// `asleepTotal`, which counts every sleep, the ones before a dark wake too: when it grew, the Mac has
/// just woken, unconfirmed problems start over and `CollectorHealth` gets the wake as `awakeSince`.
///
/// The open episode is stored as `SettingKey.collectorHealthNotice`, so a relaunched app doesn't
/// announce it again. With the rule off nothing posts and an open episode ends silently; with Notify
/// off the episode is tracked without its notice, as the collector's rules are.
@MainActor final class CollectorMonitor {
    /// Spec section 9.3: every minute.
    static let checkInterval: TimeInterval = 60
    static let threadID = "collectorHealth"
    /// How many recent counted runs a check reads; enough for every verdict (`CollectorHealth`).
    static let runWindow = 20
    /// Growth in `asleepTotal` that counts as a sleep; the two clocks are read a moment apart.
    static let minimumSleep: TimeInterval = 1

    /// Seconds asleep since boot: the continuous clock counts sleep and the uptime clock doesn't. The
    /// uptime clock is read first, so the difference can't underflow.
    nonisolated static func asleepSinceBoot() -> TimeInterval {
        let awake = clock_gettime_nsec_np(CLOCK_UPTIME_RAW)
        let continuous = clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW)
        return TimeInterval(continuous - awake) / 1_000_000_000
    }

    private let paths: TelltalePaths
    private let manager: LaunchAgentManager
    private let currentExecutable: URL
    private let service: any NotificationService
    private let calendar: Calendar
    private let now: @MainActor () -> Date
    private let sourceNames: [String: String]
    private let asleepTotal: @MainActor () -> TimeInterval
    /// `asleepTotal` at the last check; nil before the first.
    private var lastAsleepTotal: TimeInterval?
    /// When a check first saw the Mac awake after a sleep; nil until it has slept under this monitor.
    private var awakeSince: Date?
    /// The previous check found the notify condition: one more makes an episode.
    private var unconfirmed = false
    /// A notice change made while the database doesn't exist yet (ruling R27: the app never creates
    /// it): held here, read in place of the stored notice, and written once the collector has
    /// created the database. `.some(nil)` holds a cleared notice.
    private var heldNotice: HealthNoticeState??
    private var loop: Task<Void, Never>?

    /// The latest report, for the UI.
    private(set) var lastReport: CollectorHealthReport?
    /// The latest failure to read the database or post, for the UI; nil after a clean check.
    private(set) var lastError: String?

    init(
        paths: TelltalePaths, manager: LaunchAgentManager, currentExecutable: URL, service: any NotificationService,
        calendar: Calendar = .current, now: @escaping @MainActor () -> Date = Date.init, sourceNames: [String: String] = [:],
        asleepTotal: @escaping @MainActor () -> TimeInterval = { CollectorMonitor.asleepSinceBoot() }
    ) {
        self.paths = paths
        self.manager = manager
        self.currentExecutable = currentExecutable
        self.service = service
        self.calendar = calendar
        self.now = now
        self.sourceNames = sourceNames
        self.asleepTotal = asleepTotal
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
        guard let (report, inputs, at) = await assess() else { return nil }
        do {
            if report.lamp != .red, !report.heldAfterWake {
                do { try Store.open(paths.database, mode: .readWriteExisting).set(.collectorAcknowledgement, nil) }
                catch StoreError.notInitialized { }
            }
            if let held = heldNotice { try save(held) }
            try await advanceEpisode(report, enabled: inputs.enabled, rule: inputs.rule, notice: inputs.notice, at: at)
        } catch {
            lastError = error.localizedDescription
        }
        return report
    }

    /// Spec section 9.3's health, read-only: no notification, no notice written, and no database
    /// created (ruling R24: a copy that isn't the installed app shows health but never acts on it).
    @discardableResult func evaluate() async -> CollectorHealthReport? {
        await assess()?.report
    }

    /// Reads the inputs through a read-only connection, asks launchd off the main actor, and
    /// records the report (or the read failure).
    private func assess() async -> (report: CollectorHealthReport, inputs: Inputs, at: Date)? {
        let inputs: Inputs
        do {
            inputs = try readInputs()
        } catch {
            lastError = error.localizedDescription
            return nil
        }
        let manager = manager
        let (installed, installedAt, loaded) = await Task.detached {
            (manager.installedExecutable(), manager.installedAt(), manager.isLoaded())
        }.value
        let at = now()
        noteSleep(at: at)
        let report = CollectorHealth.evaluate(
            enabled: inputs.enabled, installedExecutable: installed, installedAt: installedAt, currentExecutable: currentExecutable, loaded: loaded,
            runs: inputs.runs, intervalMinutes: inputs.intervalMinutes, sourceStates: inputs.sourceStates, now: at, calendar: calendar,
            sourceNames: sourceNames, awakeSince: awakeSince)
        lastReport = report
        lastError = nil
        return (report, inputs, at)
    }

    private func noteSleep(at: Date) {
        let total = asleepTotal()
        if let lastAsleepTotal, total - lastAsleepTotal >= Self.minimumSleep {
            awakeSince = at
            unconfirmed = false
        }
        lastAsleepTotal = total
    }

    // MARK: Episodes

    /// The notice is saved before its notification posts and restored if the post fails, so a
    /// failed save never leads to the same notification twice, and a refused post is retried.
    private func advanceEpisode(
        _ report: CollectorHealthReport, enabled: Bool, rule: BasicRule, notice: HealthNoticeState?, at: Date
    ) async throws {
        // The collector off by choice, or the rule off, ends an open episode silently: neither is a recovery.
        guard enabled, rule.enabled else {
            unconfirmed = false
            if notice != nil { try save(nil) }
            return
        }
        guard let text = report.notice else {
            unconfirmed = false
            guard let notice, !report.heldAfterWake else { return }
            try save(nil)
            if rule.notifyOnClear {
                try await post(
                    id: Self.identifier(notice, "cleared"), title: Copy.clearedTitle(CollectorHealth.title), body: Copy.collectorRecovered, restoring: notice)
            }
            return
        }
        guard notice == nil else { return }
        guard unconfirmed else {
            unconfirmed = true
            return
        }
        let opened = HealthNoticeState(problem: text, notifiedAt: at)
        try save(opened)
        if rule.notify {
            try await post(
                id: Self.identifier(opened, "fired"), title: Copy.alertTitle(CollectorHealth.title, lamp: .red), body: opened.problem, restoring: nil)
        }
        unconfirmed = false
    }

    private static func identifier(_ notice: HealthNoticeState, _ kind: String) -> String {
        "\(threadID)-\(Int(notice.notifiedAt.timeIntervalSince1970))-\(kind)"
    }

    /// Posts, putting `restoring` back as the stored notice when the post fails.
    private func post(id: String, title: String, body: String, restoring previous: HealthNoticeState?) async throws {
        let notification = PendingNotification(id: id, title: title, body: body, threadID: Self.threadID)
        do {
            try await service.post(NativeNotificationPoster.request(for: notification))
        } catch {
            try? save(previous)
            throw error
        }
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
                rule: RuleSettings.defaults.collectorHealth, runs: [], sourceStates: [], notice: heldNotice ?? nil)
        }
        let stored = try store.value(.collectorHealthNotice)
        return Inputs(
            enabled: try store.value(.collectorEnabled), intervalMinutes: try store.value(.intervalMinutes),
            rule: try store.usableRules().rules.collectorHealth, runs: try store.recentRuns(limit: Self.runWindow, includingSkipped: false),
            sourceStates: try store.sourceStates(), notice: heldNotice ?? stored)
    }

    /// Writes the notice through a short-lived connection to the existing database, as the app does
    /// for settings; before the collector has created it, holds the notice in memory instead.
    private func save(_ notice: HealthNoticeState?) throws {
        do {
            try Store.open(paths.database, mode: .readWriteExisting).set(.collectorHealthNotice, notice)
            heldNotice = nil
        } catch StoreError.notInitialized {
            heldNotice = .some(notice)
        }
    }
}
