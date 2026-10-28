import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

/// Spec section 9.1's panel, read from a seeded store (`RuleHarness`: Sep 2026 in New York, the
/// synthetic model "Example" and the status source "Example Status").
private enum Panel {
    static let signals: Set<Signal> = [.speed, .errors, .link, .provider, .load]
    static let codex = SourceSummary(provider: .codex, name: "Codex", statusName: "Example Status", statusSourceID: RuleHarness.sourceID, signals: signals, naming: SyntheticNaming())
    static let healthy = CollectorHealthReport(
        installed: .green, loaded: .green, lastRun: .green, onSchedule: .green, problems: [], needsRepair: false, footer: "", notify: false)

    static func load(_ h: RuleHarness, at now: Date, health: CollectorHealthReport? = healthy, sources: [SourceSummary] = [codex]) throws -> PanelSnapshot {
        try PanelSnapshot.load(store: h.store, baseline: h.base.engine, health: health, sources: sources, now: now, calendar: h.calendar)
    }

    /// An open episode with its fired event.
    @discardableResult
    static func episode(
        _ h: RuleHarness, rule: RuleID, provider: String = "codex", scope: String = Synth.model, severity: LampColor, fired: Date, body: String
    ) throws -> Int64 {
        let direction: Direction? = rule == .slower ? .slower : rule == .faster ? .faster : nil
        let id = try h.store.insertEpisode(EpisodeRow(
            rule: rule.rawValue, provider: provider, scope: scope, direction: direction, onset: fired.addingTimeInterval(-900), firedAt: fired,
            severity: severity.rawValue, worstValue: 0.7))
        try h.store.insertEvent(EventRow(at: fired, kind: EventKind.ruleFired, provider: provider, scope: scope, title: rule.title, body: body, episodeID: id))
        return id
    }
}

@Suite struct PanelSnapshotTests {
    @Test func quietSnapshotHasNoLamps() throws {
        try withRules { h in
            try h.seedUsual()
            try h.run(30, throughput: 40, hour: 9)
            try h.evaluate(through: h.sep4(9, 30))
            let run = try h.store.beginRun(at: h.sep4(9, 30))
            try h.store.finishRun(run, at: h.sep4(9, 30).addingTimeInterval(4), outcome: .succeeded)
            // Neither an episode a disabled rule ended nor a connection-history gap is an alert.
            try h.store.insertEpisode(EpisodeRow(
                rule: RuleID.disconnects.rawValue, provider: "codex", scope: "*", direction: nil, onset: h.sep4(8), firedAt: h.sep4(8, 5),
                endedAt: h.sep4(8, 30), endReason: EpisodeRow.EndReason.ruleDisabled, severity: LampColor.amber.rawValue, worstValue: 3))
            try h.store.recordConnectionGap(provider: .codex, gap: DateInterval(start: h.sep4(7), end: h.sep4(8)), calendar: h.calendar)

            let snapshot = try Panel.load(h, at: h.sep4(9, 31))
            #expect(snapshot.signals == [.speed, .errors, .link, .provider, .load, .collector])
            #expect(snapshot.lamps.values.allSatisfy { $0 == nil })
            #expect(snapshot.mostSevere == nil)
            #expect(snapshot.alerts.isEmpty)
            #expect(snapshot.checkedAt == h.sep4(9, 30).addingTimeInterval(4))
            #expect(snapshot.collector == .green)
            #expect(snapshot.footer == "Collector running, every 5 min")
            #expect(snapshot.labels[.provider] == "Example Status" && snapshot.labels[.speed] == "Speed")
        }
    }

    @Test func slowEpisodeLightsSpeedAmber() throws {
        try withRules { h in
            try h.seedUsual()
            try h.run(30, throughput: 30, hour: 9)
            try h.evaluate(through: h.sep4(9, 20))
            let snapshot = try Panel.load(h, at: h.sep4(9, 22))
            #expect(snapshot.lamps[.speed] == .amber)
            #expect(snapshot.mostSevere == .amber)
            #expect(snapshot.alerts == [PanelSnapshot.Alert(color: .amber, text: "Example is 25% slower than usual for prompts this size. Since 08:55.")])
            #expect([Signal.errors, .link, .provider, .load, .collector].allSatisfy { snapshot.lamps[$0] == .some(nil) })
        }
    }

    @Test func redOutranksAmberInAlertOrder() throws {
        try withRules { h in
            try Panel.episode(h, rule: .faster, scope: Synth.otherModel, severity: .blue, fired: h.sep4(9, 20), body: "Sample is faster.")
            try Panel.episode(h, rule: .slower, severity: .amber, fired: h.sep4(9, 0), body: "Example is slower.")
            try Panel.episode(h, rule: .largePrompts, severity: .amber, fired: h.sep4(9, 10), body: "Large prompts.")
            try Panel.episode(h, rule: .failedTurns, scope: "*", severity: .red, fired: h.sep4(8, 0), body: "1 turn failed: model at capacity")
            let snapshot = try Panel.load(h, at: h.sep4(9, 30))
            #expect(snapshot.alerts.map(\.text) == ["1 turn failed: model at capacity", "Large prompts.", "Example is slower.", "Sample is faster."])
            #expect(snapshot.alerts.map(\.color) == [.red, .amber, .amber, .blue])
            #expect(snapshot.lamps[.speed] == .amber && snapshot.lamps[.errors] == .red && snapshot.lamps[.load] == .amber)
            #expect(snapshot.mostSevere == .red)

            // An escalation rewords the alert and turns it red.
            let escalated = try Panel.episode(h, rule: .slower, scope: "example-model-3.0", severity: .amber, fired: h.sep4(9, 25), body: "Fired wording.")
            var episode = try #require(try h.store.openEpisodes().first { $0.id == escalated })
            episode.severity = LampColor.red.rawValue
            try h.store.updateEpisode(episode)
            try h.store.insertEvent(EventRow(
                at: h.sep4(9, 28), kind: EventKind.ruleEscalated, provider: "codex", scope: "example-model-3.0", title: "Slower than usual",
                body: "Escalated wording.", episodeID: escalated))
            let later = try Panel.load(h, at: h.sep4(9, 30))
            #expect(later.alerts.prefix(2).map(\.text) == ["Escalated wording.", "1 turn failed: model at capacity"])
            #expect(later.lamps[.speed] == .red)
        }
    }

    @Test func modelRowsOnlyForRecentModels() throws {
        try withRules { h in
            try h.seedUsual()
            try h.seedUsual(model: Synth.otherModel)
            try h.run(30, throughput: 40, hour: 9)
            // The other model's last response ends at 06:29, more than 3 hours before 09:30.
            try h.run(30, throughput: 40, hour: 6, model: Synth.otherModel)
            try h.evaluate(from: h.sep4(6), through: h.sep4(9, 30))
            let snapshot = try Panel.load(h, at: h.sep4(9, 30))
            let row = try #require(snapshot.models.first)
            #expect(snapshot.models.count == 1)
            #expect(row.model == Synth.model && row.name == "Example" && row.id == "codex/\(Synth.model)")
            #expect(approximately(row.tps, 40) && approximately(row.usual, 40))
            #expect(row.sparkline.count == 36)
            #expect(approximately(row.sparkline.last ?? nil, 40))
            #expect(row.sparkline.first == .some(nil))

            // Still listed while its last response is within the 3 hours.
            #expect(Set(try Panel.load(h, at: h.sep4(9, 28)).models.map(\.model)) == [Synth.model, Synth.otherModel])
            #expect(try Panel.load(h, at: h.sep4(9, 0).addingTimeInterval(-1)).models.map(\.model) == [Synth.otherModel])
        }
    }

    /// The mockup colors a slowed model's tok/s and sparkline in its lamp color: an open speed
    /// episode scoped to that model sets the row's color; other rules and models don't.
    @Test func speedEpisodeColorsItsModelRow() throws {
        try withRules { h in
            try h.seedUsual()
            try h.seedUsual(model: Synth.otherModel)
            try h.run(30, throughput: 40, hour: 9)
            try h.run(30, throughput: 40, hour: 9, model: Synth.otherModel)
            try Panel.episode(h, rule: .slower, severity: .amber, fired: h.sep4(9, 20), body: "Example is slower.")
            try Panel.episode(h, rule: .largePrompts, scope: "*", severity: .red, fired: h.sep4(9, 21), body: "Large prompts.")
            let snapshot = try Panel.load(h, at: h.sep4(9, 30))
            #expect(snapshot.models.first { $0.model == Synth.model }?.color == .amber)
            #expect(snapshot.models.first { $0.model == Synth.otherModel }?.color == nil)

            // A faster episode colors its own model, blue.
            try Panel.episode(h, rule: .faster, scope: Synth.otherModel, severity: .blue, fired: h.sep4(9, 22), body: "Sample is faster.")
            let later = try Panel.load(h, at: h.sep4(9, 30))
            #expect(later.models.first { $0.model == Synth.otherModel }?.color == .blue)
            #expect(later.models.first { $0.model == Synth.model }?.color == .amber)
        }
    }

    /// The checked time is the newest succeeded run, however many failures followed it.
    @Test func checkedTimeOutlastsManyFailures() throws {
        try withRules { h in
            let succeeded = try h.store.beginRun(at: h.sep4(8))
            try h.store.finishRun(succeeded, at: h.sep4(8).addingTimeInterval(4), outcome: .succeeded)
            for index in 0..<25 {
                let start = h.sep4(8, 5).addingTimeInterval(Double(index) * 60)
                let failed = try h.store.beginRun(at: start)
                try h.store.finishRun(failed, at: start.addingTimeInterval(2), outcome: .failed, detail: "synthetic failure")
            }
            #expect(try Panel.load(h, at: h.sep4(9, 30)).checkedAt == h.sep4(8).addingTimeInterval(4))
        }
    }

    @Test func usualIsMixMatched() throws {
        try withRules { h in
            // Usual: 40 tok/s under 50k input, 20 tok/s at 100-200k.
            for day in 1...3 {
                try h.base.add(20, throughput: 40, month: 9, day: day, hour: 9)
                try h.base.add(20, throughput: 20, month: 9, day: day, hour: 12, inputTokens: 150_000)
            }
            // The last hour: 9 small prompts at their usual and 12 large ones at theirs.
            try h.run(9, throughput: 40, hour: 9)
            try h.run(12, throughput: 20, hour: 9, minute: 10, inputTokens: 150_000)
            let row = try #require(try Panel.load(h, at: h.sep4(9, 30)).models.first)
            // Running at usual for this mix: no gap, though the mix is slower than small prompts alone.
            #expect(approximately(row.tps, 20) && approximately(row.usual, 20))
        }
    }

    @Test func thinDataNote() throws {
        try withRules { h in
            try h.seedUsual()
            try h.run(5, throughput: 40, hour: 9)
            try h.evaluate(through: h.sep4(9, 10))
            let row = try #require(try Panel.load(h, at: h.sep4(9, 11)).models.first)
            #expect(row.note == "Not enough recent responses to judge speed")
        }
    }

    @Test func learningNote() throws {
        try withRules { h in
            try h.seedUsual()
            try h.run(30, throughput: 40, hour: 9)
            try h.evaluate(through: h.sep4(9, 30))
            let row = try #require(try Panel.load(h, at: h.sep4(9, 30)).models.first)
            #expect(row.note == "Learning usual: 3 of 14 days")
        }
    }

    @Test func shiftPromptIncluded() throws {
        try withRules { h in
            try h.seedUsual()
            for day in 1...3 {
                try h.base.episode(
                    onset: h.at(9, day, 9, 45), fired: h.at(9, day, 10), ended: h.at(9, day, 11), endReason: EpisodeRow.EndReason.cleared, worst: 0.75)
            }
            let snapshot = try Panel.load(h, at: h.at(9, 3, 12))
            let shift = try #require(snapshot.shift)
            #expect(shift.model == Synth.model && shift.direction == .slower && shift.days == 3)
            #expect(shift.firstDay == LocalDay(year: 2026, month: 9, day: 1))
            #expect(snapshot.shiftText == "Example has been about 25% slower than usual for 3 days. Accept as usual?")
            // A shift is not an alert: nothing is lit.
            #expect(snapshot.alerts.isEmpty && snapshot.mostSevere == nil)
        }
    }

    /// R31: the lasting-shift prompt links to the status-page incidents in its period.
    @Test func shiftPromptLinksIncidentsInItsPeriod() throws {
        try withRules { h in
            try h.seedUsual()
            for day in 1...3 {
                try h.base.episode(
                    onset: h.at(9, day, 9, 45), fired: h.at(9, day, 10), ended: h.at(9, day, 11), endReason: EpisodeRow.EndReason.cleared, worst: 0.75)
            }
            try h.store.upsert(incidents: [h.incident("inc_synthetic_07", name: "Synthetic slow responses", published: h.at(9, 2, 9), resolved: h.at(9, 2, 12), impacts: [])])
            let shift = try #require(try Panel.load(h, at: h.at(9, 3, 12)).shift)
            #expect(shift.incidents == [IncidentLink(
                id: "inc_synthetic_07", name: "Synthetic slow responses", link: URL(string: "https://status.example.com/incidents/inc_synthetic_07")!)])
        }
    }

    @Test func collectorOffFooter() throws {
        try withRules { h in
            let off = CollectorHealth.evaluate(
                enabled: false, installedExecutable: nil, installedAt: nil, currentExecutable: URL(fileURLWithPath: "/nonexistent-synthetic/Telltale"),
                loaded: false, runs: [], intervalMinutes: 5, sourceStates: [], now: h.sep4(9), calendar: h.calendar)
            let snapshot = try Panel.load(h, at: h.sep4(9), health: off)
            #expect(snapshot.footer == "Collector off. Turn it on to keep watching.")
            #expect(snapshot.collector == .unlit && snapshot.lamps[.collector] == .some(nil) && snapshot.mostSevere == nil)

            // A health problem lights Collector red and takes the footer.
            var failing = Panel.healthy
            failing.loaded = .red
            failing.problems = ["Telltale's collector isn't loaded. Open the Collector view to turn it back on."]
            let red = try Panel.load(h, at: h.sep4(9), health: failing)
            #expect(red.lamps[.collector] == .red && red.collector == .red && red.mostSevere == .red)
            #expect(red.footer == failing.problems[0])
        }
    }

    @Test func lampsLimitedToDeclaredSignals() throws {
        try withRules { h in
            let speedOnly = SourceSummary(provider: .codex, name: "Codex", statusName: "Example Status", statusSourceID: RuleHarness.sourceID, signals: [.speed], naming: SyntheticNaming())
            try Panel.episode(h, rule: .failedTurns, scope: "*", severity: .red, fired: h.sep4(9), body: "1 turn failed: model at capacity")
            try Panel.episode(h, rule: .incident, provider: RuleHarness.sourceID, scope: "inc_synthetic_01", severity: .amber, fired: h.sep4(9), body: "Example Status: Elevated errors.")
            try Panel.episode(h, rule: .slower, provider: "example-unregistered", severity: .amber, fired: h.sep4(9), body: "Unregistered provider.")
            try Panel.episode(h, rule: .slower, severity: .amber, fired: h.sep4(9, 5), body: "Example is slower.")
            let snapshot = try Panel.load(h, at: h.sep4(9, 10), sources: [speedOnly])
            #expect(snapshot.signals == [.speed, .collector])
            #expect(snapshot.lamps[.errors] == nil && snapshot.lamps[.provider] == nil)
            #expect(snapshot.alerts.map(\.text) == ["Example is slower."])
            #expect(snapshot.lamps[.speed] == .amber)
        }
    }

    @Test func alertsNameProviderWhenSeveral() throws {
        try withRules { h in
            let other = ProviderID(rawValue: "example-other")
            let second = SourceSummary(provider: other, name: "Example Other", statusName: "Example Status", statusSourceID: RuleHarness.sourceID, signals: Panel.signals, naming: SyntheticNaming())
            try Panel.episode(h, rule: .slower, severity: .amber, fired: h.sep4(9), body: "Example is slower.")
            try Panel.episode(h, rule: .disconnects, provider: other.rawValue, scope: "*", severity: .amber, fired: h.sep4(9, 5), body: "3 disconnect or retry events in the last 60 minutes.")
            try Panel.episode(h, rule: .incident, provider: RuleHarness.sourceID, scope: "inc_synthetic_01", severity: .amber, fired: h.sep4(9, 1), body: "Example Status: Elevated errors.")
            let snapshot = try Panel.load(h, at: h.sep4(9, 10), sources: [Panel.codex, second])
            #expect(snapshot.alerts.map(\.text) == [
                "Example Other: 3 disconnect or retry events in the last 60 minutes.", "Example Status: Elevated errors.", "Codex: Example is slower.",
            ])
            // One lamp per signal across providers.
            #expect(snapshot.lamps[.speed] == .amber && snapshot.lamps[.link] == .amber && snapshot.lamps[.provider] == .amber)
            #expect(snapshot.labels[.provider] == "Example Status")

            var elsewhere = second
            elsewhere.statusName = "Other Status"
            #expect(try Panel.load(h, at: h.sep4(9, 10), sources: [Panel.codex, elsewhere]).labels[.provider] == "Status")
            // A single source's alerts are not prefixed.
            #expect(try Panel.load(h, at: h.sep4(9, 10)).alerts.map(\.text).contains("Example is slower."))
        }
    }
}
