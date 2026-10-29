import Foundation
import TelltaleCore

/// The parts of the status summary Telltale uses (spec section 10).
public struct StatusSummary: Sendable, Equatable {
    public struct OngoingIncident: Sendable, Equatable {
        public var id: String
        public var name: String?
        public var status: String?
        public var publishedAt: Date?
        /// The newest update's time, else `publishedAt`: the change marker (the live element has no
        /// `updated_at`). Nil when the entry carries neither.
        public var updatedAt: Date?

        public init(id: String, name: String? = nil, status: String? = nil, publishedAt: Date? = nil, updatedAt: Date? = nil) {
            self.id = id
            self.name = name
            self.status = status
            self.publishedAt = publishedAt
            self.updatedAt = updatedAt
        }
    }

    public var ongoingIncidents: [OngoingIncident]
    public var components: [StatusComponent]

    public init(ongoingIncidents: [OngoingIncident], components: [StatusComponent]) {
        self.ongoingIncidents = ongoingIncidents
        self.components = components
    }
}

/// An incident's detail response (spec section 10), before the source adds its id and link.
public struct DecodedIncident: Sendable, Equatable {
    public var name: String
    public var status: String
    public var publishedAt: Date
    /// The newest update's time, or `publishedAt` when there are no updates.
    public var updatedAt: Date
    public var history: [StatusChange]
    public var impacts: [ComponentImpact]
}

/// Decodes the status payloads. Anything that isn't the expected shape throws
/// `StatusError.unexpectedPayload`, so a malformed answer never reads as "no incidents".
public enum StatusDecoding {
    /// `summary.ongoing_incidents` (the same shape as an incident detail: id, and optionally name,
    /// status, `published_at` and `updates[].published_at`, which date the last change) and
    /// `summary.components`, given either as a list of `{id, name}` or as an id-to-name map.
    public static func summary(_ data: Data) throws -> StatusSummary {
        let root = try jsonObject(data)
        guard let summary = root["summary"] as? [String: Any] else { throw missing("summary") }
        guard let incidents = summary["ongoing_incidents"] as? [Any] else { throw missing("summary.ongoing_incidents") }
        guard let components = summary["components"] else { throw missing("summary.components") }

        var ongoing: [StatusSummary.OngoingIncident] = []
        for case let entry as [String: Any] in incidents {
            guard let id = nonEmpty(entry["id"]) else { throw missing("summary.ongoing_incidents[].id") }
            let published = date(entry["published_at"])
            let lastUpdate = updateTimes(entry).max()
            ongoing.append(StatusSummary.OngoingIncident(
                id: id, name: nonEmpty(entry["name"]), status: nonEmpty(entry["status"]),
                publishedAt: published, updatedAt: [published, lastUpdate].compactMap { $0 }.max()))
        }
        if ongoing.count != incidents.count { throw StatusError.unexpectedPayload("summary.ongoing_incidents has a non-object entry") }
        return StatusSummary(ongoingIncidents: ongoing, components: try decodeComponents(components))
    }

    /// `incident.{name, status, published_at, updates[].{published_at, to_status},
    /// component_impacts[].{component_id, status, start_at, end_at}}`.
    public static func incident(_ data: Data) throws -> DecodedIncident {
        let root = try jsonObject(data)
        guard let incident = root["incident"] as? [String: Any] else { throw missing("incident") }
        guard let name = nonEmpty(incident["name"]) else { throw missing("incident.name") }
        guard let status = nonEmpty(incident["status"]) else { throw missing("incident.status") }
        guard let publishedAt = date(incident["published_at"]) else { throw missing("incident.published_at") }

        var history: [StatusChange] = []
        for case let update as [String: Any] in (incident["updates"] as? [Any]) ?? [] {
            guard let at = date(update["published_at"]), let toStatus = nonEmpty(update["to_status"]) else { continue }
            history.append(StatusChange(at: at, status: toStatus))
        }
        history.sort { $0.at < $1.at }

        var impacts: [ComponentImpact] = []
        for case let impact as [String: Any] in (incident["component_impacts"] as? [Any]) ?? [] {
            guard let componentID = nonEmpty(impact["component_id"]), let impactStatus = nonEmpty(impact["status"]),
                  let start = date(impact["start_at"]) else { continue }
            impacts.append(ComponentImpact(componentID: componentID, status: impactStatus, start: start, end: date(impact["end_at"])))
        }
        return DecodedIncident(
            name: name, status: status, publishedAt: publishedAt, updatedAt: ([publishedAt] + updateTimes(incident)).max() ?? publishedAt,
            history: history, impacts: impacts)
    }

    // MARK: Helpers

    /// The `published_at` of each entry of `updates`.
    private static func updateTimes(_ element: [String: Any]) -> [Date] {
        ((element["updates"] as? [Any]) ?? []).compactMap { date(( $0 as? [String: Any])?["published_at"]) }
    }

    private static func jsonObject(_ data: Data) throws -> [String: Any] {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw StatusError.unexpectedPayload("not a JSON object")
        }
        return object
    }

    private static func missing(_ field: String) -> StatusError { .unexpectedPayload("missing \(field)") }

    private static func nonEmpty(_ value: Any?) -> String? {
        guard let string = value as? String else { return nil }
        let trimmed = string.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    private static func decodeComponents(_ value: Any) throws -> [StatusComponent] {
        if let list = value as? [Any] {
            return try list.map { entry in
                guard let object = entry as? [String: Any], let id = nonEmpty(object["id"] ?? object["component_id"]),
                      let name = nonEmpty(object["name"]) else { throw missing("summary.components[].{id,name}") }
                return StatusComponent(id: id, name: name)
            }
        }
        if let map = value as? [String: Any] {
            return try map.keys.sorted().map { id in
                let name = nonEmpty(map[id]) ?? nonEmpty((map[id] as? [String: Any])?["name"])
                guard let name else { throw missing("summary.components.\(id)") }
                return StatusComponent(id: id, name: name)
            }
        }
        throw StatusError.unexpectedPayload("summary.components is neither a list nor a map")
    }

    /// ISO 8601 with or without fractional seconds.
    static func date(_ value: Any?) -> Date? {
        guard let string = value as? String else { return nil }
        return ISO8601Time.date(string)
    }
}
