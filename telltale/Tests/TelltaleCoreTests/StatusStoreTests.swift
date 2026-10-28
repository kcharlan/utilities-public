import Foundation
import Testing
import TelltaleTestSupport
@testable import TelltaleCore

@Suite struct StatusStoreTests {
    private static func makeStore(_ directory: URL) throws -> Store {
        try Store.open(directory.appending(path: "telltale.sqlite"), mode: .readWrite)
    }

    private static func incident(
        _ id: String, status: String = "investigating", published: TimeInterval = 0, updated: TimeInterval = 100,
        impacts: [ComponentImpact] = [], source: String = "example.status"
    ) -> IncidentRecord {
        IncidentRecord(
            source: source, id: id, name: "Synthetic incident \(id)", status: status,
            publishedAt: Synthetic.at(published), updatedAt: Synthetic.at(updated),
            link: URL(string: "https://status.example.com/incidents/\(id)")!,
            history: [StatusChange(at: Synthetic.at(published), status: "investigating")], impacts: impacts)
    }

    private static func impact(_ start: TimeInterval, _ end: TimeInterval?, component: String = "component-a") -> ComponentImpact {
        ComponentImpact(componentID: component, status: "partial_outage", start: Synthetic.at(start), end: end.map(Synthetic.at))
    }

    @Test func upsertReplacesByID() throws {
        try withScratchDirectory { directory in
            let store = try Self.makeStore(directory)
            let first = Self.incident("synthetic-01", impacts: [Self.impact(0, nil)])
            try store.upsert(incidents: [first, Self.incident("synthetic-02")])
            #expect(try store.openIncidents(source: "example.status") == [first, Self.incident("synthetic-02")])

            // Same id: the new record replaces the old one, history and impacts included.
            var resolved = first
            resolved.status = "resolved"
            resolved.updatedAt = Synthetic.at(500)
            resolved.history.append(StatusChange(at: Synthetic.at(500), status: "resolved"))
            resolved.impacts = [Self.impact(0, 480)]
            try store.upsert(incidents: [resolved])

            #expect(try store.openIncidents(source: "example.status") == [Self.incident("synthetic-02")])
            let all = try store.incidents(source: "example.status", overlapping: DateInterval(start: Synthetic.at(-10), end: Synthetic.at(10_000)))
            #expect(all == [resolved, Self.incident("synthetic-02")])
            // Sources don't mix.
            #expect(try store.openIncidents(source: "other.status").isEmpty)
        }
    }

    @Test func overlappingQueryUsesImpactTimes() throws {
        try withScratchDirectory { directory in
            let store = try Self.makeStore(directory)
            // Published early but impacted only 1000...2000.
            let late = Self.incident("late", status: "resolved", published: 0, updated: 2_100, impacts: [Self.impact(1_000, 2_000)])
            // Impact ended before the window.
            let early = Self.incident("early", status: "resolved", published: 0, updated: 600, impacts: [Self.impact(100, 500)])
            // Open-ended impact on a still-open incident overlaps any later window.
            let ongoing = Self.incident("ongoing", published: 0, updated: 100, impacts: [Self.impact(200, nil)])
            // Open-ended impact on a resolved incident ends at resolution.
            let closed = Self.incident("closed", status: "resolved", published: 0, updated: 700, impacts: [Self.impact(200, nil)])
            // No impacts: counts from publication to resolution.
            let bare = Self.incident("bare", status: "resolved", published: 1_500, updated: 1_800)
            try store.upsert(incidents: [late, early, ongoing, closed, bare])

            func ids(_ start: TimeInterval, _ end: TimeInterval) throws -> [String] {
                try store.incidents(source: "example.status", overlapping: DateInterval(start: Synthetic.at(start), end: Synthetic.at(end))).map(\.id)
            }
            #expect(try ids(900, 950) == ["ongoing"])
            #expect(try ids(1_700, 1_750) == ["late", "ongoing", "bare"])
            #expect(try ids(300, 400) == ["closed", "early", "ongoing"])
            #expect(try ids(2_500, 3_000) == ["ongoing"])
            // The window's edges count.
            #expect(try ids(2_000, 2_000) == ["late", "ongoing"])
        }
    }

    @Test func rssItemsDedupeByLink() throws {
        func item(_ number: Int, title: String = "Synthetic post") -> RSSItem {
            RSSItem(
                title: "\(title) \(number)", link: URL(string: "https://status.example.com/incidents/synthetic-\(number)")!,
                publishedAt: Synthetic.at(Double(number) * 60))
        }
        try withScratchDirectory { directory in
            let store = try Self.makeStore(directory)
            // A repeated link inside one batch counts once.
            #expect(try store.recordRSSItems([item(1), item(2), item(1, title: "Edited")], source: "example.status", displayName: "Example") == [item(1), item(2)])
            // A later run returns only what is new.
            #expect(try store.recordRSSItems([item(2), item(3)], source: "example.status", displayName: "Example") == [item(3)])
            #expect(try store.recordRSSItems([item(1), item(2), item(3)], source: "example.status", displayName: "Example").isEmpty)

            let events = try store.query("SELECT at, kind, provider, scope, title, body, link, episode_id, epoch_id, undone_at FROM events ORDER BY at") {
                (at: $0.date(0), kind: $0.text(1), provider: $0.text(2), scope: $0.text(3), title: $0.text(4), body: $0.text(5),
                 link: $0.text(6), episode: $0.optionalInt(7), epoch: $0.optionalInt(8), undone: $0.optionalDate(9))
            }
            #expect(events.count == 3)
            let first = try #require(events.first)
            #expect(first.at == Synthetic.at(60))
            #expect(first.kind == "statusPost" && first.provider == "example.status" && first.scope == "*")
            #expect(first.title == "Synthetic post 1")
            #expect(first.body == "Example posted: Synthetic post 1.")
            #expect(first.link == "https://status.example.com/incidents/synthetic-1")
            #expect(first.episode == nil && first.epoch == nil && first.undone == nil)
        }
    }

    @Test func replaceComponentsReplacesTheSourcesList() throws {
        try withScratchDirectory { directory in
            let store = try Self.makeStore(directory)
            let a = StatusComponent(id: "component-a", name: "Example Chat")
            let b = StatusComponent(id: "component-b", name: "Example API")
            try store.replace(components: [b, a], source: "example.status")
            try store.replace(components: [StatusComponent(id: "component-z", name: "Other")], source: "other.status")
            #expect(try store.components(source: "example.status") == [b, a])  // Ordered by name.
            try store.replace(components: [a], source: "example.status")
            #expect(try store.components(source: "example.status") == [a])
            #expect(try store.components(source: "other.status").count == 1)
        }
    }
}
