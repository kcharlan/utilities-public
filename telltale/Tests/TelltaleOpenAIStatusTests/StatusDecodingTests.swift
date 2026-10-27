import Foundation
import Testing
import TelltaleCore
@testable import TelltaleOpenAIStatus

@Suite struct StatusDecodingTests {
    @Test func decodesOngoingIncidentsAndComponents() throws {
        let summary = try StatusDecoding.summary(Fixtures.data("summary_incident.json"))
        #expect(summary.ongoingIncidents == [
            .init(id: "synthetic-01", name: "Elevated errors for Example Chat", status: "investigating",
                  updatedAt: Fixtures.date("2026-10-27T14:20:00.000Z")),
            .init(id: "synthetic-02", name: "Slow responses for Example API", status: "monitoring",
                  updatedAt: Fixtures.date("2026-10-27T13:05:30Z")),
        ])
        #expect(summary.components == [
            StatusComponent(id: "component-a", name: "Example Chat"),
            StatusComponent(id: "component-b", name: "Example API"),
            StatusComponent(id: "component-c", name: "Example Files"),
        ])

        let quiet = try StatusDecoding.summary(Fixtures.data("summary_quiet.json"))
        #expect(quiet.ongoingIncidents.isEmpty)
        #expect(quiet.components == [
            StatusComponent(id: "component-a", name: "Example Chat"),
            StatusComponent(id: "component-b", name: "Example API"),
        ])
    }

    @Test func decodesIncidentDetailHistoryAndImpacts() throws {
        let incident = try StatusDecoding.incident(Fixtures.data("incident_detail.json"))
        #expect(incident.name == "Elevated errors for Example Chat")
        #expect(incident.status == "monitoring")
        #expect(incident.publishedAt == Fixtures.date("2026-10-27T13:40:00.000Z"))
        // History is oldest first whatever order the page lists it in, and the newest update dates the incident.
        #expect(incident.history == [
            StatusChange(at: Fixtures.date("2026-10-27T13:40:00Z"), status: "investigating"),
            StatusChange(at: Fixtures.date("2026-10-27T14:00:00Z"), status: "identified"),
            StatusChange(at: Fixtures.date("2026-10-27T14:20:00Z"), status: "monitoring"),
        ])
        #expect(incident.updatedAt == Fixtures.date("2026-10-27T14:20:00Z"))
        #expect(incident.impacts == [
            ComponentImpact(componentID: "component-a", status: "degraded_performance", start: Fixtures.date("2026-10-27T13:38:00Z"), end: nil),
            ComponentImpact(componentID: "component-b", status: "partial_outage", start: Fixtures.date("2026-10-27T13:45:00Z"), end: Fixtures.date("2026-10-27T14:10:00Z")),
        ])
    }

    @Test func decodesRSS() throws {
        let items = try StatusDecoding.rss(Fixtures.data("feed.rss"))
        #expect(items == [
            RSSItem(
                title: "Elevated errors for Example Chat",
                link: URL(string: "https://status.example.com/incidents/synthetic-01")!,
                publishedAt: Fixtures.date("2026-10-27T13:40:00Z")),
            RSSItem(
                title: "Slow responses for Example API",
                link: URL(string: "https://status.example.com/incidents/synthetic-02")!,
                publishedAt: Fixtures.date("2026-10-27T12:30:00Z")),
        ])
    }

    @Test func htmlPageThrowsUnexpectedPayload() throws {
        let page = try Fixtures.data("error_page.html")
        #expect(throws: StatusError.self) { try StatusDecoding.summary(page) }
        #expect(throws: StatusError.self) { try StatusDecoding.incident(page) }
        #expect(throws: StatusError.self) { try StatusDecoding.rss(page) }
        // A well-formed XML page that isn't a feed is still not an empty feed.
        #expect(throws: StatusError.self) { try StatusDecoding.rss(Data("<html><body/></html>".utf8)) }
    }

    @Test func missingSummaryThrows() throws {
        for body in [#"{"status": {"indicator": "none"}}"#, #"{"summary": {"components": []}}"#, #"{"summary": {"ongoing_incidents": []}}"#, "[]", ""] {
            #expect(throws: StatusError.self) { try StatusDecoding.summary(Data(body.utf8)) }
        }
        // Detail needs a name, status and publication time.
        #expect(throws: StatusError.self) { try StatusDecoding.incident(Data(#"{"incident": {"name": "x", "status": "investigating"}}"#.utf8)) }
    }
}
