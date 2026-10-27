import Foundation

// Status-page data (spec section 10): components, incidents and the RSS fallback's posts.

extension Store {
    /// Replaces a source's component list (ids to names) with `components`.
    public func replace(components: [StatusComponent], source: String) throws {
        try transaction {
            try run("DELETE FROM status_components WHERE source = ?", [.text(source)])
            let insert = try prepare("INSERT OR REPLACE INTO status_components (source, component_id, name) VALUES (?, ?, ?)")
            for component in components {
                try insert.run([.text(source), .text(component.id), .text(component.name)])
            }
        }
    }

    /// A source's components, ordered by name.
    public func components(source: String) throws -> [StatusComponent] {
        try query(
            "SELECT component_id, name FROM status_components WHERE source = ? ORDER BY name, component_id",
            [.text(source)]
        ) { StatusComponent(id: $0.text(0), name: $0.text(1)) }
    }

    /// Inserts or replaces incidents by `(source, id)`; a replaced incident's history and impacts
    /// are the new record's.
    public func upsert(incidents: [IncidentRecord]) throws {
        try transaction {
            let statement = try prepare("""
                INSERT INTO incidents (source, incident_id, name, status, published_at, updated_at, link, history_json, impacts_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (source, incident_id) DO UPDATE SET
                    name = excluded.name, status = excluded.status, published_at = excluded.published_at,
                    updated_at = excluded.updated_at, link = excluded.link,
                    history_json = excluded.history_json, impacts_json = excluded.impacts_json
                """)
            for incident in incidents {
                try statement.run([
                    .text(incident.source), .text(incident.id), .text(incident.name), .text(incident.status),
                    .date(incident.publishedAt), .date(incident.updatedAt), .text(incident.link.absoluteString),
                    .text(try StoreJSON.encode(incident.history)), .text(try StoreJSON.encode(incident.impacts)),
                ])
            }
        }
    }

    /// Incidents not yet resolved or postmortem, oldest first.
    public func openIncidents(source: String) throws -> [IncidentRecord] {
        try incidentRows(source: source, whereClause: "AND status NOT IN ('resolved', 'postmortem')")
    }

    /// Incidents whose component impacts overlap `interval` (both ends inclusive), oldest first.
    /// An impact without an end is open until the incident resolves (its `updated_at`), or
    /// without bound while the incident is open. An incident with no impacts counts as one
    /// impact from publication on, on the same terms.
    public func incidents(source: String, overlapping interval: DateInterval) throws -> [IncidentRecord] {
        try incidentRows(source: source, whereClause: "").filter { incident in
            let open = incident.isResolved ? incident.updatedAt : Date.distantFuture
            let spans = incident.impacts.isEmpty
                ? [(start: incident.publishedAt, end: open)]
                : incident.impacts.map { (start: $0.start, end: $0.end ?? open) }
            return spans.contains { $0.start <= interval.end && $0.end >= interval.start }
        }
    }

    private func incidentRows(source: String, whereClause: String) throws -> [IncidentRecord] {
        try query("""
            SELECT incident_id, name, status, published_at, updated_at, link, history_json, impacts_json
            FROM incidents WHERE source = ? \(whereClause) ORDER BY published_at, incident_id
            """, [.text(source)]
        ) { row in
            guard let link = URL(string: row.text(5)) else {
                throw StoreError.invalidData("Unreadable link for incident \(row.text(0))")
            }
            do {
                return IncidentRecord(
                    source: source, id: row.text(0), name: row.text(1), status: row.text(2),
                    publishedAt: row.date(3), updatedAt: row.date(4), link: link,
                    history: try StoreJSON.decode([StatusChange].self, from: row.text(6)),
                    impacts: try StoreJSON.decode([ComponentImpact].self, from: row.text(7)))
            } catch {
                throw StoreError.invalidData("Unreadable history for incident \(row.text(0))")
            }
        }
    }

    /// Stores each item whose link has no `statusPost` event yet (duplicates within `items`
    /// count once) and returns those new items, in the order given. RSS items carry no reliable
    /// open or resolved state, so they appear in Events but never light or clear a lamp.
    @discardableResult
    public func recordRSSItems(_ items: [RSSItem], source: String, displayName: String) throws -> [RSSItem] {
        try transaction {
            let kind = "statusPost"
            let known = try prepare("SELECT 1 FROM events WHERE kind = ? AND provider = ? AND link = ? LIMIT 1")
            let insert = try prepare("""
                INSERT INTO events (at, kind, provider, scope, title, body, link) VALUES (?, ?, ?, '*', ?, ?, ?)
                """)
            var recorded: [RSSItem] = []
            for item in items {
                let link = item.link.absoluteString
                guard try known.rows([.text(kind), .text(source), .text(link)], { _ in true }).isEmpty else { continue }
                try insert.run([
                    .date(item.publishedAt), .text(kind), .text(source), .text(item.title),
                    .text(Copy.statusPost(source: displayName, title: item.title)), .text(link),
                ])
                recorded.append(item)
            }
            return recorded
        }
    }
}
