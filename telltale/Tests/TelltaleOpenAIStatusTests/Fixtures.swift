import Foundation
import TelltaleOpenAIStatus

/// Loads the hand-written synthetic fixtures and fakes the network.
enum Fixtures {
    static func data(_ name: String) throws -> Data {
        guard let url = Bundle.module.resourceURL?.appending(path: "Fixtures/\(name)") else {
            throw CocoaError(.fileNoSuchFile)
        }
        return try Data(contentsOf: url)
    }

    static func date(_ iso: String) -> Date {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: iso) { return date }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: iso)!
    }
}

/// A transport that answers from a table keyed by URL path and records every request.
actor FakeTransport: HTTPTransport {
    enum Answer: Sendable {
        case body(Data, status: Int = 200)
        case failure
    }

    struct Offline: Error {}

    private var answers: [String: Answer]
    private(set) var requests: [URL] = []

    init(_ answers: [String: Answer]) { self.answers = answers }

    func get(_ url: URL) async throws -> (Data, HTTPURLResponse) {
        requests.append(url)
        switch answers[url.path] ?? .failure {
        case .failure:
            throw Offline()
        case .body(let data, let status):
            return (data, HTTPURLResponse(url: url, statusCode: status, httpVersion: "HTTP/1.1", headerFields: nil)!)
        }
    }

    var paths: [String] { requests.map(\.path) }
}

enum Paths {
    static let summary = "/proxy/status.openai.com"
    static func detail(_ id: String) -> String { "/proxy/status.openai.com/incidents/\(id)" }
    static let feed = "/feed.rss"
}
