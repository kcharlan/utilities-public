import Foundation
import TelltaleCore

/// A status-page request failed or answered with something that isn't the expected payload.
public enum StatusError: Error, Equatable, Sendable, LocalizedError {
    /// The response wasn't JSON or RSS of the expected shape, or lacked a required field.
    case unexpectedPayload(String)
    case httpStatus(Int)
    case notHTTP

    public var errorDescription: String? {
        switch self {
        case .unexpectedPayload(let detail): "The status page returned an unexpected response: \(detail)"
        case .httpStatus(let code): "The status page answered with HTTP \(code)."
        case .notHTTP: "The status page didn't answer over HTTP."
        }
    }
}

/// How the status source reaches the network. Tests substitute a fake; only the status pages
/// are ever requested (spec section 11).
public protocol HTTPTransport: Sendable {
    func get(_ url: URL) async throws -> (Data, HTTPURLResponse)
}

public struct URLSessionTransport: HTTPTransport {
    public static let timeout: TimeInterval = 15
    public static let userAgent = "Telltale/\(TelltaleRelease.version) (status check)"

    private let session: URLSession

    public init() {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = Self.timeout
        configuration.timeoutIntervalForResource = Self.timeout
        configuration.httpCookieStorage = nil
        configuration.urlCache = nil
        session = URLSession(configuration: configuration)
    }

    public func get(_ url: URL) async throws -> (Data, HTTPURLResponse) {
        var request = URLRequest(url: url, timeoutInterval: Self.timeout)
        request.setValue(Self.userAgent, forHTTPHeaderField: "User-Agent")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw StatusError.notHTTP }
        return (data, http)
    }
}

/// The three OpenAI status requests (spec section 10). The legacy `/api/v2/summary.json` is
/// never requested: it can report "All Systems Operational" during an incident.
struct StatusClient: Sendable {
    let transport: any HTTPTransport
    let base: URL

    var summaryURL: URL { base.appending(path: "proxy/status.openai.com") }
    var feedURL: URL { base.appending(path: "feed.rss") }

    func incidentURL(_ id: String) -> URL { summaryURL.appending(path: "incidents").appending(path: id) }
    func incidentLink(_ id: String) -> URL { base.appending(path: "incidents").appending(path: id) }

    func summary() async throws -> StatusSummary { try StatusDecoding.summary(try await body(of: summaryURL)) }
    func incident(_ id: String) async throws -> DecodedIncident { try StatusDecoding.incident(try await body(of: incidentURL(id))) }
    func feed() async throws -> [RSSItem] { try StatusDecoding.rss(try await body(of: feedURL)) }

    private func body(of url: URL) async throws -> Data {
        let (data, response) = try await transport.get(url)
        guard (200..<300).contains(response.statusCode) else { throw StatusError.httpStatus(response.statusCode) }
        return data
    }
}
