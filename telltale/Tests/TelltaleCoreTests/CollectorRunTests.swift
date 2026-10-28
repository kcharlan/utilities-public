import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

// MARK: - Fakes

/// A usage source that hands out the responses added to it, each once: those ending after the
/// previous run's `now` (its cursor) and at or before this run's. Its other output is set per test.
final class FakeUsageSource: UsageSource, @unchecked Sendable {
    let provider: ProviderID
    let displayName: String
    let statusSourceID: String
    let signals: Set<Signal> = [.speed, .errors, .link, .provider, .load]
    private let naming = SyntheticNaming()
    private let lock = NSLock()
    private var pending: [ResponseRecord] = []
    private var nextBatch = IngestBatch()
    private var nextState = SetupState.ready
    private var onIngest: (@Sendable () -> Void)?
    private var calls: [(cursor: Data?, backfillFrom: Date, now: Date)] = []

    init(provider: ProviderID = .codex, displayName: String = "Example", statusSourceID: String = RuleHarness.sourceID) {
        self.provider = provider
        self.displayName = displayName
        self.statusSourceID = statusSourceID
    }

    func displayName(model: String) -> String { naming.displayName(model: model) }
    func incidentTitle(_ title: String, names model: String) -> Bool { naming.incidentTitle(title, names: model) }

    func add(_ responses: [ResponseRecord]) { lock.withLock { pending += responses } }
    /// Failed turns, connection events, gaps, a usage limit and a version for the next ingest only.
    func setNextBatch(_ batch: IngestBatch) { lock.withLock { nextBatch = batch } }
    func setState(_ state: SetupState) { lock.withLock { nextState = state } }
    func setOnIngest(_ body: @escaping @Sendable () -> Void) { lock.withLock { onIngest = body } }
    var cursorsSeen: [Data?] { lock.withLock { calls.map(\.cursor) } }
    var backfillFromSeen: [Date] { lock.withLock { calls.map(\.backfillFrom) } }

    static func cursor(_ now: Date) -> Data { Data(String(now.timeIntervalSince1970).utf8) }

    func ingest(cursor: Data?, backfillFrom: Date, now: Date) -> IngestResult {
        let (batch, state, hook) = lock.withLock { () -> (IngestBatch, SetupState, (@Sendable () -> Void)?) in
            calls.append((cursor, backfillFrom, now))
            let after = cursor.flatMap { Double(String(decoding: $0, as: UTF8.self)) }.map(Date.init(timeIntervalSince1970:))
            var batch = nextBatch
            nextBatch = IngestBatch()
            batch.responses = pending.filter { response in
                response.end <= now && response.end >= backfillFrom && (after.map { response.end > $0 } ?? true)
            }
            return (batch, nextState, onIngest)
        }
        hook?()
        return IngestResult(batch: batch, cursor: Self.cursor(now), state: state)
    }
}

/// A status source whose next answer the test sets.
final class FakeStatusSource: StatusSource, @unchecked Sendable {
    struct Down: Error, LocalizedError {
        var errorDescription: String? { "synthetic status outage" }
    }

    let id = RuleHarness.sourceID
    let displayName = "Example Status"
    private let lock = NSLock()
    private var answer: Result<StatusFetch, any Error> = .failure(Down())

    func setAnswer(_ answer: Result<StatusFetch, any Error>) { lock.withLock { self.answer = answer } }

    func fetch(known: [IncidentRecord]) async throws -> StatusFetch {
        try lock.withLock { answer }.get()
    }
}

struct InjectedCrash: Error, LocalizedError {
    var errorDescription: String? { "synthetic crash after a committed chunk" }
}

/// Temporary paths, a fake source, a fake notifier and the America/New_York calendar.
final class CollectorHarness {
    let home: URL
    let paths: TelltalePaths
    let calendar = Synth.newYork
    let source = FakeUsageSource()
    let notifier = RecordingNotifier()
    var statusSources: [any StatusSource] = []
    var synth = Synth()

    init(home: URL) {
        self.home = home
        paths = TelltalePaths(home: home, codexHome: home.appending(path: "synthetic-codex", directoryHint: .isDirectory))
    }

    /// A local time in 2026.
    func at(_ month: Int, _ day: Int, _ hour: Int = 0, _ minute: Int = 0) -> Date { Synth.local(2026, month, day, hour, minute) }

    func run(at now: Date, sources: [any UsageSource]? = nil, hooks: RunHooks = .none) async -> RunReport {
        await CollectorRun(
            paths: paths, sources: sources ?? [source], statusSources: statusSources, notifier: notifier,
            calendar: calendar, now: now, hooks: hooks
        ).run()
    }

    func store() throws -> Store { try Store.open(paths.database, mode: .readWrite) }

    /// Sep 1–3: 20 responses a day at 40 tok/s from 09:00, so Sep 4 is past cold start with a
    /// usual of 40 for the default key.
    func seedUsual() {
        for day in 1...3 { source.add(synth.responses(20, throughput: 40, from: at(9, day, 9))) }
    }

    /// Sep 4: `count` responses a minute apart at 30 tok/s from 09:00, a speed index of
    /// 30 / 40 = 0.75 (25% slower). The 09:05 window holds 6 responses (thin); 09:10, 09:15 and
    /// 09:20 hold at least 10, so the slower rule fires at 09:20 with onset 09:10 − 15 min = 08:55.
    func seedSlowdown(count: Int = 30) {
        source.add(synth.responses(count, throughput: 30, from: at(9, 4, 9)))
    }

    var log: String { (try? String(contentsOf: paths.log, encoding: .utf8)) ?? "" }
}

func withCollector(_ body: (CollectorHarness) async throws -> Void) async throws {
    try await withAsyncScratchDirectory { home in try await body(CollectorHarness(home: home)) }
}

// MARK: - Tests

@Suite struct CollectorRunTests {
    @Test func skippedWhenLockHeld() async throws {
        try await withCollector { harness throws in
            try FileManager.default.createDirectory(at: harness.paths.appSupport, withIntermediateDirectories: true)
            let held = try #require(try RunLock.acquire(harness.paths.lock))
            let now = harness.at(9, 4, 10)

            let report = await harness.run(at: now)

            #expect(report == RunReport(outcome: .skipped, exitCode: 0, detail: CollectorRun.skippedDetail, notificationsPosted: 0))
            #expect(CollectorRun.skippedDetail == "skipped: previous run still active")
            let runs = try harness.store().recentRuns(limit: 5)
            #expect(runs.map(\.outcome) == [.skipped])
            #expect(runs.first?.detail == CollectorRun.skippedDetail)
            #expect(runs.first?.startedAt == now)
            #expect(harness.source.cursorsSeen.isEmpty)
            #expect(harness.log.contains(CollectorRun.skippedDetail))
            withExtendedLifetime(held) {}
        }
    }

    @Test func firstRunBackfillsWithoutNotifying() async throws {
        try await withCollector { harness throws in
            harness.seedUsual()
            harness.seedSlowdown()
            let now = harness.at(9, 4, 10)

            let report = await harness.run(at: now)

            #expect(report.outcome == .succeeded && report.exitCode == 0 && report.notificationsPosted == 0)
            #expect(await harness.notifier.posted.isEmpty)
            let store = try harness.store()
            #expect(try store.value(.backfillThrough) == now)
            #expect(try store.lastEvaluatedPoint() == now)
            // §8's 30-day lookback, in the run's calendar.
            #expect(harness.source.backfillFromSeen == [harness.at(8, 5, 10)])
            let episodes = try store.episodes(rule: RuleID.slower.rawValue)
            #expect(episodes.map(\.firedAt) == [harness.at(9, 4, 9, 20)])
            #expect(episodes.map(\.onset) == [harness.at(9, 4, 8, 55)])
        }
    }

    @Test func liveRunNotifiesFreshFire() async throws {
        try await withCollector { harness throws in
            harness.seedUsual()
            #expect(await harness.run(at: harness.at(9, 4, 8)).outcome == .succeeded)  // cold start
            harness.seedSlowdown()

            let report = await harness.run(at: harness.at(9, 4, 9, 20))

            #expect(report.outcome == .succeeded && report.notificationsPosted == 1)
            let episode = try #require(try harness.store().episodes(rule: RuleID.slower.rawValue).first?.id)
            let expected = PendingNotification(
                id: "slower-\(episode)-fired", title: "Slower than usual",
                body: Copy.slowerFired(model: "Example", percent: 25, since: harness.at(9, 4, 8, 55), calendar: harness.calendar),
                threadID: "slower.codex.\(Synth.model)")
            #expect(await harness.notifier.posted == [expected])

            // The next run has nothing new to say.
            #expect(await harness.run(at: harness.at(9, 4, 9, 25)).notificationsPosted == 0)
            #expect(await harness.notifier.posted.count == 1)
        }
    }

    @Test func sourceProblemDoesNotStopOtherSources() async throws {
        try await withCollector { harness throws in
            let broken = FakeUsageSource(provider: ProviderID(rawValue: "example.broken"), displayName: "Broken")
            broken.setState(.formatProblem("synthetic format problem"))
            harness.source.add(harness.synth.responses(3, throughput: 40, from: harness.at(9, 4, 9)))
            let now = harness.at(9, 4, 10)

            let report = await harness.run(at: now, sources: [broken, harness.source])

            #expect(report.outcome == .succeeded)
            let store = try harness.store()
            #expect(try store.responses(provider: .codex, model: Synth.model, endingIn: harness.at(9, 4)...now).count == 3)
            #expect(try store.sourceState("codex")?.state == .ready)
            let brokenState = try #require(try store.sourceState("example.broken"))
            #expect(brokenState.state == .formatProblem("synthetic format problem"))
            #expect(brokenState.unavailableSince == now)

            // A later run keeps the problem's start time; recovery clears it.
            _ = await harness.run(at: harness.at(9, 4, 10, 5), sources: [broken, harness.source])
            #expect(try harness.store().sourceState("example.broken")?.unavailableSince == now)
            broken.setState(.ready)
            _ = await harness.run(at: harness.at(9, 4, 10, 10), sources: [broken, harness.source])
            #expect(try harness.store().sourceState("example.broken")?.unavailableSince == nil)
        }
    }

    @Test func ingestStoresBatchGapsCursorAndVersion() async throws {
        try await withCollector { harness throws in
            let gap = DateInterval(start: harness.at(9, 3, 18), end: harness.at(9, 4, 9))
            let failure = FailedTurnRecord(
                provider: .codex, threadID: "thread_synthetic_01", turnID: "turn_synthetic_901",
                startedAt: harness.at(9, 4, 9, 1), completedAt: harness.at(9, 4, 9, 2), errorCode: "serverOverloaded",
                message: "Synthetic failure 1")
            let connection = ConnectionEventRecord(
                provider: .codex, sourceID: "logs_synthetic:1", at: harness.at(9, 4, 9, 3), kind: .disconnect, detail: "synthetic")
            let limit = UsageLimitSnapshot(provider: .codex, at: harness.at(9, 4, 9, 4), usedPercent: 12, windowMinutes: 300)
            harness.source.setNextBatch(IngestBatch(
                failedTurns: [failure], connectionEvents: [connection], connectionGaps: [gap], usageLimit: limit,
                sourceVersion: "0.0.0-synthetic"))
            let now = harness.at(9, 4, 10)

            #expect(await harness.run(at: now).outcome == .succeeded)
            #expect(await harness.run(at: harness.at(9, 4, 10, 5)).outcome == .succeeded)

            let store = try harness.store()
            #expect(try store.connectionGaps(provider: .codex, overlapping: DateInterval(start: harness.at(9, 1), end: now)) == [gap])
            #expect(try RawSQLite.scalar(harness.paths.database, "SELECT COUNT(*) FROM failed_turns") == "1")
            #expect(try store.connectionEvents(provider: .codex, in: harness.at(9, 4)...now) == [connection])
            #expect(try store.usageLimit(provider: .codex) == limit)
            #expect(try store.cursor("codex") == FakeUsageSource.cursor(harness.at(9, 4, 10, 5)))
            #expect(harness.source.cursorsSeen == [nil, FakeUsageSource.cursor(now)])
            // The version seen is kept when a later ingest reads nothing that names one.
            #expect(try store.sourceState("codex")?.version == "0.0.0-synthetic")
        }
    }

    @Test func statusFailureMarksUnavailableAndKeepsIncidents() async throws {
        try await withCollector { harness throws in
            let status = FakeStatusSource()
            harness.statusSources = [status]
            let published = harness.at(9, 4, 8)
            let impact = ComponentImpact(componentID: "comp_cli", status: "degraded_performance", start: published)
            let link = URL(string: "https://status.example.com/incidents/inc_synthetic_01")!
            let open = IncidentRecord(
                source: RuleHarness.sourceID, id: "inc_synthetic_01", name: "Elevated errors", status: "investigating",
                publishedAt: published, updatedAt: published, link: link,
                history: [StatusChange(at: published, status: "investigating")], impacts: [impact])
            let components = [StatusComponent(id: "comp_cli", name: "CLI")]
            status.setAnswer(.success(.full(components: components, incidents: [open])))
            #expect(await harness.run(at: harness.at(9, 4, 9)).outcome == .succeeded)  // backfill: fires quietly
            #expect(try harness.store().episodes(rule: RuleID.incident.rawValue).map(\.endedAt) == [nil])

            status.setAnswer(.failure(FakeStatusSource.Down()))
            let downAt = harness.at(9, 4, 9, 30)
            let report = await harness.run(at: downAt)

            #expect(report.outcome == .succeeded)
            let store = try harness.store()
            #expect(try store.sourceState(RuleHarness.sourceID)?.unavailableSince == downAt)
            #expect(try store.openIncidents(source: RuleHarness.sourceID) == [open])
            #expect(try store.episodes(rule: RuleID.incident.rawValue).map(\.endedAt) == [nil])
            #expect(harness.log.contains("synthetic status outage"))

            // Back again with the incident resolved: the episode clears and notifies.
            let resolvedAt = harness.at(9, 4, 9, 32)
            var resolved = open
            resolved.status = "resolved"
            resolved.updatedAt = resolvedAt
            resolved.history.append(StatusChange(at: resolvedAt, status: "resolved"))
            status.setAnswer(.success(.full(components: components, incidents: [resolved])))
            #expect(await harness.run(at: harness.at(9, 4, 9, 35)).notificationsPosted == 1)
            #expect(await harness.notifier.posted.map(\.body) == [Copy.incidentCleared(source: "Example Status", name: "Elevated errors")])
            #expect(try harness.store().sourceState(RuleHarness.sourceID)?.unavailableSince == nil)
        }
    }

    @Test func rssOnlyPostsOutsideTheLookbackAreNotRecorded() async throws {
        try await withCollector { harness throws in
            let status = FakeStatusSource()
            harness.statusSources = [status]
            let now = harness.at(9, 4, 10)
            let recent = RSSItem(title: "Synthetic recent post", link: URL(string: "https://status.example.com/incidents/inc_synthetic_02")!,
                                 publishedAt: harness.at(9, 1))
            let old = RSSItem(title: "Synthetic old post", link: URL(string: "https://status.example.com/incidents/inc_synthetic_03")!,
                              publishedAt: harness.at(7, 1))
            status.setAnswer(.success(.rssOnly([recent, old])))

            #expect(await harness.run(at: now).outcome == .succeeded)

            #expect(try RawSQLite.column(harness.paths.database, "SELECT title FROM events WHERE kind = 'statusPost'") == [recent.title])
            #expect(try harness.store().sourceState(RuleHarness.sourceID)?.unavailableSince == now)
        }
    }

    @Test func rebuildFollowsRebuildTable() async throws {
        try await withCollector { harness throws in
            let url = harness.paths.database
            let old = harness.at(7, 1, 12)
            var rules = RuleSettings.defaults
            rules.failedTurns.enabled = false  // so the reset evaluated_at stays visible after the run
            rules.slower.threshold = 0.2
            do {
                let store = try harness.store()
                // Discarded.
                try store.upsert(responses: [harness.synth.response(throughput: 40, end: old)])  // resp_synthetic_01
                try store.insertEvalPoints([EvalPointRow(
                    provider: .codex, model: Synth.model, at: old, speedIndex: 1, mixUsual: 40, medianTPS: 40, samples: 12, state: .known)])
                let episode = try store.insertEpisode(EpisodeRow(
                    rule: EpisodeRow.slowerRule, provider: "codex", scope: Synth.model, direction: .slower, onset: old,
                    firedAt: old, endedAt: old.addingTimeInterval(3_600), endReason: EpisodeRow.EndReason.cleared,
                    severity: "red", worstValue: 0.6))
                for kind in EventKind.ruleKinds {
                    try store.insertEvent(EventRow(at: old, kind: kind, provider: "codex", scope: Synth.model, title: "Slower than usual",
                                                   body: "synthetic \(kind)", episodeID: episode))
                }
                try store.setRuleState(rule: RuleID.slower.rawValue, provider: "codex", scope: Synth.model, json: "{}")
                try store.setLastEvaluatedPoint(old)
                try store.setFailureNotices(FailureNotices(lastNoticeAt: old))
                try store.setCursor("codex", Data("synthetic old cursor".utf8))
                // Kept.
                try store.upsert(failedTurns: [FailedTurnRecord(
                    provider: .codex, threadID: "thread_synthetic_01", turnID: "turn_synthetic_901", startedAt: old,
                    completedAt: old, errorCode: "serverOverloaded", message: "Synthetic failure 1")])
                try store.markEvaluated(try store.unevaluatedFailedTurns(through: old), at: old)
                try store.upsert(connectionEvents: [ConnectionEventRecord(
                    provider: .codex, sourceID: "logs_synthetic:1", at: old, kind: .retry, detail: "synthetic")])
                try store.recordConnectionGap(provider: .codex, gap: DateInterval(start: old, duration: 3_600), calendar: harness.calendar)
                let epoch = try store.insertEpoch(
                    provider: .codex, model: Synth.model, since: LocalDay(old, calendar: harness.calendar), createdAt: old,
                    before: UsualTable(medians: [:], samples: [:], activeDays: 0, epochID: nil))
                try store.insertEvent(EventRow(at: old, kind: EventKind.baselineAccepted, provider: "codex", scope: Synth.model,
                                               title: "Usual accepted", body: "synthetic", epochID: epoch))
                try store.insertShiftDismissal(provider: .codex, model: Synth.model, direction: .slower,
                                               firstDay: LocalDay(old, calendar: harness.calendar), at: old)
                try store.replace(components: [StatusComponent(id: "comp_cli", name: "CLI")], source: RuleHarness.sourceID)
                try store.upsert(incidents: [IncidentRecord(
                    source: RuleHarness.sourceID, id: "inc_synthetic_01", name: "Elevated errors", status: "resolved",
                    publishedAt: old, updatedAt: old, link: URL(string: "https://status.example.com/incidents/inc_synthetic_01")!,
                    history: [], impacts: [])])
                try store.recordRSSItems(
                    [RSSItem(title: "Synthetic post", link: URL(string: "https://status.example.com/incidents/inc_synthetic_01")!, publishedAt: old)],
                    source: RuleHarness.sourceID, displayName: "Example Status")
                try store.setUsageLimit(UsageLimitSnapshot(provider: .codex, at: old, usedPercent: 50, windowMinutes: 300))
                try store.setSourceState(SourceStateRow(source: "codex", state: .ready, version: "0.0.0-synthetic", updatedAt: old))
                try store.set(.rules, rules)
                try store.set(.watchedComponents, ["CLI"])
                try store.set(.rebuildRequestedAt, harness.at(9, 4, 9, 55))
            }
            let keptEvents = try RawSQLite.rows(url, "SELECT id, kind FROM events WHERE kind NOT IN ('ruleFired', 'ruleEscalated', 'ruleCleared') ORDER BY id")
            #expect(keptEvents.map { $0[1] } == [EventKind.connectionHistoryIncomplete, EventKind.baselineAccepted, EventKind.statusPost])
            let now = harness.at(9, 4, 10)

            let report = await harness.run(at: now)

            #expect(report.outcome == .succeeded && report.notificationsPosted == 0)
            #expect(await harness.notifier.posted.isEmpty)
            #expect(harness.source.cursorsSeen == [nil])
            let store = try harness.store()
            // Discarded: responses, evaluation points, episodes, rule events, rule state, cursors (replaced by
            // this run's), and failed_turns.evaluated_at.
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM responses") == "0")
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM eval_points") == "0")
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM episodes") == "0")
            #expect(try RawSQLite.rows(url, "SELECT id, kind FROM events ORDER BY id") == keptEvents)
            let ruleStates = try RawSQLite.column(url, "SELECT rule || '/' || scope FROM rule_state")
            #expect(ruleStates == ["engine/lastPoint"])
            #expect(try store.lastEvaluatedPoint() == now)
            #expect(try store.failureNotices() == FailureNotices())
            #expect(try store.cursor("codex") == FakeUsageSource.cursor(now))
            #expect(try RawSQLite.rows(url, "SELECT turn_id, evaluated_at FROM failed_turns") == [["turn_synthetic_901", "NULL"]])
            // Kept.
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM connection_events") == "1")
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM baseline_epochs") == "1")
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM shift_dismissals") == "1")
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM incidents") == "1")
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM status_components") == "1")
            #expect(try store.usageLimit(provider: .codex)?.usedPercent == 50)
            #expect(try store.sourceState("codex")?.version == "0.0.0-synthetic")
            #expect(try store.value(.rules) == rules)
            #expect(try store.value(.watchedComponents) == ["CLI"])
            // The request is consumed and the replay ends at this run.
            #expect(try store.value(.rebuildRequestedAt) == nil)
            #expect(try store.value(.backfillThrough) == now)
        }
    }

    @Test func rebuildDiscardsExactlyTheRuleEventKinds() {
        #expect(EventKind.ruleKinds == ["ruleFired", "ruleEscalated", "ruleCleared"])
        #expect(!EventKind.ruleKinds.contains(EventKind.connectionHistoryIncomplete))
        #expect(!EventKind.ruleKinds.contains(EventKind.statusPost))
    }

    @Test func postFailureStillSucceeds() async throws {
        try await withCollector { harness throws in
            harness.seedUsual()
            _ = await harness.run(at: harness.at(9, 4, 8))
            harness.seedSlowdown()
            await harness.notifier.refuseAll()

            let report = await harness.run(at: harness.at(9, 4, 9, 20))

            #expect(report.outcome == .succeeded && report.exitCode == 0 && report.notificationsPosted == 0)
            #expect(report.detail == "1 notification couldn't be posted: synthetic notification refusal")
            #expect(try harness.store().recentRuns(limit: 1).first?.detail == report.detail)
            #expect(harness.log.contains("synthetic notification refusal"))
        }
    }

    @Test func crashMidBackfillResumesInBackfillMode() async throws {
        try await withCollector { harness throws in
            harness.seedUsual()
            harness.seedSlowdown(count: 40)  // 09:00–09:39, then nothing: still open at 10:10
            let firstNow = harness.at(9, 4, 10)
            // Points run from the lookback start, Aug 5 10:00 (a 5-minute boundary), 288 to a chunk:
            // chunk 0 is Aug 5 10:00 through Aug 6 09:55.
            let chunk0End = harness.at(8, 5, 10).addingTimeInterval(287 * 300)
            #expect(chunk0End == harness.at(8, 6, 9, 55))

            let crashed = await harness.run(at: firstNow, hooks: RunHooks(afterChunkCommit: { index in
                if index == 0 { throw InjectedCrash() }
            }))

            #expect(crashed.outcome == .failed && crashed.exitCode == 1)
            #expect(crashed.detail == "synthetic crash after a committed chunk")
            #expect(try harness.store().lastEvaluatedPoint() == chunk0End)
            #expect(try harness.store().value(.backfillThrough) == firstNow)

            // The next run resumes at Aug 6 10:00. The slowdown fires at Sep 4 09:20, before
            // backfillThrough, so it stays quiet even though it is still open when this run ends:
            // a live fire in the gap would have sent a catch-up notice.
            let resumed = await harness.run(at: harness.at(9, 4, 10, 10))

            #expect(resumed.outcome == .succeeded && resumed.notificationsPosted == 0)
            #expect(await harness.notifier.posted.isEmpty)
            let store = try harness.store()
            #expect(try store.value(.backfillThrough) == firstNow)
            #expect(try store.lastEvaluatedPoint() == harness.at(9, 4, 10, 10))
            let episodes = try store.episodes(rule: RuleID.slower.rawValue)
            #expect(episodes.map(\.firedAt) == [harness.at(9, 4, 9, 20)])
            #expect(episodes.map(\.endedAt) == [nil])
            #expect(try store.recentRuns(limit: 5).map(\.outcome) == [.succeeded, .failed])
        }
    }

    @Test func runWritesStartAndFinishRecords() async throws {
        try await withCollector { harness throws in
            let now = harness.at(9, 4, 10)
            let database = harness.paths.database
            let duringRun = Locked<[CollectorRunRecord]>([])
            harness.source.setOnIngest {
                let runs = (try? Store.open(database, mode: .readOnly).recentRuns(limit: 5)) ?? []
                duringRun.set(runs)
            }

            let report = await harness.run(at: now)

            #expect(report == RunReport(outcome: .succeeded, exitCode: 0, detail: "", notificationsPosted: 0))
            let during = duringRun.value
            #expect(during.map(\.outcome) == [.running])
            #expect(during.first?.startedAt == now && during.first?.finishedAt == nil)
            let runs = try harness.store().recentRuns(limit: 5)
            #expect(runs.count == 1)
            let record = try #require(runs.first)
            #expect(record.id == during.first?.id && record.outcome == .succeeded && record.startedAt == now)
            #expect(try #require(record.finishedAt) >= now)
            #expect(harness.log.contains("succeeded"))
        }
    }

    @Test func invalidStoredRulesFallBackToDefaults() async throws {
        try await withCollector { harness throws in
            var rules = RuleSettings.defaults
            rules.slower.threshold = 1.5  // invalid; would never fire on a 25% slowdown
            try harness.store().set(.rules, rules)
            harness.seedUsual()
            harness.seedSlowdown()

            let report = await harness.run(at: harness.at(9, 4, 10))

            let error = Copy.invalidRuleParameter(field: "Slower than usual threshold")
            #expect(report.outcome == .succeeded)
            #expect(report.detail.contains(error))
            #expect(harness.log.contains(error))
            // Evaluated with the defaults: the slowdown fired.
            #expect(try harness.store().episodes(rule: RuleID.slower.rawValue).count == 1)
            #expect(try harness.store().value(.rules) == rules)  // the stored value is left alone
        }
    }
}

/// A value shared with a `@Sendable` closure.
final class Locked<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: Value
    init(_ value: Value) { stored = value }
    var value: Value { lock.withLock { stored } }
    func set(_ value: Value) { lock.withLock { stored = value } }
}

// MARK: - Fix round 1 (R19, R20, undecodable rules, source-state reads)

extension CollectorRunTests {
    /// R19: a source whose ingest throws leaves evaluation, selection and notification for the
    /// next run, so no point is written without its data. A trigger makes the store refuse that
    /// source's responses.
    @Test func ingestFailureSkipsEvaluationAndRetriesNextRun() async throws {
        try await withCollector { harness throws in
            let url = harness.paths.database
            _ = try harness.store()  // create and migrate
            try RawSQLite.rows(url, """
                CREATE TRIGGER synthetic_refusal BEFORE INSERT ON responses WHEN NEW.provider = 'example.broken'
                BEGIN SELECT RAISE(ABORT, 'synthetic write refusal'); END
                """)
            let broken = FakeUsageSource(provider: ProviderID(rawValue: "example.broken"), displayName: "Broken")
            var brokenSynth = Synth(provider: broken.provider, firstNumber: 900)
            broken.add(brokenSynth.responses(3, throughput: 40, from: harness.at(9, 4, 9)))
            harness.seedUsual()
            harness.seedSlowdown()
            let firstNow = harness.at(9, 4, 10)

            let failed = await harness.run(at: firstNow, sources: [broken, harness.source])

            #expect(failed.outcome == .failed && failed.exitCode == 1)
            #expect(failed.detail.contains("synthetic write refusal"))
            let store = try harness.store()
            #expect(try store.lastEvaluatedPoint() == nil)
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM eval_points") == "0")
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM episodes") == "0")
            // The other source's ingest still landed; the broken one's cursor didn't advance.
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM responses WHERE provider = 'codex'") == "90")
            #expect(try store.cursor("example.broken") == nil)
            #expect(harness.log.contains("Evaluation skipped"))

            // Fixed: the next run ingests the broken source again and evaluates every point.
            try RawSQLite.rows(url, "DROP TRIGGER synthetic_refusal")
            let resumed = await harness.run(at: harness.at(9, 4, 10, 5), sources: [broken, harness.source])

            #expect(resumed.outcome == .succeeded)
            #expect(try store.lastEvaluatedPoint() == harness.at(9, 4, 10, 5))
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM responses WHERE provider = 'example.broken'") == "3")
            #expect(try store.episodes(rule: RuleID.slower.rawValue).map(\.firedAt) == [harness.at(9, 4, 9, 20)])
            // Points through Sep 4 10:00 are still backfill: the run that set it failed, not the replay.
            #expect(try store.value(.backfillThrough) == firstNow)
            #expect(await harness.notifier.posted.isEmpty)
        }
    }

    /// A source reporting a problem through its state isn't a thrown error: evaluation goes on.
    @Test func reportedSourceProblemStillEvaluates() async throws {
        try await withCollector { harness throws in
            harness.source.setState(.notSetUp("synthetic: not set up"))
            harness.seedUsual()
            harness.seedSlowdown()
            let now = harness.at(9, 4, 10)

            #expect(await harness.run(at: now).outcome == .succeeded)
            #expect(try harness.store().lastEvaluatedPoint() == now)
            #expect(try harness.store().episodes(rule: RuleID.slower.rawValue).count == 1)
        }
    }

    /// An unreadable stored source state is read with `try`, so it fails the ingest (and the run)
    /// instead of silently dropping the recorded version and problem start.
    @Test func unreadableSourceStateFailsTheIngest() async throws {
        try await withCollector { harness throws in
            let url = harness.paths.database
            _ = try harness.store()
            try RawSQLite.rows(url, "INSERT INTO source_state (source, state_json, updated_at) VALUES ('codex', 'not json', 0)")

            let report = await harness.run(at: harness.at(9, 4, 10))

            #expect(report.outcome == .failed)
            #expect(report.detail == "Unreadable setup state for source codex")
            #expect(try harness.store().lastEvaluatedPoint() == nil)
        }
    }

    /// R20: a lock failure other than "held" still leaves a failed run record.
    @Test func lockFailureIsRecorded() async throws {
        try await withCollector { harness throws in
            // A directory where the lock file belongs: open(2) fails with EISDIR.
            try FileManager.default.createDirectory(at: harness.paths.lock, withIntermediateDirectories: true)
            let now = harness.at(9, 4, 10)

            let report = await harness.run(at: now)

            #expect(report.outcome == .failed && report.exitCode == 1)
            #expect(report.detail.hasPrefix("Couldn't open the collector lock"))
            let runs = try harness.store().recentRuns(limit: 5)
            #expect(runs.map(\.outcome) == [.failed])
            #expect(runs.first?.detail == report.detail && runs.first?.startedAt == now && runs.first?.finishedAt == now)
            #expect(harness.source.cursorsSeen.isEmpty)
        }
    }

    /// R20: `running` rows a killed process left are closed by the next lock holder.
    @Test func interruptedRunsAreClosed() async throws {
        try await withCollector { harness throws in
            let killed = try harness.store().beginRun(at: harness.at(9, 4, 9, 55))
            let now = harness.at(9, 4, 10)

            #expect(await harness.run(at: now).outcome == .succeeded)

            let runs = try harness.store().recentRuns(limit: 5)
            #expect(runs.map(\.outcome) == [.succeeded, .failed])
            let closed = try #require(runs.first { $0.id == killed })
            #expect(closed.detail == CollectorRun.interruptedDetail && closed.detail == "interrupted")
            #expect(closed.finishedAt == now)
        }
    }

    /// R16 also covers stored rules that no longer decode (`Store.value` would quietly return the
    /// defaults).
    @Test func undecodableStoredRulesAreNoted() async throws {
        try await withCollector { harness throws in
            _ = try harness.store()
            try RawSQLite.rows(harness.paths.database, #"INSERT INTO settings (key, value_json) VALUES ('rules', '{"slower": 1}')"#)
            harness.seedUsual()
            harness.seedSlowdown()

            let report = await harness.run(at: harness.at(9, 4, 10))

            let note = "Rule settings are invalid, so this run used the defaults: The stored rules couldn't be read."
            #expect(report.outcome == .succeeded)
            #expect(report.detail == note)
            #expect(harness.log.contains(note))
            #expect(try harness.store().episodes(rule: RuleID.slower.rawValue).count == 1)  // defaults evaluated
        }
    }
}
