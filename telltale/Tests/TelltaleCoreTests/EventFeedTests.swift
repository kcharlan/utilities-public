import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

/// Spec section 9.2's Events list and section 8's Undo contract, on a seeded store
/// (`BaselineHarness`: Sep 2026 in New York, the synthetic model "Example").
private enum Feed {
    static let naming = SyntheticNaming()

    static func load(_ h: BaselineHarness, limit: Int = 50) throws -> [FeedEvent] {
        try EventFeed.load(store: h.store, limit: limit, naming: { naming.displayName(model: $1) }, calendar: h.calendar,
            sources: [SourceSummary(provider: .codex, name: "Codex", statusName: "Example Status", statusSourceID: "example-status", signals: [.speed, .provider], naming: naming)])
    }

    @discardableResult
    static func fired(_ h: BaselineHarness, rule: RuleID, scope: String = Synth.model, severity: LampColor, at: Date, ended: Date? = nil,
                      endReason: String? = nil, body: String, link: URL? = nil) throws -> Int64 {
        let direction: Direction? = rule == .slower ? .slower : rule == .faster ? .faster : nil
        let id = try h.store.insertEpisode(EpisodeRow(
            rule: rule.rawValue, provider: ProviderID.codex.rawValue, scope: scope, direction: direction, onset: at.addingTimeInterval(-600),
            firedAt: at, endedAt: ended, endReason: endReason, severity: severity.rawValue, worstValue: 0.7))
        try h.store.insertEvent(EventRow(
            at: at, kind: EventKind.ruleFired, provider: ProviderID.codex.rawValue, scope: scope, title: rule.title, body: body, episodeID: id,
            link: link))
        return id
    }
}

@Suite struct EventFeedTests {
    @Test func reversedEpisodeEndIsNotListed() throws {
        try withBaseline { h in
            try Feed.fired(h, rule: .slower, severity: .amber, at: h.at(9, 4, 9), ended: h.at(9, 4, 10), endReason: EpisodeRow.EndReason.reversed, body: "synthetic")
            let feed = try Feed.load(h)
            #expect(feed.count == 1 && feed.first?.kind == .slowdown)
        }
    }
    @Test func compactionEventsHaveAFeedKind() throws {
        try withBaseline { h in
            try Feed.fired(h, rule: .compactions, scope: "*", severity: .amber, at: h.at(9, 4, 9), body: "synthetic")
            #expect(try Feed.load(h).first?.kind == .compactions)
        }
    }
    @Test func silentEndsNameUsageAndStatusSourcesOnce() throws {
        try withBaseline { h in
            let sources = [
                SourceSummary(provider: .codex, name: "Codex", statusName: "Synthetic Status", statusSourceID: "synthetic-status", signals: [.speed, .provider], naming: SyntheticNaming()),
                SourceSummary(provider: ProviderID(rawValue: "synthetic-other"), name: "Synthetic Other", statusName: "Synthetic Status", statusSourceID: "synthetic-status", signals: [.speed, .provider], naming: SyntheticNaming()),
            ]
            for (provider, rule, reason) in [("codex", RuleID.slower, EpisodeRow.EndReason.idleEnded),
                                             ("synthetic-other", .slower, EpisodeRow.EndReason.ruleDisabled),
                                             ("synthetic-status", .incident, EpisodeRow.EndReason.ruleDisabled)] {
                try h.store.insertEpisode(EpisodeRow(rule: rule.rawValue, provider: provider, scope: "synthetic", direction: nil,
                    onset: h.at(9, 4, 8), firedAt: h.at(9, 4, 9), endedAt: h.at(9, 4, 10), endReason: reason,
                    severity: LampColor.amber.rawValue, worstValue: 0.7))
            }
            let bodies = try EventFeed.load(store: h.store, limit: 10, sources: sources).filter { $0.kind == .ended }.map(\.body)
            #expect(Set(bodies) == ["Codex: Ended with no recent responses to judge.",
                                    "Synthetic Other: Ended because the rule was turned off.",
                                    "Synthetic Status: Ended because the rule was turned off."])
        }
    }
    @Test func connectionGapAndBaselineEventsArePrefixed() throws {
        try withBaseline { h in
            try h.seedLastingSlowdown()
            try h.store.recordConnectionGap(provider: .codex, providerName: "Synthetic Provider", gap: DateInterval(start: h.at(9, 4, 6), end: h.at(9, 4, 7)), calendar: h.calendar)
            let accepted = try h.engine.accept(provider: .codex, providerName: "Synthetic Provider", model: h.model, since: h.localDay(9, 15), at: h.at(9, 18, 10))
            try h.engine.undo(epochID: accepted.epochID, providerName: "Synthetic Provider", at: h.at(9, 18, 11))
            let events = try Feed.load(h).filter { [.historyGap, .baselineAccepted, .baselineUndone].contains($0.kind) }
            #expect(events.count == 3)
            #expect(events.allSatisfy { $0.body.hasPrefix("Synthetic Provider: ") })
        }
    }
    @Test func newestFirst() throws {
        try withBaseline { h in
            try h.store.recordConnectionGap(provider: .codex, gap: DateInterval(start: h.at(9, 4, 6), end: h.at(9, 4, 7)), calendar: h.calendar)
            try h.store.recordRSSItems(
                [RSSItem(title: "Synthetic maintenance", link: URL(string: "https://status.example.com/incidents/rss_01")!, publishedAt: h.at(9, 4, 8))],
                source: "example-status", displayName: "Example Status")
            try Feed.fired(h, rule: .slower, severity: .amber, at: h.at(9, 4, 9), ended: h.at(9, 4, 9, 30),
                           endReason: EpisodeRow.EndReason.idleEnded, body: "Example is 26% slower than usual for prompts this size. Since 08:50.")
            try Feed.fired(h, rule: .disconnects, scope: "*", severity: .amber, at: h.at(9, 4, 9, 10), ended: h.at(9, 4, 9, 40),
                           endReason: EpisodeRow.EndReason.ruleDisabled, body: Copy.disconnectsFired(count: 5, windowMinutes: 15))
            // Two failed collector runs in a row show as one entry; a success ends the streak.
            for (minute, outcome) in [(0, RunOutcome.succeeded), (5, .failed), (10, .skipped), (15, .failed), (20, .succeeded)] {
                let run = try h.store.beginRun(at: h.at(9, 4, 10, minute))
                try h.store.finishRun(run, at: h.at(9, 4, 10, minute).addingTimeInterval(2), outcome: outcome,
                                      detail: outcome == .failed ? "synthetic history locked" : "")
            }

            let feed = try Feed.load(h)
            #expect(feed.map(\.at) == [
                h.at(9, 4, 10, 15).addingTimeInterval(2), h.at(9, 4, 9, 40), h.at(9, 4, 9, 30), h.at(9, 4, 9, 10), h.at(9, 4, 9),
                h.at(9, 4, 8), h.at(9, 4, 6),
            ])
            #expect(feed.map(\.kind) == [.collectorFailed, .ended, .ended, .disconnects, .slowdown, .statusPost, .historyGap])
            #expect(feed[0].body == Copy.collectorRunsFailed(
                count: 2, from: h.at(9, 4, 10, 5).addingTimeInterval(2), to: h.at(9, 4, 10, 15).addingTimeInterval(2),
                reason: "synthetic history locked", calendar: h.calendar))
            #expect(feed[0].color == .red)
            #expect(feed[1].title == RuleID.disconnects.title && feed[1].body == "Codex: Ended because the rule was turned off.")
            #expect(feed[2].title == RuleID.slower.title && feed[2].body == "Codex: Ended with no recent responses to judge.")
            #expect(feed[4].color == .amber)
            #expect(feed[6].endsAt == h.at(9, 4, 7))
            #expect(Set(feed.map(\.id)).count == feed.count)
            #expect(try Feed.load(h, limit: 3).map(\.kind) == [.collectorFailed, .ended, .ended])
        }
    }

    @Test func eachAcceptanceOffersUndoUntilUndone() throws {
        try withBaseline { h in
            try h.seedLastingSlowdown()
            try h.seedLastingSlowdown(model: Synth.otherModel)
            let example = try h.engine.accept(provider: .codex, model: h.model, since: h.localDay(9, 15), at: h.at(9, 18, 10, 0))
            let sample = try h.engine.accept(provider: .codex, model: Synth.otherModel, since: h.localDay(9, 15), at: h.at(9, 18, 10, 5))

            var accepted = try Feed.load(h).filter { $0.kind == .baselineAccepted }
            #expect(accepted.map(\.undoableEpochID) == [sample.epochID, example.epochID])
            #expect(accepted.allSatisfy { $0.undoneAt == nil && $0.undoConfirmation == nil })
            // Display names replace the raw model ids the collector-side text carries.
            #expect(accepted.last?.body == Copy.acceptance(model: "Example", percent: example.percentChange))

            try h.engine.undo(epochID: example.epochID, at: h.at(9, 18, 11))
            let feed = try Feed.load(h)
            accepted = feed.filter { $0.kind == .baselineAccepted }
            #expect(accepted.map(\.undoableEpochID) == [sample.epochID, nil])
            #expect(accepted.last?.undoneAt == h.at(9, 18, 11))
            #expect(feed.first?.kind == .baselineUndone)
            #expect(feed.first?.body == Copy.baselineRestored(model: "Example"))
            #expect(feed.first?.undoableEpochID == nil)
        }
    }

    @Test func olderAcceptanceUndoRequiresConfirmation() throws {
        try withBaseline { h in
            try h.seedLastingSlowdown()
            let older = try h.engine.accept(provider: .codex, model: h.model, since: h.localDay(9, 15), at: h.at(9, 18, 10, 0))
            let newer = try h.engine.accept(provider: .codex, model: h.model, since: h.localDay(9, 16), at: h.at(9, 18, 10, 10))

            var accepted = try Feed.load(h).filter { $0.kind == .baselineAccepted }
            #expect(accepted.map(\.undoableEpochID) == [newer.epochID, older.epochID])
            #expect(accepted[0].undoConfirmation == nil)
            #expect(accepted[1].undoConfirmation == Copy.undoEarlierAcceptanceConfirmation(model: "Example"))

            // Once the newer one is undone, the older one is the latest live acceptance again.
            try h.engine.undo(epochID: newer.epochID, at: h.at(9, 18, 11))
            accepted = try Feed.load(h).filter { $0.kind == .baselineAccepted }
            #expect(accepted.map(\.undoableEpochID) == [nil, older.epochID])
            #expect(accepted[1].undoConfirmation == nil)
        }
    }

    /// Confirming an older acceptance's Undo also undoes the newer one (spec section 8): both
    /// entries then show their undone state and neither offers Undo.
    @Test func cascadeUndoMarksTheNewerAcceptanceUndone() throws {
        try withBaseline { h in
            try h.seedLastingSlowdown()
            let older = try h.engine.accept(provider: .codex, model: h.model, since: h.localDay(9, 15), at: h.at(9, 18, 10, 0))
            let newer = try h.engine.accept(provider: .codex, model: h.model, since: h.localDay(9, 16), at: h.at(9, 18, 10, 10))
            let before = try Feed.load(h).filter { $0.kind == .baselineAccepted }
            #expect(before.map(\.undoableEpochID) == [newer.epochID, older.epochID])
            #expect(before[1].undoConfirmation != nil)

            try h.engine.undo(epochID: older.epochID, at: h.at(9, 18, 11))
            let after = try Feed.load(h).filter { $0.kind == .baselineAccepted }
            #expect(after.map(\.undoableEpochID) == [nil, nil])
            #expect(after.map(\.undoneAt) == [h.at(9, 18, 11), h.at(9, 18, 11)])
            #expect(after.allSatisfy { $0.undoConfirmation == nil })
        }
    }

    /// Collector failure streaks are read only as far back as the feed shows: with a limit of 2,
    /// the two newest streaks come back whole, however many runs are kept.
    @Test func collectorStreaksAreReadOnlyAsFarAsTheLimit() throws {
        try withBaseline { h in
            // 60 streaks of 5 failures, each ended by a success, five minutes apart: 360 runs, so the
            // feed reads more than one page and a streak straddles the page boundary.
            var minute = 0
            for _ in 0..<60 {
                for outcome in [RunOutcome.failed, .failed, .failed, .failed, .failed, .succeeded] {
                    let start = h.at(9, 4, 0).addingTimeInterval(Double(minute) * 60)
                    let run = try h.store.beginRun(at: start)
                    try h.store.finishRun(run, at: start.addingTimeInterval(2), outcome: outcome, detail: outcome == .failed ? "synthetic failure" : "")
                    minute += 5
                }
            }
            let feed = try Feed.load(h, limit: 2)
            #expect(feed.map(\.kind) == [.collectorFailed, .collectorFailed])
            let last = h.at(9, 4, 0).addingTimeInterval(Double(minute - 10) * 60 + 2)
            #expect(feed.first?.at == last)
            #expect(feed.first?.body == Copy.collectorRunsFailed(
                count: 5, from: last.addingTimeInterval(-20 * 60), to: last, reason: "synthetic failure", calendar: h.calendar))
            #expect(feed.last?.at == last.addingTimeInterval(-30 * 60))
            // Past the first page, every streak still comes back whole.
            let long = try Feed.load(h, limit: 50)
            #expect(long.count == 50 && long.allSatisfy { $0.body.hasPrefix("5 collector runs failed from ") })
        }
    }

    @Test func statusPostsCarryLinks() throws {
        try withBaseline { h in
            let post = URL(string: "https://status.example.com/incidents/rss_01")!
            let incident = URL(string: "https://status.example.com/incidents/inc_synthetic_01")!
            try h.store.recordRSSItems(
                [RSSItem(title: "Synthetic maintenance", link: post, publishedAt: h.at(9, 4, 8))], source: "example-status",
                displayName: "Example Status")
            try Feed.fired(h, rule: .incident, scope: "inc_synthetic_01", severity: .amber, at: h.at(9, 4, 9),
                           body: Copy.incidentFired(source: "Example Status", name: "Elevated errors"), link: incident)
            try Feed.fired(h, rule: .failedTurns, scope: "*", severity: .red, at: h.at(9, 4, 10), body: Copy.failedTurns(count: 3, reasons: ["model at capacity"]))

            let feed = try Feed.load(h)
            #expect(feed.map(\.kind) == [.failedTurns, .incident, .statusPost])
            #expect(feed.map(\.link) == [nil, incident, post])
            #expect(feed[2].body == "Example Status posted: Synthetic maintenance.")
            #expect(feed.map(\.color) == [.red, .amber, nil])
        }
    }
}

private struct FeedCollisionNaming: ModelNaming {
    func displayName(model: String) -> String { "Example" }
    func incidentTitle(_ title: String, names model: String) -> Bool { false }
}

@Test func historicalSpeedEventsDisambiguateVisibleModels() throws {
    try withBaseline { h in
        try Feed.fired(h, rule: .slower, scope: "synthetic-a", severity: .amber, at: h.at(9, 4, 9), body: "Codex: Example is 20% slower than usual.")
        try Feed.fired(h, rule: .slower, scope: "synthetic-b", severity: .amber, at: h.at(9, 4, 10), body: "Codex: Example is 30% slower than usual.")
        let source = SourceSummary(provider: .codex, name: "Codex", statusName: "Example", statusSourceID: "synthetic", signals: [.speed], naming: FeedCollisionNaming())
        let events = try EventFeed.load(store: h.store, limit: 10, sources: [source])
        #expect(events.contains { $0.body.contains("Example (a) is 20%") })
        #expect(events.contains { $0.body.contains("Example (b) is 30%") })
    }
}

@Test func historicalRuleEventNamesProvider() throws {
    try withBaseline { h in
        try Feed.fired(h, rule: .disconnects, scope: "*", severity: .amber, at: h.at(9, 4, 9), body: "3 synthetic disconnects.")
        #expect(try Feed.load(h).first?.body == "Codex: 3 synthetic disconnects.")
    }
}

@Test func oldSuffixesAreReplacedUsingVisibleModels() throws {
    try withBaseline { h in
        let ids = ["synthetic-a-shared", "synthetic-b-shared", "synthetic-a-other", "synthetic-b-other"]
        for (index, id) in ids.enumerated() {
            let suffix = index.isMultiple(of: 2) ? "a" : "b"
            try Feed.fired(h, rule: .slower, scope: id, severity: .amber, at: h.at(9, 4, 9, index), body: "Codex: Example (\(suffix)) is 20% slower than usual.")
        }
        let source = SourceSummary(provider: .codex, name: "Codex", statusName: "Example", statusSourceID: "synthetic", signals: [.speed], naming: FeedCollisionNaming())
        let events = try EventFeed.load(store: h.store, limit: 10, sources: [source])
        #expect(Set(events.map(\.body)).count == 4)
        #expect(Set(events.compactMap(\.modelID)) == Set(ids))
        for event in events {
            let id = try #require(event.modelID)
            let expected = id.replacingOccurrences(of: "synthetic-", with: "")
            #expect(event.body == "Codex: Example (\(expected)) is 20% slower than usual.")
        }
    }
}
