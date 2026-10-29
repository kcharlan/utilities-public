import Foundation
import TelltaleCore

/// OpenAI's status page (spec section 10). Reads `status.openai.com/proxy/status.openai.com`,
/// never the legacy `/api/v2/summary.json`.
public struct OpenAIStatusSource: StatusSource {
    public static let defaultBase = URL(string: "https://status.openai.com")!

    public static let sourceID = "openai"
    public static let name = "OpenAI"

    public let id = OpenAIStatusSource.sourceID
    public let displayName = OpenAIStatusSource.name
    public let defaultWatchedComponents = ["CLI", "VS Code extension", "Codex in ChatGPT Desktop", "Codex API", "Codex Web", "Responses"]

    private let client: StatusClient
    private let clock: @Sendable () -> Date

    /// `clock` only dates an incident whose detail couldn't be fetched and that the summary
    /// doesn't date either.
    public init(transport: any HTTPTransport, base: URL = OpenAIStatusSource.defaultBase, clock: @escaping @Sendable () -> Date = { Date() }) {
        client = StatusClient(transport: transport, base: base)
        self.clock = clock
    }

    /// One collector run's fetch. Details are fetched for ongoing incidents that are new or
    /// changed since `known`, and for stored-open incidents that left the ongoing list (to see
    /// whether they resolved). Unchanged ongoing incidents come back as stored. If the summary
    /// itself fails, the RSS feed answers instead (`.rssOnly`); if that fails too, this throws
    /// the summary's error.
    public func fetch(known: [IncidentRecord]) async throws -> StatusFetch {
        let summary: StatusSummary
        do {
            summary = try await client.summary()
        } catch is CancellationError {
            throw CancellationError()
        } catch let summaryError {
            do {
                return .rssOnly(try await client.feed())
            } catch is CancellationError {
                throw CancellationError()
            } catch {
                throw summaryError
            }
        }

        let stored = Dictionary(known.filter { $0.source == id }.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        var incidents: [IncidentRecord] = []
        var feed: [RSSItem]?
        var feedTried = false
        var ongoingIDs = Set<String>()

        for ongoing in summary.ongoingIncidents where ongoingIDs.insert(ongoing.id).inserted {
            let prior = stored[ongoing.id]
            if let prior, !prior.isResolved, !Self.changed(ongoing, since: prior) {
                incidents.append(prior)
                continue
            }
            do {
                incidents.append(record(ongoing.id, try await client.incident(ongoing.id), summary: ongoing))
            } catch is CancellationError {
                throw CancellationError()
            } catch {
                if let prior {
                    incidents.append(prior)
                    continue
                }
                if ongoing.name == nil, !feedTried {
                    feedTried = true
                    feed = try? await client.feed()
                }
                incidents.append(placeholder(ongoing, feed: feed ?? []))
            }
        }

        for prior in known.sorted(by: { $0.id < $1.id }) where prior.source == id && !prior.isResolved && !ongoingIDs.contains(prior.id) {
            do {
                incidents.append(record(prior.id, try await client.incident(prior.id), summary: nil))
            } catch is CancellationError {
                throw CancellationError()
            } catch {
                continue  // Still stored as open; the next run checks again.
            }
        }
        return .full(components: summary.components, incidents: incidents)
    }

    // MARK: Building records

    private static func changed(_ ongoing: StatusSummary.OngoingIncident, since prior: IncidentRecord) -> Bool {
        if let name = ongoing.name, name != prior.name { return true }
        if let status = ongoing.status, status != prior.status { return true }
        guard let updatedAt = ongoing.updatedAt else { return true }  // Can't tell, so look.
        return updatedAt > prior.updatedAt
    }

    private func record(_ incidentID: String, _ detail: DecodedIncident, summary: StatusSummary.OngoingIncident?) -> IncidentRecord {
        IncidentRecord(
            source: id, id: incidentID, name: detail.name, status: detail.status, publishedAt: detail.publishedAt,
            updatedAt: max(detail.updatedAt, summary?.updatedAt ?? detail.updatedAt),
            link: client.incidentLink(incidentID), history: detail.history, impacts: detail.impacts)
    }

    /// An incident whose detail couldn't be fetched and that isn't stored yet. The summary names
    /// it, or else the RSS feed does (spec section 10: RSS is the fallback for titles and links).
    private func placeholder(_ ongoing: StatusSummary.OngoingIncident, feed: [RSSItem]) -> IncidentRecord {
        let post = feed.first { $0.link.lastPathComponent == ongoing.id }
        let published = post?.publishedAt ?? ongoing.publishedAt ?? ongoing.updatedAt ?? clock()
        return IncidentRecord(
            source: id, id: ongoing.id, name: ongoing.name ?? post?.title ?? "Incident \(ongoing.id)",
            status: ongoing.status ?? "investigating", publishedAt: published, updatedAt: ongoing.updatedAt ?? published,
            link: post?.link ?? client.incidentLink(ongoing.id), history: [], impacts: [])
    }

    // MARK: Applying a result

    /// Stores a fetch result and returns whether incident data is available (`Store.applyStatus`,
    /// with this source's name on RSS posts).
    @discardableResult
    public static func apply(
        _ result: Result<StatusFetch, any Error>, sourceID: String, store: Store, now: Date
    ) throws -> Bool {
        try store.applyStatus(result, source: sourceID, displayName: Self.name, now: now)
    }
}
