import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

// MARK: - Fakes

/// A usage source that hands out the responses added to it, each once: those ending after the
/// previous run's `now` (its cursor) and at or before this run's. Its other output is set per test.
final class FakeUsageSource: UsageSource, @unchecked Sendable {
    var dataFolder: URL { URL(fileURLWithPath: "/tmp/telltale-synthetic") }
    let provider: ProviderID
    let displayName: String
    let statusSourceID: String
    let signals: Set<Signal> = [.speed, .errors, .link, .provider, .load]
    let failureNoun: String
    let supportedRules: Set<RuleID>
    private let naming = SyntheticNaming()
    private let lock = NSLock()
    private var pending: [ResponseRecord] = []
    private var nextBatch = IngestBatch()
    private var nextState = SetupState.ready
    private var onIngest: (@Sendable () -> Void)?
    private var calls: [(cursor: Data?, backfillFrom: Date, now: Date)] = []

    init(provider: ProviderID = .codex, displayName: String = "Example", statusSourceID: String = RuleHarness.sourceID,
         failureNoun: String = "turn", supportedRules: Set<RuleID> = Set(RuleID.allCases)) {
        self.provider = provider
        self.displayName = displayName
        self.statusSourceID = statusSourceID
        self.failureNoun = failureNoun
        self.supportedRules = supportedRules
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
                response.end <= now && (after.map { response.end > $0 } ?? true)
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
    let defaultWatchedComponents = ["CLI"]
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
    @Test func readProblemKeepsItsSinceAcrossRuns() async throws {
        try await withCollector { h throws in
            let first = h.at(9, 4, 10)
            h.source.setState(.readProblem("synthetic one"))
            _ = await h.run(at: first)
            h.source.setState(.readProblem("synthetic two"))
            _ = await h.run(at: h.at(9, 4, 10, 5))
            #expect(try h.store().sourceState("codex")?.unavailableSince == first)
        }
    }
    @Test func movingFromFormatToReadProblemRestartsSince() async throws {
        try await withCollector { h throws in
            h.source.setState(.formatProblem("synthetic"))
            _ = await h.run(at: h.at(9, 4, 10))
            let changed = h.at(9, 4, 10, 5)
            h.source.setState(.readProblem("synthetic"))
            _ = await h.run(at: changed)
            #expect(try h.store().sourceState("codex")?.unavailableSince == changed)
        }
    }

    @Test func notificationLogCountsEachProviderSeparately() async throws {
        try await withCollector { h in
            let other = FakeUsageSource(provider: ProviderID(rawValue: "synthetic-other"), displayName: "Synthetic Other")
            let start = h.at(9, 4, 9)
            #expect(await h.run(at: start, sources: [h.source, other]).outcome == .succeeded)
            let now = start.addingTimeInterval(300)
            for source in [h.source, other] {
                source.setNextBatch(IngestBatch(failedTurns: [FailedTurnRecord(provider: source.provider,
                    threadID: "thread_synthetic_\(source.provider.rawValue)", turnID: "turn_synthetic_\(source.provider.rawValue)",
                    startedAt: now.addingTimeInterval(-60), completedAt: now.addingTimeInterval(-60),
                    errorCode: "serverOverloaded", message: "Synthetic failure")]))
            }
            let report = await h.run(at: now, sources: [h.source, other])
            #expect(report.notificationsPosted == 2)
            #expect(h.log.components(separatedBy: "Posted 1 of 1 notifications").count - 1 == 2)
            #expect(!h.log.contains("Posted 2 of 1 notifications"))
        }
    }
    @Test func olderDeferredUsageLimitDoesNotReplaceNewerSnapshot() async throws {
        try await withCollector { h in
            let now = h.at(9, 4, 9)
            let newer = UsageLimitSnapshot(provider: .codex, at: now, usedPercent: 100, windowMinutes: 300)
            let older = UsageLimitSnapshot(provider: .codex, at: now.addingTimeInterval(-60), usedPercent: 100, windowMinutes: 10080)
            h.source.setNextBatch(IngestBatch(usageLimit: newer))
            #expect(await h.run(at: now).outcome == .succeeded)
            h.source.setNextBatch(IngestBatch(usageLimit: older))
            #expect(await h.run(at: now.addingTimeInterval(300)).outcome == .succeeded)
            let store = try h.store()
            #expect(try store.usageLimit(provider: .codex) == newer)
        }
    }
    @Test func ingestStoresCompactions() async throws {
        try await withCollector { h in
            let at = h.at(9, 4, 9)
            let record = CompactionRecord(provider: .codex, lineID: "synthetic-line", sessionID: "synthetic-session", agentID: "synthetic-agent",
                at: at, trigger: .auto, tokensBefore: 100, tokensAfter: 10, duration: 12, precomputed: true)
            h.source.setNextBatch(IngestBatch(compactions: [record, record]))
            #expect(await h.run(at: at).outcome == .succeeded)
            let store = try h.store()
            #expect(try store.compactions(provider: .codex, in: at...at) == [record])
        }
    }
    @Test func newlyRegisteredStatusDefaultsApplyOnlyOnce() async throws {
        try await withCollector { h in
            #expect(await h.run(at: h.at(9, 4, 9)).outcome == .succeeded)
            let store = try h.store()
            try store.set(.watchedComponents, ["Synthetic custom"])
            h.statusSources = [FakeStatusSource()]
            _ = await h.run(at: h.at(9, 4, 9, 5))
            #expect(try store.value(.watchedComponents) == ["Synthetic custom", "CLI"])
            try store.set(.watchedComponents, ["Synthetic custom"])
            _ = await h.run(at: h.at(9, 4, 9, 10))
            #expect(try store.value(.watchedComponents) == ["Synthetic custom"])
        }
    }
    @Test func providerRebuildLeavesOtherUnitsUntouched() async throws {
        try await withCollector { rebuilt in
            try await withCollector { control in
                let id = ProviderID(rawValue: "synthetic-other")
                let other = FakeUsageSource(provider: id, displayName: "Synthetic Other")
                let controlOther = FakeUsageSource(provider: id, displayName: "Synthetic Other")
                let start = rebuilt.at(9, 4, 9)
                #expect(await rebuilt.run(at: start, sources: [rebuilt.source, other]).outcome == .succeeded)
                #expect(await control.run(at: start, sources: [control.source, controlOther]).outcome == .succeeded)
                for provider in [ProviderID.codex, id] {
                    let record = CompactionRecord(provider: provider, lineID: "synthetic", sessionID: "synthetic", agentID: nil,
                        at: start, trigger: .auto, tokensBefore: 100, tokensAfter: nil, duration: nil, precomputed: false)
                    try rebuilt.store().upsert(compactions: [record])
                    try control.store().upsert(compactions: [record])
                }
                try rebuilt.store().set(.providerRebuildRequests, ["synthetic-other": start])
                let next = start.addingTimeInterval(300)
                let liveFailure = FailedTurnRecord(provider: .codex, threadID: "thread_synthetic_live", turnID: "turn_synthetic_live",
                    startedAt: next.addingTimeInterval(-60), completedAt: next.addingTimeInterval(-60),
                    errorCode: "serverOverloaded", message: "Synthetic failure")
                rebuilt.source.setNextBatch(IngestBatch(failedTurns: [liveFailure]))
                control.source.setNextBatch(IngestBatch(failedTurns: [liveFailure]))
                #expect(await rebuilt.run(at: next, sources: [rebuilt.source, other]).outcome == .succeeded)
                #expect(await control.run(at: next, sources: [control.source, controlOther]).outcome == .succeeded)
                #expect(try rebuilt.store().compactions(provider: id, in: start...next).isEmpty)
                #expect(try rebuilt.store().compactions(provider: .codex, in: start...next).count == 1)
                for table in ["responses", "eval_points", "episodes", "rule_state"] {
                    #expect(try RawSQLite.rows(rebuilt.paths.database, "SELECT * FROM \(table) WHERE provider = 'codex' ORDER BY rowid") == RawSQLite.rows(control.paths.database, "SELECT * FROM \(table) WHERE provider = 'codex' ORDER BY rowid"))
                }
                #expect(try rebuilt.store().lastEvaluatedPoint(unit: "codex") == next)
                #expect(await rebuilt.notifier.posted.map(\.threadID) == control.notifier.posted.map(\.threadID))
                #expect(await rebuilt.notifier.posted.map(\.threadID) == [NotificationPolicy.failedTurnsThreadID(provider: .codex)])
                #expect(try rebuilt.store().backfill(unit: id.rawValue)?.reason == .rebuild)
            }
        }
    }
    @Test func providerAddedWrittenOnceAndSurvivesRebuild() async throws {
        try await withCollector { h in
            let other = FakeUsageSource(provider: ProviderID(rawValue: "synthetic-other"), displayName: "Synthetic Other")
            let start = h.at(9, 4, 9)
            #expect(await h.run(at: start).outcome == .succeeded)
            #expect(await h.run(at: start.addingTimeInterval(300), sources: [h.source, other]).outcome == .succeeded)
            let store = try h.store()
            #expect(try store.value(.pendingArrivals) == ["synthetic-other"])
            #expect(try EventFeed.load(store: store, limit: 100).filter { $0.body.contains("now watches Synthetic Other") }.count == 1)
            try store.set(.providerRebuildRequests, ["synthetic-other": start])
            #expect(await h.run(at: start.addingTimeInterval(600), sources: [h.source, other]).outcome == .succeeded)
            #expect(try store.value(.pendingArrivals) == ["synthetic-other"])
            #expect(try store.value(.providerRebuildRequests).isEmpty)
            #expect(try store.backfill(unit: "synthetic-other")?.reason == .rebuild)
            #expect(other.cursorsSeen.count == 2 && other.cursorsSeen.last! == nil)
            #expect(try EventFeed.load(store: store, limit: 100).filter { $0.body.contains("now watches Synthetic Other") }.count == 1)
            #expect(try EventFeed.load(store: store, limit: 100).filter { $0.body.contains("Synthetic Other history rebuilt") }.count == 1)
            let reloaded = try h.store()
            #expect(try reloaded.value(.pendingArrivals) == ["synthetic-other"])
        }
    }

    @Test func globalRebuildConsumesProviderRequests() async throws {
        try await withCollector { h in
            let other = FakeUsageSource(provider: ProviderID(rawValue: "synthetic-other"), displayName: "Synthetic Other")
            let start = h.at(9, 4, 9)
            #expect(await h.run(at: start, sources: [h.source, other]).outcome == .succeeded)
            let store = try h.store()
            try store.upsert(compactions: [.codex, other.provider].map {
                CompactionRecord(provider: $0, lineID: "synthetic", sessionID: "synthetic", agentID: nil,
                    at: start, trigger: .auto, tokensBefore: 100, tokensAfter: nil, duration: nil, precomputed: false)
            })
            try store.set(.rebuildRequestedAt, start)
            try store.set(.providerRebuildRequests, ["synthetic-other": start])
            #expect(await h.run(at: start.addingTimeInterval(300), sources: [h.source, other]).outcome == .succeeded)
            #expect(try store.compactions(provider: .codex, in: start...start.addingTimeInterval(300)).isEmpty)
            #expect(try store.compactions(provider: other.provider, in: start...start.addingTimeInterval(300)).isEmpty)
            #expect(try store.value(.providerRebuildRequests).isEmpty)
            #expect(try store.backfill(unit: "codex")?.reason == .rebuild)
            #expect(try store.backfill(unit: "synthetic-other")?.reason == .rebuild)
            #expect(try EventFeed.load(store: store, limit: 100).filter { $0.body.contains("history rebuilt") }.count == 2)
        }
    }

    @Test func rebuildDuringOtherBackfillKeepsBothCorrect() async throws {
        try await withCollector { h in
            let other = FakeUsageSource(provider: ProviderID(rawValue: "synthetic-other"), displayName: "Synthetic Other")
            let start = h.at(9, 4, 9)
            #expect(await h.run(at: start).outcome == .succeeded)
            let second = start.addingTimeInterval(300)
            let callbacks = Locked(0)
            let interrupted = await h.run(at: second, sources: [h.source, other], hooks: RunHooks(afterChunkCommit: { _ in
                let count = callbacks.value
                callbacks.set(count + 1)
                if count == 1 { throw InjectedCrash() }
            }))
            #expect(interrupted.outcome == .failed)
            let store = try h.store()
            #expect(try store.backfill(unit: other.provider.rawValue)?.finishedAt == nil)
            try store.set(.providerRebuildRequests, ["codex": second])
            let next = second.addingTimeInterval(300)
            #expect(await h.run(at: next, sources: [h.source, other]).outcome == .succeeded)
            #expect(try store.backfill(unit: "codex")?.reason == .rebuild)
            #expect(try store.backfill(unit: other.provider.rawValue)?.reason == .new)
            #expect(try store.backfill(unit: other.provider.rawValue)?.finishedAt == next)
            #expect(try store.value(.pendingArrivals) == [other.provider.rawValue])
            #expect(await h.notifier.posted.isEmpty)
        }
    }
    @Test func statusSourceWaitsWhenAllAssociatedIngestsFailAndResumesWhenOneSucceeds() async throws {
        try await withCollector { h in
            let status = FakeStatusSource()
            h.statusSources = [status]
            let other = FakeUsageSource(provider: ProviderID(rawValue: "synthetic-other"), displayName: "Synthetic Other")
            let start = h.at(9, 4, 9)
            let published = start.addingTimeInterval(-300)
            let component = StatusComponent(id: "comp_cli", name: "CLI")
            let open = IncidentRecord(source: status.id, id: "inc_synthetic_01", name: "Synthetic outage",
                status: "investigating", publishedAt: published, updatedAt: published,
                link: URL(string: "https://status.example.com/incidents/inc_synthetic_01")!,
                history: [StatusChange(at: published, status: "investigating")],
                impacts: [ComponentImpact(componentID: component.id, status: "degraded_performance", start: published)])
            status.setAnswer(.success(.full(components: [component], incidents: [open])))
            #expect(await h.run(at: start, sources: [h.source, other]).outcome == .succeeded)
            let store = try h.store()
            let before = try store.episodes(rule: RuleID.incident.rawValue)
            #expect(before.count == 1 && before[0].endedAt == nil)
            let states = try store.ruleStates(rule: RuleID.incident.rawValue, unit: status.id).map(\.json)
            var resolved = open
            let resolvedAt = start.addingTimeInterval(120)
            resolved.status = "resolved"
            resolved.updatedAt = resolvedAt
            resolved.history.append(StatusChange(at: resolvedAt, status: "resolved"))
            status.setAnswer(.success(.full(components: [component], incidents: [resolved])))
            var codexSynth = Synth()
            var otherSynth = Synth(provider: other.provider)
            h.source.add(codexSynth.responses(1, throughput: 40, from: start.addingTimeInterval(60)))
            other.add(otherSynth.responses(1, throughput: 40, from: start.addingTimeInterval(60)))
            try store.exec("""
                CREATE TRIGGER synthetic_refusal BEFORE INSERT ON responses
                BEGIN SELECT RAISE(ABORT, 'synthetic ingest refusal'); END
                """)
            let failedAt = start.addingTimeInterval(300)
            #expect(await h.run(at: failedAt, sources: [h.source, other]).outcome == .failed)
            #expect(try store.lastEvaluatedPoint(unit: status.id) == start)
            #expect(try store.episodes(rule: RuleID.incident.rawValue) == before)
            #expect(try store.ruleStates(rule: RuleID.incident.rawValue, unit: status.id).map(\.json) == states)

            // A shared status source resumes when one associated ingest succeeds.
            try store.exec("DROP TRIGGER synthetic_refusal")
            try store.exec("""
                CREATE TRIGGER synthetic_refusal BEFORE INSERT ON responses WHEN NEW.provider = 'synthetic-other'
                BEGIN SELECT RAISE(ABORT, 'synthetic ingest refusal'); END
                """)
            let partialAt = start.addingTimeInterval(600)
            #expect(await h.run(at: partialAt, sources: [h.source, other]).outcome == .failed)
            #expect(try store.lastEvaluatedPoint(unit: status.id) == partialAt)
            #expect(try store.episodes(rule: RuleID.incident.rawValue).first?.endedAt == failedAt)
            #expect(await h.notifier.posted.map(\.body) == [Copy.incidentCleared(source: status.displayName, name: open.name)])
            try store.exec("DROP TRIGGER synthetic_refusal")
            let retryAt = start.addingTimeInterval(900)
            #expect(await h.run(at: retryAt, sources: [h.source, other]).outcome == .succeeded)
            #expect(try store.lastEvaluatedPoint(unit: status.id) == retryAt)
            #expect(try store.lastEvaluatedPoint(unit: other.provider.rawValue) == retryAt)
        }
    }

    @Test func liveProviderNotifiesWhileAnotherBackfillIsInterruptedAndResumed() async throws {
        try await withCollector { h in
            let start = h.at(9, 4, 9)
            #expect(await h.run(at: start).outcome == .succeeded)
            let now = start.addingTimeInterval(300)
            let other = FakeUsageSource(provider: ProviderID(rawValue: "synthetic-other"), displayName: "Synthetic Other")
            h.source.setNextBatch(IngestBatch(failedTurns: [FailedTurnRecord(provider: .codex,
                threadID: "thread_synthetic_live", turnID: "turn_synthetic_live", startedAt: now.addingTimeInterval(-60),
                completedAt: now.addingTimeInterval(-60), errorCode: "serverOverloaded", message: "Synthetic failure")]))
            let historical = now.addingTimeInterval(-29 * 86_400 - 23 * 3_600)
            other.setNextBatch(IngestBatch(failedTurns: [FailedTurnRecord(provider: other.provider,
                threadID: "thread_synthetic_history", turnID: "turn_synthetic_history", startedAt: historical,
                completedAt: historical, errorCode: "serverOverloaded", message: "Synthetic failure")]))
            let callbacks = Locked(0)
            let interrupted = await h.run(at: now, sources: [h.source, other], hooks: RunHooks(afterChunkCommit: { _ in
                let count = callbacks.value
                callbacks.set(count + 1)
                if count == 1 { throw InjectedCrash() }
            }))
            #expect(interrupted.outcome == .failed)
            let store = try h.store()
            #expect(try store.lastEvaluatedPoint(unit: "codex") == now)
            #expect(try store.lastEvaluatedPoint(unit: other.provider.rawValue) != nil)
            #expect(try store.backfill(unit: other.provider.rawValue)?.finishedAt == nil)
            #expect(try store.episodes(rule: RuleID.failedTurns.rawValue).contains { $0.provider == other.provider.rawValue })
            #expect(await h.notifier.posted.map(\.threadID) == [NotificationPolicy.failedTurnsThreadID(provider: .codex)])

            let retryAt = now.addingTimeInterval(300)
            #expect(await h.run(at: retryAt, sources: [h.source, other]).outcome == .succeeded)
            #expect(try store.lastEvaluatedPoint(unit: other.provider.rawValue) == retryAt)
            #expect(try store.backfill(unit: other.provider.rawValue)?.finishedAt == retryAt)
            #expect(await h.notifier.posted.map(\.threadID) == [NotificationPolicy.failedTurnsThreadID(provider: .codex)])
        }
    }
    @Test func newProviderBackfillsQuietlyWhileOtherStaysLive() async throws {
        try await withCollector { h in
            let other = FakeUsageSource(provider: ProviderID(rawValue: "synthetic-other"), displayName: "Synthetic Other")
            let first = h.at(9, 4, 10)
            #expect(await h.run(at: first).outcome == .succeeded)
            let second = first.addingTimeInterval(310)
            #expect(await h.run(at: second, sources: [h.source, other]).outcome == .succeeded)
            let store = try h.store()
            #expect(try store.lastEvaluatedPoint(unit: "codex") == first.addingTimeInterval(300))
            let backfill = try #require(try store.backfill(unit: "synthetic-other"))
            #expect(backfill.reason == .new && backfill.announce && backfill.through == second)
            #expect(backfill.finishedAt == second)
            #expect(await h.notifier.posted.isEmpty)
        }
    }

    @Test func freshDatabaseBackfillsBothWithoutAnnouncing() async throws {
        try await withCollector { h in
            let other = FakeUsageSource(provider: ProviderID(rawValue: "synthetic-other"), displayName: "Synthetic Other")
            let now = h.at(9, 4, 10)
            #expect(await h.run(at: now, sources: [h.source, other]).outcome == .succeeded)
            let store = try h.store()
            #expect(try store.backfill(unit: "codex")?.announce == false)
            #expect(try store.backfill(unit: "synthetic-other")?.announce == false)
        }
    }

    @Test func newStatusSourceBackfillsQuietlyOnUpgrade() async throws {
        try await withCollector { h in
            let old = h.at(9, 4, 9)
            let now = h.at(9, 4, 10)
            let store = try h.store()
            try store.setLastEvaluatedPoint(old)
            try store.setCursor("codex", FakeUsageSource.cursor(old))
            try store.set(.backfillThrough, old)
            h.statusSources = [FakeStatusSource()]
            #expect(await h.run(at: now).outcome == .succeeded)
            #expect(try store.lastEvaluatedPoint(unit: "openai") == old)
            #expect(try store.lastEvaluatedPoint(unit: "codex") == now)
            #expect(try store.lastEvaluatedPoint(unit: RuleHarness.sourceID) == now)
            #expect(try store.backfill(unit: RuleHarness.sourceID)?.announce == false)
            #expect(try store.backfill(unit: RuleHarness.sourceID)?.finishedAt == now)
        }
    }

    @Test func alertNamesItsProviderOnce() async throws {
        try await withCollector { h in
            let now = h.at(9, 4, 10)
            let source = FakeUsageSource(displayName: "Synthetic Provider", failureNoun: "request")
            let store = try h.store()
            try store.setLastEvaluatedPoint(now.addingTimeInterval(-300), unit: "codex")
            source.setNextBatch(IngestBatch(failedTurns: [FailedTurnRecord(provider: .codex,
                threadID: "thread_synthetic_01", turnID: "turn_synthetic_01", startedAt: now.addingTimeInterval(-60),
                completedAt: now.addingTimeInterval(-60), errorCode: "overloaded", message: "Synthetic failure")]))
            #expect(await h.run(at: now, sources: [source]).outcome == .succeeded)
            #expect(await h.notifier.posted.map(\.body) == ["Synthetic Provider: 1 request failed: model overloaded"])
        }
    }

    @Test func sourceRuleOverridesDispatchThroughExistential() async throws {
        try await withCollector { h in
            let now = h.at(9, 4, 10)
            let source = FakeUsageSource(supportedRules: [])
            let store = try h.store()
            try store.setLastEvaluatedPoint(now.addingTimeInterval(-300), unit: "codex")
            source.setNextBatch(IngestBatch(failedTurns: [FailedTurnRecord(provider: .codex,
                threadID: "thread_synthetic_02", turnID: "turn_synthetic_02", startedAt: now.addingTimeInterval(-60),
                completedAt: now.addingTimeInterval(-60), errorCode: "overloaded", message: "Synthetic failure")]))
            #expect(await h.run(at: now, sources: [source]).outcome == .succeeded)
            #expect(try store.episodes(rule: RuleID.failedTurns.rawValue).isEmpty)
            #expect(await h.notifier.posted.isEmpty)
        }
    }

    @Test func upgradeFrom011KeepsCodexLive() async throws {
        try await withCollector { h in
            let old = h.at(9, 4, 9)
            let now = h.at(9, 4, 10)
            let store = try h.store()
            try store.setLastEvaluatedPoint(old)
            try store.setCursor("codex", FakeUsageSource.cursor(old))
            try store.set(.backfillThrough, old)
            let other = FakeUsageSource(provider: ProviderID(rawValue: "synthetic-other"), displayName: "Synthetic Other")
            h.source.setNextBatch(IngestBatch(failedTurns: [FailedTurnRecord(provider: .codex,
                threadID: "thread_synthetic_live", turnID: "turn_synthetic_live", startedAt: now.addingTimeInterval(-60),
                completedAt: now.addingTimeInterval(-60), errorCode: "serverOverloaded", message: "Synthetic failure")]))
            other.setNextBatch(IngestBatch(failedTurns: [FailedTurnRecord(provider: other.provider,
                threadID: "thread_synthetic_old", turnID: "turn_synthetic_old", startedAt: old,
                completedAt: old, errorCode: "serverOverloaded", message: "Synthetic failure")]))
            #expect(await h.run(at: now, sources: [h.source, other]).outcome == .succeeded)
            let notices = await h.notifier.posted
            #expect(notices.count == 1)
            #expect(notices.first?.threadID == NotificationPolicy.failedTurnsThreadID(provider: .codex))
            #expect(try store.backfill(unit: other.provider.rawValue)?.announce == true)
            #expect(try store.episodes(rule: RuleID.failedTurns.rawValue).count == 2)
        }
    }

    @Test func emptyEligibleBackfillFinishes() async throws {
        try await withCollector { h in
            let point = h.at(9, 4, 10)
            let through = point.addingTimeInterval(10)
            let store = try h.store()
            try store.setLastEvaluatedPoint(point, unit: "codex")
            try store.setBackfill(ProviderBackfill(reason: .new, startedAt: through, through: through,
                finishedAt: nil, announce: false), unit: "codex")
            #expect(await h.run(at: through).outcome == .succeeded)
            #expect(try store.backfill(unit: "codex")?.finishedAt == through)
            #expect(try store.lastEvaluatedPoint(unit: "codex") == point)
        }
    }

    @Test func failedBackfillPreparationDoesNotEvaluateHistoryLive() async throws {
        try await withCollector { h in
            let store = try h.store()
            try store.exec("""
                CREATE TRIGGER synthetic_backfill_refusal BEFORE INSERT ON rule_state
                WHEN NEW.provider = 'codex' AND NEW.rule = 'engine' AND NEW.scope = 'backfill'
                BEGIN SELECT RAISE(ABORT, 'synthetic backfill refusal'); END
                """)
            let now = h.at(9, 4, 10)
            h.source.setNextBatch(IngestBatch(failedTurns: [FailedTurnRecord(provider: .codex,
                threadID: "thread_synthetic_history", turnID: "turn_synthetic_history", startedAt: now,
                completedAt: now, errorCode: "serverOverloaded", message: "Synthetic failure")]))
            #expect(await h.run(at: now).outcome == .failed)
            #expect(try store.lastEvaluatedPoint(unit: "codex") == nil)
            #expect(try store.episodes(rule: RuleID.failedTurns.rawValue).isEmpty)
            #expect(await h.notifier.posted.isEmpty)
        }
    }

    @Test func ingestFailureSkipsOnlyThatProvider() async throws {
        try await withCollector { h in
            let store = try h.store()
            let old = h.at(9, 4, 9, 50)
            let now = h.at(9, 4, 10)
            let broken = FakeUsageSource(provider: ProviderID(rawValue: "synthetic-broken"), displayName: "Synthetic Broken")
            for key in ["codex", broken.provider.rawValue] {
                try store.setLastEvaluatedPoint(old, unit: key)
                try store.setCursor(key, FakeUsageSource.cursor(old))
            }
            try store.exec("""
                CREATE TRIGGER synthetic_ingest_refusal BEFORE INSERT ON responses
                WHEN NEW.provider = 'synthetic-broken'
                BEGIN SELECT RAISE(ABORT, 'synthetic ingest refusal'); END
                """)
            var synth = Synth(provider: broken.provider)
            broken.add(synth.responses(1, throughput: 40, from: h.at(9, 4, 9, 55)))
            h.source.setNextBatch(IngestBatch(failedTurns: [FailedTurnRecord(provider: .codex,
                threadID: "thread_synthetic_live", turnID: "turn_synthetic_live", startedAt: now.addingTimeInterval(-60),
                completedAt: now.addingTimeInterval(-60), errorCode: "serverOverloaded", message: "Synthetic failure")]))
            #expect(await h.run(at: now, sources: [h.source, broken]).outcome == .failed)
            #expect(try store.lastEvaluatedPoint(unit: broken.provider.rawValue) == old)
            #expect(try store.lastEvaluatedPoint(unit: "codex") == now)
            #expect(await h.notifier.posted.count == 1)
            try store.exec("DROP TRIGGER synthetic_ingest_refusal")
            #expect(await h.run(at: now.addingTimeInterval(300), sources: [h.source, broken]).outcome == .succeeded)
            #expect(try store.lastEvaluatedPoint(unit: broken.provider.rawValue) == now.addingTimeInterval(300))
        }
    }
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
            #expect(try store.backfill(unit: "codex")?.through == now)
            #expect(try store.lastEvaluatedPoint(unit: "codex") == now)
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
                id: "slower-\(episode)-fired", title: "🟠 Slower than usual",
                body: "Example: " + Copy.slowerFired(model: "Example", percent: 25, since: harness.at(9, 4, 8, 55), calendar: harness.calendar),
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

    /// The start of unavailability restarts when a source changes from one unavailable state to the
    /// other (a format problem is a different problem from not being set up), and keeps through
    /// repeats of the same state, whatever the text.
    @Test func notSetUpThenFormatProblemRestartsUnavailableSince() async throws {
        try await withCollector { harness throws in
            let (t1, t2, t3, t4) = (harness.at(9, 4, 10), harness.at(9, 4, 10, 5), harness.at(9, 4, 10, 10), harness.at(9, 4, 10, 15))
            harness.source.setState(.notSetUp("synthetic: not set up"))
            _ = await harness.run(at: t1)
            #expect(try harness.store().sourceState("codex")?.unavailableSince == t1)

            harness.source.setState(.formatProblem("synthetic format problem"))
            _ = await harness.run(at: t2)
            #expect(try harness.store().sourceState("codex")?.unavailableSince == t2)

            harness.source.setState(.formatProblem("synthetic different text"))
            _ = await harness.run(at: t3)
            #expect(try harness.store().sourceState("codex")?.unavailableSince == t2)

            harness.source.setState(.ready)
            _ = await harness.run(at: t4)
            #expect(try harness.store().sourceState("codex")?.unavailableSince == nil)
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

    @Test func linesFromBeforeTheLookbackAreNotStored() async throws {
        try await withCollector { h in
            let now = h.at(9, 4, 10)
            let old = now.addingTimeInterval(-31 * 86_400)
            let recent = now.addingTimeInterval(-3_600)
            let responses = [h.synth.response(throughput: 40, end: old), h.synth.response(throughput: 40, end: recent)]
            h.source.add(responses)
            let compactions = [old, recent].enumerated().map { index, at in
                CompactionRecord(provider: .codex, lineID: "synthetic-\(index)", sessionID: "synthetic", agentID: nil,
                                 at: at, trigger: .auto, tokensBefore: 100, tokensAfter: nil, duration: nil, precomputed: false)
            }
            let events = [old, recent].enumerated().map { index, at in
                ConnectionEventRecord(provider: .codex, sourceID: "synthetic-\(index)", at: at, kind: .retry, detail: "synthetic")
            }
            h.source.setNextBatch(IngestBatch(compactions: compactions, connectionEvents: events))
            #expect(await h.run(at: now).outcome == .succeeded)
            let store = try h.store()
            #expect(try store.responses(provider: .codex, model: Synth.model, endingIn: old...now) == [responses[1]])
            #expect(try store.compactions(provider: .codex, in: old...now) == [compactions[1]])
            #expect(try store.connectionEvents(provider: .codex, in: old...now) == [events[1]])
            let summary = SourceSummary(provider: .codex, name: "Example", statusName: "Example", statusSourceID: h.source.statusSourceID,
                                        signals: h.source.signals, naming: h.source)
            #expect(try ProviderSummary.load(store: store, sources: [summary]).first?.oldestResponse == recent)
            #expect(h.log.contains("Example: skipped 3 record(s) from before the lookback"))
        }
    }

    @Test func catchUpAfterTheLookbackKeepsOnlyRecentLines() async throws {
        try await withCollector { h throws in
            let first = h.at(9, 4, 10)
            #expect(await h.run(at: first).outcome == .succeeded)
            let now = first.addingTimeInterval(35 * 86_400)
            let old = now.addingTimeInterval(-33 * 86_400)
            let recent = now.addingTimeInterval(-86_400)
            let responses = [h.synth.response(throughput: 40, end: old), h.synth.response(throughput: 40, end: recent)]
            h.source.add(responses)
            #expect(await h.run(at: now).outcome == .succeeded)
            #expect(try h.store().responses(provider: .codex, model: Synth.model, endingIn: old...now) == [responses[1]])
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
                try store.setLastEvaluatedPoint(old, unit: "codex")
                try store.setFailureNotices(FailureNotices(lastNoticeAt: old), provider: .codex)
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
            // this run's), and failed_turns.evaluated_at. With the failed-turn rule on, the July turn, from
            // before the Aug 5 10:00 lookback start, is settled there uncounted: no episode above.
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM responses") == "0")
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM eval_points") == "0")
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM episodes") == "0")
            #expect(try RawSQLite.rows(url, "SELECT id, kind FROM events WHERE kind != 'historyRebuilt' ORDER BY id") == keptEvents)
            #expect(try RawSQLite.column(url, "SELECT kind FROM events WHERE kind = 'historyRebuilt'") == [EventKind.historyRebuilt])
            let ruleStates = try RawSQLite.column(url, "SELECT rule || '/' || scope FROM rule_state")
            #expect(ruleStates.sorted() == ["engine/backfill", "engine/lastPoint"])
            #expect(try store.lastEvaluatedPoint(unit: "codex") == now)
            #expect(try store.failureNotices(provider: .codex) == FailureNotices())
            #expect(try store.cursor("codex") == FakeUsageSource.cursor(now))
            #expect(try RawSQLite.rows(url, "SELECT turn_id, CAST(evaluated_at AS INTEGER) FROM failed_turns") == [["turn_synthetic_901", unix(harness.at(8, 5, 10))]])
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
            #expect(try store.backfill(unit: "codex")?.through == now)
        }
    }

    /// A failed turn on Sep 4 09:01–09:02, ingested by the next run.
    func recentFailure(_ harness: CollectorHarness) -> FailedTurnRecord {
        FailedTurnRecord(
            provider: .codex, threadID: "thread_synthetic_02", turnID: "turn_synthetic_902", startedAt: harness.at(9, 4, 9, 1),
            completedAt: harness.at(9, 4, 9, 2), errorCode: "serverOverloaded", message: "Synthetic failure 2")
    }

    /// The failed-turn episodes and their fired events, as (onset, worst value) and (time, body).
    func failedTurnHistory(_ harness: CollectorHarness) throws -> (episodes: [[String]], events: [[String]]) {
        let url = harness.paths.database
        return (
            try RawSQLite.rows(url, "SELECT CAST(onset_at AS INTEGER), worst_value FROM episodes WHERE rule = 'failedTurns' ORDER BY id"),
            try RawSQLite.rows(url, "SELECT CAST(at AS INTEGER), body FROM events WHERE kind = 'ruleFired' AND title = 'Failed turns' ORDER BY id"))
    }

    @Test func rebuildRecreatesFailedTurnDetails() async throws {
        try await withCollector { harness throws in
            let second = FailedTurnRecord(provider: .codex, threadID: "thread_synthetic_03", turnID: "turn_synthetic_903",
                startedAt: harness.at(9, 4, 9, 7), completedAt: harness.at(9, 4, 9, 8), errorCode: "timeout", message: "Synthetic failure 3")
            let failures = [recentFailure(harness), second]
            harness.source.setNextBatch(IngestBatch(failedTurns: failures))
            #expect(await harness.run(at: harness.at(9, 4, 9, 10)).outcome == .succeeded)
            let store = try harness.store()
            let original = try #require(try store.openEpisodes().first { $0.rule == RuleID.failedTurns.rawValue })
            let key = Acknowledgements.key(original)
            let ackAt = harness.at(9, 4, 9, 11)
            try store.acknowledge([PanelSnapshot.Alert(color: .red, text: "synthetic", key: key, failedTurns: 2)], at: ackAt)
            try store.set(.rebuildRequestedAt, harness.at(9, 4, 9, 12))
            harness.source.setNextBatch(IngestBatch(failedTurns: failures))
            #expect(await harness.run(at: harness.at(9, 4, 9, 15)).outcome == .succeeded)
            let episode = try #require(try harness.store().openEpisodes().first { $0.rule == RuleID.failedTurns.rawValue })
            let detail = try #require(try FailedTurnEpisodeDetail.decode(episode.detail))
            #expect(detail.priorCount == 0 && detail.failures.map(\.turnID) == ["turn_synthetic_902", "turn_synthetic_903"])
            #expect(Acknowledgements.key(episode) == key)
            let saved = try #require(try harness.store().value(.alertAcknowledgements)[Acknowledgements.key(episode)])
            #expect(saved.at == ackAt && Acknowledgements.holds(saved, severity: .red, failedTurns: 2))
        }
    }
    @Test func rebuildCountsOnlyFailedTurnsInsideTheLookback() async throws {
        try await withCollector { harness throws in
            let old = harness.at(7, 1, 12)
            do {
                let store = try harness.store()
                try store.upsert(failedTurns: [FailedTurnRecord(
                    provider: .codex, threadID: "thread_synthetic_01", turnID: "turn_synthetic_901", startedAt: old,
                    completedAt: old, errorCode: "serverOverloaded", message: "Synthetic failure 1")])
                try store.markEvaluated(try store.unevaluatedFailedTurns(through: old), at: old)
                try store.setLastEvaluatedPoint(old, unit: "codex")
                try store.set(.rebuildRequestedAt, harness.at(9, 4, 9, 55))
            }
            harness.source.setNextBatch(IngestBatch(failedTurns: [recentFailure(harness)]))

            #expect(await harness.run(at: harness.at(9, 4, 10)).outcome == .succeeded)

            // Only the Sep 4 failure is counted, at 09:05. The July one, from before the Aug 5 10:00
            // lookback start, is settled there uncounted rather than reported as failing then.
            let history = try failedTurnHistory(harness)
            #expect(history.episodes == [[unix(harness.at(9, 4, 9, 1)), "1.0"]])
            #expect(history.events == [[unix(harness.at(9, 4, 9, 5)), "Example: 1 turn failed: model at capacity"]])
            #expect(try RawSQLite.rows(harness.paths.database, "SELECT turn_id, CAST(evaluated_at AS INTEGER) FROM failed_turns ORDER BY turn_id") == [
                ["turn_synthetic_901", unix(harness.at(8, 5, 10))],
                ["turn_synthetic_902", unix(harness.at(9, 4, 9, 5))],
            ])
        }
    }

    @Test func catchUpAfterMoreThanTheLookbackCountsOnlyFailedTurnsInsideIt() async throws {
        try await withCollector { harness throws in
            #expect(await harness.run(at: harness.at(7, 1, 10)).outcome == .succeeded)  // cold start, then off
            // The old cursor hands over everything since, including a failure from before the lookback.
            let gapFailure = FailedTurnRecord(
                provider: .codex, threadID: "thread_synthetic_01", turnID: "turn_synthetic_901", startedAt: harness.at(7, 20, 12),
                completedAt: harness.at(7, 20, 12, 1), errorCode: "serverOverloaded", message: "Synthetic failure 1")
            harness.source.setNextBatch(IngestBatch(failedTurns: [gapFailure, recentFailure(harness)]))

            #expect(await harness.run(at: harness.at(9, 4, 10)).outcome == .succeeded)

            let history = try failedTurnHistory(harness)
            #expect(history.episodes == [[unix(harness.at(9, 4, 9, 1)), "1.0"]])
            #expect(history.events.map { $0[0] } == [unix(harness.at(9, 4, 9, 5))])
            #expect(try RawSQLite.scalar(harness.paths.database, "SELECT COUNT(*) FROM failed_turns WHERE evaluated_at IS NULL") == "0")
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

    @Test func unpostedFailedTurnNoticeWaitsForTheNextRun() async throws {
        try await withCollector { harness throws in
            _ = await harness.run(at: harness.at(9, 4, 8))  // cold start
            let failure = recentFailure(harness)
            harness.source.setNextBatch(IngestBatch(failedTurns: [failure]))
            await harness.notifier.refuseAll()

            let refused = await harness.run(at: harness.at(9, 4, 9, 5))

            #expect(refused.outcome == .succeeded && refused.notificationsPosted == 0)
            // The failure waits again and no notice counts as sent, so the coalescing window stays open.
            #expect(try harness.store().failureNotices(provider: .codex) == FailureNotices(lastNoticeAt: nil, waiting: [failure]))

            await harness.notifier.acceptAll()
            let retried = await harness.run(at: harness.at(9, 4, 9, 10))

            #expect(retried.notificationsPosted == 1)
            #expect(await harness.notifier.posted.map(\.body) == ["Example: 1 turn failed: model at capacity"])
            #expect(try harness.store().failureNotices(provider: .codex) == FailureNotices(lastNoticeAt: harness.at(9, 4, 9, 10), waiting: []))
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
            #expect(try harness.store().lastEvaluatedPoint(unit: "codex") == chunk0End)
            #expect(try harness.store().backfill(unit: "codex")?.through == firstNow)

            // The next run resumes at Aug 6 10:00. The slowdown fires at Sep 4 09:20, before
            // backfillThrough, so it stays quiet even though it is still open when this run ends:
            // a live fire in the gap would have sent a catch-up notice.
            let resumed = await harness.run(at: harness.at(9, 4, 10, 10))

            #expect(resumed.outcome == .succeeded && resumed.notificationsPosted == 0)
            #expect(await harness.notifier.posted.isEmpty)
            let store = try harness.store()
            #expect(try store.backfill(unit: "codex")?.through == firstNow)
            #expect(try store.lastEvaluatedPoint(unit: "codex") == harness.at(9, 4, 10, 10))
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
            #expect(try store.lastEvaluatedPoint(unit: "codex") == firstNow)
            #expect(try store.lastEvaluatedPoint(unit: "example.broken") == nil)
            #expect(try store.backfill(unit: "example.broken") == nil)
            #expect(try store.episodes(rule: RuleID.slower.rawValue).count == 1)
            // The other source's ingest still landed; the broken one's cursor didn't advance.
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM responses WHERE provider = 'codex'") == "90")
            #expect(try store.cursor("example.broken") == nil)

            // Fixed: the next run ingests the broken source again and evaluates every point.
            try RawSQLite.rows(url, "DROP TRIGGER synthetic_refusal")
            let resumed = await harness.run(at: harness.at(9, 4, 10, 5), sources: [broken, harness.source])

            #expect(resumed.outcome == .succeeded)
            #expect(try store.lastEvaluatedPoint(unit: "codex") == harness.at(9, 4, 10, 5))
            #expect(try RawSQLite.scalar(url, "SELECT COUNT(*) FROM responses WHERE provider = 'example.broken'") == "3")
            #expect(try store.episodes(rule: RuleID.slower.rawValue).map(\.firedAt) == [harness.at(9, 4, 9, 20)])
            // The newly ready provider backfills through the retry and remains quiet.
            #expect(try store.backfill(unit: "example.broken")?.through == harness.at(9, 4, 10, 5))
            #expect(await harness.notifier.posted.isEmpty)
        }
    }

    /// An unready provider without progress waits until it becomes ready.
    @Test func reportedSourceProblemStillEvaluates() async throws {
        try await withCollector { harness throws in
            harness.source.setState(.notSetUp("synthetic: not set up"))
            harness.seedUsual()
            harness.seedSlowdown()
            let now = harness.at(9, 4, 10)

            #expect(await harness.run(at: now).outcome == .succeeded)
            #expect(try harness.store().lastEvaluatedPoint(unit: "codex") == nil)
            #expect(try harness.store().backfill(unit: "codex") == nil)
            #expect(try harness.store().episodes(rule: RuleID.slower.rawValue).isEmpty)
            harness.source.setState(.ready)
            #expect(await harness.run(at: now.addingTimeInterval(300)).outcome == .succeeded)
            #expect(try harness.store().lastEvaluatedPoint(unit: "codex") == now.addingTimeInterval(300))
            #expect(try harness.store().episodes(rule: RuleID.slower.rawValue).count == 1)
            harness.source.setState(.notSetUp("synthetic: unavailable"))
            #expect(await harness.run(at: now.addingTimeInterval(600)).outcome == .succeeded)
            #expect(try harness.store().lastEvaluatedPoint(unit: "codex") == now.addingTimeInterval(600))
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
            #expect(try harness.store().lastEvaluatedPoint(unit: "codex") == nil)
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

/// A date as the whole Unix seconds `CAST(... AS INTEGER)` prints.
func unix(_ date: Date) -> String { String(Int(date.timeIntervalSince1970)) }
