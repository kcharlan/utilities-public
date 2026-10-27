import Foundation
import Testing
import TelltaleCore
import TelltaleTestSupport
@testable import TelltaleOpenAIStatus

@Suite struct OpenAIStatusSourceTests {
    static let base = URL(string: "https://status.example.com")!
    static let now = Fixtures.date("2026-10-27T15:00:00Z")

    private static func source(_ transport: FakeTransport) -> OpenAIStatusSource {
        OpenAIStatusSource(transport: transport, base: base, clock: { now })
    }

    private static func stored(
        _ id: String, status: String, updatedAt: String = "2026-10-27T13:00:00Z", name: String = "Stored incident"
    ) -> IncidentRecord {
        IncidentRecord(
            source: "openai", id: id, name: name, status: status,
            publishedAt: Fixtures.date("2026-10-27T12:00:00Z"), updatedAt: Fixtures.date(updatedAt),
            link: base.appending(path: "incidents/\(id)"), history: [], impacts: [])
    }

    private static func summary(_ incidents: [(id: String, status: String, updated: String)]) -> Data {
        let entries = incidents.map {
            #"{"id": "\#($0.id)", "name": "Name \#($0.id)", "status": "\#($0.status)", "last_update_at": "\#($0.updated)"}"#
        }.joined(separator: ",")
        return Data(#"{"summary": {"ongoing_incidents": [\#(entries)], "components": [{"id": "component-a", "name": "Example Chat"}]}}"#.utf8)
    }

    @Test func fetchesDetailOnlyForNewChangedOrVanished() async throws {
        let detail = try Fixtures.data("incident_detail.json")
        let transport = FakeTransport([
            Paths.summary: .body(Self.summary([
                (id: "new-1", status: "investigating", updated: "2026-10-27T14:20:00Z"),
                (id: "changed-2", status: "identified", updated: "2026-10-27T14:00:00Z"),
                (id: "same-3", status: "monitoring", updated: "2026-10-27T13:00:00Z"),
            ])),
            Paths.detail("new-1"): .body(detail),
            Paths.detail("changed-2"): .body(detail),
            Paths.detail("vanished-4"): .body(detail),
        ])
        let known = [
            Self.stored("changed-2", status: "investigating"),
            Self.stored("same-3", status: "monitoring", name: "Name same-3"),
            Self.stored("vanished-4", status: "monitoring"),
            Self.stored("resolved-5", status: "resolved"),
        ]

        let fetched = try await Self.source(transport).fetch(known: known)

        let paths = await transport.paths
        #expect(paths == [Paths.summary, Paths.detail("new-1"), Paths.detail("changed-2"), Paths.detail("vanished-4")])
        guard case .full(let components, let incidents) = fetched else { Issue.record("expected .full"); return }
        #expect(components == [StatusComponent(id: "component-a", name: "Example Chat")])
        #expect(incidents.map(\.id) == ["new-1", "changed-2", "same-3", "vanished-4"])
        let new = try #require(incidents.first)
        #expect(new.source == "openai")
        #expect(new.name == "Elevated errors for Example Chat")
        #expect(new.link == Self.base.appending(path: "incidents/new-1"))
        #expect(new.history.count == 3 && new.impacts.count == 2)
        // The unchanged incident comes back as stored, untouched.
        #expect(incidents[2] == known[1])
    }

    @Test func neverRequestsLegacySummaryJSON() async throws {
        let transport = FakeTransport([
            Paths.summary: .body(Self.summary([(id: "new-1", status: "investigating", updated: "2026-10-27T14:20:00Z")])),
            Paths.detail("new-1"): .body(try Fixtures.data("incident_detail.json")),
            Paths.feed: .body(try Fixtures.data("feed.rss")),
        ])
        _ = try await Self.source(transport).fetch(known: [Self.stored("old-2", status: "monitoring")])
        // Also the summary-failure path, which reaches for the feed.
        let failing = FakeTransport([Paths.feed: .body(try Fixtures.data("feed.rss"))])
        _ = try await Self.source(failing).fetch(known: [])

        for requested in [await transport.requests, await failing.requests] {
            #expect(!requested.isEmpty)
            #expect(requested.allSatisfy { !$0.path.contains("/api/v2/") && !$0.path.hasSuffix("summary.json") })
            #expect(requested.allSatisfy { $0.host == "status.example.com" })
        }
    }

    @Test func rssFillsTitleWhenDetailFails() async throws {
        // The summary lists the incident without a name, and its detail request fails.
        let summary = Data(#"""
            {"summary": {"ongoing_incidents": [{"id": "synthetic-01", "last_update_at": "2026-10-27T14:20:00Z"}],
             "components": []}}
            """#.utf8)
        let transport = FakeTransport([
            Paths.summary: .body(summary),
            Paths.detail("synthetic-01"): .failure,
            Paths.feed: .body(try Fixtures.data("feed.rss")),
        ])

        let fetched = try await Self.source(transport).fetch(known: [])

        guard case .full(_, let incidents) = fetched else { Issue.record("expected .full"); return }
        let incident = try #require(incidents.first)
        #expect(incident.name == "Elevated errors for Example Chat")
        #expect(incident.link == URL(string: "https://status.example.com/incidents/synthetic-01"))
        #expect(incident.status == "investigating")
        #expect(!incident.isResolved)
        #expect(incident.updatedAt == Fixtures.date("2026-10-27T14:20:00Z"))
        #expect(incident.history.isEmpty && incident.impacts.isEmpty)
    }

    @Test func detailFailureKeepsAChangedStoredIncident() async throws {
        let prior = Self.stored("synthetic-01", status: "investigating")
        let transport = FakeTransport([
            Paths.summary: .body(Self.summary([(id: "synthetic-01", status: "identified", updated: "2026-10-27T14:20:00Z")])),
            Paths.detail("synthetic-01"): .failure,
        ])
        guard case .full(_, let incidents) = try await Self.source(transport).fetch(known: [prior]) else {
            Issue.record("expected .full"); return
        }
        #expect(incidents == [prior])
    }

    @Test func summaryFailureFallsBackToRSS() async throws {
        let transport = FakeTransport([
            Paths.summary: .failure,
            Paths.feed: .body(try Fixtures.data("feed.rss")),
        ])
        let fetched = try await Self.source(transport).fetch(known: [Self.stored("old-2", status: "monitoring")])
        guard case .rssOnly(let items) = fetched else { Issue.record("expected .rssOnly"); return }
        #expect(items.map(\.title) == ["Elevated errors for Example Chat", "Slow responses for Example API"])
        #expect(await transport.paths == [Paths.summary, Paths.feed])

        // A summary that answers with an HTTP error status also falls back.
        let serverError = FakeTransport([
            Paths.summary: .body(Data("oops".utf8), status: 503),
            Paths.feed: .body(try Fixtures.data("feed.rss")),
        ])
        guard case .rssOnly = try await Self.source(serverError).fetch(known: []) else { Issue.record("expected .rssOnly"); return }

        // With RSS failing too, the fetch throws.
        let bothDown = FakeTransport([:])
        await #expect(throws: (any Error).self) { try await Self.source(bothDown).fetch(known: []) }
    }

    @Test func malformedFetchKeepsStoredIncidentsOpen() async throws {
        let page = try Fixtures.data("error_page.html")
        // A success status with an HTML body, from the summary and from the feed.
        let transport = FakeTransport([
            Paths.summary: .body(page),
            Paths.feed: .body(page),
        ])
        let open = Self.stored("synthetic-01", status: "investigating")

        let result: Result<StatusFetch, any Error>
        do {
            result = .success(try await Self.source(transport).fetch(known: [open]))
        } catch {
            result = .failure(error)
        }
        guard case .failure = result else { Issue.record("expected a thrown fetch"); return }

        try withScratchDirectory { directory in
            let store = try Store.open(directory.appending(path: "telltale.sqlite"), mode: .readWrite)
            try store.upsert(incidents: [open])

            let available = try OpenAIStatusSource.apply(result, sourceID: "openai", store: store, now: Self.now)
            #expect(available == false)
            #expect(try store.openIncidents(source: "openai") == [open])
            #expect(try store.sourceState("openai")?.unavailableSince == Self.now)

            // A later failure doesn't move the start of the outage.
            _ = try OpenAIStatusSource.apply(result, sourceID: "openai", store: store, now: Self.now.addingTimeInterval(600))
            #expect(try store.sourceState("openai")?.unavailableSince == Self.now)
        }
    }

    @Test func applyFullStoresDataAndClearsUnavailable() throws {
        let incident = Self.stored("synthetic-01", status: "investigating")
        try withScratchDirectory { directory in
            let store = try Store.open(directory.appending(path: "telltale.sqlite"), mode: .readWrite)
            let down = Result<StatusFetch, any Error>.failure(FakeTransport.Offline())
            #expect(try OpenAIStatusSource.apply(down, sourceID: "openai", store: store, now: Self.now) == false)
            #expect(try store.sourceState("openai")?.unavailableSince == Self.now)

            let full = Result<StatusFetch, any Error>.success(
                .full(components: [StatusComponent(id: "component-a", name: "Example Chat")], incidents: [incident]))
            #expect(try OpenAIStatusSource.apply(full, sourceID: "openai", store: store, now: Self.now.addingTimeInterval(60)) == true)
            #expect(try store.sourceState("openai")?.unavailableSince == nil)
            #expect(try store.openIncidents(source: "openai") == [incident])
            #expect(try store.components(source: "openai") == [StatusComponent(id: "component-a", name: "Example Chat")])
        }
    }

    @Test func applyRSSOnlyRecordsPostsButLeavesIncidentsAlone() throws {
        let open = Self.stored("synthetic-01", status: "investigating")
        let post = RSSItem(
            title: "Synthetic post", link: URL(string: "https://status.example.com/incidents/synthetic-09")!,
            publishedAt: Fixtures.date("2026-10-27T14:00:00Z"))
        try withScratchDirectory { directory in
            let store = try Store.open(directory.appending(path: "telltale.sqlite"), mode: .readWrite)
            try store.upsert(incidents: [open])

            let result = Result<StatusFetch, any Error>.success(.rssOnly([post]))
            #expect(try OpenAIStatusSource.apply(result, sourceID: "openai", store: store, now: Self.now) == false)
            #expect(try store.sourceState("openai")?.unavailableSince == Self.now)
            #expect(try store.openIncidents(source: "openai") == [open])
            // The same post on the next run is already recorded.
            #expect(try store.recordRSSItems([post], source: "openai", displayName: "OpenAI").isEmpty)
        }
    }

    @Test func urlSessionTransportIsConstructedButNotCalled() {
        // The real transport is never called in tests; its settings are fixed.
        _ = URLSessionTransport()
        #expect(URLSessionTransport.timeout == 15)
        #expect(URLSessionTransport.userAgent.contains("Telltale/\(TelltaleRelease.version)"))
    }
}
