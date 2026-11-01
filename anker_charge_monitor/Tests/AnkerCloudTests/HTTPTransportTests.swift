import Foundation
import Testing
@testable import AnkerCloud

private final class RedirectProtocol: URLProtocol, @unchecked Sendable {
    override class func canInit(with request: URLRequest) -> Bool { request.url?.host?.hasSuffix("synthetic.invalid") == true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let url = request.url!
        if url.path.hasPrefix("/start") {
            let destination = URL(string: url.path == "/start-cross" ? "https://other.synthetic.invalid/target" : (url.path == "/start-same" ? "https://synthetic.invalid/target" : "http://synthetic.invalid/target"))!
            let response = HTTPURLResponse(url: url, statusCode: 302, httpVersion: nil, headerFields: ["Location": destination.absoluteString])!
            client?.urlProtocol(self, wasRedirectedTo: URLRequest(url: destination), redirectResponse: response)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocolDidFinishLoading(self)
        } else {
            let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: nil)!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocolDidFinishLoading(self)
        }
    }
    override func stopLoading() {}
}

@Test func authenticatedTransportOnlyFollowsSameOriginHTTPS() async throws {
    let transport = URLSessionTransport(protocolClasses: [RedirectProtocol.self])
    for (path, expected) in [("start-cross", 302), ("start-same", 200)] {
        var request = URLRequest(url: URL(string: "https://synthetic.invalid/\(path)")!)
        request.setValue("synthetic-token", forHTTPHeaderField: "X-Auth-Token")
        let (_, response) = try await transport.send(request)
        #expect(response.statusCode == expected)
    }
}

@Test func authenticatedTransportRejectsInsecureRedirect() async throws {
    var request = URLRequest(url: URL(string: "https://synthetic.invalid/start")!)
    request.setValue("synthetic-token", forHTTPHeaderField: "X-Auth-Token")
    let (_, response) = try await URLSessionTransport(protocolClasses: [RedirectProtocol.self]).send(request)
    #expect(response.statusCode == 302)
}
