import Foundation

/// A collector lamp: unlit when there is nothing to judge (or the collector is off by choice).
public enum LampState: String, Sendable, Equatable, Hashable, Codable {
    case unlit, green, red
}

/// Spec section 9.3's Collector lamps plus section 7.4's Collector health verdict.
public struct CollectorHealthReport: Sendable, Equatable {
    public var installed: LampState
    public var loaded: LampState
    public var lastRun: LampState
    public var onSchedule: LampState
    /// Plain messages for what's wrong, most urgent first: not loaded, the last run's failure,
    /// overdue, format problems.
    public var problems: [String]
    /// The collector is on but its plist is missing, unreadable or runs another executable.
    public var needsRepair: Bool
    /// The collector-state line: the off footer, the first-run wait, or empty.
    public var footer: String
    /// Section 7.4's Collector health condition holds: post (or keep) a health notification.
    public var notify: Bool

    public init(
        installed: LampState, loaded: LampState, lastRun: LampState, onSchedule: LampState, problems: [String], needsRepair: Bool,
        footer: String, notify: Bool
    ) {
        self.installed = installed
        self.loaded = loaded
        self.lastRun = lastRun
        self.onSchedule = onSchedule
        self.problems = problems
        self.needsRepair = needsRepair
        self.footer = footer
        self.notify = notify
    }

    /// The Collector signal's lamp: unlit when off (Installed and Loaded are lit whenever it's on),
    /// red when a lamp is red or there is a problem (a format problem lights it without lighting
    /// one of the four), else green.
    public var lamp: LampState {
        let lamps = [installed, loaded, lastRun, onSchedule]
        if lamps.allSatisfy({ $0 == .unlit }) { return .unlit }
        return lamps.contains(.red) || !problems.isEmpty ? .red : .green
    }
}

/// Judges the collector from its run records, the launchd job and the sources' states (spec
/// sections 6.5, 7.4 and 9.3). Pure: the UI gathers the inputs every minute (`CollectorMonitor`).
///
/// - Skipped runs (another run held the lock) count for nothing: not as a run, a success or a
///   failure.
/// - Last run is the newest finished run. When it failed, the message gives its detail and the
///   next start: the first interval boundary after now, counted from the newest run's start.
/// - On schedule: the newest run (including one still running) started within 2 × the interval
///   + 1 minute.
/// - Notify when on and: not loaded; the two newest finished runs failed; no run succeeded for
///   more than 3 × the interval (counted from the newest success's start, else the oldest run's,
///   else `installedAt`, the plist's last write, when no run is on record);
///   or a source reports a format problem. A run still in progress that started on schedule
///   holds back the no-success verdict until it ends.
public enum CollectorHealth {
    /// Section 7.4's rule name, used as the notification title.
    public static let title = "Collector health"

    /// The next scheduled start: the first interval boundary after `now`, counted from `anchor`, the
    /// newest run's start (launchd's StartInterval clock).
    public static func nextRun(after anchor: Date, intervalMinutes: Int, now: Date) -> Date {
        let interval = TimeInterval(Settings.usableInterval(intervalMinutes) * 60)
        let elapsed = max(0, now.timeIntervalSince(anchor))
        return anchor.addingTimeInterval(interval * (floor(elapsed / interval) + 1))
    }

    public static func evaluate(
        enabled: Bool, installedExecutable: URL?, installedAt: Date?, currentExecutable: URL, loaded: Bool, runs: [CollectorRunRecord],
        intervalMinutes: Int, sourceStates: [SourceStateRow], now: Date, calendar: Calendar
    ) -> CollectorHealthReport {
        guard enabled else {
            return CollectorHealthReport(
                installed: .unlit, loaded: .unlit, lastRun: .unlit, onSchedule: .unlit, problems: [], needsRepair: false,
                footer: Copy.collectorOff, notify: false)
        }
        let interval = TimeInterval(Settings.usableInterval(intervalMinutes) * 60)
        let counted = runs.filter { $0.outcome != .skipped }
            .sorted { ($0.startedAt, $0.id) > ($1.startedAt, $1.id) }
        let finished = counted.filter { $0.outcome == .succeeded || $0.outcome == .failed }
        var problems: [String] = []

        let installedMatches = installedExecutable.map { LaunchAgentManager.sameExecutable($0, currentExecutable) } ?? false
        if !loaded { problems.append(Copy.collectorNotLoaded) }

        var lastRun = LampState.unlit
        if let last = finished.first {
            lastRun = last.outcome == .succeeded ? .green : .red
            if last.outcome == .failed, let anchor = counted.first?.startedAt {
                let next = nextRun(after: anchor, intervalMinutes: intervalMinutes, now: now)
                problems.append(Copy.collectorFailing(at: last.finishedAt ?? last.startedAt, reason: last.detail, next: next, calendar: calendar))
            }
        }

        var onSchedule = LampState.unlit
        let scheduleLimit = 2 * interval + 60
        if let newest = counted.first {
            onSchedule = now.timeIntervalSince(newest.startedAt) <= scheduleLimit ? .green : .red
            if onSchedule == .red { problems.append(Copy.collectorOverdue(since: newest.startedAt, calendar: calendar)) }
        }

        let twoFailures = finished.count >= 2 && finished.prefix(2).allSatisfy { $0.outcome == .failed }
        var noSuccess = false
        if let reference = finished.first(where: { $0.outcome == .succeeded })?.startedAt ?? counted.last?.startedAt ?? installedAt {
            let pending = counted.first.map { $0.outcome == .running && now.timeIntervalSince($0.startedAt) <= scheduleLimit } ?? false
            noSuccess = !pending && now.timeIntervalSince(reference) > 3 * interval
            if noSuccess, problems.isEmpty { problems.append(Copy.collectorOverdue(since: reference, calendar: calendar)) }
        }

        let formatProblems = sourceStates.filter {
            if case .formatProblem = $0.state { true } else { false }
        }
        for state in formatProblems {
            problems.append(Copy.formatProblem(since: state.unavailableSince ?? state.updatedAt, calendar: calendar))
        }

        return CollectorHealthReport(
            installed: installedMatches ? .green : .red, loaded: loaded ? .green : .red, lastRun: lastRun, onSchedule: onSchedule,
            problems: problems, needsRepair: !installedMatches, footer: counted.isEmpty && problems.isEmpty ? Copy.waitingForFirstRun : "",
            notify: !loaded || twoFailures || noSuccess || !formatProblems.isEmpty)
    }
}
