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
///    note in the log and run detail. Adopt legacy progress and apply a pending Rebuild, then
///    prepare backfill independently for status sources and ready usage providers.
/// 3. Ingest each usage source from §8's 30-day lookback: its records, usage limit, connection
///    gaps (as `connectionHistoryIncomplete` events), cursor and setup state, in one transaction
///    per source. An ingest that throws skips that provider's evaluation, while others continue.
/// 4. Fetch and store each status source.
/// 5. Evaluate every point after the last evaluated one (or from the lookback) through now, one
///    day per transaction for each unit. A point at or before its backfill boundary is backfill; later points are
///    live. A crash mid-backfill therefore resumes still in backfill. Failed turns from before the
///    lookback start are first settled uncounted (`Store.settleFailedTurns`), since no point
///    reaches them.
/// 6. Select notifications from the live outcomes and post them. A failed post is logged and
///    counted in the run's detail; the run still succeeds. An unposted failed-turn notice puts its
///    failures back in waiting for the next run.
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
            do {
                let usable = try store.usableRules()
                settings = usable.rules
                if !usable.problems.isEmpty { note("\(CollectorRun.invalidRulesNote) \(usable.problems.joined(separator: " "))") }
                let storedInterval = try store.value(.intervalMinutes)
                interval = Settings.usableInterval(storedInterval)
                try prepareBackfill(run)
                watched = try store.watchedComponents(sources: run.statusSources.map { StatusSourceSummary(id: $0.id, displayName: $0.displayName, defaultWatchedComponents: $0.defaultWatchedComponents) })
            } catch {
                fail("Couldn't read settings", error)
                return
            }
            baseline.discardCache()

            // Step 3: usage sources.
            let backfillFrom = calendar.date(byAdding: .day, value: -CollectorRun.lookbackDays, to: now)
                ?? now.addingTimeInterval(-TimeInterval(CollectorRun.lookbackDays) * 86_400)
            var ingestFailed: Set<ProviderID> = []
            for source in run.sources {
                if !ingest(source, backfillFrom: backfillFrom, calendar: calendar) { ingestFailed.insert(source.provider) }
                baseline.discardCache()
            }

            do {
                let existing = try Set(run.sources.filter { try store.lastEvaluatedPoint(unit: $0.provider.rawValue) != nil }.map(\.provider))
                for source in run.sources where !ingestFailed.contains(source.provider) {
                    let key = source.provider.rawValue
                    if try store.lastEvaluatedPoint(unit: key) == nil, try store.backfill(unit: key) == nil,
                       try store.sourceState(key)?.state == .ready {
                        try store.setBackfill(ProviderBackfill(reason: .new, startedAt: now, through: now, finishedAt: nil,
                            announce: existing.contains(where: { $0 != source.provider })), unit: key)
                        log.write("\(source.displayName): backfilling history", at: now)
                    }
                }
            } catch { fail("Couldn't prepare provider backfill", error) }

            // Step 4: status sources.
            var available: Set<String> = []
            for source in run.statusSources where await fetchStatus(source, backfillFrom: backfillFrom) {
                available.insert(source.id)
            }

            // Each failed ingest leaves that provider's progress unchanged for the next run.
            await evaluateAndNotify(
                run, baseline: baseline, settings: settings, watched: watched, interval: interval,
                backfillFrom: backfillFrom, available: available, ingestFailed: ingestFailed)

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
            backfillFrom: Date, available: Set<String>, ingestFailed: Set<ProviderID>
        ) async {
            let calendar = run.calendar
            // Step 5: evaluation, one day per transaction.
            let providerInfo = Dictionary(run.sources.map { source in
                (source.provider, RuleProviderInfo(name: source.displayName, failureNoun: source.failureNoun,
                    signals: source.signals, rules: source.supportedRules, naming: source))
            }, uniquingKeysWith: { first, _ in first })
            let engine = RuleEngine(
                store: store, baseline: baseline, calendar: calendar,
                providers: providerInfo)
            var units: [EvaluationUnit] = []
            do {
                for source in run.sources where !ingestFailed.contains(source.provider) {
                    let key = source.provider.rawValue
                    if try store.lastEvaluatedPoint(unit: key) != nil ||
                        (store.sourceState(key)?.state == .ready && store.backfill(unit: key) != nil) {
                        units.append(.provider(source.provider))
                    }
                }
                for source in run.statusSources {
                    let providers = run.sources.filter { $0.statusSourceID == source.id }.map(\.provider)
                    if !providers.isEmpty && providers.allSatisfy({ ingestFailed.contains($0) }) { continue }
                    units.append(.statusSource(RuleStatusSource(id: source.id, displayName: source.displayName, providers: providers),
                        available: available.contains(source.id)))
                }
            } catch { fail("Couldn't select evaluation units", error); return }
            for unit in units {
              var liveOutcomes: [RuleOutcome] = []
              var backfill: ProviderBackfill?
              func isLive(_ point: Date) -> Bool { backfill.map { point > $0.through } ?? true }
              do {
                backfill = try store.backfill(unit: unit.key)
                if case .provider(let provider) = unit {
                    let settled = try store.settleFailedTurns(before: backfillFrom, provider: provider)
                    if settled > 0 { log.write("Settled \(settled) failed turn(s) from before the lookback without counting them", at: now) }
                }
                let points = EvaluationPoints.after(try store.lastEvaluatedPoint(unit: unit.key), through: now, earliest: backfillFrom)
                var backfilled = 0
                for (index, start) in stride(from: 0, to: points.count, by: CollectorRun.pointsPerChunk).enumerated() {
                    let chunk = Array(points[start..<min(start + CollectorRun.pointsPerChunk, points.count)])
                    let outcomes = try engine.evaluate(
                        points: chunk, unit: unit, settings: settings, watchedComponents: watched)
                    liveOutcomes += outcomes.filter { isLive($0.at) }
                    backfilled += chunk.filter { !isLive($0) }.count
                    try run.hooks.afterChunkCommit?(index)
                }
                if var pending = backfill, pending.finishedAt == nil,
                   EvaluationPoints.after(try store.lastEvaluatedPoint(unit: unit.key), through: pending.through, earliest: backfillFrom).isEmpty {
                    try store.transaction {
                        pending.finishedAt = now
                        try store.setBackfill(pending, unit: unit.key)
                        if case .provider(let provider) = unit, let source = run.sources.first(where: { $0.provider == provider }) {
                            if pending.reason == .rebuild || pending.announce {
                                let body = pending.reason == .rebuild
                                    ? Copy.historyRebuilt(name: source.displayName, days: CollectorRun.lookbackDays)
                                    : Copy.providerAdded(name: source.displayName, days: CollectorRun.lookbackDays)
                                try store.insertEvent(EventRow(at: now, kind: pending.reason == .rebuild ? EventKind.historyRebuilt : EventKind.providerAdded,
                                    provider: provider.rawValue, scope: "*", title: source.displayName, body: body))
                            }
                            if pending.announce {
                                var arrivals = try store.value(.pendingArrivals)
                                if !arrivals.contains(provider.rawValue) { arrivals.append(provider.rawValue) }
                                try store.set(.pendingArrivals, arrivals)
                            }
                        }
                    }
                }
                log.write("\(unit.key): evaluated \(points.count) points (\(backfilled) in backfill)", at: now)
            } catch {
                fail("Evaluation stopped", error)
            }

            // Step 6: notifications, from whatever evaluation committed.
            do {
                // Backfill never notifies (spec section 7.3), so a run that ends inside it selects nothing.
                if let latest = try store.lastEvaluatedPoint(unit: unit.key), isLive(latest) {
                    let provider: ProviderID? = { if case .provider(let p) = unit { return p }; return nil }()
                    let previous = try provider.map { try store.failureNotices(provider: $0) } ?? FailureNotices()
                    var notices = previous
                    let pending = NotificationPolicy.select(
                        liveOutcomes, latestPoint: latest, intervalMinutes: interval, settings: settings, mode: .live,
                        failureNotices: &notices, calendar: calendar, provider: provider.flatMap { providerInfo[$0] })
                    if let provider { try store.setFailureNotices(notices, provider: provider) }
                    let unposted = await post(pending, notifier: run.notifier)
                    // As CollectorMonitor does: saved before posting, put back when the post fails, so
                    // the failed-turn notice's failures wait for the next run instead of being lost.
                    if let provider, unposted.contains(where: { $0.threadID == NotificationPolicy.failedTurnsThreadID(provider: provider) }) {
                        try store.setFailureNotices(NotificationPolicy.withheldFailureNotices(
                            liveOutcomes, latestPoint: latest, intervalMinutes: interval, settings: settings, failureNotices: previous,
                            provider: providerInfo[provider]), provider: provider)
                    }
                }
            } catch {
                fail("Couldn't select notifications", error)
            }
            }
        }

        /// Adopts old progress and prepares the requested and status-source backfills.
        private func prepareBackfill(_ run: CollectorRun) throws {
            try store.transaction {
                try store.applyWatchedDefaults(sources: run.statusSources.map { StatusSourceSummary(id: $0.id, displayName: $0.displayName, defaultWatchedComponents: $0.defaultWatchedComponents) })
                _ = try store.adoptGlobalProgress(providers: run.sources.map(\.provider), legacyStatusSourceIDs: ["openai"])
                var requests = try store.value(.providerRebuildRequests)
                if try store.value(.rebuildRequestedAt) != nil {
                    try store.discardForRebuild()
                    try store.set(.rebuildRequestedAt, nil)
                    for source in run.sources {
                        requests.removeValue(forKey: source.provider.rawValue)
                        try store.setBackfill(ProviderBackfill(reason: .rebuild, startedAt: now, through: now, finishedAt: nil, announce: false), unit: source.provider.rawValue)
                        log.write("\(source.displayName): rebuilding history", at: now)
                    }
                    for source in run.statusSources {
                        try store.setBackfill(ProviderBackfill(reason: .rebuild, startedAt: now, through: now, finishedAt: nil, announce: false), unit: source.id)
                        log.write("\(source.displayName): rebuilding history", at: now)
                    }
                    log.write("Rebuilding from provider logs: derived data discarded", at: now)
                } else {
                    for source in run.sources where requests[source.provider.rawValue] != nil {
                        try store.discardForRebuild(provider: source.provider)
                        try store.setBackfill(ProviderBackfill(reason: .rebuild, startedAt: now, through: now, finishedAt: nil, announce: false), unit: source.provider.rawValue)
                        requests.removeValue(forKey: source.provider.rawValue)
                        log.write("Rebuilding from \(source.displayName) logs: derived data discarded", at: now)
                    }
                }
                try store.set(.providerRebuildRequests, requests)
                for source in run.statusSources where try store.lastEvaluatedPoint(unit: source.id) == nil && store.backfill(unit: source.id) == nil {
                    try store.setBackfill(ProviderBackfill(reason: .new, startedAt: now, through: now, finishedAt: nil, announce: false), unit: source.id)
                    log.write("\(source.displayName): backfilling history", at: now)
                }
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
                    try store.upsert(compactions: batch.compactions)
                    try store.upsert(failedTurns: batch.failedTurns)
                    try store.upsert(connectionEvents: batch.connectionEvents)
                    if let limit = batch.usageLimit { try store.setUsageLimit(limit) }
                    for gap in batch.connectionGaps { try store.recordConnectionGap(provider: source.provider, providerName: source.displayName, gap: gap, calendar: calendar) }
                    try store.setCursor(key, result.cursor)
                    try store.setSourceState(SourceStateRow(
                        source: key, state: result.state, version: batch.sourceVersion ?? previous?.version,
                        unavailableSince: Self.unavailableSince(previous: previous, new: result.state, now: now), updatedAt: now))
                }
                log.write(
                    "\(source.displayName): \(batch.responses.count) responses, \(batch.failedTurns.count) failed turns, "
                        + "\(batch.connectionEvents.count) connection events, \(batch.connectionGaps.count) gaps, "
                        + "\(batch.excludedServerToolResponses) excluded server-tool responses, "
                        + "\(batch.excludedClientErrors) excluded client errors, \(batch.invalidCompactions) invalid compactions; \(Self.describe(result.state))",
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

        /// Posts each notification and returns the ones that couldn't be posted.
        private mutating func post(_ pending: [PendingNotification], notifier: any NotificationPosting) async -> [PendingNotification] {
            var failures: [any Error] = []
            var unposted: [PendingNotification] = []
            for notification in pending {
                do {
                    try await notifier.post(notification)
                    posted += 1
                } catch {
                    log.write("Couldn't post notification \(notification.id): \(CollectorRun.describe(error))", at: now)
                    failures.append(error)
                    unposted.append(notification)
                }
            }
            if !pending.isEmpty { log.write("Posted \(pending.count - unposted.count) of \(pending.count) notifications", at: now) }
            if let first = failures.first {
                let noun = failures.count == 1 ? "notification" : "notifications"
                notes.append("\(failures.count) \(noun) couldn't be posted: \(CollectorRun.describe(first))")
            }
            return unposted
        }

        /// When the source became unavailable in its current way (spec 6.5): nil while ready; kept while the same
        /// kind of problem continues, whatever its text; `now` when the source changes from ready or from the
        /// other kind of problem.
        private static func unavailableSince(previous: SourceStateRow?, new: SetupState, now: Date) -> Date? {
            switch (previous?.state, new) {
            case (_, .ready): nil
            case (.notSetUp?, .notSetUp), (.formatProblem?, .formatProblem): previous?.unavailableSince ?? now
            default: now
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
    /// Ends every `running` run record as `failed` with `CollectorRun.interruptedDetail` at `at`.
    /// Called only by the lock holder, before it records its own start. Returns the rows closed.
    func closeInterruptedRuns(at: Date) throws -> Int {
        try run(
            "UPDATE collector_runs SET outcome = ?, detail = ?, finished_at = ? WHERE outcome = ?",
            [.text(RunOutcome.failed.rawValue), .text(CollectorRun.interruptedDetail), .date(at), .text(RunOutcome.running.rawValue)])
    }

    /// Global rebuild removes derived data for all usage and status units:
    ///
    /// - discarded: responses, evaluation points, episodes, rule events (`EventKind.ruleKinds`),
    ///   rule state (including the last evaluated point and failed-turn notices), cursors, and
    ///   `failed_turns.evaluated_at` (reset to null; the backfill counts the turns inside the
    ///   lookback again and settles older ones uncounted, `settleFailedTurns`);
    /// - kept: baseline epochs and their events, shift dismissals, incidents, status components,
    ///   `statusPost`, `providerAdded`, `historyRebuilt` and `connectionHistoryIncomplete` events, failed-turn and connection-event
    ///   rows, usage limits and source state (the next ingest overwrites both), and settings.
    func discardForRebuild() throws {
        try transaction {
            let kinds = EventKind.ruleKinds
            try run("DELETE FROM events WHERE kind IN (\(kinds.map { _ in "?" }.joined(separator: ", ")))", kinds.map(SQLValue.text))
            for table in ["episodes", "eval_points", "rule_state", "cursors", "responses", "compactions"] {
                try exec("DELETE FROM \(table)")
            }
            try exec("UPDATE failed_turns SET evaluated_at = NULL")
        }
    }

    /// Discard this provider's responses, evaluation points, episodes, rule events, rule state and
    /// cursor; reset its failed-turn evaluation. Keep status units, acceptances, incidents,
    /// failed turns, connection history, completion events and settings.
    func discardForRebuild(provider: ProviderID) throws {
        try transaction {
            let kinds = EventKind.ruleKinds
            try run("DELETE FROM events WHERE provider = ? AND kind IN (\(kinds.map { _ in "?" }.joined(separator: ", ")))", [.text(provider.rawValue)] + kinds.map(SQLValue.text))
            for table in ["episodes", "eval_points", "rule_state", "responses", "compactions"] {
                try run("DELETE FROM \(table) WHERE provider = ?", [.text(provider.rawValue)])
            }
            try run("DELETE FROM cursors WHERE source = ?", [.text(provider.rawValue)])
            try run("UPDATE failed_turns SET evaluated_at = NULL WHERE provider = ?", [.text(provider.rawValue)])
        }
    }
}
