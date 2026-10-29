import Foundation
import Testing
import TelltaleCodex
import TelltaleClaude
import TelltaleCore
import TelltaleOpenAIStatus
import TelltaleTestSupport

/// The status page, faked: a quiet summary with one watched component, and nothing else. Every
/// request is recorded so a test can see that only the injected base was asked.
actor QuietStatusTransport: HTTPTransport {
    static let base = URL(string: "https://status.example.com")!
    static let summary = Data("""
        {"summary": {"id": "synthetic-page", "name": "Example Status", "ongoing_incidents": [],
          "components": [{"id": "comp_cli", "name": "CLI"}], "affected_components": []}}
        """.utf8)

    private(set) var requests: [URL] = []

    func get(_ url: URL) async throws -> (Data, HTTPURLResponse) {
        requests.append(url)
        let found = url.path == "/proxy/status.openai.com"
        return (found ? Self.summary : Data(), HTTPURLResponse(url: url, statusCode: found ? 200 : 404, httpVersion: "HTTP/1.1", headerFields: nil)!)
    }
}

/// A synthetic Codex home: one rollout per local day, each response a user message followed by
/// its `token_usage_record` (start = the message, end = the record; spec section 6.1).
final class CodexWorkload {
    static let model = "gpt-6.1-sol"
    static let display = "6.1 Sol"
    /// Every response has this many output and input tokens.
    static let outputTokens = 1_000
    static let inputTokens = 10_000

    let codexHome: URL
    let calendar = Synth.newYork
    private var sessions = 0
    private var responses = 0

    init(codexHome: URL) { self.codexHome = codexHome }

    /// A session starting `start`: for each `(count, throughput)` run, `count` responses ending a
    /// minute apart, the first ending at `firstEnd` and each run following the last.
    func session(start: Date, firstEnd: Date, runs: [(count: Int, throughput: Double)]) -> RolloutBuilder {
        sessions += 1
        var builder = RolloutBuilder(session: sessions, origin: start)
        builder.sessionMeta()
        builder.turnContext(at: 1, model: Self.model)
        var end = firstEnd
        for run in runs {
            for _ in 0..<run.count {
                responses += 1
                let seconds = end.timeIntervalSince(start)
                builder.userMessage(at: seconds - Double(Self.outputTokens) / run.throughput)
                builder.usage(at: seconds, response: responses, input: Self.inputTokens, cached: 0, output: Self.outputTokens, reasoning: nil)
                end = end.addingTimeInterval(60)
            }
        }
        return builder
    }

    /// Writes the lines stamped at or before `through` (all by default) as the plain rollout, dated
    /// like a live file.
    func write(_ builder: RolloutBuilder, through: Date? = nil) throws {
        let count = through.map { limit in builder.lines.indices.last { Self.stamp(builder.lines[$0]) <= limit }.map { $0 + 1 } ?? 0 }
            ?? builder.lines.count
        let url = try builder.writePlain(builder.encoded(0..<count), codexHome: codexHome)
        let modified = count == 0 ? builder.origin : Self.stamp(builder.lines[count - 1])
        try FileManager.default.setAttributes([.modificationDate: modified], ofItemAtPath: url.path)
    }

    private static func stamp(_ line: String) -> Date {
        let object = try! JSONSerialization.jsonObject(with: Data(line.utf8)) as! [String: Any]
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: object["timestamp"] as! String)!
    }
}

/// Temporary paths with a synthetic Codex home, the real Codex source, the OpenAI status source
/// on a fake transport, and a recording notifier.
final class IntegrationHarness {
    let home: URL
    let paths: TelltalePaths
    let workload: CodexWorkload
    let transport = QuietStatusTransport()
    let notifier = RecordingNotifier()
    var calendar: Calendar { workload.calendar }

    init(home: URL) {
        self.home = home
        paths = TestPaths.synthetic(home: home)
        workload = CodexWorkload(codexHome: paths.codexHome)
    }

    func at(_ month: Int, _ day: Int, _ hour: Int = 0, _ minute: Int = 0) -> Date { Synth.local(2026, month, day, hour, minute) }

    func run(at now: Date) async -> RunReport {
        await CollectorRun(
            paths: paths, sources: [CodexUsageSource(codexHome: paths.codexHome, busyTimeout: .milliseconds(50))],
            statusSources: [OpenAIStatusSource(transport: transport, base: QuietStatusTransport.base, clock: { now })],
            notifier: notifier, calendar: calendar, now: now
        ).run()
    }

    /// Sep 1–3: 30 responses a day at 40 tok/s ending 09:00–09:29, so Sep 4 is past cold start
    /// (3 active days) with 90 samples of usual 40 for the one key (medium, no tier, under 50k).
    func seedUsualDays() throws {
        for day in 1...3 {
            try workload.write(workload.session(start: at(9, day, 8), firstEnd: at(9, day, 9), runs: [(30, 40)]))
        }
    }

    func store() throws -> Store { try Store.open(paths.database, mode: .readOnly) }
}

func withIntegration(_ body: (IntegrationHarness) async throws -> Void) async throws {
    try await withAsyncScratchDirectory { home in try await body(IntegrationHarness(home: home)) }
}

@Suite struct CollectorIntegrationTests {
    /// Sep 4 runs every 5 minutes. Responses at 30 tok/s end 09:00–09:29: each lasts
    /// 1000 / 30 = 33.333 s (millisecond timestamps), a throughput of 30.0003, so the speed index
    /// is 30.0003 / 40 = 0.75 and the slowdown is round(|0.75 − 1| × 100) = 25%, above the 15%
    /// trigger and below red (30%). The 09:05 window (09:00–09:05) holds 6 responses, too thin;
    /// 09:10, 09:15 and 09:20 each hold at least 10, so it fires at 09:20 with onset
    /// 09:10 − 15 min = 08:55. Recovery at 40 tok/s ends 09:30–10:19. The 09:40 window
    /// (09:25–09:40] holds 4 slow and 11 usual responses, median 1.0, within the 8% band; 30
    /// minutes of that is 09:40 through 10:05, six points, so it clears at 10:05.
    @Test func endToEndSlowdownFiresOnceAndClears() async throws {
        try await withIntegration { harness throws in
            try harness.seedUsualDays()
            let today = harness.workload.session(start: harness.at(9, 4, 8), firstEnd: harness.at(9, 4, 9), runs: [(30, 30), (50, 40)])
            var noticesByRun: [(at: Date, notices: [PendingNotification])] = []
            var seen = 0
            var now = harness.at(9, 4, 8)
            while now <= harness.at(9, 4, 10, 30) {
                try harness.workload.write(today, through: now)
                let report = await harness.run(at: now)
                #expect(report.outcome == .succeeded, "run at \(now): \(report.detail)")
                let posted = await harness.notifier.posted
                if posted.count > seen { noticesByRun.append((now, Array(posted[seen...]))) }
                seen = posted.count
                now = now.addingTimeInterval(5 * 60)
            }

            let calendar = harness.calendar
            let expected: [(at: Date, title: String, body: String)] = [
                (harness.at(9, 4, 9, 20), "Slower than usual",
                 "Codex: " + Copy.slowerFired(model: CodexWorkload.display, percent: 25, since: harness.at(9, 4, 8, 55), calendar: calendar)),
                (harness.at(9, 4, 10, 5), "Slower than usual", "Codex: " + Copy.speedCleared(model: CodexWorkload.display)),
            ]
            #expect(noticesByRun.map(\.at) == expected.map(\.at))
            #expect(noticesByRun.flatMap(\.notices).map(\.title) == expected.map(\.title))
            #expect(noticesByRun.flatMap(\.notices).map(\.body) == expected.map(\.body))
            let episodes = try harness.store().episodes(rule: RuleID.slower.rawValue)
            #expect(episodes.count == 1)
            #expect(episodes.first?.endReason == EpisodeRow.EndReason.cleared)
            #expect(episodes.first?.endedAt == harness.at(9, 4, 10, 5))
        }
    }

    /// A 20-day gap: the collector last ran Sep 4 08:05 and next runs Sep 24 10:00. Every day of
    /// the gap, Sep 4–23, has a slowdown that fires and clears inside it (30 responses at 30 tok/s
    /// ending 09:00–09:29, then 170 at 40 tok/s ending 09:30–12:19: 4,000 responses). Sep 24 has
    /// 40 slow responses ending 09:00–09:39 and nothing after, so its episode fires at 09:20
    /// (onset 08:55) and is still open at 10:00. The one catch-up run must stay under 60 s in a
    /// debug build and post only spec section 7.3's notice for the open episode.
    @Test func twentyDayGapCatchUpIsBoundedAndQuiet() async throws {
        try await withIntegration { harness throws in
            try harness.seedUsualDays()
            #expect(await harness.run(at: harness.at(9, 4, 8)).outcome == .succeeded)       // cold start
            #expect(await harness.run(at: harness.at(9, 4, 8, 5)).outcome == .succeeded)    // live, quiet
            let gapDays = 20
            for offset in 0..<gapDays {
                let day = harness.calendar.date(byAdding: .day, value: offset, to: harness.at(9, 4))!
                try harness.workload.write(harness.workload.session(
                    start: day.addingTimeInterval(8 * 3_600), firstEnd: day.addingTimeInterval(9 * 3_600), runs: [(30, 30), (170, 40)]))
            }
            try harness.workload.write(harness.workload.session(start: harness.at(9, 24, 8), firstEnd: harness.at(9, 24, 9), runs: [(40, 30)]))

            let clock = ContinuousClock()
            let started = clock.now
            let report = await harness.run(at: harness.at(9, 24, 10))
            let elapsed = started.duration(to: clock.now)

            #expect(report.outcome == .succeeded, "\(report.detail)")
            #expect(elapsed < .seconds(60), "catch-up took \(elapsed)")
            let expected = "Codex: " + Copy.slowerCatchUp(
                model: CodexWorkload.display, percent: 25, since: harness.at(9, 24, 8, 55), calendar: harness.calendar)
            #expect(await harness.notifier.posted.map(\.body) == [expected])
            let episodes = try harness.store().episodes(rule: RuleID.slower.rawValue)
            #expect(episodes.count == gapDays + 1)
            #expect(episodes.dropLast().allSatisfy { $0.endReason == EpisodeRow.EndReason.cleared })
            #expect(episodes.last?.endedAt == nil && episodes.last?.firedAt == harness.at(9, 24, 9, 20))
        }
    }

    /// Every dependency is injected: the paths derive from the scratch home, Codex is read from
    /// the synthetic home only, the status page is a fake transport on a synthetic base, and the
    /// notifier records. Codex's files compare equal before and after, by
    /// `codexFilesAreNotModified`'s contract (`FileSnapshot`).
    @Test func neverTouchesRealHome() async throws {
        try await withIntegration { harness throws in
            let codexHome = harness.paths.codexHome
            let now = harness.at(9, 4, 10)
            try harness.workload.write(harness.workload.session(start: harness.at(9, 4, 8), firstEnd: harness.at(9, 4, 9), runs: [(3, 40)]))
            let compressed = harness.workload.session(start: harness.at(9, 3, 8), firstEnd: harness.at(9, 3, 9), runs: [(3, 40)])
            try compressed.writeCompressed(codexHome: codexHome)
            let archived = harness.workload.session(start: harness.at(9, 2, 8), firstEnd: harness.at(9, 2, 9), runs: [(3, 40)])
            try archived.writeCompressed(codexHome: codexHome, archived: true)
            let history = try CodexDatabase.threadHistory(codexHome: codexHome)
            try history.addTurn(
                turn: 1, status: "failed", errorJSON: CodexDatabase.errorJSON(code: "serverOverloaded", message: "synthetic"),
                startedAt: harness.at(9, 4, 9, 30), completedAt: harness.at(9, 4, 9, 31))
            let logs = try CodexDatabase.logs(codexHome: codexHome)
            try logs.addLog(at: harness.at(9, 4, 9, 40), body: CodexDatabase.retryBody(samplingError: CodexDatabase.disconnectError))

            let before = try FileSnapshot.take(codexHome)
            #expect(await harness.run(at: now).outcome == .succeeded)
            #expect(await harness.run(at: now.addingTimeInterval(300)).outcome == .succeeded)
            #expect(try FileSnapshot.take(codexHome) == before)
            #expect(before.count == 5)

            // The run read what it was pointed at.
            let store = try harness.store()
            #expect(try store.responses(provider: .codex, model: CodexWorkload.model, endingIn: harness.at(9, 1)...now).count == 9)
            #expect(try store.connectionEvents(provider: .codex, in: harness.at(9, 4)...now).count == 1)
            // Everything it wrote is under the scratch home.
            let root = harness.home.standardizedFileURL.path + "/"
            let derived = [harness.paths.appSupport, harness.paths.database, harness.paths.lock, harness.paths.appLock,
                           harness.paths.logDirectory, harness.paths.log, harness.paths.launchAgents, harness.paths.codexHome]
            #expect(derived.allSatisfy { $0.standardizedFileURL.path.hasPrefix(root) })
            for url in [harness.paths.database, harness.paths.lock, harness.paths.log] {
                #expect(FileManager.default.fileExists(atPath: url.path), "\(url.lastPathComponent)")
            }
            #expect(try FileManager.default.contentsOfDirectory(atPath: harness.home.path).sorted() == ["Library", "synthetic-codex"])
            // The status page was the fake one, on the synthetic base.
            let requests = await harness.transport.requests
            #expect(!requests.isEmpty && requests.allSatisfy { $0.host() == "status.example.com" })
        }
    }
}

private struct IntegrationStatus: StatusSource {
    struct Down: Error {}
    let id: String
    let down: Bool
    var displayName: String { id }
    func fetch(known: [IncidentRecord]) async throws -> StatusFetch {
        if down { throw Down() }
        return .full(components: [], incidents: [])
    }
}

extension CollectorIntegrationTests {
    private func runBoth(_ h: IntegrationHarness, at now: Date, down: String? = nil) async -> RunReport {
        await CollectorRun(paths: h.paths,
            sources: [CodexUsageSource(codexHome: h.paths.codexHome), ClaudeUsageSource(roots: [h.paths.claudeHome])],
            statusSources: [IntegrationStatus(id: "openai", down: down == "openai"), IntegrationStatus(id: "anthropic", down: down == "anthropic")],
            notifier: h.notifier, calendar: h.calendar, now: now).run()
    }

    private func writeClaude(_ h: IntegrationHarness, broken: Bool = false) throws {
        let text = try TranscriptBuilder.user("2026-09-04T12:59:00Z") + (broken
            ? TranscriptBuilder.line(["type": "assistant", "timestamp": "2026-09-04T13:00:00Z", "message": ["id": "msg_synthetic_01", "model": "claude-opus-5-5"]])
            : TranscriptBuilder.assistant("2026-09-04T13:00:00Z"))
        let url = try TranscriptBuilder.file(root: h.paths.claudeHome, text: text)
        try FileManager.default.setAttributes([.modificationDate: h.at(9, 4, 9)], ofItemAtPath: url.path)
    }

    @Test func codexAndClaudeTogether() async throws {
        try await withIntegration { h in
            try h.workload.write(h.workload.session(start: h.at(9, 4, 8), firstEnd: h.at(9, 4, 9), runs: [(1, 40)]))
            try writeClaude(h)
            #expect(await runBoth(h, at: h.at(9, 4, 10)).outcome == .succeeded)
            let store = try h.store()
            #expect(try store.responses(provider: .codex, model: CodexWorkload.model, endingIn: h.at(9, 4)...h.at(9, 4, 10)).count == 1)
            #expect(try store.responses(provider: .claude, model: "claude-opus-5-5", endingIn: h.at(9, 4)...h.at(9, 4, 10)).count == 1)
        }
    }

    @Test func claudeHomeAloneWorks() async throws {
        try await withIntegration { h in
            try writeClaude(h)
            #expect(await runBoth(h, at: h.at(9, 4, 10)).outcome == .succeeded)
            #expect(try h.store().responses(provider: .claude, model: "claude-opus-5-5", endingIn: h.at(9, 4)...h.at(9, 4, 10)).count == 1)
        }
    }

    @Test func claudeAbsentLeavesCodexUntouched() async throws {
        try await withIntegration { h in
            try h.workload.write(h.workload.session(start: h.at(9, 4, 8), firstEnd: h.at(9, 4, 9), runs: [(1, 40)]))
            #expect(await runBoth(h, at: h.at(9, 4, 10)).outcome == .succeeded)
            #expect(try h.store().responses(provider: .codex, model: CodexWorkload.model, endingIn: h.at(9, 4)...h.at(9, 4, 10)).count == 1)
        }
    }

    @Test func statusFetchDoesntResetClaudeFormatSince() async throws {
        try await withIntegration { h in
            try writeClaude(h, broken: true)
            let now = h.at(9, 4, 10)
            #expect(await runBoth(h, at: now).outcome == .succeeded)
            #expect(await runBoth(h, at: now.addingTimeInterval(300)).outcome == .succeeded)
            #expect(try h.store().sourceState("claude")?.unavailableSince == now)
            #expect(try h.store().sourceState("anthropic")?.state == .ready)
        }
    }

    @Test func oneStatusSourceDownLeavesTheOtherEvaluated() async throws {
        try await withIntegration { h in
            try writeClaude(h)
            #expect(await runBoth(h, at: h.at(9, 4, 10), down: "openai").outcome == .succeeded)
            #expect(try h.store().sourceState("anthropic")?.state == .ready)
            #expect(try h.store().sourceState("openai")?.unavailableSince != nil)
        }
    }
}
