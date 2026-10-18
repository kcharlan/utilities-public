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
