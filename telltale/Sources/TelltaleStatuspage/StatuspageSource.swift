import Foundation
import TelltaleCore

public struct StatuspageSource: StatusSource {
    public let id: String
    public let displayName: String
    public let defaultWatchedComponents: [String]
    private let baseURL: URL
    private let transport: any HTTPTransport

    public init(id: String, displayName: String, baseURL: URL, transport: any HTTPTransport, defaultWatchedComponents: [String]) {
        self.id = id; self.displayName = displayName; self.baseURL = baseURL
        self.transport = transport; self.defaultWatchedComponents = defaultWatchedComponents
    }

    public func fetch(known: [IncidentRecord]) async throws -> StatusFetch {
        let summary: Summary
        let components: [StatusComponent]
        do {
            summary = try StatuspageDecoding.decode(Summary.self, try await transport.body(of: baseURL.appending(path: "api/v2/summary.json")))
            components = try summary.components.map { component in
                guard let name = component.name, !name.isEmpty else { throw StatusError.unexpectedPayload("missing component name") }
                return StatusComponent(id: component.id, name: name)
            }
            guard summary.incidents.allSatisfy({ ISO8601Time.date($0.updated_at) != nil }) else { throw StatusError.unexpectedPayload("invalid incident date") }
        } catch is CancellationError { throw CancellationError() }
        catch let summaryError {
            do { return .rssOnly(try RSSFeed.items(try await transport.body(of: baseURL.appending(path: "history.rss")))) }
            catch is CancellationError { throw CancellationError() }
            catch { throw summaryError }
        }
        let stored = Dictionary(known.filter { $0.source == id }.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        var records: [IncidentRecord] = []
        var ids = Set<String>()
        for incident in summary.incidents where ids.insert(incident.id).inserted {
            let prior = stored[incident.id]
            guard let updated = ISO8601Time.date(incident.updated_at) else { throw StatusError.unexpectedPayload("invalid incident date") }
            if let prior, !prior.isResolved, updated <= prior.updatedAt { records.append(prior); continue }
            do { records.append(try await detail(incident.id)) }
            catch is CancellationError { throw CancellationError() }
            catch {
                if let prior { records.append(prior) }
                // A new summary can omit impacts. Leave it unstored so the next fetch retries detail.
            }
        }
        for prior in known.sorted(by: { $0.id < $1.id }) where prior.source == id && !prior.isResolved && !ids.contains(prior.id) {
            do { records.append(try await detail(prior.id)) }
            catch is CancellationError { throw CancellationError() }
            catch { continue }
        }
        return .full(components: components, incidents: records)
    }

    private func detail(_ incidentID: String) async throws -> IncidentRecord {
        let url = baseURL.appending(path: "api/v2/incidents").appending(path: "\(incidentID).json")
        let envelope = try StatuspageDecoding.decode(Envelope.self, try await transport.body(of: url))
        return try StatuspageDecoding.record(envelope.incident, source: id)
    }
}
