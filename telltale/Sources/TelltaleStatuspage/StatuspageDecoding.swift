import Foundation
import TelltaleCore

struct Summary: Decodable {
    let components: [Component]
    let incidents: [Incident]
}
struct Component: Decodable { let id: String; let name: String? }
struct Envelope: Decodable { let incident: Incident }
struct Incident: Decodable {
    let id: String
    let name: String
    let status: String
    let created_at: String
    let updated_at: String
    let started_at: String?
    let resolved_at: String?
    let shortlink: String
    let impact: String?
    let components: [Component]?
    let incident_updates: [Update]?
}
struct Update: Decodable {
    let created_at: String
    let status: String
    let affected_components: [Affected]?
}
struct Affected: Decodable { let code: String; let new_status: String }

enum StatuspageDecoding {
    static func decode<T: Decodable>(_ type: T.Type, _ data: Data) throws -> T {
        do { return try JSONDecoder().decode(type, from: data) }
        catch { throw StatusError.unexpectedPayload("invalid Statuspage JSON") }
    }
    static func record(_ incident: Incident, source: String) throws -> IncidentRecord {
        guard let created = ISO8601Time.date(incident.created_at), let updated = ISO8601Time.date(incident.updated_at),
              let link = URL(string: incident.shortlink), link.scheme != nil else { throw StatusError.unexpectedPayload("invalid incident fields") }
        let updates = try (incident.incident_updates ?? []).map { update -> (Date, Update) in
            guard let date = ISO8601Time.date(update.created_at) else { throw StatusError.unexpectedPayload("invalid update date") }
            return (date, update)
        }.sorted { $0.0 < $1.0 }
        let resolved = incident.resolved_at.flatMap(ISO8601Time.date)
        var impacts: [ComponentImpact] = []
        var open: [String: Int] = [:]
        for (date, update) in updates {
            for affected in update.affected_components ?? [] {
                let status = affected.new_status == "major_outage" ? "full_outage" : affected.new_status
                if status == "operational" {
                    if let index = open.removeValue(forKey: affected.code) { impacts[index].end = date }
                } else if let index = open[affected.code] {
                    if impacts[index].status != status {
                        impacts[index].end = date
                        impacts.append(.init(componentID: affected.code, status: status, start: date))
                        open[affected.code] = impacts.count - 1
                    }
                } else {
                    impacts.append(.init(componentID: affected.code, status: status, start: date))
                    open[affected.code] = impacts.count - 1
                }
            }
        }
        for index in open.values { impacts[index].end = resolved }
        if updates.contains(where: { $0.1.affected_components == nil || $0.1.affected_components!.isEmpty }),
           let start = incident.started_at.flatMap(ISO8601Time.date) {
            let status: String? = switch incident.impact {
            case "minor": "degraded_performance"
            case "major": "partial_outage"
            case "critical": "full_outage"
            default: nil
            }
            if let status {
                for component in incident.components ?? [] {
                    impacts.append(.init(componentID: component.id, status: status, start: start, end: resolved))
                }
            }
        }
        return IncidentRecord(source: source, id: incident.id, name: incident.name, status: incident.status,
            publishedAt: created, updatedAt: updated, link: link,
            history: updates.map { StatusChange(at: $0.0, status: $0.1.status) }, impacts: impacts)
    }
}
