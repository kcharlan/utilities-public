import Foundation
import Testing
@testable import BrewVersionCore

final class SyntheticURLProtocol: URLProtocol, @unchecked Sendable {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let url = request.url!
        if url.path == "/redirect" {
            let response = HTTPURLResponse(url: url, statusCode: 301, httpVersion: nil, headerFields: ["Location": "http://example.invalid/x"])!
            client?.urlProtocol(self, wasRedirectedTo: URLRequest(url: URL(string: "http://example.invalid/x")!), redirectResponse: response)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocolDidFinishLoading(self)
        } else {
            let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: ["ETag": "synthetic-response"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: Data((request.value(forHTTPHeaderField: "If-None-Match") ?? "absent").utf8))
            client?.urlProtocolDidFinishLoading(self)
        }
    }
    override func stopLoading() {}
}

struct TransportTests {
    func transport() -> URLSessionTransport {
        URLSessionTransport(requestTimeout: 7, resourceTimeout: 19, protocolClasses: [SyntheticURLProtocol.self])
    }

    @Test func refusesHTTPRedirect() async throws {
        let response = try await transport().get(URL(string: "https://example.invalid/redirect")!, ifNoneMatch: nil)
        #expect(response.status == 301)
    }

    @Test func rejectsNonHTTPSURL() async {
        await #expect(throws: (any Error).self) {
            try await transport().get(URL(string: "http://example.invalid")!, ifNoneMatch: nil)
        }
    }

    @Test func sendsIfNoneMatch() async throws {
        let response = try await transport().get(URL(string: "https://example.invalid/header")!, ifNoneMatch: "synthetic-request")
        #expect(response.status == 200)
        #expect(String(decoding: response.body, as: UTF8.self) == "synthetic-request")
        #expect(response.etag == "synthetic-response")
    }

    @Test func noURLCache() {
        #expect(transport().configuration.urlCache == nil)
        #expect(transport().configuration.requestCachePolicy == .reloadIgnoringLocalCacheData)
    }

    @Test func timeoutPolicy() {
        // Idle timeout: https://developer.apple.com/documentation/foundation/urlsessionconfiguration/timeoutintervalforrequest
        // Total timeout: https://developer.apple.com/documentation/foundation/urlsessionconfiguration/timeoutintervalforresource
        #expect(transport().configuration.timeoutIntervalForRequest == 7)
        #expect(transport().configuration.timeoutIntervalForResource == 19)
        #expect(URLSessionTransport.standard().configuration.timeoutIntervalForRequest == 10)
        #expect(URLSessionTransport.standard().configuration.timeoutIntervalForResource == 30)
    }
}

private final class EventRecorder: EventLogging, @unchecked Sendable {
    private let lock = NSLock()
    private var entries: [(String, [String: LogValue])] = []
    func record(_ event: String, _ fields: [String: LogValue]) { lock.withLock { entries.append((event, fields)) } }
    var recorded: [(String, [String: LogValue])] { lock.withLock { entries } }
}
private struct FixedTransport: HTTPTransport {
    let result: Result<HTTPResponse, URLError>
    func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse { try result.get() }
}

extension TransportTests {
    @Test func loggingTransportRecordsResponsesAndErrorsButSkips304() async throws {
        let log = EventRecorder(), url = URL(string: "https://example.invalid/synthetic")!
        let response = HTTPResponse(status: 200, body: Data("synthetic".utf8), etag: "synthetic", headers: ["last-modified": "synthetic-date"])
        let returned = try await LoggingTransport(FixedTransport(result: .success(response)), log: log).get(url, ifNoneMatch: nil)
        #expect(returned.body == response.body && returned.headers == response.headers)
        _ = try await LoggingTransport(FixedTransport(result: .success(HTTPResponse(status: 304, body: Data()))), log: log).get(url, ifNoneMatch: nil)
        await #expect(throws: URLError.self) { try await LoggingTransport(FixedTransport(result: .failure(URLError(.timedOut))), log: log).get(url, ifNoneMatch: nil) }
        #expect(log.recorded.map(\.0) == ["http", "http"])
        #expect(log.recorded[0].1["lastModified"] == .string("synthetic-date"))
        #expect(log.recorded[1].1["error"] != nil)
    }
}
