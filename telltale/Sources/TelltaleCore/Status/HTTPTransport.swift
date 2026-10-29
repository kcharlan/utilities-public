import Foundation

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

extension HTTPTransport {
    public func body(of url: URL) async throws -> Data {
        let (data, response) = try await get(url)
        guard (200..<300).contains(response.statusCode) else { throw StatusError.httpStatus(response.statusCode) }
        return data
    }
}
