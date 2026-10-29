import Foundation
import Testing
import TelltaleCore
import TelltaleStatuspage

actor Transport: HTTPTransport {
    let bodies: [String: Data]
    var paths: [String] = []
    init(_ bodies: [String: Data]) { self.bodies = bodies }
    func get(_ url: URL) async throws -> (Data, HTTPURLResponse) {
        paths.append(url.path)
        guard let body = bodies[url.path] else { throw StatusError.httpStatus(503) }
        return (body, HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: nil)!)
    }
}

@Suite struct StatuspageSourceTests {
    let base = URL(string: "https://status.example.com")!
    let summary = "/api/v2/summary.json"
    let detail = "/api/v2/incidents/fake-incident.json"
    func fixture(_ name: String) throws -> Data { try Data(contentsOf: Bundle.module.resourceURL!.appending(path: "Fixtures/\(name)")) }
    func source(_ transport: Transport) -> StatuspageSource { .init(id: "fake", displayName: "Example", baseURL: base, transport: transport, defaultWatchedComponents: ["Example Code"]) }
    func known(_ updated: String = "2026-01-01T00:05:00Z") -> IncidentRecord {
        .init(source: "fake", id: "fake-incident", name: "Synthetic interruption", status: "investigating", publishedAt: ISO8601DateFormatter().date(from: "2026-01-01T00:00:00Z")!, updatedAt: ISO8601DateFormatter().date(from: updated)!, link: base.appending(path: "incidents/fake-incident"), history: [], impacts: [])
    }
    @Test func quietSummaryHasComponentsAndNoIncidents() async throws {
        let t = Transport([summary: try fixture("summary_quiet.json")])
        guard case .full(let components, let incidents) = try await source(t).fetch(known: []) else { Issue.record("expected full"); return }
        #expect(components == [.init(id: "fake-component", name: "Example Code")]); #expect(incidents.isEmpty)
    }
    @Test func newIncidentFetchesItsDetailOnce() async throws {
        let t = Transport([summary: try fixture("summary_incident.json"), detail: try fixture("incident_detail.json")])
        guard case .full(_, let incidents) = try await source(t).fetch(known: []) else { Issue.record("expected full"); return }
        #expect(await t.paths == [summary, detail]); #expect(incidents.first?.history.count == 2); #expect(incidents.first?.status == "resolved")
    }
    @Test func failedNewDetailIsRetriedWhenSummaryTimestampIsUnchanged() async throws {
        let first = Transport([summary: try fixture("summary_incident.json")])
        guard case .full(_, let initial) = try await source(first).fetch(known: []) else { Issue.record("expected full"); return }
        let second = Transport([summary: try fixture("summary_incident.json"), detail: try fixture("incident_detail.json")])
        guard case .full(_, let recovered) = try await source(second).fetch(known: initial) else { Issue.record("expected full"); return }
        #expect(await second.paths == [summary, detail])
        #expect(recovered.first?.impacts.first?.status == "full_outage")
    }
    @Test func unchangedKnownIncidentSkipsDetail() async throws {
        let t = Transport([summary: try fixture("summary_incident.json")]); let prior = known()
        guard case .full(_, let incidents) = try await source(t).fetch(known: [prior]) else { Issue.record("expected full"); return }
        #expect(await t.paths == [summary]); #expect(incidents == [prior])
    }
    @Test func resolvedIncidentMissingFromSummaryIsFetched() async throws {
        let t = Transport([summary: try fixture("summary_quiet.json"), detail: try fixture("incident_detail.json")])
        guard case .full(_, let incidents) = try await source(t).fetch(known: [known()]) else { Issue.record("expected full"); return }
        #expect(await t.paths == [summary, detail]); #expect(incidents.first?.isResolved == true)
    }
    @Test func majorOutageNormalizesToFullOutage() async throws {
        let t = Transport([summary: try fixture("summary_incident.json"), detail: try fixture("incident_detail.json")])
        guard case .full(_, let incidents) = try await source(t).fetch(known: []) else { Issue.record("expected full"); return }
        let impact = try #require(incidents.first?.impacts.first)
        #expect(impact.status == "full_outage"); #expect(impact.end == ISO8601DateFormatter().date(from: "2026-01-01T00:10:00Z"))
    }
    @Test func updateWithoutAffectedComponentsFallsBack() async throws {
        let t = Transport([summary: try fixture("summary_incident.json"), detail: try fixture("incident_no_affected.json")])
        guard case .full(_, let incidents) = try await source(t).fetch(known: []) else { Issue.record("expected full"); return }
        let impact = try #require(incidents.first?.impacts.first)
        #expect(impact.componentID == "fake-component"); #expect(impact.status == "partial_outage"); #expect(impact.end != nil)
    }
    @Test func mixedUpdateHistoryKeepsFallbackAndExplicitImpacts() async throws {
        let detailBody = Data(#"""
            {"incident":{"id":"fake-incident","name":"Synthetic interruption","status":"resolved",
            "created_at":"2026-01-01T00:00:00Z","updated_at":"2026-01-01T00:10:00Z",
            "started_at":"2026-01-01T00:00:00Z","resolved_at":"2026-01-01T00:10:00Z",
            "shortlink":"https://status.example.com/incidents/fake-incident","impact":"major",
            "components":[{"id":"fake-component"}],"incident_updates":[
            {"created_at":"2026-01-01T00:00:00Z","status":"investigating"},
            {"created_at":"2026-01-01T00:05:00Z","status":"identified",
             "affected_components":[{"code":"fake-component","new_status":"major_outage"}]}]}}
            """#.utf8)
        let t = Transport([summary: try fixture("summary_incident.json"), detail: detailBody])
        guard case .full(_, let incidents) = try await source(t).fetch(known: []) else { Issue.record("expected full"); return }
        let impacts = try #require(incidents.first?.impacts)
        let date = ISO8601DateFormatter()
        #expect(impacts.contains(.init(componentID: "fake-component", status: "partial_outage", start: date.date(from: "2026-01-01T00:00:00Z")!, end: date.date(from: "2026-01-01T00:10:00Z")!)))
        #expect(impacts.contains(.init(componentID: "fake-component", status: "full_outage", start: date.date(from: "2026-01-01T00:05:00Z")!, end: date.date(from: "2026-01-01T00:10:00Z")!)))
    }
    @Test func summaryFailureFallsBackToRSS() async throws {
        let t = Transport(["/history.rss": try fixture("history.rss")])
        guard case .rssOnly(let items) = try await source(t).fetch(known: []) else { Issue.record("expected rss"); return }
        #expect(items.first?.title == "Synthetic interruption"); #expect(await t.paths == [summary, "/history.rss"])
    }
    @Test func malformedSummaryFallsBackToRSS() async throws {
        let malformed = Data(#"{"components":[{"id":"fake-component"}],"incidents":[]}"#.utf8)
        let t = Transport([summary: malformed, "/history.rss": try fixture("history.rss")])
        guard case .rssOnly = try await source(t).fetch(known: []) else { Issue.record("expected rss"); return }
        #expect(await t.paths == [summary, "/history.rss"])
    }
    @Test func htmlErrorPageMarksUnavailable() async throws {
        let page = try fixture("error_page.html"); let t = Transport([summary: page, "/history.rss": page])
        await #expect(throws: (any Error).self) { try await source(t).fetch(known: []) }
    }
}
