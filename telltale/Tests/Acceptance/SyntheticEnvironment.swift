// Port: brew_version/Tests/Acceptance/SyntheticEnvironment.swift, SyntheticEnvironment, fbd3e03.
// Adaptation: replaces the Homebrew inventory and SyntheticTransport with a seeded Telltale
// database under an explicit private home, plus a command-runner double for launchctl. Shared by
// the snapshot and acceptance builders. Every value is conspicuously synthetic.
import Foundation
import Synchronization
import TelltaleCore

/// Synthetic model names: `example-model-1.0` is "Example", `example-model-2.0` is "Sample".
struct SyntheticNaming: ModelNaming {
    func displayName(model: String) -> String {
        switch model {
        case SyntheticEnvironment.example: "Example"
        case SyntheticEnvironment.sample: "Sample"
        default: model
        }
    }
    func incidentTitle(_ title: String, names model: String) -> Bool { false }
}

/// Records launchctl calls and never starts a process. `print` reports the job missing.
final class SyntheticCommandRunner: CommandRunner, Sendable {
    private let recorded = Mutex<[[String]]>([])
    var calls: [[String]] { recorded.withLock { $0 } }
    func run(_ executable: String, _ arguments: [String]) throws -> CommandResult {
        recorded.withLock { $0.append(arguments) }
        if arguments.first == "print" { return CommandResult(status: 113, stdout: "", stderr: "Could not find service (synthetic)\n") }
        return CommandResult(status: 0, stdout: "", stderr: "")
    }
}

enum SyntheticEnvironment {
    static let example = "example-model-1.0"
    static let sample = "example-model-2.0"
    static let sessionID = "00000000-0000-4000-8000-000000000001"
    /// Snapshots render at a fixed instant in a fixed zone: Fri Sep 4 2026, 09:30 in New York.
    static let calendar: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "America/New_York")!
        calendar.locale = Locale(identifier: "en_US_POSIX")
        return calendar
    }()
    static let snapshotNow = calendar.date(from: DateComponents(year: 2026, month: 9, day: 4, hour: 9, minute: 30))!
    /// The synthetic status page the scenes' incidents come from.
    static let statusSourceID = "status.example.com"
    static let sources = [SourceSummary(
        provider: .codex, name: "Codex", statusName: "Demo", statusSourceID: statusSourceID, signals: [.speed, .errors, .link, .provider, .load],
        naming: SyntheticNaming())]

    /// The panel states the harnesses seed (spec section 13's snapshot list, plus the acceptance mix).
    enum Scene: String, CaseIterable {
        case quiet, alerting, shift
        /// The acceptance app: an alerting model, a shift prompt and the collector off.
        case acceptance
        /// The dashboard's model view: alerting, plus 14 days of hourly points with a fast spell, a
        /// slow morning with failed turns and a provider incident, and their events.
        case dashboard
        /// The collector view's problem state: loaded and on schedule, but the last run failed.
        case collectorProblem
        /// Settings: the quiet scene plus the status page's component list, which lacks some of the
        /// saved watched names; the snapshot adds an invalid Rules entry.
        case settings
    }

    static func paths(home: URL) -> TelltalePaths {
        TelltalePaths(home: home.appending(path: "home", directoryHint: .isDirectory), codexHome: home.appending(path: "codex", directoryHint: .isDirectory))
    }

    /// The acceptance bundle's explicit private home (`SyntheticAcceptanceHome` in its Info.plist).
    static func requireHome(_ value: Any?) -> URL {
        guard let path = value as? String, path.hasPrefix("/"), FileManager.default.fileExists(atPath: path) else {
            fatalError("Explicit acceptance home missing")
        }
        return URL(fileURLWithPath: path, isDirectory: true)
    }

    /// Collector health for a scene: running, off by choice for the acceptance app, or the problem
    /// scene's failed last run (as `seed` records it at `snapshotNow`).
    static func health(_ scene: Scene) -> CollectorHealthReport {
        if scene == .collectorProblem {
            return CollectorHealthReport(
                installed: .green, loaded: .green, lastRun: .red, onSchedule: .green,
                problems: [Copy.collectorFailing(
                    at: snapshotNow.addingTimeInterval(-30), reason: failedRunDetail, next: snapshotNow.addingTimeInterval(270), calendar: calendar)],
                needsRepair: false, footer: "", notify: true)
        }
        return scene == .acceptance
            ? CollectorHealthReport(
                installed: .unlit, loaded: .unlit, lastRun: .unlit, onSchedule: .unlit, problems: [], needsRepair: false,
                footer: Copy.collectorOff, notify: false)
            : CollectorHealthReport(
                installed: .green, loaded: .green, lastRun: .green, onSchedule: .green, problems: [], needsRepair: false, footer: "",
                notify: false)
    }

    /// Creates the scene's database under `home`, relative to `now`:
    /// - 14 earlier active days of usual (Example 42 tok/s, Sample 74 tok/s);
    /// - the last hour's responses and 3 hours of evaluation points for both models;
    /// - a succeeded collector run a minute before `now`;
    /// - alerting: Example 26% slower plus a large-prompt alert, both amber;
    /// - shift: three consecutive days of slower episodes ending before today, with a provider
    ///   incident on the middle day that the prompt links to;
    /// - dashboard: two 300k+ prompts a day and 4 in 10 in the last hour, with cached input and
    ///   reasoning tokens throughout.
    /// - settings and acceptance: a status-page component list for the watched-components checklist.
    @discardableResult
    static func seed(_ scene: Scene, home: URL, now: Date, calendar: Calendar) throws -> TelltalePaths {
        let paths = paths(home: home)
        let store = try Store.open(paths.database, mode: .readWrite)
        let today = calendar.startOfDay(for: now)
        var number = 0
        // The dashboard scene fills the Workload grid: cached input and reasoning on every response.
        let dashboard = scene == .dashboard
        func responses(
            _ model: String, count: Int, tps: Double, from first: Date, spacing: TimeInterval = 60, input: (Int) -> Int = { _ in 10_000 }
        ) throws {
            try store.upsert(responses: (0..<count).map { index in
                number += 1
                let end = first.addingTimeInterval(Double(index) * spacing)
                let tokens = input(index)
                return ResponseRecord(
                    provider: .codex, model: model, effort: "medium", serviceTier: nil, sessionID: sessionID, isSubagent: false,
                    turnID: String(format: "turn_synthetic_%02ld", number), responseID: String(format: "resp_synthetic_%02ld", number),
                    start: end.addingTimeInterval(-1_000 / tps), end: end, inputTokens: tokens, cachedInputTokens: dashboard ? tokens * 3 / 5 : 0,
                    outputTokens: 1_000, reasoningTokens: dashboard ? 250 : nil)
            })
        }
        let shifting = scene == .shift || scene == .acceptance
        for daysBack in 1...17 {
            let day = calendar.date(byAdding: .day, value: -daysBack, to: today)!.addingTimeInterval(9 * 3_600)
            let slowDay = shifting && daysBack <= 3
            try responses(example, count: 20, tps: slowDay ? 31 : 42, from: day)
            try responses(sample, count: 20, tps: 74, from: day.addingTimeInterval(1_800))
            if dashboard && daysBack <= 14 {
                // Two large prompts a day, in the same hour as the rest: the 300k+ bucket's usual share
                // and speed, while the usual median prompt stays small.
                try responses(example, count: 2, tps: 42, from: day.addingTimeInterval(25 * 60)) { _ in 320_000 }
            }
            if shifting && daysBack == 2 {
                // A provider incident inside the lasting shift: its prompt links to it (ruling R31).
                try store.upsert(incidents: [IncidentRecord(
                    source: statusSourceID, id: "inc_synthetic_02", name: "Synthetic slow responses", status: "resolved",
                    publishedAt: day, updatedAt: day.addingTimeInterval(2 * 3_600),
                    link: URL(string: "https://status.example.com/incidents/inc_synthetic_02")!,
                    history: [StatusChange(at: day, status: "investigating")], impacts: [])])
            }
            if slowDay {
                try store.insertEpisode(EpisodeRow(
                    rule: RuleID.slower.rawValue, provider: ProviderID.codex.rawValue, scope: example, direction: .slower,
                    onset: day.addingTimeInterval(-600), firedAt: day.addingTimeInterval(300), endedAt: day.addingTimeInterval(1_800),
                    endReason: EpisodeRow.EndReason.cleared, severity: LampColor.amber.rawValue, worstValue: 0.74))
            }
        }
        let alerting = scene == .alerting || scene == .acceptance || scene == .dashboard
        let exampleNow: Double = alerting ? 31 : 41
        // The dashboard's large-prompt alert: 4 in 10 of the last hour's prompts are 300k or more.
        try responses(example, count: 30, tps: exampleNow, from: now.addingTimeInterval(-3_600 + 60), spacing: 118) { dashboard && $0 % 5 < 2 ? 320_000 : 10_000 }
        try responses(sample, count: 20, tps: 70, from: now.addingTimeInterval(-3_600 + 90), spacing: 170)

        // Three hours of 5-minute points: the slowdown shows as a step in Example's sparkline.
        let lastPoint = EvaluationPoints.after(nil, through: now, earliest: now.addingTimeInterval(-EvaluationPoints.cadence)).last ?? now
        var points: [EvalPointRow] = []
        for step in 0..<PanelSnapshot.sparklinePoints {
            let at = lastPoint.addingTimeInterval(-EvaluationPoints.cadence * Double(PanelSnapshot.sparklinePoints - 1 - step))
            let wave = sin(Double(step) / 3)
            let examplePoint = alerting && step > 20 ? 31 + wave : 41 + wave
            points.append(EvalPointRow(provider: .codex, model: example, at: at, speedIndex: examplePoint / 42, mixUsual: 42, medianTPS: examplePoint, samples: 12, state: .known))
            points.append(EvalPointRow(provider: .codex, model: sample, at: at, speedIndex: (71 + wave) / 74, mixUsual: 74, medianTPS: 71 + wave, samples: 12, state: .known))
        }
        try store.insertEvalPoints(points)

        if alerting {
            let onset = now.addingTimeInterval(-50 * 60)
            try alert(store, rule: .slower, scope: example, direction: .slower, onset: onset, at: onset.addingTimeInterval(900),
                      body: Copy.slowerFired(model: "Example", percent: 26, since: onset, calendar: calendar))
            try alert(store, rule: .largePrompts, scope: "*", direction: nil, onset: now.addingTimeInterval(-20 * 60), at: now.addingTimeInterval(-15 * 60),
                      body: Copy.largePromptsFired(count: 4, of: 10, tokens: 300_000))
        }
        if scene == .acceptance { try store.set(.collectorEnabled, false) }
        if scene == .settings || scene == .acceptance {
            // The checklist's page: two of the default watched names, one other, and none of the rest.
            try store.replace(
                components: [
                    StatusComponent(id: "comp_synthetic_01", name: "CLI"), StatusComponent(id: "comp_synthetic_02", name: "Codex API"),
                    StatusComponent(id: "comp_synthetic_03", name: "Example Chat"),
                ], source: statusSourceID)
        }
        let run = try store.beginRun(at: now.addingTimeInterval(-64))
        try store.finishRun(run, at: now.addingTimeInterval(-60), outcome: .succeeded)
        if scene == .dashboard { try dashboardHistory(store, now: now, calendar: calendar) }
        if scene == .collectorProblem { try collectorProblem(store, paths: paths, now: now) }
        return paths
    }

    /// The collector problem scene's failed run: why it failed, as the run record and log say.
    static let failedRunDetail = "the synthetic history database was locked"

    /// 14 days of hourly speed points (09:00–16:00), with a fast spell 10 days back and a slow,
    /// failing morning yesterday under a provider incident; each with its event. A status post and
    /// a disconnect event round out the event list.
    static func dashboardHistory(_ store: Store, now: Date, calendar: Calendar) throws {
        let today = calendar.startOfDay(for: now)
        var points: [EvalPointRow] = []
        for daysBack in 1...14 {
            let day = calendar.date(byAdding: .day, value: -daysBack, to: today)!
            for hour in 9...16 {
                let at = day.addingTimeInterval(Double(hour) * 3_600 + 1_200)
                let wave = sin(Double(daysBack * 8 + hour)) * 0.05
                let index = daysBack == 10 ? 1.42 + wave : daysBack == 1 && hour < 12 ? 0.66 + wave : 1 + wave
                points.append(EvalPointRow(
                    provider: .codex, model: example, at: at, speedIndex: index, mixUsual: 42, medianTPS: 42 * index, samples: 12, state: .known))
            }
        }
        try store.insertEvalPoints(points)
        let fast = calendar.date(byAdding: .day, value: -10, to: today)!.addingTimeInterval(9 * 3_600)
        let fastID = try store.insertEpisode(EpisodeRow(
            rule: RuleID.faster.rawValue, provider: ProviderID.codex.rawValue, scope: example, direction: .faster, onset: fast,
            firedAt: fast.addingTimeInterval(3_600), endedAt: fast.addingTimeInterval(8 * 3_600), endReason: EpisodeRow.EndReason.cleared,
            severity: LampColor.blue.rawValue, worstValue: 1.48))
        try store.insertEvent(EventRow(
            at: fast.addingTimeInterval(3_600), kind: EventKind.ruleFired, provider: ProviderID.codex.rawValue, scope: example,
            title: RuleID.faster.title, body: Copy.fasterFired(model: "Example", percent: 42, since: fast, calendar: calendar), episodeID: fastID))
        let slow = calendar.date(byAdding: .day, value: -1, to: today)!.addingTimeInterval(9 * 3_600)
        try store.insertEpisode(EpisodeRow(
            rule: RuleID.slower.rawValue, provider: ProviderID.codex.rawValue, scope: example, direction: .slower, onset: slow,
            firedAt: slow.addingTimeInterval(1_800), endedAt: slow.addingTimeInterval(3 * 3_600), endReason: EpisodeRow.EndReason.cleared,
            severity: LampColor.red.rawValue, worstValue: 0.62))
        try store.upsert(failedTurns: (1...3).map { number in
            FailedTurnRecord(
                provider: .codex, threadID: sessionID, turnID: String(format: "turn_synthetic_failed_%02ld", number),
                startedAt: slow.addingTimeInterval(Double(number) * 2_400), completedAt: slow.addingTimeInterval(Double(number) * 2_400 + 30),
                model: example, errorCode: "synthetic_capacity", message: "Synthetic model is at capacity")
        })
        let failedID = try store.insertEpisode(EpisodeRow(
            rule: RuleID.failedTurns.rawValue, provider: ProviderID.codex.rawValue, scope: "*", direction: nil, onset: slow.addingTimeInterval(2_400),
            firedAt: slow.addingTimeInterval(7_230), endedAt: slow.addingTimeInterval(4 * 3_600), endReason: EpisodeRow.EndReason.cleared,
            severity: LampColor.red.rawValue, worstValue: 3))
        try store.insertEvent(EventRow(
            at: slow.addingTimeInterval(7_230), kind: EventKind.ruleFired, provider: ProviderID.codex.rawValue, scope: "*",
            title: RuleID.failedTurns.title, body: Copy.failedTurns(count: 3, reasons: ["Synthetic model is at capacity"]), episodeID: failedID))
        let link = URL(string: "https://status.example.com/incidents/inc_synthetic_01")!
        try store.upsert(incidents: [IncidentRecord(
            source: "status.example.com", id: "inc_synthetic_01", name: "Synthetic elevated latency", status: "resolved",
            publishedAt: slow.addingTimeInterval(1_200), updatedAt: slow.addingTimeInterval(3 * 3_600), link: link,
            history: [StatusChange(at: slow.addingTimeInterval(1_200), status: "investigating")], impacts: [])])
        try store.insertEvent(EventRow(
            at: slow.addingTimeInterval(1_200), kind: EventKind.statusPost, provider: ProviderID.codex.rawValue, scope: "*",
            title: "Demo status", body: Copy.statusPost(source: "Demo", title: "Synthetic elevated latency"), link: link))
        let disconnectsID = try store.insertEpisode(EpisodeRow(
            rule: RuleID.disconnects.rawValue, provider: ProviderID.codex.rawValue, scope: "*", direction: nil, onset: now.addingTimeInterval(-7_200),
            firedAt: now.addingTimeInterval(-6_900), endedAt: now.addingTimeInterval(-5_400), endReason: EpisodeRow.EndReason.cleared,
            severity: LampColor.amber.rawValue, worstValue: 3))
        try store.insertEvent(EventRow(
            at: now.addingTimeInterval(-6_900), kind: EventKind.ruleFired, provider: ProviderID.codex.rawValue, scope: "*",
            title: RuleID.disconnects.title, body: Copy.disconnectsFired(count: 3, windowMinutes: 30), episodeID: disconnectsID))
    }

    /// A failed run after the succeeded one, and the log lines both runs wrote.
    static func collectorProblem(_ store: Store, paths: TelltalePaths, now: Date) throws {
        let failed = try store.beginRun(at: now.addingTimeInterval(-30))
        try store.finishRun(failed, at: now.addingTimeInterval(-29.6), outcome: .failed, detail: failedRunDetail)
        let stamp = Date.ISO8601FormatStyle(timeZone: calendar.timeZone)
        let lines = [
            (now.addingTimeInterval(-64), "run started"),
            (now.addingTimeInterval(-62), "scanned 3 synthetic rollouts, 40 responses, 0 failed turns"),
            (now.addingTimeInterval(-61), "status page: no open incidents"),
            (now.addingTimeInterval(-60), "run succeeded in 4.0 s"),
            (now.addingTimeInterval(-30), "run started"),
            (now.addingTimeInterval(-29.6), "run failed: \(failedRunDetail)"),
        ]
        try FileManager.default.createDirectory(at: paths.log.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data(lines.map { "\(stamp.format($0.0)) \($0.1)\n" }.joined().utf8).write(to: paths.log)
    }

    /// An open amber episode with its fired event.
    static func alert(_ store: Store, rule: RuleID, scope: String, direction: Direction?, onset: Date, at: Date, body: String, severity: LampColor = .amber) throws {
        let id = try store.insertEpisode(EpisodeRow(
            rule: rule.rawValue, provider: ProviderID.codex.rawValue, scope: scope, direction: direction, onset: onset, firedAt: at,
            severity: severity.rawValue, worstValue: 0.74))
        try store.insertEvent(EventRow(at: at, kind: EventKind.ruleFired, provider: ProviderID.codex.rawValue, scope: scope, title: rule.title, body: body, episodeID: id))
    }

    /// The acceptance app's Check now double: records a synthetic succeeded run instead of
    /// kickstarting launchd, so the panel's checked time moves.
    static func recordCheck(paths: TelltalePaths, at now: Date) throws {
        let store = try Store.open(paths.database, mode: .readWrite)
        let run = try store.beginRun(at: now)
        try store.finishRun(run, at: now.addingTimeInterval(1), outcome: .succeeded)
    }
}
