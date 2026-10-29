import Foundation
import TelltaleCore

/// The three OpenAI status requests (spec section 10). The legacy `/api/v2/summary.json` is
/// never requested: it can report "All Systems Operational" during an incident.
struct StatusClient: Sendable {
    let transport: any HTTPTransport
    let base: URL

    var summaryURL: URL { base.appending(path: "proxy/status.openai.com") }
    var feedURL: URL { base.appending(path: "feed.rss") }

    func incidentURL(_ id: String) -> URL { summaryURL.appending(path: "incidents").appending(path: id) }
    func incidentLink(_ id: String) -> URL { base.appending(path: "incidents").appending(path: id) }

    func summary() async throws -> StatusSummary { try StatusDecoding.summary(try await transport.body(of: summaryURL)) }
    func incident(_ id: String) async throws -> DecodedIncident { try StatusDecoding.incident(try await transport.body(of: incidentURL(id))) }
    func feed() async throws -> [RSSItem] { try RSSFeed.items(try await transport.body(of: feedURL)) }

}
