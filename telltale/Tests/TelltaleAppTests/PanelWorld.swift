import Foundation
import TelltaleCore
import TelltaleTestSupport
@testable import Telltale

/// Synthetic model names for the app tests: `example-model-1.0` is "Example".
struct AppSyntheticNaming: ModelNaming {
    func displayName(model: String) -> String { model == Synth.model ? "Example" : model }
    func incidentTitle(_ title: String, names model: String) -> Bool { false }
}

/// A seeded, conspicuously synthetic Telltale database under a scratch directory, and the panel
/// objects that read it. Sep 4 2026 in New York.
enum PanelWorld {
    static let statusSummaries = [StatusSourceSummary(id: statusSourceID, displayName: "Example Status", defaultWatchedComponents: ["CLI", "VS Code extension", "Codex in ChatGPT Desktop", "Codex API", "Codex Web", "Responses"])]
    static let sources = [SourceSummary(
        provider: .codex, name: "Codex", statusName: "Example Status", statusSourceID: statusSourceID, signals: [.speed, .errors, .link, .provider, .load],
        naming: AppSyntheticNaming())]
    static let now = Synth.local(2026, 9, 4, 9, 30)
    static let statusSourceID = "example-status"
    static let alertText = "Example is 25% slower than usual for prompts this size. Since 08:55."

    static func paths(_ directory: URL) -> TelltalePaths {
        TelltalePaths(home: directory.appending(path: "home", directoryHint: .isDirectory), codexHome: directory.appending(path: "codex", directoryHint: .isDirectory))
    }

    /// Creates the database as the collector would: a finished run at 09:29 and 30 responses at 40 tok/s
    /// ending 09:00–09:29. `alerting` adds an open amber slower episode.
    @discardableResult
    static func seed(_ paths: TelltalePaths, alerting: Bool = false) throws -> Store {
        let store = try Store.open(paths.database, mode: .readWrite)
        var synth = Synth()
        try store.upsert(responses: synth.responses(30, throughput: 40, from: Synth.local(2026, 9, 4, 9, 0)))
        let run = try store.beginRun(at: Synth.local(2026, 9, 4, 9, 29))
        try store.finishRun(run, at: Synth.local(2026, 9, 4, 9, 29).addingTimeInterval(4), outcome: .succeeded)
        if alerting { try addAlert(store) }
        return store
    }

    /// A resolved one-hour incident on the sources' status page.
    static func incident(published: Date, id: String = "inc_synthetic_07") -> IncidentRecord {
        IncidentRecord(
            source: statusSourceID, id: id, name: "Synthetic slow responses", status: "resolved", publishedAt: published,
            updatedAt: published.addingTimeInterval(3_600), link: URL(string: "https://status.example.com/incidents/\(id)")!,
            history: [StatusChange(at: published, status: "investigating")], impacts: [])
    }

    /// An open amber slower episode for Example with its fired event.
    static func addAlert(_ store: Store, body: String = alertText) throws {
        let fired = Synth.local(2026, 9, 4, 9, 20)
        let id = try store.insertEpisode(EpisodeRow(
            rule: RuleID.slower.rawValue, provider: ProviderID.codex.rawValue, scope: Synth.model, direction: .slower,
            onset: Synth.local(2026, 9, 4, 8, 55), firedAt: fired, severity: LampColor.amber.rawValue, worstValue: 0.75))
        try store.insertEvent(EventRow(
            at: fired, kind: EventKind.ruleFired, provider: ProviderID.codex.rawValue, scope: Synth.model, title: RuleID.slower.title,
            body: body, episodeID: id))
    }

    @MainActor static func live(
        _ paths: TelltalePaths, poll: Duration = .seconds(3_600), watch: Bool = false,
        health: @escaping @MainActor () async -> CollectorHealthReport? = { nil }
    ) -> LiveStore {
        LiveStore(paths: paths, sources: sources, calendar: Synth.newYork, now: { now }, health: health, pollInterval: poll, watchFiles: watch)
    }

    @MainActor static func actions(_ paths: TelltalePaths, kickstart: @escaping @Sendable () throws -> Void = {}) -> UserActions {
        UserActions(paths: paths, calendar: Synth.newYork, now: { now }, kickstart: kickstart)
    }
}

/// Waits up to `timeout` for `condition`, yielding to the main actor between checks.
@MainActor func eventually(timeout: Duration = .seconds(5), _ condition: @MainActor () -> Bool) async -> Bool {
    let deadline = ContinuousClock.now.advanced(by: timeout)
    while ContinuousClock.now < deadline {
        if condition() { return true }
        try? await Task.sleep(for: .milliseconds(20))
    }
    return condition()
}
