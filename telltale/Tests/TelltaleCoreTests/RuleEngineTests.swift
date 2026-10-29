import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

/// Synthetic model names: `example-model-1.0` is "Example", `example-model-2.0` is "Sample". A
/// status title names a model when it contains its display name and version ("Example 1.0").
struct SyntheticNaming: ModelNaming {
    static let names = [Synth.model: ("Example", "1.0"), Synth.otherModel: ("Sample", "2.0")]

    func displayName(model: String) -> String { Self.names[model]?.0 ?? model }
    func incidentTitleIsModelSpecific(_ title: String) -> Bool { title.contains("Sample 2.0") }

    func incidentTitle(_ title: String, names model: String) -> Bool {
        guard let (name, version) = Self.names[model] else { return false }
        return title.contains("\(name) \(version)")
    }
}

private struct DefaultSyntheticNaming: ModelNaming {
    func displayName(model: String) -> String { model }
    func incidentTitle(_ title: String, names model: String) -> Bool { false }
}

/// A temporary store with a rule engine on the America/New_York calendar, a synthetic status
/// source and the baseline harness's helpers.
final class RuleHarness {
    static let sourceID = "example-status"
    static let source = RuleStatusSource(id: sourceID, displayName: "Example Status", providers: [.codex])

    let base: BaselineHarness
    let engine: RuleEngine
    var store: Store { base.store }
    var url: URL { base.url }
    var calendar: Calendar { base.calendar }
    let model = Synth.model
    var settings = RuleSettings.defaults
    var watched = ["CLI"]

    init(directory: URL) throws {
        base = try BaselineHarness(directory: directory)
        engine = RuleEngine(store: base.store, baseline: base.engine, calendar: base.calendar, naming: [.codex: SyntheticNaming()])
    }

    /// A local time in 2026.
    func at(_ month: Int, _ day: Int, _ hour: Int = 0, _ minute: Int = 0) -> Date { base.at(month, day, hour, minute) }

    /// Sep 4 at `hour`:`minute`, the day most tests evaluate.
    func sep4(_ hour: Int, _ minute: Int = 0) -> Date { at(9, 4, hour, minute) }

    /// Evaluates every point after the last evaluated one (or from `from`) through `through`.
    @discardableResult
    func evaluate(from: Date? = nil, through: Date, statusAvailable: Bool = true) throws -> [RuleOutcome] {
        var outcomes: [RuleOutcome] = []
        for unit in [EvaluationUnit.provider(.codex), .statusSource(Self.source, available: statusAvailable)] {
            let points = EvaluationPoints.after(try store.lastEvaluatedPoint(unit: unit.key), through: through, earliest: from ?? sep4(9))
            outcomes += try engine.evaluate(points: points, unit: unit, settings: settings, watchedComponents: watched)
        }
        return outcomes.sorted { $0.at < $1.at }
    }

    /// Sep 1–3: 20 responses a day at 40 tok/s from 09:00, so speed rules can judge Sep 4 (three
    /// active days, usual 40 for the default key).
    func seedUsual(model: String? = nil, days: ClosedRange<Int> = 1...3) throws {
        for day in days { try base.add(20, throughput: 40, month: 9, day: day, model: model) }
    }

    /// `count` responses a minute apart on Sep 4, the first ending at `hour`:`minute`.
    func run(_ count: Int, throughput: Double, hour: Int, minute: Int = 0, model: String? = nil, inputTokens: Int = 10_000) throws {
        try base.add(count, throughput: throughput, month: 9, day: 4, hour: hour, minute: minute, model: model, inputTokens: inputTokens)
    }

    func failure(_ number: Int, started: Date, completed: Date?, turnID: String? = nil, code: String = "serverOverloaded") -> FailedTurnRecord {
        FailedTurnRecord(
            provider: .codex, threadID: String(format: "thread_synthetic_%02ld", number),
            turnID: turnID ?? String(format: "turn_synthetic_9%02ld", number), startedAt: started, completedAt: completed,
            errorCode: code, message: "Synthetic failure \(number)")
    }

    func connection(_ number: Int, at: Date, kind: ConnectionKind) -> ConnectionEventRecord {
        ConnectionEventRecord(provider: .codex, sourceID: "logs_synthetic:\(number)", at: at, kind: kind, detail: "synthetic \(kind.rawValue)")
    }

    func incident(
        _ id: String = "inc_synthetic_01", name: String = "Elevated errors", status: String = "investigating",
        published: Date, resolved: Date? = nil, impacts: [ComponentImpact]
    ) -> IncidentRecord {
        var history = [StatusChange(at: published, status: "investigating")]
        if let resolved { history.append(StatusChange(at: resolved, status: "resolved")) }
        return IncidentRecord(
            source: Self.sourceID, id: id, name: name, status: resolved == nil ? status : "resolved", publishedAt: published,
            updatedAt: resolved ?? published, link: URL(string: "https://status.example.com/incidents/\(id)")!,
            history: history, impacts: impacts)
    }

    func seedComponents() throws {
        try store.replace(components: [StatusComponent(id: "comp_cli", name: "CLI"), StatusComponent(id: "comp_other", name: "Other")], source: Self.sourceID)
    }

    func episodes(_ rule: RuleID) throws -> [EpisodeRow] { try store.episodes(rule: rule.rawValue) }

    /// Event rows: [kind, provider, scope, title, body, episode_id, link].
    func events() throws -> [[String]] {
        try RawSQLite.rows(url, "SELECT kind, provider, scope, title, body, episode_id, IFNULL(link, 'NULL') FROM events ORDER BY id")
    }

    func clock(_ date: Date) -> String {
        let parts = calendar.dateComponents([.hour, .minute], from: date)
        return String(format: "%02ld:%02ld", parts.hour!, parts.minute!)
    }
}

func withRules(_ body: (RuleHarness) throws -> Void) throws {
    try withScratchDirectory { directory in try body(try RuleHarness(directory: directory)) }
}

extension RuleOutcome {
    var firedOnset: Date? {
        if case .fired(let onset, _) = transition { return onset }
        return nil
    }
}

@Suite struct RuleEngineTests {
    @Test func defaultNamingLeavesIncidentsUnchanged() throws {
        try withRules { h in
            try h.seedComponents()
            try h.store.upsert(incidents: [h.incident(name: "Synthetic Sample 2.0 issue", published: h.sep4(9), impacts: [ComponentImpact(componentID: "comp_cli", status: "partial_outage", start: h.sep4(9))])])
            let engine = RuleEngine(store: h.store, baseline: h.base.engine, calendar: h.calendar, naming: [.codex: DefaultSyntheticNaming()])
            try engine.evaluate(points: [h.sep4(9)], unit: .statusSource(RuleHarness.source, available: true), settings: h.settings, watchedComponents: h.watched)
            #expect(try h.episodes(.incident).count == 1)
        }
    }
    @Test func watchedComponentSkipsAnotherModelsIncident() throws {
        try withRules { h in
            try h.seedComponents()
            try h.store.upsert(incidents: [h.incident(name: "Synthetic Sample 2.0 issue", published: h.sep4(9),
                impacts: [ComponentImpact(componentID: "comp_cli", status: "partial_outage", start: h.sep4(9))])])
            try h.evaluate(through: h.sep4(9, 5))
            #expect(try h.episodes(.incident).isEmpty)
        }
    }
    @Test func watchedComponentFiresOnceTheNamedModelIsUsed() throws {
        try withRules { h in
            try h.seedComponents()
            try h.store.upsert(incidents: [h.incident(name: "Synthetic Sample 2.0 issue", published: h.sep4(9), impacts: [ComponentImpact(componentID: "comp_cli", status: "partial_outage", start: h.sep4(9))])])
            try h.evaluate(through: h.sep4(9, 5))
            #expect(try h.episodes(.incident).isEmpty)
            try h.store.upsert(responses: [h.base.synth.response(model: Synth.otherModel, throughput: 40, end: h.sep4(9, 6))])
            try h.evaluate(through: h.sep4(9, 10))
            #expect(try h.episodes(.incident).count == 1)
        }
    }
    @Test func openIncidentEpisodeSurvivesUseRollingOff() throws {
        try withRules { h in
            try h.seedComponents()
            try h.store.upsert(responses: [h.base.synth.response(model: Synth.otherModel, throughput: 40, end: h.at(9, 3, 9, 1))])
            try h.store.upsert(incidents: [h.incident(name: "Synthetic Sample 2.0 issue", published: h.sep4(9), impacts: [ComponentImpact(componentID: "comp_cli", status: "partial_outage", start: h.sep4(9))])])
            try h.evaluate(through: h.sep4(9))
            try h.evaluate(through: h.sep4(9, 10))
            #expect(try h.store.openEpisodes().filter { $0.rule == RuleID.incident.rawValue }.count == 1)
        }
    }
    @Test func modelFreeTitleStillFiresOnWatchedComponent() throws {
        try withRules { h in
            try h.seedComponents()
            try h.store.upsert(incidents: [h.incident(name: "Synthetic service issue", published: h.sep4(9), impacts: [ComponentImpact(componentID: "comp_cli", status: "partial_outage", start: h.sep4(9))])])
            try h.evaluate(through: h.sep4(9))
            #expect(try h.episodes(.incident).count == 1)
        }
    }
    @Test func providerNamedBodies() throws {
        try withRules { h in
            let info = RuleProviderInfo(name: "Synthetic Provider", failureNoun: "request", signals: [.errors], rules: [.failedTurns], naming: SyntheticNaming())
            let engine = RuleEngine(store: h.store, baseline: h.base.engine, calendar: h.calendar, providers: [.codex: info])
            try h.store.upsert(failedTurns: [h.failure(1, started: h.sep4(9, 1), completed: h.sep4(9, 2))])
            let outcomes = try engine.evaluate(points: [h.sep4(9, 5)], unit: .provider(.codex), settings: h.settings, watchedComponents: [])
            #expect(outcomes.first?.message == "Synthetic Provider: 1 request failed: model at capacity")
            #expect(try h.events().first?[4] == "Synthetic Provider: 1 request failed: model at capacity")
        }
    }
    @Test func unsupportedRuleNeitherFiresNorNotifies() throws {
        try withRules { h in
            let info = RuleProviderInfo(name: "Codex", failureNoun: "turn", signals: [.errors], rules: [], naming: SyntheticNaming())
            let engine = RuleEngine(store: h.store, baseline: h.base.engine, calendar: h.calendar, providers: [.codex: info])
            try h.store.upsert(failedTurns: [h.failure(1, started: h.sep4(9, 1), completed: h.sep4(9, 2))])
            let outcomes = try engine.evaluate(points: [h.sep4(9, 5)], unit: .provider(.codex), settings: h.settings, watchedComponents: [])
            #expect(outcomes.isEmpty)
            #expect(try h.episodes(.failedTurns).isEmpty)
        }
    }

    @Test func undeclaredSignalsRuleNeitherFiresNorNotifies() throws {
        try withRules { h in
            let info = RuleProviderInfo(name: "Codex", failureNoun: "turn", signals: [], rules: [.failedTurns], naming: SyntheticNaming())
            let engine = RuleEngine(store: h.store, baseline: h.base.engine, calendar: h.calendar, providers: [.codex: info])
            try h.store.upsert(failedTurns: [h.failure(1, started: h.sep4(9, 1), completed: h.sep4(9, 2))])
            let outcomes = try engine.evaluate(points: [h.sep4(9, 5)], unit: .provider(.codex), settings: h.settings, watchedComponents: [])
            #expect(outcomes.isEmpty)
            #expect(try h.episodes(.failedTurns).isEmpty)
        }
    }
    @Test func evaluationOnlyTouchesItsUnit() throws {
        try withRules { h in
            let other = ProviderID(rawValue: "synthetic-other")
            let at = h.sep4(9)
            let id = try h.store.insertEpisode(EpisodeRow(rule: RuleID.failedTurns.rawValue, provider: other.rawValue,
                scope: "*", direction: nil, onset: at, firedAt: at, severity: "red", worstValue: 1))
            h.settings.failedTurns.enabled = false
            try h.engine.evaluate(points: [at], unit: .provider(.codex), settings: h.settings, watchedComponents: [])
            #expect(try h.store.openEpisodes().contains { $0.id == id })
            #expect(try h.store.lastEvaluatedPoint(unit: other.rawValue) == nil)
        }
    }

    @Test func unavailableStatusAdvancesWithoutChangingIncidents() throws {
        try withRules { h in
            let at = h.sep4(9)
            let id = try h.store.insertEpisode(EpisodeRow(rule: RuleID.incident.rawValue, provider: RuleHarness.sourceID,
                scope: "synthetic-incident", direction: nil, onset: at, firedAt: at, severity: "amber", worstValue: 1))
            h.settings.incident.enabled = false
            try h.engine.evaluate(points: [at], unit: .statusSource(RuleHarness.source, available: false),
                settings: h.settings, watchedComponents: [])
            #expect(try h.store.openEpisodes().contains { $0.id == id })
            #expect(try h.store.lastEvaluatedPoint(unit: RuleHarness.sourceID) == at)
        }
    }

    @Test func sharedStatusSourceEvaluatesIncidentsOnce() throws {
        try withRules { h in
            try h.seedComponents()
            try h.store.upsert(incidents: [h.incident(published: h.sep4(9),
                impacts: [ComponentImpact(componentID: "comp_cli", status: "degraded_performance", start: h.sep4(9))])])
            let source = RuleStatusSource(id: RuleHarness.sourceID, displayName: "Example Status",
                providers: [.codex, ProviderID(rawValue: "synthetic-other")])
            let outcomes = try h.engine.evaluate(points: [h.sep4(9), h.sep4(9, 5)], unit: .statusSource(source, available: true),
                settings: h.settings, watchedComponents: h.watched)
            #expect(outcomes.count == 1)
            #expect(try h.episodes(.incident).count == 1)
        }
    }
    // MARK: Speed

    @Test func slowerFiresAndStoresPointsWithUsual() throws {
        try withRules { h in
            try h.seedUsual()
            // 30 tok/s against a usual of 40: index 0.75, one response a minute from 09:00.
            try h.run(30, throughput: 30, hour: 9)
            let outcomes = try h.evaluate(through: h.sep4(9, 20))

            // 09:10 is the first point with 10 responses in its window; 09:10, 09:15, 09:20 fire.
            #expect(outcomes.count == 1)
            let fired = try #require(outcomes.first)
            #expect(fired.rule == .slower)
            #expect(fired.at == h.sep4(9, 20))
            #expect(fired.provider == "codex" && fired.scope == h.model)
            #expect(fired.transition == .fired(onset: h.sep4(8, 55), severity: .amber))
            #expect(fired.message == "Example is 25% slower than usual for prompts this size. Since 08:55.")
            #expect(fired.catchUpMessage == "Example has been 25% slower than usual for prompts this size since 08:55.")

            let points = try h.store.evalPoints(provider: .codex, model: h.model, in: h.sep4(9)...h.sep4(9, 20))
            #expect(points.map(\.at) == [h.sep4(9), h.sep4(9, 5), h.sep4(9, 10), h.sep4(9, 15), h.sep4(9, 20)])
            #expect(points.map(\.state) == [.thin, .thin, .known, .known, .known])
            #expect(points.map(\.samples) == [1, 6, 11, 15, 15])
            #expect(points[1].speedIndex == nil)
            #expect(approximately(points[1].mixUsual, 40))
            #expect(approximately(points[2].speedIndex, 0.75))
            #expect(approximately(points[2].mixUsual, 40))
            #expect(approximately(points[2].medianTPS, 30))

            let episode = try #require(try h.episodes(.slower).first)
            #expect(episode.id == fired.episodeID)
            #expect(episode.direction == .slower)
            #expect(episode.onset == h.sep4(8, 55) && episode.firedAt == h.sep4(9, 20) && episode.endedAt == nil)
            #expect(episode.severity == "amber")
            #expect(approximately(episode.worstValue, 0.75))
            #expect(try h.events() == [["ruleFired", "codex", h.model, "Slower than usual", fired.message, "\(fired.episodeID)", "NULL"]])
            #expect(RuleID.slower.rawValue == EpisodeRow.slowerRule && RuleID.faster.rawValue == EpisodeRow.fasterRule)
        }
    }

    @Test func fasterFiresBlue() throws {
        try withRules { h in
            try h.seedUsual()
            try h.run(30, throughput: 50, hour: 9)
            let outcomes = try h.evaluate(through: h.sep4(9, 30))
            #expect(outcomes.map(\.rule) == [.faster])
            #expect(outcomes.first?.transition == .fired(onset: h.sep4(8, 55), severity: .blue))
            #expect(outcomes.first?.message == "Example is 25% faster than usual for prompts this size. Check that output isn't shallower. Since 08:55.")
            let episode = try #require(try h.episodes(.faster).first)
            #expect(episode.direction == .faster && episode.severity == "blue")
            #expect(approximately(episode.worstValue, 1.25))
            #expect(try h.episodes(.slower).isEmpty)
        }
    }

    @Test func reversalEndsTheOppositeEpisode() throws {
        try withRules { h in
            try h.seedUsual()
            try h.run(30, throughput: 30, hour: 9)
            try h.run(60, throughput: 50, hour: 9, minute: 30)
            var outcomes: [RuleOutcome] = []
            for minute in stride(from: 30, through: 90, by: 5) {
                let time = h.sep4(9).addingTimeInterval(Double(minute * 60))
                outcomes += try h.evaluate(through: time)
                if time >= h.sep4(9, 50) {
                    #expect(try h.episodes(.slower).allSatisfy { $0.endedAt != nil })
                }
            }
            let slower = try #require(try h.episodes(.slower).first)
            let faster = try #require(try h.episodes(.faster).first)
            #expect(slower.endedAt == h.sep4(9, 50))
            #expect(slower.endReason == EpisodeRow.EndReason.reversed)
            #expect(faster.endedAt == nil && slower.id != faster.id)
            #expect(outcomes.contains { $0.episodeID == slower.id && $0.transition == .reversed })
            #expect(outcomes.contains { $0.episodeID == faster.id && $0.message.contains("after running slower") })
            #expect(try h.events().map { $0[0] } == ["ruleFired", "ruleFired"])
        }
    }

    @Test func fasterIsReversedBySlower() throws {
        try withRules { h in
            try h.seedUsual()
            try h.run(30, throughput: 50, hour: 9)
            try h.run(60, throughput: 30, hour: 9, minute: 30)
            for minute in stride(from: 30, through: 90, by: 5) {
                let time = h.sep4(9).addingTimeInterval(Double(minute * 60))
                _ = try h.evaluate(through: time)
                let open = try (h.episodes(.slower) + h.episodes(.faster)).filter { $0.endedAt == nil }
                #expect(open.count <= 1)
            }
            let faster = try #require(try h.episodes(.faster).first)
            #expect(faster.endReason == EpisodeRow.EndReason.reversed)
            #expect(try h.episodes(.slower).first?.endedAt == nil)
            #expect(try h.events().last?[4].contains("after running faster") == true)
        }
    }
    @Test func redSlowerEpisodeIsReversed() throws {
        try withRules { h in
            try h.seedUsual()
            try h.run(30, throughput: 20, hour: 9)
            try h.run(60, throughput: 50, hour: 9, minute: 30)
            _ = try h.evaluate(through: h.sep4(10, 30))
            let slower = try #require(try h.episodes(.slower).first)
            #expect(slower.severity == "red" && slower.endReason == EpisodeRow.EndReason.reversed)
        }
    }
    @Test func clearAtTheOppositeFireIsAClear() throws {
        for initial in [Direction.slower, .faster] {
            try withRules { h in
                h.settings.slower.clearMinutes = 15
                h.settings.faster.clearMinutes = 15
                try h.seedUsual()
                try h.run(30, throughput: initial == .slower ? 30 : 50, hour: 9)
                try h.run(60, throughput: initial == .slower ? 50 : 30, hour: 9, minute: 30)
                let outcomes = try h.evaluate(through: h.sep4(10, 30))
                let old = try #require(try h.episodes(.speed(initial)).first)
                let replacement = try #require(try h.episodes(.speed(initial.opposite)).first)
                #expect(old.endReason == EpisodeRow.EndReason.cleared)
                #expect(old.endedAt == replacement.firedAt)
                #expect(outcomes.first { $0.episodeID == replacement.id }?.message.contains("after running") == false)
            }
        }
    }
    @Test func clearBeforeTheOppositeFireIsAClear() throws {
        try withRules { h in
            h.settings.slower.clearMinutes = 5
            try h.seedUsual()
            try h.run(30, throughput: 30, hour: 9)
            try h.run(60, throughput: 50, hour: 9, minute: 30)
            let outcomes = try h.evaluate(through: h.sep4(10, 30))
            let old = try #require(try h.episodes(.slower).first)
            let replacement = try #require(try h.episodes(.faster).first)
            #expect(old.endReason == EpisodeRow.EndReason.cleared && old.endedAt! < replacement.firedAt)
            #expect(outcomes.first { $0.episodeID == replacement.id }?.message.contains("after running") == false)
        }
    }
    @Test func legacyOverlappingSpeedEpisodesSettle() throws {
        try withRules { h in
            try h.seedUsual()
            for direction in Direction.allCases {
                var machine = EpisodeMachine(firePoints: 1, clearPoints: 1, windowMinutes: 15, color: direction == .slower ? .amber : .blue)
                _ = machine.step(at: h.sep4(8, 55), trigger: .true, clear: .false, red: .false, idle: false)
                let id = try h.store.insertEpisode(EpisodeRow(rule: RuleID.speed(direction).rawValue, provider: "codex", scope: h.model,
                    direction: direction, onset: h.sep4(8, 40), firedAt: h.sep4(8, 55), severity: direction == .slower ? "amber" : "blue", worstValue: 1))
                let machineObject = try JSONSerialization.jsonObject(with: JSONEncoder().encode(machine))
                let json = try JSONSerialization.data(withJSONObject: ["machine": machineObject, "episodeID": id, "extreme": 1])
                try h.store.setRuleState(rule: RuleID.speed(direction).rawValue, provider: "codex", scope: h.model, json: String(decoding: json, as: UTF8.self))
            }
            try h.run(30, throughput: 40, hour: 9)
            _ = try h.evaluate(through: h.sep4(12))
            for direction in Direction.allCases {
                let episode = try #require(try h.episodes(.speed(direction)).first)
                #expect([EpisodeRow.EndReason.cleared, EpisodeRow.EndReason.idleEnded].contains(episode.endReason ?? ""))
                #expect(try h.store.ruleState(rule: RuleID.speed(direction).rawValue, provider: "codex", scope: h.model) == nil)
            }
        }
    }

    @Test func coldModelStaysQuiet() throws {
        try withRules { h in
            // Two active days: fewer than the three cold start needs (spec section 8).
            try h.seedUsual(days: 1...2)
            try h.run(60, throughput: 20, hour: 9)
            let outcomes = try h.evaluate(through: h.sep4(10))
            #expect(outcomes.isEmpty)
            #expect(try h.episodes(.slower).isEmpty)
            let points = try h.store.evalPoints(provider: .codex, model: h.model, in: h.sep4(9, 30)...h.sep4(9, 30))
            #expect(points.map(\.state) == [.cold])
            #expect(approximately(points.first?.speedIndex, 0.5))
        }
    }

    // MARK: Large prompts

    @Test func largePromptsFiresAndClears() throws {
        try withRules { h in
            // 10 small, 3 at exactly 300k (inclusive), then small again.
            try h.run(10, throughput: 40, hour: 9)
            try h.run(3, throughput: 40, hour: 9, minute: 10, inputTokens: 300_000)
            try h.run(17, throughput: 40, hour: 9, minute: 13)
            let outcomes = try h.evaluate(through: h.sep4(9, 30))

            // 09:15: 3 of the last 10. 09:20: 2 (still above "≤ 1"). 09:25: none.
            #expect(outcomes.map(\.rule) == [.largePrompts, .largePrompts])
            #expect(outcomes.map(\.at) == [h.sep4(9, 15), h.sep4(9, 25)])
            #expect(outcomes[0].transition == .fired(onset: h.sep4(9, 10), severity: .amber))
            #expect(outcomes[0].message == "3 of your last 10 prompts were at least 300k tokens. A fresh session would speed things up.")
            #expect(outcomes[1].transition == .cleared)
            #expect(outcomes[1].message == "Prompt sizes are back to usual.")
            let episode = try #require(try h.episodes(.largePrompts).first)
            #expect(episode.scope == h.model && episode.direction == nil && episode.worstValue == 3)
            #expect(episode.endReason == EpisodeRow.EndReason.cleared)
        }
    }

    @Test func largePromptSelectionUsesLastResponsesAcrossTimeGap() throws {
        try withRules { h in
            try h.run(7, throughput: 40, hour: 9)
            try h.run(3, throughput: 40, hour: 9, minute: 7, inputTokens: 400_000)
            #expect(try h.evaluate(through: h.sep4(9, 10)).map(\.transition) == [.fired(onset: h.sep4(9, 7), severity: .amber)])

            // 80 quiet minutes, then one small prompt: the last 10 still hold all 3 large ones.
            try h.run(1, throughput: 40, hour: 10, minute: 31)
            #expect(try h.evaluate(through: h.sep4(10, 35)).isEmpty)

            // No responses for 2 hours ends the episode silently (spec section 7.2) at 12:35.
            let idle = try h.evaluate(through: h.sep4(13))
            #expect(idle.map(\.transition) == [.idleEnded])
            #expect(idle.map(\.at) == [h.sep4(12, 35)])
            #expect(try h.events().count == 1)

            // The next activity starts fresh: one small prompt doesn't refire on the 3 old large
            // ones still in the last 10.
            try h.run(1, throughput: 40, hour: 13, minute: 1)
            #expect(try h.evaluate(through: h.sep4(13, 5)).isEmpty)
            #expect(try h.episodes(.largePrompts).count == 1)

            // A new large prompt meets the count with them (4 of the last 10) and fires.
            try h.run(1, throughput: 40, hour: 13, minute: 6, inputTokens: 400_000)
            let fresh = try h.evaluate(through: h.sep4(13, 10))
            #expect(fresh.map(\.transition) == [.fired(onset: h.sep4(13, 6), severity: .amber)])
            #expect(fresh.first?.message == "4 of your last 10 prompts were at least 300k tokens. A fresh session would speed things up.")
            let episodes = try h.episodes(.largePrompts)
            #expect(episodes.count == 2)
            #expect(episodes[0].endReason == EpisodeRow.EndReason.idleEnded && episodes[0].endedAt == h.sep4(12, 35))
            #expect(episodes[1].endedAt == nil && episodes[1].firedAt == h.sep4(13, 10) && episodes[1].onset == h.sep4(13, 6))
        }
    }

    // MARK: Failed turns

    @Test func failedTurnDetailsRecordOnlyCountedBatches() throws {
        try withRules { h in
            let cutoff = h.sep4(9, 5)
            try h.store.upsert(failedTurns: [h.failure(1, started: h.sep4(9, 1), completed: h.sep4(9, 2)), h.failure(2, started: cutoff, completed: cutoff)])
            _ = try h.store.settleFailedTurns(before: cutoff, provider: .codex)
            try h.evaluate(from: cutoff, through: cutoff)
            var episode = try #require(try h.store.openEpisodes().first)
            var detail = try #require(try FailedTurnEpisodeDetail.decode(episode.detail))
            #expect(detail.priorCount == 0 && detail.failures.map(\.turnID) == ["turn_synthetic_902"])
            try h.store.upsert(failedTurns: [h.failure(6, started: h.sep4(9, 1), completed: h.sep4(9, 2)),
                h.failure(3, started: h.sep4(9, 10), completed: h.sep4(9, 10))])
            _ = try h.store.settleFailedTurns(before: h.sep4(9, 10), provider: .codex)
            try h.evaluate(through: h.sep4(9, 10))
            episode = try #require(try h.store.openEpisodes().first)
            detail = try #require(try FailedTurnEpisodeDetail.decode(episode.detail))
            #expect(detail.failures.map(\.turnID) == ["turn_synthetic_902", "turn_synthetic_903"])
            let reopened = try Store.open(h.url, mode: .readWriteExisting)
            let resumed = RuleEngine(store: reopened, baseline: BaselineEngine(store: reopened, calendar: h.calendar), calendar: h.calendar, naming: [.codex: SyntheticNaming()])
            try reopened.upsert(failedTurns: [h.failure(4, started: h.sep4(9, 11), completed: h.sep4(9, 12))])
            _ = try resumed.evaluate(points: [h.sep4(9, 15)], unit: .provider(.codex), settings: h.settings, watchedComponents: h.watched)
            episode = try #require(try reopened.openEpisodes().first)
            detail = try #require(try FailedTurnEpisodeDetail.decode(episode.detail))
            #expect(detail.failures.map(\.turnID) == ["turn_synthetic_902", "turn_synthetic_903", "turn_synthetic_904"])
            episode.detail = Data("invalid".utf8)
            try reopened.updateEpisode(episode)
            try reopened.upsert(failedTurns: [h.failure(5, started: h.sep4(9, 16), completed: h.sep4(9, 17))])
            #expect(throws: (any Error).self) {
                try resumed.evaluate(points: [h.sep4(9, 20)], unit: .provider(.codex), settings: h.settings, watchedComponents: h.watched)
            }
            #expect(try reopened.openEpisodes().first?.worstValue == 3)
            #expect(try reopened.unevaluatedFailedTurns(through: h.sep4(9, 20)).map(\.turnID) == ["turn_synthetic_905"])
        }
    }
    @Test func failedTurnDetailValidatesMembershipAndRanges() throws {
        let detail = FailedTurnEpisodeDetail(priorCount: 2, failures: [.init(turnID: "turn_synthetic_901", errorCode: "timeout")])
        #expect(try FailedTurnEpisodeDetail.decode(detail.encoded()) == detail)
        #expect(detail.reasons(in: 0..<3) == nil)
        #expect(detail.reasons(in: 0..<0) == [])
        #expect(detail.reasons(in: 2..<3) == ["timeout"])
        #expect(detail.reasons(in: 2..<4) == nil)
        #expect(try FailedTurnEpisodeDetail.decode(nil) == nil)
        #expect(throws: (any Error).self) { try FailedTurnEpisodeDetail.decode(Data("invalid".utf8)) }
        #expect(throws: (any Error).self) { try FailedTurnEpisodeDetail(priorCount: -1, failures: []).encoded() }
        #expect(throws: (any Error).self) {
            try FailedTurnEpisodeDetail(priorCount: 0, failures: [.init(turnID: "synthetic", errorCode: "a"), .init(turnID: "synthetic", errorCode: "b")]).encoded()
        }
    }
    @Test func failedTurnLampHoldsForQuietWindow() throws {
        try withRules { h in
            try h.store.upsert(failedTurns: [
                h.failure(1, started: h.sep4(9, 1), completed: h.sep4(9, 3)),
                h.failure(2, started: h.sep4(9, 10), completed: h.sep4(9, 12)),
            ])
            let first = try h.evaluate(through: h.sep4(9, 40))
            #expect(first.map(\.at) == [h.sep4(9, 5), h.sep4(9, 15)])
            #expect(first[0].transition == .fired(onset: h.sep4(9, 1), severity: .red))
            #expect(first[0].failures.map(\.turnID) == ["turn_synthetic_901"])
            #expect(first[0].message == "1 turn failed: model at capacity")
            // A failure while the episode is open carries no transition.
            #expect(first[1].transition == nil && first[1].failures.map(\.turnID) == ["turn_synthetic_902"])
            #expect(first[1].episodeID == first[0].episodeID)

            // 30 quiet minutes after the last failure (counted at 09:15).
            let cleared = try h.evaluate(through: h.sep4(9, 45))
            #expect(cleared.map(\.transition) == [.cleared])
            #expect(cleared.first?.message == "No failed turns for 30 minutes.")
            let episode = try #require(try h.episodes(.failedTurns).first)
            #expect(episode.scope == "*" && episode.severity == "red" && episode.worstValue == 2)
            #expect(try RawSQLite.column(h.url, "SELECT evaluated_at IS NOT NULL FROM failed_turns ORDER BY turn_id") == ["1", "1"])
        }
    }

    @Test func failedTurnModelJoinedFromResponses() throws {
        try withRules { h in
            // Failed turns arrive without a model (Task 5); spec section 6.2 joins turn_id to responses.
            let response = h.base.synth.response(model: Synth.otherModel, throughput: 40, end: h.sep4(9, 1))
            try h.store.upsert(responses: [response])
            try h.store.upsert(failedTurns: [
                h.failure(1, started: h.sep4(9, 0), completed: h.sep4(9, 2), turnID: response.turnID),
                h.failure(2, started: h.sep4(9, 0), completed: h.sep4(9, 2), turnID: "turn_synthetic_unknown"),
            ])
            let outcome = try #require(try h.evaluate(through: h.sep4(9, 5)).first { $0.rule == .failedTurns })
            let models = Dictionary(uniqueKeysWithValues: outcome.failures.map { ($0.turnID, $0.model) })
            #expect(models[try #require(response.turnID)] == Synth.otherModel)
            #expect(models["turn_synthetic_unknown"] == .some(nil))
        }
    }

    @Test func lateIngestedFailedTurnIsCounted() throws {
        try withRules { h in
            #expect(try h.evaluate(through: h.sep4(9, 30)).isEmpty)
            // Ingested in a later run, dated before points already evaluated.
            try h.store.upsert(failedTurns: [h.failure(1, started: h.sep4(9, 12), completed: h.sep4(9, 13))])
            let outcomes = try h.evaluate(through: h.sep4(9, 35))
            #expect(outcomes.map(\.at) == [h.sep4(9, 35)])
            #expect(outcomes.first?.failures.count == 1)
            #expect(try h.evaluate(through: h.sep4(9, 40)).isEmpty)
        }
    }

    @Test func compactionsFireAtTwoAutomaticInTheWindow() throws {
        try withRules { h in
            func record(_ id: String, _ at: Date, _ trigger: CompactionTrigger, _ precomputed: Bool = false) -> CompactionRecord {
                CompactionRecord(provider: .codex, lineID: id, sessionID: "synthetic", agentID: nil, at: at,
                    trigger: trigger, tokensBefore: 100, tokensAfter: nil, duration: nil, precomputed: precomputed)
            }
            try h.store.upsert(compactions: [record("a", h.sep4(9, 1), .auto), record("b", h.sep4(9, 6), .auto, true), record("c", h.sep4(9, 7), .manual)])
            let outcomes = try h.evaluate(through: h.sep4(10, 10)).filter { $0.rule == .compactions }
            #expect(outcomes.map(\.at) == [h.sep4(9, 10), h.sep4(10, 10)])
            #expect(outcomes.first?.transition == .fired(onset: h.sep4(9, 1), severity: .amber))
            #expect(outcomes.last?.transition == .cleared)
            #expect(try h.episodes(.compactions).first?.worstValue == 2)
        }
    }

    @Test func compactionsNeedTheRuleAndTheSignal() throws {
        for (signals, rules): (Set<Signal>, Set<RuleID>) in [([], [.compactions]), ([.load], [])] {
            try withRules { h in
                let info = RuleProviderInfo(name: "Synthetic", failureNoun: "turn", signals: signals, rules: rules, naming: SyntheticNaming())
                let engine = RuleEngine(store: h.store, baseline: h.base.engine, calendar: h.calendar, providers: [.codex: info])
                try h.store.upsert(compactions: ["a", "b"].map {
                    CompactionRecord(provider: .codex, lineID: $0, sessionID: "synthetic", agentID: nil, at: h.sep4(9),
                        trigger: .auto, tokensBefore: 100, tokensAfter: nil, duration: nil, precomputed: false)
                })
                #expect(try engine.evaluate(points: [h.sep4(9, 5)], unit: .provider(.codex), settings: h.settings, watchedComponents: []).isEmpty)
            }
        }
    }

    @Test func compactionsOnlySumLongAutomaticBlocks() throws {
        try withRules { h in
            let records: [(String, CompactionTrigger, Double)] = [("a", .auto, 210), ("b", .auto, 10), ("c", .auto, 9), ("d", .manual, 100)]
            try h.store.upsert(compactions: records.map { id, trigger, duration in
                CompactionRecord(provider: .codex, lineID: id, sessionID: "synthetic", agentID: nil, at: h.sep4(9),
                    trigger: trigger, tokensBefore: 100, tokensAfter: nil, duration: duration, precomputed: false)
            })
            let outcome = try h.evaluate(through: h.sep4(9)).first { $0.rule == .compactions }
            #expect(outcome?.message == "3 automatic compactions in the last 60 minutes. Fresh sessions or subagents would keep more context. They held sessions for 3 min 40 s.")
        }
    }

    // MARK: Disconnects

    @Test func disconnectsCountsExcludeReconnect() throws {
        try withRules { h in
            // Reconnects are the routine 60-minute websocket limit (spec section 6.3).
            try h.store.upsert(connectionEvents: [
                h.connection(1, at: h.sep4(9, 1), kind: .disconnect),
                h.connection(2, at: h.sep4(9, 2), kind: .retry),
                h.connection(3, at: h.sep4(9, 3), kind: .reconnect),
                h.connection(4, at: h.sep4(9, 4), kind: .reconnect),
                h.connection(5, at: h.sep4(9, 6), kind: .disconnect),
            ])
            let outcomes = try h.evaluate(through: h.sep4(10, 10))
            // 09:05 counts 2; 09:10 counts 3. At 10:05 the window (09:05, 10:05] holds 1.
            #expect(outcomes.map(\.at) == [h.sep4(9, 10), h.sep4(10, 5)])
            #expect(outcomes[0].rule == .disconnects && outcomes[0].scope == "*")
            #expect(outcomes[0].transition == .fired(onset: h.sep4(9, 1), severity: .amber))
            #expect(outcomes[0].message == "3 disconnect or retry events in the last 60 minutes.")
            #expect(outcomes[1].transition == .cleared)
            #expect(outcomes[1].message == "Connection is steady again.")
            #expect(try h.episodes(.disconnects).first?.worstValue == 3)
        }
    }

    @Test func disconnectWindowsOverlappingAConnectionGapAreUnknown() throws {
        try withRules { h in
            try h.store.upsert(connectionEvents: [
                h.connection(1, at: h.sep4(9, 1), kind: .disconnect),
                h.connection(2, at: h.sep4(9, 2), kind: .retry),
                h.connection(3, at: h.sep4(9, 6), kind: .disconnect),
            ])
            // The log no longer covered 09:30–09:50 (spec section 6.3).
            try h.store.recordConnectionGap(provider: .codex, gap: DateInterval(start: h.sep4(9, 30), end: h.sep4(9, 50)), calendar: h.calendar)
            #expect(try h.events() == [[
                "connectionHistoryIncomplete", "codex", "*", "Disconnects", "Connection history incomplete from 09:30 to 09:50.", "NULL", "NULL",
            ]])
            #expect(try h.store.connectionGaps(provider: .codex, overlapping: DateInterval(start: h.sep4(9), end: h.sep4(9, 31)))
                == [DateInterval(start: h.sep4(9, 30), end: h.sep4(9, 50))])
            #expect(try h.store.connectionGaps(provider: .codex, overlapping: DateInterval(start: h.sep4(9, 50), end: h.sep4(11))).isEmpty)

            // Without the gap the episode would clear at 10:05 (one event in its window). Every
            // window from 09:35 to 10:45 overlaps the gap, so those points are unknown and hold.
            let outcomes = try h.evaluate(through: h.sep4(11))
            #expect(outcomes.map(\.at) == [h.sep4(9, 10), h.sep4(10, 50)])
            #expect(outcomes.map(\.transition) == [.fired(onset: h.sep4(9, 1), severity: .amber), .cleared])
            #expect(try h.episodes(.disconnects).first?.worstValue == 3)
        }
        try withRules { h in
            // A gap over the first events: no window that could count 3 is complete, so nothing fires.
            try h.store.upsert(connectionEvents: (1...3).map { h.connection($0, at: h.sep4(9, $0), kind: .disconnect) })
            try h.store.recordConnectionGap(provider: .codex, gap: DateInterval(start: h.sep4(8), end: h.sep4(9, 4)), calendar: h.calendar)
            #expect(try h.evaluate(through: h.sep4(11)).isEmpty)
            #expect(try h.episodes(.disconnects).isEmpty)
        }
    }

    // MARK: Provider incidents

    @Test func incidentOnWatchedComponentFires() throws {
        try withRules { h in
            try h.seedComponents()
            try h.store.upsert(incidents: [
                h.incident(published: h.sep4(9, 2), impacts: [ComponentImpact(componentID: "comp_cli", status: "degraded_performance", start: h.sep4(9, 2))]),
                // Only an unwatched component, and its title names no model.
                h.incident("inc_synthetic_02", name: "Image generation errors", published: h.sep4(9, 2),
                           impacts: [ComponentImpact(componentID: "comp_other", status: "partial_outage", start: h.sep4(9, 2))]),
            ])
            let outcomes = try h.evaluate(through: h.sep4(9, 10))
            #expect(outcomes.count == 1)
            let fired = try #require(outcomes.first)
            #expect(fired.rule == .incident && fired.provider == RuleHarness.sourceID && fired.scope == "inc_synthetic_01")
            #expect(fired.at == h.sep4(9, 5))
            #expect(fired.transition == .fired(onset: h.sep4(9, 2), severity: .amber))
            #expect(fired.message == "Example Status: Elevated errors.")
            #expect(fired.catchUpMessage == "Example Status: Elevated errors. Open since 09:02.")
            #expect(try h.events() == [[
                "ruleFired", RuleHarness.sourceID, "inc_synthetic_01", "Provider incident", fired.message, "\(fired.episodeID)",
                "https://status.example.com/incidents/inc_synthetic_01",
            ]])
            #expect(try h.episodes(.incident).first?.worstValue == 1)
        }
    }

    @Test func incidentTitleNamingRecentModelFires() throws {
        try withRules { h in
            try h.seedComponents()
            // Example used 1 hour before; Sample last used 26 hours before.
            try h.store.upsert(responses: [
                h.base.synth.response(throughput: 40, end: h.sep4(8)),
                h.base.synth.response(model: Synth.otherModel, throughput: 40, end: h.at(9, 3, 7)),
            ])
            try h.store.upsert(incidents: [
                h.incident("inc_synthetic_01", name: "Slow responses for Example 1.0", published: h.sep4(9, 2),
                           impacts: [ComponentImpact(componentID: "comp_other", status: "degraded_performance", start: h.sep4(9, 2))]),
                h.incident("inc_synthetic_02", name: "Slow responses for Sample 2.0", published: h.sep4(9, 2), impacts: []),
            ])
            let outcomes = try h.evaluate(through: h.sep4(9, 10))
            #expect(outcomes.map(\.scope) == ["inc_synthetic_01"])
            #expect(outcomes.first?.transition == .fired(onset: h.sep4(9, 2), severity: .amber))
            // With no watched impact, the incident's own impacts rank it: degraded performance is 1.
            #expect(try h.episodes(.incident).first?.worstValue == 1)
        }
    }

    @Test func incidentRedForOutageImpact() throws {
        try withRules { h in
            try h.seedComponents()
            try h.store.upsert(incidents: [
                h.incident(published: h.sep4(9, 2), impacts: [ComponentImpact(componentID: "comp_cli", status: "partial_outage", start: h.sep4(9, 2))]),
                h.incident("inc_synthetic_02", name: "Degraded CLI", published: h.sep4(9, 2),
                           impacts: [ComponentImpact(componentID: "comp_cli", status: "degraded_performance", start: h.sep4(9, 2))]),
            ])
            let first = try h.evaluate(through: h.sep4(9, 10))
            #expect(first.map(\.transition) == [.fired(onset: h.sep4(9, 2), severity: .red), .fired(onset: h.sep4(9, 2), severity: .amber)])

            // The second incident worsens to a full outage from 09:20: one escalation.
            try h.store.upsert(incidents: [
                h.incident("inc_synthetic_02", name: "Degraded CLI", published: h.sep4(9, 2), impacts: [
                    ComponentImpact(componentID: "comp_cli", status: "degraded_performance", start: h.sep4(9, 2), end: h.sep4(9, 20)),
                    ComponentImpact(componentID: "comp_cli", status: "full_outage", start: h.sep4(9, 20)),
                ]),
            ])
            let later = try h.evaluate(through: h.sep4(9, 40))
            #expect(later.map(\.transition) == [.escalated])
            #expect(later.map(\.at) == [h.sep4(9, 20)])
            #expect(later.first?.message == "Example Status: Degraded CLI is now an outage.")
            let escalation = try #require(later.first)
            #expect(try h.events().last == [
                "ruleEscalated", RuleHarness.sourceID, "inc_synthetic_02", "Provider incident", escalation.message,
                "\(escalation.episodeID)", "https://status.example.com/incidents/inc_synthetic_02",
            ])
            let episodes = try h.episodes(.incident)
            #expect(episodes.map(\.severity) == ["red", "red"])
            #expect(episodes.map(\.worstValue) == [2, 3])
        }
    }

    @Test func incidentResolvedClears() throws {
        try withRules { h in
            try h.seedComponents()
            let impact = ComponentImpact(componentID: "comp_cli", status: "degraded_performance", start: h.sep4(9, 2))
            try h.store.upsert(incidents: [h.incident(published: h.sep4(9, 2), impacts: [impact])])
            #expect(try h.evaluate(through: h.sep4(9, 10)).count == 1)

            try h.store.upsert(incidents: [h.incident(published: h.sep4(9, 2), resolved: h.sep4(9, 30), impacts: [impact])])
            let outcomes = try h.evaluate(through: h.sep4(9, 40))
            #expect(outcomes.map(\.transition) == [.cleared])
            #expect(outcomes.map(\.at) == [h.sep4(9, 30)])
            #expect(outcomes.first?.message == "Example Status resolved: Elevated errors.")
            #expect(try h.episodes(.incident).first?.endReason == EpisodeRow.EndReason.cleared)
        }
    }

    @Test func unavailableStatusSourceDoesNotClearIncidentEpisode() throws {
        try withRules { h in
            try h.seedComponents()
            let impact = ComponentImpact(componentID: "comp_cli", status: "degraded_performance", start: h.sep4(9, 2))
            try h.store.upsert(incidents: [h.incident(published: h.sep4(9, 2), impacts: [impact])])
            #expect(try h.evaluate(through: h.sep4(9, 10)).count == 1)

            // While the source is unavailable (spec section 10) nothing about incidents is judged,
            // even when stored data says resolved.
            try h.store.upsert(incidents: [h.incident(published: h.sep4(9, 2), resolved: h.sep4(9, 20), impacts: [impact])])
            #expect(try h.evaluate(through: h.sep4(9, 30), statusAvailable: false).isEmpty)
            #expect(try h.episodes(.incident).first?.endedAt == nil)
            #expect(try h.store.openEpisodes().map(\.rule) == [RuleID.incident.rawValue])

            // Available again: it clears at the next evaluated point.
            let outcomes = try h.evaluate(through: h.sep4(9, 35))
            #expect(outcomes.map(\.transition) == [.cleared])
            #expect(outcomes.map(\.at) == [h.sep4(9, 35)])
        }
    }

    // MARK: Settings and history

    @Test func disabledRuleWritesNothing() throws {
        try withRules { h in
            try h.seedUsual()
            try h.seedComponents()
            try h.run(30, throughput: 30, hour: 9, inputTokens: 300_000)
            try h.store.upsert(failedTurns: [h.failure(1, started: h.sep4(9, 1), completed: h.sep4(9, 2))])
            try h.store.upsert(connectionEvents: (1...4).map { h.connection($0, at: h.sep4(9, $0), kind: .disconnect) })
            try h.store.upsert(incidents: [h.incident(published: h.sep4(9, 2), impacts: [ComponentImpact(componentID: "comp_cli", status: "full_outage", start: h.sep4(9, 2))])])
            try h.store.setUsageLimit(UsageLimitSnapshot(provider: .codex, at: h.sep4(9), usedPercent: 99, windowMinutes: 300))
            h.settings.slower.enabled = false
            h.settings.faster.enabled = false
            h.settings.largePrompts.enabled = false
            h.settings.failedTurns.enabled = false
            h.settings.disconnects.enabled = false
            h.settings.incident.enabled = false
            h.settings.usageLimit.enabled = false

            #expect(try h.evaluate(through: h.sep4(10)).isEmpty)
            #expect(try RawSQLite.scalar(h.url, "SELECT COUNT(*) FROM episodes") == "0")
            #expect(try RawSQLite.scalar(h.url, "SELECT COUNT(*) FROM events") == "0")
            #expect(try RawSQLite.scalar(h.url, "SELECT COUNT(*) FROM eval_points") == "0")
            let ruleIDs = RuleID.allCases.map { "'\($0.rawValue)'" }.joined(separator: ", ")
            #expect(try RawSQLite.scalar(h.url, "SELECT COUNT(*) FROM rule_state WHERE rule IN (\(ruleIDs))") == "0")
            #expect(try RawSQLite.scalar(h.url, "SELECT COUNT(*) FROM failed_turns WHERE evaluated_at IS NOT NULL") == "0")
        }
        try withRules { h in
            // Only "Slower than usual" off: no slower rows, but faster still records the points.
            try h.seedUsual()
            try h.run(30, throughput: 30, hour: 9)
            h.settings.slower.enabled = false
            #expect(try h.evaluate(through: h.sep4(9, 30)).isEmpty)
            #expect(try h.episodes(.slower).isEmpty)
            #expect(try RawSQLite.scalar(h.url, "SELECT COUNT(*) FROM rule_state WHERE rule = 'slower'") == "0")
            #expect(try h.store.evalPoints(provider: .codex, model: h.model, in: h.sep4(9)...h.sep4(9, 30)).count == 7)
        }
    }

    @Test func disablingRuleEndsItsOpenEpisodeSilently() throws {
        try withRules { h in
            try h.seedUsual()
            try h.run(30, throughput: 30, hour: 9)
            try h.run(20, throughput: 40, hour: 11)
            let fired = try h.evaluate(through: h.sep4(9, 20))
            #expect(fired.map(\.transition) == [.fired(onset: h.sep4(8, 55), severity: .amber)])
            // While the episode is open, Sep 4's responses from its onset are left out of usual:
            // only Sep 1–3's 60 count.
            #expect(try h.base.usual(h.at(9, 5, 12)).samples[BaselineHarness.defaultKey] == 60)

            // "Slower than usual" turned off: the episode ends at the next point, with no event,
            // no outcome and no state left.
            h.settings.slower.enabled = false
            #expect(try h.evaluate(through: h.sep4(9, 30)).isEmpty)
            let episode = try #require(try h.episodes(.slower).first)
            #expect(episode.endedAt == h.sep4(9, 25) && episode.endReason == EpisodeRow.EndReason.ruleDisabled)
            #expect(approximately(episode.worstValue, 0.75))
            #expect(try h.store.openEpisodes().isEmpty)
            #expect(try h.events().map { $0[0] } == ["ruleFired"])
            #expect(try RawSQLite.scalar(h.url, "SELECT COUNT(*) FROM rule_state WHERE rule = 'slower'") == "0")

            // Usual takes Sep 4's responses from 09:25 on again: 5 slow ones (09:25–09:29) and 20 at 11:00.
            #expect(try h.base.usual(h.at(9, 5, 12)).samples[BaselineHarness.defaultKey] == 85)
            // Still off: later points write nothing for it.
            #expect(try h.evaluate(through: h.sep4(12)).isEmpty)
            #expect(try h.episodes(.slower).count == 1)
        }
        try withRules { h in
            // Every other rule ends the same way.
            try h.seedComponents()
            try h.run(7, throughput: 40, hour: 9)
            try h.run(3, throughput: 40, hour: 9, minute: 7, inputTokens: 400_000)
            try h.store.upsert(failedTurns: [h.failure(1, started: h.sep4(9, 1), completed: h.sep4(9, 2))])
            try h.store.upsert(connectionEvents: (1...3).map { h.connection($0, at: h.sep4(9, $0), kind: .disconnect) })
            try h.store.upsert(incidents: [h.incident(published: h.sep4(9, 2), impacts: [ComponentImpact(componentID: "comp_cli", status: "degraded_performance", start: h.sep4(9, 2))])])
            try h.store.setUsageLimit(UsageLimitSnapshot(provider: .codex, at: h.sep4(9), usedPercent: 99, windowMinutes: 300))
            h.settings.usageLimit.enabled = true
            let fired = try h.evaluate(through: h.sep4(9, 10))
            let rules: Set<RuleID> = [.largePrompts, .failedTurns, .disconnects, .incident, .usageLimit]
            #expect(Set(fired.map(\.rule)) == rules)

            h.settings.largePrompts.enabled = false
            h.settings.failedTurns.enabled = false
            h.settings.disconnects.enabled = false
            h.settings.incident.enabled = false
            h.settings.usageLimit.enabled = false
            #expect(try h.evaluate(through: h.sep4(9, 15)).isEmpty)
            let ended = try RawSQLite.rows(h.url, "SELECT rule, ended_at = \(h.sep4(9, 15).timeIntervalSince1970), end_reason FROM episodes ORDER BY rule")
            #expect(ended == rules.map(\.rawValue).sorted().map { [$0, "1", "ruleDisabled"] })
            #expect(try h.events().allSatisfy { $0[0] == "ruleFired" })
            #expect(try RawSQLite.scalar(h.url, "SELECT COUNT(*) FROM rule_state WHERE rule <> 'engine'") == "0")
        }
    }

    @Test func usageLimitFiresAndClears() throws {
        try withRules { h in
            h.settings.usageLimit.enabled = true
            try h.store.setUsageLimit(UsageLimitSnapshot(provider: .codex, at: h.sep4(9, 3), usedPercent: 92.4, windowMinutes: 300, resetsAt: h.sep4(9, 22)))
            let outcomes = try h.evaluate(through: h.sep4(9, 30))
            // Before the snapshot nothing is known; at the reset it clears.
            #expect(outcomes.map(\.at) == [h.sep4(9, 5), h.sep4(9, 25)])
            #expect(outcomes[0].transition == .fired(onset: h.sep4(9, 3), severity: .amber))
            #expect(outcomes[0].message == "92% of the 300-minute limit used. Resets at 09:22.")
            #expect(outcomes[1].transition == .cleared)
            #expect(outcomes[1].message == "Usage is back under the limit you set.")
        }
    }

    @Test func historyStoresUsualInEffectAtTheTime() throws {
        try withRules { h in
            try h.seedUsual()
            try h.run(30, throughput: 30, hour: 9)
            try h.evaluate(through: h.sep4(9, 30))
            let before = try h.store.evalPoints(provider: .codex, model: h.model, in: h.sep4(9, 10)...h.sep4(9, 10))
            #expect(approximately(before.first?.mixUsual, 40))

            // Accept the slow day as usual (spec section 8): usual becomes 30 from now on.
            try h.base.engine.accept(provider: .codex, model: h.model, since: h.base.localDay(9, 4), at: h.sep4(12))
            try h.run(30, throughput: 30, hour: 13)
            try h.evaluate(through: h.sep4(13, 30))

            let after = try h.store.evalPoints(provider: .codex, model: h.model, in: h.sep4(9, 10)...h.sep4(9, 10))
            #expect(after == before)
            let later = try h.store.evalPoints(provider: .codex, model: h.model, in: h.sep4(13, 15)...h.sep4(13, 15))
            #expect(approximately(later.first?.mixUsual, 30))
            #expect(approximately(later.first?.speedIndex, 1))
        }
    }

    @Test func evaluationResumesAfterLastPointAndIsDeterministic() throws {
        // Two engines over the same data, one run in a single call and one in many calls,
        // produce the same episodes: state lives in the database, not the engine.
        var results: [[String]] = []
        for split in [false, true] {
            try withRules { h in
                try h.seedUsual()
                try h.run(30, throughput: 30, hour: 9)
                try h.run(40, throughput: 40, hour: 9, minute: 30)
                if split {
                    for minute in stride(from: 0, through: 120, by: 15) {
                        let engine = RuleEngine(store: h.store, baseline: BaselineEngine(store: h.store, calendar: h.calendar), calendar: h.calendar, naming: [:])
                        let points = EvaluationPoints.after(try h.store.lastEvaluatedPoint(unit: "codex"), through: h.sep4(9).addingTimeInterval(Double(minute) * 60), earliest: h.sep4(9))
                        try engine.evaluate(points: points, unit: .provider(.codex), settings: h.settings, watchedComponents: [])
                    }
                } else {
                    try h.evaluate(through: h.sep4(11))
                }
                #expect(try h.store.lastEvaluatedPoint(unit: "codex") == h.sep4(11))
                results.append(try RawSQLite.rows(h.url, "SELECT rule, onset_at, fired_at, IFNULL(ended_at, 'open'), IFNULL(end_reason, '-'), severity, worst_value FROM episodes ORDER BY id").map { $0.joined(separator: " ") })
            }
        }
        #expect(results[0] == results[1])
        #expect(results[0].count == 1)
    }
}
