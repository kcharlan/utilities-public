import Foundation

public protocol HTTPTransport: Sendable {
    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse)
}

/// Total timeout from anker-solix-api `apitypes.py`, REQUEST_TIMEOUT_DEF,
/// and `session.py`, request, commit 8a5222b.
public struct URLSessionTransport: HTTPTransport {
    private let urlSession: URLSession

    public init() {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 10
        configuration.timeoutIntervalForResource = 10
        configuration.httpCookieStorage = nil
        configuration.urlCache = nil
        urlSession = URLSession(configuration: configuration)
    }

    public func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let (data, response) = try await urlSession.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw AnkerError.malformed }
        return (data, response)
    }
}
