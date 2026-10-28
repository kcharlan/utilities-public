import Foundation

/// Posts a notification as Telltale. The executable adapts the system notification center; tests
/// record or refuse.
public protocol NotificationPosting: Sendable {
    func post(_ notification: PendingNotification) async throws
}

/// Test-only fault injection.
public struct RunHooks: Sendable {
    /// Called after each evaluation chunk commits, with the chunk's index from 0. A throw stops
    /// evaluation as a crash would, leaving the committed chunks in place.
    public var afterChunkCommit: (@Sendable (Int) throws -> Void)?

    public init(afterChunkCommit: (@Sendable (Int) throws -> Void)? = nil) {
        self.afterChunkCommit = afterChunkCommit
    }

    public static let none = RunHooks()
}

/// How a collector run ended. `detail` is what the run record stores.
public struct RunReport: Sendable, Equatable {
    public var outcome: RunOutcome
    public var exitCode: Int32
    public var detail: String
    public var notificationsPosted: Int

    public init(outcome: RunOutcome, exitCode: Int32, detail: String, notificationsPosted: Int) {
        self.outcome = outcome
        self.exitCode = exitCode
        self.detail = detail
        self.notificationsPosted = notificationsPosted
    }
}

/// One `Telltale --collect` run (spec sections 4, 7.3 and 9.3), in this order:
///
/// 1. Create the directories and take `RunLock`. A held lock records a `skipped` run and exits 0;
///    any other lock failure records a `failed` run when the database opens.
/// 2. Close `running` records a killed run left (`interrupted`) and record this run's start, then
///    read settings. Rules that don't validate or don't decode are replaced by the defaults, with a
///    note in the log and run detail. A pending Rebuild discards derived data (the storage mapping
///    in `Store.discardForRebuild`), sets `backfillThrough` to now and clears the request. A cold
///    start (no evaluated point, no `backfillThrough`) also sets `backfillThrough`.
/// 3. Ingest each usage source from §8's 30-day lookback: its records, usage limit, connection
///    gaps (as `connectionHistoryIncomplete` events), cursor and setup state, in one transaction
///    per source. One source's problem never stops another source's ingest, but an ingest that
///    throws skips steps 5 and 6 for the whole run (the run fails; the next one catches up).
/// 4. Fetch and store each status source.
/// 5. Evaluate every point after the last evaluated one (or from the lookback) through now, one
///    day per transaction. A point at or before `backfillThrough` is backfill; later points are
///    live. A crash mid-backfill therefore resumes still in backfill.
/// 6. Select notifications from the live outcomes and post them. A failed post is logged and
///    counted in the run's detail; the run still succeeds.
/// 7. Prune per the retention table, then record the run as `succeeded`, or `failed` with the
///    first error's description (exit 1).
public struct CollectorRun: Sendable {
    /// Spec section 8's cold-start lookback, which Rebuild also re-reads.
    public static let lookbackDays = 30
    /// One day of 5-minute evaluation points per transaction.
    public static let pointsPerChunk = 24 * 60 / EvaluationPoints.cadenceMinutes
    /// Spec section 4's wording for a run that found the lock held.
    public static let skippedDetail = "skipped: previous run still active"
    /// The detail of a run record left `running` by a process that died; the next run closes it.
    public static let interruptedDetail = "interrupted"
    /// R16's note when the stored rules can't be used; the reasons follow it.
    static let invalidRulesNote = "Rule settings are invalid, so this run used the defaults:"
    /// The reason given when the stored rules no longer decode.
    static let undecodableRules = "The stored rules couldn't be read."

    /// Process exit codes for `Telltale --collect` (and the command line's usage error).
    public enum ExitCode {
        /// The run succeeded, or was skipped because another run holds the lock.
        public static let success: Int32 = 0
        /// The run failed; the run record (when one could be written) and the log say why.
        public static let failure: Int32 = 1
        /// The command line wasn't understood.
        public static let usage: Int32 = 2
    }

    private let paths: TelltalePaths
    private let sources: [any UsageSource]
    private let statusSources: [any StatusSource]
    private let notifier: any NotificationPosting
    private let calendar: Calendar
    private let now: Date
    private let hooks: RunHooks

    public init(
        paths: TelltalePaths, sources: [any UsageSource], statusSources: [any StatusSource], notifier: any NotificationPosting,
        calendar: Calendar, now: Date, hooks: RunHooks = .none
    ) {
        self.paths = paths
        self.sources = sources
        self.statusSources = statusSources
        self.notifier = notifier
        self.calendar = calendar
        self.now = now
        self.hooks = hooks
    }

    public func run() async -> RunReport {
        let log = CollectorLog(url: paths.log, timeZone: calendar.timeZone)
        let clock = ContinuousClock()
        let started = clock.now
        // The run is stamped at `now`; its finish adds the time it took.
        func finishTime() -> Date {
            let elapsed = started.duration(to: clock.now).components
            return now.addingTimeInterval(TimeInterval(elapsed.seconds) + TimeInterval(elapsed.attoseconds) / 1e18)
        }

        let lock: RunLock
        do {
            try FileManager.default.createDirectory(at: paths.appSupport, withIntermediateDirectories: true)
            try FileManager.default.createDirectory(at: paths.logDirectory, withIntermediateDirectories: true)
            guard let acquired = try RunLock.acquire(paths.lock) else { return recordSkipped(log: log) }
            lock = acquired
        } catch {
            // Every attempt leaves a run record when the database opens (Task 10 reads them).
            log.write("Run failed before starting: \(Self.describe(error))", at: now)
            recordUnstartedRun(.failed, detail: Self.describe(error), log: log)
            return RunReport(outcome: .failed, exitCode: ExitCode.failure, detail: Self.describe(error), notificationsPosted: 0)
        }
        defer { withExtendedLifetime(lock) {} }

        let store: Store
        let runID: Int64
        let interrupted: Int
        do {
            store = try Store.open(paths.database, mode: .readWrite)
            // Holding the lock, no other run can own a `running` row: any left belong to a killed process.
            (runID, interrupted) = try store.transaction {
                let closed = try store.closeInterruptedRuns(at: now)
                return (try store.beginRun(at: now), closed)
            }
        } catch {
            log.write("Run failed: couldn't open the database: \(Self.describe(error))", at: now)
            return RunReport(outcome: .failed, exitCode: ExitCode.failure, detail: Self.describe(error), notificationsPosted: 0)
        }
        log.write("Run \(runID) started", at: now)
        if interrupted > 0 { log.write("Closed \(interrupted) interrupted run record(s)", at: now) }

        var pass = Pass(store: store, log: log, now: now)
        await pass.perform(self)

        let detail = ([pass.firstError.map(Self.describe)].compactMap { $0 } + pass.notes).joined(separator: "; ")
        let outcome: RunOutcome = pass.firstError == nil ? .succeeded : .failed
        var report = RunReport(
            outcome: outcome, exitCode: outcome == .succeeded ? ExitCode.success : ExitCode.failure, detail: detail,
            notificationsPosted: pass.posted)
        let finished = finishTime()
        do {
            try store.finishRun(runID, at: finished, outcome: outcome, detail: detail)
        } catch {
            log.write("Couldn't record the end of run \(runID): \(Self.describe(error))", at: finished)
            report.outcome = .failed
            report.exitCode = ExitCode.failure
        }
        log.write("Run \(runID) \(report.outcome.rawValue)\(detail.isEmpty ? "" : ": \(detail)")", at: finished)
        return report
    }

    /// Spec section 4: a run that can't get the lock exits 0 and records itself as skipped.
    private func recordSkipped(log: CollectorLog) -> RunReport {
        recordUnstartedRun(.skipped, detail: Self.skippedDetail, log: log)
        log.write("Run \(Self.skippedDetail)", at: now)
        return RunReport(outcome: .skipped, exitCode: ExitCode.success, detail: Self.skippedDetail, notificationsPosted: 0)
    }

    /// Records a run that never held the lock as already finished. Start and finish share one
    /// transaction, so the lock holder never sees its row as `running` (and closes it as interrupted).
    private func recordUnstartedRun(_ outcome: RunOutcome, detail: String, log: CollectorLog) {
        do {
            let store = try Store.open(paths.database, mode: .readWrite)
            try store.transaction {
                let id = try store.beginRun(at: now)
                try store.finishRun(id, at: now, outcome: outcome, detail: detail)
            }
        } catch {
            log.write("Couldn't record a \(outcome.rawValue) run: \(Self.describe(error))", at: now)
        }
    }

    static func describe(_ error: any Error) -> String {
        (error as? any LocalizedError)?.errorDescription ?? String(describing: error)
    }

    // MARK: - Steps 2 to 7

    /// The state of one run between the lock and the run record.
    private struct Pass {
        let store: Store
        let log: CollectorLog
        let now: Date
        var firstError: (any Error)?
        var notes: [String] = []
        var posted = 0

        init(store: Store, log: CollectorLog, now: Date) {
            self.store = store
            self.log = log
            self.now = now
        }

        mutating func fail(_ context: String, _ error: any Error) {
            log.write("\(context): \(CollectorRun.describe(error))", at: now)
            if firstError == nil { firstError = error }
        }

        mutating func note(_ text: String) {
            log.write(text, at: now)
            notes.append(text)
        }

        mutating func perform(_ run: CollectorRun) async {
            let calendar = run.calendar
            let baseline = BaselineEngine(store: store, calendar: calendar)
            baseline.discardCache()

            // Step 2: settings, Rebuild and cold start.
            let settings: RuleSettings
            let watched: [String]
            let interval: Int
            let backfillThrough: Date?
            do {
                let usable = try store.usableRules()
                settings = usable.rules
                if !usable.problems.isEmpty { note("\(CollectorRun.invalidRulesNote) \(usable.problems.joined(separator: " "))") }
                watched = try store.value(.watchedComponents)
                let storedInterval = try store.value(.intervalMinutes)
                interval = Settings.usableInterval(storedInterval)
                backfillThrough = try prepareBackfill()
            } catch {
                fail("Couldn't read settings", error)
                return
            }
            baseline.discardCache()

            // Step 3: usage sources.
            let backfillFrom = calendar.date(byAdding: .day, value: -CollectorRun.lookbackDays, to: now)
                ?? now.addingTimeInterval(-TimeInterval(CollectorRun.lookbackDays) * 86_400)
            var ingestFailed = false
            for source in run.sources {
                if !ingest(source, backfillFrom: backfillFrom, calendar: calendar) { ingestFailed = true }
                baseline.discardCache()
            }

            // Step 4: status sources.
            var available: Set<String> = []
            for source in run.statusSources where await fetchStatus(source, backfillFrom: backfillFrom) {
                available.insert(source.id)
            }

            // Steps 5 and 6 are skipped when an ingest threw: evaluated points are history (spec
            // section 7.3) and must not be written without that source's data. The next run catches
            // up from the unchanged last evaluated point. A problem a source reports through its
            // setup state isn't thrown, so evaluation goes on.
            if ingestFailed {
                log.write("Evaluation skipped: an ingest failed, so the next run evaluates these points", at: now)
            } else {
                await evaluateAndNotify(
                    run, baseline: baseline, settings: settings, watched: watched, interval: interval,
                    backfillThrough: backfillThrough, backfillFrom: backfillFrom, available: available)
            }

            // Step 7: retention.
            do {
                if try Retention.prune(store: store, now: now, calendar: calendar) { log.write("Pruned expired rows", at: now) }
            } catch {
                fail("Couldn't prune", error)
            }
        }

        /// Steps 5 and 6: evaluate one day per transaction, then select and post live notices.
        private mutating func evaluateAndNotify(
            _ run: CollectorRun, baseline: BaselineEngine, settings: RuleSettings, watched: [String], interval: Int,
            backfillThrough: Date?, backfillFrom: Date, available: Set<String>
        ) async {
            let calendar = run.calendar
            // Step 5: evaluation, one day per transaction.
            let engine = RuleEngine(
                store: store, baseline: baseline, calendar: calendar,
                naming: Dictionary(run.sources.map { ($0.provider, $0 as any ModelNaming) }, uniquingKeysWith: { first, _ in first }))
            let ruleSources = run.statusSources.filter { available.contains($0.id) }.map { source in
                RuleStatusSource(
                    id: source.id, displayName: source.displayName,
                    providers: run.sources.filter { $0.statusSourceID == source.id }.map(\.provider))
            }
            func isLive(_ point: Date) -> Bool { backfillThrough.map { point > $0 } ?? true }
            var liveOutcomes: [RuleOutcome] = []
            do {
                let points = EvaluationPoints.after(try store.lastEvaluatedPoint(), through: now, earliest: backfillFrom)
                var backfilled = 0
                for (index, start) in stride(from: 0, to: points.count, by: CollectorRun.pointsPerChunk).enumerated() {
                    let chunk = Array(points[start..<min(start + CollectorRun.pointsPerChunk, points.count)])
                    let outcomes = try engine.evaluate(
                        points: chunk, providers: run.sources.map(\.provider), statusSources: ruleSources, settings: settings,
                        watchedComponents: watched, statusAvailable: !ruleSources.isEmpty)
                    liveOutcomes += outcomes.filter { isLive($0.at) }
                    backfilled += chunk.filter { !isLive($0) }.count
                    try run.hooks.afterChunkCommit?(index)
                }
                log.write("Evaluated \(points.count) points (\(backfilled) in backfill)", at: now)
            } catch {
                fail("Evaluation stopped", error)
            }

            // Step 6: notifications, from whatever evaluation committed.
            do {
                // Backfill never notifies (spec section 7.3), so a run that ends inside it selects nothing.
                if let latest = try store.lastEvaluatedPoint(), isLive(latest) {
                    var notices = try store.failureNotices()
                    let pending = NotificationPolicy.select(
                        liveOutcomes, latestPoint: latest, intervalMinutes: interval, settings: settings, mode: .live,
                        failureNotices: &notices, calendar: calendar)
                    try store.setFailureNotices(notices)
                    await post(pending, notifier: run.notifier)
                }
            } catch {
                fail("Couldn't select notifications", error)
            }
        }

        /// Applies a pending Rebuild or a cold start and returns the end of the backfill.
        private func prepareBackfill() throws -> Date? {
            try store.transaction {
                if try store.value(.rebuildRequestedAt) != nil {
                    try store.discardForRebuild()
                    try store.set(.backfillThrough, now)
                    try store.set(.rebuildRequestedAt, nil)
                    log.write("Rebuilding from Codex logs: derived data discarded", at: now)
                } else if try store.lastEvaluatedPoint() == nil, try store.value(.backfillThrough) == nil {
                    try store.set(.backfillThrough, now)
                    log.write("Cold start: backfilling the last \(CollectorRun.lookbackDays) days", at: now)
                }
                return try store.value(.backfillThrough)
            }
        }

        /// Stores one source's ingest and returns whether that worked; a throw is recorded as the
        /// run's error. A problem the source reports through its setup state is stored, not thrown.
        private mutating func ingest(_ source: any UsageSource, backfillFrom: Date, calendar: Calendar) -> Bool {
            let key = source.provider.rawValue
            do {
                let cursor = try store.cursor(key)
                let previous = try store.sourceState(key)
                let result = source.ingest(cursor: cursor, backfillFrom: backfillFrom, now: now)
                let batch = result.batch
                try store.transaction {
                    try store.upsert(responses: batch.responses)
                    try store.upsert(failedTurns: batch.failedTurns)
                    try store.upsert(connectionEvents: batch.connectionEvents)
                    if let limit = batch.usageLimit { try store.setUsageLimit(limit) }
                    for gap in batch.connectionGaps { try store.recordConnectionGap(provider: source.provider, gap: gap, calendar: calendar) }
                    try store.setCursor(key, result.cursor)
                    try store.setSourceState(SourceStateRow(
                        source: key, state: result.state, version: batch.sourceVersion ?? previous?.version,
                        unavailableSince: result.state == .ready ? nil : previous?.unavailableSince ?? now, updatedAt: now))
                }
                log.write(
                    "\(source.displayName): \(batch.responses.count) responses, \(batch.failedTurns.count) failed turns, "
                        + "\(batch.connectionEvents.count) connection events, \(batch.connectionGaps.count) gaps; \(Self.describe(result.state))",
                    at: now)
                return true
            } catch {
                fail("\(source.displayName) ingest failed", error)
                return false
            }
        }

        /// Fetches and stores one status source; returns whether its incident data is available.
        private mutating func fetchStatus(_ source: any StatusSource, backfillFrom: Date) async -> Bool {
            do {
                let known = try store.openIncidents(source: source.id)
                var result: Result<StatusFetch, any Error>
                do {
                    result = .success(try await source.fetch(known: known))
                } catch {
                    result = .failure(error)
                    log.write("\(source.displayName) status unavailable: \(CollectorRun.describe(error))", at: now)
                }
                // Posts older than the lookback would reach past every other record (the feed holds ~100).
                if case .success(.rssOnly(let items)) = result {
                    result = .success(.rssOnly(items.filter { $0.publishedAt >= backfillFrom }))
                    log.write("\(source.displayName) status: summary unavailable, RSS posts only", at: now)
                }
                return try store.applyStatus(result, source: source.id, displayName: source.displayName, now: now)
            } catch {
                fail("\(source.displayName) status couldn't be stored", error)
                return false
            }
        }

        private mutating func post(_ pending: [PendingNotification], notifier: any NotificationPosting) async {
            var failures: [any Error] = []
            for notification in pending {
                do {
                    try await notifier.post(notification)
                    posted += 1
                } catch {
                    log.write("Couldn't post notification \(notification.id): \(CollectorRun.describe(error))", at: now)
                    failures.append(error)
                }
            }
            if !pending.isEmpty { log.write("Posted \(posted) of \(pending.count) notifications", at: now) }
            if let first = failures.first {
                let noun = failures.count == 1 ? "notification" : "notifications"
                notes.append("\(failures.count) \(noun) couldn't be posted: \(CollectorRun.describe(first))")
            }
        }

        private static func describe(_ state: SetupState) -> String {
            switch state {
            case .ready: "ready"
            case .notSetUp(let reason): "not set up: \(reason)"
            case .formatProblem(let detail): "format problem: \(detail)"
            }
        }
    }
}

// MARK: - Rebuild

extension Store {
    /// Spec section 7.3's "Rebuild from Codex logs", as Task 9's storage mapping:
    ///
    /// - discarded: responses, evaluation points, episodes, rule events (`EventKind.ruleKinds`),
    ///   rule state (including the last evaluated point and failed-turn notices), cursors, and
    ///   `failed_turns.evaluated_at` (reset to null);
    /// - kept: baseline epochs and their events, shift dismissals, incidents, status components,
    ///   `statusPost` and `connectionHistoryIncomplete` events, failed-turn and connection-event
    ///   rows, usage limits and source state (the next ingest overwrites both), and settings.
    /// Ends every `running` run record as `failed` with `CollectorRun.interruptedDetail` at `at`.
    /// Called only by the lock holder, before it records its own start. Returns the rows closed.
    func closeInterruptedRuns(at: Date) throws -> Int {
        try run(
            "UPDATE collector_runs SET outcome = ?, detail = ?, finished_at = ? WHERE outcome = ?",
            [.text(RunOutcome.failed.rawValue), .text(CollectorRun.interruptedDetail), .date(at), .text(RunOutcome.running.rawValue)])
    }

    func discardForRebuild() throws {
        try transaction {
            let kinds = EventKind.ruleKinds
            try run("DELETE FROM events WHERE kind IN (\(kinds.map { _ in "?" }.joined(separator: ", ")))", kinds.map(SQLValue.text))
            for table in ["episodes", "eval_points", "rule_state", "cursors", "responses"] {
                try exec("DELETE FROM \(table)")
            }
            try exec("UPDATE failed_turns SET evaluated_at = NULL")
        }
    }
}
