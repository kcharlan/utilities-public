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
    static let sources = [SourceSummary(
        provider: .codex, name: "Codex", statusName: "Demo", signals: [.speed, .errors, .link, .provider, .load],
        naming: SyntheticNaming())]

    /// The panel states the harnesses seed (spec section 13's snapshot list, plus the acceptance mix).
    enum Scene: String, CaseIterable {
        case quiet, alerting, shift
        /// The acceptance app: an alerting model, a shift prompt and the collector off.
        case acceptance
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

    /// Collector health for a scene: running, or off by choice for the acceptance app.
    static func health(_ scene: Scene) -> CollectorHealthReport {
        scene == .acceptance
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
    /// - shift: three consecutive days of slower episodes ending before today.
    @discardableResult
    static func seed(_ scene: Scene, home: URL, now: Date, calendar: Calendar) throws -> TelltalePaths {
        let paths = paths(home: home)
        let store = try Store.open(paths.database, mode: .readWrite)
        let today = calendar.startOfDay(for: now)
        var number = 0
        func responses(_ model: String, count: Int, tps: Double, from first: Date, spacing: TimeInterval = 60, input: Int = 10_000) throws {
            try store.upsert(responses: (0..<count).map { index in
                number += 1
                let end = first.addingTimeInterval(Double(index) * spacing)
                return ResponseRecord(
                    provider: .codex, model: model, effort: "medium", serviceTier: nil, sessionID: sessionID, isSubagent: false,
                    turnID: String(format: "turn_synthetic_%02ld", number), responseID: String(format: "resp_synthetic_%02ld", number),
                    start: end.addingTimeInterval(-1_000 / tps), end: end, inputTokens: input, cachedInputTokens: 0, outputTokens: 1_000)
            })
        }
        let shifting = scene == .shift || scene == .acceptance
        for daysBack in 1...17 {
            let day = calendar.date(byAdding: .day, value: -daysBack, to: today)!.addingTimeInterval(9 * 3_600)
            let slowDay = shifting && daysBack <= 3
            try responses(example, count: 20, tps: slowDay ? 31 : 42, from: day)
            try responses(sample, count: 20, tps: 74, from: day.addingTimeInterval(1_800))
            if slowDay {
                try store.insertEpisode(EpisodeRow(
                    rule: RuleID.slower.rawValue, provider: ProviderID.codex.rawValue, scope: example, direction: .slower,
                    onset: day.addingTimeInterval(-600), firedAt: day.addingTimeInterval(300), endedAt: day.addingTimeInterval(1_800),
                    endReason: EpisodeRow.EndReason.cleared, severity: LampColor.amber.rawValue, worstValue: 0.74))
            }
        }
        let alerting = scene == .alerting || scene == .acceptance
        let exampleNow: Double = alerting ? 31 : 41
        try responses(example, count: 30, tps: exampleNow, from: now.addingTimeInterval(-3_600 + 60), spacing: 118)
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
        let run = try store.beginRun(at: now.addingTimeInterval(-64))
        try store.finishRun(run, at: now.addingTimeInterval(-60), outcome: .succeeded)
        return paths
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
